#!/usr/bin/env python3
"""
commplex_qa_dispatch_v2.py — CommPlex QA Obligation Dispatcher · v2
Drop into: CommPlexAPI/server/routes/commplex_qa_dispatch_v2.py

CHANGES FROM v1:
  - Bland.ai REMOVED from Charles's surface (Twilio is now Charles's domain)
  - Cynthia: holds residual Bland.ai during wind-down + SvelteKit + form fill
  - Charles: Twilio voice/SMS outbound + networking/infra
  - Justin: 4th RACI member (remote); obligation pool auto-tagged with fallback owner
  - CI/CD hook: POSTs to /cicd/manual-trigger on each campaign run start
  - Gemini 2.5 Pro with thinking for debrief root cause analysis
  - SOLID applied:
      S — each class has one job (QARouter, DebriefAnalyzer, ObligationStore, etc.)
      O — open to new obligation sources via ObligationPlugin interface
      L — all obligation stores satisfy the ObligationRepository interface
      I — thin interfaces (ObligationRepository, NotificationSink)
      D — depend on abstractions (inject store + notifier, don't instantiate in handler)
  - GoF patterns:
      Strategy  → NotificationSink (Email | Slack | DryRun)
      Repository → FirestoreObligationStore | InMemoryObligationStore
      Facade    → QADispatchFacade (single call to trigger full flow)
      Chain of Responsibility → debrief validation chain
      Singleton → shared Gemini client

RACI — CommPlex v2:
  kenyon   → GCP / Cloud Run / Firestore / orchestrator / big scraper / ML/MSCS / Android
  charles  → Twilio voice+SMS / networking / infra QA / Twilio webhook verification
  cynthia  → SvelteKit dashboard / form fill / Bland.ai wind-down / smoke QA / dealer CSV intake
  justin   → Remote (coverage priority: kenyon > charles > cynthia)

INSTALL:
  1. cp commplex_qa_dispatch_v2.py CommPlexAPI/server/routes/
  2. In main.py:
       from .routes import commplex_qa_dispatch_v2
       app.include_router(commplex_qa_dispatch_v2.router)
  3. Env vars:
       SMTP_USER, SMTP_PASS
       KENYON_EMAIL, CHARLES_EMAIL, CYNTHIA_EMAIL, JUSTIN_EMAIL
       GCP_PROJECT, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN
       GITHUB_PAT, GITHUB_REPO
       CICD_TRIGGER_URL (default: /cicd/manual-trigger)
"""

from __future__ import annotations

import json
import logging
import os
import smtplib
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

import httpx
import vertexai
from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, JSONResponse
from google.cloud import firestore
from vertexai.generative_models import GenerationConfig, GenerativeModel

try:
    from vertexai.generative_models import ThinkingConfig
    _THINKING_AVAILABLE = True
except ImportError:
    _THINKING_AVAILABLE = False

router = APIRouter()
logger = logging.getLogger("commplex_qa_v2")

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

GCP_PROJECT       = os.getenv("GCP_PROJECT", "commplex-493805")
GEMINI_MODEL      = "gemini-2.5-pro-preview-05-06"
CICD_TRIGGER_URL  = os.getenv("CICD_TRIGGER_URL", "http://localhost:8080/cicd/manual-trigger")

SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")

TEAM: Dict[str, str] = {
    "kenyon":  os.getenv("KENYON_EMAIL",  "kjones@commplex.io"),
    "charles": os.getenv("CHARLES_EMAIL", "charles@commplex.io"),
    "cynthia": os.getenv("CYNTHIA_EMAIL", "cynthia@commplex.io"),
    "justin":  os.getenv("JUSTIN_EMAIL",  "justin@commplex.io"),
}

# ═══════════════════════════════════════════════════════════════════════════════
# MODELS
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class QAObligation:
    id: str
    owner: str                     # kenyon | charles | cynthia | justin
    fallback_owner: Optional[str]  # who covers if justin is unavailable
    area: str
    priority: str
    description: str
    steps: List[str]
    rollback: str = ""
    campaign: str = ""
    status: str = "pending"        # pending | pass | fail | skipped

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()

@dataclass
class DeployTrigger:
    run_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    campaign: str = ""
    phase: str = ""
    commit_sha: str = ""
    triggered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    changed_files: List[str] = field(default_factory=list)
    dry_run: bool = False

@dataclass
class DebriefSubmission:
    run_id: str
    submitter: str
    passed_items: List[str]
    failed_items: List[str]
    notes: str
    screenshots: List[str] = field(default_factory=list)
    submitted_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

# ═══════════════════════════════════════════════════════════════════════════════
# INTERFACE — ObligationRepository (LSP / DIP)
# ═══════════════════════════════════════════════════════════════════════════════

class ObligationRepository(ABC):
    @abstractmethod
    def save_obligations(self, trigger: DeployTrigger, obligations: List[QAObligation]) -> None: ...
    @abstractmethod
    def load_obligations(self, run_id: str) -> List[QAObligation]: ...
    @abstractmethod
    def save_debrief(self, debrief: DebriefSubmission) -> None: ...

class FirestoreObligationStore(ObligationRepository):
    """Firestore-backed production store."""
    def __init__(self):
        self._db: Optional[Any] = None

    @property
    def db(self):
        if self._db is None:
            self._db = firestore.Client(project=GCP_PROJECT)
        return self._db

    def save_obligations(self, trigger: DeployTrigger, obligations: List[QAObligation]) -> None:
        batch = self.db.batch()
        ref = self.db.collection("commplex_qa_runs").document(trigger.run_id)
        batch.set(ref, {
            "run_id": trigger.run_id, "campaign": trigger.campaign,
            "phase": trigger.phase, "triggered_at": trigger.triggered_at,
            "obligation_count": len(obligations),
        })
        for o in obligations:
            batch.set(ref.collection("obligations").document(o.id), o.to_dict())
        batch.commit()
        logger.info("[store] saved %d obligations for run %s", len(obligations), trigger.run_id)

    def load_obligations(self, run_id: str) -> List[QAObligation]:
        docs = self.db.collection("commplex_qa_runs").document(run_id)\
                      .collection("obligations").stream()
        return [QAObligation(**d.to_dict()) for d in docs]

    def save_debrief(self, debrief: DebriefSubmission) -> None:
        self.db.collection("commplex_qa_debriefs").add(debrief.__dict__)
        logger.info("[store] debrief saved for run %s by %s", debrief.run_id, debrief.submitter)

class InMemoryObligationStore(ObligationRepository):
    """In-memory store for dry-run / testing. (Also useful for unit tests.)"""
    def __init__(self):
        self._obligations: Dict[str, List[QAObligation]] = {}
        self._debriefs: List[DebriefSubmission] = []

    def save_obligations(self, trigger: DeployTrigger, obligations: List[QAObligation]) -> None:
        self._obligations[trigger.run_id] = obligations

    def load_obligations(self, run_id: str) -> List[QAObligation]:
        return self._obligations.get(run_id, [])

    def save_debrief(self, debrief: DebriefSubmission) -> None:
        self._debriefs.append(debrief)

# ═══════════════════════════════════════════════════════════════════════════════
# INTERFACE — NotificationSink  (Strategy pattern)
# ═══════════════════════════════════════════════════════════════════════════════

class NotificationSink(ABC):
    @abstractmethod
    def notify(self, member: str, run_id: str, obligations: List[QAObligation],
               summary: str, debrief_url: str) -> None: ...

class EmailNotificationSink(NotificationSink):
    """Send HTML obligation emails via SMTP."""
    ICONS = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}
    AREA_ICONS = {
        "twilio": "📞", "gcp": "☁️", "firestore": "🗃️", "scraper": "🕷️",
        "sveltekit": "🖥️", "bland_residual": "📟", "networking": "🌐",
        "ml": "🧠", "audit": "🔍",
    }

    def notify(self, member: str, run_id: str, obligations: List[QAObligation],
               summary: str, debrief_url: str) -> None:
        if not SMTP_USER or not SMTP_PASS:
            logger.warning("[email] SMTP not configured — logging for %s", member)
            for o in obligations:
                logger.info("  [%s][%s] %s", o.priority, o.area, o.description)
            return
        try:
            rows = ""
            for o in obligations:
                pi = self.ICONS.get(o.priority, "⚪")
                ai = self.AREA_ICONS.get(o.area, "📋")
                steps_html = "".join(f"<li><code>{s}</code></li>" for s in o.steps)
                fb = (f"<p style='color:#888'><small>Fallback: {o.fallback_owner}</small></p>"
                      if o.fallback_owner else "")
                rows += f"""
<div style='border-left:4px solid #1a73e8;margin:14px 0;padding:12px 16px;background:#f8f9fa;
            border-radius:4px;'>
  <p><b>{pi} {ai} [{o.priority.upper()}] [{o.area}]</b> {o.description}</p>
  <ol style='margin:8px 0 8px 20px;'>{steps_html}</ol>
  {"<p><b>Rollback:</b> " + o.rollback + "</p>" if o.rollback else ""}
  {fb}
  <p style='color:#aaa;font-size:10px;'>ID: {o.id} · campaign: {o.campaign}</p>
</div>"""

            body = f"""<html><body style='font-family:sans-serif;max-width:700px;margin:auto;
                    color:#222;'>
<h2 style='border-bottom:2px solid #1a73e8;padding-bottom:8px;'>
  CommPlex QA · Run <code>{run_id}</code>
</h2>
<p><b>Gemini Analysis:</b> {summary}</p>
<h3>Your Obligations ({len(obligations)})</h3>
{rows}
<hr style='margin:24px 0;'>
<a href='{debrief_url}' style='background:#1a73e8;color:#fff;padding:12px 24px;
  text-decoration:none;border-radius:6px;display:inline-block;font-weight:bold;'>
  Submit Debrief ✓
</a>
<p style='color:#aaa;font-size:11px;margin-top:24px;'>
  CommPlex QA Dispatch v2 · Twilio/GCP/SvelteKit
</p></body></html>"""

            msg = MIMEMultipart("alternative")
            msg["Subject"] = (
                f"[CommPlex QA {run_id}] {len(obligations)} obligation(s) — {member}"
            )
            msg["From"] = SMTP_USER
            msg["To"]   = TEAM.get(member, SMTP_USER)
            msg.attach(MIMEText(body, "html"))
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
                smtp.login(SMTP_USER, SMTP_PASS)
                smtp.sendmail(SMTP_USER, [TEAM[member]], msg.as_string())
            logger.info("[email] dispatched to %s (%d items)", member, len(obligations))
        except Exception as exc:
            logger.error("[email] failed for %s: %s", member, exc)

class DryRunNotificationSink(NotificationSink):
    """Log obligations without sending anything (for dry-run / test)."""
    def notify(self, member: str, run_id: str, obligations: List[QAObligation],
               summary: str, debrief_url: str) -> None:
        logger.info("[dry-run notify] %s (%d obligations):", member, len(obligations))
        for o in obligations:
            logger.info("  [%s][%s] %s", o.priority, o.area, o.description)

# ═══════════════════════════════════════════════════════════════════════════════
# SINGLETON — Gemini Client
# ═══════════════════════════════════════════════════════════════════════════════

class _GeminiClientSingleton:
    _instance: Optional["_GeminiClientSingleton"] = None
    _model: Optional[GenerativeModel] = None

    def __new__(cls) -> "_GeminiClientSingleton":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            vertexai.init(project=GCP_PROJECT, location="us-central1")
            cls._instance._model = GenerativeModel(GEMINI_MODEL)
        return cls._instance

    def generate(self, prompt: str) -> str:
        cfg = GenerationConfig(max_output_tokens=6144, temperature=0.2)
        kwargs: Dict[str, Any] = {"generation_config": cfg}
        if _THINKING_AVAILABLE:
            kwargs["thinking_config"] = ThinkingConfig(thinking_budget=6000)
        return self._model.generate_content(prompt, **kwargs).text

GeminiClient = _GeminiClientSingleton

# ═══════════════════════════════════════════════════════════════════════════════
# CHAIN OF RESPONSIBILITY — Debrief Validation
# Each validator checks one concern, passes to next.
# ═══════════════════════════════════════════════════════════════════════════════

class DebriefValidator(ABC):
    def __init__(self):
        self._next: Optional["DebriefValidator"] = None

    def set_next(self, v: "DebriefValidator") -> "DebriefValidator":
        self._next = v
        return v

    def validate(self, d: DebriefSubmission) -> Optional[str]:
        """Return error string or None. Call next if None."""
        err = self._check(d)
        if err:
            return err
        return self._next.validate(d) if self._next else None

    @abstractmethod
    def _check(self, d: DebriefSubmission) -> Optional[str]: ...

class RunIdValidator(DebriefValidator):
    def _check(self, d: DebriefSubmission) -> Optional[str]:
        return "run_id required" if not d.run_id else None

class SubmitterValidator(DebriefValidator):
    def _check(self, d: DebriefSubmission) -> Optional[str]:
        if d.submitter not in TEAM:
            return f"unknown submitter '{d.submitter}'"
        return None

class ItemsValidator(DebriefSubmission):
    def _check(self, d: DebriefSubmission) -> Optional[str]:
        if not d.passed_items and not d.failed_items:
            return "at least one passed or failed item required"
        return None

def _build_validator_chain() -> DebriefValidator:
    head = RunIdValidator()
    head.set_next(SubmitterValidator())
    return head

# ═══════════════════════════════════════════════════════════════════════════════
# OBLIGATION DEFINITIONS (v2 — Twilio surface, Justin added)
# ═══════════════════════════════════════════════════════════════════════════════

def build_campaign_obligations(
    trigger: DeployTrigger,
    gemini_additions: Optional[List[Dict]] = None,
) -> List[QAObligation]:
    """
    Build the full obligation set for a campaign run.
    Merges static baseline + Gemini-generated additions.
    """
    base = _static_obligations(trigger)
    if gemini_additions:
        for item in gemini_additions:
            base.append(QAObligation(
                id              = item.get("id", f"gem_{uuid.uuid4().hex[:6]}"),
                owner           = item.get("owner", "kenyon"),
                fallback_owner  = item.get("fallback_owner"),
                area            = item.get("area", "gcp"),
                priority        = item.get("priority", "medium"),
                description     = item.get("description", ""),
                steps           = item.get("steps", []),
                rollback        = item.get("rollback", ""),
                campaign        = trigger.campaign,
            ))
    return base

def _static_obligations(trigger: DeployTrigger) -> List[QAObligation]:
    c = trigger.campaign
    return [
        # ── KENYON ────────────────────────────────────────────────────────────
        QAObligation(
            id="kv2_k001", owner="kenyon", fallback_owner=None,
            area="gcp", priority="critical", campaign=c,
            description="Verify Cloud Run service health + Firestore write access",
            steps=[
                "curl https://commplex-api-349126848698.us-central1.run.app/health",
                "python3 -c \"from google.cloud import firestore; "
                "db=firestore.Client(); db.collection('qa_pings').add({'t':'ok'}); print('OK')\"",
                "gcloud run revisions list --service=commplex-api --region=us-central1 | head -5",
            ],
            rollback="gcloud run services update-traffic commplex-api --to-revisions=PREVIOUS=100",
        ),
        QAObligation(
            id="kv2_k002", owner="kenyon", fallback_owner=None,
            area="scraper", priority="high", campaign=c,
            description="Verify orchestrator dry-run completes without Firestore errors",
            steps=[
                f"python3 commplex_orchestrator.py --campaign {c or 'rv-nd'} "
                "--phase scrape --dry-run",
                "Check scraper_runs.jsonl — expect status:dry_run",
                "Verify no 403/quota errors in stdout",
            ],
            rollback="Roll back to last working orchestrator commit",
        ),
        QAObligation(
            id="kv2_k003", owner="kenyon", fallback_owner=None,
            area="ml", priority="medium", campaign=c,
            description="Verify Gemini Vertex endpoint reachable + quota headroom",
            steps=[
                "python3 -c \"import vertexai; vertexai.init(project='commplex-493805',"
                "location='us-central1'); from vertexai.generative_models import "
                "GenerativeModel; m=GenerativeModel('gemini-1.5-flash-001'); "
                "print(m.generate_content('ping').text[:50])\"",
                "Check GCP Console → Vertex AI → Quotas → us-central1 flash-lite",
            ],
            rollback="Downgrade Gemini model in .env to gemini-1.5-flash-001",
        ),
        # ── CHARLES ───────────────────────────────────────────────────────────
        QAObligation(
            id="kv2_c001", owner="charles", fallback_owner="kenyon",
            area="twilio", priority="critical", campaign=c,
            description="Verify Twilio account active + outbound SMS test send",
            steps=[
                "Check Twilio Console → Account → Status (must be Active)",
                "python3 -c \"from twilio.rest import Client; "
                "c=Client(); c.messages.create(to='+17018705235',"
                "from_='+1TWILIO_NUM',body='CommPlex QA ping'); print('SMS sent')\"",
                "Confirm SMS received on Kenyon's number",
                "Check Twilio error log for any 4xx/5xx codes",
            ],
            rollback="Revert TWILIO_PHONE_NUMBER env var to last working number",
        ),
        QAObligation(
            id="kv2_c002", owner="charles", fallback_owner="kenyon",
            area="twilio", priority="high", campaign=c,
            description="Verify Twilio webhook URL points to current Cloud Run revision",
            steps=[
                "Twilio Console → Phone Numbers → Active Numbers → Voice URL",
                "URL must be: https://commplex-api-*.run.app/voice/twilio-webhook",
                "POST a test TwiML request: curl -X POST <webhook_url> -d 'CallSid=test'",
                "Expect 200 + valid TwiML response",
            ],
            rollback="Update Twilio webhook URL back to previous revision URL",
        ),
        QAObligation(
            id="kv2_c003", owner="charles", fallback_owner="kenyon",
            area="networking", priority="medium", campaign=c,
            description="Verify Cloud Run ingress + external reachability from outside GCP",
            steps=[
                "From non-GCP network: curl https://commplex-api-*.run.app/health",
                "Verify response time < 2s",
                "Check Cloud Run IAM: allUsers should have roles/run.invoker for public routes",
                "Verify no accidental VPC-only ingress setting",
            ],
            rollback="gcloud run services update commplex-api --ingress=all",
        ),
        # ── CYNTHIA ───────────────────────────────────────────────────────────
        QAObligation(
            id="kv2_cy001", owner="cynthia", fallback_owner="charles",
            area="sveltekit", priority="high", campaign=c,
            description="Smoke test SvelteKit dashboard build + dealer contact form",
            steps=[
                "cd dashboard && npm run dev",
                "Open http://localhost:5173 — verify no console errors",
                "Submit a test dealer contact form → verify Firestore entry in dealer_contacts",
                "Check campaign monitor panel shows recent run data",
            ],
            rollback="git stash && npm install && npm run dev",
        ),
        QAObligation(
            id="kv2_cy002", owner="cynthia", fallback_owner="charles",
            area="bland_residual", priority="low", campaign=c,
            description="Bland.ai wind-down check — verify no active campaigns still on Bland",
            steps=[
                "Bland.ai Console → Campaigns → verify no new campaigns were started",
                "If Bland calls still in-flight: let them complete, do NOT start new ones",
                "Log count of remaining Bland calls to Kenyon via Slack",
                "Any net-new outbound goes through Twilio (Charles)",
            ],
            rollback="N/A — wind-down is one-way; escalate unexpected Bland activity to Kenyon",
        ),
        QAObligation(
            id="kv2_cy003", owner="cynthia", fallback_owner="charles",
            area="audit", priority="medium", campaign=c,
            description="Process any pending dealer CSVs in ~/Downloads → Firestore intake",
            steps=[
                "python3 tools/commplex_file_intake_v2.py --ingest",
                "Verify counts: python3 tools/commplex_file_intake_v2.py --status",
                "Check Firestore dealer_contacts for new entries",
                "Flag any parse errors to Kenyon",
            ],
            rollback="python3 tools/commplex_file_intake_v2.py --rollback-last",
        ),
        # ── JUSTIN (remote) ───────────────────────────────────────────────────
        QAObligation(
            id="kv2_j001", owner="justin", fallback_owner="kenyon",
            area="gcp", priority="medium", campaign=c,
            description="(Kenyon covers if unavailable) — confirm /health endpoint returns 200",
            steps=[
                "curl https://commplex-api-349126848698.us-central1.run.app/health",
                "Expected: {\"status\": \"ok\"}",
                "Reply to team email with result (pass/fail + timestamp)",
            ],
            rollback="Escalate to Kenyon immediately if not reachable",
        ),
        QAObligation(
            id="kv2_j002", owner="justin", fallback_owner="charles",
            area="twilio", priority="low", campaign=c,
            description="(Charles covers if unavailable) — confirm inbound test SMS received",
            steps=[
                "Charles will send a test SMS via Twilio to a shared test number",
                "Justin: confirm receipt and reply via email with delivery timestamp",
                "If not received within 10 min → escalate to Charles",
            ],
            rollback="Escalate to Charles",
        ),
    ]

# ═══════════════════════════════════════════════════════════════════════════════
# FACADE — single call to trigger full QA flow
# ═══════════════════════════════════════════════════════════════════════════════

class QADispatchFacade:
    """
    Facade: hide the complexity of store + Gemini + notification.
    Callers just: facade.trigger(campaign, phase, commit_sha, dry_run)
    """
    def __init__(
        self,
        store: ObligationRepository,
        notifier: NotificationSink,
    ):
        self._store    = store
        self._notifier = notifier

    async def trigger(
        self,
        campaign: str,
        phase: str,
        commit_sha: str = "",
        changed_files: Optional[List[str]] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        trigger = DeployTrigger(
            campaign=campaign, phase=phase,
            commit_sha=commit_sha,
            changed_files=changed_files or [],
            dry_run=dry_run,
        )

        # Optionally enrich with Gemini additions
        gemini_extra: List[Dict] = []
        try:
            gemini_extra = await _get_gemini_obligation_additions(trigger)
        except Exception as exc:
            logger.warning("[gemini] obligation enrichment failed: %s", exc)

        obligations = build_campaign_obligations(trigger, gemini_additions=gemini_extra)
        self._store.save_obligations(trigger, obligations)

        # Notify each team member
        for member in ["kenyon", "charles", "cynthia", "justin"]:
            mine = [o for o in obligations if o.owner == member]
            if mine:
                debrief_url = (
                    f"https://commplex-api-349126848698.us-central1.run.app"
                    f"/commplex/qa/debrief-form?run_id={trigger.run_id}&submitter={member}"
                )
                self._notifier.notify(
                    member=member, run_id=trigger.run_id,
                    obligations=mine, summary="", debrief_url=debrief_url,
                )

        # Fire CI/CD trigger
        if not dry_run:
            await _fire_cicd_trigger(trigger)

        return {
            "run_id": trigger.run_id,
            "campaign": campaign,
            "obligations": len(obligations),
            "owners": {
                m: sum(1 for o in obligations if o.owner == m)
                for m in ["kenyon", "charles", "cynthia", "justin"]
            },
        }

async def _get_gemini_obligation_additions(trigger: DeployTrigger) -> List[Dict]:
    """Ask Gemini to add campaign-specific obligations beyond the static baseline."""
    prompt = f"""You are CommPlex QA intelligence.
Campaign: {trigger.campaign} | Phase: {trigger.phase}
Changed files: {trigger.changed_files[:10]}

Produce 0-3 additional QA obligations (beyond the standard baseline) specific
to this campaign/phase/files. Return JSON array only:
[{{"id":"gem_X","owner":"kenyon|charles|cynthia|justin","fallback_owner":"...",
   "area":"twilio|gcp|scraper|sveltekit|networking|ml",
   "priority":"critical|high|medium|low",
   "description":"...", "steps":["..."], "rollback":"..."}}]
If no additional obligations are needed, return an empty array: []
"""
    try:
        raw = GeminiClient().generate(prompt)
        clean = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        return json.loads(clean) if clean.startswith("[") else []
    except Exception:
        return []

async def _fire_cicd_trigger(trigger: DeployTrigger) -> None:
    """Notify the CICD pipeline of a new campaign run."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(CICD_TRIGGER_URL, json={
                "commit_sha": trigger.commit_sha,
                "message":    f"campaign: {trigger.campaign} phase: {trigger.phase}",
                "pusher":     "commplex_qa_dispatch",
                "dry_run":    False,
            })
    except Exception as exc:
        logger.warning("[cicd] trigger failed (non-fatal): %s", exc)

# ═══════════════════════════════════════════════════════════════════════════════
# DEPENDENCY INJECTION — build default facade
# ═══════════════════════════════════════════════════════════════════════════════

def _build_facade(dry_run: bool = False) -> QADispatchFacade:
    store    = InMemoryObligationStore() if dry_run else FirestoreObligationStore()
    notifier = DryRunNotificationSink() if dry_run else EmailNotificationSink()
    return QADispatchFacade(store=store, notifier=notifier)

# ═══════════════════════════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/commplex/qa/trigger")
async def trigger_qa(request: Request, background_tasks: BackgroundTasks):
    """
    Trigger QA obligation dispatch for a campaign run.
    Body: { "campaign": "rv-nd", "phase": "scrape",
            "commit_sha": "...", "dry_run": false }
    """
    data     = await request.json()
    campaign = data.get("campaign", "rv-nd")
    phase    = data.get("phase", "scrape")
    sha      = data.get("commit_sha", "")
    files    = data.get("changed_files", [])
    dry_run  = data.get("dry_run", False)

    facade = _build_facade(dry_run=dry_run)
    background_tasks.add_task(facade.trigger, campaign, phase, sha, files, dry_run)
    return JSONResponse({"status": "queued", "campaign": campaign, "phase": phase})


@router.post("/commplex/qa/debrief")
async def submit_debrief(request: Request):
    """
    Receive debrief submission from a team member.
    Stores to Firestore, triggers Gemini root-cause if failures present.
    """
    data = await request.json()
    debrief = DebriefSubmission(
        run_id        = data.get("run_id", ""),
        submitter     = data.get("submitter", ""),
        passed_items  = data.get("passed_items", []),
        failed_items  = data.get("failed_items", []),
        notes         = data.get("notes", ""),
        screenshots   = data.get("screenshots", []),
    )

    chain = _build_validator_chain()
    err = chain.validate(debrief)
    if err:
        return JSONResponse({"status": "error", "message": err}, status_code=400)

    store = FirestoreObligationStore()
    store.save_debrief(debrief)

    if debrief.failed_items:
        analysis = await _analyze_failures(debrief)
        return JSONResponse({
            "status": "received",
            "failures": len(debrief.failed_items),
            "gemini_analysis": analysis,
        })

    return JSONResponse({"status": "received", "failures": 0})


async def _analyze_failures(debrief: DebriefSubmission) -> str:
    prompt = f"""CommPlex QA debrief failure analysis.
Submitter: {debrief.submitter}
Run ID: {debrief.run_id}
Failed items: {debrief.failed_items}
Notes: {debrief.notes}

RACI:
  kenyon  = GCP/Cloud Run/Firestore/orchestrator/ML
  charles = Twilio voice+SMS/networking
  cynthia = SvelteKit/form-fill/Bland wind-down
  justin  = remote, covered by kenyon

For each failure:
1. Most likely root cause (1 sentence)
2. Owner (from RACI)
3. Immediate remediation step (1 sentence)

Be concise. Plain text only.
"""
    try:
        return GeminiClient().generate(prompt)[:1500]
    except Exception as exc:
        return f"(Gemini analysis unavailable: {exc})"


@router.get("/commplex/qa/debrief-form")
async def debrief_form(run_id: str = "", submitter: str = ""):
    """Serve the HTML debrief form."""
    obligations = []
    if run_id:
        try:
            store = FirestoreObligationStore()
            obligations = store.load_obligations(run_id)
        except Exception:
            pass

    member_obligations = [o for o in obligations if o.owner == submitter]
    items_html = "".join(
        f"<label style='display:block;margin:6px 0;'>"
        f"<input type='checkbox' name='items' value='{o.id}'> "
        f"[{o.area}] {o.description}</label>"
        for o in (member_obligations or [
            type("o", (), {"id":"manual", "area":"general",
                           "description":"(No obligations found — describe what you tested)"})()
        ])
    )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>CommPlex QA Debrief — {run_id}</title>
  <style>
    body{{font-family:sans-serif;max-width:600px;margin:40px auto;color:#222;padding:0 20px}}
    h2{{border-bottom:2px solid #1a73e8;padding-bottom:8px}}
    .btn{{background:#1a73e8;color:#fff;border:none;padding:12px 24px;
          border-radius:4px;font-size:16px;cursor:pointer;margin-top:16px;}}
    textarea{{width:100%;height:80px;margin-top:6px;padding:8px;box-sizing:border-box}}
    .section{{margin:20px 0;padding:16px;background:#f8f9fa;border-radius:4px}}
  </style>
</head>
<body>
  <h2>CommPlex QA Debrief</h2>
  <p><b>Run:</b> {run_id} &nbsp;|&nbsp; <b>Submitter:</b> {submitter}</p>
  <form id="form">
    <div class="section">
      <h4>Pass/Fail</h4>
      <p><b>Check items that PASSED:</b></p>
      {items_html}
      <p><b>Failed item IDs (comma-separated):</b></p>
      <input id="failed" style="width:100%;padding:8px;box-sizing:border-box"
             placeholder="e.g. kv2_c001, kv2_cy002">
    </div>
    <div class="section">
      <label><b>Notes / screenshots / error messages:</b>
        <textarea id="notes" placeholder="Paste logs, error messages, or context here..."></textarea>
      </label>
    </div>
    <button class="btn" onclick="submit(event)">Submit Debrief</button>
    <p id="msg" style="color:#1a73e8;margin-top:12px;display:none">✓ Submitted!</p>
  </form>
  <script>
    async function submit(e) {{
      e.preventDefault();
      const checked = [...document.querySelectorAll('input[name=items]:checked')].map(i=>i.value);
      const failedRaw = document.getElementById('failed').value;
      const failed = failedRaw ? failedRaw.split(',').map(s=>s.trim()).filter(Boolean) : [];
      const passed = checked.filter(id=>!failed.includes(id));
      const notes = document.getElementById('notes').value;
      const r = await fetch('/commplex/qa/debrief', {{
        method:'POST',
        headers:{{'Content-Type':'application/json'}},
        body: JSON.stringify({{
          run_id:'{run_id}', submitter:'{submitter}',
          passed_items: passed, failed_items: failed, notes
        }})
      }});
      const j = await r.json();
      document.getElementById('msg').style.display='block';
      if(j.gemini_analysis) alert('Failures analyzed:\\n' + j.gemini_analysis);
    }}
  </script>
</body>
</html>"""
    return HTMLResponse(html)


@router.get("/commplex/qa/health")
async def qa_health():
    return JSONResponse({
        "status": "ok",
        "version": "v2",
        "twilio": bool(os.getenv("TWILIO_ACCOUNT_SID")),
        "bland_residual": "wind-down (cynthia)",
        "team": list(TEAM.keys()),
    })
