import os, json, re
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Form
from fastapi.responses import PlainTextResponse, Response
from twilio.twiml.messaging_response import MessagingResponse
from twilio.twiml.voice_response import VoiceResponse, Gather
from google.cloud import firestore
from google import genai
from google.genai.types import HttpOptions

router = APIRouter()

PROJECT_ID = os.getenv("GCP_PROJECT_ID", "commplex-493805")
_client = genai.Client(http_options=HttpOptions(api_version="v1"))
_db = firestore.Client(project=PROJECT_ID)

AUDRY_SYSTEM = """You are Audry Harper, AI sales representative for AutoBäad — Kenyon Jones's private vehicle liquidation operation out of Hazen, North Dakota.

THE 4 VEHICLES:
1. 2006 F-350 King Ranch — VIN 1FTWW31Y86EA12357
   47,000 actual miles | 6.8L Triton V10 Gas (NO diesel) | 4x4 | Crew Cab / Long Bed
   Factory 5th Wheel Kingpin Hitch | Clean Georgia Title | Douglasville GA
   Asking: $24,000–$32,000 | Packet: tinyurl.com/Ford-KR-F350V10-ExtBedCab
   HOOK: Same GA lot as Jayco — truck can tow camper out in one trip

2. 2017 Jayco Eagle HT 26.5BHS — VIN 1UJCJ0BPXH1P20237
   2,400 actual tow miles | 4-season Climate Shield (rated to 0°F) | Half-ton towable
   Clean Georgia Title | Douglasville GA
   Disclosed (~$950-$1,200 total, priced in): tire age, underbelly coroplast patch, Lippert rear jacks disengaged (manual works), one cabinet hinge
   Asking: $24,000–$32,000 | Packet: tinyurl.com/Jayco-Eagle-BHS-26p5-HT-2017

3. 2016 Lincoln MKZ Hybrid — VIN 3LN6L2LUXGR630397
   ~100,000 miles | 2.0L Hybrid | BILL OF SALE ONLY — NO TITLE IN HAND
   12V auxiliary battery DEAD — $150-200 fix. Hybrid drivetrain unaffected.
   Location: Lucky's Towing & Repair, Beulah ND
   Asking: $4,000–$12,000 | Packet: tinyurl.com/MKZ-2016-Hybrid-Rebuild-100k

4. 1988 Lincoln Town Car Signature — VIN 1LNBM82FXJY779113
   31,511 actual miles | 5.0L Windsor V8 | Oxford White / Navy Windsor Velour
   No airbags — 1988 predates them. Clean North Dakota Title | Hazen ND
   Disclosed: driver door panel disintegrated, passenger corner upholstery peeled, driver window module needs replacement, cigarette lighter fuse blown, engine idles high from old engine cleaner, air ride bags applied/chains present
   Asking: $8,000–$16,000 | Packet: tinyurl.com/Lincoln-Town-Car-1988-Sig
   HOOK: Town Car + MKZ = 2-car carrier, one trip from western ND

THE TEAM:
  Kenyon Jones — owner, all offers/decisions. (701) 870-5235
  Cynthia Ennis — authorized rep. (701) 946-5731
  Charles Perrine — outreach. (701) 870-5448

BEHAVIOR RULES:
1. GIVE TO GET: Never give a spec without asking one qualifying question back.
2. CAPTURE FIRST: Get their callback number BEFORE giving Kenyon's number.
3. NEVER give Kenyon's number proactively — only if explicitly asked AND you have their info.
4. OFFER GATEKEEPER: Below-floor offers: "We're a bit far apart. Can you get closer to our floor?"
   Floor: F-350 $24k | Jayco $24k | Town Car $8k | MKZ $4k
5. CROSS-SELL: F-350 mention Jayco. Jayco mention F-350. Town Car mention MKZ. MKZ mention Town Car.
6. FULL DISCLOSURE: State all vehicle disclosures proactively.
7. SCHEDULING: Say "I'll pass your preferred time to Kenyon — he'll confirm by text." Never say you booked anything.

RESPONSE STYLE:
- Warm, professional, conversational
- SMS: under 160 characters when possible
- Voice: under 2 sentences, no lists
- Always end with a question"""


def get_session(phone: str) -> dict:
    try:
        doc = _db.collection("sms_sessions").document(phone).get()
        if doc.exists:
            return doc.to_dict()
    except Exception:
        pass
    return {"phone": phone, "history": [], "state": "new"}


def save_session(phone: str, session: dict):
    try:
        session["updated_at"] = datetime.now(timezone.utc).isoformat()
        _db.collection("sms_sessions").document(phone).set(session)
    except Exception:
        pass


def get_call_session(call_sid: str) -> dict:
    try:
        doc = _db.collection("call_sessions").document(call_sid).get()
        if doc.exists:
            return doc.to_dict()
    except Exception:
        pass
    return {"call_sid": call_sid, "history": []}


def save_call_session(call_sid: str, session: dict):
    try:
        session["updated_at"] = datetime.now(timezone.utc).isoformat()
        _db.collection("call_sessions").document(call_sid).set(session)
    except Exception:
        pass


def gemini_respond(user_msg: str, history: list, channel: str = "sms") -> str:
    channel_note = " Keep reply under 160 chars." if channel == "sms" else " Keep reply under 2 sentences."
    prompt_parts = [AUDRY_SYSTEM + channel_note + "\n\n"]
    for turn in history[-8:]:
        role_label = "Customer" if turn["role"] == "user" else "Audry"
        prompt_parts.append(f"{role_label}: {turn['parts'][0]}")
    prompt_parts.append(f"Customer: {user_msg}")
    prompt_parts.append("Audry:")
    full_prompt = "\n".join(prompt_parts)
    try:
        response = _client.models.generate_content(
            model="gemini-2.5-flash",
            contents=full_prompt,
        )
        return response.text.strip()
    except Exception as e:
        print(f"[Gemini error] {e}")
        if channel == "sms":
            return "Thanks for reaching out to AutoBäad. Kenyon will follow up shortly. (866) 736-2349"
        return "Thanks for calling AutoBäad. Please hold while I connect you with Kenyon."


@router.post("/webhook/sms")
async def handle_sms(request: Request):
    form = await request.form()
    from_number = form.get("From", "")
    body = form.get("Body", "").strip()
    if not from_number or not body:
        return PlainTextResponse("", status_code=200)
    session = get_session(from_number)
    history = session.get("history", [])
    reply = gemini_respond(body, history, channel="sms")
    history.append({"role": "user", "parts": [body]})
    history.append({"role": "model", "parts": [reply]})
    session["history"] = history[-20:]
    save_session(from_number, session)
    resp = MessagingResponse()
    resp.message(reply)
    return PlainTextResponse(str(resp), media_type="text/xml")


@router.post("/voice/twiml")
async def handle_voice_inbound(request: Request):
    resp = VoiceResponse()
    gather = Gather(input="speech", action="/voice/respond", method="POST",
                    timeout=5, speech_timeout="auto", language="en-US")
    gather.say("Thank you for calling AutoBäad. This is Audry. How can I help you today?",
               voice="Polly.Joanna")
    resp.append(gather)
    resp.redirect("/voice/twiml", method="POST")
    return Response(content=str(resp), media_type="text/xml")


@router.post("/voice/respond")
async def handle_voice_respond(request: Request):
    form = await request.form()
    call_sid = form.get("CallSid", "")
    speech_input = form.get("SpeechResult", "").strip()
    confidence = float(form.get("Confidence", "0"))
    resp = VoiceResponse()
    if not speech_input or confidence < 0.3:
        gather = Gather(input="speech", action="/voice/respond", method="POST", timeout=5)
        gather.say("I'm sorry, I didn't catch that. Could you repeat?", voice="Polly.Joanna")
        resp.append(gather)
        resp.redirect("/voice/twiml", method="POST")
        return Response(content=str(resp), media_type="text/xml")
    session = get_call_session(call_sid)
    history = session.get("history", [])
    audry_reply = gemini_respond(speech_input, history, channel="voice")
    history.append({"role": "user", "parts": [speech_input]})
    history.append({"role": "model", "parts": [audry_reply]})
    session["history"] = history[-20:]
    save_call_session(call_sid, session)
    transfer_signals = ["speak to kenyon", "call kenyon", "talk to the owner", "real person"]
    if any(sig in audry_reply.lower() for sig in transfer_signals):
        resp.say(audry_reply, voice="Polly.Joanna")
        resp.dial("+17018705235")
        return Response(content=str(resp), media_type="text/xml")
    gather = Gather(input="speech", action="/voice/respond", method="POST",
                    timeout=5, speech_timeout="auto", language="en-US")
    gather.say(audry_reply, voice="Polly.Joanna")
    resp.append(gather)
    resp.redirect("/voice/twiml", method="POST")
    return Response(content=str(resp), media_type="text/xml")


@router.get("/debug/gemini")
async def debug_gemini():
    import traceback
    try:
        response = _client.models.generate_content(
            model="gemini-2.5-flash",
            contents="Say hello from AutoBäad in one sentence.",
        )
        return {"status": "ok", "response": response.text}
    except Exception as e:
        return {"status": "error", "error": str(e), "trace": traceback.format_exc()}


@router.get("/health")
async def health():
    return {"status": "ok", "revision": "00027"}
