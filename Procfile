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

web: gunicorn CommPlexAPI.server.main:app \
       --worker-class uvicorn.workers.UvicornWorker \
       --workers 2 \
       --bind 0.0.0.0:${PORT:-8000} \
       --timeout 120 \
       --keep-alive 5 \
       --log-level info \
       --access-logfile - \
       --error-logfile -

sentry: python sentry.py
