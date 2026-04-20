#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# Arc Badlands CommPlex — Master Installer v5-Final
# April 2026 | Architect: Kenyon Jones | Packaged by Claude
#
# WHAT THIS DOES:
#   1. Creates the full 4-domain CommPlex folder structure
#   2. Writes all source files to correct locations
#   3. Sets up Python venv + installs deps
#   4. Syncs secrets from GCP if gcloud is authenticated
#   5. Sets up git remote to github.com/KenyukiShy/Arc-Badlands-CommPlex
#
# USAGE:
#   bash COMMPLEX_INSTALL.sh                    # full install
#   bash COMMPLEX_INSTALL.sh --dry-run          # preview
#   bash COMMPLEX_INSTALL.sh --skip-gcp         # skip GCP
#   bash COMMPLEX_INSTALL.sh --status           # check install state
#   bash COMMPLEX_INSTALL.sh --force            # overwrite existing
#
# VOICE BACKEND OPTIONS (set in .env):
#   VOICE_BACKEND=BLAND        # Bland.ai (thia@shy2shy.com, ~$2 balance)
#   VOICE_BACKEND=GCP_TWILIO   # Google TTS + Twilio (RECOMMENDED — cheaper)
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail
IFS=$'\n\t'

# ── Colours ────────────────────────────────────────────────────────────────────
CY='\033[96m'; GR='\033[92m'; YL='\033[93m'; RD='\033[91m'
BD='\033[1m';  DM='\033[2m';  RS='\033[0m'
ok()   { echo -e "${GR}✓${RS} $*"; }
warn() { echo -e "${YL}⚠${RS}  $*"; }
info() { echo -e "${CY}→${RS} $*"; }
hdr()  { echo -e "\n${BD}${CY}━━ $* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RS}"; }

banner() {
echo -e "${BD}${CY}"
cat << 'BANNER'
╔══════════════════════════════════════════════════════════════╗
║      Arc Badlands CommPlex — Master Installer v5-Final       ║
║      April 2026 | github.com/KenyukiShy                      ║
╚══════════════════════════════════════════════════════════════╝
BANNER
echo -e "${RS}"
}

# ── Parse args ────────────────────────────────────────────────────────────────
DRY_RUN=false; SKIP_GCP=false; FORCE=false; STATUS_ONLY=false
INSTALL_DIR="${HOME}/Arc-Badlands-CommPlex"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)   DRY_RUN=true ;;
    --skip-gcp)  SKIP_GCP=true ;;
    --force)     FORCE=true ;;
    --status)    STATUS_ONLY=true ;;
    --dir)       INSTALL_DIR="$2"; shift ;;
    --help|-h)
      echo "Usage: bash COMMPLEX_INSTALL.sh [--dry-run] [--skip-gcp] [--force] [--status] [--dir PATH]"
      exit 0 ;;
  esac
  shift
done

PYTHON=$(command -v python3 2>/dev/null || echo "python3")

# ── Environment detection ─────────────────────────────────────────────────────
detect_env() {
  ENV_TYPE="linux"
  [[ -n "${CODESPACES:-}" ]] && ENV_TYPE="codespaces"
  [[ -n "${GOOGLE_CLOUD_SHELL:-}" ]] && ENV_TYPE="cloudshell"
  [[ -d "/mnt/chromeos" ]] && ENV_TYPE="chromebook"
  ok "Environment: ${BD}${ENV_TYPE}${RS} | user=$(whoami)"
}

# ── Create directory structure ────────────────────────────────────────────────
create_dirs() {
  hdr "Creating CommPlex Directory Structure"
  local dirs=(
    "CommPlexSpec/campaigns"
    "CommPlexSpec/utils"
    "CommPlexCore/campaigns"
    "CommPlexCore/gcp"
    "CommPlexCore/modules"
    "CommPlexCore/scripts"
    "CommPlexAPI/server"
    "CommPlexAPI/modules"
    "CommPlexAPI/scripts"
    "CommPlexEdge/modules"
    "CommPlexEdge/pwa"
    "CommPlexEdge/icons"
    "CommPlex_Data/04_Bureaucracy/01_Requested"
    "CommPlex_Data/04_Bureaucracy/03_Granted"
    "CommPlex_Data/04_Bureaucracy/04_Denied"
    "CommPlex_Data/04_Bureaucracy/05_Archive"
    "tests"
    "deprecated"
    ".devcontainer"
  )
  for d in "${dirs[@]}"; do
    [[ "$DRY_RUN" == "false" ]] && mkdir -p "${INSTALL_DIR}/${d}" || echo "  [DRY] mkdir -p ${d}"
  done
  ok "Directory tree created"
}

# ── Write __init__.py files ───────────────────────────────────────────────────
write_inits() {
  local init_dirs=(
    "CommPlexSpec" "CommPlexSpec/campaigns" "CommPlexSpec/utils"
    "CommPlexCore" "CommPlexCore/campaigns" "CommPlexCore/gcp"
    "CommPlexCore/modules" "CommPlexCore/scripts"
    "CommPlexAPI" "CommPlexAPI/server" "CommPlexAPI/modules"
    "CommPlexEdge" "CommPlexEdge/modules"
    "tests"
  )
  for d in "${init_dirs[@]}"; do
    local target="${INSTALL_DIR}/${d}/__init__.py"
    if [[ "$DRY_RUN" == "false" ]]; then
      [[ ! -f "$target" ]] && touch "$target"
    fi
  done
  ok "__init__.py files created"
}

# ── Write source files using ManifestBuilder ─────────────────────────────────
run_manifest() {
  hdr "Deploying CommPlex Source Files"

  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  MB=""
  for loc in "$SCRIPT_DIR" "$(pwd)" "$HOME" "$HOME/Downloads"; do
    for name in ManifestBuilder_v4_final.py ManifestBuilder_VoiceFinal.py ManifestBuilder_v3.py ManifestBuilder.py; do
      [[ -f "${loc}/${name}" ]] && { MB="${loc}/${name}"; break 2; }
    done
  done

  if [[ -n "$MB" ]]; then
    ok "ManifestBuilder found: $MB"
    [[ "$DRY_RUN" == "false" ]] && $PYTHON "$MB" --dir "$INSTALL_DIR" $([ "$FORCE" == "true" ] && echo "--force")
  else
    warn "ManifestBuilder not found — writing files directly from installer"
    write_files_inline
  fi
}

# ── Inline file writer (fallback if no ManifestBuilder) ──────────────────────
write_files_inline() {
  info "Writing CommPlex files inline..."

  # .env.example
  write_file ".env.example" << 'ENVEOF'
# Arc Badlands CommPlex — Environment Variables
# cp .env.example .env && fill in values
# NEVER commit .env to git

# ── Kill switches (BOTH default ON) ─────────
DRY_RUN=true
VERTEX_STATUS=STUB

# ── Voice Backend ────────────────────────────
# BLAND = Bland.ai (thia@shy2shy.com, ~$2 balance)
# GCP_TWILIO = Google TTS + Twilio (recommended, cheaper)
VOICE_BACKEND=GCP_TWILIO

# ── GCP ─────────────────────────────────────
GCP_PROJECT_ID=commplex-493805
GCS_BUCKET=commplex-assets-493805
VERTEX_LOCATION=us-central1
GOOGLE_APPLICATION_CREDENTIALS=service-account.json

# ── Sluice Engine ────────────────────────────
SLUICE_PRICE_STANDARD=28500
SLUICE_PRICE_AGGRESSIVE=24000
SLUICE_MIN_YEAR=2020

# ── Notifications (ntfy.sh) ──────────────────
NTFY_SERVER=https://ntfy.sh
NTFY_TOPIC=px10pro-commplex-z7x2-alert-hub
NTFY_TOPIC_OPS=commplex-ops-z7x2
NTFY_TOPIC_DEV=commplex-dev-z7x2
NTFY_TOPIC_EMERGENCY=badlands-panic-z7x2

# ── Email (Purelymail SMTP) ──────────────────
SMTP_HOST=smtp.purelymail.com
SMTP_PORT=587
SMTP_USER=kjonesmle@purelymail.com
SMTP_PASSWORD=REPLACE_WITH_APP_PASSWORD

# ── Gmail (alternative SMTP) ─────────────────
# SMTP_HOST=smtp.gmail.com
# SMTP_PORT=587
# SMTP_USER=kjonesmle@gmail.com
# SMTP_PASSWORD=frwp tmyz wmio lppa

# ── Twilio (voice + SMS) ─────────────────────
TWILIO_ACCOUNT_SID=REPLACE_WITH_TWILIO_SID
TWILIO_AUTH_TOKEN=REPLACE_WITH_TWILIO_TOKEN
TWILIO_PHONE_NUMBER=REPLACE_WITH_+1XXXXXXXXXX
TRANSFER_NUMBER=7018705235

# ── Bland.ai (legacy — low balance) ──────────
BLAND_API_KEY=org_741899502e615287eae2dcbfe47ff760f1ba25d311b516a7ce2bd28c5417a784fc3bf0e3dc06a623ff3d69
BLAND_FROM_NUMBER=REPLACE_WITH_+1XXXXXXXXXX

# ── Gemini ───────────────────────────────────
GEMINI_API_KEY=REPLACE_WITH_GEMINI_KEY

# ── Database ─────────────────────────────────
DATABASE_URL=sqlite:///./commplex_leads.db
PORT=8080
LOG_LEVEL=INFO

# ── SendGrid (email scale) ───────────────────
SENDGRID_API_KEY=REPLACE_WITH_SENDGRID_KEY

# ── Campaign ─────────────────────────────────
ACTIVE_CAMPAIGN=mkz
ENVEOF

  # CommPlexSpec/CommPlexConfig.sh
  write_file "CommPlexSpec/CommPlexConfig.sh" << 'CONFEOF'
#!/bin/bash
# CommPlexSpec/CommPlexConfig.sh — Global Config Source
export SENDER_PHONE="7018705235"
export SENDER_EMAIL="kjonesmle@gmail.com"
export SENDER_NAME="Kenyon Jones"
export ALT_PHONE="7019465731"
export ALT_NAME="Cynthia Ennis"
export COMMPLEX_ROOT="${HOME}/Arc-Badlands-CommPlex"
export DRY_RUN="${DRY_RUN:-true}"
export VERTEX_STATUS="${VERTEX_STATUS:-STUB}"
export VOICE_BACKEND="${VOICE_BACKEND:-GCP_TWILIO}"
export NTFY_TOPIC="${NTFY_TOPIC:-px10pro-commplex-z7x2-alert-hub}"
export SLUICE_PRICE_STANDARD="${SLUICE_PRICE_STANDARD:-28500}"
export SLUICE_PRICE_AGGRESSIVE="${SLUICE_PRICE_AGGRESSIVE:-24000}"
export SLUICE_MIN_YEAR="${SLUICE_MIN_YEAR:-2020}"
CONFEOF

  ok "Inline files written (limited set — run ManifestBuilder for complete set)"
}

# Helper: write a single file via heredoc
write_file() {
  local rel_path="$1"; shift
  local full_path="${INSTALL_DIR}/${rel_path}"
  if [[ "$DRY_RUN" == "false" ]]; then
    if [[ "$FORCE" == "true" ]] || [[ ! -f "$full_path" ]]; then
      mkdir -p "$(dirname "$full_path")"
      cat > "$full_path"
    else
      warn "Skipping (exists): ${rel_path} — use --force to overwrite"
    fi
  else
    echo "  [DRY] Write ${rel_path}"
    cat > /dev/null  # consume stdin
  fi
}

# ── Python venv + deps ────────────────────────────────────────────────────────
setup_python() {
  hdr "Python Environment"
  cd "$INSTALL_DIR"
  local venv="${INSTALL_DIR}/.venv"

  if [[ ! -d "$venv" ]] && [[ "$DRY_RUN" == "false" ]]; then
    $PYTHON -m venv "$venv"
    ok "Venv created at $venv"
  fi

  if [[ "$DRY_RUN" == "false" ]] && [[ -f "$venv/bin/activate" ]]; then
    source "$venv/bin/activate"
    pip install --quiet --upgrade pip

    if [[ -f "${INSTALL_DIR}/requirements.txt" ]]; then
      pip install --quiet -r "${INSTALL_DIR}/requirements.txt" || warn "Some deps failed"
    else
      # Minimal install if requirements.txt missing
      pip install --quiet \
        fastapi uvicorn[standard] sqlalchemy pydantic httpx python-dotenv \
        google-cloud-aiplatform google-cloud-secret-manager google-cloud-storage \
        google-cloud-bigquery google-cloud-texttospeech \
        google-api-python-client google-auth-oauthlib gspread \
        twilio requests pyyaml pandas openpyxl pytest pytest-asyncio \
        black ruff sendgrid playwright 2>/dev/null || true
    fi
    playwright install chromium --with-deps 2>/dev/null || true
    ok "Python deps installed"
    deactivate
  fi
}

# ── .env setup ────────────────────────────────────────────────────────────────
setup_env() {
  hdr ".env Configuration"
  local env_file="${INSTALL_DIR}/.env"
  local example="${INSTALL_DIR}/.env.example"

  if [[ -f "$env_file" ]]; then
    warn ".env already exists — preserving (use --force to overwrite)"
    return
  fi

  if [[ "$DRY_RUN" == "false" ]]; then
    [[ -f "$example" ]] && cp "$example" "$env_file" && ok ".env created from .env.example"
  fi
}

# ── GCP secrets sync ──────────────────────────────────────────────────────────
setup_gcp() {
  hdr "GCP Secrets Sync"
  [[ "$SKIP_GCP" == "true" ]] && { warn "Skipping GCP (--skip-gcp)"; return; }
  ! command -v gcloud &>/dev/null && { warn "gcloud not found — skipping"; return; }

  GCP_PROJECT="commplex-493805"
  local active_acct
  active_acct=$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | head -1 || echo "")

  if [[ -z "$active_acct" ]]; then
    warn "Not authenticated. Run: gcloud auth login --no-launch-browser"
    return
  fi
  ok "GCP auth: $active_acct"

  [[ "$DRY_RUN" == "false" ]] && gcloud config set project "$GCP_PROJECT" 2>/dev/null || true

  # Pull secrets into .env
  local env_file="${INSTALL_DIR}/.env"
  if [[ -f "$env_file" ]] && [[ "$DRY_RUN" == "false" ]]; then
    info "Pulling secrets from GCP Secret Manager..."
    pull_secret() {
      local secret_name="$1" env_key="$2"
      local val
      val=$(gcloud secrets versions access latest --secret="$secret_name" --project="$GCP_PROJECT" 2>/dev/null || echo "")
      if [[ -n "$val" ]]; then
        if grep -q "^${env_key}=" "$env_file"; then
          sed -i "s|^${env_key}=.*|${env_key}=${val}|" "$env_file"
        else
          echo "${env_key}=${val}" >> "$env_file"
        fi
        ok "  Pulled: $secret_name"
      else
        warn "  Not found: $secret_name (placeholder kept)"
      fi
    }

    pull_secret "SMTP_PASSWORD"              "SMTP_PASSWORD"
    pull_secret "BLAND_AI_API_KEY"           "BLAND_API_KEY"
    pull_secret "GEMINI_API_KEY"             "GEMINI_API_KEY"
    pull_secret "TWILIO_ACCOUNT_SID"         "TWILIO_ACCOUNT_SID"
    pull_secret "TWILIO_ACCOUNT_AUTH_TOKEN"  "TWILIO_AUTH_TOKEN"
    pull_secret "NTFY_TOPIC_PERSONAL"        "NTFY_TOPIC"
    pull_secret "VERTEX_STATUS"              "VERTEX_STATUS"
    pull_secret "VIN_MKZ"                    "VIN_MKZ"
    pull_secret "VIN_TOWNCAR"                "VIN_TOWNCAR"
    pull_secret "VIN_F350"                   "VIN_F350"
    pull_secret "VIN_JAYCO"                  "VIN_JAYCO"
  fi
}

# ── Git setup ─────────────────────────────────────────────────────────────────
setup_git() {
  hdr "Git Setup"
  cd "$INSTALL_DIR"

  if [[ ! -d ".git" ]] && [[ "$DRY_RUN" == "false" ]]; then
    git init -b main
    ok "Git initialized"
  fi

  if [[ "$DRY_RUN" == "false" ]]; then
    git config user.email "kjones@shy2shy.com"
    git config user.name "Kenyon Jones"
    git config --global credential.helper store

    local remote="https://github.com/KenyukiShy/Arc-Badlands-CommPlex.git"
    local current
    current=$(git remote get-url origin 2>/dev/null || echo "")
    if [[ "$current" != "$remote" ]]; then
      git remote remove origin 2>/dev/null || true
      git remote add origin "$remote"
      ok "Remote: $remote"
    fi
  fi

  warn "To push: cd ${INSTALL_DIR} && git push -u origin main"
  warn "PAT: github.com → Settings → Developer Settings → Tokens (classic) → repo scope"
}

# ── DB init ───────────────────────────────────────────────────────────────────
init_db() {
  hdr "Database Init"
  [[ "$DRY_RUN" == "true" ]] && { info "[DRY] Would init SQLite DB"; return; }

  local venv_py="${INSTALL_DIR}/.venv/bin/python"
  [[ ! -f "$venv_py" ]] && venv_py="$PYTHON"

  cd "$INSTALL_DIR"
  PYTHONPATH="$INSTALL_DIR" "$venv_py" -c "
try:
    from CommPlexAPI.models import init_db
    init_db()
    print('  DB initialized')
except Exception as e:
    print(f'  DB init deferred: {e}')
" 2>/dev/null || warn "DB init deferred — run 'make db-init' later"
}

# ── Status report ─────────────────────────────────────────────────────────────
status_report() {
  hdr "CommPlex Status Report"
  echo ""

  chk() { [[ -f "${INSTALL_DIR}/$1" ]] && ok "$2" || warn "MISSING: $2 ($1)"; }

  chk "CommPlexSpec/campaigns/base.py"       "CommPlexSpec — THE LAW"
  chk "CommPlexCore/gcp/vertex.py"           "CommPlexCore — SluiceEngine + Classifier"
  chk "CommPlexCore/gcp/secrets.py"          "CommPlexCore — Secrets (GCP+ENV dual-mode)"
  chk "CommPlexCore/campaigns/mkz.py"        "CommPlexCore — MKZ Campaign"
  chk "CommPlexCore/campaigns/towncar.py"    "CommPlexCore — TownCar Campaign"
  chk "CommPlexCore/campaigns/f350.py"       "CommPlexCore — F350 Campaign"
  chk "CommPlexCore/campaigns/jayco.py"      "CommPlexCore — Jayco Campaign"
  chk "CommPlexCore/campaigns/registry.py"   "CommPlexCore — CampaignRegistry"
  chk "CommPlexCore/modules/voice_gcp.py"    "CommPlexCore — Voice (Bland + GCP/Twilio)"
  chk "CommPlexAPI/server/main.py"           "CommPlexAPI — FastAPI Gateway"
  chk "CommPlexAPI/models.py"               "CommPlexAPI — Lead Models"
  chk "CommPlexEdge/modules/notifier.py"     "CommPlexEdge — Notifier (ntfy)"
  chk "CommPlexEdge/index.html"             "CommPlexEdge — PWA Dashboard"
  chk "tests/test_commplex.py"             "Tests — 73-test suite"
  chk ".env"                               ".env config"

  echo ""
  echo -e "${BD}Voice Backend Status:${RS}"
  local voice_backend
  voice_backend=$(grep "^VOICE_BACKEND=" "${INSTALL_DIR}/.env" 2>/dev/null | cut -d= -f2 || echo "not set")
  info "  VOICE_BACKEND=${voice_backend}"
  info "  Bland.ai account: thia@shy2shy.com (~\$2 balance)"
  info "  Migration: Set VOICE_BACKEND=GCP_TWILIO in .env for cheaper calling"
}

# ── Post-install summary ──────────────────────────────────────────────────────
post_install() {
  echo ""
  echo -e "${BD}${CY}╔══════════════════════════════════════════════════════════╗"
  echo -e "║          CommPlex v5-Final — Install Complete            ║"
  echo -e "╚══════════════════════════════════════════════════════════╝${RS}"
  echo ""
  echo -e "${BD}Next steps:${RS}"
  echo ""
  echo "  1. Fill .env secrets:"
  echo "     nano ${INSTALL_DIR}/.env"
  echo ""
  echo "  2. Run test suite:"
  echo "     cd ${INSTALL_DIR}"
  echo "     source .venv/bin/activate"
  echo "     pytest tests/ -v   # expect 73 passed"
  echo ""
  echo "  3. Start CommPlexAPI:"
  echo "     make api    # FastAPI at http://localhost:8080/docs"
  echo ""
  echo "  4. Test voice (GCP_TWILIO backend, dry-run):"
  echo "     python CommPlexCore/modules/voice_gcp.py --status"
  echo "     python CommPlexCore/modules/voice_gcp.py --preview MKZ_2016_HYBRID"
  echo ""
  echo "  5. Send first real wave (dry-run):"
  echo "     VOICE_BACKEND=GCP_TWILIO DRY_RUN=true"
  echo "     python CommPlexCore/scripts/run_campaign.py --campaign mkz --module phone"
  echo ""
  echo -e "${YL}  Phase gate before DRY_RUN=false:${RS}"
  echo "  [ ] Twilio webhook URL set → https://your-cloud-run/voice/twiml"
  echo "  [ ] NTFY_TOPIC=px10pro-commplex-z7x2-alert-hub subscribed on Pixel 10"
  echo "  [ ] All REPLACE_WITH_ secrets filled"
  echo "  [ ] VERTEX_STATUS=ACTIVE in .env"
  echo "  [ ] pytest tests/ → 73/73 green"
  echo "  [ ] Shadow mode sluice error rate < 5%"
  echo "  [ ] DRY_RUN=false  ← flip last"
  echo ""
  echo -e "${BD}Voice cost comparison:${RS}"
  echo "  Bland.ai (current):  ~\$0.09/min | ~\$2 remaining"
  echo "  GCP_TWILIO (migrate): ~\$0.015/min | \$300 GCP credit"
  echo "  Recommendation: VOICE_BACKEND=GCP_TWILIO immediately"
  echo ""
  echo -e "${BD}Team collaborator invites (need GitHub usernames):${RS}"
  echo "  Charles: ccp@shy2shy.com — email ready, need @github_handle"
  echo "  Cynthia: thia@shy2shy.com — email ready, need @github_handle"
  echo "  Justin:  jstnshw@shy2shy.com — email ready, need @github_handle"
  echo "  Once they sign up: bash invite_team.sh --all-repos"
  echo ""
}

# ── Main ──────────────────────────────────────────────────────────────────────
banner
detect_env

if [[ "$STATUS_ONLY" == "true" ]]; then
  status_report
  exit 0
fi

create_dirs
write_inits
run_manifest
setup_python
setup_env
setup_gcp
setup_git
init_db
status_report
post_install
