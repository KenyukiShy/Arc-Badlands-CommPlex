"""
CommPlexCore/gcp/secrets.py — Google Secret Manager Client
Domain: CommPlexCore (The Brain)

Replaces direct os.getenv() for sensitive values throughout CommPlex.
Falls back gracefully to os.getenv() for local development (.env file).

GoF: Proxy — get_secret() proxies GCP Secret Manager; transparently
falls back to environment variables when not on GCP or in STUB mode.

Usage:
    from CommPlexCore.gcp.secrets import get_secret, require_secret

    # Soft fetch — returns empty string if missing (dev-safe)
    api_key = get_secret("BLAND_API_KEY")

    # Hard fetch — raises if missing (use in production paths)
    api_key = require_secret("BLAND_API_KEY")

Strategy for dual-mode operation:
    LOCAL DEV:      reads from .env via os.getenv() fallback
    CLOUD RUN:      injects via --set-secrets; GCP pulls automatically
    GCP DIRECT:     pulls live from Secret Manager

SECRET CANONICAL NAMES (as stored in GCP Secret Manager):
    Team:        OWNER_FULL_NAME, OWNER_PHONE, OWNER_EMAIL, DEV_0[1-3]_*
    GCP:         GCP_PROJECT_ID, GCS_BUCKET, VERTEX_STATUS, VERTEX_LOCATION
    Sluice:      SLUICE_PRICE_STANDARD, SLUICE_PRICE_AGGRESSIVE, SLUICE_MIN_YEAR
    Notify:      NTFY_SERVER, NTFY_TOPIC_PERSONAL, NTFY_TOPIC_OPS, NTFY_TOPIC_DEV
    APIs:        BLAND_API_KEY, GEMINI_API_KEY, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN
    Email:       SMTP_PASSWORD
    Hardware:    VAST_API_KEY
    SA:          SERVICE_ACCOUNT_JSON
"""

from __future__ import annotations
import os
import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)

# ── Module-level config ───────────────────────────────────────────────────────

_GCP_PROJECT = os.getenv("GCP_PROJECT_ID", "commplex-493805")
_USE_GCP     = os.getenv("VERTEX_STATUS", "STUB") != "STUB"  # GCP only when ACTIVE

# ── In-memory cache (TTL-less — process lifetime) ─────────────────────────────
_cache: Dict[str, str] = {}


def get_secret(secret_id: str, version: str = "latest",
               fallback_env: bool = True) -> str:
    """
    Pull a secret from GCP Secret Manager.
    Falls back to os.getenv(secret_id) when GCP is unavailable or in STUB mode.

    GoF: Proxy — identical interface whether GCP or env var backs the call.

    Args:
        secret_id:    Canonical secret name (e.g. "BLAND_API_KEY")
        version:      Secret version string (default "latest")
        fallback_env: If True, fall back to os.getenv when GCP fails

    Returns:
        Secret value string (empty string if not found anywhere)
    """
    # Cache hit
    cache_key = f"{secret_id}:{version}"
    if cache_key in _cache:
        return _cache[cache_key]

    # Try GCP Secret Manager if ACTIVE
    if _USE_GCP:
        try:
            from google.cloud import secretmanager
            client = secretmanager.SecretManagerServiceClient()
            name   = f"projects/{_GCP_PROJECT}/secrets/{secret_id}/versions/{version}"
            resp   = client.access_secret_version(request={"name": name})
            value  = resp.payload.data.decode("UTF-8")
            _cache[cache_key] = value
            logger.debug(f"[Secrets] GCP pull: {secret_id}")
            return value
        except Exception as e:
            logger.warning(f"[Secrets] GCP pull failed for {secret_id!r}: {e}")

    # Fallback: environment variable
    if fallback_env:
        value = os.getenv(secret_id, "")
        if value:
            _cache[cache_key] = value
            logger.debug(f"[Secrets] ENV fallback: {secret_id}")
        else:
            logger.warning(f"[Secrets] {secret_id!r} not found in GCP or env")
        return value

    return ""


def require_secret(secret_id: str, version: str = "latest") -> str:
    """
    Like get_secret() but raises ValueError if the value is empty or a placeholder.
    Use in production code paths where a missing key is a fatal error.

    Args:
        secret_id: Canonical secret name

    Returns:
        Secret value string (never empty — raises otherwise)

    Raises:
        ValueError: If secret is missing or still contains a placeholder value
    """
    value = get_secret(secret_id, version)
    if not value or value.startswith("REPLACE_WITH") or value.startswith("PENDING"):
        raise ValueError(
            f"[Secrets] Required secret {secret_id!r} is missing or still has placeholder value. "
            f"Set it via: printf 'your-value' | gcloud secrets versions add {secret_id} --data-file=-"
        )
    return value


def get_secret_batch(secret_ids: list, version: str = "latest") -> Dict[str, str]:
    """
    Fetch multiple secrets at once. Returns a dict keyed by secret_id.
    Missing/failed secrets have empty string values.

    Args:
        secret_ids: List of canonical secret name strings
        version:    Version to fetch for all (default "latest")

    Returns:
        Dict[secret_id → value]
    """
    return {sid: get_secret(sid, version) for sid in secret_ids}


def invalidate_cache(secret_id: Optional[str] = None):
    """
    Invalidate the in-memory cache.
    Pass secret_id to invalidate one entry; pass None to clear all.

    Use when you know a secret has been rotated mid-process.
    """
    global _cache
    if secret_id is None:
        _cache = {}
        logger.info("[Secrets] Full cache cleared")
    else:
        keys_to_clear = [k for k in _cache if k.startswith(f"{secret_id}:")]
        for k in keys_to_clear:
            del _cache[k]
        logger.info(f"[Secrets] Cache cleared for {secret_id!r}")


def health() -> Dict:
    """Return secrets module health info — useful for /health endpoint."""
    return {
        "mode":         "GCP" if _USE_GCP else "ENV",
        "project":      _GCP_PROJECT,
        "cached":       len(_cache),
        "vertex_status": os.getenv("VERTEX_STATUS", "STUB"),
    }


# ── Known required secrets (for validation / health checks) ──────────────────

REQUIRED_PRODUCTION_SECRETS = [
    "BLAND_API_KEY",
    "GEMINI_API_KEY",
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "SMTP_PASSWORD",
]

PLACEHOLDER_SECRETS = [
    "SERVICE_ACCOUNT_JSON",
    "TWILIO_API_KEY_SID",
    "TWILIO_API_KEY_SECRET",
]

def validate_production_secrets() -> Dict[str, bool]:
    """
    Check whether all production-required secrets have real (non-placeholder) values.
    Returns dict of {secret_id: is_valid}.

    Use in Stage 11 health check and before flipping DRY_RUN=false.
    """
    results = {}
    for sid in REQUIRED_PRODUCTION_SECRETS:
        val = get_secret(sid)
        is_valid = bool(val) and not val.startswith("REPLACE_WITH") and not val.startswith("PENDING")
        results[sid] = is_valid
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("=" * 60)
    print("CommPlexCore — Secrets Module Test")
    print("=" * 60)

    h = health()
    print(f"\nHealth: {h}")

    print("\n── Soft fetches (dev-safe) ──")
    test_secrets = [
        "GCP_PROJECT_ID", "VERTEX_STATUS", "NTFY_TOPIC_PERSONAL",
        "SLUICE_PRICE_STANDARD", "BLAND_API_KEY",
    ]
    for sid in test_secrets:
        val = get_secret(sid)
        masked = (val[:8] + "...") if len(val) > 8 else (val or "(empty)")
        print(f"  {sid}: {masked}")

    print("\n── Production secret validation ──")
    validation = validate_production_secrets()
    all_ok = True
    for sid, valid in validation.items():
        icon = "✅" if valid else "⚠️ "
        print(f"  {icon} {sid}: {'set' if valid else 'PLACEHOLDER OR MISSING'}")
        if not valid:
            all_ok = False

    print()
    if all_ok:
        print("✅ All production secrets validated.")
    else:
        print("⚠️  Some secrets need real values before going live.")
        print("   Update with: printf 'value' | gcloud secrets versions add NAME --data-file=-")
