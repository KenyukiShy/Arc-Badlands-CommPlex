# Arc Badlands — Glossary of Terms
## For Cynthia, Charles, and anyone new to the stack

These definitions are written for people who can work with Python but are building
their mental model of what each piece does and why.

---

### A

**API (Application Programming Interface)**
A door between two programs. When we tell Bland AI to make a call, we're knocking on
their API door with a message in JSON format. They handle the phone call machinery.
We handle the business logic.
→ Think of it as ordering food via an app: you don't cook it, you just send the order.

**async / await**
Python keywords for "start this and don't block the whole program waiting for it."
`await page.goto(url)` means "go to this URL and wait, but let other code run meanwhile."
Without `async`, filling 5 forms in a row takes 5× as long. With it, they happen simultaneously.
→ Python docs: https://docs.python.org/3/library/asyncio.html

**aiohttp**
An async HTTP library. Like `requests`, but it can fire 10 API calls at once without waiting.
Used in `bland_dispatcher.py` to dispatch parallel calls.
→ https://docs.aiohttp.org/

---

### B

**Bland AI**
The voice AI platform that handles our outbound calls. We send it a phone number and a
"system prompt" (instructions), and it dials, talks, and sends us back a transcript.
Free Start plan: 100 calls/day, $0.14/min.
→ https://docs.bland.ai/

**Branch (Git)**
A parallel copy of the codebase for working without breaking the main version.
Cynthia works on `cynthia/playwright`. Charles works on `charles/voice`.
Kenyon reviews and merges into `main`.
→ https://git-scm.com/book/en/v2/Git-Branching-Basic-Branching-and-Merging

---

### C

**C4 Model**
A way of drawing software architecture at four levels: Context → Containers → Components → Code.
We're not using formal C4 here, but the concept of "zoom levels" is useful:
- Context: The whole project and who it talks to (dealers, Gmail, Bland AI)
- Container: The main pieces (form filler, voice dispatcher, webhook server, dashboard)
- Component: What's inside each piece (semantic fill function, draft generator, etc.)
→ https://c4model.com/

**Colab (Google Colaboratory)**
A free Jupyter notebook environment hosted by Google. No install needed.
It runs our Python code in a cloud Linux machine with up to 12GB RAM.
Limitation: sessions time out after 90 min idle or 12 hours total.
→ https://colab.google/

**Crostini**
Chrome OS's built-in Linux container. Lets you run Linux apps (like PyCharm, Python, Git)
on a Chromebook without dual-booting. It's a sandboxed Debian environment.
→ https://chromeos.dev/en/linux

---

### D

**devcontainer.json**
A configuration file that tells GitHub Codespaces exactly how to set up the dev environment.
It's like a recipe: "Install Python 3.12, install Playwright, install Node.js 20, forward port 8000."
Everyone who opens the repo in Codespaces gets the exact same environment automatically.
→ https://containers.dev/

**Docker / Container**
A lightweight, portable "box" containing an app and everything it needs to run.
We use the official Playwright Docker image as our base — it pre-installs Chrome and all the
system libraries that headless browsers need. Without it, Chrome won't start on a server.
→ https://docs.docker.com/get-started/

---

### E

**Edge AI / On-Device AI**
AI running directly on a device (like your Pixel 10 Pro) instead of in the cloud.
Gemini Nano runs on-device. Fast, private, no internet required.
We defer this to Phase 2 — for now our AI runs in Gemini's cloud.
→ https://ai.google/get-started/on-device/

**Environment Variable (.env)**
A way to store secrets (API keys, passwords) outside of your code.
Instead of typing your API key in the script (and accidentally committing it to GitHub!),
you store it in a `.env` file that is never committed.
`os.getenv("BLAND_API_KEY")` reads it at runtime.
→ https://saurabh-kumar.com/python-dotenv/

---

### F

**FastAPI**
A Python web framework for building APIs. We use it to host our webhook endpoint:
the URL that Bland AI POSTs call transcripts to after each call ends.
It's fast, modern, and automatically generates API documentation at `/docs`.
→ https://fastapi.tiangolo.com/

**Form Fill / Web Automation**
Using a script to navigate a website and fill out forms automatically, as if a human typed it.
Playwright is our tool for this. It controls a real Chrome browser instance.
→ https://playwright.dev/python/

---

### G

**Gemini API**
Google's large language model API. We use it for:
  1. Reading dealer email replies and drafting responses
  2. (Phase 2) Gemini Nano on-device for call scoring
Free tier: 15 requests/minute, 1 million tokens/day. More than enough.
→ https://ai.google.dev/gemini-api/docs

**Git**
The version control system that tracks all changes to code.
`git commit` = save a snapshot. `git push` = upload to GitHub.
`git pull` = download the latest from teammates.
→ https://git-scm.com/book/en/v2

**GitHub Codespaces**
VS Code running in your browser, connected to a Linux container provisioned by GitHub.
60 hours/month free per account. Works on Chromebook, Windows, Pixel — any device with Chrome.
Your code is automatically synced with the GitHub repo.
→ https://docs.github.com/en/codespaces

**gspread**
Python library for reading and writing Google Sheets. Our "database."
We read dealer rows from the sheet, lock them, and write results back.
→ https://docs.gspread.org/

---

### H

**Headless Browser**
Chrome running with no visible window. The robot equivalent of browsing the web.
It can load pages, click buttons, fill forms, and take screenshots — invisibly.
Required for running in Colab/Codespaces/servers (no screen available).
→ https://playwright.dev/python/docs/api/class-browser#browser-launch

**HOT Lead**
A dealer who showed buying intent: multiple email opens, replied with a price,
or asked for callback. Sheet status: `[ HOT ]`. Dashboard color: emerald green.
Warrant immediate manual follow-up before automated pipeline.

---

### I

**Idempotent / Idempotency**
A function that's safe to call multiple times with the same result as calling it once.
Our orchestrator is idempotent: if you run it twice, rows already marked `[Cy]`
are skipped. No dealer gets contacted twice by accident.
→ Related: "at-least-once delivery" vs. "exactly-once delivery"

---

### J

**JSON (JavaScript Object Notation)**
A text format for structured data. Looks like Python dicts.
`{"vin": "1UJCJ0BPXH1P20237", "price": 28500}` is JSON.
APIs send and receive JSON. Our `vehicle_bible.json` is JSON.
→ https://www.json.org/

---

### L

**Label (Gmail)**
Like a tag or folder in Gmail. We use `arc-badlands-pending` to mark emails
we've already processed so we don't generate duplicate drafts.
→ https://developers.google.com/gmail/api/guides/labels

**Locking (Row Lock)**
Writing `[L]` to a row in the sheet before processing it.
This prevents two simultaneous runs of the script from both trying to fill the same form.
Like placing a "reserved" sign on a restaurant table.

---

### N

**nest_asyncio**
A tiny Python library that patches the asyncio event loop so async code works inside
Jupyter notebooks and Google Colab (which already have their own event loop running).
Without it: `RuntimeError: This event loop is already running.`
With it: everything works.
→ https://github.com/erdewit/nest_asyncio

**ngrok**
A tool that creates a public HTTPS URL tunneling to a port on your local machine.
When Bland AI wants to POST a transcript to our webhook, it needs a public URL.
ngrok makes your local `localhost:8000` reachable from the internet.
Free tier is sufficient for testing.
→ https://ngrok.com/docs/getting-started/

---

### O

**OAuth2**
A secure authentication protocol. Instead of giving Gmail your password,
you get a temporary "access token" that lets our script read/write your Gmail.
The token is saved in `config/gmail_token.json` and refreshed automatically.
→ https://developers.google.com/identity/protocols/oauth2

**Orchestrator**
The "brain" script that reads the task list and decides what to do.
It doesn't fill forms itself — it calls `form_filler.py` to do that.
It doesn't make calls itself — it calls `bland_dispatcher.py`.
It coordinates everything and writes results back to the sheet.
→ Pattern: https://en.wikipedia.org/wiki/Orchestration_(computing)

---

### P

**Playwright**
Microsoft's browser automation library. Controls Chrome headlessly.
Key advantage over older tools (Selenium): better async support, faster, more reliable
with JavaScript-heavy modern websites.
→ https://playwright.dev/python/docs/intro

**POST Request**
An HTTP message that sends data to a server. When we trigger a Bland AI call,
we POST a JSON payload to `https://api.bland.ai/v1/calls`.
GET = asking for data. POST = sending data (usually to create something).
→ https://developer.mozilla.org/en-US/docs/Web/HTTP/Methods/POST

---

### S

**Semantic Search (Form Filling)**
Finding form fields by looking at their LABEL TEXT instead of hardcoded CSS selectors.
Instead of: `await page.fill("#vin_input_id_123", value)`
We do: find every `<label>` on the page, look for labels containing "VIN", fill that input.
This makes the bot work on any website without writing custom code per site.

**Sequence Diagram**
A diagram showing how components communicate over time, using vertical bars (lifelines)
and horizontal arrows (messages). Useful for understanding call flows.
See `docs/sequence_diagram.md` for our system's diagram.
→ https://www.plantuml.com/plantuml/uml/

**Service Account**
A special Google "robot" account that lets our Python script access Google APIs
without anyone needing to log in. You create it in Google Cloud Console,
download a JSON key file, and our script uses it to authenticate.
→ https://cloud.google.com/iam/docs/service-account-overview

**SIP (Session Initiation Protocol)**
The protocol behind internet phone calls. "SIP Transfer" means Bland AI
warm-transfers the call to your real phone using SIP, so the dealer
seamlessly transitions from talking to the bot to talking to you.
→ https://en.wikipedia.org/wiki/Session_Initiation_Protocol

**State Machine**
A system that can only be in one state at a time and transitions between
defined states based on inputs. Our row states: `[ ] → [L] → [Cy] → [HOT]`
The orchestrator is the machine. The sheet is the state store.

**SvelteKit**
A JavaScript framework for building web UIs. Cynthia uses it for the status dashboard.
It's fast, component-based, and works great as a PWA (installable web app) on Pixels.
→ https://kit.svelte.dev/

---

### U

**uvicorn**
The server that runs our FastAPI webhook app.
`uvicorn webhook_server:app --port 8000` starts it listening on port 8000.
→ https://www.uvicorn.org/

---

### V

**Vehicle Bible**
Our term for `config/vehicle_bible.json`. The single source of truth for every
vehicle's specs, pricing, VIN, and contact info. No number or spec should be
typed twice — it should always be read from the Bible.

**VIN (Vehicle Identification Number)**
The unique 17-character ID for a specific vehicle. Like a serial number.
Our Jayco's VIN: `1UJCJ0BPXH1P20237`. Never misspell this in a form.

---

### W

**Webhook**
A URL that an external service calls when something happens.
Bland AI calls our webhook when a call ends, to deliver the transcript.
Gmail could call a webhook when an email arrives.
It's the opposite of polling (us asking "anything new?") — instead,
they push data to us immediately when it's available.
→ https://en.wikipedia.org/wiki/Webhook

**WebSocket**
A persistent two-way connection between client and server.
We avoided this in favor of polling (simpler, cheaper) for our dashboard.
Phase 2 consideration if we need real-time updates faster than 10-second intervals.
→ https://developer.mozilla.org/en-US/docs/Web/API/WebSocket
