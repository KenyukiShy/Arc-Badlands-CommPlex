"""
CommPlexAPI/modules/voice_routes.py — Twilio Voice Webhook Routes
Domain: CommPlexAPI (The Mouth)

These FastAPI routes handle Twilio webhook callbacks for the GCP_TWILIO
voice backend. Add to CommPlexAPI/server/main.py with:

    from CommPlexAPI.modules.voice_routes import router as voice_router
    app.include_router(voice_router, prefix="/voice", tags=["Voice"])

GoF: Facade — CommPlexAPI handles all Twilio callbacks here,
     routing Q&A to CommPlexCore.VoiceQAClassifier.
"""

from __future__ import annotations
import os
import logging
from fastapi import APIRouter, Request, Form
from fastapi.responses import Response

logger = logging.getLogger("CommPlexVoice")

router = APIRouter()

GCP_TTS_VOICE = "Google.en-US-Neural2-F"
TRANSFER_TO   = os.getenv("TRANSFER_NUMBER", "7018705235")


def _twiml_response(content: str) -> Response:
    return Response(content=content, media_type="application/xml")


@router.post("/twiml")
async def voice_twiml(
    request: Request,
    campaign_id: str = "mkz",
    contact_name: str = "Dealer",
):
    """
    Generate TwiML for outbound call using Google TTS voice.
    Twilio calls this URL when the call connects.
    """
    try:
        from CommPlexCore.modules.voice_gcp import OPENER_SCRIPTS, GcpTwilioBackend

        campaign_map = {
            "mkz":     "MKZ_2016_HYBRID",
            "towncar": "TOWNCAR_1988_SIGNATURE",
            "f350":    "F350_2006_KING_RANCH",
            "jayco":   "JAYCO_2017_EAGLE_HT",
        }
        campaign_id_full = campaign_map.get(campaign_id.lower(), "MKZ_2016_HYBRID")
        script = OPENER_SCRIPTS.get(campaign_id_full, OPENER_SCRIPTS["MKZ_2016_HYBRID"])

        base_url = str(request.base_url).rstrip("/")
        twiml = GcpTwilioBackend.build_twiml_response(script, campaign_id)
        twiml = twiml.replace(
            "/voice/gather",
            f"{base_url}/voice/gather"
        ).replace(
            "/voice/no-response",
            f"{base_url}/voice/no-response"
        )

        logger.info(f"[VoiceTwiML] Serving script for {campaign_id} / {contact_name}")
        return _twiml_response(twiml)

    except Exception as e:
        logger.error(f"[VoiceTwiML] Error: {e}")
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="{GCP_TTS_VOICE}">Hello, this is Morgan calling on behalf of Kenyon Jones at Arc Badlands regarding a vehicle for sale. Please call Kenyon directly at 7 0 1, 8 7 0, 5 2 3 5. Thank you.</Say>
  <Hangup/>
</Response>"""
        return _twiml_response(twiml)


@router.post("/gather")
async def voice_gather(
    request: Request,
    campaign_id: str = "mkz",
    Digits: str = Form(default=""),
):
    """
    Handle DTMF input from dealer:
    1 = interested, send callback alert
    2 = decline
    3 = transfer to Kenyon
    """
    digit = Digits.strip()
    logger.info(f"[VoiceGather] campaign={campaign_id} digits={digit}")

    if digit == "1":
        # Fire ntfy alert
        try:
            from CommPlexEdge.modules.notifier import NotifierModule
            n = NotifierModule()
            n.campaign_milestone(campaign_id, "DEALER INTERESTED", "Press 1 via voice wave")
        except Exception:
            pass
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="{GCP_TTS_VOICE}">Wonderful! Kenyon will call you back shortly. Thank you for your interest.</Say>
  <Hangup/>
</Response>"""

    elif digit == "3":
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="{GCP_TTS_VOICE}">One moment, I am transferring you to Kenyon Jones now.</Say>
  <Dial callerId="+1{TRANSFER_TO}">
    <Number>+1{TRANSFER_TO}</Number>
  </Dial>
</Response>"""

    else:
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="{GCP_TTS_VOICE}">Thank you for your time. If you change your mind, please call Kenyon Jones at 7 0 1, 8 7 0, 5 2 3 5. Have a great day.</Say>
  <Hangup/>
</Response>"""

    return _twiml_response(twiml)


@router.post("/no-response")
async def voice_no_response(campaign_id: str = "mkz"):
    """Handle calls where dealer didn't press any key."""
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="{GCP_TTS_VOICE}">Thank you for your time. Kenyon Jones can be reached at 7 0 1, 8 7 0, 5 2 3 5 if you'd like to discuss further. Have a great day.</Say>
  <Hangup/>
</Response>"""
    return _twiml_response(twiml)


@router.post("/status")
async def voice_status(
    CallSid: str = Form(default=""),
    CallStatus: str = Form(default=""),
    CallDuration: str = Form(default="0"),
    To: str = Form(default=""),
):
    """
    Twilio status callback — log call outcome, update lead if needed.
    """
    logger.info(f"[VoiceStatus] {CallSid} → {CallStatus} | {CallDuration}s | to={To}")

    # Fire ntfy for connected calls
    if CallStatus == "completed" and int(CallDuration or 0) > 5:
        try:
            from CommPlexEdge.modules.notifier import NotifierModule
            n = NotifierModule()
            n.campaign_milestone(
                "voice_wave",
                f"Call completed ({CallDuration}s)",
                f"SID: {CallSid} | To: {To}"
            )
        except Exception:
            pass

    return {"received": True, "status": CallStatus, "sid": CallSid}
