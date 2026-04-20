# Arc Badlands CommPlex — v5 Final
**April 20, 2026 | Kenyon Jones (KenyukiShy) | commplex-493805**

---

## CONFIRMED INFRASTRUCTURE (from images)

| Item | Value | Status |
|---|---|---|
| GCP Project | commplex-493805 | ✅ Active |
| IAM | kjones.px10pro@gmail.com — Owner | ✅ Set |
| APIs | Secret Manager, Firestore, Gemini, Compute, BigQuery | ✅ Enabled |
| ntfy PRIMARY topic | `px10pro-commplex-z7x2-alert-hub` | ✅ LIVE (4 alerts) |
| ntfy secondary topic | `arc-badlands-kenyon` | ✅ Subscribed |
| Google Voice | (701) 951-8490 → forwards to (701) 870-5235 | ✅ Active |
| Twilio number | +1-866-736-2349 (toll-free) | ✅ Confirmed |
| Bland.ai | thia@shy2shy.com, ~$2 balance | ⚠ Low |
| Email primary | kjonesmle@gmail.com (SMTP) | ✅ Use this |
| Voice backend | GCP_TWILIO (recommended) | ⏸ Deploy needed |

---

## TEAM

| Person | GitHub | Email | Domain |
|---|---|---|---|
| Kenyon | KenyukiShy | kjones@shy2shy.com | CommPlexSpec + Core |
| Charles | v-n-n-v | ccp@shy2shy.com | CommPlexAPI |
| Justin | jstnmshw | jstnshw@shy2shy.com | QA |
| Cynthia | Thia or Kitt (TBD) | thia@shy2shy.com | CommPlexEdge |

---

## QUICK START

```bash
# 1. Extract package
tar -xzf commplex_v5.tar.gz
cd commplex_v5

# 2. Set up Python
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Configure
cp .env.example .env
nano .env  # fill REPLACE_WITH_ values

# 4. Pull secrets from GCP (if gcloud authed)
bash gcp_secrets_sync.sh

# 5. Run tests
make test

# 6. Start API
make api
# → http://localhost:8080/docs

# 7. Test notifications (Pixel 10)
make notifier-test
```

---

## VOICE ARCHITECTURE (GCP_TWILIO — confirmed working)

```
CommPlexCore.VoiceModule.run_wave()
    ↓
Twilio REST API → dials +1-866-736-2349 outbound
    ↓
Twilio webhooks to CommPlexAPI /voice/twiml
    ↓
FastAPI returns TwiML with <Say voice="Google.en-US-Neural2-F">
    ↓  (NO separate Google TTS API needed — it's built into Twilio)
Dealer hears Morgan's script
    ↓ press 1 → ntfy alert to px10pro-commplex-z7x2-alert-hub
    ↓ press 3 → transfers to (701) 870-5235
```

**Cost:** ~$0.015/min vs $0.09/min on Bland.ai
**Setup remaining:** Deploy CommPlexAPI to Cloud Run → get webhook URL

---

## DEPLOY TO CLOUD RUN (one command)

```bash
make deploy
# → Copy the service URL
# → Set TWILIO_WEBHOOK_BASE_URL=https://commplex-api-xxx-uc.a.run.app in .env
# → Go to console.twilio.com → your 866 number → Voice webhook → paste URL + /voice/twiml
```

---

## NTFY CONFIRMED

Both topics active on Pixel 10:
- `px10pro-commplex-z7x2-alert-hub` — **PRIMARY** (instant delivery ON)
- `arc-badlands-kenyon` — secondary

Test alert:
```bash
curl -d "CommPlex test" -H "Title: Test" https://ntfy.sh/px10pro-commplex-z7x2-alert-hub
```

---

## PHONE NUMBER DECISION

| Number | Use |
|---|---|
| (701) 870-5235 | Kenyon's cell — TRANSFER TARGET only |
| (701) 951-8490 | Google Voice — receiving/forwarding only |
| +1-866-736-2349 | Twilio toll-free — OUTBOUND AI calls ← USE THIS |
| Bland.ai number | Check app.bland.ai (if still using Bland) |

---

## PHASE GATE CHECKLIST

```
[✅] GCP project commplex-493805 active
[✅] APIs enabled (Secret Manager, Firestore, BigQuery, etc.)
[✅] ntfy subscribed: px10pro-commplex-z7x2-alert-hub
[✅] Twilio number: +1-866-736-2349
[ ] make test → 73/73 green
[ ] gcloud run deploy → get webhook URL
[ ] Set TWILIO_WEBHOOK_BASE_URL in .env + in Twilio console
[ ] Fill SMTP_PASSWORD (Gmail app password)
[ ] VERTEX_STATUS=ACTIVE (after SA key confirmed)
[ ] DRY_RUN=false ← FLIP LAST
```

---

## FILE MAP

```
Arc-Badlands-CommPlex/
├── CommPlexSpec/campaigns/base.py      ← THE LAW
├── CommPlexCore/
│   ├── campaigns/{mkz,towncar,f350,jayco,registry}.py
│   ├── gcp/{vertex,secrets}.py
│   └── modules/voice_gcp.py           ← Bland.ai + GCP/Twilio dual-mode
├── CommPlexAPI/
│   ├── server/main.py                  ← FastAPI gateway
│   ├── models.py
│   └── modules/voice_routes.py        ← Twilio TwiML webhooks
├── CommPlexEdge/
│   ├── modules/notifier.py             ← ntfy push
│   └── index.html                      ← PWA dashboard
├── tests/test_commplex.py              ← 73-test suite
├── .env.example                        ← Fill this
├── Makefile                            ← make api / test / deploy
├── requirements.txt
└── pyproject.toml
```
