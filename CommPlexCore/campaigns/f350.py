"""
CommPlexCore/campaigns/f350.py — 2006 Ford F-350 King Ranch Campaign
Domain: CommPlexCore (The Brain)

GoF: Concrete Template Method implementation of CommPlexSpec.BaseCampaign.
Split from legacy all_campaigns.py; fully CommPlex-domain-aware.

Primary channel: Bring a Trailer + collector specialists.
BaT target: $28,000–$36,000. Reserve: $22,000.

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

_BAT_UNICORN = """\
Hello,

I'm reaching out because I have what I believe is a rare Bring a Trailer candidate \
currently stored in Douglasville, Georgia.

2006 FORD F-350 KING RANCH V10 — THE "UNICORN" SPEC
• Crew Cab, 8-ft Long Bed, Single Rear Wheel, 4×4
• 47,000 original miles. Clean Georgia Title. Zero accidents.
• 6.8L Triton V10 — No diesel headaches, no 6.0L risk, no DEF
• Factory 5th Wheel Kingpin Hitch installed

WHY BaT: This is for the collector who wants the King Ranch aesthetic and 1-ton \
capacity and specifically avoids the diesel. A clean, low-mile V10 King Ranch in \
this configuration is nearly impossible to find. The truck spent its entire life \
towing one fifth wheel — never a daily driver.

The Castaño saddle leather (pre-2008 untreated hide) is in bright, unfaded condition. \
Collectors pay $5,000–$8,000 over a high-mileage example specifically for this leather.

BaT gas V10 comp: 26k-mile 2000 F-250 sold $31,250 in January 2026.
Specialist dealers list <40k-mile V10 King Ranch at $32,000–$38,000 retail.
Reserve: $22,000. Target hammer: $28,000–$36,000.

Photos and on-site access via Doug & Sherrie Appleby (770-315-1949), Douglasville GA.
I am ready to sign and transport immediately.

Kenyon Jones | (701) 870-5235 | kjonesmle@gmail.com"""

_DEFAULT = """\
Hello,

My name is Kenyon Jones. I have a 2006 Ford F-350 Super Duty King Ranch for sale and \
I believe it may be a strong candidate for your consignment or auction program.

THE TRUCK:
• VIN: 1FTWW31Y86EA12357 | Clean Georgia Title
• Year / Trim: 2006 F-350 Super Duty — King Ranch Edition (top trim)
• Engine: 6.8L Triton V10 Gas | 6-Speed SelectShift Automatic
• Cab / Bed: Crew Cab 4-Door / Long Bed (8 ft) with Bed Cap / Topper
• Drivetrain: 4×4 Selectable | GCWR ~18,000 lbs
• Mileage: ~47,000 Actual Miles — Verified
• Exterior: Oxford White
• Interior: King Ranch Castaño Saddle Brown Untreated Leather — Heated Front Seats
  King Ranch embossed medallion | Genuine wood-grain accents
• Tow Package: Factory 5th Wheel Kingpin Hitch — pre-wired, day-1 ready

THE STORY: This truck spent its entire life towing a single fifth wheel trailer. \
47,000 miles on a 2006 F-350 King Ranch is a genuine standout.

PRE-LISTING PREP NEEDED (transparent disclosure):
• Professional detail and wash | Standard tune-up | Tire inspection
• Estimated total: $400–$900

On-site contacts: Doug & Sherrie Appleby (770-315-1949) — Douglasville, GA.

Kenyon Jones | (701) 870-5235 | kjonesmle@gmail.com
Cynthia Ennis (authorized) | (701) 946-5731"""


# ── F350 Campaign ─────────────────────────────────────────────────────────────

class F350Campaign(BaseCampaign):
    """
    2006 Ford F-350 King Ranch V10 campaign.
    GoF: Concrete Template Method.

    Channel strategy:
        1. BaT Local Partners — unicorn pitch
        2. Collector/auction specialists near Douglasville GA
        3. Mecum Indy (May 2026)
        4. BaT direct submission
    """

    SLUG        = "f350"
    CAMPAIGN_ID = "F350_2006_KING_RANCH"
    VERSION     = "2.0"

    @property
    def vehicle_info(self) -> Dict:
        return {
            "display":   "2006 Ford F-350 King Ranch V10",
            "vin":       "1FTWW31Y86EA12357",
            "year":      2006,
            "mileage":   "~47,000",
            "color":     "Oxford White",
            "trim":      "King Ranch (top trim above Lariat)",
            "title":     "Clean GA Title",
            "location":  "Douglasville, GA 30134",
            "onsite":    "Doug & Sherrie Appleby | (770) 315-1949",
            "asking":    "$31,000",
            "bat_range": "$28,000–$36,000",
            "reserve":   "$22,000",
            "note":      "Professional detail + photo shoot required before any listing. "
                         "Coordinate with Sherrie Appleby.",
            "alert":     None,
        }

    @property
    def messages(self) -> Dict[str, str]:
        return {
            "BAT_UNICORN": _BAT_UNICORN,
            "DEFAULT":     _DEFAULT,
        }

    @property
    def priority_contacts(self) -> List[Contact]:
        return [
            Contact(
                name="BaT Local Partners",
                email="localpartners@bringatrailer.com",
                tier="BAT_UNICORN", method="email",
                notes="Primary BaT channel — unicorn V10 King Ranch pitch.",
            ),
            Contact(
                name="The Patina Group NC",
                url="https://www.bringatrailer.com/local-partners/",
                tier="BAT_UNICORN", method="form",
                notes="Statesville NC ~330mi from Douglasville. Closest BaT partner.",
            ),
            Contact(
                name="RK Motors Charlotte",
                phone="7045965211",
                email="sales@rkmotors.com",
                tier="BAT_UNICORN", method="email",
                notes="Charlotte NC ~240mi — large classic car dealer, professional.",
            ),
            Contact(
                name="Bullet Motorsports",
                email="sales@bulletmotorsport.com",
                phone="9543632261",
                tier="BAT_UNICORN", method="email",
                notes="Fort Lauderdale FL — BaT partner.",
            ),
            Contact(
                name="Gulf Coast Exotic",
                tier="BAT_UNICORN", method="email",
                notes="Gulfport MS ~370mi — BaT partner.",
            ),
        ]

    @property
    def contacts(self) -> List[Contact]:
        return self.priority_contacts + [
            Contact(
                name="GAA Classic Cars",
                url="https://www.gaaclassiccars.com/how-to-sell",
                tier="DEFAULT", method="form",
                notes="Greensboro NC — July 23-25 2026. CONSIGN NOW for best slot.",
            ),
            Contact(
                name="Vicari Auction",
                url="https://vicariauction.com/sell-a-car/",
                tier="DEFAULT", method="form",
                notes="Biloxi MS May 1–2 2026. Deadline approaching — submit immediately.",
            ),
            Contact(
                name="Mecum Consignment",
                url="https://www.mecum.com/consign/",
                tier="DEFAULT", method="form",
                notes="Mecum Indy May 8–16 2026 — best domestic collector truck auction.",
            ),
            Contact(
                name="BaT Direct Submit",
                url="https://bringatrailer.com/submit-a-vehicle/",
                tier="DEFAULT", method="form",
                notes="Direct BaT submission — 50+ photos required. Sherrie shoots first.",
            ),
            Contact(
                name="Cars & Bids",
                url="https://carsandbids.com",
                tier="DEFAULT", method="form",
                notes="Backup to BaT — modern enthusiast audience.",
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
                    logger.warning(f"[F350 Sluice] Anti-hallucination flag for {dealer_name}")
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

_instance: Optional[F350Campaign] = None

def get_campaign() -> F350Campaign:
    global _instance
    if _instance is None:
        _instance = F350Campaign()
    return _instance


if __name__ == "__main__":
    import json, logging
    logging.basicConfig(level=logging.INFO)
    c = F350Campaign()
    print(f"Campaign: {c}")
    print(json.dumps(c.summary(), indent=2))
    print(f"\n✅ F350Campaign checkpoint complete.")
