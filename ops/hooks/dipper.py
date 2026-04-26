#!/usr/bin/env python3
"""
big_scraper_qa_hook.py — CI/CD QA Hook for Big Scraper Runs
Place at: ~/arc-badlands-commplex/tools/big_scraper_qa_hook.py

PURPOSE:
  After each big_scraper_engine.py run (or on a cron schedule), this script:
    1. Reads the last N entries from scraper_runs.jsonl
    2. Reads any pending BaT/RV Trader/auction comp CSVs in intake/
    3. Posts a combined context to commplex_cicd_gemini /cicd/manual-trigger
       (which triggers Gemini long-think → per-person email dispatch)
    4. Sends direct SMS obligation summary to each team member via Twilio
    5. Generates a human-readable rolling test obligation snapshot

  This is the "scraper thread" of the CI/CD system — parallel to but
  separate from the CommPlex API deploy thread (commplex_cicd_gemini.py).
  The two threads feed into the same Gemini analysis engine and the same
  Firestore deploy_analyses collection, but they are triggered by different
  events and produce different obligation surfaces.

ARCHITECTURE — Design Patterns:
  Strategy    → ObligationBuilder per team member (builds member-specific check list)
  Chain of Responsibility → ScraperQAChain: log_reader → comp_reader → obligation_builder → dispatcher
  Command     → QAObligation (encapsulates one check item; execute() runs auto_cmd if present)
  Facade      → ScraperQAFacade: single .run() call triggers entire chain
  Singleton   → TwilioClientSingleton (one client instance per process)
  Decorator   → @log_step, @retry_on_http (reused from big_scraper_engine patterns)

RACI:
  kenyon  → GCP / Firestore integrity / comp analysis accuracy / ML  (7018705235)
  charles → Twilio SMS delivery confirmation / call dispatch health   (7018705448)
  cynthia → Intake CSV hygiene / form-fill test / SvelteKit read     (7019465731)
  justin  → Remote; simplest obligation each run (fallback: kenyon)  (jstnmshw@gmail.com)

Usage:
  python3 big_scraper_qa_hook.py                     # run full QA hook
  python3 big_scraper_qa_hook.py --dry-run           # print obligations, no SMS/POST
  python3 big_scraper_qa_hook.py --last-n 5          # analyze last 5 scraper runs
  python3 big_scraper_qa_hook.py --vehicle jayco     # filter to one vehicle
  python3 big_scraper_qa_hook.py --sms-only          # skip CI/CD POST, SMS only
  python3 big_scraper_qa_hook.py --print-obligations # human-readable snapshot
  python3 big_scraper_qa_hook.py --debrief           # interactive debrief collection
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import smtplib
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# ── Optional deps ─────────────────────────────────────────────────────────────
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

try:
    from twilio.rest import Client as _TwilioClientBase
    TWILIO_AVAILABLE = True
except ImportError:
    TWILIO_AVAILABLE = False

# ════════════════════════════════════════════════════════════════════════════════
# CONFIG
# ════════════════════════════════════════════════════════════════════════════════

SCRAPER_LOG   = Path(os.getenv("SCRAPER_LOG",   "scraper_runs.jsonl"))
INTAKE_DIR    = Path(os.getenv("INTAKE_DIR",    "~/arc-badlands-commplex/intake")).expanduser()
CICD_HOOK_URL = os.getenv("CICD_HOOK_URL",      "")   # commplex API /cicd/manual-trigger
TWILIO_SID    = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN",  "")
TWILIO_FROM   = os.getenv("TWILIO_FROM_NUMBER", "")
SMTP_USER     = os.getenv("SMTP_USER",          "")
SMTP_PASS     = os.getenv("SMTP_PASS",          "")

TEAM = {
    "kenyon":  {"phone": os.getenv("KENYON_PHONE",  "+17018705235"),
                "email": os.getenv("KENYON_EMAIL",  "kjonesmle@gmail.com"),
                "role":  "GCP / Firestore / ML / Android"},
    "charles": {"phone": os.getenv("CHARLES_PHONE", "+17018705448"),
                "email": os.getenv("CHARLES_EMAIL", ""),
                "role":  "Twilio voice+SMS / networking / infra"},
    "cynthia": {"phone": os.getenv("CYNTHIA_PHONE", "+17019465731"),
                "email": os.getenv("CYNTHIA_EMAIL", ""),
                "role":  "SvelteKit / form-fill / CSV intake / smoke QA"},
    "justin":  {"phone": os.getenv("JUSTIN_PHONE",  ""),
                "email": os.getenv("JUSTIN_EMAIL",  "jstnmshw@gmail.com"),
                "role":  "Remote — covered by kenyon first, then charles/cynthia"},
}

logger = logging.getLogger("scraper_qa_hook")
logger.setLevel(logging.INFO)
_h = logging.StreamHandler(sys.stdout)
_h.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s'))
logger.addHandler(_h)

# ════════════════════════════════════════════════════════════════════════════════
# SINGLETON — Twilio Client
# ════════════════════════════════════════════════════════════════════════════════

class TwilioClientSingleton:
    """Singleton: one Twilio client per process (avoids repeated auth handshakes)."""
    _instance: Optional[Any] = None

    @classmethod
    def get(cls) -> Optional[Any]:
        if not TWILIO_AVAILABLE or not TWILIO_SID or not TWILIO_TOKEN:
            return None
        if cls._instance is None:
            cls._instance = _TwilioClientBase(TWILIO_SID, TWILIO_TOKEN)
            logger.info("[twilio] client initialized")
        return cls._instance

# ════════════════════════════════════════════════════════════════════════════════
# MODELS
# ════════════════════════════════════════════════════════════════════════════════

@dataclass
class ScraperRunEntry:
    """One line from scraper_runs.jsonl."""
    run_id: str
    vehicle_type: str
    sources: List[str]
    contacts: int
    new: int
    bat_comps: int
    avg_comp: Optional[float]
    status: str
    dry_run: bool
    timestamp: str

    @classmethod
    def from_dict(cls, d: Dict) -> "ScraperRunEntry":
        return cls(
            run_id       = d.get("run_id", "unknown"),
            vehicle_type = d.get("vehicle_type", ""),
            sources      = d.get("sources", []),
            contacts     = d.get("contacts", 0),
            new          = d.get("new", 0),
            bat_comps    = d.get("bat_comps", 0),
            avg_comp     = d.get("avg_comp"),
            status       = d.get("status", "unknown"),
            dry_run      = d.get("dry_run", False),
            timestamp    = d.get("timestamp", ""),
        )


@dataclass
class QAObligation:
    """
    Command pattern: one QA obligation.
    execute() runs auto_cmd if set; returns True on pass.
    """
    id: str
    owner: str
    fallback: Optional[str]
    area: str
    priority: str          # critical | high | medium | low
    description: str
    steps: List[str]
    rollback: str          = ""
    auto_cmd: str          = ""
    status: str            = "pending"
    generated_by: str      = "big_scraper_qa_hook"

    def execute(self) -> bool:
        """Run auto_cmd shell command. Returns True if exit code 0."""
        if not self.auto_cmd:
            return True
        import subprocess
        try:
            result = subprocess.run(self.auto_cmd, shell=True, timeout=30,
                                    capture_output=True, text=True)
            passed = result.returncode == 0
            self.status = "pass" if passed else "fail"
            logger.info("[auto] %s → %s (exit %d)", self.auto_cmd[:60],
                        self.status, result.returncode)
            return passed
        except Exception as exc:
            logger.warning("[auto] cmd failed: %s", exc)
            self.status = "error"
            return False

    def to_sms(self) -> str:
        icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(self.priority, "⚪")
        fb   = f" [→{self.fallback}]" if self.fallback else ""
        return f"{icon}[{self.priority.upper()}]{fb} {self.description}"

    def to_display(self) -> str:
        icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(self.priority, "⚪")
        stat = {"pending": "⏳", "pass": "✅", "fail": "❌", "skip": "⏭️"}.get(self.status, "❓")
        fb   = f" [fallback: {self.fallback}]" if self.fallback else ""
        lines = [
            f"\n{stat} {icon} [{self.id}] [{self.owner.upper()}{fb}] [{self.area}] [{self.priority.upper()}]",
            f"   {self.description}",
        ]
        for i, s in enumerate(self.steps, 1):
            lines.append(f"   {i}. {s}")
        if self.rollback:
            lines.append(f"   ↩ Rollback: {self.rollback}")
        if self.auto_cmd:
            lines.append(f"   ⚙ Auto: {self.auto_cmd}")
        return "\n".join(lines)

# ════════════════════════════════════════════════════════════════════════════════
# CHAIN OF RESPONSIBILITY — QA Pipeline Steps
# Each handler in the chain processes the context and passes it forward.
# ════════════════════════════════════════════════════════════════════════════════

@dataclass
class QAContext:
    """Shared context passed through the QA chain."""
    run_entries:  List[ScraperRunEntry]    = field(default_factory=list)
    intake_tree:  Dict[str, int]           = field(default_factory=dict)  # dir → file count
    obligations:  List[QAObligation]       = field(default_factory=list)
    summary:      str                      = ""
    dry_run:      bool                     = False
    vehicle_filter: Optional[str]          = None


class BaseQAHandler(ABC):
    """Chain of Responsibility: base handler."""
    def __init__(self):
        self._next: Optional[BaseQAHandler] = None

    def set_next(self, handler: "BaseQAHandler") -> "BaseQAHandler":
        self._next = handler
        return handler

    def handle(self, ctx: QAContext) -> QAContext:
        ctx = self._process(ctx)
        if self._next:
            return self._next.handle(ctx)
        return ctx

    @abstractmethod
    def _process(self, ctx: QAContext) -> QAContext: ...


class LogReaderHandler(BaseQAHandler):
    """Chain step 1: read scraper_runs.jsonl into context."""

    def __init__(self, last_n: int = 10):
        super().__init__()
        self.last_n = last_n

    def _process(self, ctx: QAContext) -> QAContext:
        entries = []
        if not SCRAPER_LOG.exists():
            logger.warning("[log-reader] %s not found", SCRAPER_LOG)
            return ctx
        try:
            lines = SCRAPER_LOG.read_text().strip().splitlines()
            for line in reversed(lines[-self.last_n:] if self.last_n else lines):
                try:
                    d = json.loads(line)
                    entry = ScraperRunEntry.from_dict(d)
                    if ctx.vehicle_filter and entry.vehicle_type != ctx.vehicle_filter:
                        continue
                    entries.append(entry)
                except Exception:
                    pass
        except Exception as exc:
            logger.error("[log-reader] read failed: %s", exc)
        ctx.run_entries = entries
        logger.info("[log-reader] loaded %d run entries", len(entries))
        return ctx


class IntakeTreeHandler(BaseQAHandler):
    """Chain step 2: scan intake dir and record file counts per category."""

    CATEGORIES = [
        "dealer_csvs", "bat_history", "rvtrader_listings", "auction_history",
        "nd_local", "ga_local", "knowledge_base", "scraper_logs",
        "twilio_logs", "bland_residual", "campaign_reports",
    ]

    def _process(self, ctx: QAContext) -> QAContext:
        tree: Dict[str, int] = {}
        if not INTAKE_DIR.exists():
            logger.info("[intake-tree] intake dir not found: %s", INTAKE_DIR)
            ctx.intake_tree = tree
            return ctx
        for cat in self.CATEGORIES:
            cat_dir = INTAKE_DIR / cat
            if cat_dir.exists():
                files = list(cat_dir.iterdir())
                tree[cat] = len(files)
                if files:
                    logger.info("[intake-tree] %s: %d files", cat, len(files))
        ctx.intake_tree = tree
        return ctx


class ObligationBuilderHandler(BaseQAHandler):
    """
    Chain step 3: build per-person QA obligations based on run entries + intake state.
    Strategy pattern: one ObligationBuilder per team member.
    """

    def _process(self, ctx: QAContext) -> QAContext:
        obligations: List[QAObligation] = []
        last_run = ctx.run_entries[0] if ctx.run_entries else None

        obligations.extend(KenyonObligationBuilder(last_run, ctx).build())
        obligations.extend(CharlesObligationBuilder(last_run, ctx).build())
        obligations.extend(CynthiaObligationBuilder(last_run, ctx).build())
        obligations.extend(JustinObligationBuilder(last_run, ctx).build())

        ctx.obligations = obligations
        ctx.summary = _build_summary(ctx.run_entries, ctx.intake_tree)
        logger.info("[builder] %d total obligations across 4 members", len(obligations))
        return ctx


class CICDPostHandler(BaseQAHandler):
    """Chain step 4: POST context to commplex_cicd_gemini for Gemini long-think."""

    def _process(self, ctx: QAContext) -> QAContext:
        if ctx.dry_run or not CICD_HOOK_URL or not REQUESTS_AVAILABLE:
            logger.info("[cicd-post] skipping (dry_run=%s, url_set=%s)", ctx.dry_run, bool(CICD_HOOK_URL))
            return ctx
        payload = {
            "commit_sha":    f"scraper_qa_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
            "message":       ctx.summary,
            "pusher":        "big_scraper_qa_hook",
            "dry_run":       False,
            "scraper_runs":  [
                {"run_id": e.run_id, "vehicle": e.vehicle_type,
                 "contacts": e.contacts, "status": e.status}
                for e in ctx.run_entries
            ],
            "intake_tree": ctx.intake_tree,
        }
        try:
            resp = requests.post(CICD_HOOK_URL, json=payload, timeout=15)
            logger.info("[cicd-post] %s → %d", CICD_HOOK_URL, resp.status_code)
        except Exception as exc:
            logger.warning("[cicd-post] failed: %s", exc)
        return ctx


class SMSDispatchHandler(BaseQAHandler):
    """Chain step 5: SMS each team member their obligation list."""

    def _process(self, ctx: QAContext) -> QAContext:
        if ctx.dry_run:
            logger.info("[sms-dispatch] dry-run — printing SMS content")
            for member in TEAM:
                mine = [o for o in ctx.obligations if o.owner == member]
                if mine:
                    print(f"\n── SMS to {member.upper()} ──")
                    for o in mine:
                        print(f"  {o.to_sms()}")
            return ctx

        client = TwilioClientSingleton.get()
        for member, info in TEAM.items():
            phone = info.get("phone", "")
            if not phone or not client:
                continue
            mine = [o for o in ctx.obligations if o.owner == member]
            if not mine:
                continue

            lines = [
                f"CommPlex Scraper QA [{datetime.now().strftime('%m/%d %H:%M')}]",
                f"Your {len(mine)} obligation(s):",
            ]
            for o in mine:
                lines.append(o.to_sms())
            if CICD_HOOK_URL:
                lines.append(f"Details → email / Firestore deploy_analyses")

            body = "\n".join(lines)
            try:
                msg = client.messages.create(body=body, from_=TWILIO_FROM, to=phone)
                logger.info("[sms] sent to %s (%s): %s", member, phone, msg.sid)
            except Exception as exc:
                logger.warning("[sms] failed for %s: %s", member, exc)

        # Justin also gets email (no confirmed SMS number)
        _send_justin_email(ctx)
        return ctx


class EmailFallbackHandler(BaseQAHandler):
    """Chain step 6: email for anyone without a confirmed SMS (justin + any missing phone)."""

    def _process(self, ctx: QAContext) -> QAContext:
        # Justin email is the primary case
        _send_justin_email(ctx)
        return ctx

# ════════════════════════════════════════════════════════════════════════════════
# STRATEGY — Per-member ObligationBuilders
# Each builder knows one person's domain and produces relevant obligations.
# ════════════════════════════════════════════════════════════════════════════════

class BaseObligationBuilder(ABC):
    def __init__(self, last_run: Optional[ScraperRunEntry], ctx: QAContext):
        self.run = last_run
        self.ctx = ctx

    @abstractmethod
    def build(self) -> List[QAObligation]: ...

    def _obl(self, suffix: str, area: str, priority: str,
             desc: str, steps: List[str],
             rollback: str = "", auto_cmd: str = "",
             fallback: Optional[str] = None) -> QAObligation:
        owner  = self._owner()
        run_id = self.run.run_id if self.run else "no-run"
        return QAObligation(
            id          = f"sq_{owner}_{run_id}_{suffix}",
            owner       = owner,
            fallback    = fallback,
            area        = area,
            priority    = priority,
            description = desc,
            steps       = steps,
            rollback    = rollback,
            auto_cmd    = auto_cmd,
        )

    @abstractmethod
    def _owner(self) -> str: ...


class KenyonObligationBuilder(BaseObligationBuilder):
    """Builds Kenyon's obligations: GCP, Firestore, comp analysis, ML enrichment."""
    def _owner(self) -> str: return "kenyon"

    def build(self) -> List[QAObligation]:
        obls = []
        run  = self.run

        # Always: Firestore write verification
        obls.append(self._obl(
            "k001", "firestore", "critical" if (run and run.status != "success") else "high",
            f"Verify Firestore dealer_contacts write for last scraper run"
            + (f" [{run.run_id}] ({run.vehicle_type})" if run else ""),
            steps=[
                "python3 -c \"from google.cloud import firestore; "
                "db=firestore.Client(project='commplex-493805'); "
                "docs=list(db.collection('dealer_contacts').limit(5).stream()); "
                "print(f'{len(docs)} docs readable — OK')\"",
                "Check Firestore Console: dealer_contacts collection → newest entries",
                f"Verify flag='ACTIVE' on most recent docs",
            ],
            rollback="Re-run: python3 big_scraper_engine.py --vehicle jayco --dry-run (verify contacts appear)",
            auto_cmd="python3 -c \"from google.cloud import firestore; db=firestore.Client(project='commplex-493805'); list(db.collection('dealer_contacts').limit(1).stream()); print('ok')\" && echo 'PASS' || echo 'FAIL'",
        ))

        # If comp data found: verify pricing intelligence
        if run and run.bat_comps > 0:
            obls.append(self._obl(
                "k002", "ml", "medium",
                f"Review BaT comp analysis: {run.bat_comps} comps, avg=${run.avg_comp:,.0f}" if run.avg_comp else f"Review BaT comp analysis: {run.bat_comps} comps found",
                steps=[
                    "python3 big_scraper_engine.py --vehicle " + (run.vehicle_type if run else "jayco") + " --comps-only",
                    "Compare avg_comp to knowledge_base.csv pricing_floor",
                    "If delta > 15%: update pricing_floor in knowledge_base.csv",
                ],
            ))

        # If any run errored: investigate
        if run and run.status == "error":
            obls.append(self._obl(
                "k003", "gcp", "critical",
                f"Scraper run {run.run_id} errored — investigate Cloud Logging",
                steps=[
                    "tail -20 scraper_runs.jsonl | python3 -m json.tool",
                    "gcloud logging read 'resource.type=cloud_run_revision' --limit=50 --format=json | python3 -m json.tool | head -100",
                    "Re-run with: python3 big_scraper_engine.py --vehicle " + (run.vehicle_type if run else "?") + " --dry-run",
                ],
                rollback="Check KNOWLEDGE_BASE_PATH env var and intake dir permissions",
                priority="critical",
            ))

        # Intake dir check
        unprocessed = sum(v for k, v in self.ctx.intake_tree.items()
                         if k in ("bat_history", "auction_history") and v > 0)
        if unprocessed > 0:
            obls.append(self._obl(
                "k004", "ml", "medium",
                f"{unprocessed} BaT/auction comp files pending enrichment in intake/",
                steps=[
                    "python3 big_scraper_engine.py --vehicle jayco --comps-only",
                    "python3 big_scraper_engine.py --vehicle f350 --comps-only",
                    "Check intake/bat_history/ and intake/auction_history/ for new CSVs",
                ],
            ))

        return obls


class CharlesObligationBuilder(BaseObligationBuilder):
    """Builds Charles's obligations: Twilio SMS delivery, networking, infra."""
    def _owner(self) -> str: return "charles"

    def build(self) -> List[QAObligation]:
        obls = []
        run  = self.run

        # Twilio SMS delivery verification (always)
        obls.append(self._obl(
            "c001", "twilio", "high",
            "Verify Twilio SMS delivery — confirm team received scraper run notification",
            steps=[
                "Check Twilio Console → Message Logs → filter last 1 hour",
                "Verify messages sent to Kenyon +17018705235, Charles +17018705448, Cynthia +17019465731",
                "Check message status: delivered (not 'failed' or 'undelivered')",
                "If failed: check TWILIO_FROM_NUMBER env var and account balance",
            ],
            rollback="Manually SMS Kenyon: 'Twilio SMS delivery check — see deploy_analyses in Firestore'",
            auto_cmd="",  # Twilio delivery check requires console or API call
        ))

        # Network/infra check if CI/CD hook is configured
        if CICD_HOOK_URL:
            obls.append(self._obl(
                "c002", "networking", "medium",
                "Verify CI/CD hook POST reached commplex API (check for 200 response)",
                steps=[
                    f"curl -X POST {CICD_HOOK_URL} -H 'Content-Type: application/json' -d '{{\"commit_sha\":\"cicd_test\",\"message\":\"charles health check\"}}' -w '\\nHTTP %{{http_code}}'",
                    "Expected: HTTP 200 with {\"status\": \"queued\", \"run_id\": \"...\"}",
                    "If failed: check Cloud Run service is running (kenyon to investigate)",
                ],
                rollback="Escalate to Kenyon if Cloud Run endpoint unreachable",
            ))

        # Twilio call dispatch check (if Bland is winding down)
        obls.append(self._obl(
            "c003", "twilio", "medium",
            "Confirm Twilio outbound call config matches current Cloud Run URL (not old Bland webhook)",
            steps=[
                "Log into Twilio Console → Phone Numbers → Active Numbers",
                "Verify Voice webhook URL points to current Cloud Run service",
                "Check TwiML App config if using programmatic voice",
                "Test with: twilio api:core:calls:create --to +17018705235 --from $TWILIO_FROM --url http://demo.twilio.com/docs/voice.xml (dry-run call)",
            ],
            rollback="Revert Twilio webhook URL to last known good Cloud Run revision URL",
        ))

        return obls


class CynthiaObligationBuilder(BaseObligationBuilder):
    """Builds Cynthia's obligations: intake CSV hygiene, form-fill, SvelteKit smoke."""
    def _owner(self) -> str: return "cynthia"

    def build(self) -> List[QAObligation]:
        obls = []
        run  = self.run

        # Intake CSV health
        dealer_csv_count = self.ctx.intake_tree.get("dealer_csvs", 0)
        obls.append(self._obl(
            "cy001", "intake", "high",
            f"Verify intake/dealer_csvs/ has correct format ({dealer_csv_count} files present)",
            steps=[
                "ls ~/arc-badlands-commplex/intake/dealer_csvs/",
                "head -3 intake/dealer_csvs/dealers_jayco.csv  # verify columns: name,phone,email,city,state,segment",
                "python3 commplex_file_intake_v2.py --parse-csvs",
                "Check for any parse errors in output",
            ],
            rollback="Re-export dealer CSV from source with correct column headers",
            auto_cmd="[ -d ~/arc-badlands-commplex/intake/dealer_csvs ] && echo 'PASS' || echo 'FAIL'",
        ))

        # RV Trader / BaT intake check
        rvt_count = self.ctx.intake_tree.get("rvtrader_listings", 0)
        bat_count = self.ctx.intake_tree.get("bat_history", 0)
        if rvt_count > 0 or bat_count > 0:
            obls.append(self._obl(
                "cy002", "intake", "medium",
                f"Process pending intake files: {rvt_count} RV Trader + {bat_count} BaT CSVs",
                steps=[
                    "python3 commplex_file_intake_v2.py --parse-rvt",
                    "python3 commplex_file_intake_v2.py --parse-bat",
                    "Verify files moved to intake/processed/ (or renamed .done)",
                    "Check Firestore for new dealer_contacts entries after parse",
                ],
            ))

        # SvelteKit smoke (if in Phase 2)
        obls.append(self._obl(
            "cy003", "sveltekit", "low",
            "Smoke test SvelteKit dashboard (Phase 2 — verify it builds without errors)",
            steps=[
                "cd ~/arc-badlands-commplex/dashboard && npm run build 2>&1 | tail -20",
                "Verify no TypeScript/Svelte errors",
                "If not started: note as Phase 2 pending — skip this obligation",
            ],
            rollback="Revert last Svelte component change via git",
            auto_cmd="[ -d ~/arc-badlands-commplex/dashboard ] && echo 'PASS (dir exists)' || echo 'SKIP (Phase 2 not started)'",
        ))

        # Bland residual wind-down check
        bland_count = self.ctx.intake_tree.get("bland_residual", 0)
        if bland_count > 0:
            obls.append(self._obl(
                "cy004", "bland_residual", "low",
                f"Archive {bland_count} Bland.ai residual log(s) — wind-down tracking only",
                steps=[
                    "ls intake/bland_residual/",
                    "python3 commplex_file_intake_v2.py --status | grep bland",
                    "Move processed bland logs to intake/bland_residual/archived/",
                    "Confirm no new Bland campaigns created (Twilio is now Charles's)",
                ],
            ))

        return obls


class JustinObligationBuilder(BaseObligationBuilder):
    """
    Builds Justin's obligations: simplest possible verifications, remote-safe.
    Always includes fallback owner. Prefer curl/health checks.
    """
    def _owner(self) -> str: return "justin"

    def build(self) -> List[QAObligation]:
        obls = []
        run  = self.run

        # Health check — simplest possible test
        api_url = os.getenv("API_URL", "https://commplex-api-349126848698.us-central1.run.app")
        obls.append(self._obl(
            "j001", "gcp", "low",
            f"Verify Cloud Run /health endpoint responds (escalate to Kenyon if fails)",
            steps=[
                f"curl {api_url}/health",
                "Expected: {\"status\": \"ok\"}",
                "If fails: email kenyon at kjonesmle@gmail.com with response",
            ],
            auto_cmd=f"curl -sf {api_url}/health | python3 -c 'import sys,json; d=json.load(sys.stdin); print(\"PASS\" if d.get(\"status\")==\"ok\" else \"FAIL\")'",
            fallback="kenyon",
        ))

        # Scraper log read — just check file exists and last entry
        obls.append(self._obl(
            "j002", "scraper", "low",
            "Confirm scraper_runs.jsonl updated with latest run (no action needed if ok)",
            steps=[
                "tail -1 scraper_runs.jsonl | python3 -m json.tool",
                "Verify 'status' is 'success' and 'timestamp' is recent",
                "If status is 'error': notify kenyon immediately",
            ],
            auto_cmd="tail -1 scraper_runs.jsonl | python3 -c 'import sys,json; d=json.load(sys.stdin); print(\"PASS\" if d.get(\"status\")==\"success\" else \"FAIL\")'",
            fallback="kenyon",
        ))

        return obls

# ════════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ════════════════════════════════════════════════════════════════════════════════

def _build_summary(runs: List[ScraperRunEntry], intake: Dict[str, int]) -> str:
    if not runs:
        return "No scraper runs found in log. Check SCRAPER_LOG path."
    r   = runs[0]
    pending_intake = sum(intake.values())
    comp_note = f" | BaT avg=${r.avg_comp:,.0f}" if r.avg_comp else ""
    return (
        f"Last scraper run [{r.run_id}]: {r.vehicle_type} | "
        f"{r.contacts} contacts ({r.new} new) | sources: {','.join(r.sources) or 'csv'} | "
        f"status: {r.status}{comp_note} | "
        f"intake pending: {pending_intake} files across {len(intake)} categories."
    )


def _send_justin_email(ctx: QAContext) -> None:
    """Email Justin his obligations (SMS number TBD)."""
    if not SMTP_USER or not SMTP_PASS:
        logger.info("[email-justin] SMTP not configured — printing Justin's obligations")
        mine = [o for o in ctx.obligations if o.owner == "justin"]
        for o in mine:
            print(o.to_display())
        return

    mine = [o for o in ctx.obligations if o.owner == "justin"]
    if not mine:
        return

    rows_html = "".join(
        f"<div style='border-left:4px solid #333;margin:12px 0;padding:10px 14px;background:#f9f9f9;'>"
        f"<p><b>[{o.priority.upper()}]</b> {o.description}</p>"
        f"<ol>{''.join(f'<li><code>{s}</code></li>' for s in o.steps)}</ol>"
        f"<p style='color:#888;font-size:11px'>Fallback: {o.fallback or 'none'} | ID: {o.id}</p>"
        f"</div>"
        for o in mine
    )
    body = (
        f"<html><body style='font-family:sans-serif;max-width:680px;margin:auto;'>"
        f"<h2>CommPlex Scraper QA — Justin's Obligations</h2>"
        f"<p>{ctx.summary}</p>"
        f"<h3>Your Items ({len(mine)})</h3>"
        f"{rows_html}"
        f"<p style='color:#888;font-size:11px;'>If unavailable, Kenyon covers these first.</p>"
        f"</body></html>"
    )
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[CommPlex QA] Justin's obligations — {len(mine)} item(s)"
        msg["From"]    = SMTP_USER
        msg["To"]      = TEAM["justin"]["email"]
        msg.attach(MIMEText(body, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(SMTP_USER, SMTP_PASS)
            smtp.sendmail(SMTP_USER, [TEAM["justin"]["email"]], msg.as_string())
        logger.info("[email] sent to Justin (%s)", TEAM["justin"]["email"])
    except Exception as exc:
        logger.warning("[email] Justin email failed: %s", exc)

# ════════════════════════════════════════════════════════════════════════════════
# FACADE — ScraperQAFacade
# Single .run() call wires and triggers the full chain.
# ════════════════════════════════════════════════════════════════════════════════

class ScraperQAFacade:
    """
    Facade: one entry point for the full QA hook pipeline.
    Composes the Chain of Responsibility and exposes .run().
    """

    def __init__(self, last_n: int = 10, dry_run: bool = False,
                 vehicle_filter: Optional[str] = None, sms_only: bool = False):
        self.dry_run        = dry_run
        self.vehicle_filter = vehicle_filter

        # Build chain
        log_reader   = LogReaderHandler(last_n=last_n)
        intake_tree  = IntakeTreeHandler()
        builder      = ObligationBuilderHandler()
        cicd_post    = CICDPostHandler()
        sms_dispatch = SMSDispatchHandler()

        if sms_only:
            # Skip CI/CD POST
            log_reader.set_next(intake_tree).set_next(builder).set_next(sms_dispatch)
        else:
            log_reader.set_next(intake_tree).set_next(builder).set_next(cicd_post).set_next(sms_dispatch)

        self._chain = log_reader

    def run(self) -> QAContext:
        ctx = QAContext(dry_run=self.dry_run, vehicle_filter=self.vehicle_filter)
        return self._chain.handle(ctx)

# ════════════════════════════════════════════════════════════════════════════════
# INTERACTIVE DEBRIEF
# ════════════════════════════════════════════════════════════════════════════════

def run_debrief(ctx: QAContext) -> None:
    """Simple CLI debrief: walk each obligation, mark pass/fail, POST results."""
    print("\n═══ CommPlex Scraper QA Debrief ═══")
    print(f"Summary: {ctx.summary}\n")

    debrief_log = []
    for o in ctx.obligations:
        print(o.to_display())
        ans = input(f"\n  Mark [{o.id}] as (p)ass / (f)ail / (s)kip? [p]: ").strip().lower()
        o.status = {"p": "pass", "f": "fail", "s": "skip"}.get(ans, "pass")
        debrief_log.append({"id": o.id, "owner": o.owner, "status": o.status})
        print(f"  → Marked: {o.status}")

    # Write debrief to JSONL
    entry = {
        "submitted_at":  datetime.now(timezone.utc).isoformat(),
        "submitter":     "cli_debrief",
        "run_summary":   ctx.summary,
        "items":         debrief_log,
        "passed_items":  [d["id"] for d in debrief_log if d["status"] == "pass"],
        "failed_items":  [d["id"] for d in debrief_log if d["status"] == "fail"],
    }
    debrief_path = Path("scraper_qa_debriefs.jsonl")
    with open(debrief_path, "a") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"\n✅ Debrief saved to {debrief_path}")

# ════════════════════════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Big Scraper QA Hook")
    parser.add_argument("--dry-run",           action="store_true", default=False)
    parser.add_argument("--last-n",            type=int, default=10, help="Analyze last N run entries")
    parser.add_argument("--vehicle",           default=None, help="Filter to one vehicle type")
    parser.add_argument("--sms-only",          action="store_true", help="SMS team, skip CI/CD POST")
    parser.add_argument("--print-obligations", action="store_true", help="Print obligations and exit")
    parser.add_argument("--debrief",           action="store_true", help="Interactive debrief mode")
    args = parser.parse_args()

    facade = ScraperQAFacade(
        last_n=args.last_n,
        dry_run=args.dry_run,
        vehicle_filter=args.vehicle,
        sms_only=args.sms_only,
    )
    ctx = facade.run()

    if args.print_obligations or args.dry_run:
        print(f"\n═══ Summary ═══\n{ctx.summary}")
        for member in ["kenyon", "charles", "cynthia", "justin"]:
            mine = [o for o in ctx.obligations if o.owner == member]
            if mine:
                print(f"\n── {member.upper()} ({len(mine)} items) ──")
                for o in mine:
                    print(o.to_display())

    if args.debrief:
        run_debrief(ctx)

    total  = len(ctx.obligations)
    failed = sum(1 for o in ctx.obligations if o.status == "fail")
    logger.info("QA hook complete: %d obligations | %d failed | dry_run=%s", total, failed, args.dry_run)


if __name__ == "__main__":
    main()
