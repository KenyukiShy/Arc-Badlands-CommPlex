# Arc Badlands CommPlex — v5 Final
**Production Date:** April 20, 2026 | **Lead Architect:** Kenyon Jones | **Project:** commplex-493805

## 🔗 Live Operations Status
* **API Health:** [LIVE](https://commplex-api-349126848698.us-central1.run.app/health) (Status: Healthy / DB: Connected)
* **GCP Logs:** [Cloud Run Console](https://console.cloud.google.com/run/detail/us-central1/commplex-api/logs?project=commplex-493805)
* **Alert Hub:** [ntfy.sh/px10pro-commplex-z7x2-alert-hub](https://ntfy.sh/px10pro-commplex-z7x2-alert-hub)

## 🏛️ The Four Laws (Metaphor Key)
To maintain strict domain isolation, we use the following naming conventions:
1. **Spec (The Law):** Interfaces and base classes.
2. **Core (The Brain):** AI logic, Campaign data, and Sluice filtering.
3. **API (The Mouth):** FastAPI gateway and Twilio Webhooks.
4. **Edge (The Hands):** Notifications (ntfy) and User Dashboard.

## 📊 Phase Gate Status
| Item | Status |
| :--- | :--- |
| **GCP Project** | Active (commplex-493805) |
| **Infrastructure** | Live on Cloud Run |
| **Test Suite** | **103/103 GREEN** ✅ |
| **AI Status** | **ACTIVE** (DRY_RUN=false) |
| **Twilio Number** | +1-866-736-2349 |

## 🛠️ Quick Start for Developers
1. **Clone:** `git clone https://github.com/shy2shy/arc-badlands-commplex.git`
2. **Install:** `make install` (installs venv and dependencies)
3. **Secrets:** Run `bash gcp_secrets_sync.sh` to hydrate your local `.env`.
4. **Verify:** Run `make test` to confirm 103 tests pass.

## 📂 Domain Map
* `CommPlexSpec/` -> Base Campaign logic.
* `CommPlexCore/` -> Vehicle data (MKZ, TownCar, F350, Jayco) and AI classification.
* `CommPlexAPI/` -> Webhook routes and Database models.
* `CommPlexEdge/` -> ntfy push modules and PWA dashboard.
