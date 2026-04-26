"""
CommPlex GCP-Native Voice + SMS Handler
File: CommPlexAPI/server/routes/gcp_voice_sms.py

Replaces Bland.ai entirely. Uses:
  - Twilio for telephony/SMS transport (no Bland needed)
  - GCP STT (Speech-to-Text) for live call transcription  
  - Gemini Flash via Vertex for response generation
  - GCP TTS (Text-to-Speech) for voice output
  - Firestore for session persistence
  - Cloud Run as the orchestration layer

Architecture:
  Inbound call  → Twilio → /voice/twiml → TwiML <Gather> loop → Gemini → TTS → audio back
  Inbound SMS   → Twilio → /webhook/sms → Gemini → SMS reply
  Outbound SMS  → Cloud Run → Twilio API → dealer list
  Outbound call → Cloud Run → Twilio API → Gemini conversation

Cost estimate (GCP free tier + $1,300 credits):
  STT: $0.016/min → 1,000 calls × 3min = $48
  TTS: $0.000016/char → ~$5/month at current volume
  Gemini Flash: $0.001/call → $1/1,000 calls
  Firestore: free tier covers this volume
  Total: well under $100/month

Deploy: replace sms_intake.py imports in main.py with this module
"""

import os
import json
import re
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Request, Form, BackgroundTasks
from fastapi.responses import PlainTextResponse, Response
from twilio.twiml.messaging_response import MessagingResponse
from twilio.twiml.voice_response import VoiceResponse, Gather, Say, Hangup

from google import genai
from google.genai.types import HttpOptions, GenerateContentConfig
from google.cloud import firestore, texttospeech

router = APIRouter()

# ── GCP INIT ─────────────────────────────────────────────────────────────────

PROJECT_ID = os.getenv("GCP_PROJECT_ID", "commplex-493805")
REGION     = os.getenv("GCP_REGION", "us-central1")

try:
    if os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower() == "true":
        _client = genai.Client(project=PROJECT_ID, location=REGION)
    else:
        _client = genai.Client(http_options=HttpOptions(api_version="v1"))
except Exception as _e:
    import sys; print(f"WARN: Gemini init: {_e}", file=sys.stderr)
    _client = None
try:
    _db = firestore.Client(project=PROJECT_ID)
except Exception as _e:
    import sys; print(f"WARN: Firestore init: {_e}", file=sys.stderr)
    _db = None
try:
    _tts = texttospeech.TextToSpeechClient()
except Exception as _e:
    import sys; print(f"WARN: TTS init: {_e}", file=sys.stderr)
    _tts = None



def lookup_caller(phone: str) -> dict:
    """
    Look up a caller by phone number across dealers, contacts, and leads.
    Returns enriched context dict injected into Audry's system prompt.
    """
    try:
        digits = re.sub(r"[^\d]", "", phone)
        db = _firestore()

        # Check dealers collection
        for doc in db.collection("dealers").stream():
            d = doc.to_dict()
            if re.sub(r"[^\d]", "", d.get("phone","")) == digits:
                return {
                    "known": True,
                    "type": "dealer",
                    "company": d.get("company",""),
                    "contact_name": d.get("contact_name",""),
                    "vehicle_interest": d.get("vehicle_interest",""),
                    "tier": d.get("tier",""),
                    "notes": d.get("notes",""),
                    "priority": d.get("priority", 99),
                }

        # Check contacts collection
        for doc in db.collection("contacts").stream():
            d = doc.to_dict()
            if re.sub(r"[^\d]", "", d.get("phone","")) == digits:
                return {
                    "known": True,
                    "type": d.get("source","contact"),
                    "company": d.get("company",""),
                    "contact_name": d.get("contact_name",""),
                    "vehicle_interest": d.get("vehicle",""),
                    "campaign": d.get("campaign",""),
                    "notes": d.get("notes",""),
                    "priority": d.get("priority","NORMAL"),
                }

        # Check leads — returning caller?
        leads = list(db.collection("leads")
                     .where("phone", "==", phone)
                     .order_by("ts", direction="DESCENDING")
                     .limit(3).stream())
        if leads:
            last = leads[0].to_dict()
            return {
                "known": True,
                "type": "returning_lead",
                "company": "",
                "contact_name": "",
                "vehicle_interest": last.get("message","")[:100],
                "notes": f"Previously asked: {last.get('message','')}",
                "priority": "WARM",
            }

    except Exception as e:
        print(f"[lookup_caller] {e}")

    return {"known": False, "type": "unknown", "company": "", "notes": ""}


def build_caller_context(caller_info: dict) -> str:
    """Build a short context string injected into Audry's prompt."""
    if not caller_info.get("known"):
        return ""
    lines = ["\n\n[CALLER CONTEXT — use this to personalize your response]"]
    if caller_info.get("company"):
        lines.append(f"  Caller is from: {caller_info['company']}")
    if caller_info.get("contact_name"):
        lines.append(f"  Contact name: {caller_info['contact_name']}")
    if caller_info.get("vehicle_interest"):
        lines.append(f"  Vehicle interest: {caller_info['vehicle_interest']}")
    if caller_info.get("tier"):
        lines.append(f"  Dealer tier: {caller_info['tier']}")
    if caller_info.get("notes"):
        lines.append(f"  Notes: {caller_info['notes']}")
    if caller_info.get("type") == "bat_partners":
        lines.append("  This is a BaT/auction partner — use BaT partner script.")
    if caller_info.get("type") == "returning_lead":
        lines.append("  This caller has contacted us before — acknowledge warmly.")
    lines.append("[END CALLER CONTEXT]")
    return "\n".join(lines)


def log_lead(phone: str, channel: str, message: str, reply: str):
    """Log inbound contact to Firestore for lead tracking."""
    try:
        if _db is None:
            return
        from datetime import datetime, timezone
        doc = {
            "phone": phone,
            "channel": channel,
            "message": message[:200],
            "reply": reply[:200],
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        _db.collection("leads").add(doc)
    except Exception as e:
        print(f"WARN: lead log failed: {e}", flush=True)

# ── AUDRY SYSTEM PROMPT ───────────────────────────────────────────────────────

AUDRY_SYSTEM = """===== AutoBäad | Audry Harper | Vehicle Sales Agent: PERSONA GLOBAL PROMPT v3 =====

You are Audry Harper, the AI sales representative and inbound call handler for AutoBäad — Kenyon Jones's private vehicle liquidation operation out of Hazen, North Dakota. You handle BOTH inbound and outbound calls.

AutoBäad (pronounced "Auto-Baad") — Badlands of ND/SD + baud (fast signal) + baad (vehicles that are a little rough around the edges but ready to move). The umlaut nods to Northern Plains German/Scandinavian roots. AutoBäad is NOT a dealership — Kenyon Jones is selling his own vehicles directly.

THE TEAM:
  Kenyon Jones — owner. Handles all offers, price decisions, closing.
    (701) 870-5235 | kjonesmle@gmail.com | 218 1st Ave NW #347, Hazen ND 58545
  Cynthia Ennis — authorized rep. Live calls and warm follow-ups.
    (701) 946-5731 | thia@shy2shy.com
  Charles Perrine — outreach, email, Slydialer, form submissions. (701) 870-5448
  Sherrie Appleby — on-site coordinator, Douglasville GA 30134.

THE 4 VEHICLES:

=== 2006 Ford F-350 Super Duty King Ranch ===
VIN: 1FTWW31Y86EA12357 | ~47,000 actual miles — top 5% surviving for year/model
Engine: 6.8L Triton V10 Gas — NO DEF, NO diesel complexity, NO injector risk
Trans: 6-Speed SelectShift | Drive: 4x4 Selectable | Cab: Crew Cab 4-Door / Long Bed 8ft / Factory Bed Cap
Trim: King Ranch — Castaño saddle leather (untreated, bright — collector-preferred), heated captain's seats, King Ranch medallion, wood-grain
Tow Package: Factory 5th Wheel Kingpin Hitch pre-wired — rated ~18,000 lbs GCWR
Title: Clean Georgia Title — Zero Liens
Location: Douglasville GA — Sherrie Appleby on-site
Staging: needs professional detail, basic V10 service, tire DOT check, photo shoot. NOT listing-ready yet.
Asking: $24,000–$32,000 | BaT/Mecum reserve: $24,000
Packet: https://tinyurl.com/Ford-KR-F350V10-ExtBedCab
HOOK: Truck and Jayco on SAME GA lot — transport partner can drive truck and tow camper in ONE trip.

=== 2017 Jayco Eagle HT 26.5BHS Fifth Wheel ===
VIN: 1UJCJ0BPXH1P20237 | ~2,400 actual tow miles — essentially factory-fresh
GVWR: 9,950 lbs | Half-ton towable (F-150 compatible)
Four-Season: Jayco Climate Shield — rated to 0°F — PEX plumbing — heated underbelly
Floorplan: Rear bunkhouse — double-over-double bunks — sleeps 8–10
Systems: Lippert auto-level, MORryde CRE-3000, electric awning w/LED, 15K BTU A/C, high-BTU furnace, gas/electric water heater
Condition: Extra Clean 9/10 — NO water damage, smoke, pets, or odors
Title: Clean Georgia Title — Zero Liens
Location: Douglasville GA — same lot as F-350
Disclosed items (all priced in, ~$950–$1,200 total):
  - Tires: 2017 DOT codes, age-recommend replacement (~$600–$800)
  - Underbelly: one localized coroplast repair, frame unaffected (~$293)
  - Lippert rear jacks disengaged — manual override works, slide fully operational
  - One cabinet hinge needs re-hanging (~$50)
Asking: $24,000–$32,000
Packet: https://tinyurl.com/Jayco-Eagle-BHS-26p5-HT-2017

=== 2016 Lincoln MKZ Hybrid ===
VIN: 3LN6L2LUXGR630397 | ~100,000 miles
Engine: 2.0L Hybrid CVT — 41 MPG city / 39 MPG hwy — hybrid drivetrain FULLY OPERATIONAL
Interior: Premium Fabric / Miko Suede — 8" SYNC 3 touchscreen — backup camera
Color: Ingot Silver Metallic — warm medium gray (NOT champagne, NOT beige, NOT battleship gray)
TITLE: BILL OF SALE ONLY — NO TITLE IN HAND.
  Original title retained by shipper when transported to ND. Original seller uncooperative.
  Kenyon has Bill of Sale. Vehicle in ND 13+ months.
  ND Bonded Title application is next step — NOT filed yet. Car must run first for DMV inspection.
  ALWAYS disclose proactively. Target: flippers, dealers comfortable with Bill of Sale. NOT for buyers expecting clean title.
Battery: 12V AGM auxiliary battery is dead from sitting (~$150–$200 fix at Lucky's or any Beulah shop).
  This is NOT the high-voltage hybrid pack. Hybrid drivetrain unaffected.
Location: Lucky's Towing & Repair, Beulah ND — direct lot pickup
  Tow to Mandan/Bismarck/Dickinson (~$900) for right deal. Williston/Minot: buyer pickup, no transport cost.
Asking: $4,000–$12,000 (adjusted for title situation) — Kenyon sets final number
Packet: https://tinyurl.com/MKZ-2016-Hybrid-Rebuild-100k
WARM LEAD: Royal Drive Autos (royaldriveautos.com) opened MKZ email 5 times — HIGHEST PRIORITY. Reply to same thread.

=== 1988 Lincoln Town Car Signature ===
VIN: 1LNBM82FXJY779113 | 31,511 actual miles — extraordinary time capsule
Engine: 5.0L Windsor V8 | Trim: Signature Series
Color: Oxford White exterior / Navy Blue Windsor Velour interior
  Windsor Velour stays soft — does NOT crack like leather — collector premium
NO AIRBAGS — 1988 Town Car predates airbags. Lincoln added them in 1990. Do NOT check airbag boxes on intake forms.
Title: Clean North Dakota Title
Location: Hazen ND — Kenyon can arrange viewing or drive to buyer
  AJ at Ideal Auto Minot: ~75 min north | Eide Ford Mandan: ~70 min south
Asking: $8,000–$16,000 | BaT/Mecum reserve: $8,000
Packet: https://tinyurl.com/Lincoln-Town-Car-1988-Sig
ND HOOK: Town Car (Hazen) + MKZ Hybrid (Beulah) = 2-car carrier deal from western ND in one trip.

INBOUND GREETING:
"Thank you for calling — this is Audry, assistant to Kenyon Jones at AutoBäad.
Are you calling back about one of our vehicle listings or a logistics partnership?"

QUALIFY: Ask which vehicle — Town Car (ND), F-350 (GA), Jayco (GA), or MKZ Hybrid (ND).

BaT PARTNER NETWORK (HIGH PRIORITY inbound callers):
ND Package: Millrace Motor Club MN, Motive Archive Chicago, Conquest Classic Cars CO, Hyman LTD St Louis, Vantage Auto NJ (TOP for Town Car), Vanguard Motor Sales MI, Vintique Motors MI
GA Package: RK Motors Charlotte, Bullet Motorsports FL, HCC Specialty Cars TX, Specialty Cars Trucks Hayden ID, WOB CARS LA
Both: Compass Racing/Karl Thomson CA, Gateway Classic Cars (Allan Wiesing 623-900-4884, Tim Johnson 602-796-8534)
Active Local: Corral Sales Mandan 701-663-9538 (Jayco primary), AJ Ideal Auto Minot 701-380-4166 (both Lincolns), Steve Schumacher Eide Ford 701-380-8110

NEGOTIATION RULES:
- NEVER name specific competitors or their exact offers
- Use HINTING: "We're seeing consignment splits as low as 15% for survivor-grade vehicles in this class"
- NEVER say "Kenyon will accept X" or any price commitment
- When asked bottom line: "Kenyon reviews the offer leaderboard each evening and personally calls back the strongest partners. What's the best callback number for him?"
- Log ALL offers, terms, splits, transport quotes to Firestore immediately

PACKAGE DEAL SCRIPTS:
ND Package: "Town Car is a 31,511-mile Oxford White time capsule in Hazen. We're structuring a 2-car carrier incentive — the 2016 MKZ is in Beulah nearby. One carrier pulls both Lincolns in a single run. Build the transport into consignment terms, you get the Town Car listing."
GA Package: "King Ranch is a 47k-mile V10 survivor — factory 5th wheel already in, no diesel headaches. Same lot as a 2017 Jayco Eagle HT with 2,400 miles. Your driver can literally drive the truck and tow the camper out in one trip. We want a transport-included partner who takes both."

CALL WRAP-UP: "Kenyon reviews all terms this evening and personally calls back the strongest partners. I'm texting you the sales packet link right now. Is [their number] the best for his callback?"

TinyURLs:
  Town Car: https://tinyurl.com/Lincoln-Town-Car-1988-Sig
  F-350: https://tinyurl.com/Ford-KR-F350V10-ExtBedCab
  Jayco: https://tinyurl.com/Jayco-Eagle-BHS-26p5-HT-2017
  MKZ: https://tinyurl.com/MKZ-2016-Hybrid-Rebuild-100k

=== END PERSONA: AUDRY HARPER / AutoBäad v3 ===

KNOWLEDGE BASE HIGHLIGHTS:
[OBJECTION HANDLING]
  - Price too high: Direct to sales packet comps. All disclosed items are factored in. Escalate offers to Kenyon.
  - Rebuilt/no title (MKZ): Full transparency — Bill of Sale only. ND Bonded Title path. Priced to reflect. Not for clean-title buyers.
  - Never heard of AutoBäad: Kenyon Jones selling his own vehicles directly. No middleman. Real, titled, verified.
  - Need to think about it: Send packet, offer callback in 24-48h. No pressure.

[OUTREACH SEQUENCE]
  Touch 1: Email (Charles, Day 1) → Touch 2: Slydialer voicemail (Day 3) → Touch 3: Live call warm leads only (Cynthia, Day 5-6) → Touch 4: Kenyon closing call on positive signal
  Exception: Corral Sales gets live call Day 1.

[VOICEMAIL SCRIPT]
  75-second message. State name (Audry, for Kenyon Jones), specific vehicle + one compelling fact, asking price range, packet URL, two callback numbers: Kenyon (701) 870-5235 and Cynthia (701) 946-5731.

[MARKET COMPS]
  F-350: Gas V10 comps cleared $31,250 on BaT (26k-mile 2000 F-250). Specialist dealers list comparable at $32k-$38k retail.
  Jayco: Original MSRP $40,285. New 2025 Eagle HT lists $44k+. Zero competing 26.5BHS in ND currently.
  Town Car: BaT + Mecum both reach collector audiences. MI has deep Lincoln collector culture.
"""

# ── FIRESTORE SESSION ─────────────────────────────────────────────────────────

def get_session(phone: str) -> dict:
    doc = _db.collection("sms_sessions").document(phone).get()
    if doc.exists:
        return doc.to_dict()
    return {"phone": phone, "history": [], "state": "new", "data": {}}

def save_session(phone: str, session: dict):
    session["updated_at"] = datetime.now(timezone.utc).isoformat()
    _db.collection("sms_sessions").document(phone).set(session)

def get_call_session(call_sid: str) -> dict:
    doc = _db.collection("call_sessions").document(call_sid).get()
    if doc.exists:
        return doc.to_dict()
    return {"call_sid": call_sid, "history": [], "turn": 0}

def save_call_session(call_sid: str, session: dict):
    session["updated_at"] = datetime.now(timezone.utc).isoformat()
    _db.collection("call_sessions").document(call_sid).set(session)

# ── GEMINI RESPONSE ───────────────────────────────────────────────────────────

def gemini_respond(user_msg: str, history: list, channel: str = "sms", caller_context: str = "") -> str:
    """
    Generate Audry's response using Gemini Flash.
    history: list of {"role": "user"|"model", "parts": [str]}
    """
    # Build conversation history for Gemini
    contents = []
    for turn in history[-10:]:  # Keep last 10 turns to stay within context
        contents.append({"role": turn["role"], "parts": [{"text": turn["parts"][0]}]})
    contents.append({"role": "user", "parts": [{"text": user_msg}]})

    channel_note = ""
    if channel == "sms":
        channel_note = "\n\nIMPORTANT: This is SMS. Respond in ONE complete sentence under 160 characters. Never cut off mid-sentence. Be direct and finish your thought."
    elif channel == "voice":
        channel_note = "\n\nIMPORTANT: This is a phone call. Give exactly 1-2 SHORT complete sentences. Never list items with numbers. Speak conversationally. End with one question."
    elif channel == "web":
        channel_note = "\n\nIMPORTANT: This is a web chat. Give complete, helpful responses of 3-5 sentences. Include all relevant vehicle details. Do not truncate."

    system = AUDRY_SYSTEM + channel_note + caller_context

    try:
        response = _client.models.generate_content(
            model="gemini-2.5-flash",
            contents=contents,
            config=GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=1500 if channel == "sms" else (400 if channel == "voice" else 2000),
                temperature=0.4,
            )
        )
        return response.text.strip()
    except Exception as e:
        if channel == "sms":
            return "Thanks for reaching out to AutoBäad. Kenyon will follow up shortly. (866) 736-2349"
        return "Thanks for calling AutoBäad. Kenyon will follow up with you shortly."

# ── GCP TTS ───────────────────────────────────────────────────────────────────

def text_to_speech_url(text: str, call_sid: str) -> str:
    """
    Convert text to speech using GCP TTS, store in GCS, return public URL.
    For now, returns None to fall back to Twilio <Say> — implement GCS upload when needed.
    """
    # TODO: Synthesize audio, upload to GCS bucket, return public URL
    # synthesis_input = texttospeech.SynthesisInput(text=text)
    # voice = texttospeech.VoiceSelectionParams(
    #     language_code="en-US",
    #     name="en-US-Journey-F",  # Natural female voice
    #     ssml_gender=texttospeech.SsmlVoiceGender.FEMALE
    # )
    # audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)
    # response = _tts.synthesize_speech(input=synthesis_input, voice=voice, audio_config=audio_config)
    # ... upload to GCS, return signed URL
    return None  # Falls back to Twilio <Say> until GCS is configured

# ── INBOUND SMS ───────────────────────────────────────────────────────────────

@router.post("/webhook/sms")
async def handle_sms(request: Request):
    """
    Inbound SMS from Twilio. Routes through Gemini for Audry's response.
    Uses Firestore for conversation history persistence.
    """
    form = await request.form()
    from_number = form.get("From", "")
    body        = form.get("Body", "").strip()
    
    if not from_number or not body:
        return PlainTextResponse("", status_code=200)
    
    # Load session
    session = get_session(from_number)
    history = session.get("history", [])
    
    # Look up caller and generate Audry's response
    caller_info = lookup_caller(from_number)
    caller_ctx = build_caller_context(caller_info)
    reply = gemini_respond(body, history, channel="sms", caller_context=caller_ctx)
    # Tag lead with caller info
    if caller_info.get("known"):
        session["caller_company"] = caller_info.get("company","")
        session["caller_type"] = caller_info.get("type","")
    
    # Update history
    history.append({"role": "user", "parts": [body]})
    history.append({"role": "model", "parts": [reply]})
    session["history"] = history[-20:]  # Keep last 20 turns
    session["last_message"] = body
    session["last_reply"] = reply
    save_session(from_number, session)
    
    # Send reply via Twilio TwiML
    resp = MessagingResponse()
    if len(reply) <= 1550:
        resp.message(reply)
    else:
        for chunk in [reply[i:i+1550] for i in range(0, len(reply), 1550)]:
            resp.message(chunk)
    log_lead(from_number, "sms", body, reply)
    return PlainTextResponse(str(resp), media_type="text/xml")

# ── INBOUND VOICE (Gather Loop) ───────────────────────────────────────────────

@router.post("/voice/twiml")
async def handle_voice_inbound(request: Request):
    """
    Inbound call from Twilio. Returns TwiML with <Gather> to capture speech.
    Uses Twilio's built-in STT (speechResult) to transcribe caller speech,
    feeds to Gemini, returns Audry's spoken response via <Say>.
    
    For higher quality: swap <Say> for GCP TTS audio URL via <Play>.
    """
    form = await request.form()
    call_sid = form.get("CallSid", "")
    
    resp = VoiceResponse()
    gather = Gather(
        input="speech",
        action="/voice/respond",
        method="POST",
        timeout=5,
        speech_timeout="auto",
        language="en-US"
    )
    # Opening greeting
    gather.say(
        "Thank you for calling Auto-Bad. This is Aw-dree. "
        "I can tell you about our vehicles or connect you with Kenyon. How can I help you today?",
        voice="Polly.Joanna",  # AWS Polly via Twilio — sounds natural, no extra cost
    )
    resp.append(gather)
    # Fallback if no speech detected
    resp.redirect("/voice/twiml", method="POST")
    
    return Response(content=str(resp), media_type="text/xml")


@router.post("/voice/respond")
async def handle_voice_respond(request: Request):
    """
    Receives transcribed speech from Twilio <Gather>, generates Gemini response,
    speaks it back, then loops for next turn.
    """
    form = await request.form()
    call_sid     = form.get("CallSid", "")
    speech_input = form.get("SpeechResult", "").strip()
    confidence   = float(form.get("Confidence", "0"))
    
    resp = VoiceResponse()
    
    if not speech_input or confidence < 0.3:
        # Didn't catch it — ask again
        gather = Gather(input="speech", action="/voice/respond", method="POST", timeout=5)
        gather.say("I didn't quite catch that — could you say that again?", voice="Polly.Joanna")
        resp.append(gather)
        resp.redirect("/voice/twiml", method="POST")
        return Response(content=str(resp), media_type="text/xml")
    
    # Load call session
    session = get_call_session(call_sid)
    history = session.get("history", [])
    
    # Generate Audry's response — wrapped so interrupt/crash never kills call
    try:
        audry_reply = gemini_respond(speech_input, history, channel="voice")
    except Exception as e:
        print(f"[voice error] {e}")
        audry_reply = "I didn't catch that clearly. What vehicle can I tell you about?"
    
    # Update history
    history.append({"role": "user", "parts": [speech_input]})
    history.append({"role": "model", "parts": [audry_reply]})
    session["history"] = history[-20:]
    session["turn"] = session.get("turn", 0) + 1
    save_call_session(call_sid, session)
    
    # Check if we should transfer to Kenyon
    transfer_signals = ["transfer to kenyon", "connecting you to kenyon", "putting you through to kenyon", "transferring you now"]
    if any(sig in audry_reply.lower() for sig in transfer_signals):
        resp.say(audry_reply, voice="Polly.Joanna")
        resp.dial("+17018705235")  # Kenyon's number
        return Response(content=str(resp), media_type="text/xml")
    
    # Check for hangup signals
    goodbye = ["goodbye", "take care", "have a great", "thanks for calling"]
    if any(sig in audry_reply.lower() for sig in goodbye):
        resp.say(audry_reply, voice="Polly.Joanna")
        resp.hangup()
        return Response(content=str(resp), media_type="text/xml")
    
    # Continue conversation loop
    gather = Gather(
        input="speech",
        action="/voice/respond",
        method="POST",
        timeout=5,
        speech_timeout="auto",
        language="en-US"
    )
    gather.say(audry_reply, voice="Polly.Joanna")
    resp.append(gather)
    resp.redirect("/voice/twiml", method="POST")
    
    return Response(content=str(resp), media_type="text/xml")


# ── OUTBOUND CALL (Gemini-initiated) ─────────────────────────────────────────

@router.post("/voice/outbound/start")
async def handle_outbound_call_answer(request: Request):
    """
    TwiML served when an outbound call is answered.
    Audry introduces herself and starts the conversation loop.
    """
    form = await request.form()
    call_sid = form.get("CallSid", "")
    to_number = form.get("To", "")
    
    resp = VoiceResponse()
    gather = Gather(
        input="speech",
        action="/voice/respond",
        method="POST",
        timeout=8,
        speech_timeout="auto",
        language="en-US"
    )
    gather.say(
        "Hi, this is Aw-dree with Auto-Bad — I'm following up on behalf of Kenyon Jones "
        "about our vehicle listings. Do you have a moment?",
        voice="Polly.Joanna"
    )
    resp.append(gather)
    resp.hangup()
    
    return Response(content=str(resp), media_type="text/xml")


# ── OUTBOUND SMS ──────────────────────────────────────────────────────────────

def send_outbound_sms(to: str, body: str) -> dict:
    """
    Send an outbound SMS via Twilio API.
    Used by sms_drafter / batch campaign runner.
    """
    import httpx, base64
    
    sid   = os.getenv("TWILIO_ACCOUNT_SID", "")
    token = os.getenv("TWILIO_AUTH_TOKEN", "")
    from_ = os.getenv("TWILIO_FROM_NUMBER", "+18667362349")
    
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
    
    try:
        r = httpx.post(url, data={"From": from_, "To": to, "Body": body},
                       headers={"Authorization": f"Basic {auth}"}, timeout=10)
        return r.json()
    except Exception as e:
        return {"error": str(e)}



# ── WEB CHAT ENDPOINT ────────────────────────────────────────────────────────

from pydantic import BaseModel

class WebChatRequest(BaseModel):
    message: str
    history: list = []
    agent: str = "audry"

@router.post("/chat/web")
async def handle_web_chat(payload: WebChatRequest):
    """Web widget endpoint — used by autobad_demo.html and any web UI."""
    try:
        history = [
            {"role": m.get("role", "user"), "parts": [m.get("content", "")]}
            for m in payload.history[-10:]
        ]
        reply = gemini_respond(payload.message, history, channel="web")
        log_lead(payload.dict().get("phone","web"), "web", payload.message, reply)
        return {"status": "ok", "reply": reply}
    except Exception as e:
        return {
            "status": "error",
            "reply": "Thanks for reaching out to AutoBäad! Text or call (866) 736-2349 to connect with Kenyon.",
        }


# ── DEBUG ─────────────────────────────────────────────────────────────────────

@router.get("/debug/gemini")
async def debug_gemini():
    """Quick smoke test for Gemini connectivity."""
    import traceback
    try:
        response = _client.models.generate_content(
            model="gemini-2.5-flash",
            contents="Say hello from AutoBäad in one sentence.",
        )
        return {"status": "ok", "response": response.text}
    except Exception as e:
        return {"status": "error", "error": str(e), "trace": traceback.format_exc()}


# ── HEALTH CHECK ──────────────────────────────────────────────────────────────

@router.get("/health/gcp")
async def health_gcp():
    """Verify GCP services are reachable."""
    status = {"gemini": False, "firestore": False, "tts": False}
    try:
        _client.models.generate_content(model="gemini-2.5-flash", contents="ping")
        status["gemini"] = True
    except Exception as e:
        status["gemini_error"] = str(e)
    try:
        _db.collection("health").document("ping").set({"ts": datetime.now().isoformat()})
        status["firestore"] = True
    except Exception as e:
        status["firestore_error"] = str(e)
    try:
        _tts.list_voices(language_code="en-US")
        status["tts"] = True
    except Exception as e:
        status["tts_error"] = str(e)
    return status
