"""
CommPlex Inbound SMS Pre-Qualification Engine
File: CommPlexAPI/server/routes/sms_intake.py
"""

import os
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Request, Form
from fastapi.responses import PlainTextResponse
from twilio.twiml.messaging_response import MessagingResponse
from twilio.twiml.voice_response import VoiceResponse, Dial, Sip
from google.cloud import secretmanager
from googleapiclient.discovery import build
from google.oauth2 import service_account

router = APIRouter()

# -- SESSION STORE & CONFIG --
_sessions = {}
CONTACT_TYPES = {"1": "dealer", "2": "consigner", "3": "private_buyer", "4": "auction_house"}
VEHICLE_KEYWORDS = {"f350": "F-350 King Ranch", "jayco": "2017 Jayco Eagle HT", "mkz": "2016 Lincoln MKZ Hybrid", "town car": "1988 Lincoln Town Car"}

def get_session(phone: str) -> dict:
    if phone not in _sessions:
        _sessions[phone] = {"state": "GREET", "phone": phone, "offers": [], "started_at": datetime.now(timezone.utc).isoformat()}
    return _sessions[phone]

def process_sms(from_number: str, body: str) -> str:
    body_lower = body.strip().lower()
    session = get_session(from_number)
    state = session["state"]
    
    if body_lower in ("stop", "quit"): return "Unsubscribed."
    if body_lower in ("restart", "reset"): session["state"] = "GREET"

    if session["state"] == "GREET":
        session["state"] = "QUALIFY"
        return "Hi, this is AutoBäad. Reply with your role: 1. Dealer, 2. Consigner, 3. Private buyer, 4. Other"
    
    return "Hi — this is AutoBäad. Reply HELP for info or RESTART to begin."

@router.post("/webhook/sms", response_class=PlainTextResponse)
async def inbound_sms(From: str = Form(...), Body: str = Form(...)):
    reply_text = process_sms(From, Body)
    resp = MessagingResponse()
    resp.message(reply_text)
    return PlainTextResponse(str(resp), media_type="application/xml")

@router.post("/voice/twiml", response_class=PlainTextResponse)
async def inbound_voice(request: Request):
    resp = VoiceResponse()
    resp.say("Thank you for calling AutoBäad. Please hold while we connect you.", voice="Polly.Joanna")
    dial = Dial(timeout=30, caller_id="+18667362349")
    dial.sip("sip:+17013805915@sip.bland.ai")
    resp.append(dial)
    return PlainTextResponse(str(resp), media_type="application/xml")
