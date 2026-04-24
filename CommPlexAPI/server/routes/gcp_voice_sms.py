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

import vertexai
from vertexai.generative_models import GenerativeModel, Part
from google.cloud import firestore, texttospeech, speech_v1
from google.cloud import secretmanager

router = APIRouter()

# ── GCP INIT ─────────────────────────────────────────────────────────────────

PROJECT_ID = os.getenv("GCP_PROJECT_ID", "commplex-493805")
REGION     = os.getenv("GCP_REGION", "us-central1")

vertexai.init(project=PROJECT_ID, location=REGION)
_gemini = GenerativeModel("gemini-2.0-flash")
_db     = firestore.Client(project=PROJECT_ID)
_tts    = texttospeech.TextToSpeechClient()

# ── AUDRY SYSTEM PROMPT ───────────────────────────────────────────────────────

AUDRY_SYSTEM = """You are Audry Harper, AI sales representative for AutoBäad — Kenyon Jones's private vehicle liquidation operation out of Hazen, North Dakota.

THE 4 VEHICLES:

1. 2006 F-350 King Ranch — VIN 1FTWW31Y86EA12357
   47,000 actual miles | 6.8L Triton V10 Gas (NO diesel) | 4x4 | Crew Cab / Long Bed
   Factory 5th Wheel Kingpin Hitch pre-wired, rated ~18,000 lbs GCWR
   Castaño saddle leather | Clean Georgia Title | Douglasville GA (Sherrie Appleby on-site)
   Staging needed: detail, V10 service, tire check, photos — not listing-ready yet
   Asking: $24,000–$32,000 | BaT/Mecum reserve: $24,000
   Packet: tinyurl.com/Ford-KR-F350V10-ExtBedCab
   HOOK: Same GA lot as Jayco — truck can tow camper out in one trip

2. 2017 Jayco Eagle HT 26.5BHS — VIN 1UJCJ0BPXH1P20237
   2,400 actual tow miles | 4-season Climate Shield (rated to 0°F) | Half-ton towable
   Rear bunkhouse sleeps 8-10 | MORryde CRE-3000 | Lippert auto-level
   Clean Georgia Title | Douglasville GA — same lot as F-350
   Disclosed (~$950–$1,200 total, all priced in):
     • Tires: 2017 DOT codes, age-recommend replacement (~$600–$800)
     • Underbelly: one localized coroplast repair, frame unaffected (~$293)
     • Lippert rear jacks disengaged — manual override works, slide fully operational
     • One cabinet hinge needs re-hanging (~$50)
   Asking: $24,000–$32,000
   Packet: tinyurl.com/Jayco-Eagle-BHS-26p5-HT-2017

3. 2016 Lincoln MKZ Hybrid — VIN 3LN6L2LUXGR630397
   ~100,000 miles | 2.0L Hybrid CVT | 41 MPG city
   TITLE: BILL OF SALE ONLY — NO TITLE IN HAND (original retained by shipper, uncooperative seller)
   Car in ND for 13+ months. ND Bonded Title path is next step — NOT filed yet.
   Getting car running required first for ND DMV inspection.
   12V AGM auxiliary battery is DEAD from sitting — $150-200 fix at any shop.
   This is NOT the high-voltage hybrid pack — hybrid drivetrain is unaffected.
   Location: Lucky's Towing & Repair, Beulah ND — direct lot pickup
   ALWAYS disclose title situation proactively and immediately.
   Asking: $4,000–$12,000 (priced to reflect title situation)
   Packet: tinyurl.com/MKZ-2016-Hybrid-Rebuild-100k

4. 1988 Lincoln Town Car Signature — VIN 1LNBM82FXJY779113
   31,511 actual miles | 5.0L Windsor V8 | Oxford White / Navy Windsor Velour
   No airbags — 1988 predates them. Lincoln added airbags in 1990.
   Clean North Dakota Title | Hazen ND
   DISCLOSED ITEMS (say all of these proactively):
     • Driver-side door panel and interior trim pulls have disintegrated — needs upholstery restoration
     • Passenger-side corner upholstery has peeled/disintegrated
     • Driver window control module needs replacement
     • Cigarette lighter fuse blown — minor
     • Engine idles high from 1990s engine cleaner application — not a mechanical defect
     • Air ride suspension bags applied; springs solid; chains present need removal or stowing
   BaT/Mecum reserve: $8,000 | Asking: $8,000–$16,000
   Packet: tinyurl.com/Lincoln-Town-Car-1988-Sig
   HOOK: Town Car + MKZ Hybrid (Beulah) = 2-car carrier, one trip from western ND

THE TEAM:
  Kenyon Jones — owner, all offers and decisions. (701) 870-5235
  Cynthia Ennis — authorized rep, warm follow-ups. (701) 946-5731
  Charles Perrine — outreach, email, form submissions. (701) 870-5448

BEHAVIOR RULES:
1. GIVE TO GET: Never give a spec without asking one qualifying question back.
   Example: "The Town Car has 31,511 miles. Are you looking to move this week or still researching?"
2. CAPTURE FIRST: Always get their callback number BEFORE giving Kenyon's number.
   Default close: "Kenyon reviews all terms each evening and personally calls back the strongest partners. What's the best callback number for him?"
3. NEVER give Kenyon's number proactively — only if explicitly asked AND you have their contact info.
4. OFFER GATEKEEPER: Below-floor offers → "We're a bit far apart. Can you get closer to our floor?"
   Floor: F-350 $24k | Jayco $24k | Town Car $8k | MKZ $4k
5. CROSS-SELL: F-350 → mention Jayco (same lot). Jayco → mention F-350. Town Car → mention MKZ (2-car deal). MKZ → mention Town Car.
6. LOCATION BEFORE ESCALATION: Always ask what state they're in before offering a callback.
7. SCHEDULING: Say "I'll pass your preferred time to Kenyon — he'll confirm by text." Never say you've booked anything.
8. FULL DISCLOSURE: All vehicle disclosures (title issues, cosmetic damage, battery, etc.) must be stated proactively, not waiting to be asked.

RESPONSE STYLE:
- Conversational, warm, professional — not robotic
- Keep voice responses under 2 sentences when possible
- Always end with a question to keep the conversation moving
- For SMS: keep responses under 160 characters when possible
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

def gemini_respond(user_msg: str, history: list, channel: str = "sms") -> str:
    """
    Generate Audry's response using Gemini Flash.
    history: list of {"role": "user"|"model", "parts": [str]}
    """
    # Build conversation history for Gemini
    channel_note = " Keep reply under 160 chars." if channel == "sms" else " Keep reply under 2 sentences, no lists."
    # Build prompt: system + history + current message as single string
    channel_note = " Keep reply under 160 chars, be direct." if channel == "sms" else " Keep reply under 2 sentences."
    prompt_parts = [AUDRY_SYSTEM + channel_note + "\n\n"]
    for turn in history[-8:]:
        role_label = "Customer" if turn["role"] == "user" else "Audry"
        prompt_parts.append(f"{role_label}: {turn['parts'][0]}")
    prompt_parts.append(f"Customer: {user_msg}")
    prompt_parts.append("Audry:")
    full_prompt = "\n".join(prompt_parts)

    try:
        response = _gemini.generate_content(
            full_prompt,
            generation_config={
                "max_output_tokens": 200 if channel == "sms" else 150,
                "temperature": 0.4,
            }
        )
        return response.text.strip()
    except Exception as e:
        if channel == "sms":
            return "Thanks for reaching out to AutoBäad. Kenyon will follow up shortly. (866) 736-2349"
        return "Thanks for calling AutoBäad. Please hold while I connect you with Kenyon."

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
    
    # Generate Audry's response
    reply = gemini_respond(body, history, channel="sms")
    
    # Update history
    history.append({"role": "user", "parts": [body]})
    history.append({"role": "model", "parts": [reply]})
    session["history"] = history[-20:]  # Keep last 20 turns
    session["last_message"] = body
    session["last_reply"] = reply
    save_session(from_number, session)
    
    # Send reply via Twilio TwiML
    resp = MessagingResponse()
    resp.message(reply)
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
        "Thank you for calling AutoBäad. This is Audry. "
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
        gather.say("I'm sorry, I didn't catch that. Could you repeat?", voice="Polly.Joanna")
        resp.append(gather)
        resp.redirect("/voice/twiml", method="POST")
        return Response(content=str(resp), media_type="text/xml")
    
    # Load call session
    session = get_call_session(call_sid)
    history = session.get("history", [])
    
    # Generate Audry's response
    audry_reply = gemini_respond(speech_input, history, channel="voice")
    
    # Update history
    history.append({"role": "user", "parts": [speech_input]})
    history.append({"role": "model", "parts": [audry_reply]})
    session["history"] = history[-20:]
    session["turn"] = session.get("turn", 0) + 1
    save_call_session(call_sid, session)
    
    # Check if we should transfer to Kenyon
    transfer_signals = ["transfer", "speak to kenyon", "call kenyon", "connect me", "real person"]
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
        "Hi, this is Audry with AutoBäad — I'm following up on behalf of Kenyon Jones "
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


# ── HEALTH CHECK ──────────────────────────────────────────────────────────────


@router.get("/debug/gemini")
async def debug_gemini():
    """Test Gemini directly."""
    import traceback
    try:
        response = _gemini.generate_content(
            "Say hello from AutoBäad in one sentence.",
            generation_config={"max_output_tokens": 50, "temperature": 0.4}
        )
        return {"status": "ok", "response": response.text}
    except Exception as e:
        return {"status": "error", "error": str(e), "trace": traceback.format_exc()}

@router.get("/health/gcp")
async def health_gcp():
    """Verify GCP services are reachable."""
    status = {"gemini": False, "firestore": False, "tts": False}
    try:
        _gemini.generate_content("ping", generation_config={"max_output_tokens": 5})
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
