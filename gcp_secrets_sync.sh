#!/usr/bin/env bash
# gcp_secrets_sync.sh — Pull GCP secrets into local .env
# Run after gcloud auth login to hydrate .env with live vault values
#
# Usage:
#   bash gcp_secrets_sync.sh                  # pull all secrets to .env
#   bash gcp_secrets_sync.sh --show           # show current secret names
#   bash gcp_secrets_sync.sh --validate       # check which secrets are placeholders

set -euo pipefail

GCP_PROJECT="commplex-493805"
INSTALL_DIR="${HOME}/Arc-Badlands-CommPlex"
ENV_FILE="${INSTALL_DIR}/.env"

GR='\033[92m'; YL='\033[93m'; RD='\033[91m'; CY='\033[96m'; RS='\033[0m'
ok()   { echo -e "${GR}✓${RS} $*"; }
warn() { echo -e "${YL}⚠${RS}  $*"; }
info() { echo -e "${CY}→${RS} $*"; }

# ── Verify auth ────────────────────────────────────────────────────────────────
if ! gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | head -1 | grep -q "@"; then
  echo -e "${RD}Not authenticated with gcloud.${RS}"
  echo "Run: gcloud auth login --no-launch-browser"
  echo "Then: gcloud auth application-default login --no-launch-browser"
  exit 1
fi

ACCT=$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | head -1)
ok "Authenticated as: $ACCT"

# ── --show mode ───────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--show" ]]; then
  echo ""
  info "Secrets in commplex-493805:"
  gcloud secrets list --project="$GCP_PROJECT" --format="table(name,createTime)"
  exit 0
fi

# ── --validate mode ───────────────────────────────────────────────────────────
if [[ "${1:-}" == "--validate" ]]; then
  echo ""
  info "Checking for placeholder values..."
  PLACEHOLDER_SECRETS=(
    "BLAND_AI_API_KEY" "GEMINI_API_KEY" "TWILIO_ACCOUNT_SID"
    "TWILIO_ACCOUNT_AUTH_TOKEN" "SMTP_PASSWORD"
  )
  ALL_OK=true
  for SECRET in "${PLACEHOLDER_SECRETS[@]}"; do
    VAL=$(gcloud secrets versions access latest --secret="$SECRET" --project="$GCP_PROJECT" 2>/dev/null || echo "")
    if [[ -z "$VAL" ]] || echo "$VAL" | grep -qi "REPLACE"; then
      warn "$SECRET — PLACEHOLDER OR MISSING"
      ALL_OK=false
    else
      ok "$SECRET — set (${#VAL} chars)"
    fi
  done
  echo ""
  [[ "$ALL_OK" == "true" ]] && ok "All critical secrets are set." || warn "Some secrets need real values."
  exit 0
fi

# ── Pull secrets into .env ─────────────────────────────────────────────────────
[[ ! -f "$ENV_FILE" ]] && { warn ".env not found at ${ENV_FILE} — run COMMPLEX_INSTALL.sh first"; exit 1; }

pull_secret() {
  local SECRET_NAME="$1" ENV_KEY="$2"
  local VAL
  VAL=$(gcloud secrets versions access latest --secret="$SECRET_NAME" --project="$GCP_PROJECT" 2>/dev/null || echo "")
  if [[ -n "$VAL" ]] && ! echo "$VAL" | grep -qi "REPLACE"; then
    if grep -q "^${ENV_KEY}=" "$ENV_FILE"; then
      sed -i "s|^${ENV_KEY}=.*|${ENV_KEY}=${VAL}|" "$ENV_FILE"
    else
      echo "${ENV_KEY}=${VAL}" >> "$ENV_FILE"
    fi
    ok "${SECRET_NAME} → ${ENV_KEY}"
  else
    warn "${SECRET_NAME} — placeholder or not found (keeping current)"
  fi
}

echo ""
info "Pulling secrets from commplex-493805 → ${ENV_FILE}"
echo ""

pull_secret "SMTP_PASSWORD"              "SMTP_PASSWORD"
pull_secret "BLAND_AI_API_KEY"           "BLAND_API_KEY"
pull_secret "GEMINI_API_KEY"             "GEMINI_API_KEY"
pull_secret "TWILIO_ACCOUNT_SID"         "TWILIO_ACCOUNT_SID"
pull_secret "TWILIO_ACCOUNT_AUTH_TOKEN"  "TWILIO_AUTH_TOKEN"
pull_secret "NTFY_TOPIC_PERSONAL"        "NTFY_TOPIC"
pull_secret "VERTEX_STATUS"              "VERTEX_STATUS"
pull_secret "GCP_PROJECT_ID"             "GCP_PROJECT_ID"
pull_secret "GCS_BUCKET"                 "GCS_BUCKET"
pull_secret "SLUICE_PRICE_STANDARD"      "SLUICE_PRICE_STANDARD"
pull_secret "SLUICE_PRICE_AGGRESSIVE"    "SLUICE_PRICE_AGGRESSIVE"
pull_secret "SLUICE_MIN_YEAR"            "SLUICE_MIN_YEAR"
pull_secret "VIN_MKZ"                    "VIN_MKZ"
pull_secret "VIN_TOWNCAR"                "VIN_TOWNCAR"
pull_secret "VIN_F350"                   "VIN_F350"
pull_secret "VIN_JAYCO"                  "VIN_JAYCO"

echo ""
ok "Sync complete. Review: cat ${ENV_FILE}"
echo ""
echo "To go live:"
echo "  1. Set VERTEX_STATUS=ACTIVE (when SA key is vaulted)"
echo "  2. Set DRY_RUN=false (very last step, after shadow mode)"
