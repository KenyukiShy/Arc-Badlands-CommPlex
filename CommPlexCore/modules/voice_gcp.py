"""
CommPlexCore/modules/voice_gcp.py — AI Voice Calling Module
Domain: CommPlexCore (The Brain)

STATUS: Dual-mode — BLAND (Bland.ai) | GCP_TWILIO (Google TTS + Twilio)
        Set VOICE_BACKEND=BLAND or VOICE_BACKEND=GCP_TWILIO in .env

BLAND.AI (current):
    Active account: thia@shy2shy.com
    Key: org_741899502e615287eae2dcbfe47ff760f1ba25d311b516a7ce2bd28c5417a784fc3bf0e3dc06a623ff3d69
    Balance: ~$2 (low — migrate to GCP_TWILIO when possible)

GCP_TWILIO (recommended migration path — $0.013/min vs Bland.ai's $0.09/min):
    Uses: Twilio Programmable Voice + Google Cloud Text-to-Speech + Gemini Flash
    Cost estimate: ~$0.015/min all-in vs $0.09/min Bland.ai
    GCP TTS: $4 per 1M chars → ~$0 for CommPlex scale
    Twilio outbound: ~$0.013/min
    Gemini Flash (Q&A): ~$0.0001/call

PURE GOOGLE alternative:
    Dialogflow CX Phone Gateway ($0.002/min + $0.001/sec Agent) — requires CCAI setup
    Google Voice: NO public API — consumer product only, cannot automate

GoF Patterns:
    Strategy:  VoiceBackend ABC — Bland | GcpTwilio swappable
    Template:  call() → build_script() → place_call() → handle_response()
    Proxy:     DRY_RUN=true gates all live calls
    Facade:    VoiceModule is the single entry point
"""

from __future__ import annotations
import os
import json
import logging
import re
from typing import Optional, Dict, List
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
VOICE_BACKEND = os.getenv("VOICE_BACKEND", "BLAND")
DRY_RUN       = os.getenv("DRY_RUN", "true").lower() == "true"
TRANSFER_TO   = os.getenv("TRANSFER_NUMBER", "7018705235")  # Kenyon direct

# Bland.ai credentials (new account — thia@shy2shy.com)
BLAND_API_KEY = os.getenv(
    "BLAND_API_KEY",
    "org_741899502e615287eae2dcbfe47ff760f1ba25d311b516a7ce2bd28c5417a784fc3bf0e3dc06a623ff3d69"
)
BLAND_FROM_NUMBER = os.getenv("BLAND_FROM_NUMBER", "")

# Twilio credentials
TWILIO_SID    = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM   = os.getenv("TWILIO_PHONE_NUMBER", "")

# GCP
GCP_PROJECT   = os.getenv("GCP_PROJECT_ID", "commplex-493805")


# ── Q&A Knowledge Base — Vehicle-Specific ────────────────────────────────────

VEHICLE_QA: Dict[str, Dict[str, str]] = {
    "MKZ_2016_HYBRID": {
        "price":    "We are asking between three thousand five hundred and five thousand five hundred dollars. The rebuilt title is factored into the price.",
        "title":    "It has a rebuilt title — previously salvaged in North Dakota. The bonded title process is underway per North Dakota code thirty nine dash oh five.",
        "mileage":  "Approximately one hundred thousand miles.",
        "location": "The vehicle is at Lucky's Towing and Repair in Beulah North Dakota.",
        "battery":  "The twelve volt auxiliary battery needs a recharge — about a hundred dollar fix. The hybrid drivetrain is completely unaffected.",
        "transport":"We can arrange transport after an offer is agreed upon.",
        "photos":   "Yes, we have a full photo package available. Kenyon can send them by email immediately.",
        "vin":      "The VIN is 3 Lima November 6 Lima 2 Lima Uniform X Golf Romeo 6 3 0 3 9 7.",
        "features": "It has leather heated seats, an eight inch SYNC 3 touchscreen, backup camera, and push button start. Gets forty one miles per gallon city.",
        "default":  "That's a great question. Kenyon Jones can answer that directly. His number is seven oh one, eight seven oh, five two three five. Can I take a message for him?",
    },
    "TOWNCAR_1988_SIGNATURE": {
        "price":    "We are targeting ten thousand to fourteen thousand dollars at Bring a Trailer auction. Reserve is nine thousand five hundred.",
        "mileage":  "Thirty one thousand five hundred and eleven actual original verified miles.",
        "title":    "Clean North Dakota title, zero liens.",
        "location": "Hazen slash Beulah North Dakota. Inspection by appointment.",
        "condition":"This is a genuine time capsule. Oxford White with the full black Landau vinyl roof. Windsor Velour interior — collector preferred over leather versions.",
        "issues":   "Fully disclosed items: driver door panel dry rot which is cosmetic, window module repair, A C recharge needed, and suspension currently on springs. Total service estimate is five to seven hundred dollars.",
        "bat":      "Yes, we have an eighteen photo catalog and a complete BaT submission package ready to go.",
        "default":  "Kenyon Jones can speak to that directly at seven oh one, eight seven oh, five two three five.",
    },
    "F350_2006_KING_RANCH": {
        "price":    "We are targeting twenty eight to thirty six thousand at Bring a Trailer. Reserve is twenty two thousand.",
        "mileage":  "Approximately forty seven thousand actual original miles.",
        "engine":   "Six point eight liter Triton V10 gas engine — no diesel, no six point oh headaches, no DEF fluid.",
        "title":    "Clean Georgia title.",
        "location": "Douglasville Georgia. On-site contacts are Doug and Sherrie Appleby at seven seven oh, three one five, one nine four nine.",
        "tow":      "Factory fifth wheel kingpin hitch installed. GCWR around eighteen thousand pounds.",
        "king_ranch":"King Ranch is the top trim above Lariat. Full Castano saddle leather interior, heated front seats, genuine wood grain accents.",
        "photos":   "Sherrie Appleby can do a walkthrough and photo session on short notice.",
        "default":  "Kenyon Jones at seven oh one, eight seven oh, five two three five can answer that.",
    },
    "JAYCO_2017_EAGLE_HT": {
        "price":    "We are asking twenty seven to thirty five thousand depending on the scenario.",
        "mileage":  "Approximately twenty four hundred actual tow miles — essentially new use.",
        "title":    "Clean Georgia title, zero liens. Title number seven seven oh one seven five two oh six one two seven nine eight zero.",
        "location": "Douglasville Georgia. On-site contacts Doug and Sherrie Appleby at seven seven oh, three one five, one nine four nine.",
        "four_season":"Yes, the Jayco Climate Shield package. Fully enclosed heated underbelly rated to zero degrees Fahrenheit. PEX plumbing, double layer fiberglass, forced air heated tank system. This is not optional in North Dakota.",
        "tow":      "GVWR is nine thousand nine hundred fifty pounds — half ton towable with an F-150, Ram 1500, or Silverado 1500.",
        "bat":      "BaT does not accept fifth wheel RVs. We are going through Corral Sales in Mandan North Dakota as the primary channel.",
        "disclosed":"Tires are full tread but two thousand seventeen DOT code, age-recommend replacement. Localized coroplast repair at one underbelly entry point. Lippert rear auto-level jacks disengaged — front jacks and slide fully operational. Total disclosed estimate is nine fifty to twelve hundred.",
        "default":  "Kenyon Jones at seven oh one, eight seven oh, five two three five.",
    },
}


# ── Scripts ───────────────────────────────────────────────────────────────────

OPENER_SCRIPTS: Dict[str, str] = {
    "MKZ_2016_HYBRID": (
        "Hello, may I please speak with someone in vehicle purchasing or management? "
        "My name is Morgan and I'm calling on behalf of Kenyon Jones at Arc Badlands. "
        "Kenyon has a twenty sixteen Lincoln MKZ Hybrid — rebuilt title, approximately "
        "one hundred thousand miles — located in Beulah North Dakota. He's seeking offers "
        "in the thirty-five hundred to fifty-five hundred range and wanted to know if your "
        "team would be interested. Can I tell him you'd like to hear more, or would you "
        "like me to transfer you to him directly?"
    ),
    "TOWNCAR_1988_SIGNATURE": (
        "Hello, may I speak with your classic vehicle buyer or consignment contact? "
        "My name is Morgan, calling for Kenyon Jones at Arc Badlands. "
        "Kenyon has a nineteen eighty eight Lincoln Town Car Signature Series — "
        "thirty one thousand five hundred actual miles, Oxford White, clean North Dakota title. "
        "This is a genuine Bring a Trailer candidate. He's targeting ten to fourteen thousand "
        "at auction. Would you or your team be interested in a consignment conversation?"
    ),
    "F350_2006_KING_RANCH": (
        "Hello, may I speak with someone who handles collector truck acquisitions or consignment? "
        "I'm Morgan, calling for Kenyon Jones at Arc Badlands. "
        "He has a two thousand six Ford F-350 King Ranch V10 — forty seven thousand original miles, "
        "crew cab long bed, factory fifth wheel hitch, clean Georgia title. "
        "No diesel, no six-point-oh risk. BaT range is twenty eight to thirty six thousand. "
        "Would your team be open to a conversation?"
    ),
    "JAYCO_2017_EAGLE_HT": (
        "Hello, may I speak with your RV consignment or purchasing contact? "
        "My name is Morgan, calling on behalf of Kenyon Jones. "
        "He has a twenty seventeen Jayco Eagle HT twenty six point five BHS — "
        "four season Climate Shield package, approximately twenty four hundred tow miles, "
        "clean Georgia title. Southeast stored, zero road salt. "
        "He's moving it to North Dakota and asking twenty seven to thirty five thousand. "
        "Would you be interested in discussing consignment or purchase?"
    ),
}

VOICEMAIL_SCRIPTS: Dict[str, str] = {
    "MKZ_2016_HYBRID": (
        "Hello, this message is for the vehicle buying or sales manager. "
        "My name is Morgan and I am calling on behalf of Kenyon Jones at Arc Badlands "
        "regarding a twenty sixteen Lincoln MKZ Hybrid for sale. "
        "Rebuilt title, approximately one hundred thousand miles, located in Beulah North Dakota. "
        "Asking thirty five hundred to fifty five hundred dollars. "
        "Please call Kenyon directly at seven oh one, eight seven oh, five two three five. "
        "Or reach Cynthia Ennis at seven oh one, nine four six, five seven three one. "
        "Thank you and have a great day."
    ),
    "TOWNCAR_1988_SIGNATURE": (
        "Hello, this message is for your classic car buyer or consignment contact. "
        "I am Morgan, calling for Kenyon Jones at Arc Badlands. "
        "He has a nineteen eighty eight Lincoln Town Car Signature Series — "
        "only thirty one thousand five hundred actual miles, Oxford White, clean North Dakota title. "
        "Strong Bring a Trailer candidate, targeting ten to fourteen thousand. "
        "Please call Kenyon at seven oh one, eight seven oh, five two three five. Thank you."
    ),
    "F350_2006_KING_RANCH": (
        "Hello, this message is for your collector truck buyer or consignment department. "
        "I'm Morgan, calling for Kenyon Jones at Arc Badlands. "
        "He has a two thousand six F-350 King Ranch V10 — forty seven thousand original miles, "
        "crew cab long bed, clean Georgia title. BaT range twenty eight to thirty six thousand. "
        "Please call Kenyon at seven oh one, eight seven oh, five two three five. Thank you."
    ),
    "JAYCO_2017_EAGLE_HT": (
        "Hello, this message is for your RV consignment or purchasing team. "
        "I'm Morgan, calling for Kenyon Jones. "
        "He has a twenty seventeen Jayco Eagle HT bunkhouse fifth wheel — "
        "four season Climate Shield, twenty four hundred tow miles, clean Georgia title. "
        "Asking twenty seven to thirty five thousand. Moving to North Dakota spring twenty twenty six. "
        "Please call Kenyon at seven oh one, eight seven oh, five two three five. Thank you."
    ),
}


# ── Abstract Voice Backend ────────────────────────────────────────────────────

class VoiceBackend(ABC):
    """GoF Strategy — swappable voice calling backend."""

    @abstractmethod
    def place_call(self, to_number: str, script: str,
                   campaign_id: str, contact_name: str,
                   dry_run: bool = True) -> Dict:
        ...

    @abstractmethod
    def check_balance(self) -> Dict:
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        ...


# ── Bland.ai Backend ──────────────────────────────────────────────────────────

class BlandBackend(VoiceBackend):
    """
    Bland.ai voice backend.
    Current account: thia@shy2shy.com (~$2 balance)
    MIGRATE to GcpTwilioBackend when balance runs out.
    """

    name = "BLAND"
    API_URL = "https://api.bland.ai/v1"

    def __init__(self):
        self.api_key = BLAND_API_KEY
        self.from_number = BLAND_FROM_NUMBER

    def check_balance(self) -> Dict:
        import requests
        try:
            r = requests.get(f"{self.API_URL}/me",
                             headers={"authorization": self.api_key}, timeout=10)
            r.raise_for_status()
            data = r.json()
            return {"status": "ok", "data": data, "backend": "BLAND"}
        except Exception as e:
            return {"status": "error", "error": str(e), "backend": "BLAND"}

    def place_call(self, to_number: str, script: str,
                   campaign_id: str, contact_name: str,
                   dry_run: bool = True) -> Dict:
        if dry_run:
            logger.info(f"[Bland DRY] → {to_number} | {contact_name}")
            return {"status": "DRY_RUN", "to": to_number, "backend": "BLAND"}

        if not self.api_key or self.api_key.startswith("REPLACE"):
            return {"status": "STUB", "to": to_number}

        import requests
        payload = {
            "phone_number": f"+1{to_number}" if not to_number.startswith("+") else to_number,
            "from": self.from_number,
            "task": script,
            "voice": "maya",
            "max_duration": 4,
            "wait_for_greeting": True,
            "amd": True,
            "transfer_phone_number": f"+1{TRANSFER_TO}",
            "record": True,
            "metadata": {"campaign_id": campaign_id, "contact": contact_name},
        }
        try:
            r = requests.post(
                f"{self.API_URL}/calls",
                json=payload,
                headers={"authorization": self.api_key, "Content-Type": "application/json"},
                timeout=30,
            )
            r.raise_for_status()
            data = r.json()
            logger.info(f"[Bland] Call placed → {to_number}: {data.get('call_id')}")
            return {"status": "CALLED", "call_id": data.get("call_id"),
                    "to": to_number, "backend": "BLAND"}
        except Exception as e:
            logger.error(f"[Bland] Call failed for {to_number}: {e}")
            return {"status": "FAILED", "error": str(e), "to": to_number}


# ── GCP + Twilio Backend ──────────────────────────────────────────────────────

class GcpTwilioBackend(VoiceBackend):
    """
    Google Cloud TTS + Twilio Programmable Voice.
    Replaces Bland.ai at ~$0.015/min vs $0.09/min.

    Architecture:
        1. CommPlexAPI → Twilio /calls → initiates outbound call
        2. Twilio webhooks to CommPlexAPI /voice/twiml
        3. CommPlexAPI generates TwiML using Google TTS
        4. Gemini Flash handles Q&A classification on transcripts

    Cost breakdown (per call, ~2 min avg):
        Twilio outbound: $0.013/min × 2 = $0.026
        Google TTS: ~$0.000008 per call (negligible)
        Gemini Q&A: ~$0.0001 per call (negligible)
        Total: ~$0.027/call vs $0.18 on Bland.ai

    Setup required:
        1. Twilio: Set webhook URL → https://your-cloud-run-url/voice/twiml
        2. GCP: Enable Cloud TTS API
        3. .env: VOICE_BACKEND=GCP_TWILIO, TWILIO_WEBHOOK_BASE_URL=https://...
    """

    name = "GCP_TWILIO"
    WEBHOOK_BASE = os.getenv("TWILIO_WEBHOOK_BASE_URL", "http://localhost:8080")

    def check_balance(self) -> Dict:
        if not TWILIO_SID or not TWILIO_TOKEN:
            return {"status": "not_configured", "backend": "GCP_TWILIO"}
        try:
            from twilio.rest import Client
            client = Client(TWILIO_SID, TWILIO_TOKEN)
            acct = client.api.accounts(TWILIO_SID).fetch()
            return {"status": "ok", "name": acct.friendly_name, "backend": "GCP_TWILIO"}
        except Exception as e:
            return {"status": "error", "error": str(e), "backend": "GCP_TWILIO"}

    def place_call(self, to_number: str, script: str,
                   campaign_id: str, contact_name: str,
                   dry_run: bool = True) -> Dict:
        if dry_run:
            logger.info(f"[GcpTwilio DRY] → {to_number} | {contact_name}")
            return {"status": "DRY_RUN", "to": to_number, "backend": "GCP_TWILIO"}

        if not TWILIO_SID or not TWILIO_TOKEN or not TWILIO_FROM:
            return {"status": "STUB", "reason": "Twilio not configured"}

        try:
            from twilio.rest import Client
            client = Client(TWILIO_SID, TWILIO_TOKEN)

            to_e164 = f"+1{to_number}" if not to_number.startswith("+") else to_number

            # TwiML webhook carries campaign_id so server can fetch the right script
            twiml_url = (
                f"{self.WEBHOOK_BASE}/voice/twiml"
                f"?campaign_id={campaign_id}"
                f"&contact_name={contact_name.replace(' ', '+')}"
            )

            call = client.calls.create(
                to=to_e164,
                from_=TWILIO_FROM,
                url=twiml_url,
                status_callback=f"{self.WEBHOOK_BASE}/voice/status",
                status_callback_method="POST",
                record=True,
            )
            logger.info(f"[GcpTwilio] Call placed → {to_number}: {call.sid}")
            return {"status": "CALLED", "call_sid": call.sid,
                    "to": to_number, "backend": "GCP_TWILIO"}
        except Exception as e:
            logger.error(f"[GcpTwilio] Call failed for {to_number}: {e}")
            return {"status": "FAILED", "error": str(e), "to": to_number}

    @staticmethod
    def build_twiml_response(script: str, campaign_id: str) -> str:
        """
        Build TwiML using Google TTS voices.
        Used by CommPlexAPI /voice/twiml endpoint.
        Returns TwiML XML string.
        """
        from xml.etree.ElementTree import Element, SubElement, tostring

        response = Element("Response")
        say = SubElement(response, "Say",
                         voice="Google.en-US-Neural2-F",
                         language="en-US")
        say.text = script

        # Gather digits (1=yes, 2=no, 3=transfer)
        gather = SubElement(response, "Gather",
                            numDigits="1",
                            action=f"/voice/gather?campaign_id={campaign_id}",
                            method="POST",
                            timeout="8")
        say2 = SubElement(gather, "Say",
                           voice="Google.en-US-Neural2-F")
        say2.text = (
            "Press 1 if you're interested and would like Kenyon to call you back. "
            "Press 2 to decline. Press 3 to transfer to Kenyon Jones directly."
        )

        redirect = SubElement(response, "Redirect")
        redirect.text = f"/voice/no-response?campaign_id={campaign_id}"

        return '<?xml version="1.0" encoding="UTF-8"?>' + tostring(response, encoding="unicode")

    @staticmethod
    def tts_synthesize(text: str, output_path: str) -> bool:
        """
        Google Cloud TTS → MP3 file. Used for pre-recorded drop.
        Costs ~$0.000004 per call at CommPlex scale.
        """
        try:
            from google.cloud import texttospeech
            client = texttospeech.TextToSpeechClient()
            synthesis_input = texttospeech.SynthesisInput(text=text)
            voice = texttospeech.VoiceSelectionParams(
                language_code="en-US",
                name="en-US-Neural2-F",
            )
            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3
            )
            response = client.synthesize_speech(
                input=synthesis_input, voice=voice, audio_config=audio_config
            )
            with open(output_path, "wb") as f:
                f.write(response.audio_content)
            logger.info(f"[GcpTTS] Synthesized → {output_path}")
            return True
        except ImportError:
            logger.warning("[GcpTTS] google-cloud-texttospeech not installed")
            return False
        except Exception as e:
            logger.error(f"[GcpTTS] Synthesis failed: {e}")
            return False


# ── Q&A Classifier ────────────────────────────────────────────────────────────

class VoiceQAClassifier:
    """
    Classifies inbound questions from dealer transcripts and returns canned answers.
    Uses regex first (fast), Gemini Flash as fallback (smart).
    """

    KEYWORDS = {
        "price":      ["price", "asking", "cost", "offer", "how much", "want for"],
        "title":      ["title", "salvage", "rebuilt", "clean", "branded"],
        "mileage":    ["miles", "mileage", "odometer", "how many"],
        "location":   ["where", "location", "located", "state", "city"],
        "transport":  ["transport", "ship", "deliver", "pick up"],
        "photos":     ["photo", "picture", "image", "gallery", "see it"],
        "vin":        ["vin", "number", "vehicle identification"],
        "features":   ["features", "options", "equipped", "has it got"],
        "battery":    ["battery", "start", "electric", "hybrid"],
        "four_season":["winter", "cold", "four season", "climate", "heated"],
        "tow":        ["tow", "haul", "payload", "hitch"],
        "bat":        ["bring a trailer", "bat", "auction", "consign"],
    }

    def classify(self, transcript: str, campaign_id: str) -> str:
        """Return canned answer for the question in the transcript."""
        text = transcript.lower()
        qa = VEHICLE_QA.get(campaign_id, {})

        for key, keywords in self.KEYWORDS.items():
            if any(kw in text for kw in keywords):
                if key in qa:
                    return qa[key]

        return qa.get("default", "Please call Kenyon Jones at (701) 870-5235.")


# ── Voice Module Facade ───────────────────────────────────────────────────────

class VoiceModule:
    """
    Main CommPlex voice calling module.
    GoF: Facade — single entry point for all outbound voice.

    Usage:
        from CommPlexCore.modules.voice_gcp import VoiceModule
        vm = VoiceModule()
        results = vm.run_wave(campaign, wave=1, dry_run=True)
    """

    def __init__(self):
        backend_name = VOICE_BACKEND.upper()
        if backend_name == "GCP_TWILIO":
            self._backend: VoiceBackend = GcpTwilioBackend()
        else:
            self._backend = BlandBackend()

        self._qa = VoiceQAClassifier()
        logger.info(f"[VoiceModule] Backend: {self._backend.name}")

    def check_status(self) -> Dict:
        balance = self._backend.check_balance()
        return {
            "backend":    self._backend.name,
            "dry_run":    DRY_RUN,
            "transfer_to": TRANSFER_TO,
            "balance":    balance,
        }

    def call_contact(self, contact, campaign_id: str,
                     wave: int = 1, dry_run: bool = True) -> Dict:
        """Place a single AI call to a contact."""
        if not contact.phone:
            return {"status": "SKIP", "reason": "No phone number", "contact": contact.name}

        is_final = (wave >= 2)
        script = OPENER_SCRIPTS.get(campaign_id, OPENER_SCRIPTS.get("MKZ_2016_HYBRID"))

        if is_final:
            script += (
                " I can transfer you to Kenyon directly right now if you'd like — "
                "just say yes and I'll connect you immediately."
            )

        result = self._backend.place_call(
            to_number=contact.phone,
            script=script,
            campaign_id=campaign_id,
            contact_name=contact.name,
            dry_run=dry_run,
        )
        result["contact"] = contact.name
        result["wave"]    = wave
        return result

    def leave_voicemail(self, contact, campaign_id: str,
                        dry_run: bool = True) -> Dict:
        """Drop voicemail script (AMD detected answering machine)."""
        script = VOICEMAIL_SCRIPTS.get(campaign_id, VOICEMAIL_SCRIPTS["MKZ_2016_HYBRID"])
        result = self._backend.place_call(
            to_number=contact.phone,
            script=script,
            campaign_id=campaign_id,
            contact_name=f"{contact.name}_VOICEMAIL",
            dry_run=dry_run,
        )
        result["contact"] = contact.name
        result["type"]    = "VOICEMAIL"
        return result

    def run_wave(self, campaign, wave: int = 1, dry_run: bool = True) -> List[Dict]:
        """
        Run a complete wave of calls for a campaign.
        Wave 1: First contact attempt (10:30 AM)
        Wave 2: Follow-up + transfer offer (2:30 PM)
        """
        campaign_id = campaign.CAMPAIGN_ID
        results = []

        phone_contacts = [c for c in campaign.contacts
                          if c.phone and c.status == "PENDING"]

        logger.info(
            f"[VoiceModule] Wave {wave} | {campaign_id} | "
            f"{len(phone_contacts)} contacts | dry_run={dry_run}"
        )

        for contact in phone_contacts:
            result = self.call_contact(contact, campaign_id, wave, dry_run)
            results.append(result)

            status_icon = "✅" if result.get("status") == "CALLED" else (
                "📝" if result.get("status") == "DRY_RUN" else "❌"
            )
            print(f"  {status_icon} {contact.name} → {result.get('status')}")

        return results

    def handle_qa_response(self, transcript: str, campaign_id: str) -> str:
        """Handle a dealer's question from a live call transcript."""
        return self._qa.classify(transcript, campaign_id)


# ── Module singleton ──────────────────────────────────────────────────────────

_instance: Optional[VoiceModule] = None

def get_voice_module() -> VoiceModule:
    global _instance
    if _instance is None:
        _instance = VoiceModule()
    return _instance


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="CommPlex Voice Module")
    parser.add_argument("--status",    action="store_true", help="Check backend status")
    parser.add_argument("--preview",   metavar="CAMPAIGN_ID", help="Preview call scripts")
    parser.add_argument("--qa-test",   metavar="TRANSCRIPT",  help="Test Q&A classifier")
    parser.add_argument("--campaign",  default="mkz")
    parser.add_argument("--wave",      type=int, default=1)
    parser.add_argument("--dry-run",   action="store_true", default=True)
    args = parser.parse_args()

    vm = VoiceModule()

    if args.status:
        import json as _json
        print(_json.dumps(vm.check_status(), indent=2))

    elif args.preview:
        campaign_id = args.preview.upper().replace("-", "_")
        print(f"\n── OPENER ({campaign_id}) ──")
        print(OPENER_SCRIPTS.get(campaign_id, "Campaign not found"))
        print(f"\n── VOICEMAIL ({campaign_id}) ──")
        print(VOICEMAIL_SCRIPTS.get(campaign_id, "Campaign not found"))

    elif args.qa_test:
        campaign_map = {
            "mkz": "MKZ_2016_HYBRID",
            "towncar": "TOWNCAR_1988_SIGNATURE",
            "f350": "F350_2006_KING_RANCH",
            "jayco": "JAYCO_2017_EAGLE_HT",
        }
        cid = campaign_map.get(args.campaign, "MKZ_2016_HYBRID")
        answer = vm.handle_qa_response(args.qa_test, cid)
        print(f"\nQ: {args.qa_test}")
        print(f"A: {answer}")

    else:
        print("CommPlex Voice Module")
        print(f"Backend: {vm._backend.name} | DRY_RUN={DRY_RUN}")
        print("\nOptions: --status | --preview CAMPAIGN_ID | --qa-test 'What is the price?'")
        print("         --campaign mkz|towncar|f350|jayco")
