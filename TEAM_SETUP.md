# CommPlex Team Setup Guide

> **For:** Kenyon, Cynthia, Charles, Justin
> **Environment:** GitHub Codespaces (primary) + Linux local (optional)
> **Updated:** April 20, 2026

---

## Step 0: Get Access (Everyone Does This First)

Before you can do anything, **Kenyon** must grant you access to:

1. **GitHub repo** — Kenyon invites you as a Collaborator at `Settings > Collaborators`
2. **GCP IAM** — Kenyon runs:
   ```bash
   # Replace EMAIL with your Google account email
   gcloud projects add-iam-policy-binding commplex-493805 \
     --member="user:YOUR_EMAIL@gmail.com" \
     --role="roles/secretmanager.secretAccessor"
   ```
3. **Linear workspace** — Kenyon invites you via Linear (use shy2shy domain or personal email)

Once Kenyon confirms, proceed below.

---

## Step 1: GitHub Codespaces (Recommended for All)

Codespaces gives you a fully configured Linux dev environment in your browser — no local setup needed.

### Launch

1. Navigate to [github.com/shy2shy/arc-badlands-commplex](https://github.com/shy2shy/arc-badlands-commplex)
2. Click the green **`<> Code`** button
3. Click the **`Codespaces`** tab
4. Click **`Create codespace on master`**
5. Wait ~3 minutes. The `setup.sh` script installs everything automatically.

### First-Time Auth Inside Codespace

Open the terminal in your Codespace and run these **once**:

```bash
# 1. Authenticate with Google Cloud
gcloud auth login
# → Opens browser link. Sign in with your Google account.

gcloud auth application-default login
# → Do this too. It's required for GCP SDK calls.

gcloud config set project commplex-493805

# 2. Authenticate GitHub CLI
gh auth login
# → Choose "GitHub.com" → "HTTPS" → "Login with a web browser"

# 3. Pull secrets from GCP into your local .env
bash gcp_secrets_sync.sh

# 4. Verify everything
make test
# Expected output: 103 passed ✅
```

### Daily Workflow in Codespaces

```bash
# Start your session
make run          # Starts API at localhost:8000

# Run tests before any commit
make test

# Check logs
make logs
```

---

## Step 2: Configure Git Identity

Inside your Codespace terminal:

```bash
git config --global user.name "Your Name"
git config --global user.email "your@email.com"
```

---

## Step 3: Create Your First Branch

Never work directly on `master`. Always branch from `dev`:

```bash
git fetch origin
git checkout dev
git pull origin dev
git checkout -b feat/YOUR_INITIALS-ISSUE_NUMBER-short-description
# Example: feat/CC-12-ntfy-push-module
```

---

## Step 4: Linear — Task Tracking

We use Linear for sprint tracking. Task hierarchy:

```
Project  (= GitHub Milestone / Epic group)
  └── Epic  (= major feature track, ~2 week scope)
        └── Story  (= user-facing feature, ~1-3 days)
              └── Task  (= implementation unit, ~hours)
                    └── Subtask  (= granular checklist item)
```

### Access Linear

- URL: [linear.app](https://linear.app) — use the team workspace (Kenyon will invite you)
- All issues sync with GitHub labels (see the label system in the repo)

### Label Convention

When creating GitHub issues, use these label combinations:

```
scope:platform + unit:ops + role:devops + cert:pro + P1:Critical + status:todo
```

---

## Step 5: Verify Twilio / Calling

```bash
# Check Twilio env vars loaded
grep TWILIO .env

# Test outreach (DRY RUN — no real calls)
DRY_RUN=true python -m CommPlexCore.scripts.run_wave --campaign test

# Live serial call (REAL — be sure!)
python -m CommPlexCore.scripts.run_serial --campaign mkz_leads --limit 1
```

---

## Per-Role Setup Notes

### Kenyon (Lead Architect)
- You own GCP access provisioning — run `bash invite_team.sh` for each new member
- You own Secret Manager — add secrets via GCP Console or `gcloud secrets create`
- Regenerate OAuth desktop client before sharing with team (see README)
- You own `master` → only you merge `dev` into `master`

### Charles (Backend Engineer)
- Primary domain: `CommPlexCore/` and `CommPlexAPI/`
- For DB work: `docker-compose.yml` is in `CommPlexAPI/` — run `make docker-up`
- Cloud SQL proxy: `cloud-sql-proxy commplex-493805:us-central1:commplex-db`
- Run `make test` before every PR

### Cynthia (Operations Lead)
- Primary domain: `CommPlexEdge/` — ntfy modules and PWA dashboard
- Monitor alerts at: [ntfy.sh/px10pro-commplex-z7x2-alert-hub](https://ntfy.sh/px10pro-commplex-z7x2-alert-hub)
- Campaign management: coordinate with Kenyon on wave scheduling
- Manage `CommPlexSpec/campaigns/` data with Charles

### Justin (Frontend Engineer — Phase 1)
- Primary domain: `CommPlexEdge/pwa/`
- Stack: HTML/JS/CSS — see `CommPlexEdge/index.html` for current PWA shell
- API base URL for local dev: `http://localhost:8000`
- API docs auto-generated at: `http://localhost:8000/docs`

---

## Troubleshooting Quick Reference

```bash
# Can't access GCP secrets?
gcloud auth application-default login

# Tests failing with import errors?
make install

# Port conflict?
lsof -ti:8000 | xargs kill -9

# Codespace won't build?
# In VS Code: Ctrl+Shift+P → "Codespaces: Rebuild Container"

# Wrong GCP project?
gcloud config set project commplex-493805

# .env is empty after sync?
cat gcp_secrets_sync.sh  # Verify script targets correct secret names
```
