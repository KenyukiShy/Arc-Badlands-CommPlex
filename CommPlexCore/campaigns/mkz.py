"""
CommPlexCore/campaigns/mkz.py — Lincoln MKZ 2016 Hybrid Campaign
Domain: CommPlexCore (The Brain)

GoF: Concrete Template Method implementation of BaseCampaign.
Coordinates the Wave (outreach fan-out) and the Sluice (qualification).

⚡ PRIORITY CONTACT: Lucky's Towing — vehicle on their lot since Jan 2026.
   LUCKY_OFFER tier fires FIRST in all module runs.
"""

from __future__ import annotations
import logging
from typing import List, Dict, Optional

# Domain-correct import from CommPlexSpec (The Law)
try:
    from CommPlexSpec.campaigns.base import (
        BaseCampaign, Contact, SENDER,
        STATUS_PENDING, STATUS_QUALIFIED, STATUS_REJECTED, STATUS_MANUAL_REVIEW,
    )
except ImportError:
    # Local fallback for direct execution / testing
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from CommPlexSpec.campaigns.base import (
        BaseCampaign, Contact, SENDER,
        STATUS_PENDING, STATUS_QUALIFIED, STATUS_REJECTED, STATUS_MANUAL_REVIEW,
    )

logger = logging.getLogger(__name__)


# ── Message Tiers ─────────────────────────────────────────────────────────────

_LUCKYS_OFFER = f"""Hello,

My name is Kenyon Jones. I'm the owner of the 2016 Lincoln MKZ Hybrid (VIN: 3LN6L2LUXGR630397) \
currently on your lot at Lucky's Towing & Repair, 812 2nd St NW, Beulah ND 58523.

First — I want to apologize. The vehicle has been in your care since January 2026 and I have \
not reached out sooner than I should have. I'm working to resolve this as quickly as possible \
and I appreciate your patience.

DIRECT PURCHASE OFFER TO LUCKY'S:
I'd like to offer Lucky's the opportunity to purchase the vehicle directly at $2,500, which \
saves us both the hassle of a third-party sale. I am actively marketing this vehicle to dealers \
offering $3,500–$5,500. This is a transparent, fair offer.

VEHICLE:
• VIN: 3LN6L2LUXGR630397
• 2016 Lincoln MKZ Hybrid | ~100,000 miles | Beige | Select/Premier
• Title: Rebuilt (Bonded title in process — NDCC §39-05-20.3)
• Battery: 12V auxiliary needs recharge (~$100). Hybrid drivetrain fully unaffected.
• Features: Leather heated seats, 8" SYNC 3, backup camera, push-button start
• 41 MPG city / 39 MPG highway

DOCUMENTATION: Signed CA Bill of Sale, Zelle records ($4,995), bank statements, \
transport confirmation, active ND GEICO insurance.

If you're not interested in purchasing, I'd like to arrange removal within 10 days.

Kenyon Jones | (701) 870-5235 | kjonesmle@gmail.com
Cynthia Ennis (authorized) | (701) 946-5731
"""

_TIER1_INSTANT = """Hello,

I have a 2016 Lincoln MKZ Hybrid for sale and would like to know if you are interested in making an offer.

VEHICLE:
• VIN: 3LN6L2LUXGR630397
• Mileage: ~100,000 | Color: Beige | Trim: Select/Premier
• Title: Rebuilt (Previously Salvaged ND brand)
• Battery: 12V auxiliary needs recharge (~$100 fix). Hybrid drivetrain unaffected.

LOCATION: Lucky's Towing & Repair, 812 2nd St NW, Beulah ND 58523.
Transport can be arranged after offer agreed.

Kenyon Jones | (701) 870-5235 | kjonesmle@gmail.com
"""

_TIER3_LOCAL = """Hello,

My name is Kenyon Jones. I have a 2016 Lincoln MKZ Hybrid available and wanted to reach out \
to see if your dealership would be interested in making an offer.

VEHICLE DETAILS:
• VIN: 3LN6L2LUXGR630397
• Year/Model: 2016 Lincoln MKZ Hybrid
• Mileage: ~100,000 miles
• Color: Beige Exterior
• Trim: Select/Premier Package
• Title: Rebuilt Title (ND State, bonded title in process)
• Known Issue: 12V auxiliary battery needs recharge (~$100). Hybrid system unaffected.

The vehicle is currently located at Lucky's Towing & Repair, 812 2nd St NW, Beulah ND 58523. \
Transport or pickup can be arranged.

I have full documentation available: original bill of sale, payment records, \
and active insurance.

Please let me know if you'd like photos or have any questions.

Kenyon Jones
(701) 870-5235 | kjonesmle@gmail.com
Authorized: Cynthia Ennis | (701) 946-5731
"""

_DEFAULT = """Hello,

I have a 2016 Lincoln MKZ Hybrid available for purchase. I am looking for a fair offer.

Vehicle is located in Beulah, ND (Lucky's Towing). VIN: 3LN6L2LUXGR630397.
Title: Rebuilt. Condition: Good — minor 12V battery issue only.

Please contact me if interested.

Kenyon Jones | (701) 870-5235 | kjonesmle@gmail.com
"""


# ── MKZ Campaign ──────────────────────────────────────────────────────────────

class MKZCampaign(BaseCampaign):
    """
    2016 Lincoln MKZ Hybrid procurement campaign.
    GoF: Concrete Template Method — implements BaseCampaign contract.

    Wave strategy:
        1. Lucky's direct offer (PRIORITY — vehicle on their lot)
        2. Tier 1 instant buyers (CarMax, Peddle, Carvana)
        3. Local ND/SD/MT dealers (Tier 3)
        4. Default outreach for all others

    Sluice integration:
        - classify_lead() called after each inbound transcript
        - verify_price() anti-hallucination guardrail on all AI-reported prices
        - QUALIFIED leads fire ntfy alert to Kenyon's Pixel 10
    """

    SLUG        = "mkz"
    CAMPAIGN_ID = "MKZ_2016_HYBRID"
    VERSION     = "2.0"   # Upgraded to CommPlex domain architecture

    @property
    def vehicle_info(self) -> Dict:
        return {
            "display":   "2016 Lincoln MKZ Hybrid",
            "vin":       "3LN6L2LUXGR630397",
            "year":      2016,
            "mileage":   "~100,000",
            "color":     "Beige",
            "trim":      "Select/Premier",
            "title":     "Rebuilt (Bonded title in process — NDCC §39-05-20.3)",
            "mpg":       "41 city / 39 hwy",
            "location":  "Lucky's Towing & Repair, 812 2nd St NW, Beulah ND 58523",
            "asking":    "$3,500–$5,500",
            "note":      "12V auxiliary battery needs recharge (~$100). Hybrid drivetrain unaffected.",
            "alert":     "⚡ PRIORITY: Vehicle at Lucky's since Jan 2026. Lucky's offer goes FIRST.",
            "features": [
                "Leather heated seats",
                "8\" SYNC 3 touchscreen",
                "Backup camera",
                "Push-button start",
                "41 MPG city hybrid",
            ],
        }

    @property
    def messages(self) -> Dict[str, str]:
        return {
            "LUCKY_OFFER": _LUCKYS_OFFER,
            "TIER1_INSTANT": _TIER1_INSTANT,
            "TIER3_LOCAL":   _TIER3_LOCAL,
            "DEFAULT":       _DEFAULT,
        }

    @property
    def priority_contacts(self) -> List[Contact]:
        """Lucky's Towing — must be first in every wave."""
        return [
            Contact(
                name="Lucky's Towing & Repair",
                phone="7015485277",
                email=None,
                url=None,
                tier="LUCKY_OFFER",
                method="phone",
                notes="Vehicle on their lot since January 2026. Priority outreach.",
            ),
        ]

    @property
    def contacts(self) -> List[Contact]:
        """Full contact list. Priority contacts first, then tiered outreach."""
        return self.priority_contacts + self._tier1_contacts + self._tier3_contacts + self._default_contacts

    @property
    def _tier1_contacts(self) -> List[Contact]:
        """Instant buyers — Tier 1."""
        return [
            Contact(name="CarMax Fargo",    phone="7012823300", tier="TIER1_INSTANT", method="phone"),
            Contact(name="Peddle.com",      url="https://www.peddle.com/sell-car",
                    tier="TIER1_INSTANT", method="form"),
            Contact(name="Carvana",         url="https://www.carvana.com/sell-my-car",
                    tier="TIER1_INSTANT", method="form"),
            Contact(name="We Buy Any Car",  url="https://www.webuyanycar.com",
                    tier="TIER1_INSTANT", method="form"),
        ]

    @property
    def _tier3_contacts(self) -> List[Contact]:
        """Local ND/SD/MT dealer outreach — Tier 3."""
        return [
            Contact(name="Luther Family Ford Bismarck",
                    phone="7012231200", email="sales@lutherbismarck.com",
                    tier="TIER3_LOCAL", method="phone",
                    notes="Large regional dealer, takes rebuilt titles"),
            Contact(name="Corwin Honda Fargo",
                    phone="7012823700",
                    tier="TIER3_LOCAL", method="phone"),
            Contact(name="Rydell Chevrolet Grand Forks",
                    phone="7017758811",
                    tier="TIER3_LOCAL", method="phone"),
            Contact(name="Minot Motors",
                    phone="7018522000",
                    tier="TIER3_LOCAL", method="phone"),
            Contact(name="Spitzer Chrysler Dodge Beulah",
                    phone="7018735000",
                    tier="TIER3_LOCAL", method="phone",
                    notes="Local — same town as vehicle"),
        ]

    @property
    def _default_contacts(self) -> List[Contact]:
        """General outreach contacts — Default tier."""
        return [
            Contact(name="Auto Trader Listing",
                    url="https://www.autotrader.com/sell-your-car",
                    tier="DEFAULT", method="form"),
            Contact(name="Cars.com Listing",
                    url="https://www.cars.com/sell/",
                    tier="DEFAULT", method="form"),
        ]

    # ── Sluice Integration ────────────────────────────────────────────────────

    def qualify_inbound(self, transcript: str, dealer_name: str = "",
                        sluice_mode: str = "standard") -> Dict:
        """
        Run inbound transcript through the CommPlexCore SluiceEngine.

        Args:
            transcript:   Raw dealer call transcript
            dealer_name:  Dealer name for logging
            sluice_mode:  "standard" ($28,500) or "aggressive" ($24,000)

        Returns:
            Dict with: qualified, status, price, vehicle_year, reasoning, manual_review
        """
        try:
            from CommPlexCore.gcp.vertex import get_classifier
            clf    = get_classifier(sluice_mode=sluice_mode)
            result = clf.classify_lead(transcript, sluice_mode=sluice_mode)

            # Anti-hallucination final check using Spec's guardrail
            if result.qualified and result.price_detected:
                verified = self.verify_price(transcript, result.price_detected)
                if not verified:
                    logger.warning(
                        f"[MKZ Sluice] Anti-hallucination: price ${result.price_detected} "
                        f"not in transcript for {dealer_name}"
                    )
                    result.qualified     = False
                    result.manual_review = True

            status = (
                STATUS_QUALIFIED    if result.qualified else
                STATUS_MANUAL_REVIEW if result.manual_review else
                STATUS_REJECTED
            )
            logger.info(
                f"[MKZ Sluice] {dealer_name or 'Unknown'} → {status} "
                f"(price={result.price_detected}, year={result.vehicle_year})"
            )
            return {**result.to_dict(), "status": status}

        except ImportError:
            logger.warning("[MKZ] CommPlexCore vertex not available — returning PENDING")
            return {
                "qualified": False, "status": STATUS_PENDING,
                "price_detected": None, "vehicle_year": None,
                "reasoning": "CommPlexCore not linked — manual review",
                "manual_review": True,
            }


# ── Module-level singleton ────────────────────────────────────────────────────

_instance: Optional[MKZCampaign] = None

def get_campaign() -> MKZCampaign:
    global _instance
    if _instance is None:
        _instance = MKZCampaign()
    return _instance


# ── CLI / Quick Test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO)

    print("=" * 60)
    print("CommPlexCore — MKZCampaign Test")
    print("=" * 60)

    c = MKZCampaign()
    print(f"\nCampaign: {c}")
    print(f"\nSummary:\n{json.dumps(c.summary(), indent=2)}")

    print(f"\nPriority contacts ({len(c.priority_contacts)}):")
    for contact in c.priority_contacts:
        print(f"  {contact}")

    print(f"\nAll contacts ({len(c.contacts)}):")
    for contact in c.contacts:
        print(f"  {contact}")

    print("\n── Sluice Test ──")
    test_cases = [
        ("Fargo Ford",    "I've got a 2021 Lincoln, I could do $25,000.", "standard"),
        ("Bismarck Auto", "I want $32,000 for my 2022 Lincoln.", "standard"),
        ("Minot Motors",  "I can do $23,500 for the 2021 Lincoln.", "aggressive"),
    ]
    for dealer, transcript, mode in test_cases:
        result = c.qualify_inbound(transcript, dealer, sluice_mode=mode)
        print(f"\n  Dealer:  {dealer}")
        print(f"  Mode:    {mode}")
        print(f"  Status:  {result['status']}")
        print(f"  Price:   {result.get('price_detected')}")
        print(f"  Year:    {result.get('vehicle_year')}")

    print("\n✅ MKZCampaign checkpoint complete.")
