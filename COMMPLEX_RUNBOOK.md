# Arc Badlands CommPlex — Master Runbook
**Version:** v5-Final | **Date:** April 20, 2026 | **Author:** Claude (Architect Review)

---

## WHAT YOU SAW IN TWILIO — AND WHAT TO IGNORE

The screenshots show you browsing **Twilio Flex**, **Twilio Video**, and **Marketplace**.
**None of those are relevant to CommPlex.** CommPlex uses exactly one Twilio product:

```
✅ USED:  Twilio Programmable Voice  (outbound calls with TwiML + "Morgan" agent)
❌ SKIP:  Twilio Flex                (contact center SaaS — not needed)
❌ SKIP:  Twilio Video               (WebRTC rooms — not needed)
❌ SKIP:  Marketplace / Add-ons      (not needed)
```

Your Twilio trial account **CommPlex** has $15.50 balance and phone number **+1-866-736-2349**.
That number is your Morgan outbound caller. Everything else in Twilio console is noise.

---

## CURRENT STATE SUMMARY (from screenshots + vault)

| Item | Value | Status |
|---|---|---|
| Twilio account | CommPlex — **Trial** $15.50 | ⚠ Needs upgrade |
| Twilio number | +1-866-736-2349 | ✅ Use as TWILIO_PHONE_NUMBER |
| Bland.ai (thia) | org_741899...  ~$2 | ⚠ Low — use GCP_TWILIO |
| ntfy (Pixel 10) | px10pro-commplex-z7x2-alert-hub | ✅ LIVE, confirmed |
| GCP project | commplex-493805 | ✅ Active |
| GCP credit | $10 remaining (Google Dev Program, expires Apr 2027) | ✅ Enough for Phase 1 |
| GCP IAM | kjones.px10pro@gmail.com = Owner | ✅ |
| Gemini API key | In vault as GEMINI_API_KEY | ✅ |
| SA key | Blocked (free trial) → billing upgrade unblocks | ⚠ |
| Voice backend | GCP_TWILIO recommended ($0.013/min vs $0.09/min Bland) | 👆 Switch to this |

---

## STEP 1 — INSTALL COMMPLEXPLEX v5-FINAL ON CHROMEBOOK

```bash
# Extract the tar on your Chromebook
cd ~
tar -xzf ~/Downloads/commplex_v5_final_tar.gz
mv commplex_pkg Arc-Badlands-CommPlex
cd Arc-Badlands-CommPlex

# Set up Python venv
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Copy .env and fill it
cp .env.example .env
nano .env   # see Step 2 for what to fill
```

---

## STEP 2 — FILL YOUR .env

These are the values that matter. Everything else has a safe default.

```bash
# ── KILL SWITCHES (keep true until ready) ──────────────────
DRY_RUN=true
VERTEX_STATUS=STUB

# ── VOICE BACKEND (use this, not Bland) ────────────────────
VOICE_BACKEND=GCP_TWILIO

# ── TWILIO ──────────────────────────────────────────────────
TWILIO_ACCOUNT_SID=AC0bx...         # from vault / Twilio console
TWILIO_AUTH_TOKEN=663dx...           # from vault / Twilio console
TWILIO_PHONE_NUMBER=+18667362349     # your 866 number = Morgan

# ── GCP ─────────────────────────────────────────────────────
GCP_PROJECT_ID=commplex-493805
VERTEX_STATUS=STUB                  # change to ACTIVE after SA key step

# ── GEMINI ──────────────────────────────────────────────────
GEMINI_API_KEY=AIza...              # from vault

# ── EMAIL ────────────────────────────────────────────────────
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=kjonesmle@gmail.com
SMTP_PASSWORD=frwp tmyz wmio lppa   # from vault (SMTP_PASSWORD secret)

# ── NOTIFICATIONS ────────────────────────────────────────────
NTFY_SERVER=https://ntfy.sh
NTFY_TOPIC=px10pro-commplex-z7x2-alert-hub   # YOUR CONFIRMED LIVE TOPIC

# ── TRANSFER NUMBER ──────────────────────────────────────────
TRANSFER_NUMBER=7018705235
```

Pull live from GCP vault (fastest way):
```bash
bash gcp_secrets_sync.sh
# Requires: gcloud auth login --no-launch-browser
```

---

## STEP 3 — TWILIO: THE ONLY SETUP NEEDED

**You only need to do two things in Twilio:**

### 3A. Upgrade trial account (required for outbound calling to non-verified numbers)

Go to: https://console.twilio.com → **Upgrade account**
Cost: Add $20 minimum. At $0.013/min outbound, that's ~1,500 minutes of Morgan calls.
Your current $15.50 trial balance carries forward after upgrade.

### 3B. Wire the voice webhook (after Cloud Run deploy in Step 4)

1. console.twilio.com → **Phone Numbers** → **Active numbers** → click **+1-866-736-2349**
2. Under **Voice & Fax** → **A CALL COMES IN**: leave blank (you make outbound, not receive)
3. Under **Voice & Fax** → **Call Status Changes**: set to `https://YOUR_CLOUD_RUN_URL/voice/status`
4. Save

That's it. Nothing else in Twilio console matters for CommPlex.

---

## STEP 4 — DEPLOY COMMPLEXAPI TO CLOUD RUN (THE MAIN BLOCKER)

This gives you a stable HTTPS URL that Twilio can webhook to.

```bash
# From Arc-Badlands-CommPlex directory
cd CommPlexAPI

# One-time deploy
gcloud run deploy commplex-api \
  --source . \
  --project=commplex-493805 \
  --region=us-central1 \
  --platform=managed \
  --allow-unauthenticated \
  --set-env-vars="DRY_RUN=true,VERTEX_STATUS=STUB,VOICE_BACKEND=GCP_TWILIO" \
  --set-secrets="TWILIO_ACCOUNT_SID=TWILIO_ACCOUNT_SID:latest,\
TWILIO_AUTH_TOKEN=TWILIO_ACCOUNT_AUTH_TOKEN:latest,\
GEMINI_API_KEY=GEMINI_API_KEY:latest,\
SMTP_PASSWORD=SMTP_PASSWORD:latest,\
NTFY_TOPIC=NTFY_TOPIC_PERSONAL:latest"

# Get your URL
gcloud run services describe commplex-api \
  --platform=managed --region=us-central1 \
  --format='value(status.url)'
# → https://commplex-api-XXXX-uc.a.run.app
```

After deploy, set `TWILIO_WEBHOOK_BASE_URL=https://commplex-api-XXXX-uc.a.run.app` in .env.

---

## STEP 5 — GCP IAM / SERVICE ACCOUNT / VERTEX

### Current IAM state (confirmed from your session):
- `kjones.px10pro@gmail.com` = **Owner** ✅
- `commplex-sa@commplex-493805.iam.gserviceaccount.com` = Created ✅
- Roles already granted: aiplatform.user, secretmanager.secretAccessor, storage.objectAdmin, datastore.user, bigquery.dataEditor ✅

### What's still blocked: SA key creation (requires billing upgrade)

```bash
# Step 5A: Upgrade billing (one-time — keeps $10 credit intact)
# Go to: console.cloud.google.com/billing
# Click "Activate full account" — does NOT charge you until credits run out

# Step 5B: After upgrade, create SA key
gcloud resource-manager org-policies disable-enforce \
  iam.disableServiceAccountKeyCreation --project=commplex-493805

gcloud iam service-accounts keys create /tmp/sa-key.json \
  --iam-account=commplex-sa@commplex-493805.iam.gserviceaccount.com

# Step 5C: Vault the key
gcloud secrets versions add SERVICE_ACCOUNT_JSON --data-file=/tmp/sa-key.json
rm /tmp/sa-key.json  # clean up local copy

# Step 5D: Activate Vertex AI
printf 'ACTIVE' | gcloud secrets versions add VERTEX_STATUS --data-file=-

# Step 5E: Update .env
# Change VERTEX_STATUS=STUB → VERTEX_STATUS=ACTIVE
```

### No SSO setup needed.
CommPlex doesn't use Twilio SSO, Flex SSO, or any identity provider. Your GCP Owner account
(`kjones.px10pro@gmail.com`) is the only admin. Charles/Cynthia get GitHub repo access,
not GCP console access.

---

## STEP 6 — VOICE: HOW THE TWILIO + GCP_TWILIO BACKEND WORKS

When CommPlex places an outbound call, here's the exact flow:

```
CommPlexCore/modules/voice_gcp.py
  → calls Twilio REST API: POST /2010-04-01/Accounts/{SID}/Calls
  → Twilio dials dealer's phone number FROM +1-866-736-2349
  → When dealer picks up, Twilio webhooks to YOUR Cloud Run URL:
      GET https://commplex-api-XXXX-uc.a.run.app/voice/twiml?campaign_id=mkz
  → CommPlexAPI/modules/voice_routes.py returns TwiML
  → TwiML uses <Say voice="Google.en-US-Neural2-F"> to play Morgan's script
  → Dealer presses 1 (interested) → Twilio webhooks to /voice/gather
  → CommPlexAPI fires ntfy alert to your Pixel 10
  → Dealer presses 3 → Twilio transfers call to +1-701-870-5235 (you)
```

**No Google Cloud TTS API setup required** — Twilio handles the Google TTS call internally.
`<Say voice="Google.en-US-Neural2-F">` works natively in any Twilio account.

---

## STEP 7 — RUN YOUR FIRST WAVE

```bash
# From Arc-Badlands-CommPlex, with venv active
cd ~/Arc-Badlands-CommPlex
source .venv/bin/activate

# Verify imports work
make test  # or: python -m pytest tests/test_commplex.py -v

# Preview the MKZ contact list
python CommPlexCore/campaigns/registry.py

# Dry-run wave (no real calls fire, DRY_RUN=true)
PYTHONPATH=. python CommPlexCore/modules/voice_gcp.py --preview MKZ_2016_HYBRID
PYTHONPATH=. python CommPlexCore/modules/voice_gcp.py --status

# Shadow mode: run with real leads, DRY_RUN still true
# Compare AI sluice decisions to what you'd manually decide
# When sluice error rate < 5%: flip DRY_RUN=false

# LIVE: flip ONE switch
# In .env: DRY_RUN=false
# Then:
PYTHONPATH=. python CommPlexCore/modules/voice_gcp.py --campaign mkz --wave 1
```

---

## PHASE GATE — ARMED WHEN ALL ✅

```
[ ] Twilio trial account UPGRADED (console.twilio.com → Upgrade)
[ ] CommPlexAPI deployed to Cloud Run (gcloud run deploy)
[ ] TWILIO_WEBHOOK_BASE_URL set to Cloud Run URL
[ ] Twilio number +1-866-736-2349 status callback wired
[ ] GCP billing upgraded → SA key created → vaulted
[ ] VERTEX_STATUS=ACTIVE in .env (after SA key step)
[ ] ntfy CONFIRMED: px10pro-commplex-z7x2-alert-hub subscribed on Pixel 10 ✅
[ ] make test → 73/73 green
[ ] Shadow mode run → sluice error rate < 5%
[ ] DRY_RUN=false  ← very last flip
```

---

## COST FORECAST (after upgrades)

| Service | Cost | Notes |
|---|---|---|
| Twilio outbound voice | $0.013/min | Morgan calls dealers |
| Google TTS | $0 | Twilio handles it internally |
| Cloud Run | $0 | Free tier (2M req/mo) |
| GCP Vertex Flash | ~$0.0001/call | Gemini classification |
| GCP Credit ($10) | burns ~$2-3/mo | Plenty for Phase 1 |
| Twilio $15.50 trial | + $20 upgrade | ~2,000 minutes of Morgan |

**Total runway: $35 Twilio + $10 GCP ≈ unlimited for Phase 1.**

---

## THINGS TO NEVER DO IN YOUR TWILIO ACCOUNT

- Do NOT set up Flex (contact center — $150/user/mo)
- Do NOT provision Twilio Video rooms (WebRTC — not needed)
- Do NOT use Twilio Studio (visual flow builder — use voice_gcp.py instead)
- Do NOT add add-ons from Marketplace (not needed)
- Do NOT change the +1-866-736-2349 number assignment

---

## QUICKREF: THE 5 URLS THAT MATTER

```
GCP Console:     console.cloud.google.com/home/dashboard?project=commplex-493805
Secret Manager:  console.cloud.google.com/security/secret-manager?project=commplex-493805
Cloud Run:       console.cloud.google.com/run?project=commplex-493805
Twilio Phone:    console.twilio.com/us1/develop/phone-numbers/manage/active
Bland.ai (thia): app.bland.ai (if you want to keep it as backup)
ntfy web:        ntfy.sh/px10pro-commplex-z7x2-alert-hub (live feed in browser)
```
