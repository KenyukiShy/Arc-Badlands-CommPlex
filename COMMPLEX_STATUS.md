# Arc Badlands CommPlex — Integration Status & Next Steps
# Generated: April 20, 2026 | Prepared for git commit

---

## CURRENT PROJECT STATE

### What's Complete and Solid
| File | Domain | Status |
|---|---|---|
| CommPlexSpec/campaigns/base.py | Spec | ✅ THE LAW — verify_price(), Contact, BaseCampaign |
| CommPlexCore/gcp/vertex.py | Core | ✅ GeminiFlashClassifier + SluiceEngine (STUB→ACTIVE) |
| CommPlexCore/gcp/secrets.py | Core | ✅ Dual-mode GCP+ENV, get_secret()/require_secret() |
| CommPlexCore/campaigns/mkz.py | Core | ✅ Full MKZ with qualify_inbound() + anti-hallucination |
| CommPlexCore/campaigns/towncar.py | Core | ✅ BaT pitch + SluiceEngine integration |
| CommPlexCore/campaigns/f350.py | Core | ✅ Unicorn V10 King Ranch + BaT contacts |
| CommPlexCore/campaigns/jayco.py | Core | ✅ ND Climate Shield pitch + Corral Sales primary |
| CommPlexCore/campaigns/registry.py | Core | ✅ CampaignRegistry (SLUG→class, reset() for tests) |
| CommPlexCore/modules/voice_gcp.py | Core | ✅ NEW — Bland.ai + GCP/Twilio dual-mode |
| CommPlexAPI/server/main.py | API | ✅ FastAPI — /webhook/bland, /webhook/email, /leads |
| CommPlexAPI/models.py | API | ✅ SQLAlchemy Lead + LeadStatus |
| CommPlexAPI/scripts/test_gateway.py | API | ✅ 8-scenario simulation suite |
| CommPlexAPI/modules/voice_routes.py | API | ✅ NEW — Twilio TwiML webhooks |
| CommPlexEdge/modules/notifier.py | Edge | ✅ ntfy.sh + Pushover + FCM |
| CommPlexEdge/index.html | Edge | ✅ PWA dashboard with heat badges |
| CommPlexEdge/pwa/sw.js | Edge | ✅ Service Worker + offline cache |
| CommPlexEdge/pwa/manifest.json | Edge | ✅ Arc Badlands branding |
| tests/test_commplex.py | Tests | ✅ 73 tests across all 4 domains |
| COMMPLEX_INSTALL.sh | Root | ✅ v5-Final self-contained installer |

### Legacy Files to Tombstone (not yet moved)
```bash
mkdir -p deprecated
mv app.py config.py storage.py bigquery.py vertex.py tracker.py \
   test_all.py stubs.py formfill.py emailer.py mkz_campaign.py \
   all_campaigns.py base_campaign.py run_campaign.py deprecated/
```

---

## VOICE STRATEGY — BLAND.AI → GCP/TWILIO MIGRATION

### Current State
- **Old Bland.ai account** (kjonesmle): overdrawn at -$6.40
- **New Bland.ai account** (thia@shy2shy.com): ~$2 balance
  - Key: `org_741899502e615287eae2dcbfe47ff760f1ba25d311b516a7ce2bd28c5417a784fc3bf0e3dc06a623ff3d69`
  - Good for testing only — will run out fast

### Recommended Migration: GCP_TWILIO Backend

| Provider | Cost/min | Notes |
|---|---|---|
| Bland.ai (old) | ~$0.09/min | Overdrawn |
| Bland.ai (new) | ~$0.09/min | ~$2 = ~22 mins total |
| **GCP_TWILIO** | **~$0.015/min** | ~$300 credit = 20,000 mins |
| Google Voice | N/A | NO public API — consumer only |
| Dialogflow CX | ~$0.003/min + $0.001/sec | Requires CCAI setup, complex |

### Migration Steps
```bash
# 1. Set backend in .env
VOICE_BACKEND=GCP_TWILIO

# 2. Wire Twilio webhook in Twilio console:
#    From: https://console.twilio.com
#    Phone Numbers → your number → Voice → webhook:
#    https://your-cloud-run-url/voice/twiml

# 3. Add voice routes to main.py:
from CommPlexAPI.modules.voice_routes import router as voice_router
app.include_router(voice_router, prefix="/voice", tags=["Voice"])

# 4. Test (dry-run):
python CommPlexCore/modules/voice_gcp.py --status
python CommPlexCore/modules/voice_gcp.py --preview MKZ_2016_HYBRID
```

### Pure Google Voice Option
Google Voice does NOT have a public API. Cannot be automated.
If you want pure-Google, use **Dialogflow CX Phone Gateway** — but this
requires a CCAI setup and is more complex than Twilio. Stick with Twilio.

---

## EMAIL STRATEGY

### Current Configuration
- **Purelymail** (primary): smtp.purelymail.com:587
  - Secret: `SMTP_PASSWORD` (already in GCP vault: `frwp tmyz wmio lppa`)
- **Gmail** (backup): smtp.gmail.com:587
  - Same app password works
- **SendGrid** (scale): REPLACE_WITH_SENDGRID_KEY
  - Add when Gmail rate limits hit (~500/day)

### Gmail API vs SMTP
Use Gmail SMTP for now — simpler, works. Gmail API only needed if you want
to send AS a different address or need OAuth2 delegation.

---

## GCP INTEGRATION STATUS

| Resource | Status | Notes |
|---|---|---|
| Project: commplex-493805 | ✅ Active | |
| GCS Bucket: commplex-assets-493805 | ✅ Created | |
| Secret Manager | ✅ All secrets vaulted | See list below |
| Service Account | ✅ Created | SA key in vault as SERVICE_ACCOUNT_JSON |
| Billing upgraded | ✅ Confirmed | SA key creation unblocked |
| Firestore | ✅ Created | Hardware registry (XE4118GTS) |
| BigQuery | ✅ commplex_analytics | Campaign events |
| Vertex AI | ⏸ STUB | Activate: set VERTEX_STATUS=ACTIVE |
| Cloud Run | ⏸ Not deployed | Deploy CommPlexAPI for Twilio webhook URL |
| Google TTS | ⏸ Not enabled | Run: gcloud services enable texttospeech.googleapis.com |

### Enable Google TTS
```bash
gcloud services enable texttospeech.googleapis.com --project=commplex-493805
```

### Deploy CommPlexAPI to Cloud Run (for Twilio webhook)
```bash
cd ~/Arc-Badlands-CommPlex
gcloud run deploy commplex-api \
  --source CommPlexAPI/ \
  --project=commplex-493805 \
  --region=us-central1 \
  --platform=managed \
  --allow-unauthenticated \
  --set-env-vars="DRY_RUN=true,VERTEX_STATUS=STUB"
# Copy the service URL → set as TWILIO_WEBHOOK_BASE_URL in .env
```

---

## GCP SECRETS VAULT (commplex-493805)

All stored — confirmed from your session notes:

| Secret Name | Status | Notes |
|---|---|---|
| TWILIO_ACCOUNT_SID | ✅ Live | AC0bx... |
| TWILIO_ACCOUNT_AUTH_TOKEN | ✅ Live | 663dx... |
| TWILIO_ACCOUNT_TEST_SID | ✅ Test | AC56x... |
| TWILIO_API_KEY_SID | ✅ | SK26x... |
| TWILIO_API_KEY_SECRET | ✅ | FIGTx... |
| BLAND_AI_API_KEY | ✅ NEW | org_7418... (thia@shy2shy.com) |
| GEMINI_API_KEY | ✅ | AIzax... |
| SMTP_PASSWORD | ✅ Gmail app pw | frwp tmyz wmio lppa |
| VAST_API_KEY | ✅ | 7879x... |
| SERVICE_ACCOUNT_JSON | ✅ | SA key content |
| VIN_MKZ | ✅ | 3LN6L2LUXGR630397 |
| VIN_TOWNCAR | ✅ | 1LNBM82FXJY779113 |
| VIN_F350 | ✅ | 1FTWW31Y86EA12357 |
| VIN_JAYCO | ✅ | 1UJCJ0BPXH1P20237 |
| NTFY_TOPIC_PERSONAL | ⏸ Update | Set to: px10pro-commplex-z7x2-alert-hub |
| VERTEX_STATUS | ✅ | STUB |

### Update NTFY topic
```bash
printf 'px10pro-commplex-z7x2-alert-hub' | \
  gcloud secrets versions add NTFY_TOPIC_PERSONAL --data-file=-
```

---

## TEAM STATUS

| Person | Domain | Email | GitHub | Status |
|---|---|---|---|---|
| Kenyon | Spec + Core | kjones@shy2shy.com | KenyukiShy | ✅ Active |
| Charles | API | ccp@shy2shy.com | ❓ Need @handle | ⏸ Waiting |
| Cynthia | Edge | thia@shy2shy.com | ❓ Need @handle | ⏸ Waiting |
| Justin | QA | jstnshw@shy2shy.com | ❓ Need @handle | ⏸ Waiting |

Once they sign up at github.com and share @handles:
```bash
bash invite_team.sh --all-repos
```

---

## GOOGLE WORKSPACE INTEGRATION (Planned)

| Service | Purpose | Status |
|---|---|---|
| Google Sheets (gspread) | Live outreach status tracker | ⏸ Implement |
| Google Drive | Archive transcripts/PDFs | ⏸ Implement via drive_sync.py |
| Google Docs | Sales packets (already as DOCX) | Ready |
| Google Keep | Quick notes / alerts | Consumer — no API |
| Gmail | Outbound email | ✅ SMTP configured |
| Google Calendar | Wave scheduling | ⏸ Optional |
| Google Chat | Team notifications | Alternative to Slack |

---

## GPU / COMPUTE STRATEGY

**Current CommPlex needs NO GPU.** Gemini Flash is a serverless API call.

| Use Case | Tech | When |
|---|---|---|
| Lead classification | Gemini Flash API | NOW — STUB→ACTIVE |
| Form fills (Playwright) | GCP e2-standard-4 preemptible | Per wave (~$0.05/wave) |
| Database | SQLite → Cloud SQL | Phase 2 |
| Dashboard | Cloud Run (serverless) | Deploy CommPlexAPI |
| GPU fine-tuning | Vast.ai T4 ($0.05/hr) | Only if custom model needed |

No V100/A100/H100 needed for Phase 1. Vast.ai key is in vault if burst needed.

---

## PHASE GATE CHECKLIST

```
[ ] bash COMMPLEX_INSTALL_v5.sh                  # Install all files
[ ] cd ~/Arc-Badlands-CommPlex && nano .env       # Fill REPLACE_WITH_ values
[ ] gcloud auth login                             # Authenticate
[ ] bash gcp_secrets_sync.sh                      # Pull secrets to .env
[ ] gcloud services enable texttospeech.googleapis.com
[ ] gcloud run deploy commplex-api ...            # Get Twilio webhook URL
[ ] Set TWILIO_WEBHOOK_BASE_URL in .env           # Wire Twilio callbacks
[ ] Set NTFY_TOPIC=px10pro-commplex-z7x2-alert-hub
[ ] Subscribe Pixel 10 to ntfy topic             # ntfy app → subscribe
[ ] VERTEX_STATUS=ACTIVE in .env                 # After SA key confirmed
[ ] pytest tests/ → 73/73 green
[ ] DRY_RUN=true shadow mode run
[ ] Sluice error rate < 5%
[ ] DRY_RUN=false  ← flip last
```

---

## QUESTIONS STILL NEEDED

1. **Charles & Cynthia GitHub handles** — needed for `bash invite_team.sh`
2. **Twilio phone number** — check console.twilio.com → phone numbers
3. **Bland.ai phone number** (new account: thia@shy2shy.com) — check app.bland.ai/home?page=phone-numbers
4. **Purelymail vs Gmail** — confirmed Purelymail is primary? Or Gmail?
5. **Pixel 10 ntfy confirmed?** — is `px10pro-commplex-z7x2-alert-hub` subscribed?

---

## FILES DELIVERED THIS SESSION

```
COMMPLEX_INSTALL_v5.sh                  # Master installer (self-contained)
CommPlexCore--modules--voice_gcp.py     # Voice: Bland.ai + GCP/Twilio dual-mode
CommPlexAPI--modules--voice_routes.py   # Twilio TwiML webhook routes
COMMPLEX_STATUS.md                      # This document
```

Place `CommPlexCore--modules--voice_gcp.py` at `CommPlexCore/modules/voice_gcp.py`
Place `CommPlexAPI--modules--voice_routes.py` at `CommPlexAPI/modules/voice_routes.py`
