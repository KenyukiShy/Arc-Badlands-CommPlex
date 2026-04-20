# Team Communications — CommPlex Launch
**From:** Kenyon Jones | **Date:** April 20, 2026

---

## 📧 MESSAGE 1 — TO: Cynthia & Charles (Send NOW)

**Subject:** CommPlex is LIVE — You're invited — Action required TODAY

---

Team,

We are live. CommPlex v5 is deployed on GCP, 103 tests green, Twilio number active at +1-866-736-2349. We're making calls today.

I need you set up in the next 2 hours. Here's what to do right now:

**1. Accept the GitHub invite**
Check your email for a collaborator invite from `KenyukiShy` to `shy2shy/arc-badlands-commplex`. Accept it immediately.

**2. Accept the Linear invite**
I'll send this separately. We're using Linear for sprint tracking — accept and log in.

**3. Reply to this message with your Google account email**
I need to grant you GCP access (Secret Manager). This is a blocker — nothing works without it.

**4. Once you have GCP access, follow the setup guide:**
`TEAM_SETUP.md` in the repo — Section "Step 1: GitHub Codespaces"

The whole setup is browser-based via GitHub Codespaces. No local install needed.
Target: `make test` shows `103 passed` on your machine.

**Your assignments for today:**

**Charles:**
- Get your Codespace running and tests passing
- Review `CommPlexCore/` and `CommPlexAPI/` — own those domains
- Run serial call mode in DRY_RUN and report back
- Spin up `make docker-up` and verify DB connects

**Cynthia:**
- Get your Codespace running and tests passing
- Install ntfy app, subscribe to: `px10pro-commplex-z7x2-alert-hub`
- Start the Vehicle Asset Tracker Google Sheet (5 vehicles: MKZ, TownCar, F350, Jayco, Ford Edge)
- Review `CommPlexEdge/` — that's your domain

I'll be on Twilio and GCP today watching the first wave go out. Once you're both set up we run together.

Move fast.

— Kenyon

---

## 📧 MESSAGE 2 — TO: Charles ONLY (Send after Message 1)

**Subject:** Your domain: CommPlexCore & CommPlexAPI — quick briefing

---

Charles,

Your two domains:

**CommPlexCore/** (The Brain)
- `campaigns/` — vehicle lead data. MKZ, TownCar, F350, Jayco.
- `gcp/` — GCP service integrations
- `modules/` — Sluice filter (AI call classification)
- `scripts/` — `run_wave.py` and `run_serial.py` — the calling engines

**CommPlexAPI/** (The Mouth)
- `server/` — FastAPI app, routes, Twilio webhook handler
- `models.py` — SQLAlchemy DB models
- `docker-compose.yml` — local Postgres stack
- `scripts/` — DB migrations and seed scripts

**Your first priorities (today):**
1. Get Codespace running, `make test` = 103 green
2. `make docker-up` → verify Postgres connects
3. Dry-run serial: `DRY_RUN=true python -m CommPlexCore.scripts.run_serial --campaign test --limit 1`
4. Review the Twilio webhook route in `CommPlexAPI/server/` — make sure you understand how inbound responses flow back through the Sluice

Branch naming for you: `feat/CH-ISSUE-description`

The Linear board has your stories assigned. Check them after you accept the invite.

Questions → ping me directly.

— K

---

## 📧 MESSAGE 3 — TO: Cynthia ONLY (Send after Message 1)

**Subject:** Your domain: CommPlexEdge — dashboard, ntfy, campaigns

---

Cynthia,

Your domain is **CommPlexEdge/** (The Hands):

- `modules/` — ntfy push notification senders. These fire on every call event.
- `pwa/` — the user dashboard. Justin will build this out in Phase 1 but you own the specs.
- `index.html` — current PWA shell

**Your first priorities (today):**
1. Get Codespace running — `make test` = 103 green
2. Install ntfy app (iOS App Store or Android Play Store)
3. Subscribe to our alert channel: `px10pro-commplex-z7x2-alert-hub`
4. Send a test alert to confirm it works:
   ```
   curl -d "Cynthia online ✅" https://ntfy.sh/px10pro-commplex-z7x2-alert-hub
   ```
5. **Start the Vehicle Asset Tracker** (this is critical for revenue):
   - Create a Google Sheet in our Shared Drive
   - Columns: Vehicle | Year | VIN | Title Status | KBB Low | KBB High | Asking Price | Platform | Lead Count | Status | Notes
   - One row per vehicle: MKZ, TownCar, F350 Truck, Jayco Camper, Ford Edge
   - The Ford Edge needs to be listed in the Georgia market TODAY (Facebook Marketplace Atlanta + CarGurus)
   - Duplicate title applications are pending for MKZ, Truck, and Camper — note that in the sheet

The vehicle sales are our runway capital. This is as urgent as the tech work.

Branch naming for you: `feat/CC-ISSUE-description`

Check Linear for your assigned stories. Everything is scoped there.

— K

---

## 📧 MESSAGE 4 — TO: Justin (Send when he joins — Phase 1)

**Subject:** CommPlex — Welcome to the team — Your domain: CommPlexEdge/pwa

---

Justin,

Welcome. You're joining a live, running system. Here's the quick orientation:

**The system:** CommPlex is an AI-driven outbound calling and campaign management platform. It runs on Google Cloud Platform (Cloud Run), uses Twilio for calls/SMS, and has a FastAPI backend. Your piece is the frontend.

**Your domain:** `CommPlexEdge/pwa/`
- The current UI is in `CommPlexEdge/index.html` — basic PWA shell
- API is at `localhost:8000` when running locally (docs at `localhost:8000/docs`)
- The dashboard needs to show: live call status, campaign progress, ntfy alerts, vehicle tracker

**Setup:**
Follow `TEAM_SETUP.md` in the repo. Codespaces is your dev environment.

Branch naming: `feat/JM-ISSUE-description`

Check Linear for your assigned stories. Cynthia will brief you on the Edge domain since she owns it operationally.

Questions → ping me or Charles for backend stuff, Cynthia for operational context.

— K

---

## 💬 MESSAGE 5 — Slack/Text Group Message (Send to Charles + Cynthia NOW)

```
Team — we're moving today. CommPlex v5 is live on GCP.
Check your email: GitHub invite from KenyukiShy + Linear invite incoming.
Reply with your Google account email so I can add you to GCP.
Full setup in TEAM_SETUP.md — Codespaces, no local install needed.
Target: make test = 103 passed on your end within 2 hours.
First wave goes out today. Let's go. — K
```

---

## 🔧 KENYON'S PERSONAL CHECKLIST (Do these before team is online)

- [ ] Regenerate OAuth desktop client in GCP (see README)
- [ ] Verify all 7 secrets exist in Secret Manager
- [ ] Run `bash invite_team.sh` once Charles and Cynthia send their emails
- [ ] Set up branch protection on `master` and `dev`
- [ ] Create Linear workspace, import `LINEAR_IMPORT.csv`
- [ ] Invite Charles and Cynthia to Linear
- [ ] Run first wave in DRY_RUN mode to confirm no errors
- [ ] Run first LIVE wave — monitor ntfy hub
- [ ] Confirm Ford Edge listed in Georgia market
- [ ] File duplicate title for MKZ, Truck, Camper if not done

**GCP commands to verify secrets:**
```bash
gcloud secrets list --project=commplex-493805

# Expected output includes:
# TWILIO_ACCOUNT_SID
# TWILIO_AUTH_TOKEN
# TWILIO_FROM_NUMBER
# DATABASE_URL
# OPENAI_API_KEY
# NTFY_TOPIC
# OAUTH_CLIENT_SECRET
```
