"""
voice_stream.py — Twilio Media Streams + Google STT + Gemini + GCP TTS
CommPlexAPI/server/routes/voice_stream.py

Architecture:
  OLD: Call → Twilio STT (<Gather>) → HTTP POST → Gemini → Polly TTS
  NEW: Call → WebSocket → Google STT → Gemini flash-lite → GCP TTS → stream back

Target latency: ~1.5-2s from caller stops speaking to Audry starts speaking.
"""

import asyncio
import base64
import json
import os
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import Response
from twilio.twiml.voice_response import VoiceResponse, Connect
from google.cloud import speech_v1 as speech
from google.cloud import texttospeech_v1 as tts
from google.cloud import firestore
)

router = APIRouter()

PROJECT = os.environ.get("GCP_PROJECT_ID", "commplex-493805")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

_stt_client = None
_tts_client = None
_db = None

def _stt():
    global _stt_client
    if _stt_client is None:
        _stt_client = speech.SpeechClient()
    return _stt_client

def _tts():
    global _tts_client
    if _tts_client is None:
        _tts_client = tts.TextToSpeechClient()
    return _tts_client

def _firestore():
    global _db
    if _db is None:
        _db = firestore.Client(project=PROJECT)
    return _db

STT_CONFIG = speech.RecognitionConfig(
    encoding=speech.RecognitionConfig.AudioEncoding.MULAW,
    sample_rate_hertz=8000,
    language_code="en-US",
    model="phone_call",
    use_enhanced=True,
    enable_automatic_punctuation=True,
)

TTS_VOICE = tts.VoiceSelectionParams(
    language_code="en-US",
    name="en-US-Neural2-F",
)
TTS_AUDIO = tts.AudioConfig(
    audio_encoding=tts.AudioEncoding.MULAW,
    sample_rate_hertz=8000,
    speaking_rate=1.05,
    pitch=0.0,
)

AUDRY_SYSTEM = """You are Audry Harper, AI sales agent for AutoBäad — Kenyon Jones's private vehicle liquidation from Hazen, North Dakota. You are speaking on the phone. Use short, natural spoken sentences — never lists, never bullet points. One clear thought, then one question. Maximum 2 sentences per turn.

VEHICLES:
1. 2006 F-350 King Ranch — 47k mi, 6.8L V10 gas (no DEF, no diesel), 4x4 selectable, factory 5th wheel kingpin hitch, clean GA title, Douglasville GA. $24k–$32k. Same lot as Jayco — one trip pickup.
2. 2017 Jayco Eagle HT 26.5BHS — 2,400 tow miles, 4-season Climate Shield (0°F rated), half-ton towable, bunkhouse sleeps 8–10, clean GA title. $24k–$32k. Disclosed: tire age, underbelly coroplast patch, Lippert jacks disengaged (manual works), one cabinet hinge. All priced in.
3. 2016 Lincoln MKZ Hybrid — ~100k miles, BILL OF SALE ONLY (no title — retained by shipper, seller uncooperative), HV hybrid traction battery needs deep cycle recharge (NOT a simple 12V swap), Lucky's Towing, Beulah ND. $4k–$12k. Always disclose title situation first.
4. 1988 Lincoln Town Car Signature — 31,511 actual miles, 5.0L Windsor V8, Oxford White/Navy Windsor Velour interior, NO AIRBAGS (1988 predates them), clean ND title, Hazen ND. $8k–$16k. BaT/Mecum reserve $8k. Disclosed: driver door panel/trim disintegrated, passenger corner upholstery peeled, driver window module needs replacement, cigarette lighter fuse blown, high idle from 1990s engine cleaner (not a defect), air ride bags applied/springs solid/chains need stowing.

RULES:
- Greet warmly, identify yourself as Aw-dree from Auto-Bad
- Disclose all issues before buyer asks
- Capture their callback number before giving Kenyon's
- Offer floor gatekeeper: below floor → "We're a bit apart — can you come closer to $X?"
- Cross-sell: F-350 ↔ Jayco (same GA lot). Town Car ↔ MKZ (2-car carrier from western ND)
- Close: "Kenyon reviews offers each evening — what's the best number to reach you?"
"""

GREETING = (
    "Thank you for calling Auto-Bad. This is Aw-dree, the A I sales agent for Kenyon Jones. "
    "We have four vehicles available — an eighty-eight Town Car, a twenty-sixteen M K Z Hybrid, "
    "a twenty-oh-six F Three-Fifty King Ranch, and a twenty-seventeen Jayco Eagle. "
    "Which one can I tell you about?"
)

SILENCE_SECONDS = 0.65
MAX_AUDIO_SECONDS = 30


def synthesize(text: str) -> bytes:
    resp = _tts().synthesize_speech(
        input=tts.SynthesisInput(text=text),
        voice=TTS_VOICE,
        audio_config=TTS_AUDIO,
    )
    return resp.audio_content


def transcribe_batch(audio_bytes: bytes) -> str:
    if len(audio_bytes) < 800:
        return ""

    def _gen():
        yield speech.StreamingRecognizeRequest(
            streaming_config=speech.StreamingRecognitionConfig(
                config=STT_CONFIG,
                interim_results=False,
                single_utterance=True,
            )
        )
        chunk_size = 4096
        for i in range(0, len(audio_bytes), chunk_size):
            yield speech.StreamingRecognizeRequest(
                audio_content=audio_bytes[i : i + chunk_size]
            )

    best = ""
    try:
        for result in _stt().streaming_recognize(requests=_gen()):
            for r in result.results:
                if r.is_final and r.alternatives:
                    candidate = r.alternatives[0].transcript.strip()
                    if len(candidate) > len(best):
                        best = candidate
    except Exception as e:
        print(f"[STT error] {e}")
    return best


def gemini_voice_reply(transcript: str, history: list) -> str:
    vertexai.init(project=PROJECT, location=LOCATION)
        "gemini-2.0-flash-lite",
        system_instruction=AUDRY_SYSTEM,
    )
    contents = []
    for turn in history[-8:]:
        contents.append(Content(
            role=turn["role"],
            parts=[Part.from_text(turn["parts"][0])]
        ))
    contents.append(Content(role="user", parts=[Part.from_text(transcript)]))

    try:
        resp = model.generate_content(
            contents,
                max_output_tokens=120,
                temperature=0.35,
            ),
        )
        return resp.text.strip()
    except Exception as e:
        print(f"[Gemini error] {e}")
        return "I didn't catch that — which vehicle were you asking about?"


def log_voice_lead(call_sid: str, caller: str, transcript: str, reply: str):
    try:
        from datetime import datetime, timezone
        _firestore().collection("leads").add({
            "channel": "voice_stream",
            "call_sid": call_sid,
            "phone": caller,
            "message": transcript,
            "reply": reply,
            "ts": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        print(f"[Firestore log error] {e}")


@router.post("/voice/stream-twiml")
async def voice_stream_twiml(request: Request):
    host = request.headers.get("host", "commplex-api-349126848698.us-central1.run.app")
    resp = VoiceResponse()
    connect = Connect()
    connect.stream(url=f"wss://{host}/voice/stream")
    resp.append(connect)
    return Response(content=str(resp), media_type="text/xml")


@router.websocket("/voice/stream")
async def voice_stream_ws(websocket: WebSocket):
    await websocket.accept()

    stream_sid: str = ""
    call_sid: str = ""
    caller: str = ""
    history: list = []
    audio_buf = bytearray()
    silence_task = None
    loop = asyncio.get_event_loop()
    processing = False

    async def send_audio(pcm: bytes):
        if not pcm:
            return
        payload = base64.b64encode(pcm).decode()
        await websocket.send_text(json.dumps({
            "event": "media",
            "streamSid": stream_sid,
            "media": {"payload": payload},
        }))

    async def play_text(text: str):
        if not text:
            return
        audio = await loop.run_in_executor(None, synthesize, text)
        await send_audio(audio)

    async def process_utterance():
        nonlocal audio_buf, processing
        if processing or not audio_buf:
            return
        processing = True
        buf_snapshot = bytes(audio_buf)
        audio_buf = bytearray()

        try:
            transcript = await loop.run_in_executor(None, transcribe_batch, buf_snapshot)
            if not transcript:
                await play_text("I didn't quite catch that — could you say that again?")
                return

            print(f"[STT] {transcript}")
            reply = await loop.run_in_executor(None, gemini_voice_reply, transcript, history)
            print(f"[Gemini] {reply}")

            history.append({"role": "user",  "parts": [transcript]})
            history.append({"role": "model", "parts": [reply]})

            await play_text(reply)
            loop.run_in_executor(None, log_voice_lead, call_sid, caller, transcript, reply)

        except Exception as e:
            print(f"[process_utterance error] {e}")
            await play_text("I had a small hiccup — which vehicle were you asking about?")
        finally:
            processing = False

    async def silence_fired():
        await asyncio.sleep(SILENCE_SECONDS)
        await process_utterance()

    try:
        async for raw_msg in websocket.iter_text():
            msg = json.loads(raw_msg)
            event = msg.get("event")

            if event == "connected":
                print("[stream] WebSocket connected")

            elif event == "start":
                info = msg.get("start", {})
                stream_sid = info.get("streamSid", "")
                call_sid   = info.get("callSid", "")
                caller     = info.get("customParameters", {}).get("caller", "unknown")
                print(f"[stream] start — call={call_sid}")
                await play_text(GREETING)

            elif event == "media":
                chunk = base64.b64decode(msg["media"]["payload"])
                audio_buf.extend(chunk)
                if silence_task and not silence_task.done():
                    silence_task.cancel()
                silence_task = asyncio.create_task(silence_fired())
                if len(audio_buf) > 8000 * MAX_AUDIO_SECONDS:
                    if silence_task and not silence_task.done():
                        silence_task.cancel()
                    await process_utterance()

            elif event == "stop":
                if silence_task and not silence_task.done():
                    silence_task.cancel()
                await process_utterance()
                break

    except WebSocketDisconnect:
        print(f"[stream] disconnected — call={call_sid}")
    except Exception as e:
        print(f"[stream] error: {e}")
    finally:
        if silence_task and not silence_task.done():
            silence_task.cancel()
        print(f"[stream] session ended — call={call_sid}")
