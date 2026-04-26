"""
CommPlexCore/campaigns/jayco.py — 2017 Jayco Eagle HT 26.5BHS Campaign
Domain: CommPlexCore (The Brain)

GoF: Concrete Template Method implementation of CommPlexSpec.BaseCampaign.
Split from legacy all_campaigns.py; fully CommPlex-domain-aware.

NOTE: BaT does NOT accept 5th wheel RVs. Use Corral Sales + RV Trader + Steffes.
Primary channel: Corral Sales Mandan ND. Spring 2026 is peak ND buying season.

DEPENDENCY: CommPlexSpec.campaigns.base — THE LAW.
"""

from __future__ import annotations
import logging
from typing import List, Dict, Optional

try:
    from CommPlexSpec.campaigns.base import (
        BaseCampaign, Contact, SENDER,
        STATUS_PENDING, STATUS_QUALIFIED, STATUS_REJECTED, STATUS_MANUAL_REVIEW,
    )
except ImportError:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from CommPlexSpec.campaigns.base import (
        BaseCampaign, Contact, SENDER,
        STATUS_PENDING, STATUS_QUALIFIED, STATUS_REJECTED, STATUS_MANUAL_REVIEW,
    )

logger = logging.getLogger(__name__)


# ── Message Tiers ─────────────────────────────────────────────────────────────

_ND_COLD = """\
Hello,

I have a 2017 Jayco Eagle HT 26.5BHS — a 4-Season bunkhouse fifth wheel with approximately
2,400 actual tow miles, currently in Douglasville, Georgia, moving to North Dakota spring/summer 2026.

WHY THIS UNIT FOR YOUR MARKET:
The Climate Shield package (0°F rated, fully enclosed heated underbelly, PEX plumbing, \
double-layer fiberglass, forced-air heated tank system) is not a luxury feature in ND/SD/MT — \
it's a necessity. This unit has it. Southeast-stored — zero road salt exposure. Clean GA title.

SPECS:
• VIN: 1UJCJ0BPXH1P20237 | GA Title #770175206127980 — Clean, Zero Liens
• Half-ton towable (GVWR 9,950 lbs | Hitch Weight: 1,370 lbs)
• Sleeps 8–10 | Double-over-double bunkhouse | Single living area slide
• Walk-in shower with skylight | Full kitchen | Extra Clean 9/10 interior
• ~2,400 actual tow miles — essentially new use

DISCLOSED ITEMS (fully factored into pricing):
• Tires: Full tread, 2017 DOT code — age-recommend replacement (~$600–$800)
• Underbelly: Localized coroplast repair at one entry point, frame unaffected (~$293)
• Lippert rear auto-level jacks disengaged — front jacks and slide fully operational
• One cabinet hinge needs re-hanging (~$50)
• Total disclosed: ~$950–$1,200

ASKING: $27,000–$35,000 depending on scenario. Flexible for consignment terms.

On-site contact in GA: Doug & Sherrie Appleby (770-315-1949).
29-photo catalog + Sherrie walkthrough video available.

Kenyon Jones | (701) 870-5235 | kjonesmle@gmail.com"""

_DEFAULT = """\
Hello,

My name is Kenyon Jones. I have a 2017 Jayco Eagle HT 26.5BHS Four-Season Bunkhouse \
Fifth Wheel for sale — approximately 2,400 actual tow miles — and I believe it may be \
a strong fit for your program.

UNIT:
• VIN: 1UJCJ0BPXH1P20237 | GA Title #770175206127980 — Clean, Zero Liens
• Mileage: ~2,400 actual tow miles — essentially new use
• GVWR / UVW: 9,950 lbs / 7,582 lbs | Half-ton towable (F-150, RAM 1500, Silverado 1500)
• Four-Season: Jayco Climate Shield — rated to 0°F; fully enclosed heated underbelly
  PEX plumbing; double-layer fiberglass; forced-air heated tank system; dual-pane windows
• Floorplan: Rear bunkhouse — double-over-double bunks, private bath, sleeps 8–10
• Slide: Single (living area) | Full kitchen | Walk-in shower with skylight
• Interior: Extra Clean 9/10 — no water damage, smoke, pets, or odors
• Southeast stored — ZERO road salt. Currently in Douglasville, GA.

ASKING: $27,000–$35,000 (scenario-dependent)
On-site: Doug & Sherrie Appleby (770-315-1949) — photos, video, showings.

NOTE: BaT does not accept 5th wheel RVs. Corral Sales Mandan ND is the primary channel.

Kenyon Jones | (701) 870-5235 | kjonesmle@gmail.com
Cynthia Ennis (authorized) | (701) 946-5731"""

# ── SMS Variants (~160 chars, 1 segment) ──────────────────────────────────────

_ND_COLD_SMS = (
    "Kenyon Jones — 2017 Jayco Eagle HT 26.5BHS, 4-Season/Climate Shield, "
    "~2,400 tow miles, clean GA title. $27K–$35K, consignment OK. (701) 870-5235"
)

_DEFAULT_SMS = (
    "Kenyon Jones — 2017 Jayco Eagle HT 26.5BHS fifth wheel, ~2,400 tow miles, "
    "clean GA title. $27K–$35K, consignment welcome. (701) 870-5235"
)


# ── Jayco Campaign ────────────────────────────────────────────────────────────

class JaycoCampaign(BaseCampaign):
    """
    2017 Jayco Eagle HT 26.5BHS campaign.
    GoF: Concrete Template Method.

    Channel strategy:
        1. Corral Sales Mandan ND — primary ND consignment (spring peak)
        2. Integrity RV Douglasville — 3 miles from storage
        3. Capital RV + Roughrider RVs — ND regional dealers
        4. PPL Motor Homes Houston — largest RV consignment USA
        5. RV Trader / AuctionTime — online listing
    """

    SLUG        = "jayco"
    CAMPAIGN_ID = "JAYCO_2017_EAGLE_HT"
    VERSION     = "2.0"

    @property
    def vehicle_info(self) -> Dict:
        return {
            "display":   "2017 Jayco Eagle HT 26.5BHS",
            "vin":       "1UJCJ0BPXH1P20237",
            "ga_title":  "770175206127980",
            "year":      2017,
            "mileage":   "~2,400",
            "gvwr":      "9,950 lbs",
            "title":     "Clean GA Title — Zero Liens",
            "location":  "Douglasville, GA (moving to ND spring/summer 2026)",
            "onsite":    "Doug & Sherrie Appleby | (770) 315-1949",
            "corral":    "Corral Sales RV | (701) 663-9538 | hello@corralsales.com",
            "asking":    "$27,000–$35,000",
            "note":      "BaT does NOT accept 5th wheels. Corral Sales + RV Trader + Steffes Group.",
            "alert":     None,
        }

    @property
    def messages(self) -> Dict[str, str]:
        return {
            "ND_COLD":     _ND_COLD,
            "DEFAULT":     _DEFAULT,
            "ND_COLD_SMS": _ND_COLD_SMS,
            "DEFAULT_SMS": _DEFAULT_SMS,
        }

    @property
    def priority_contacts(self) -> List[Contact]:
        return [
            Contact(
                name="Corral Sales RV Mandan",
                email="hello@corralsales.com",
                phone="7016639538",
                tier="ND_COLD", method="email",
                notes="Primary ND consignment channel. Ask for lot space + listing terms. Submit FIRST.",
            ),
            Contact(
                name="Integrity RV Douglasville",
                phone="7706931186",
                tier="DEFAULT", method="phone",
                notes="3 miles from storage. Call and ask if they need a bunkhouse 5th wheel.",
            ),
            Contact(
                name="Capital RV Bismarck",
                phone="7012557878",
                url="https://www.capitalrv.com/bismarck/contact-us",
                tier="ND_COLD", method="form",
                notes="Big dealer in western ND — lead with Climate Shield.",
            ),
            Contact(
                name="Roughrider RVs Dickinson",
                phone="7014839844",
                url="https://www.roughriderrvs.net/contactus",
                tier="ND_COLD", method="form",
                notes="Oil field market — pitch as shelter/survival unit.",
            ),
        ]

    @property
    def contacts(self) -> List[Contact]:
        return self.priority_contacts + [
            Contact(
                name="Southland RV Norcross",
                phone="7707172890",
                url="https://www.southlandrv.com/consignment",
                tier="DEFAULT", method="form",
                notes="Atlanta area — high-end clientele, 30 min from unit.",
            ),
            Contact(
                name="PPL Motor Homes Houston",
                phone="8007554775",
                url="https://www.pplmotorhomes.com/rvconsignment",
                tier="DEFAULT", method="form",
                notes="Largest RV consignment dealer in USA. 10% commission.",
            ),
            Contact(
                name="Pifer's Auction Steele ND",
                phone="7014757653",
                url="https://www.pifers.com/contact",
                tier="ND_COLD", method="form",
                notes="King of ND equipment auction — pitch as oil field / hunting rig.",
            ),
            Contact(
                name="Steffes Group West Fargo",
                tier="ND_COLD", method="email",
                notes="BaT-equivalent for ND RV auction. Contact for spring consignment dates.",
            ),
            Contact(
                name="RV Trader Listing",
                url="https://www.rvtrader.com",
                tier="DEFAULT", method="form",
            ),
            Contact(
                name="AuctionTime ND",
                url="https://www.auctiontime.com",
                tier="ND_COLD", method="form",
            ),
        ]

    # ── Sluice Integration ────────────────────────────────────────────────────

    def qualify_inbound(self, transcript: str, dealer_name: str = "",
                        sluice_mode: str = "standard") -> Dict:
        """Run inbound transcript through CommPlexCore SluiceEngine."""
        try:
            from CommPlexCore.gcp.vertex import get_classifier
            clf    = get_classifier(sluice_mode=sluice_mode)
            result = clf.classify_lead(transcript, sluice_mode=sluice_mode)
            if result.qualified and result.price_detected:
                if not self.verify_price(transcript, result.price_detected):
                    result.qualified     = False
                    result.manual_review = True
            status = (
                STATUS_QUALIFIED    if result.qualified else
                STATUS_MANUAL_REVIEW if result.manual_review else
                STATUS_REJECTED
            )
            return {**result.to_dict(), "status": status}
        except ImportError:
            return {"qualified": False, "status": STATUS_PENDING,
                    "price_detected": None, "vehicle_year": None,
                    "reasoning": "CommPlexCore not linked", "manual_review": True}


# ── Module-level singleton ────────────────────────────────────────────────────

_instance: Optional[JaycoCampaign] = None

def get_campaign() -> JaycoCampaign:
    global _instance
    if _instance is None:
        _instance = JaycoCampaign()
    return _instance


if __name__ == "__main__":
    import json, logging
    logging.basicConfig(level=logging.INFO)
    c = JaycoCampaign()
    print(f"Campaign: {c}")
    print(json.dumps(c.summary(), indent=2))
    print(f"\nNote: {c.vehicle_info['note']}")
    print(f"\n✅ JaycoCampaign checkpoint complete.")
