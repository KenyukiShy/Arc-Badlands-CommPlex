.PHONY: api edge test lint clean push dry-all db-init secrets wave-mkz voice-status deploy

PYTHON  := .venv/bin/python
PYTEST  := .venv/bin/pytest
UVICORN := .venv/bin/uvicorn
GCP_PROJECT := commplex-493805
REGION  := us-central1

# ── Dev ───────────────────────────────────────
api:
	PYTHONPATH=$(PWD) $(UVICORN) CommPlexAPI.server.main:app --reload --host 0.0.0.0 --port 8080

edge:
	cd CommPlexEdge && python3 -m http.server 5173

test:
	PYTHONPATH=$(PWD) VERTEX_STATUS=STUB DRY_RUN=true $(PYTEST) tests/ -v --tb=short

test-smoke:
	PYTHONPATH=$(PWD) VERTEX_STATUS=STUB $(PYTEST) tests/ -v -k "smoke" --tb=short

lint:
	.venv/bin/ruff check CommPlexSpec CommPlexCore CommPlexAPI CommPlexEdge 2>/dev/null || true

fmt:
	.venv/bin/black CommPlexSpec CommPlexCore CommPlexAPI CommPlexEdge 2>/dev/null || true

db-init:
	PYTHONPATH=$(PWD) $(PYTHON) -c "from CommPlexAPI.models import init_db; init_db(); print('DB ready')"

db-reset:
	rm -f commplex_leads.db && $(MAKE) db-init

# ── Secrets ───────────────────────────────────
secrets:
	gcloud secrets list --project=$(GCP_PROJECT) --format="table(name)"

sync-secrets:
	bash gcp_secrets_sync.sh

update-ntfy:
	printf 'px10pro-commplex-z7x2-alert-hub' | gcloud secrets versions add NTFY_TOPIC_PERSONAL --data-file=- --project=$(GCP_PROJECT)
	@echo "ntfy topic updated in vault"

# ── Voice ─────────────────────────────────────
voice-status:
	PYTHONPATH=$(PWD) $(PYTHON) CommPlexCore/modules/voice_gcp.py --status

voice-preview:
	PYTHONPATH=$(PWD) $(PYTHON) CommPlexCore/modules/voice_gcp.py --preview MKZ_2016_HYBRID

voice-test:
	PYTHONPATH=$(PWD) $(PYTHON) CommPlexCore/modules/voice_gcp.py --qa-test "What is the price?" --campaign mkz

# ── Notifications ─────────────────────────────
notifier-test:
	PYTHONPATH=$(PWD) NTFY_TOPIC=px10pro-commplex-z7x2-alert-hub \
	  $(PYTHON) -m CommPlexEdge.modules.notifier --test

notifier-qualified:
	PYTHONPATH=$(PWD) NTFY_TOPIC=px10pro-commplex-z7x2-alert-hub \
	  $(PYTHON) -m CommPlexEdge.modules.notifier --qualified

# ── GCP Cloud Run Deploy ───────────────────────
deploy:
	@echo "Deploying CommPlexAPI to Cloud Run..."
	gcloud run deploy commplex-api \
	  --source . \
	  --project=$(GCP_PROJECT) \
	  --region=$(REGION) \
	  --platform=managed \
	  --allow-unauthenticated \
	  --set-env-vars="DRY_RUN=true,VERTEX_STATUS=STUB,NTFY_TOPIC=px10pro-commplex-z7x2-alert-hub,GOOGLE_GENAI_USE_VERTEXAI=True" \
	  --memory=512Mi
	@echo "After deploy: copy the service URL and set TWILIO_WEBHOOK_BASE_URL in .env"

enable-tts:
	gcloud services enable texttospeech.googleapis.com --project=$(GCP_PROJECT)
	@echo "Google TTS enabled"

# ── Campaigns ─────────────────────────────────
list:
	PYTHONPATH=$(PWD) $(PYTHON) -c "\
from CommPlexCore.campaigns.registry import CampaignRegistry; \
CampaignRegistry.reset(); \
[print(f'{s[\"campaign_id\"]}: {s[\"total_contacts\"]} contacts | {s[\"asking\"]}') for s in CampaignRegistry.summaries()]"

wave-dry:
	PYTHONPATH=$(PWD) DRY_RUN=true $(PYTHON) -c "\
from CommPlexCore.campaigns.registry import CampaignRegistry; \
from CommPlexCore.modules.voice_gcp import VoiceModule; \
CampaignRegistry.reset(); vm = VoiceModule(); \
c = CampaignRegistry.get('mkz'); r = vm.run_wave(c, wave=1, dry_run=True); print(r)"

# ── Housekeeping ──────────────────────────────
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true

push:
	git add -A && git commit -m "feat: CommPlex update $(shell date +%Y-%m-%d_%H:%M)" && git push

status:
	@echo "=== CommPlex Status ==="
	@[ -f .env ] && grep -E "^(DRY_RUN|VERTEX_STATUS|VOICE_BACKEND|NTFY_TOPIC)=" .env || echo "No .env found"
	@echo ""
	@echo "=== GCP ==="
	@gcloud config get-value project 2>/dev/null || echo "gcloud not authed"
