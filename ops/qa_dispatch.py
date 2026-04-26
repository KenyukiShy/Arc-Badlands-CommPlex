"""
qa_dispatch.py — Rolling QA Obligation Dispatcher · Arc Badlands CommPlex
Drop into: CommPlexAPI/server/routes/qa_dispatch.py

FLOW PER DEPLOY:
  1. POST /qa/trigger (Kenyon after every `gcloud run deploy`) or
     POST /qa/deploy-hook (Cloud Build Pub/Sub — automatic once subscribed)
  2. Gemini 2.5 Flash [thinking] reads: commit diff, build log, prior open obligations,
     local file tree → produces per-person JSON obligations
  3. Emails Charles & Cynthia with a link to their checklist form
  4. They open /qa/form/{id}?person=charles|cynthia, fill results, attach screenshots
  5. POST /qa/debrief → Gemini reads failures → escalates to fix owner
  6. Only NEW or CHANGED items require retesting — carried items roll forward

RACI:
  charles  → Twilio console, webhooks, A2P monitoring, live SMS/voice tests
  cynthia  → Smoke tests (call number, web chat, form), Firestore viewer, Cloud Run console
  kenyon   → GCP, Cloud Build, Vertex AI, IAM, continued development

DEPLOY NOTES:
  1. cp this file to CommPlexAPI/server/routes/qa_dispatch.py
  2. In CommPlexAPI/server/main.py:
       from .routes import ..., qa_dispatch
       app.include_router(qa_dispatch.router)
  3. Add to requirements.txt:  httpx
  4. Set env vars (via --set-env-vars or Secret Manager):
       GITHUB_PAT          Personal Access Token (repo read scope)
       SMTP_USER           Kenyon Gmail address
       SMTP_PASS           Gmail App Password (not account password)
       CHARLES_EMAIL       charles@...
       CYNTHIA_EMAIL       cynthia@...
       KENYON_EMAIL        kenyon@...
  5. Cloud Build Pub/Sub (auto-hook, optional):
       gcloud pubsub subscriptions create qa-deploy-hook \\
         --topic=cloud-builds \\
         --push-endpoint=https://commplex-api-349126848698.us-central1.run.app/qa/deploy-hook \\
         --project=commplex-493805
"""

import base64
import json
import os
import smtplib
import uuid
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import httpx
import vertexai
from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, JSONResponse
from google.cloud import firestore
from vertexai.generative_models import GenerationConfig, GenerativeModel

# Try to import ThinkingConfig — only in newer SDK versions
try:
    from vertexai.generative_models import ThinkingConfig
    _THINKING_AVAILABLE = True
except ImportError:
    _THINKING_AVAILABLE = False

router = APIRouter()

# ── Config ─────────────────────────────────────────────────────────────────────
PROJECT  = os.environ.get("GCP_PROJECT_ID", "commplex-493805")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

GH_TOKEN = os.environ.get("GITHUB_PAT", "")
GH_REPOS = [
    "shy2shy/arc-badlands-commplex",         # shy2shy = Kenyon's personal GH
    "KenyukiShy/Arc-Badlands-CommPlex",      # monorepo mirror
    "KenyukiShy/arcbadlandscompute",         # site repo
]

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")

TEAM = {
    "charles": {"email": os.environ.get("CHARLES_EMAIL", ""), "name": "Charles"},
    "cynthia": {"email": os.environ.get("CYNTHIA_EMAIL", ""), "name": "Cynthia"},
    "kenyon":  {"email": os.environ.get("KENYON_EMAIL", ""),  "name": "Kenyon"},
}

SERVICE_URL = os.environ.get(
    "SERVICE_URL",
    "https://commplex-api-349126848698.us-central1.run.app"
)

RACI_CONTEXT = {
    "charles": (
        "Twilio console access, phone number webhook configuration (voice + SMS), "
        "A2P/10DLC campaign monitoring, live SMS send/receive tests from real number, "
        "Twilio debugger logs, Media Streams WebSocket verification"
    ),
    "cynthia": (
        "Smoke tests: call 866-736-2349 and verify Audry responds correctly, "
        "check web chat on autobad.html, test HTML contact form submission, "
        "Firestore viewer in GCP console (verify leads collection), "
        "Cloud Run console (confirm latest revision serving 100%), "
        "UI/UX verification on site"
    ),
    "kenyon": (
        "GCP deploys, Cloud Build, Vertex AI quota management, IAM/service accounts, "
        "continued development, architecture decisions, code fixes when Gemini escalates"
    ),
}

# ── Firestore ──────────────────────────────────────────────────────────────────
_db = None

def _firestore():
    global _db
    if _db is None:
        _db = firestore.Client(project=PROJECT)
    return _db


# ── GitHub helpers ─────────────────────────────────────────────────────────────
async def _gh_get(url: str) -> Optional[dict]:
    if not GH_TOKEN:
        return None
    headers = {
        "Authorization": f"Bearer {GH_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(url, headers=headers)
            return r.json() if r.status_code == 200 else None
    except Exception as e:
        print(f"[GitHub] {e}")
        return None


async def get_commit_info(sha: str) -> dict:
    """Try each known repo until we find the commit."""
    for repo in GH_REPOS:
        data = await _gh_get(f"https://api.github.com/repos/{repo}/commits/{sha}")
        if data and "commit" in data:
            return {
                "sha":           data.get("sha", "")[:8],
                "repo":          repo,
                "message":       data.get("commit", {}).get("message", ""),
                "author":        data.get("commit", {}).get("author", {}).get("name", ""),
                "changed_files": [f["filename"] for f in data.get("files", [])],
                "additions":     sum(f.get("additions", 0) for f in data.get("files", [])),
                "deletions":     sum(f.get("deletions", 0) for f in data.get("files", [])),
            }
    return {}


# ── Gemini obligation generator ────────────────────────────────────────────────
def generate_obligations(deploy_info: dict, prior_open: list, local_tree: dict) -> dict:
    """
    Gemini 2.5 Flash with thinking analyzes a deploy and produces per-person obligations.
    Runs synchronously in a thread pool (called via run_in_executor).
    Returns: {summary, obligations, skipped_prior, notes_for_kenyon}
    """
    vertexai.init(project=PROJECT, location=LOCATION)

    # Build generation config — use thinking if available
    if _THINKING_AVAILABLE:
        gen_config = GenerationConfig(
            max_output_tokens=3000,
            temperature=1.0,  # required with thinking
            thinking_config=ThinkingConfig(thinking_budget=8192),
        )
    else:
        gen_config = GenerationConfig(max_output_tokens=2000, temperature=0.2)

    model = GenerativeModel(
        "gemini-2.5-flash",
        system_instruction="""You are the QA orchestrator for Arc Badlands CommPlex —
an autonomous vehicle sales system run by Kenyon Jones (Hazen, ND).

System: Python FastAPI on Cloud Run, Gemini AI, Twilio voice/SMS, Firestore, GitHub Pages site.
Vehicles: 1988 Town Car, 2016 MKZ Hybrid, 2006 F-350, 2017 Jayco Eagle.
Phone: (866) 736-2349 (voice), 701-888-5090 (SMS).
Site: https://kenyukishy.github.io/arcbadlandscompute/autobad.html
API: https://commplex-api-349126848698.us-central1.run.app

RACI — assign obligations to exactly the right person:
  charles  → Twilio console, number webhooks, A2P/10DLC, live call/SMS tests
  cynthia  → Smoke tests, GCP console viewer, Cloud Run revision check, site UI
  kenyon   → GCP deploys, code fixes, Vertex AI, architecture

RULES:
- Only assign obligations that are ACTUALLY AFFECTED by this deploy's changed files
- Be specific — include exact commands, URLs, or console paths to check
- Carry forward uncleared prior obligations unless they were clearly fixed by this deploy
- If a prior obligation is now irrelevant (the bug was fixed), add its id to skipped_prior
- Output ONLY valid JSON — no markdown, no preamble, no trailing commas""",
    )

    prior_str  = json.dumps(prior_open[:15], indent=2) if prior_open else "[]"
    tree_str   = json.dumps(local_tree, indent=2) if local_tree else "{}"
    deploy_str = json.dumps(deploy_info, indent=2)

    prompt = f"""DEPLOY INFO:
{deploy_str}

PRIOR OPEN OBLIGATIONS (not yet marked pass):
{prior_str}

LOCAL FILE TREE (Kenyon's Penguin — Downloads = intake, Documents = reviewed):
{tree_str}

Analyze this deploy and produce test obligations. Output this exact JSON structure:
{{
  "summary": "one sentence — what changed and what risk it introduces",
  "obligations": [
    {{
      "id": "ob_xxxxxxxx",
      "person": "charles|cynthia|kenyon",
      "area": "voice|sms|web|firestore|twilio|gcp|ui|deploy",
      "is_new": true,
      "priority": "critical|high|low",
      "description": "clear one-line description of what to test",
      "test_steps": [
        "Concrete step — include the actual command, URL, or console path",
        "..."
      ],
      "expected_result": "exactly what pass looks like",
      "retest_trigger": "what future change would require retesting this",
      "carried_from": null
    }}
  ],
  "skipped_prior": ["ob_id of prior obligations now irrelevant because this deploy fixed them"],
  "notes_for_kenyon": "any dev issues noticed in changed files, build log, or local tree"
}}"""

    try:
        resp = model.generate_content(prompt, generation_config=gen_config)
        text = resp.text.strip()
        # Strip markdown fences if Gemini wraps output
        if "```" in text:
            parts = text.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                try:
                    return json.loads(part)
                except Exception:
                    continue
        return json.loads(text)
    except Exception as e:
        print(f"[Gemini obligations error] {e}")
        return {
            "summary": f"Analysis failed: {e}",
            "obligations": [],
            "skipped_prior": [],
            "notes_for_kenyon": str(e),
        }


# ── Debrief follow-up analysis ─────────────────────────────────────────────────
def gemini_debrief_followup(deploy_id: str, person: str, results: dict):
    """
    Called in background after debrief submission.
    Gemini reads failures → determines fix owner → stores escalation.
    """
    failures = {
        oid: r for oid, r in results.items()
        if r.get("result") in ("fail", "blocked")
    }
    if not failures:
        print(f"[debrief] {person}/{deploy_id} — all pass ✓")
        return

    try:
        doc = _firestore().collection("qa_obligations").document(deploy_id).get()
        if not doc.exists:
            return
        data = doc.to_dict()
        ob_map = {ob["id"]: ob for ob in data.get("obligations", [])}

        failed_items = [
            {
                "obligation": ob_map.get(oid, {}),
                "result":     r["result"],
                "notes":      r.get("notes", ""),
            }
            for oid, r in failures.items()
        ]

        vertexai.init(project=PROJECT, location=LOCATION)
        model = GenerativeModel("gemini-2.5-flash")

        prompt = f"""QA debrief received — deploy {deploy_id}, submitted by {person}.

Failures:
{json.dumps(failed_items, indent=2)}

Deploy context:
{json.dumps(data.get('deploy_info', {}), indent=2)}

For each failure, determine:
1. Most likely root cause (code bug / config issue / environment / user error)
2. Fix owner: kenyon (code/infra) | charles (Twilio config) | cynthia (retest needed / user error)
3. Specific next action (concrete command or step)
4. Urgency: critical (system broken for real callers) | high (feature broken) | low (cosmetic)

Output JSON only:
{{"failures": [{{"id": "ob_...", "root_cause": "...", "fix_owner": "kenyon|charles|cynthia", "next_action": "...", "urgency": "critical|high|low"}}]}}"""

        resp = model.generate_content(
            prompt,
            generation_config=GenerationConfig(max_output_tokens=1000, temperature=0.2),
        )
        text = resp.text.strip()
        if "```" in text:
            parts = text.split("```")
            for part in parts:
                if part.strip().startswith("{") or part.strip().startswith("json"):
                    text = part.strip().lstrip("json").strip()
                    break

        analysis = json.loads(text)

        _firestore().collection("qa_obligations").document(deploy_id).update({
            f"followup_{person}":    analysis,
            f"followup_{person}_at": datetime.now(timezone.utc).isoformat(),
        })

        # Log escalations
        for f in analysis.get("failures", []):
            urgency = f.get("urgency", "?").upper()
            owner   = f.get("fix_owner", "kenyon")
            action  = f.get("next_action", "")
            print(f"[ESCALATE] [{urgency}] → {owner}: {action}")

        # TODO: send follow-up email to fix_owner (requires SMTP)

    except Exception as e:
        print(f"[debrief follow-up error] {e}")


# ── Email sender ───────────────────────────────────────────────────────────────
def send_qa_email(person: str, deploy_id: str, obligations: list, summary: str, revision: str):
    """Send HTML checklist email to a team member."""
    person_obs = [o for o in obligations if o.get("person") == person]
    if not person_obs:
        return

    info     = TEAM.get(person, {})
    to_email = info.get("email", "")
    if not to_email or not SMTP_USER or not SMTP_PASS:
        print(f"[email] Skipping {person} — email not configured")
        return

    form_url = f"{SERVICE_URL}/qa/form/{deploy_id}?person={person}"

    # Build obligation HTML blocks
    items_html = ""
    for ob in person_obs:
        priority_color = {"critical": "#d32f2f", "high": "#f57c00", "low": "#388e3c"}.get(
            ob.get("priority", "low"), "#666"
        )
        steps_html = "".join(f"<li>{s}</li>" for s in ob.get("test_steps", []))
        carried_tag = (
            '<span style="color:#999;font-size:11px"> ↩ carried forward</span>'
            if not ob.get("is_new") else ""
        )
        items_html += f"""
        <div style="border:1px solid #e0e0e0;border-radius:8px;padding:16px;margin:12px 0;background:#fafafa">
          <div style="margin-bottom:8px">
            <span style="background:#e8f4fd;color:#1565c0;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;margin-right:8px">{ob.get('area','').upper()}</span>
            <span style="color:{priority_color};font-size:11px;font-weight:600;margin-right:8px">{ob.get('priority','').upper()}</span>
            <strong>{ob.get('description','')}</strong>{carried_tag}
          </div>
          <ol style="padding-left:20px;margin:8px 0;font-size:14px;line-height:1.6">{steps_html}</ol>
          <div style="color:#4caf50;font-size:13px;margin-top:8px">✓ Expected: {ob.get('expected_result','')}</div>
        </div>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[Arc Badlands QA] {revision} — {len(person_obs)} item(s) for {info.get('name', person)}"
    msg["From"]    = SMTP_USER
    msg["To"]      = to_email

    html_body = f"""
    <html><head><meta charset="UTF-8"></head>
    <body style="font-family:system-ui,sans-serif;max-width:640px;margin:0 auto;padding:24px;color:#1a1a2e">
      <h2 style="margin-bottom:4px">Arc Badlands QA — {revision}</h2>
      <p style="color:#666;font-size:13px;margin-bottom:16px">Deploy {deploy_id[:8]} · {datetime.now().strftime('%Y-%m-%d %H:%M')} CT</p>
      
      <div style="background:#1a1a2e;color:#fff;padding:12px 16px;border-radius:8px;margin-bottom:20px;font-size:14px">
        {summary}
      </div>

      <p>Hi {info.get('name','')}, you have <strong>{len(person_obs)}</strong> item(s) to verify for this deploy.</p>
      <p style="color:#666;font-size:13px">Click the button below to open your interactive checklist — you can mark pass/fail, add notes, and attach screenshots.</p>
      
      {items_html}

      <div style="text-align:center;margin-top:24px">
        <a href="{form_url}" style="background:#1a1a2e;color:#fff;padding:14px 28px;text-decoration:none;border-radius:8px;display:inline-block;font-size:15px;font-weight:600">
          Open Checklist Form →
        </a>
      </div>
      
      <p style="color:#999;font-size:12px;margin-top:24px;border-top:1px solid #eee;padding-top:12px">
        Only retest items marked <em>is_new: true</em> or explicitly flagged. 
        Carried items just need a quick confirm. Failures trigger a Gemini escalation to Kenyon.
      </p>
    </body></html>"""

    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, to_email, msg.as_string())
        print(f"[email] ✓ Sent to {person} ({to_email})")
    except Exception as e:
        print(f"[email error → {person}] {e}")


# ── HTML checklist form ────────────────────────────────────────────────────────
@router.get("/qa/form/{deploy_id}", response_class=HTMLResponse)
async def qa_form(deploy_id: str, person: str = ""):
    try:
        doc = _firestore().collection("qa_obligations").document(deploy_id).get()
        if not doc.exists:
            return HTMLResponse("<h2>Deploy not found</h2>", status_code=404)
        data = doc.to_dict()
    except Exception as e:
        return HTMLResponse(f"<h2>Firestore error: {e}</h2>", status_code=500)

    all_obs = data.get("obligations", [])
    obs     = [o for o in all_obs if not person or o.get("person") == person]
    revision = data.get("revision", deploy_id[:8])
    summary  = data.get("summary", "")

    items_html = ""
    for ob in obs:
        pcolor = {"critical": "#d32f2f", "high": "#f57c00", "low": "#388e3c"}.get(
            ob.get("priority", "low"), "#666"
        )
        steps_li = "".join(f"<li>{s}</li>" for s in ob.get("test_steps", []))
        carried  = '<span class="carried">↩ carried</span>' if not ob.get("is_new") else ""
        status   = ob.get("status", "pending")
        checked_pass    = 'checked' if status == "pass"    else ""
        checked_fail    = 'checked' if status == "fail"    else ""
        checked_blocked = 'checked' if status == "blocked" else ""

        items_html += f"""
        <div class="item" id="item-{ob['id']}">
          <div class="item-header">
            <span class="tag area">{ob.get('area','').upper()}</span>
            <span class="tag priority" style="color:{pcolor}">{ob.get('priority','').upper()}</span>
            <strong>{ob.get('description','')}</strong>{carried}
          </div>
          <ol class="steps">{steps_li}</ol>
          <div class="expected">✓ {ob.get('expected_result','')}</div>
          <div class="result-row">
            <label class="result-opt pass-opt">
              <input type="radio" name="result_{ob['id']}" value="pass" {checked_pass} required> ✓ Pass
            </label>
            <label class="result-opt fail-opt">
              <input type="radio" name="result_{ob['id']}" value="fail" {checked_fail}> ✗ Fail
            </label>
            <label class="result-opt block-opt">
              <input type="radio" name="result_{ob['id']}" value="blocked" {checked_blocked}> ⊘ Blocked
            </label>
          </div>
          <textarea name="notes_{ob['id']}" placeholder="Notes (required if Fail or Blocked)..." rows="2">{ob.get('debrief_notes','')}</textarea>
          <label class="screenshot-label">
            Screenshots <span style="color:#999">(optional — attach anything that helps)</span>
            <input type="file" name="screenshots_{ob['id']}" accept="image/*,.png,.jpg,.jpeg,.gif,.webp" multiple>
          </label>
        </div>"""

    ob_ids_csv = ",".join(o["id"] for o in obs)

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>QA Debrief — {revision}</title>
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0 }}
body {{ font-family: system-ui, -apple-system, sans-serif; background: #f0f0f4; color: #1a1a2e; min-height: 100vh }}
.container {{ max-width: 680px; margin: 0 auto; padding: 24px 16px 64px }}
h1 {{ font-size: 20px; font-weight: 700; margin-bottom: 4px }}
.meta {{ color: #888; font-size: 13px; margin-bottom: 16px }}
.summary-box {{ background: #1a1a2e; color: #fff; padding: 12px 16px; border-radius: 8px; margin-bottom: 20px; font-size: 14px; line-height: 1.5 }}
.item {{ background: #fff; border: 1px solid #e0e0e0; border-radius: 10px; padding: 18px; margin-bottom: 16px }}
.item-header {{ margin-bottom: 10px; line-height: 1.4 }}
.tag {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 10px; font-weight: 700; margin-right: 6px }}
.tag.area {{ background: #e3f2fd; color: #1565c0 }}
.tag.priority {{ background: transparent; font-size: 10px }}
.carried {{ color: #aaa; font-size: 11px; margin-left: 6px }}
.steps {{ padding-left: 18px; margin: 8px 0; font-size: 14px; line-height: 1.7; color: #333 }}
.expected {{ font-size: 13px; color: #2e7d32; margin: 8px 0; padding: 6px 10px; background: #f1f8e9; border-radius: 4px }}
.result-row {{ display: flex; gap: 12px; margin: 12px 0 8px; flex-wrap: wrap }}
.result-opt {{ display: flex; align-items: center; gap: 6px; padding: 6px 14px; border: 2px solid #e0e0e0; border-radius: 6px; cursor: pointer; font-size: 14px; font-weight: 600; transition: all .15s }}
.result-opt:has(input:checked).pass-opt {{ border-color: #4caf50; background: #e8f5e9; color: #2e7d32 }}
.result-opt:has(input:checked).fail-opt {{ border-color: #f44336; background: #ffebee; color: #c62828 }}
.result-opt:has(input:checked).block-opt {{ border-color: #ff9800; background: #fff3e0; color: #e65100 }}
.result-opt input {{ display: none }}
textarea {{ width: 100%; border: 1px solid #ddd; border-radius: 6px; padding: 8px 10px; font-size: 13px; resize: vertical; font-family: inherit; margin-top: 4px }}
textarea:focus {{ outline: none; border-color: #1a1a2e }}
.screenshot-label {{ display: block; margin-top: 10px; font-size: 13px; color: #666; cursor: pointer }}
.screenshot-label input {{ margin-top: 4px; display: block }}
.submit-btn {{ background: #1a1a2e; color: #fff; border: none; padding: 15px; border-radius: 8px; font-size: 15px; font-weight: 700; cursor: pointer; width: 100%; margin-top: 24px; letter-spacing: .02em }}
.submit-btn:hover {{ background: #2d2d4e }}
.submit-btn:disabled {{ background: #aaa }}
#success-msg {{ display: none; text-align: center; padding: 48px 24px; background: #fff; border-radius: 10px; margin-top: 20px }}
#success-msg h2 {{ color: #2e7d32; margin-bottom: 8px }}
#success-msg p {{ color: #666; font-size: 14px }}
</style>
</head><body>
<div class="container">
  <h1>QA Debrief</h1>
  <div class="meta">
    Revision: <strong>{revision}</strong> · Deploy ID: {deploy_id[:8]} · {data.get('ts','')[:10]}
    {f' · Logged in as: <strong>{person}</strong>' if person else ''}
  </div>
  <div class="summary-box">{summary}</div>

  <form id="qa-form">
    <input type="hidden" id="deploy-id-field" value="{deploy_id}">
    <input type="hidden" id="person-field" value="{person}">
    <input type="hidden" id="ob-ids-field" value="{ob_ids_csv}">
    {items_html}
    <button type="button" class="submit-btn" id="submit-btn" onclick="submitDebrief()">
      Submit Debrief →
    </button>
  </form>

  <div id="success-msg">
    <h2>✓ Debrief submitted</h2>
    <p>Gemini will review failures and escalate to the right person if needed.<br>
    You'll get a follow-up email if anything requires re-verification.</p>
  </div>
</div>

<script>
async function submitDebrief() {{
  const ids = document.getElementById('ob-ids-field').value.split(',').filter(Boolean);
  
  // Validate all items have a selection
  for (const id of ids) {{
    const sel = document.querySelector(`input[name="result_${{id}}"]:checked`);
    if (!sel) {{
      const item = document.getElementById(`item-${{id}}`);
      item.style.border = '2px solid #f44336';
      item.scrollIntoView({{behavior: 'smooth', block: 'center'}});
      return;
    }}
    // Require notes for fail/blocked
    const result = sel.value;
    if (result !== 'pass') {{
      const notes = document.querySelector(`textarea[name="notes_${{id}}"]`).value.trim();
      if (!notes) {{
        alert(`Please add notes for the failed/blocked item.`);
        document.querySelector(`textarea[name="notes_${{id}}"]`).focus();
        return;
      }}
    }}
  }}

  const btn = document.getElementById('submit-btn');
  btn.disabled = true;
  btn.textContent = 'Submitting...';

  // Build multipart form data (supports screenshots)
  const formData = new FormData();
  formData.append('deploy_id', document.getElementById('deploy-id-field').value);
  formData.append('person', document.getElementById('person-field').value);
  formData.append('obligation_ids', ids.join(','));

  for (const id of ids) {{
    const result = document.querySelector(`input[name="result_${{id}}"]:checked`)?.value || '';
    const notes  = document.querySelector(`textarea[name="notes_${{id}}"]`)?.value || '';
    formData.append(`result_${{id}}`, result);
    formData.append(`notes_${{id}}`, notes);
    
    const files = document.querySelector(`input[name="screenshots_${{id}}"]`)?.files;
    if (files) {{
      for (const file of files) {{
        formData.append(`screenshots_${{id}}`, file, file.name);
      }}
    }}
  }}

  try {{
    const resp = await fetch('/qa/debrief', {{ method: 'POST', body: formData }});
    if (resp.ok) {{
      document.getElementById('qa-form').style.display = 'none';
      document.getElementById('success-msg').style.display = 'block';
    }} else {{
      btn.disabled = false;
      btn.textContent = 'Submit Debrief →';
      alert('Submit failed — try again or contact Kenyon. Status: ' + resp.status);
    }}
  }} catch(e) {{
    btn.disabled = false;
    btn.textContent = 'Submit Debrief →';
    alert('Network error: ' + e.message);
  }}
}}
</script>
</body></html>""")


# ── Debrief receiver ───────────────────────────────────────────────────────────
@router.post("/qa/debrief")
async def qa_debrief(request: Request, background_tasks: BackgroundTasks):
    """Receive completed QA form, store results, trigger Gemini follow-up on failures."""
    import asyncio
    form = await request.form()
    deploy_id     = form.get("deploy_id", "")
    person        = form.get("person", "")
    ids_str       = form.get("obligation_ids", "")
    obligation_ids = [i.strip() for i in ids_str.split(",") if i.strip()]

    results = {}
    for oid in obligation_ids:
        results[oid] = {
            "result": form.get(f"result_{oid}", ""),
            "notes":  form.get(f"notes_{oid}", ""),
        }

    # Handle screenshots — store as GCS or Firestore base64 (simplified: log only)
    screenshots_logged = {}
    for oid in obligation_ids:
        files = form.getlist(f"screenshots_{oid}")
        if files:
            screenshots_logged[oid] = [str(getattr(f, 'filename', f)) for f in files]

    # Update Firestore
    try:
        ref = _firestore().collection("qa_obligations").document(deploy_id)
        doc = ref.get()
        if not doc.exists:
            return JSONResponse({"error": "deploy not found"}, status_code=404)

        data = doc.to_dict()
        obligations = data.get("obligations", [])
        for ob in obligations:
            if ob["id"] in results:
                ob["status"]        = results[ob["id"]]["result"]
                ob["debrief_notes"] = results[ob["id"]]["notes"]
                ob["debriefed_by"]  = person
                ob["debriefed_at"]  = datetime.now(timezone.utc).isoformat()
                if ob["id"] in screenshots_logged:
                    ob["screenshot_files"] = screenshots_logged[ob["id"]]

        ref.update({
            "obligations":              obligations,
            f"debrief_{person}_at":     datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        print(f"[debrief Firestore] {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

    # Background follow-up on failures
    background_tasks.add_task(gemini_debrief_followup, deploy_id, person, results)

    return JSONResponse({"status": "ok", "items_received": len(obligation_ids)})


# ── Manual deploy trigger ──────────────────────────────────────────────────────
@router.post("/qa/trigger")
async def qa_trigger(request: Request, background_tasks: BackgroundTasks):
    """
    Manual QA trigger — call this right after every `gcloud run deploy`.
    
    POST body (JSON):
    {
      "revision":        "commplex-api-00049-p5g",
      "commit_sha":      "3880a45",
      "commit_message":  "feat: Media Streams + GCP TTS voice handler",
      "changed_files":   ["CommPlexAPI/server/routes/voice_stream.py"],
      "build_log_excerpt": "✓ Building and deploying... Done.",
      "local_tree":      {}   // from file_intake.py --tree
    }
    
    One-liner to call after deploy:
      curl -s -X POST "https://commplex-api-...run.app/qa/trigger" \\
        -H "Content-Type: application/json" \\
        -d '{"revision":"REV","commit_sha":"SHA","commit_message":"MSG","changed_files":["FILES"]}'
    """
    body      = await request.json()
    deploy_id = str(uuid.uuid4()).replace("-", "")[:12]
    ts        = datetime.now(timezone.utc).isoformat()

    # Fetch GitHub commit info if SHA provided
    commit_info = {}
    sha = body.get("commit_sha", "")
    if sha and GH_TOKEN:
        commit_info = await get_commit_info(sha)

    deploy_info = {
        "deploy_id":      deploy_id,
        "revision":       body.get("revision", "unknown"),
        "commit_sha":     sha,
        "commit_message": body.get("commit_message") or commit_info.get("message", ""),
        "author":         commit_info.get("author", "Kenyon"),
        "changed_files":  body.get("changed_files") or commit_info.get("changed_files", []),
        "repo":           commit_info.get("repo", ""),
        "build_log":      body.get("build_log_excerpt", ""),
        "ts":             ts,
    }

    # Fetch prior open obligations from Firestore
    prior_open = []
    try:
        for doc in (
            _firestore().collection("qa_obligations")
                        .order_by("ts", direction=firestore.Query.DESCENDING)
                        .limit(8).stream()
        ):
            d = doc.to_dict()
            for ob in d.get("obligations", []):
                if ob.get("status") not in ("pass",):
                    prior_open.append({**ob, "from_deploy": d.get("revision", doc.id)})
    except Exception as e:
        print(f"[prior obligations fetch] {e}")

    local_tree = body.get("local_tree", {})

    background_tasks.add_task(
        _process_deploy, deploy_id, deploy_info, prior_open, local_tree
    )

    return JSONResponse({
        "deploy_id": deploy_id,
        "status":    "processing",
        "form_base": f"{SERVICE_URL}/qa/form/{deploy_id}",
        "note":      "Obligations generating in background — email dispatched when ready (~30s)"
    })


def _process_deploy(deploy_id: str, deploy_info: dict, prior_open: list, local_tree: dict):
    """Background: generate obligations → store → email team."""
    import asyncio
    result = generate_obligations(deploy_info, prior_open, local_tree)

    record = {
        "deploy_id":          deploy_id,
        "revision":           deploy_info.get("revision", ""),
        "ts":                 deploy_info.get("ts", ""),
        "deploy_info":        deploy_info,
        "summary":            result.get("summary", ""),
        "obligations":        result.get("obligations", []),
        "notes_for_kenyon":   result.get("notes_for_kenyon", ""),
    }

    try:
        _firestore().collection("qa_obligations").document(deploy_id).set(record)
        print(f"[QA] Stored {len(result.get('obligations',[]))} obligations for {deploy_id}")
    except Exception as e:
        print(f"[QA store error] {e}")

    obligations = result.get("obligations", [])
    summary     = result.get("summary", deploy_info.get("commit_message", "New deploy"))
    revision    = deploy_info.get("revision", deploy_id)

    for person in ("charles", "cynthia"):
        send_qa_email(person, deploy_id, obligations, summary, revision)

    # Log Kenyon's items
    kenyon_items = [o for o in obligations if o.get("person") == "kenyon"]
    if kenyon_items:
        print(f"[QA] Kenyon has {len(kenyon_items)} item(s):")
        for o in kenyon_items:
            print(f"  [{o.get('priority','?').upper()}] {o.get('description','')}")

    notes = result.get("notes_for_kenyon", "")
    if notes:
        print(f"[QA → Kenyon] {notes}")


# ── Cloud Build Pub/Sub webhook ────────────────────────────────────────────────
@router.post("/qa/deploy-hook")
async def qa_deploy_hook(request: Request, background_tasks: BackgroundTasks):
    """
    Cloud Build Pub/Sub push endpoint — fires automatically on every successful deploy.
    
    One-time setup (run once from Penguin):
      gcloud pubsub subscriptions create qa-deploy-hook \\
        --topic=cloud-builds \\
        --push-endpoint=https://commplex-api-349126848698.us-central1.run.app/qa/deploy-hook \\
        --ack-deadline=60 \\
        --project=commplex-493805
    """
    try:
        body    = await request.json()
        message = body.get("message", {})
        data_b64 = message.get("data", "")
        if not data_b64:
            return JSONResponse({"status": "no data"})

        build_data = json.loads(base64.b64decode(data_b64).decode())
        status     = build_data.get("status", "")

        # Only process successful builds
        if status != "SUCCESS":
            return JSONResponse({"status": f"skipped — build status: {status}"})

        subs    = build_data.get("substitutions", {})
        log_url = build_data.get("logUrl", "")

        # Try to extract revision from build steps
        revision = subs.get("_REVISION", "unknown")
        for step in build_data.get("steps", []):
            args_str = " ".join(step.get("args", []))
            if "commplex-api-0" in args_str:
                for part in args_str.split():
                    if part.startswith("commplex-api-"):
                        revision = part
                        break

        deploy_info = {
            "deploy_id":      build_data.get("id", str(uuid.uuid4()))[:12],
            "revision":       revision,
            "commit_sha":     subs.get("COMMIT_SHA", "")[:8],
            "commit_message": subs.get("_COMMIT_MSG", subs.get("COMMIT_SHA", "Cloud Build")),
            "changed_files":  [],  # populated via GitHub in background
            "build_log":      log_url,
            "build_id":       build_data.get("id", ""),
            "ts":             datetime.now(timezone.utc).isoformat(),
        }

        deploy_id  = build_data.get("id", str(uuid.uuid4()).replace("-", ""))[:12]
        prior_open = []  # fetched in background
        background_tasks.add_task(_process_deploy_with_gh_fetch, deploy_id, deploy_info)

        return JSONResponse({"status": "accepted", "deploy_id": deploy_id})

    except Exception as e:
        print(f"[deploy-hook error] {e}")
        return JSONResponse({"error": str(e)}, status_code=200)  # 200 to ack Pub/Sub


def _process_deploy_with_gh_fetch(deploy_id: str, deploy_info: dict):
    """Background task for Pub/Sub hook — fetches GitHub diff then generates obligations."""
    import asyncio
    loop = asyncio.new_event_loop()

    sha = deploy_info.get("commit_sha", "")
    if sha and GH_TOKEN:
        try:
            commit_info = loop.run_until_complete(get_commit_info(sha))
            if commit_info:
                deploy_info["changed_files"]  = commit_info.get("changed_files", [])
                deploy_info["commit_message"] = commit_info.get("message", deploy_info["commit_message"])
                deploy_info["author"]         = commit_info.get("author", "")
        except Exception as e:
            print(f"[GitHub fetch in background] {e}")
        finally:
            loop.close()

    prior_open = []
    try:
        for doc in (
            _firestore().collection("qa_obligations")
                        .order_by("ts", direction=firestore.Query.DESCENDING)
                        .limit(8).stream()
        ):
            d = doc.to_dict()
            for ob in d.get("obligations", []):
                if ob.get("status") not in ("pass",):
                    prior_open.append({**ob, "from_deploy": d.get("revision", doc.id)})
    except Exception as e:
        print(f"[prior fetch background] {e}")

    _process_deploy(deploy_id, deploy_info, prior_open, {})


# ── Local file tree receiver ───────────────────────────────────────────────────
@router.post("/qa/intake-tree")
async def qa_intake_tree(request: Request):
    """
    Receives the local Downloads/Documents tree from file_intake.py.
    Stores in Firestore for use in next deploy's Gemini analysis.
    """
    try:
        body = await request.json()
        tree = body.get("local_tree", body)
        _firestore().collection("system_state").document("local_tree").set({
            "tree":    tree,
            "updated": datetime.now(timezone.utc).isoformat(),
        })
        return JSONResponse({"status": "ok"})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ── Open obligations dashboard ─────────────────────────────────────────────────
@router.get("/qa/obligations")
async def qa_obligations_summary():
    """Return current open obligations — for Kenyon's dashboard or CLI check."""
    try:
        open_items: dict = {"charles": [], "cynthia": [], "kenyon": []}
        recent_deploys = []

        for doc in (
            _firestore().collection("qa_obligations")
                        .order_by("ts", direction=firestore.Query.DESCENDING)
                        .limit(10).stream()
        ):
            d   = doc.to_dict()
            rev = d.get("revision", doc.id[:8])
            recent_deploys.append({"revision": rev, "ts": d.get("ts", "")[:10], "summary": d.get("summary", "")})

            for ob in d.get("obligations", []):
                if ob.get("status") not in ("pass",):
                    person = ob.get("person", "kenyon")
                    if person in open_items:
                        open_items[person].append({
                            "deploy":      rev,
                            "area":        ob.get("area"),
                            "priority":    ob.get("priority"),
                            "description": ob.get("description"),
                            "status":      ob.get("status", "pending"),
                            "is_new":      ob.get("is_new", True),
                        })

        return JSONResponse({
            "open":            open_items,
            "total_open":      sum(len(v) for v in open_items.values()),
            "recent_deploys":  recent_deploys[:5],
            "ts":              datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
