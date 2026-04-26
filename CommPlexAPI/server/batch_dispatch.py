"""
CommPlexAPI/server/batch_dispatch.py — Outbound SMS Batch Dispatcher

Usage (always dry-run safe):
    python3 batch_dispatch.py              # preview only (DRY_RUN=true)
    DRY_RUN=false python3 batch_dispatch.py jayco   # live send for jayco

Filters applied before any send:
    - tier == TEST            → skipped
    - "LIVE call" in notes    → skipped (Cynthia handles live)
    - "not Slydialer" in notes → skipped
    - vehicle_interest must contain the campaign slug keyword

Message selection:
    - State in ND/SD/MT/MN → ND_COLD (cold-climate pitch)
    - All other states      → DEFAULT
"""

from __future__ import annotations

import csv
import os
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

# ── Paths ─────────────────────────────────────────────────────────────────────

_HERE     = Path(__file__).parent
_CSV_PATH = _HERE / "batch_dealers.csv"
_REPO     = _HERE.parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

DRY_RUN = os.getenv("DRY_RUN", "true").lower() != "false"

FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "+18667362349")

# States that get the cold-climate / ND-market pitch
_COLD_STATES = {"ND", "SD", "MT", "MN", "WI", "WY", "ID"}

# Keywords used to match vehicle_interest column to a campaign
_CAMPAIGN_KEYWORDS = {
    "jayco":   ["jayco"],
    "mkz":     ["mkz", "hybrid"],
    "towncar": ["town car", "towncar"],
    "f350":    ["f-350", "f350", "king ranch"],
}

# Notes substrings that flag a contact for human-only outreach
_SKIP_PHRASES = [
    "live call",
    "not slydialer",
    "listing coordination",
    "cynthia and sherrie handle direct",
]


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class DealerRow:
    idx:          int
    phone:        str
    name:         str
    company:      str
    city:         str
    state:        str
    interest:     str
    tier:         str
    notes:        str
    priority:     int


@dataclass
class QueueEntry:
    dealer:  DealerRow
    msg_key: str
    message: str


@dataclass
class SkipEntry:
    dealer: DealerRow
    reason: str


# ── Loader ────────────────────────────────────────────────────────────────────

def load_dealers(csv_path: Path = _CSV_PATH) -> List[DealerRow]:
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for i, row in enumerate(csv.DictReader(f), start=1):
            rows.append(DealerRow(
                idx=i,
                phone=row["phone_number"].strip(),
                name=row["contact_name"].strip(),
                company=row["company"].strip(),
                city=row["city"].strip(),
                state=row["state"].strip().upper(),
                interest=row["vehicle_interest"].strip(),
                tier=row["tier"].strip(),
                notes=row["notes"].strip(),
                priority=int(row.get("priority", 9) or 9),
            ))
    return rows


# ── Filter ────────────────────────────────────────────────────────────────────

def _matches_campaign(interest: str, slug: str) -> bool:
    kws = _CAMPAIGN_KEYWORDS.get(slug, [slug])
    return any(kw in interest.lower() for kw in kws)


def _skip_reason(dealer: DealerRow, slug: str) -> str | None:
    if dealer.tier.upper() == "TEST":
        return "tier=TEST"
    notes_lower = dealer.notes.lower()
    for phrase in _SKIP_PHRASES:
        if phrase in notes_lower:
            return f'notes: "{phrase}"'
    if not _matches_campaign(dealer.interest, slug):
        return f'vehicle_interest="{dealer.interest}"'
    return None


def filter_dealers(
    dealers: List[DealerRow], slug: str
) -> Tuple[List[QueueEntry], List[SkipEntry]]:
    from CommPlexCore.campaigns.registry import CampaignRegistry
    campaign = CampaignRegistry.get(slug)
    if campaign is None:
        raise ValueError(f"Unknown campaign slug: {slug!r}")

    queue: List[QueueEntry] = []
    skipped: List[SkipEntry] = []

    for d in dealers:
        reason = _skip_reason(d, slug)
        if reason:
            skipped.append(SkipEntry(dealer=d, reason=reason))
            continue
        base_key = "ND_COLD" if d.state in _COLD_STATES else "DEFAULT"
        # Prefer short SMS variant when the campaign defines one
        msg_key = base_key + "_SMS" if (base_key + "_SMS") in campaign.messages else base_key
        # Gracefully fall back if campaign doesn't have the expected key
        if msg_key not in campaign.messages:
            msg_key = next(iter(campaign.messages))
        queue.append(QueueEntry(
            dealer=d,
            msg_key=msg_key,
            message=campaign.messages[msg_key],
        ))

    # Sort: priority asc, then tier rank (T1 < T2 < T3 < FLOOR < FALLBACK)
    tier_rank = {"T1": 0, "T2": 1, "T3": 2, "FLOOR": 3, "FALLBACK": 4}
    queue.sort(key=lambda e: (e.dealer.priority, tier_rank.get(e.dealer.tier, 9)))
    return queue, skipped


# ── Preview ───────────────────────────────────────────────────────────────────

def _sms_segments(text: str, limit: int = 153) -> int:
    """Estimate Twilio concatenated SMS segments (153 chars per segment in multi-part)."""
    return 1 if len(text) <= 160 else -(-len(text) // limit)  # ceiling div


def preview_wave(queue: List[QueueEntry], skipped: List[SkipEntry], slug: str) -> None:
    w_co = 34
    print()
    print("=" * 70)
    print(f"  JAYCO WAVE — DRY-RUN PREVIEW   (DRY_RUN={DRY_RUN})")
    print(f"  Campaign: {slug.upper()}   From: {FROM_NUMBER}")
    print("=" * 70)

    # ── Queue ──────────────────────────────────────────────────────────────────
    print(f"\n  SEND QUEUE — {len(queue)} contact(s)\n")
    hdr = f"  {'#':>2}  {'Tier':<8} {'Company':<{w_co}} {'St':2}  {'Phone':14}  {'Msg':<8}  {'Ch':>4}  {'Seg':>3}"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for e in queue:
        d = e.dealer
        segs = _sms_segments(e.message)
        co = d.company[:w_co].ljust(w_co)
        print(f"  {d.idx:>2}  {d.tier:<8} {co} {d.state:2}  {d.phone:14}  {e.msg_key:<8}  {len(e.message):>4}  {segs:>3}")
        if d.notes:
            note = textwrap.shorten(d.notes, width=64, placeholder="…")
            print(f"  {'':2}  {'':8} {note}")

    # ── Skipped ────────────────────────────────────────────────────────────────
    print(f"\n  SKIPPED — {len(skipped)} contact(s)\n")
    hdr2 = f"  {'#':>2}  {'Tier':<8} {'Company':<{w_co}} {'Reason'}"
    print(hdr2)
    print("  " + "-" * (len(hdr2) - 2))
    for e in skipped:
        d = e.dealer
        co = d.company[:w_co].ljust(w_co)
        print(f"  {d.idx:>2}  {d.tier:<8} {co} {e.reason}")

    # ── Message previews ───────────────────────────────────────────────────────
    used_keys = sorted({e.msg_key for e in queue})
    from CommPlexCore.campaigns.registry import CampaignRegistry
    campaign = CampaignRegistry.get(slug)
    print(f"\n  MESSAGE TEMPLATES ({len(used_keys)} variant(s) in this wave)\n")
    for key in used_keys:
        msg = campaign.messages[key]
        segs = _sms_segments(msg)
        print(f"  ── {key}  ({len(msg)} chars / {segs} SMS segment(s)) " + "─" * 20)
        for line in msg.splitlines():
            print(f"  │ {line}")
        print()

    print("=" * 70)
    print(f"  SUMMARY: {len(queue)} to send, {len(skipped)} skipped")
    if DRY_RUN:
        print("  *** DRY_RUN=true — no SMS sent. Set DRY_RUN=false to live-send. ***")
    print("=" * 70)
    print()


# ── Sender ────────────────────────────────────────────────────────────────────

def send_wave(queue: List[QueueEntry], dry_run: bool = True) -> List[dict]:
    if dry_run:
        print("[send_wave] DRY_RUN — skipping all sends.")
        return []

    try:
        from routes.gcp_voice_sms import send_outbound_sms
    except ImportError:
        from CommPlexAPI.server.routes.gcp_voice_sms import send_outbound_sms

    results = []
    for e in queue:
        d = e.dealer
        print(f"  Sending → {d.company} ({d.phone}) [{e.msg_key}] … ", end="", flush=True)
        result = send_outbound_sms(to=d.phone, body=e.message)
        status = result.get("sid", result.get("error", "unknown"))
        print(status)
        results.append({"dealer": d.company, "phone": d.phone, "result": result})
    return results


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    slug = sys.argv[1] if len(sys.argv) > 1 else "jayco"
    dealers = load_dealers()
    queue, skipped = filter_dealers(dealers, slug)
    preview_wave(queue, skipped, slug)
    if not DRY_RUN:
        confirm = input(f"Send {len(queue)} SMS messages? [yes/N] ").strip().lower()
        if confirm == "yes":
            results = send_wave(queue, dry_run=False)
            print(f"\nSent {len(results)} messages.")
        else:
            print("Aborted.")
    return queue, skipped


if __name__ == "__main__":
    main()
