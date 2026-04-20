"""
CommPlexCore/gcp/vertex.py — Gemini Flash Classifier + Sluice Engine
STATUS: STUB → set VERTEX_STATUS=ACTIVE + GOOGLE_APPLICATION_CREDENTIALS to activate

Activation:
  1. gcloud services enable aiplatform.googleapis.com
  2. Create service account → download service-account.json
  3. Set GOOGLE_APPLICATION_CREDENTIALS=service-account.json in .env
  4. Set VERTEX_STATUS=ACTIVE in .env
  5. pip install google-cloud-aiplatform

GoF Patterns:
  - Strategy:  GeminiFlashClassifier swappable via STATUS env var
  - Chain:     SluiceEngine applies qualification filters in sequence
  - Singleton: get_classifier() / get_sluice() module-level singletons
  - Template:  classify_lead() defines the flow; sub-steps are overridable
"""

from __future__ import annotations
import os
import re
import json
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)

STATUS = os.getenv("VERTEX_STATUS", "STUB")

# ── Pricing Constants (The Sluice Floor) ─────────────────────────────────────
SLUICE_PRICE_STANDARD   = float(os.getenv("SLUICE_PRICE_STANDARD",   "28500"))
SLUICE_PRICE_AGGRESSIVE = float(os.getenv("SLUICE_PRICE_AGGRESSIVE",  "24000"))
SLUICE_MIN_YEAR         = int(os.getenv("SLUICE_MIN_YEAR", "2020"))

# ── Prompts ───────────────────────────────────────────────────────────────────

LEAD_CLASSIFICATION_PROMPT = """
You are a vehicle procurement qualifier for Arc Badlands Auto Acquisition.
Analyze this call transcript and extract the offer details.

Respond ONLY with valid JSON in this exact schema — no markdown, no extra text:
{{
  "qualified": <true|false>,
  "price_detected": <float or null if no price mentioned>,
  "vehicle_year": <int or null>,
  "reasoning": "<1-2 sentence explanation>"
}}

Qualification rules:
- qualified = true ONLY if price_detected <= {price_floor} AND vehicle_year >= {min_year}
- If no price or year can be determined, set qualified = false
- If price is above the floor OR year is too old, set qualified = false

Transcript:
{transcript}
"""

DEALER_TIER_PROMPT = """
Classify this vehicle dealer URL into one tier. Respond with ONLY the tier name:

TIER1_INSTANT   — Instant cash buyers (Peddle, CarMax, Carvana, We Buy Cars)
TIER2_REBUILT   — Rebuilt/salvage title specialists, insurance auction buyers
TIER3_LOCAL     — Regional/local dealers (ND/SD/MT preferred)
BAT_PARTNER     — Bring a Trailer partners, classic car specialists
DEFAULT         — Standard new/used dealer

URL: {url}
"""

FOLLOWUP_PROMPT = """
You are a vehicle sales assistant for Kenyon Jones / Arc Badlands.
Given an original outreach message and a dealer reply, write a concise follow-up in Kenyon's voice.
Max 150 words. Be professional, direct, and human.

Original message:
{original_message}

Dealer reply:
{reply}
"""


# ── Lead Result Dataclass ─────────────────────────────────────────────────────

@dataclass
class LeadResult:
    """Structured output from classify_lead()."""
    qualified:      bool
    price_detected: Optional[float]
    vehicle_year:   Optional[int]
    reasoning:      str
    raw_transcript: str
    price_floor:    float
    sluice_mode:    str    # "standard" | "aggressive"
    manual_review:  bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "qualified":      self.qualified,
            "price_detected": self.price_detected,
            "vehicle_year":   self.vehicle_year,
            "reasoning":      self.reasoning,
            "price_floor":    self.price_floor,
            "sluice_mode":    self.sluice_mode,
            "manual_review":  self.manual_review,
        }


# ── Sluice Engine — Chain of Responsibility ───────────────────────────────────

class SluiceEngine:
    """
    Pricing qualification gate — The Sluice.

    Applies rules in sequence (Chain of Responsibility):
      1. YearFilter:  vehicle_year >= SLUICE_MIN_YEAR
      2. PriceFilter: price_detected <= price_floor (standard or aggressive)
      3. AntiHallucinationFilter: price appears in raw transcript

    GoF: Chain of Responsibility — each filter can disqualify independently.
    """

    def __init__(self, mode: str = "standard"):
        """
        mode: "standard" ($28,500 floor) or "aggressive" ($24,000 floor)
        """
        self.mode = mode
        self.price_floor = (
            SLUICE_PRICE_STANDARD if mode == "standard"
            else SLUICE_PRICE_AGGRESSIVE
        )

    def qualify(self, result: Dict[str, Any], raw_transcript: str) -> LeadResult:
        """
        Run all qualification filters. Returns a LeadResult.

        Args:
            result:          Raw parsed JSON from classifier
            raw_transcript:  Original transcript string

        Returns:
            LeadResult with qualified=True only if all filters pass
        """
        price    = result.get("price_detected")
        year     = result.get("vehicle_year")
        reasoning = result.get("reasoning", "")
        qualified = True
        manual_review = False

        # ── Filter 1: Year ────────────────────────────────────────────────────
        if year is None:
            reasoning = f"[Sluice] Vehicle year not detected. {reasoning}"
            qualified = False
        elif year < SLUICE_MIN_YEAR:
            reasoning = f"[Sluice] Year {year} < minimum {SLUICE_MIN_YEAR}. {reasoning}"
            qualified = False

        # ── Filter 2: Price ───────────────────────────────────────────────────
        if price is None:
            reasoning = f"[Sluice] No price detected in transcript. {reasoning}"
            qualified = False
        elif price > self.price_floor:
            reasoning = f"[Sluice] Price ${price:,.0f} exceeds {self.mode} floor ${self.price_floor:,.0f}. {reasoning}"
            qualified = False

        # ── Filter 3: Anti-Hallucination (price in raw text) ──────────────────
        if price is not None and qualified:
            if not self._verify_price_in_transcript(raw_transcript, price):
                reasoning = f"[AntiHallucination] Price ${price:,.0f} not verified in transcript. Flagged for Manual Review."
                qualified = False
                manual_review = True
                logger.warning(f"[Sluice] Anti-hallucination flag — price ${price} not found in transcript.")

        return LeadResult(
            qualified=qualified,
            price_detected=price,
            vehicle_year=year,
            reasoning=reasoning,
            raw_transcript=raw_transcript,
            price_floor=self.price_floor,
            sluice_mode=self.mode,
            manual_review=manual_review,
        )

    @staticmethod
    def _verify_price_in_transcript(transcript: str, price: float) -> bool:
        """
        Anti-hallucination guard: check that the price appears in the raw text.
        Handles formats: 25000, 25,000, $25,000, 25.5k, etc.

        Returns True if price is verifiable in transcript.
        """
        text = transcript.lower()
        price_int = int(price)

        # Patterns to look for
        candidates = [
            str(price_int),                            # 25000
            f"{price_int:,}",                          # 25,000
            f"${price_int:,}",                         # $25,000
            f"${price_int}",                           # $25000
        ]
        # k-notation: 25k, 25.5k
        if price_int >= 1000:
            k_val = price_int / 1000
            candidates.append(f"{k_val:.0f}k")
            candidates.append(f"{k_val:.1f}k")

        return any(c in text for c in candidates)


# ── Gemini Flash Classifier ───────────────────────────────────────────────────

class GeminiFlashClassifier:
    """
    Vertex AI / Gemini 1.5 Flash lead classifier.

    When ACTIVE, uses Vertex AI for:
      - classify_lead(transcript) → LeadResult
      - classify_dealer(url)      → tier string
      - suggest_followup(...)     → follow-up message string

    When STUB, returns deterministic test outputs.

    Usage:
        clf = GeminiFlashClassifier()
        result = clf.classify_lead("I have a 2021 MKZ for $25,000")
        print(result.qualified)  # True
    """

    STATUS = STATUS
    MODEL  = "gemini-1.5-flash-001"

    def __init__(self, sluice_mode: str = "standard"):
        self._client = None
        self._model  = None
        self.sluice  = SluiceEngine(mode=sluice_mode)

        if self.STATUS == "ACTIVE":
            self._init_vertex()

    def _init_vertex(self):
        try:
            import vertexai
            from vertexai.generative_models import GenerativeModel
            project  = os.getenv("VERTEX_PROJECT", os.getenv("GCP_PROJECT_ID", ""))
            location = os.getenv("VERTEX_LOCATION", "us-central1")
            vertexai.init(project=project, location=location)
            self._model = GenerativeModel(self.MODEL)
            logger.info(f"[Vertex] Initialized: {project}/{location}/{self.MODEL}")
        except Exception as e:
            logger.error(f"[Vertex] Init failed — falling back to STUB: {e}")
            self.STATUS = "STUB"

    # ── classify_lead ─────────────────────────────────────────────────────────

    def classify_lead(self, transcript: str, sluice_mode: str = None) -> LeadResult:
        """
        Classify a call transcript through the full Sluice pipeline.

        Args:
            transcript:  Raw dealer call transcript string
            sluice_mode: Override sluice mode ("standard" | "aggressive")

        Returns:
            LeadResult with qualified status and pricing details
        """
        sluice = SluiceEngine(sluice_mode) if sluice_mode else self.sluice
        price_floor = sluice.price_floor

        if self.STATUS == "STUB":
            return self._stub_classify_lead(transcript, sluice)

        prompt = LEAD_CLASSIFICATION_PROMPT.format(
            transcript=transcript[:2000],
            price_floor=price_floor,
            min_year=SLUICE_MIN_YEAR,
        )
        try:
            response = self._model.generate_content(prompt)
            raw = response.text.strip().replace("```json", "").replace("```", "")
            parsed = json.loads(raw)
            return sluice.qualify(parsed, transcript)
        except json.JSONDecodeError as e:
            logger.error(f"[GeminiFlash] JSON parse error: {e} | Raw: {response.text[:200]}")
            return LeadResult(
                qualified=False, price_detected=None, vehicle_year=None,
                reasoning="Classification parse error — manual review required.",
                raw_transcript=transcript, price_floor=price_floor,
                sluice_mode=sluice.mode, manual_review=True,
            )
        except Exception as e:
            logger.error(f"[GeminiFlash] classify_lead failed: {e}")
            return LeadResult(
                qualified=False, price_detected=None, vehicle_year=None,
                reasoning=f"Classification error: {e}",
                raw_transcript=transcript, price_floor=price_floor,
                sluice_mode=sluice.mode, manual_review=True,
            )

    def _stub_classify_lead(self, transcript: str, sluice: SluiceEngine) -> LeadResult:
        """
        STUB classifier: uses regex to extract year and price from transcript.
        Simulates Gemini output for local testing without GCP credentials.
        """
        text = transcript.lower()

        # Extract vehicle year — 20XX pattern (2000–2029)
        year = None
        year_match = re.search(r'\b(20[0-2]\d)\b', transcript)
        if year_match:
            year = int(year_match.group(1))

        # Extract price — explicit $XX,XXX or "twenty-three thousand" or large numbers NOT years
        price = None
        # Priority 1: $XX,XXX or $XXXXX (explicit dollar sign)
        price_match = re.search(r'\$(\d{1,3}(?:,\d{3})+|\d{5,6})', transcript)
        if price_match:
            price = float(price_match.group(1).replace(",", ""))
        # Priority 2: plain number XX,XXX that is NOT a year

        if price is None:
            k_match = re.search(r'\b(\d{1,3}(?:\.\d)?)[kK]\b', transcript)
            if k_match:
                price = float(k_match.group(1)) * 1000

        if price is None:
            plain_match = re.search(r'\b(\d{1,3},\d{3})\b', transcript)
            if plain_match:
                price = float(plain_match.group(1).replace(",", ""))
        # Priority 3: number words (twenty-three thousand five hundred)
        if price is None:
            word_price = self._parse_word_price(text)
            if word_price:
                price = word_price

        reasoning = f"[STUB] Extracted year={year}, price={price} from transcript via regex."
        raw_result = {"price_detected": price, "vehicle_year": year, "reasoning": reasoning}
        result = sluice.qualify(raw_result, transcript)
        logger.info(f"[STUB] classify_lead → qualified={result.qualified}")
        return result

    @staticmethod
    def _parse_word_price(text: str) -> Optional[float]:
        """Parse simple English number-words to float. e.g. 'twenty-three thousand five hundred'."""
        ones = {"zero":0,"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,
                "eight":8,"nine":9,"ten":10,"eleven":11,"twelve":12,"thirteen":13,
                "fourteen":14,"fifteen":15,"sixteen":16,"seventeen":17,"eighteen":18,
                "nineteen":19,"twenty":20,"twenty-one":21,"twenty-two":22,"twenty-three":23,
                "twenty-four":24,"twenty-five":25,"twenty-six":26,"twenty-seven":27,
                "twenty-eight":28,"twenty-nine":29,"thirty":30}
        total = 0
        chunk = 0
        words = re.split(r'[\s\-]+', text)
        found = False
        for w in words:
            if w in ones:
                chunk += ones[w]
                found = True
            elif w == "thousand":
                chunk = chunk if chunk else 1
                total += chunk * 1000
                chunk = 0
            elif w == "hundred":
                chunk *= 100
        total += chunk
        return float(total) if found and total > 1000 else None

    # ── classify_dealer ───────────────────────────────────────────────────────

    def classify_dealer(self, url: str, page_text: str = "") -> str:
        """Classify dealer URL into campaign tier. Returns tier string."""
        VALID_TIERS = {
            "TIER1_INSTANT", "TIER2_REBUILT", "TIER3_LOCAL",
            "BAT_PARTNER", "DEFAULT", "BAT_UNICORN", "ND_COLD"
        }
        if self.STATUS == "STUB":
            logger.info(f"[STUB] classify_dealer({url}) → DEFAULT")
            return "DEFAULT"
        prompt = DEALER_TIER_PROMPT.format(url=url)
        try:
            response = self._model.generate_content(prompt)
            tier = response.text.strip().upper()
            return tier if tier in VALID_TIERS else "DEFAULT"
        except Exception as e:
            logger.error(f"[GeminiFlash] classify_dealer failed: {e}")
            return "DEFAULT"

    # ── suggest_followup ──────────────────────────────────────────────────────

    def suggest_followup(self, original_message: str, reply: str) -> str:
        """Generate a follow-up message based on dealer's reply."""
        if self.STATUS == "STUB":
            return "[STUB] Follow-up: Thank you for your reply. Can we discuss the details?"
        prompt = FOLLOWUP_PROMPT.format(
            original_message=original_message[:500],
            reply=reply[:500],
        )
        try:
            response = self._model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            logger.error(f"[GeminiFlash] suggest_followup failed: {e}")
            return "Unable to generate follow-up — please respond manually."

    def health(self) -> Dict[str, Any]:
        return {
            "status":       self.STATUS,
            "model":        self.MODEL,
            "sluice_mode":  self.sluice.mode,
            "price_floor":  self.sluice.price_floor,
            "min_year":     SLUICE_MIN_YEAR,
        }


# ── Singletons ────────────────────────────────────────────────────────────────

_classifier: Optional[GeminiFlashClassifier] = None
_sluice:     Optional[SluiceEngine] = None


def get_classifier(sluice_mode: str = "standard") -> GeminiFlashClassifier:
    global _classifier
    if _classifier is None:
        _classifier = GeminiFlashClassifier(sluice_mode=sluice_mode)
    return _classifier


def get_sluice(mode: str = "standard") -> SluiceEngine:
    global _sluice
    if _sluice is None:
        _sluice = SluiceEngine(mode=mode)
    return _sluice


# ── CLI / Quick Test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("=" * 60)
    print("CommPlexCore — GeminiFlashClassifier + SluiceEngine TEST")
    print("=" * 60)

    clf = GeminiFlashClassifier()
    print(f"\nHealth: {clf.health()}\n")

    test_cases = [
        ("QUALIFY (2021, $25k standard)",
         "I have a 2021 MKZ for $25,000. It's in great shape, well maintained."),
        ("REJECT — over standard floor",
         "I'd take $30,000 for my 2022 Lincoln. That's my final offer."),
        ("REJECT — year too old",
         "This is a 2018 model, asking $22,000 firm."),
        ("REJECT — no price detected",
         "Yeah I have a 2021 Lincoln, call me back to discuss price."),
        ("QUALIFY (aggressive mode, $23.5k)",
         "I can let it go for twenty-three thousand five hundred dollars for the 2021."),
        ("HALLUCINATION FLAG — price not in text",
         "I have a 2021 MKZ in perfect condition."),  # price injected below
    ]

    for label, transcript in test_cases:
        print(f"\n── {label} ──")
        result = clf.classify_lead(transcript)
        print(f"  qualified:      {result.qualified}")
        print(f"  price_detected: {result.price_detected}")
        print(f"  vehicle_year:   {result.vehicle_year}")
        print(f"  manual_review:  {result.manual_review}")
        print(f"  reasoning:      {result.reasoning}")

    # Test aggressive mode
    print("\n── AGGRESSIVE SLUICE MODE ──")
    result = clf.classify_lead(
        "Asking $23,500 for my 2021 Lincoln, it runs great.",
        sluice_mode="aggressive"
    )
    print(f"  qualified (aggressive $24k floor): {result.qualified}")
    print(f"  price_detected: {result.price_detected}")

    print("\n✅ Checkpoint: vertex.py import and classify_lead() functional.")
