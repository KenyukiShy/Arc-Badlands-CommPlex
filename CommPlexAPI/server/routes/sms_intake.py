import os, json, re
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Request, Form
from fastapi.responses import PlainTextResponse
from twilio.twiml.messaging_response import MessagingResponse
from twilio.twiml.voice_response import VoiceResponse, Dial

router = APIRouter()
_sessions: dict[str, dict] = {}

CONTACT_TYPES = {
    "1":"dealer","2":"consigner","3":"private_buyer","4":"other",
    "dealer":"dealer","consign":"consigner","consignment":"consigner",
    "private":"private_buyer","buyer":"private_buyer",
    "auction":"auction_house","mecum":"auction_house","bat":"auction_house",
}

VEHICLE_MAP = {
    "a":"F-350 King Ranch","b":"2017 Jayco Eagle HT",
    "c":"2016 Lincoln MKZ Hybrid","d":"1988 Lincoln Town Car","e":"ALL VEHICLES",
}

VEHICLE_KEYWORDS = {
    "f350":"F-350 King Ranch","f-350":"F-350 King Ranch","king ranch":"F-350 King Ranch",
    "truck":"F-350 King Ranch","ford":"F-350 King Ranch",
    "jayco":"2017 Jayco Eagle HT","camper":"2017 Jayco Eagle HT","rv":"2017 Jayco Eagle HT",
    "fifth wheel":"2017 Jayco Eagle HT","bunkhouse":"2017 Jayco Eagle HT",
    "mkz":"2016 Lincoln MKZ Hybrid","hybrid":"2016 Lincoln MKZ Hybrid",
    "town car":"1988 Lincoln Town Car","towncar":"1988 Lincoln Town Car",
    "1988":"1988 Lincoln Town Car","88":"1988 Lincoln Town Car",
    "all":"ALL VEHICLES","everything":"ALL VEHICLES",
}

VEHICLE_QUESTIONS = {
    "F-350 King Ranch": "Quick questions for the F-350:\nGA transport or partner lot in GA? Direct purchase, consignment, or auction (BaT/Mecum)?\nBudget range?",
    "2017 Jayco Eagle HT": "For the Jayco:\nJayco-authorized? 5th wheel hoist on site? Consignment, direct purchase, or floor plan?\nLocation and lot capacity?",
    "2016 Lincoln MKZ Hybrid": "For the MKZ:\nSet up for rebuilt-title inventory? Car is in Beulah ND — direct pickup or need transport (~$900 to Bismarck)?\nOffer range?",
    "1988 Lincoln Town Car": "For the Town Car:\nCollector, dealer, or auction (BaT/Mecum/Kissimmee)? ND car, no rust, 31.5k mi, clean title.\nOffer range?",
    "ALL VEHICLES": "All four — channel? (direct purchase, consignment, auction, wholesale)\nWhere are you located?",
}

def get_session(phone):
    if phone not in _sessions:
        _sessions[phone] = {"state":"GREET","contact_type":None,"name":None,"company":None,
            "vehicle":None,"offers":[],"slot_chosen":None,"phone":phone,"slots":[],
            "started_at":datetime.now(timezone.utc).isoformat()}
    return _sessions[phone]

def detect_vehicle(text):
    text = text.lower()
    if "town car" in text or "1988" in text: return "1988 Lincoln Town Car"
    for kw, v in VEHICLE_KEYWORDS.items():
        if kw in text: return v
    return None

def detect_offer(text):
    m = re.search(r'\$?\s*(\d[\d,\.]+)\s*[kK]?', text)
    return m.group(0).strip() if m else None

def get_slots_static():
    now = datetime.now(timezone.utc)
    slots = []
    for day_offset, hour in [(1,10),(1,14),(2,10)]:
        base = now.replace(hour=hour,minute=0,second=0,microsecond=0) + timedelta(days=day_offset)
        slots.append({"start":base,"end":base+timedelta(minutes=30)})
    return slots

def format_slots(slots):
    days = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
    lines = []
    for i, s in enumerate(slots, 1):
        dt = s["start"].astimezone(timezone(timedelta(hours=-5)))
        lines.append(f"  {i}. {days[dt.weekday()]} {dt.strftime('%b %-d')} at {dt.strftime('%-I:%M %p')} CT")
    return "\n".join(lines)

def send_ntfy(session, priority="default", extra=""):
    try:
        import httpx
        topic = "px10pro-commplex-z7x2-alert-hub"
        name = session.get("name", session["phone"])
        company = session.get("company","")
        vehicle = session.get("vehicle","Unknown")
        offers = session.get("offers",[])
        title = f"📱 AutoBäad SMS: {name}{' @ '+company if company else ''}"
        msg = f"Vehicle: {vehicle}\nType: {session.get('contact_type','?')}\nPhone: {session['phone']}\nOffers: {', '.join(offers) or 'none'}\nSlot: {session.get('slot_chosen','ASAP')}\n{extra}"
        httpx.post(f"https://ntfy.sh/{topic}", content=msg.encode(),
            headers={"Title":title,"Priority":priority,"Tags":"car,phone"}, timeout=5)
    except Exception as e:
        print(f"[ntfy] {e}")

def book_slot(session, slot):
    try:
        from google.cloud import secretmanager
        from googleapiclient.discovery import build
        from google.oauth2 import service_account
        client = secretmanager.SecretManagerServiceClient()
        name = "projects/commplex-493805/secrets/SERVICE_ACCOUNT_JSON/versions/latest"
        sa_info = json.loads(client.access_secret_version(request={"name":name}).payload.data)
        creds = service_account.Credentials.from_service_account_info(
            sa_info, scopes=["https://www.googleapis.com/auth/calendar"])
        svc = build("calendar","v3",credentials=creds)
        event = {
            "summary": f"📞 AutoBäad: {session.get('name',session['phone'])} — {session.get('vehicle','?')}",
            "description": f"SMS lead\nContact: {session.get('name')}\nCompany: {session.get('company')}\nPhone: {session['phone']}\nType: {session.get('contact_type')}\nVehicle: {session.get('vehicle')}\nOffers: {', '.join(session.get('offers',[]))}",
            "start":{"dateTime":slot["start"].strftime("%Y-%m-%dT%H:%M:%S")+"Z","timeZone":"America/Chicago"},
            "end":{"dateTime":slot["end"].strftime("%Y-%m-%dT%H:%M:%S")+"Z","timeZone":"America/Chicago"},
            "colorId":"11",
            "reminders":{"useDefault":False,"overrides":[{"method":"popup","minutes":30},{"method":"email","minutes":60}]},
        }
        for cal in ["kjones.px10pro@gmail.com","kjonesmle@gmail.com"]:
            try: svc.events().insert(calendarId=cal,body=event,sendUpdates="all").execute()
            except: pass
    except Exception as e:
        print(f"[Calendar] {e}")

def process_sms(phone, body):
    body_clean = body.strip()
    bl = body_clean.lower()
    session = get_session(phone)
    state = session["state"]

    if bl in ("stop","quit","cancel"):
        _sessions.pop(phone,None)
        return "Unsubscribed. Reply START to re-subscribe."
    if bl in ("restart","start over","reset"):
        _sessions.pop(phone,None)
        session = get_session(phone); state = "GREET"
    if bl in ("help","?"):
        return "AutoBäad — Hazen ND. 4 vehicles: '06 F-350 King Ranch V10, '17 Jayco Eagle HT, '88 Lincoln Town Car 31k mi, '16 Lincoln MKZ Hybrid. Reply RESTART or call (866) 736-2349."

    if state == "GREET":
        session["state"] = "QUALIFY"; _sessions[phone] = session
        return "Hi — AutoBäad, Kenyon Jones, Hazen ND. 4 vehicles available.\n\nYour role:\n  1. Dealer\n  2. Consigner / Auction\n  3. Private buyer\n  4. Other"

    if state == "QUALIFY":
        ctype = CONTACT_TYPES.get(bl)
        if not ctype:
            for kw,ct in CONTACT_TYPES.items():
                if kw in bl: ctype=ct; break
        if not ctype: return "Reply 1 (Dealer), 2 (Consigner), 3 (Buyer), or 4 (Other)."
        session["contact_type"]=ctype; session["state"]="INFO_NAME"; _sessions[phone]=session
        return f"Got it — {ctype.replace('_',' ').title()}. Name and company? (e.g. 'Mike, Royal Drive Autos')"

    if state == "INFO_NAME":
        parts = [p.strip() for p in re.split(r'[,\-/]',body_clean,maxsplit=1)]
        session["name"]=parts[0]; session["company"]=parts[1] if len(parts)>1 else ""
        session["state"]="VEHICLE"; _sessions[phone]=session
        return f"Thanks{', '+session['name']}! Which vehicle?\n\n  A. '06 F-350 King Ranch V10 — 47k mi, GA ($24k–$32k)\n  B. '17 Jayco Eagle HT — 2.4k mi, 4-season, GA ($24k–$32k)\n  C. '16 Lincoln MKZ Hybrid — 100k mi, rebuilt title ($4k–$12k)\n  D. '88 Lincoln Town Car — 31.5k mi, clean ND title ($8k–$16k)\n  E. All\n\nReply A–E."

    if state == "VEHICLE":
        vehicle = VEHICLE_MAP.get(bl.strip()) or detect_vehicle(bl)
        if not vehicle: return "Reply A, B, C, D, or E — or describe the vehicle."
        session["vehicle"]=vehicle; session["state"]="PREQUALIFY"; _sessions[phone]=session
        return VEHICLE_QUESTIONS.get(vehicle, f"Tell me more about your interest in the {vehicle}.")

    if state == "PREQUALIFY":
        offer = detect_offer(bl)
        if offer: session["offers"].append(offer)
        session["prequalify_response"]=body_clean
        slots = get_slots_static()
        session["slots"]=[{"start":s["start"].isoformat(),"end":s["end"].isoformat()} for s in slots]
        session["state"]="SCHEDULE"; _sessions[phone]=session
        note = f"\n\nOffer noted: {offer}. Kenyon handles pricing directly." if offer else ""
        return f"Got it.{note}\n\nAvailable times for Kenyon's call:\n\n{format_slots(slots)}\n\nReply 1, 2, or 3 — or CALL for urgent callback."

    if state == "SCHEDULE":
        if bl in ("call","asap","now"):
            session["state"]="DONE"; _sessions[phone]=session
            send_ntfy(session,priority="urgent")
            return f"Flagged urgent for Kenyon. He or Cynthia will call {phone} shortly.\n\nPackets: tinyurl.com/Ford-KR-F350V10-ExtBedCab | tinyurl.com/Jayco-Eagle-BHS-26p5-HT-2017 | tinyurl.com/MKZ-2016-Hybrid-Rebuild-100k | tinyurl.com/Lincoln-Town-Car-1988-Sig\n\nReply STOP to unsubscribe."
        if bl not in ("1","2","3"): return "Reply 1, 2, or 3 to book — or CALL for urgent callback."
        idx = int(bl)-1
        raw = session.get("slots",[])
        if idx >= len(raw): return "Invalid. Reply 1, 2, or 3."
        chosen_raw = raw[idx]
        chosen = {"start":datetime.fromisoformat(chosen_raw["start"]),"end":datetime.fromisoformat(chosen_raw["end"])}
        session["slot_chosen"]=chosen_raw; session["state"]="DONE"; _sessions[phone]=session
        book_slot(session,chosen)
        send_ntfy(session,priority="high")
        dt = chosen["start"].astimezone(timezone(timedelta(hours=-5)))
        days=["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
        slot_str=f"{days[dt.weekday()]} {dt.strftime('%b %-d')} at {dt.strftime('%-I:%M %p')} CT"
        return f"Confirmed{', '+session['name'] if session.get('name') else ''}! Kenyon calls {phone} on {slot_str}.\n\nVehicle: {session.get('vehicle')}\n\nPackets:\nF-350: tinyurl.com/Ford-KR-F350V10-ExtBedCab\nJayco: tinyurl.com/Jayco-Eagle-BHS-26p5-HT-2017\nMKZ: tinyurl.com/MKZ-2016-Hybrid-Rebuild-100k\nTown Car: tinyurl.com/Lincoln-Town-Car-1988-Sig\n\nReply STOP to unsubscribe."

    if state == "DONE":
        offer = detect_offer(bl)
        if offer:
            session["offers"].append(offer); _sessions[phone]=session
            send_ntfy(session,priority="urgent",extra=f"New offer: {offer}")
            return f"Noted {offer} — passed to Kenyon. He'll address it on your call. Reply RESTART for new inquiry."
        return f"Callback already scheduled. Reply RESTART for new inquiry or CALL to escalate."

    return "Hi — AutoBäad. Reply HELP or RESTART."

@router.post("/webhook/sms", response_class=PlainTextResponse)
async def inbound_sms(From: str = Form(...), Body: str = Form(...)):
    resp = MessagingResponse()
    resp.message(process_sms(From, Body))
    return PlainTextResponse(str(resp), media_type="application/xml")

@router.post("/voice/twiml", response_class=PlainTextResponse)
async def inbound_voice(request: Request):
    resp = VoiceResponse()
    resp.say("Thank you for calling AutoBäad. Connecting you now.", voice="Polly.Joanna")
    dial = Dial(timeout=30, caller_id="+18667362349")
    dial.sip("sip:+17013805915@sip.bland.ai")
    resp.append(dial)
    resp.say("Unable to connect. Please text this number or try again.", voice="Polly.Joanna")
    return PlainTextResponse(str(resp), media_type="application/xml")
