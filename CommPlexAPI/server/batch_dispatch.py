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
    - State in ND/SD/MT/MN → ND_COLD_SMS (cold-climate pitch, 1 segment)
    - All other states      → DEFAULT_SMS
    Falls back to ND_COLD / DEFAULT (email-length) if SMS variant absent.
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

DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"

FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "+18667362349")

_COLD_STATES = {"ND", "SD", "MT", "MN", "WI", "WY", "ID"}

_CAMPAIGN_KEYWORDS = {
    "jayco":   ["jayco"],
    "mkz":     ["mkz", "hybrid"],
    "towncar": ["town car", "towncar"],
    "f350":    ["f-350", "f350", "king ranch"],
}

_SKIP_PHRASES = [
    "live call",
    "not slydialer",
    "listing coordination",
    "cynthia and sherrie handle direct",
]

# T1 first, then T2/T3, then floor-setters, then last-resort fallbacks
_TIER_RANK = {"T1": 0, "T2": 1, "T3": 2, "FLOOR": 3, "FALLBACK": 4}

_COMPANY_COL_WIDTH = 34


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class DealerRow:
    idx:      int
    phone:    str
    name:     str
    company:  str
    city:     str
    state:    str
    interest: str
    tier:     str
    notes:    str
    priority: int


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
    return any(kw in interest.lower() for kw in _CAMPAIGN_KEYWORDS.get(slug, [slug]))


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


def _resolve_msg_key(state: str, msgs: dict) -> str:
    base = "ND_COLD" if state in _COLD_STATES else "DEFAULT"
    for candidate in (base + "_SMS", base):
        if candidate in msgs:
            return candidate
    return next(iter(msgs))


def filter_dealers(
    dealers: List[DealerRow], slug: str
) -> Tuple[List[QueueEntry], List[SkipEntry], object]:
    from CommPlexCore.campaigns.registry import CampaignRegistry
    campaign = CampaignRegistry.get(slug)
    if campaign is None:
        raise ValueError(f"Unknown campaign slug: {slug!r}")

    msgs = campaign.messages  # cache: @property rebuilds dict on every access
    queue: List[QueueEntry] = []
    skipped: List[SkipEntry] = []

    for d in dealers:
        reason = _skip_reason(d, slug)
        if reason:
            skipped.append(SkipEntry(dealer=d, reason=reason))
            continue
        msg_key = _resolve_msg_key(d.state, msgs)
        queue.append(QueueEntry(dealer=d, msg_key=msg_key, message=msgs[msg_key]))

    queue.sort(key=lambda e: (e.dealer.priority, _TIER_RANK.get(e.dealer.tier, 9)))
    return queue, skipped, campaign


# ── Preview ───────────────────────────────────────────────────────────────────

def _sms_segments(text: str, limit: int = 153) -> int:
    """Ceiling div — 153 chars/segment for Twilio concatenated multi-part SMS."""
    return 1 if len(text) <= 160 else -(-len(text) // limit)


def _print_table_header(cols: str, width: int) -> None:
    print(cols)
    print("  " + "-" * width)


def preview_wave(queue: List[QueueEntry], skipped: List[SkipEntry], slug: str, campaign) -> None:
    W = _COMPANY_COL_WIDTH
    print()
    print("=" * 70)
    print(f"  {slug.upper()} WAVE — DRY-RUN PREVIEW   (DRY_RUN={DRY_RUN})")
    print(f"  Campaign: {slug.upper()}   From: {FROM_NUMBER}")
    print("=" * 70)

    print(f"\n  SEND QUEUE — {len(queue)} contact(s)\n")
    queue_hdr = f"  {'#':>2}  {'Tier':<8} {'Company':<{W}} {'St':2}  {'Phone':14}  {'Msg':<12}  {'Ch':>4}  {'Seg':>3}"
    _print_table_header(queue_hdr, len(queue_hdr) - 2)
    for e in queue:
        d = e.dealer
        segs = _sms_segments(e.message)
        co = d.company[:W].ljust(W)
        print(f"  {d.idx:>2}  {d.tier:<8} {co} {d.state:2}  {d.phone:14}  {e.msg_key:<12}  {len(e.message):>4}  {segs:>3}")
        if d.notes:
            print(f"       {textwrap.shorten(d.notes, width=64, placeholder='…')}")

    print(f"\n  SKIPPED — {len(skipped)} contact(s)\n")
    skip_hdr = f"  {'#':>2}  {'Tier':<8} {'Company':<{W}} {'Reason'}"
    _print_table_header(skip_hdr, len(skip_hdr) - 2)
    for e in skipped:
        d = e.dealer
        print(f"  {d.idx:>2}  {d.tier:<8} {d.company[:W].ljust(W)} {e.reason}")

    msgs = campaign.messages
    used_keys = list(dict.fromkeys(e.msg_key for e in queue))  # insertion order
    print(f"\n  MESSAGE TEMPLATES ({len(used_keys)} variant(s) in this wave)\n")
    for key in used_keys:
        msg = msgs[key]
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
    queue, skipped, campaign = filter_dealers(dealers, slug)
    preview_wave(queue, skipped, slug, campaign)
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
