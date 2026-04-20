# Arc Badlands CommPlex — v5

> **Production Date:** April 20, 2026 | **Lead Architect:** Kenyon Jones
> **GCP Project:** `commplex-493805` | **Twilio:** `+1-866-736-2349`

[![CI](https://github.com/shy2shy/arc-badlands-commplex/actions/workflows/python-tests.yml/badge.svg)](https://github.com/shy2shy/arc-badlands-commplex/actions)
[![Tests](https://img.shields.io/badge/tests-103%20passing-brightgreen)](https://github.com/shy2shy/arc-badlands-commplex/actions)
[![GCP](https://img.shields.io/badge/infra-Cloud%20Run-4285F4)](https://console.cloud.google.com/run?project=commplex-493805)
[![Python](https://img.shields.io/badge/python-3.11-blue)](https://www.python.org/)

---

## 🔗 Live Operations

| Surface | Link |
|---|---|
| API Health | [Cloud Run Console](https://console.cloud.google.com/run?project=commplex-493805) |
| GCP Logs | [Log Explorer](https://console.cloud.google.com/logs?project=commplex-493805) |
| Alert Hub | [ntfy.sh/px10pro-commplex-z7x2-alert-hub](https://ntfy.sh/px10pro-commplex-z7x2-alert-hub) |
| GitHub Issues | [Backlog](https://github.com/shy2shy/arc-badlands-commplex/issues) |

---

## 🏛️ The Four Laws (Architecture Metaphor)

CommPlex is organized into four strictly isolated domains. **Never cross-import between them** except through the defined interfaces in Spec.

```
┌──────────────────────────────────────────────────────────────────┐
│                     arc-badlands-commplex                        │
│                                                                  │
│  CommPlexSpec/   ← THE LAW   (Interfaces, base classes, types)   │
│       │                                                          │
│       ├──► CommPlexCore/  ← THE BRAIN  (AI, Campaigns, Sluice)  │
│       │                                                          │
│       ├──► CommPlexAPI/   ← THE MOUTH  (FastAPI, Twilio hooks)   │
│       │                                                          │
│       └──► CommPlexEdge/  ← THE HANDS (ntfy push, PWA dashboard) │
│                                                                  │
│  tests/          ← 103 tests, all green                         │
│  .devcontainer/  ← Codespaces-ready dev environment             │
│  .github/        ← CI/CD via GitHub Actions                     │
└──────────────────────────────────────────────────────────────────┘
```

### Domain Details

| Domain | Path | Owner | Purpose |
|---|---|---|---|
| **Spec** | `CommPlexSpec/` | Kenyon | Campaign interfaces, base classes, shared types |
| **Core** | `CommPlexCore/` | Charles | AI classification, vehicle data (MKZ/TownCar/F350/Jayco), Sluice filter |
| **API** | `CommPlexAPI/` | Charles | FastAPI gateway, Twilio webhooks, DB models, docker-compose |
| **Edge** | `CommPlexEdge/` | Cynthia | ntfy push notifications, PWA dashboard, modules |

---

## 📊 System Status

| Item | Status |
|---|---|
| GCP Project | ✅ Active (`commplex-493805`) |
| Cloud Run | ✅ Live |
| Test Suite | ✅ 103/103 GREEN |
| AI Engine | ✅ ACTIVE (`DRY_RUN=false`) |
| Twilio | ✅ `+1-866-736-2349` |
| Codespaces | ✅ `.devcontainer` ready |

---

## ⚡ Quick Start (GitHub Codespaces — Recommended)

Codespaces is the **primary development environment** for this team. All tooling is pre-configured.

### 1. Launch Your Codespace

1. Go to [github.com/shy2shy/arc-badlands-commplex](https://github.com/shy2shy/arc-badlands-commplex)
2. Click **`<> Code`** → **`Codespaces`** tab → **`Create codespace on master`**
3. Wait ~3 minutes for the container to build and `setup.sh` to complete
4. You now have: Python 3.11, `gcloud` CLI, `gh` CLI, all Python deps installed

### 2. Authenticate Your Tools

```bash
# Authenticate Google Cloud (opens browser)
gcloud auth login
gcloud auth application-default login
gcloud config set project commplex-493805

# Authenticate GitHub CLI
gh auth login
```

### 3. Hydrate Your Secrets

```bash
# Pull all secrets from GCP Secret Manager into local .env
bash gcp_secrets_sync.sh
```

> **Note:** You must be granted the `roles/secretmanager.secretAccessor` role in GCP first.
> Ask **Kenyon** to run `bash invite_team.sh` with your GCP email.

### 4. Verify Everything Works

```bash
make install    # Install/verify venv and all dependencies
make test       # Run the full 103-test suite — should be ALL GREEN
make run        # Start the local API server at http://localhost:8000
```

### 5. Make a Test Call (Twilio)

```bash
# Verify Twilio credentials are in .env
grep TWILIO .env

# Trigger a test outreach (DRY_RUN mode)
DRY_RUN=true python -m CommPlexCore.scripts.run_wave --campaign test
```

---

## 🐧 Local Linux Setup (Alternative to Codespaces)

If you prefer running locally on Ubuntu/Debian:

```bash
# 1. Clone the repo
git clone https://github.com/shy2shy/arc-badlands-commplex.git
cd arc-badlands-commplex

# 2. Install system dependencies
sudo apt-get update && sudo apt-get install -y python3.11 python3.11-venv python3-pip curl git

# 3. Install Google Cloud SDK
curl https://sdk.cloud.google.com | bash
exec -l $SHELL
gcloud init

# 4. Install GitHub CLI
(type -p wget >/dev/null || (sudo apt update && sudo apt-get install wget -y)) \
  && sudo mkdir -p -m 755 /etc/apt/keyrings \
  && wget -qO- https://cli.github.com/packages/githubcli-archive-keyring.gpg \
     | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null \
  && sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
  && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
     | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
  && sudo apt update && sudo apt install gh -y

# 5. Install project
make install

# 6. Hydrate secrets
bash gcp_secrets_sync.sh

# 7. Verify
make test
```

---

## 🔐 Secrets & OAuth Setup

### Required Secrets in GCP Secret Manager

All secrets live in `commplex-493805` Secret Manager. **Never commit secrets to the repo.**

| Secret Name | Description | Owner |
|---|---|---|
| `TWILIO_ACCOUNT_SID` | Twilio account SID | Kenyon |
| `TWILIO_AUTH_TOKEN` | Twilio auth token | Kenyon |
| `TWILIO_FROM_NUMBER` | `+18667362349` | Kenyon |
| `DATABASE_URL` | Cloud SQL connection string | Kenyon |
| `OPENAI_API_KEY` | AI classification model key | Kenyon |
| `NTFY_TOPIC` | Alert hub topic string | Cynthia |
| `OAUTH_CLIENT_SECRET` | Google OAuth desktop client JSON | Kenyon |

### OAuth Desktop Client (Action Required)

The OAuth desktop client from the previous repo **must be regenerated**:

1. Go to [GCP Credentials Console](https://console.cloud.google.com/apis/credentials?project=commplex-493805)
2. Click **`+ Create Credentials`** → **`OAuth client ID`**
3. Application type: **Desktop app**
4. Name: `CommPlex Dev Client`
5. Download JSON → rename to `oauth_desktop_client_secret.json`
6. Upload to Secret Manager:
   ```bash
   gcloud secrets create OAUTH_CLIENT_SECRET \
     --data-file=oauth_desktop_client_secret.json \
     --project=commplex-493805
   ```
7. **Delete the local file.** It is already in `.gitignore`.

---

## 🛠️ Make Commands Reference

```bash
make install      # Create venv, install all requirements
make test         # Run full pytest suite (103 tests)
make run          # Start FastAPI server (localhost:8000)
make lint         # Run ruff/flake8 linter
make format       # Run black formatter
make docker-up    # Start docker-compose stack (API + DB)
make docker-down  # Stop docker-compose stack
make deploy       # Deploy to Cloud Run (requires gcloud auth)
make logs         # Tail live Cloud Run logs
make secrets      # Alias for gcp_secrets_sync.sh
```

---

## 🌊 Calling Operations: Waves & Serial

CommPlex supports two outreach modes:

### Wave Mode (Broadcast)
Sends outbound messages to a full campaign list concurrently.

```bash
# Run a wave campaign (production)
python -m CommPlexCore.scripts.run_wave --campaign <campaign_name>

# Dry run (no actual calls/SMS)
DRY_RUN=true python -m CommPlexCore.scripts.run_wave --campaign <campaign_name>
```

### Serial Mode (Sequential)
Processes contacts one at a time with AI classification between each.

```bash
python -m CommPlexCore.scripts.run_serial --campaign <campaign_name> --limit 10
```

### Campaign Data Location
Campaign definitions live in `CommPlexCore/campaigns/` and `CommPlexSpec/campaigns/`.

---

## 🌿 Branching & Workflow

```
master          ← Production. Protected. Requires PR + review.
  └── dev       ← Integration branch. All feature branches merge here first.
        ├── feat/KJ-<issue>-<slug>    ← Kenyon's features
        ├── feat/CC-<issue>-<slug>    ← Cynthia's features
        ├── feat/CH-<issue>-<slug>    ← Charles's features
        └── feat/JM-<issue>-<slug>    ← Justin's features (later)
```

**Branch naming:** `feat/KJ-42-twilio-serial-mode`
**Commit format:** `type(scope): description` → `fix(api): correct webhook signature validation`

### PR Rules
- All PRs target `dev`, not `master`
- Must pass all 103 tests in CI
- At least 1 review required before merge
- `master` ← `dev` merges are architect-only (Kenyon)

---

## 👥 Team

| Name | GitHub | Role | Domain |
|---|---|---|---|
| Kenyon Jones | `KenyukiShy` | Lead Architect | Spec, GCP, CI/CD, AI |
| Cynthia | TBD | Operations Lead | Edge, Dashboard, ntfy |
| Charles | TBD | Backend Engineer | Core, API, DB |
| Justin | TBD | Frontend Engineer | Edge/PWA (Phase 1) |

---

## 📁 Full File Tree

```
arc-badlands-commplex/
├── .devcontainer/
│   ├── devcontainer.json       # Codespaces config
│   └── setup.sh                # Container bootstrap script
├── .github/
│   └── workflows/
│       └── python-tests.yml    # CI: runs pytest on every push
├── CommPlexSpec/               # THE LAW: interfaces & types
│   ├── campaigns/
│   └── __init__.py
├── CommPlexCore/               # THE BRAIN: AI & campaign data
│   ├── campaigns/
│   ├── gcp/
│   ├── modules/
│   ├── scripts/
│   └── __init__.py
├── CommPlexAPI/                # THE MOUTH: FastAPI + Twilio
│   ├── modules/
│   ├── scripts/
│   ├── server/
│   ├── __init__.py
│   ├── docker-compose.yml
│   └── models.py
├── CommPlexEdge/               # THE HANDS: push + PWA
│   ├── modules/
│   ├── pwa/
│   ├── __init__.py
│   └── index.html
├── tests/
│   ├── __init__.py
│   └── test_commplex.py        # 103 tests
├── .env.example                # Copy to .env, then hydrate
├── .gitignore
├── COMMPLEX_INSTALL.sh         # One-shot install script
├── Makefile                    # Developer commands
├── Procfile                    # Process definitions
├── gcp_secrets_sync.sh         # Pulls secrets from GCP
├── invite_team.sh              # Adds team members to GCP IAM
├── patch.py                    # Data patching utility
├── patch_data.py               # Vehicle data patcher
├── pyproject.toml
└── requirements.txt
```

---

## 🆘 Troubleshooting

| Problem | Fix |
|---|---|
| `Permission denied` on `gcp_secrets_sync.sh` | `chmod +x gcp_secrets_sync.sh && bash gcp_secrets_sync.sh` |
| `Application Default Credentials not found` | `gcloud auth application-default login` |
| Tests fail with `missing env var` | Run `bash gcp_secrets_sync.sh` first |
| Twilio auth error | Check `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN` in `.env` |
| Port 8000 already in use | `lsof -ti:8000 \| xargs kill -9` |
| Codespace stuck building | Rebuild: `Ctrl+Shift+P` → `Codespaces: Rebuild Container` |

---

## 📜 License

Private — S2S Collective Intelligence. All rights reserved.
