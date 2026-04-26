# CommPlex v5 — Procfile
# ============================================================
# Cloud Run: set PORT env var; gunicorn binds to 0.0.0.0:$PORT
# Sentry runs as a background worker (no port binding needed).
#
# Local dev (via Honcho or foreman): `honcho start`
# Production deploy: two separate Cloud Run services recommended
#   - commplex-api    → runs `web` process
#   - commplex-sentry → runs `sentry` process (always-on min-instances=1)
# ============================================================

web: sh -c 'cd /workspace/CommPlexAPI && PYTHONPATH=/workspace uvicorn server.main:app --host 0.0.0.0 --port ${PORT:-8080}'

sentry: python sentry.py
