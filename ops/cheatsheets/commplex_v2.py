#!/usr/bin/env python3
"""
commplex_test_cheatsheet_v2.py
CommPlex Big Scraper / Orchestrator — Rolling Test Cheatsheet · v2

CHANGES FROM v1:
  - Bland.ai REMOVED from Charles's test surface (wind-down; Cynthia monitors residual)
  - Twilio IS Charles's primary QA surface (voice + SMS + webhook verification)
  - Justin added as 4th RACI member (remote coverage priority: kenyon → charles → cynthia)
  - CI/CD Gemini pipeline obligations added
  - File intake v2 obligations (BaT, RV Trader, auction history)
  - SOLID: each obligation class encapsulates one concern
  - Status tracking: each obligation has a status field (pending/pass/fail/skip)

RACI (v2):
  kenyon  → GCP / Cloud Run / Firestore / orchestrator / big scraper / ML/MSCS / Android
  charles → Twilio voice+SMS / networking / infra verification
  cynthia → SvelteKit dashboard / form fill / Bland.ai wind-down / smoke QA
  justin  → Remote (coverage: kenyon > charles > cynthia)

Run: python3 commplex_test_cheatsheet_v2.py
     python3 commplex_test_cheatsheet_v2.py --owner charles
     python3 commplex_test_cheatsheet_v2.py --critical
     python3 commplex_test_cheatsheet_v2.py --status
"""

import argparse
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

# ═══════════════════════════════════════════════════════════════════════════════
# SYSTEM STATE — Phase 1 / v2 Baseline
# ═══════════════════════════════════════════════════════════════════════════════

CURRENT_STATE = {
    "phase":              "Phase 1 — Campaign Execution (v2)",
    "voice_sms":          "Twilio (Charles) — replacing Bland.ai for all new outbound",
    "bland_ai_status":    "WIND-DOWN — Cynthia monitors residual calls only, no new campaigns",
    "firestore":          "commplex-493805 / dealer_contacts + campaigns + deploy_analyses",
    "scraper_status":     "boilerplate complete — BaT/RVTrader/auction parsers added (v2)",
    "gmail_classifier":   "boilerplate complete — OAuth creds needed (4 accounts)",
    "dashboard":          "Phase 2 (SvelteKit — Cynthia, not started)",
    "corpus_rag":         "Phase 2 (not started)",
    "approval_queue":     "Phase 2 (not started)",
    "cicd_gemini":        "commplex_cicd_gemini.py — webhook registered, Gemini long-think active",
    "file_intake_v2":     "commplex_file_intake_v2.py — BaT/RVTrader/auction parsers wired",
    "justin_status":      "Remote — covered by kenyon (first) then charles/cynthia",
}

CAMPAIGNS = {
    "rv-nd":      {"vehicle": "2017 Jayco Eagle 26.5BHS",        "floor": 30000, "ceiling": 36000,  "regions": ["ND","SD","MT"]},
    "truck-nd":   {"vehicle": "2006 Ford F-350 King Ranch",       "floor": 18000, "ceiling": 24000,  "regions": ["ND","SD","MN"]},
    "classic-nd": {"vehicle": "1988 Lincoln Town Car Signature",  "floor": 8000,  "ceiling": 12000,  "regions": ["ND","National"]},
    "hybrid-nd":  {"vehicle": "2016 Lincoln MKZ Hybrid",          "floor": 4000,  "ceiling": 12000,  "regions": ["ND","National"]},
}

API     = "https://commplex-api-349126848698.us-central1.run.app"
REPO    = "~/arc-badlands-commplex"
PROJECT = "commplex-493805"

# ═══════════════════════════════════════════════════════════════════════════════
# OBLIGATION DATACLASS
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Obligation:
    id: str
    owner: str
    fallback: Optional[str]
    area: str
    priority: str          # critical | high | medium | low
    desc: str
    steps: List[str]
    rollback: str = ""
    auto_cmd: str = ""
    status: str = "pending"    # pending | pass | fail | skip
    phase: str = "Phase 1"
    tags: List[str] = field(default_factory=list)

    def mark(self, status: str) -> "Obligation":
        self.status = status
        return self

    def display(self, show_steps: bool = True) -> str:
        icon = {"critical":"🔴","high":"🟠","medium":"🟡","low":"🟢"}.get(self.priority,"⚪")
        stat = {"pending":"⏳","pass":"✅","fail":"❌","skip":"⏭️"}.get(self.status,"❓")
        fb   = f" [fallback: {self.fallback}]" if self.fallback else ""
        lines = [
            f"\n{stat} {icon} [{self.id}] [{self.owner.upper()}{fb}] [{self.area}] "
            f"[{self.priority.upper()}]",
            f"   {self.desc}",
        ]
        if show_steps:
            for i, s in enumerate(self.steps, 1):
                lines.append(f"   {i}. {s}")
        if self.rollback:
            lines.append(f"   ↩ Rollback: {self.rollback}")
        if self.auto_cmd:
            lines.append(f"   ⚙ Auto: {self.auto_cmd}")
        return "\n".join(lines)

# ═══════════════════════════════════════════════════════════════════════════════
# KENYON — GCP / Cloud Run / Firestore / Orchestrator / ML / Android
# ═══════════════════════════════════════════════════════════════════════════════

KENYON: List[Obligation] = [

    # ─── INFRA ────────────────────────────────────────────────────────────────
    Obligation(
        id="kv2_k001", owner="kenyon", fallback=None,
        area="gcp", priority="critical",
        desc="Cloud Run service health + Firestore write access",
        steps=[
            f"curl {API}/health → expect {{\"status\":\"ok\"}}",
            f"gcloud run revisions list --service=commplex-api --region=us-central1 | head -6",
            "python3 -c \"from google.cloud import firestore; "
            "db=firestore.Client(); db.collection('qa_pings').add({'t':'ok'}); print('✓ Firestore OK')\"",
        ],
        rollback="gcloud run services update-traffic commplex-api --to-revisions=PREVIOUS=100",
        auto_cmd=f"curl -sf {API}/health | python3 -c \"import sys,json; "
                 "d=json.load(sys.stdin); sys.exit(0 if d['status']=='ok' else 1)\"",
        tags=["infra","smoke"],
    ),
    Obligation(
        id="kv2_k002", owner="kenyon", fallback=None,
        area="gcp", priority="high",
        desc="Verify Cloud Run min-instances=1 (no cold starts on Twilio webhook)",
        steps=[
            "gcloud run services describe commplex-api --region=us-central1 "
            "| grep -A5 'scaling'",
            "Expected: minInstanceCount >= 1",
            "If 0: gcloud run services update commplex-api --min-instances=1 "
            "--region=us-central1",
        ],
        rollback="gcloud run services update commplex-api --min-instances=0",
        tags=["infra","twilio"],
    ),

    # ─── ORCHESTRATOR ─────────────────────────────────────────────────────────
    Obligation(
        id="kv2_k003", owner="kenyon", fallback=None,
        area="scraper", priority="high",
        desc="Orchestrator dry-run — all campaigns, no Firestore writes",
        steps=[
            f"cd {REPO}",
            "for c in rv-nd truck-nd classic-nd hybrid-nd; do",
            "  python3 commplex_orchestrator.py --campaign $c --phase scrape --dry-run",
            "done",
            "Check scraper_runs.jsonl — all entries should have status:dry_run",
        ],
        rollback="Roll back orchestrator to last working commit",
        tags=["orchestrator","smoke"],
    ),
    Obligation(
        id="kv2_k004", owner="kenyon", fallback=None,
        area="scraper", priority="medium",
        desc="File intake v2 daemon — ingest pending files from Downloads",
        steps=[
            f"cd {REPO}/tools",
            "python3 commplex_file_intake_v2.py --status",
            "python3 commplex_file_intake_v2.py --ingest",
            "python3 commplex_file_intake_v2.py --status  # compare counts",
            "Verify Firestore dealer_contacts updated: gcloud firestore ...",
        ],
        rollback="python3 commplex_file_intake_v2.py --rollback-last",
        tags=["intake","firestore"],
    ),

    # ─── ML / GEMINI ──────────────────────────────────────────────────────────
    Obligation(
        id="kv2_k005", owner="kenyon", fallback=None,
        area="ml", priority="medium",
        desc="Verify Gemini Vertex quota headroom in us-central1",
        steps=[
            "GCP Console → Vertex AI → Quotas",
            "Filter: region=us-central1, model=gemini-*",
            "Check: Online prediction requests/min — must be >0 remaining",
            "python3 -c \"import vertexai; vertexai.init(project='commplex-493805',"
            "location='us-central1'); from vertexai.generative_models import "
            "GenerativeModel; m=GenerativeModel('gemini-1.5-flash-001'); "
            "print(m.generate_content('ping').text[:30])\"",
        ],
        rollback="Downgrade GEMINI_MODEL env var to gemini-1.5-flash-001",
        tags=["ml","gemini"],
    ),

    # ─── CI/CD GEMINI PIPELINE ────────────────────────────────────────────────
    Obligation(
        id="kv2_k006", owner="kenyon", fallback=None,
        area="ml", priority="high",
        desc="Verify commplex_cicd_gemini.py webhook registered and reachable",
        steps=[
            f"curl -X POST {API}/cicd/health → verify team roster and thinking flag",
            "GitHub → Repo → Settings → Webhooks → verify payload URL = "
            f"{API}/cicd/github-webhook",
            "Trigger manual analysis: POST {API}/cicd/manual-trigger with "
            "{{\"commit_sha\":\"test\",\"message\":\"smoke test\",\"dry_run\":true}}",
            "Verify Firestore deploy_analyses collection updated",
        ],
        rollback="Disable GitHub webhook temporarily if Gemini quota issues",
        tags=["cicd","gemini","infra"],
    ),

    # ─── BaT / AUCTION DATA ───────────────────────────────────────────────────
    Obligation(
        id="kv2_k007", owner="kenyon", fallback="cynthia",
        area="scraper", priority="medium",
        desc="Parse BaT + auction history CSVs and verify pricing reference data",
        steps=[
            "Download BaT sold results CSV for: Jayco Eagle, F-350 King Ranch, "
            "Lincoln Town Car, Lincoln MKZ Hybrid",
            "Place in ~/Downloads (naming: bat_jayco_2024.csv, bat_f350_2024.csv, etc.)",
            "python3 tools/commplex_file_intake_v2.py --parse-bat",
            "Verify Firestore dealer_contacts: "
            "gcloud firestore ... | grep source:bat | head -5",
            "Cross-reference sold prices against knowledge_base.csv pricing floors",
        ],
        rollback="python3 tools/commplex_file_intake_v2.py --rollback-last",
        tags=["intake","bat","pricing"],
    ),
]

# ═══════════════════════════════════════════════════════════════════════════════
# CHARLES — Twilio voice+SMS / Networking / Infra
# ═══════════════════════════════════════════════════════════════════════════════

CHARLES: List[Obligation] = [

    # ─── TWILIO BASELINE ──────────────────────────────────────────────────────
    Obligation(
        id="kv2_c001", owner="charles", fallback="kenyon",
        area="twilio", priority="critical",
        desc="Twilio account active + outbound SMS test to Kenyon's number",
        steps=[
            "Twilio Console → Account → Dashboard → Status must be Active",
            "python3 -c \"from twilio.rest import Client; import os; "
            "c=Client(os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN')); "
            "c.messages.create(to='+17018705235', from_=os.getenv('TWILIO_PHONE_NUMBER'), "
            "body='CommPlex v2 QA ping'); print('✓ SMS dispatched')\"",
            "Confirm receipt on Kenyon's device within 60 seconds",
        ],
        rollback="Check TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_PHONE_NUMBER env vars",
        auto_cmd="python3 -c \"from twilio.rest import Client; import os; "
                 "c=Client(os.getenv('TWILIO_ACCOUNT_SID'),os.getenv('TWILIO_AUTH_TOKEN')); "
                 "print(c.accounts.get(os.getenv('TWILIO_ACCOUNT_SID')).fetch().status)\"",
        tags=["twilio","smoke","critical"],
    ),
    Obligation(
        id="kv2_c002", owner="charles", fallback="kenyon",
        area="twilio", priority="critical",
        desc="Twilio webhook URL points to current Cloud Run revision",
        steps=[
            "Twilio Console → Phone Numbers → Active Numbers → [your number]",
            "Voice URL must be: "
            "https://commplex-api-349126848698.us-central1.run.app/voice/twilio-webhook",
            "Status Callback URL must point to: .../voice/twilio-status",
            "Test POST: curl -X POST <webhook_url> -d 'CallSid=test&CallStatus=ringing'",
            "Expected: 200 + valid TwiML <Response> XML",
        ],
        rollback="Update Twilio webhook URL to prior revision URL in Twilio Console",
        tags=["twilio","webhook","critical"],
    ),
    Obligation(
        id="kv2_c003", owner="charles", fallback="kenyon",
        area="twilio", priority="high",
        desc="Twilio outbound voice call test (dry-run to test number)",
        steps=[
            "python3 -c \"from twilio.rest import Client; import os; "
            "c=Client(os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN')); "
            "call=c.calls.create(to='+15005550006', "  # Twilio test number
            "from_=os.getenv('TWILIO_PHONE_NUMBER'), "
            "url='http://demo.twilio.com/docs/voice.xml'); print(call.sid)\"",
            "Expected: call SID returned, no exception",
            "Check Twilio Console → Monitor → Calls for the test call",
        ],
        rollback="Verify TWILIO_PHONE_NUMBER has voice capability in Twilio Console",
        tags=["twilio","voice"],
    ),
    Obligation(
        id="kv2_c004", owner="charles", fallback="kenyon",
        area="twilio", priority="high",
        desc="Verify Twilio call log exports are landing in intake correctly",
        steps=[
            "Export a Twilio call log CSV from Twilio Console (last 7 days)",
            "Save as: twilio_calls_<date>.csv to ~/Downloads",
            "python3 tools/commplex_file_intake_v2.py --ingest",
            "Verify twilio_logs/ directory has the file",
            "Verify records appeared in Firestore dealer_contacts (source:twilio)",
        ],
        rollback="python3 tools/commplex_file_intake_v2.py --rollback-last",
        tags=["twilio","intake","logging"],
    ),

    # ─── NETWORKING ───────────────────────────────────────────────────────────
    Obligation(
        id="kv2_c005", owner="charles", fallback="kenyon",
        area="networking", priority="high",
        desc="Verify Cloud Run public reachability from external network",
        steps=[
            "From cellular/non-GCP network (phone hotspot or VPN OFF):",
            f"curl -sf {API}/health",
            "Expected: {{\"status\":\"ok\"}} in <2s",
            "Verify TLS: openssl s_client -connect commplex-api-*.run.app:443 < /dev/null",
            "Verify no VPC-only ingress: gcloud run services describe commplex-api "
            "--region=us-central1 | grep ingress",
        ],
        rollback="gcloud run services update commplex-api --ingress=all --region=us-central1",
        tags=["networking","infra"],
    ),
    Obligation(
        id="kv2_c006", owner="charles", fallback="kenyon",
        area="networking", priority="medium",
        desc="Verify Twilio IP range not blocked by Cloud Run or any upstream firewall",
        steps=[
            "Twilio IP ranges: https://www.twilio.com/docs/sip-trunking/firewall-access",
            "Cloud Run doesn't have ingress IP filtering by default — verify no Cloud Armor rule",
            "GCP Console → Cloud Armor → verify no commplex-api policy blocking Twilio ranges",
            "Test: trigger inbound Twilio webhook callback and verify it reaches the service",
        ],
        rollback="Remove Cloud Armor rule if any is blocking Twilio CIDRs",
        tags=["networking","twilio","infra"],
    ),

    # ─── BLAND WIND-DOWN MONITORING (handoff from Cynthia) ───────────────────
    Obligation(
        id="kv2_c007", owner="charles", fallback="cynthia",
        area="networking", priority="low",
        desc="Confirm Bland.ai callbacks (if still in-flight) route correctly",
        steps=[
            "Charles: verify no Bland callbacks are hitting a dead Twilio number",
            "If Bland calls still completing: ensure callback webhook != Twilio endpoint",
            "Log remaining Bland call count to Kenyon",
            "No new Bland campaigns should be started — escalate if you see any",
        ],
        rollback="Escalate to Cynthia and Kenyon immediately",
        tags=["bland_residual","wind-down","monitoring"],
    ),
]

# ═══════════════════════════════════════════════════════════════════════════════
# CYNTHIA — SvelteKit / Form Fill / Bland Wind-Down / Smoke QA
# ═══════════════════════════════════════════════════════════════════════════════

CYNTHIA: List[Obligation] = [

    # ─── SVELTEKIT ────────────────────────────────────────────────────────────
    Obligation(
        id="kv2_cy001", owner="cynthia", fallback="charles",
        area="sveltekit", priority="high",
        desc="SvelteKit dashboard smoke test — dev build, console errors, form submit",
        steps=[
            f"cd {REPO}/dashboard && npm install && npm run dev",
            "Open http://localhost:5173 in browser",
            "Check browser console: no red errors",
            "Open Network tab → verify no 4xx/5xx requests on load",
            "Submit dealer contact form → check Firestore dealer_contacts for new entry",
            "Open campaign monitor panel → verify rv-nd stats visible",
        ],
        rollback="git stash && npm ci && npm run dev",
        tags=["sveltekit","smoke","dashboard"],
    ),
    Obligation(
        id="kv2_cy002", owner="cynthia", fallback="charles",
        area="sveltekit", priority="medium",
        desc="Verify SvelteKit build for production (no type errors, no missing env)",
        steps=[
            f"cd {REPO}/dashboard && npm run build",
            "Expected: BUILD SUCCESS — no TypeScript errors",
            "Check .env.production: VITE_API_URL must point to Cloud Run service URL",
            "npm run preview → open http://localhost:4173 and verify",
        ],
        rollback="Check tsconfig.json and vite.config.ts for recent changes",
        tags=["sveltekit","build"],
    ),

    # ─── FORM FILL ────────────────────────────────────────────────────────────
    Obligation(
        id="kv2_cy003", owner="cynthia", fallback="charles",
        area="forms", priority="medium",
        desc="Verify dealer contact form-fill scripts against updated form HTML",
        steps=[
            "Open current dealer contact form in browser (staging or local)",
            "Run form-fill script: python3 forms/dealer_contact_fill.py --dry-run",
            "Verify: all required fields populated correctly",
            "Submit one real form to test dealer (get Kenyon approval first)",
            "Confirm Firestore entry created with correct vehicle_type + segment",
        ],
        rollback="git diff forms/ to identify what changed in form-fill script",
        tags=["forms","smoke"],
    ),

    # ─── DEALER CSV INTAKE ────────────────────────────────────────────────────
    Obligation(
        id="kv2_cy004", owner="cynthia", fallback="kenyon",
        area="audit", priority="medium",
        desc="Process pending dealer CSVs + RV Trader exports from Downloads",
        steps=[
            "python3 tools/commplex_file_intake_v2.py --status  # before",
            "Check ~/Downloads for any dealer CSVs or RV Trader exports",
            "Rename RV Trader files to: rvtrader_<state>_<date>.csv",
            "python3 tools/commplex_file_intake_v2.py --ingest",
            "python3 tools/commplex_file_intake_v2.py --parse-rvt",
            "python3 tools/commplex_file_intake_v2.py --status  # after",
        ],
        rollback="python3 tools/commplex_file_intake_v2.py --rollback-last",
        tags=["intake","rvtrader","dealer_csvs"],
    ),

    # ─── BLAND WIND-DOWN ──────────────────────────────────────────────────────
    Obligation(
        id="kv2_cy005", owner="cynthia", fallback="kenyon",
        area="bland_residual", priority="low",
        desc="Bland.ai wind-down status: log remaining calls, no new campaigns",
        steps=[
            "Bland.ai Console → Campaigns → count remaining in-flight calls",
            "Log to intake: python3 tools/commplex_file_intake_v2.py --status",
            "Check bland_residual/ dir for call logs",
            "CRITICAL: do NOT start new Bland campaigns — all new outbound → Twilio (Charles)",
            "Email or Slack Kenyon + Charles with remaining Bland call count",
        ],
        rollback="N/A — read-only monitoring. Escalate unexpected Bland activity to Kenyon.",
        tags=["bland_residual","wind-down","monitoring"],
    ),
]

# ═══════════════════════════════════════════════════════════════════════════════
# JUSTIN — Remote (coverage: kenyon → charles → cynthia)
# All Justin obligations are the simplest form of kenyon/charles/cynthia tasks.
# ═══════════════════════════════════════════════════════════════════════════════

JUSTIN: List[Obligation] = [

    Obligation(
        id="kv2_j001", owner="justin", fallback="kenyon",
        area="gcp", priority="medium",
        desc="(Kenyon covers if unavailable) — confirm /health returns 200",
        steps=[
            f"curl {API}/health",
            "Expected: {{\"status\":\"ok\"}}",
            "If failure: immediately Slack/email Kenyon with full curl output",
            "Do NOT attempt to fix — report only",
        ],
        rollback="Escalate to Kenyon immediately",
        tags=["smoke","remote"],
    ),
    Obligation(
        id="kv2_j002", owner="justin", fallback="charles",
        area="twilio", priority="low",
        desc="(Charles covers if unavailable) — confirm inbound test SMS received",
        steps=[
            "Charles sends test SMS to shared test number via Twilio",
            "Justin: confirm receipt and reply with delivery timestamp",
            "If SMS not received within 10 min: escalate to Charles via Slack",
        ],
        rollback="Escalate to Charles",
        tags=["twilio","sms","remote"],
    ),
    Obligation(
        id="kv2_j003", owner="justin", fallback="cynthia",
        area="sveltekit", priority="low",
        desc="(Cynthia covers if unavailable) — load SvelteKit dashboard URL, report status",
        steps=[
            "Open: http://localhost:5173 (if running locally) OR "
            "the staging URL Cynthia provides",
            "Check browser: page loads, no blank screen, no major errors visible",
            "Report: pass/fail + screenshot to Cynthia via Slack/email",
        ],
        rollback="Escalate to Cynthia",
        tags=["sveltekit","smoke","remote"],
    ),
    Obligation(
        id="kv2_j004", owner="justin", fallback="kenyon",
        area="audit", priority="low",
        desc="(Kenyon covers if unavailable) — confirm debrief form submission works",
        steps=[
            f"Open: {API}/commplex/qa/debrief-form?run_id=test&submitter=justin",
            "Check at least one obligation checkbox",
            "Click Submit Debrief",
            "Expected: confirmation message ✓",
            "If error: screenshot + escalate to Kenyon",
        ],
        rollback="Escalate to Kenyon",
        tags=["qa","debrief","remote"],
    ),
]

# ═══════════════════════════════════════════════════════════════════════════════
# ALL OBLIGATIONS
# ═══════════════════════════════════════════════════════════════════════════════

ALL_OBLIGATIONS: List[Obligation] = KENYON + CHARLES + CYNTHIA + JUSTIN

OBLIGATIONS_BY_OWNER: Dict[str, List[Obligation]] = {
    "kenyon":  KENYON,
    "charles": CHARLES,
    "cynthia": CYNTHIA,
    "justin":  JUSTIN,
}

# ═══════════════════════════════════════════════════════════════════════════════
# DISPLAY / SUMMARY
# ═══════════════════════════════════════════════════════════════════════════════

SEPARATOR = "─" * 72

def print_header() -> None:
    print(f"\n{'═'*72}")
    print("  CommPlex Test Cheatsheet v2")
    print(f"  Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  Phase: {CURRENT_STATE['phase']}")
    print(f"  Voice/SMS: {CURRENT_STATE['voice_sms']}")
    print(f"  Bland.ai: {CURRENT_STATE['bland_ai_status']}")
    print(f"{'═'*72}")

def print_campaigns() -> None:
    print(f"\n{'─'*72}")
    print("  CAMPAIGNS")
    print(f"{'─'*72}")
    for cid, c in CAMPAIGNS.items():
        print(f"  {cid:14s}  {c['vehicle']:40s}  ${c['floor']:,}–${c['ceiling']:,}  "
              f"{', '.join(c['regions'])}")

def print_owner_section(owner: str, obligations: List[Obligation],
                        show_steps: bool = True) -> None:
    area_map = {
        "kenyon":  "GCP / Cloud Run / Firestore / Orchestrator / ML/MSCS / Android",
        "charles": "Twilio voice+SMS / Networking / Infra verification",
        "cynthia": "SvelteKit / Form Fill / Bland wind-down / Smoke QA",
        "justin":  "Remote (coverage: kenyon → charles → cynthia)",
    }
    pending  = [o for o in obligations if o.status == "pending"]
    passing  = [o for o in obligations if o.status == "pass"]
    failing  = [o for o in obligations if o.status == "fail"]
    critical = [o for o in obligations if o.priority == "critical"]
    print(f"\n{'═'*72}")
    print(f"  {owner.upper()} — {area_map.get(owner,'')}")
    print(f"  {len(obligations)} total | {len(critical)} critical | "
          f"{len(pending)} pending | {len(passing)} pass | {len(failing)} fail")
    print(f"{'═'*72}")
    for ob in obligations:
        print(ob.display(show_steps=show_steps))
    print()

def print_summary() -> None:
    print_header()
    print_campaigns()
    print(f"\n{'─'*72}")
    print("  OBLIGATION SUMMARY")
    print(f"{'─'*72}")
    print(f"  {'OWNER':10s} {'TOTAL':6s} {'CRITICAL':10s} {'PENDING':9s} {'PASS':6s} {'FAIL':6s}")
    print(f"  {'─'*60}")
    for owner, obs in OBLIGATIONS_BY_OWNER.items():
        crit    = sum(1 for o in obs if o.priority == "critical")
        pending = sum(1 for o in obs if o.status == "pending")
        passing = sum(1 for o in obs if o.status == "pass")
        failing = sum(1 for o in obs if o.status == "fail")
        print(f"  {owner:10s} {len(obs):6d} {crit:10d} {pending:9d} {passing:6d} {failing:6d}")
    total = len(ALL_OBLIGATIONS)
    tc    = sum(1 for o in ALL_OBLIGATIONS if o.priority == "critical")
    print(f"  {'─'*60}")
    print(f"  {'TOTAL':10s} {total:6d} {tc:10d}")

def deploy_trigger_command(campaign: str = "rv-nd", phase: str = "scrape",
                            dry_run: bool = True) -> str:
    flag = "--dry-run " if dry_run else ""
    return f"python3 commplex_orchestrator.py --campaign {campaign} --phase {phase} {flag}"

def cicd_manual_trigger(commit_sha: str = "HEAD") -> str:
    return (
        f"curl -X POST {API}/cicd/manual-trigger "
        f"-H 'Content-Type: application/json' "
        f"-d '{{\"commit_sha\":\"{commit_sha}\",\"message\":\"manual QA trigger\","
        f"\"dry_run\":true}}'"
    )

# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser(description="CommPlex Test Cheatsheet v2")
    ap.add_argument("--owner",    choices=["kenyon","charles","cynthia","justin","all"],
                    default="all", help="Filter by owner")
    ap.add_argument("--critical", action="store_true", help="Show critical only")
    ap.add_argument("--status",   action="store_true", help="Summary table only")
    ap.add_argument("--no-steps", action="store_true", help="Hide step details")
    ap.add_argument("--json",     action="store_true", help="Output JSON for CI/CD")
    args = ap.parse_args()

    if args.json:
        output = {
            "generated":  datetime.utcnow().isoformat(),
            "state":      CURRENT_STATE,
            "campaigns":  CAMPAIGNS,
            "obligations": [
                {
                    "id": o.id, "owner": o.owner, "fallback": o.fallback,
                    "area": o.area, "priority": o.priority, "desc": o.desc,
                    "steps": o.steps, "rollback": o.rollback,
                    "auto_cmd": o.auto_cmd, "status": o.status,
                }
                for o in ALL_OBLIGATIONS
                if (not args.owner or args.owner == "all" or o.owner == args.owner)
                and (not args.critical or o.priority == "critical")
            ],
        }
        print(json.dumps(output, indent=2))
        return

    print_summary()

    if args.status:
        return

    owners = (["kenyon","charles","cynthia","justin"]
              if args.owner == "all" else [args.owner])

    for owner in owners:
        obs = OBLIGATIONS_BY_OWNER.get(owner, [])
        if args.critical:
            obs = [o for o in obs if o.priority == "critical"]
        if obs:
            print_owner_section(owner, obs, show_steps=not args.no_steps)

    print(f"\n{'─'*72}")
    print("  QUICK COMMANDS")
    print(f"{'─'*72}")
    for c in ["rv-nd","truck-nd","classic-nd","hybrid-nd"]:
        print(f"  {deploy_trigger_command(c, dry_run=True)}")
    print(f"\n  CICD MANUAL TRIGGER:")
    print(f"  {cicd_manual_trigger()}")
    print(f"\n  INTAKE STATUS:")
    print( "  python3 tools/commplex_file_intake_v2.py --status")
    print(f"\n  QA DEBRIEF FORM:")
    print(f"  {API}/commplex/qa/debrief-form?run_id=<run_id>&submitter=<you>")
    print()


if __name__ == "__main__":
    main()
