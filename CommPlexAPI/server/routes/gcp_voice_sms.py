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
from google import genai
from google.genai.types import HttpOptions
import json
import re
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Request, Form, BackgroundTasks
from fastapi.responses import PlainTextResponse, Response
from twilio.twiml.messaging_response import MessagingResponse
from twilio.twiml.voice_response import VoiceResponse, Gather, Say, Hangup

from google.cloud import firestore, texttospeech, speech_v1
from google.cloud import secretmanager

router = APIRouter()

# ── GCP INIT ─────────────────────────────────────────────────────────────────

PROJECT_ID = os.getenv("GCP_PROJECT_ID", "commplex-493805")
REGION     = os.getenv("GCP_REGION", "us-central1")
_client = genai.Client(http_options=HttpOptions(api_version="v1"))

