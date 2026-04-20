#!/usr/bin/env bash
# .devcontainer/setup.sh — runs once after container creation in Codespaces/VS Code
set -euo pipefail

CYAN='\033[96m'; GREEN='\033[92m'; YELLOW='\033[93m'; RESET='\033[0m'
log() { echo -e "${CYAN}→${RESET} $*"; }
ok()  { echo -e "${GREEN}✓${RESET} $*"; }

cd /workspace

# 1. Python venv
log "Creating Python venv..."
python3 -m venv .venv
source .venv/bin/activate
pip install --quiet --upgrade pip

# 2. Install all deps
log "Installing Python dependencies..."
pip install --quiet -r requirements.txt
playwright install chromium --with-deps

# 3. Install Node deps (CommPlexEdge Svelte dashboard)
if [[ -f "CommPlexEdge/package.json" ]]; then
  log "Installing Node dependencies (CommPlexEdge)..."
  cd CommPlexEdge && npm install && cd /workspace
fi

# 4. GCP auth (will prompt in terminal on first open)
log "GCP auth status..."
gcloud auth list 2>/dev/null || echo "Run: gcloud auth login"

# 5. Create .env from example if missing
[[ -f ".env" ]] || { cp .env.example .env; ok ".env created from template"; }

# 6. Init DB
log "Initializing CommPlexAPI DB..."
PYTHONPATH=/workspace python -c "
from CommPlexAPI.models import init_db
init_db()
print('DB initialized')
"

ok "CommPlex devcontainer ready"
echo ""
echo "  Start API:  make api"
echo "  Run tests:  make test"
echo "  Dashboard:  make edge"
