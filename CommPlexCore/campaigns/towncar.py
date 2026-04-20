"""
CommPlexCore/campaigns/towncar.py — 1988 Lincoln Town Car Signature Campaign
Domain: CommPlexCore (The Brain)

GoF: Concrete Template Method implementation of CommPlexSpec.BaseCampaign.
Split from legacy all_campaigns.py; fully CommPlex-domain-aware.

Primary channel: Bring a Trailer (BaT) — $10,000–$14,000 target.
Reserve: $9,500. Seller fee 5% (max $5,000).

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

_BAT_PARTNER = """\
Hello,

I'm reaching out because I have a strong Bring a Trailer candidate I believe \
would be a fit for your program.

1988 LINCOLN TOWN CAR SIGNATURE SERIES — 31,511 ACTUAL MILES
VIN: 1LNBM82FXJY779113 | Clean North Dakota Title

This is a documented time capsule. 31,511 miles on a 1988 Signature (top trim) \
in Oxford White with the Landau vinyl roof and wire spoke wheels. No rust, no panel \
damage. Windsor Velour interior — the preferred cloth over leather in this era \
(collectors confirm: velour outsells leather at auction; leather dries and cracks).

Disclosed items: dry rot on driver door panel (cosmetic), window module repair, \
A/C recharge, and suspension on springs. Total service estimate: $500–$700.

BaT comps: 30k-mile 1987 at $10,512; 22k-mile 1989 at $19,300.
Target: $10,000–$14,000. Reserve: $9,500.

18-photo catalog and complete documentation available immediately.
LOCATION: Hazen/Beulah, North Dakota.

Am I reaching the right person for consignment inquiries?

Kenyon Jones | (701) 870-5235 | kjonesmle@gmail.com
Cynthia Ennis (authorized) | (701) 946-5731"""

_DEFAULT = """\
Hello,

I have a 1988 Lincoln Town Car Signature Series for sale — 31,511 actual, original miles.
This is a genuine time capsule survivor in Oxford White. I believe it is a strong \
Bring a Trailer candidate.

VEHICLE:
• VIN: 1LNBM82FXJY779113
• Year / Trim: 1988 Lincoln Town Car — Signature Series (top trim)
• Mileage: 31,511 — Actual, Original, Verified
• Engine: 5.0L HO V8 (Ford 302) | AOD 4-Speed Automatic
• Exterior: Oxford White — Full Black Landau Vinyl Roof (excellent condition)
• Wheels: Styled Wire Spoke Wheels | Whitewall Tires — All Four
• Interior: Windsor Velour Split-Bench (Navy Blue) — soft, no cracking, collector-preferred
  Genuine Burl Wood-Grain Accents | 6-Way Power Driver Seat | Dual-Zone Climate
• Title: Clean North Dakota Title — Zero Liens

DISCLOSED ITEMS (fully factored into pricing):
• Driver door interior panel: dry rot — cosmetic (~$200–$300)
• Driver window module: fuse/module repair (~$80–$150)
• A/C: needs R134a recharge (~$120–$180)
• Suspension: on springs (air ride chains stowed) — drives fine
• Total estimated service: $500–$700

BaT COMPARABLE SALES (verified):
• 34k-mile 1988: $8,201 | 30k-mile 1987 Sail America: $10,512
• 22k-mile 1989: $19,300 | Our target with proper presentation: $10,000–$14,000.
• Reserve recommendation: $9,500.

LOCATION: Hazen / Beulah, North Dakota. Inspection by appointment.
18-photo gallery available. Full BaT submission package ready.

Kenyon Jones | (701) 870-5235 | kjonesmle@gmail.com
Cynthia Ennis (authorized) | (701) 946-5731"""


# ── TownCar Campaign ──────────────────────────────────────────────────────────

class TownCarCampaign(BaseCampaign):
    """
    1988 Lincoln Town Car Signature — BaT auction campaign.
    GoF: Concrete Template Method.

    Channel strategy:
        1. BaT Local Partners (email direct pitch)
        2. Hagerty / Hemmings consignment
        3. Mecum Indy / Tulsa (May/June 2026)
        4. BaT direct submission (form)
    """

    SLUG        = "towncar"
    CAMPAIGN_ID = "TOWNCAR_1988_SIGNATURE"
    VERSION     = "2.0"

    @property
    def vehicle_info(self) -> Dict:
        return {
            "display":   "1988 Lincoln Town Car Signature",
            "vin":       "1LNBM82FXJY779113",
            "year":      1988,
            "mileage":   "31,511",
            "color":     "Oxford White / Black Landau",
            "trim":      "Signature Series",
            "title":     "Clean ND Title — Zero Liens",
            "location":  "Hazen / Beulah, North Dakota",
            "asking":    "$12,000",
            "bat_range": "$10,000–$14,000",
            "reserve":   "$9,500",
            "note":      "Windsor Velour interior — collector premium over leather versions.",
            "alert":     None,
        }

    @property
    def messages(self) -> Dict[str, str]:
        return {
            "BAT_PARTNER": _BAT_PARTNER,
            "DEFAULT":     _DEFAULT,
        }

    @property
    def priority_contacts(self) -> List[Contact]:
        return [
            Contact(
                name="BaT Local Partners",
                email="localpartners@bringatrailer.com",
                tier="BAT_PARTNER", method="email",
                notes="Primary BaT channel — pitch directly to the curation team.",
            ),
            Contact(
                name="Motorcar Classics",
                email="info@motorcarcl\u200bassics.com",
                tier="BAT_PARTNER", method="email",
                notes="Cash offer this week — $9k–$13k range.",
            ),
            Contact(
                name="Hagerty / Hemmings Consignment",
                email="consign@hagerty.com",
                tier="BAT_PARTNER", method="email",
            ),
        ]

    @property
    def contacts(self) -> List[Contact]:
        return self.priority_contacts + [
            Contact(
                name="Throttlestop",
                email="info@throttlestop.com",
                phone="9208762277",
                tier="BAT_PARTNER", method="email",
                notes="BaT Local Partner — Elkhart Lake WI.",
            ),
            Contact(
                name="Black Mountain Motorworks",
                email="John@blackmountainmotorworks.com",
                tier="BAT_PARTNER", method="email",
                notes="BaT Local Partner — Denver CO.",
            ),
            Contact(
                name="Gateway Classic Cars",
                url="https://www.gatewayclassiccars.com/sell",
                tier="DEFAULT", method="form",
                notes="Active Town Car inventory — consignment option.",
            ),
            Contact(
                name="BaT Direct Submit",
                url="https://bringatrailer.com/submit-a-vehicle/",
                tier="DEFAULT", method="form",
                notes="Direct BaT submission — attach 50+ photos. Review required.",
            ),
            Contact(
                name="Mecum Consignment",
                url="https://www.mecum.com/consign/",
                tier="DEFAULT", method="form",
                notes="Mecum Indy May 8–16 2026 or Tulsa June 5–6 2026.",
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
                    logger.warning(
                        f"[TownCar Sluice] Anti-hallucination: price "
                        f"${result.price_detected} not in transcript for {dealer_name}"
                    )
                    result.qualified     = False
                    result.manual_review = True
            status = (
                STATUS_QUALIFIED    if result.qualified else
                STATUS_MANUAL_REVIEW if result.manual_review else
                STATUS_REJECTED
            )
            return {**result.to_dict(), "status": status}
        except ImportError:
            logger.warning("[TownCar] CommPlexCore vertex not available — PENDING")
            return {"qualified": False, "status": STATUS_PENDING,
                    "price_detected": None, "vehicle_year": None,
                    "reasoning": "CommPlexCore not linked", "manual_review": True}


# ── Module-level singleton ────────────────────────────────────────────────────

_instance: Optional[TownCarCampaign] = None

def get_campaign() -> TownCarCampaign:
    global _instance
    if _instance is None:
        _instance = TownCarCampaign()
    return _instance


if __name__ == "__main__":
    import json, logging
    logging.basicConfig(level=logging.INFO)
    c = TownCarCampaign()
    print(f"Campaign: {c}")
    print(json.dumps(c.summary(), indent=2))
    print(f"\nPriority contacts: {len(c.priority_contacts)}")
    for ct in c.priority_contacts:
        print(f"  {ct}")
    print(f"\n✅ TownCarCampaign checkpoint complete.")
