# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Does

Arc Badlands CommPlex is an AI-driven vehicle procurement automation platform. It places outbound AI phone calls and sends emails to auto dealers asking if they want to buy vehicles owned by Kenyon Jones. Inbound dealer responses are classified by Gemini Flash through a qualification pipeline ("Sluice Engine"), leads are persisted, and push notifications fire when a deal qualifies.

## Commands

All primary dev tasks run through `make` with `PYTHONPATH=$(PWD)` set automatically.

```bash
make install          # Create .venv, install requirements
make api              # Start FastAPI dev server on :8080 (--reload)
make test             # Full pytest suite (VERTEX_STATUS=STUB DRY_RUN=true)
make test-smoke       # Smoke tests only (-k "smoke")
make lint             # ruff check on all four domains
make fmt              # black formatter on all four domains
make db-init          # Initialize SQLite DB (or Cloud SQL)
make db-reset         # Drop + reinit DB
make deploy           # gcloud run deploy to Cloud Run (us-central1)
make sync-secrets     # Pull GCP secrets to .env
make status           # Show DRY_RUN, VERTEX_STATUS, GCP auth state
```

Run a single test file or test by name:
```bash
PYTHONPATH=$(PWD) VERTEX_STATUS=STUB DRY_RUN=true pytest tests/test_commplex.py::test_name -v --tb=short
```

## Architecture: The Four Laws (Domain Isolation)

The monorepo enforces strict domain separation — no cross-domain imports except through `CommPlexSpec` interfaces.

| Domain | Role |
|---|---|
| `CommPlexSpec/` | "The Law" — ABCs, interfaces, shared types. `BaseCampaign`, `Contact`, `verify_price()` live here. |
| `CommPlexCore/` | "The Brain" — AI classification (`GeminiFlashClassifier`, `SluiceEngine`), campaign data, voice backends. |
| `CommPlexAPI/` | "The Mouth" — FastAPI gateway, Twilio webhooks, SQLAlchemy `Lead` model, DB. |
| `CommPlexEdge/` | "The Hands" — ntfy/Pushover/FCM push notifications, PWA dashboard. |

## Key Patterns

**Template Method — Campaigns:** `BaseCampaign` (in `CommPlexSpec/campaigns/base.py`) defines the campaign flow. Concrete campaigns (`CommPlexCore/campaigns/mkz.py`, `towncar.py`, `f350.py`, `jayco.py`) supply only data (vehicle details, scripts, contacts). New vehicles = new file implementing `BaseCampaign`.

**Chain of Responsibility — Sluice Engine:** `CommPlexCore/gcp/vertex.py` runs `YearFilter → PriceFilter → AntiHallucinationFilter` in sequence. Each filter can short-circuit to `REJECTED` or `MANUAL_REVIEW`.

**Strategy — Backends:** `VoiceBackend` (Bland.ai vs GCP/Twilio) and `NotifyBackend` (ntfy/Pushover/FCM) are swappable via env vars (`VOICE_BACKEND`, notification config).

**Registry:** `CommPlexCore/campaigns/registry.py` maps slug → class (`mkz`, `towncar`, `f350`, `jayco`). Adding a campaign requires registering it here.

**Singleton loaders:** `get_classifier()`, `get_sluice()`, `get_voice_module()` are module-level singletons — call these rather than constructing directly.

## The Anti-Hallucination Guardrail ("The Law")

`BaseCampaign.verify_price(raw_text, price)` checks that any LLM-reported price actually appears in the source transcript (handles `$25,000` / `25,000` / `25k` formats). If the price is not verifiable in raw text, the lead is flagged `MANUAL_REVIEW` instead of `QUALIFIED`. This check runs in both `CommPlexSpec` and `SluiceEngine` — never bypass it.

## Lead Lifecycle

```
PENDING → SluiceEngine → QUALIFIED | REJECTED | MANUAL_REVIEW
QUALIFIED → CommPlexEdge fires ntfy/Pushover/FCM alert → human closes deal
```

## Kill Switches (Safety-First)

Both default ON — never disable in tests or dev unless intentional:

- `DRY_RUN=true` — no real calls or SMS are placed
- `VERTEX_STATUS=STUB` — no Vertex AI calls; regex-based stub classifier used

These are automatically set in `pyproject.toml` `[tool.pytest.ini_options]` for all test runs.

## Environment & Infrastructure

- **GCP Project:** `commplex-493805`
- **Hosting:** Google Cloud Run (`commplex-api`, `us-central1`)
- **DB:** SQLite locally (`commplex_leads.db`); Cloud SQL (asyncpg) in production via `DATABASE_URL`
- **Voice (current):** Bland.ai; migration target is `VOICE_BACKEND=GCP_TWILIO` (Google TTS + Twilio, ~7× cheaper)
- **Twilio number:** `+1-866-736-2349`
- **Push notifications:** ntfy topic `px10pro-commplex-z7x2-alert-hub`
- **CI:** GitHub Actions runs `make test` on every push

## Branching & Commit Conventions

- Branches: `feat/KJ-<issue>-<slug>` → `dev` → `master` (protected, architect-only merges)
- PRs target `dev`; must pass all 103 tests; require 1 review
- Commit format: `type(scope): description` (e.g. `fix(api): correct webhook signature validation`)
