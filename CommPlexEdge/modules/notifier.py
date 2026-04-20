"""
CommPlexEdge/modules/notifier.py — Arc Badlands CommPlex Push Notification Module
Domain: CommPlexEdge (The Hands)

Sends push notifications to team Pixel 10 phones for:
  - Qualified lead alerts (PRIMARY — fires on every QUALIFIED status)
  - Standup reminders (M W F)
  - Call completed / failed alerts
  - Campaign milestones
  - Manual review flags (Anti-Hallucination guardrail triggered)

Backends (configure one or more in .env):
  - ntfy.sh     (FREE, open source — RECOMMENDED default)
  - Pushover    ($5 one-time app purchase)
  - Firebase FCM (GCP-native)

GoF Patterns:
  - Strategy:  NotifyBackend is swappable
  - Adapter:   Each backend adapts its API to common interface
  - Observer:  NotifierModule subscribes to CommPlexAPI QUALIFIED events
  - Composite: MultiNotifier sends to all configured backends

Setup (.env):
    NTFY_TOPIC=arc-badlands-kenyon      # unique topic, keep it private
    NTFY_SERVER=https://ntfy.sh         # or self-hosted
    PUSHOVER_TOKEN=...
    PUSHOVER_USER=...
    FCM_TOKEN_KENYON=...

Android PWA / ntfy.sh Setup (fastest path — 2 min):
    1. Install "ntfy" app on each Pixel from Play Store
    2. Subscribe to topic: arc-badlands-kenyon
    3. Set NTFY_TOPIC=arc-badlands-kenyon in .env
    4. Run: python -m CommPlexEdge.modules.notifier --test
"""

from __future__ import annotations
import os
import json
import logging
import requests
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)

STATUS_STUB   = "STUB"
STATUS_ACTIVE = "ACTIVE"


# ═══════════════════════════════════════════════════════
# PRIORITY / CATEGORY CONSTANTS
# ═══════════════════════════════════════════════════════

class Priority:
    LOW    = "low"
    NORMAL = "normal"
    HIGH   = "high"
    URGENT = "urgent"   # bypasses Do Not Disturb


class Category:
    STANDUP    = "standup"
    CALL       = "call"
    CAMPAIGN   = "campaign"
    REVIEW     = "review"
    DEPLOY     = "deploy"
    ALERT      = "alert"
    QUALIFIED  = "qualified"   # NEW: Qualified lead alert


# ═══════════════════════════════════════════════════════
# ABSTRACT BACKEND — GoF Strategy
# ═══════════════════════════════════════════════════════

class NotifyBackend(ABC):
    """Abstract notification backend. GoF: Strategy."""

    @abstractmethod
    def send(self, title: str, message: str,
             priority: str = Priority.NORMAL,
             category: str = Category.ALERT,
             url: str = None,
             tags: List[str] = None) -> bool:
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    def is_configured(self) -> bool:
        return True


# ═══════════════════════════════════════════════════════
# ntfy.sh BACKEND — Recommended default
# ═══════════════════════════════════════════════════════

class NtfyBackend(NotifyBackend):
    """
    ntfy.sh push notification backend.
    GoF: Adapter — wraps ntfy HTTP API.

    No account required. Free forever. Android app on Play Store.
    One command test: curl -d "Hello" ntfy.sh/your-topic

    Priority map:
        low → 1 | normal → 3 | high → 4 | urgent → 5 (bypasses DND)
    """

    name = "ntfy"
    PRIORITY_MAP = {
        Priority.LOW:    "1",
        Priority.NORMAL: "3",
        Priority.HIGH:   "4",
        Priority.URGENT: "5",
    }

    def __init__(self):
        self.server   = os.getenv("NTFY_SERVER", "https://ntfy.sh")
        self.topic    = os.getenv("NTFY_TOPIC",  "arc-badlands")
        self.user     = os.getenv("NTFY_USER",   "")
        self.password = os.getenv("NTFY_PASS",   "")

    def is_configured(self) -> bool:
        return bool(self.topic and self.topic not in ("arc-badlands", "arc-fleet"))

    def send(self, title: str, message: str,
             priority: str = Priority.NORMAL,
             category: str = Category.ALERT,
             url: str = None,
             tags: List[str] = None) -> bool:
        headers = {
            "Title":    title,
            "Priority": self.PRIORITY_MAP.get(priority, "3"),
            "Tags":     ",".join(tags or [category]),
        }
        if url:
            headers["Click"] = url
        auth = (self.user, self.password) if (self.user and self.password) else None

        try:
            resp = requests.post(
                f"{self.server}/{self.topic}",
                data=message.encode("utf-8"),
                headers=headers,
                auth=auth,
                timeout=10,
            )
            resp.raise_for_status()
            logger.info(f"[ntfy] Sent '{title}' → topic '{self.topic}'")
            return True
        except Exception as e:
            logger.error(f"[ntfy] Failed: {e}")
            return False

    def send_to_person(self, person: str, title: str, message: str, **kwargs) -> bool:
        """Send to person-specific topic: e.g. arc-badlands-kenyon."""
        original   = self.topic
        self.topic = f"{self.topic.rstrip('-kenyon').rstrip('-charles').rstrip('-cynthia')}-{person.lower()}"
        result     = self.send(title, message, **kwargs)
        self.topic = original
        return result


# ═══════════════════════════════════════════════════════
# PUSHOVER BACKEND
# ═══════════════════════════════════════════════════════

class PushoverBackend(NotifyBackend):
    """Pushover push backend. $5 one-time. Best UX on Android. GoF: Adapter."""

    name    = "pushover"
    API_URL = "https://api.pushover.net/1/messages.json"
    PRIORITY_MAP = {
        Priority.LOW:    -1,
        Priority.NORMAL:  0,
        Priority.HIGH:    1,
        Priority.URGENT:  2,   # requires ACK, retries every 30s
    }

    def __init__(self):
        self.token = os.getenv("PUSHOVER_TOKEN", "")
        self.user  = os.getenv("PUSHOVER_USER",  "")
        self.team_keys: Dict[str, str] = {
            "kenyon":  os.getenv("PUSHOVER_USER_KENYON",  self.user),
            "charles": os.getenv("PUSHOVER_USER_CHARLES", ""),
            "cynthia": os.getenv("PUSHOVER_USER_CYNTHIA", ""),
        }

    def is_configured(self) -> bool:
        return bool(self.token and self.user)

    def send(self, title: str, message: str,
             priority: str = Priority.NORMAL,
             category: str = Category.ALERT,
             url: str = None,
             tags: List[str] = None,
             user_key: str = None) -> bool:
        if not self.is_configured():
            logger.warning("[Pushover] Not configured — skipping")
            return False
        payload = {
            "token":    self.token,
            "user":     user_key or self.user,
            "title":    title,
            "message":  message,
            "priority": self.PRIORITY_MAP.get(priority, 0),
        }
        if url:
            payload["url"] = url
        if priority == Priority.URGENT:
            payload.update({"retry": 30, "expire": 3600})
        try:
            resp = requests.post(self.API_URL, data=payload, timeout=10)
            resp.raise_for_status()
            logger.info(f"[Pushover] Sent '{title}'")
            return True
        except Exception as e:
            logger.error(f"[Pushover] Failed: {e}")
            return False


# ═══════════════════════════════════════════════════════
# FCM BACKEND — GCP Firebase Cloud Messaging
# ═══════════════════════════════════════════════════════

class FCMBackend(NotifyBackend):
    """Firebase Cloud Messaging backend. GoF: Adapter."""

    name    = "fcm"
    FCM_URL = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"

    def __init__(self):
        self.project_id = os.getenv("FIREBASE_PROJECT_ID", os.getenv("GCP_PROJECT_ID", ""))
        self.tokens: Dict[str, str] = {
            "kenyon":  os.getenv("FCM_TOKEN_KENYON",  ""),
            "charles": os.getenv("FCM_TOKEN_CHARLES", ""),
            "cynthia": os.getenv("FCM_TOKEN_CYNTHIA", ""),
        }

    def is_configured(self) -> bool:
        return bool(self.project_id and any(self.tokens.values()))

    def _get_access_token(self) -> str:
        from google.oauth2 import service_account
        import google.auth.transport.requests
        creds_path  = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "service-account.json")
        credentials = service_account.Credentials.from_service_account_file(
            creds_path,
            scopes=["https://www.googleapis.com/auth/firebase.messaging"],
        )
        credentials.refresh(google.auth.transport.requests.Request())
        return credentials.token

    def send(self, title: str, message: str,
             priority: str = Priority.NORMAL,
             category: str = Category.ALERT,
             url: str = None,
             tags: List[str] = None,
             token: str = None) -> bool:
        if not self.is_configured():
            return False
        target_token = token or self.tokens.get("kenyon", "")
        if not target_token:
            logger.error("[FCM] No device token configured")
            return False
        try:
            access_token = self._get_access_token()
            payload = {
                "message": {
                    "token": target_token,
                    "notification": {"title": title, "body": message},
                    "android": {
                        "priority": "high" if priority in (Priority.HIGH, Priority.URGENT) else "normal",
                        "notification": {"channel_id": category},
                    },
                    "data": {"category": category, "url": url or ""},
                }
            }
            resp = requests.post(
                self.FCM_URL.format(project_id=self.project_id),
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type":  "application/json",
                },
                json=payload,
                timeout=15,
            )
            resp.raise_for_status()
            logger.info(f"[FCM] Sent '{title}'")
            return True
        except Exception as e:
            logger.error(f"[FCM] Failed: {e}")
            return False


# ═══════════════════════════════════════════════════════
# MULTI-NOTIFIER — GoF Composite
# ═══════════════════════════════════════════════════════

class MultiNotifier(NotifyBackend):
    """GoF Composite — sends to all configured backends simultaneously."""

    name = "multi"

    def __init__(self, backends: List[NotifyBackend]):
        self.backends = [b for b in backends if b.is_configured()]

    def send(self, title: str, message: str, **kwargs) -> bool:
        results = [b.send(title, message, **kwargs) for b in self.backends]
        return any(results)


# ═══════════════════════════════════════════════════════
# NOTIFIER MODULE — Main Interface / Facade
# ═══════════════════════════════════════════════════════

class NotifierModule:
    """
    Main notification module. GoF: Facade over all notification backends.
    Domain: CommPlexEdge — wired to CommPlexAPI QUALIFIED events.

    Usage:
        n = NotifierModule()
        n.qualified_lead_alert("Fargo Ford", 25000.0, lead_id=42)
        n.standup_reminder()
        n.manual_review_alert("Lead #42 — price not verified in transcript")
    """

    MODULE_ID = "notify"

    def __init__(self):
        ntfy     = NtfyBackend()
        pushover = PushoverBackend()
        fcm      = FCMBackend()

        configured  = [b for b in [ntfy, pushover, fcm] if b.is_configured()]
        self._backend = (
            MultiNotifier(configured) if len(configured) > 1
            else configured[0] if configured
            else ntfy   # ntfy fallback even if topic is default (logs warning)
        )
        self.STATUS = STATUS_ACTIVE if configured else STATUS_STUB

    def _send(self, title: str, msg: str,
              priority=Priority.NORMAL, category=Category.ALERT,
              **kwargs) -> bool:
        return self._backend.send(title, msg, priority=priority,
                                  category=category, **kwargs)

    # ── Qualified Lead Alert (PRIMARY — wired to CommPlexAPI) ─────────────────

    def qualified_lead_alert(self, dealer_name: str, price: Optional[float],
                              lead_id: int = None, campaign_id: str = "mkz") -> bool:
        """
        🚨 Fire when CommPlexAPI sets a lead to QUALIFIED.
        This is the primary event that wakes Kenyon on his Pixel 10.
        """
        price_str = f"${price:,.0f}" if price else "PRICE TBD"
        lead_str  = f" (Lead #{lead_id})" if lead_id else ""
        title     = f"🚨 QUALIFIED DEAL{lead_str} — {campaign_id.upper()}"
        message   = (
            f"Dealer: {dealer_name}\n"
            f"Offer:  {price_str}\n"
            f"Action: Call back NOW to close.\n"
            f"Kenyon: (701) 870-5235"
        )
        logger.info(f"[Notifier] Qualified lead alert → {dealer_name} {price_str}")
        return self._send(
            title, message,
            priority=Priority.URGENT,
            category=Category.QUALIFIED,
            tags=["money_bag", "car", "qualified"],
        )

    # ── Manual Review Alert (Anti-Hallucination flag) ─────────────────────────

    def manual_review_alert(self, reason: str, lead_id: int = None) -> bool:
        """
        ⚠️ Fire when SluiceEngine's anti-hallucination guardrail flags a lead.
        Requires human verification before marking QUALIFIED.
        """
        lead_str = f"Lead #{lead_id} — " if lead_id else ""
        return self._send(
            f"⚠️ MANUAL REVIEW — {lead_str}Price Unverified",
            f"Reason: {reason}\nCheck transcript manually before qualifying.",
            priority=Priority.HIGH,
            category=Category.REVIEW,
            tags=["warning", "magnifying_glass", "review"],
        )

    # ── Named event senders ───────────────────────────────────────────────────

    def standup_reminder(self, message: str = None, day: str = None) -> bool:
        day = day or datetime.now().strftime("%A")
        msg = message or f"Arc Badlands standup time — {day}. Please check in."
        return self._send(
            f"📋 Standup — {day}", msg,
            priority=Priority.HIGH, category=Category.STANDUP,
            tags=["clipboard", "standup"],
        )

    def call_completed(self, call_result: Dict) -> bool:
        status     = call_result.get("status", "unknown")
        call_id    = call_result.get("call_id", "")
        transcript = call_result.get("transcript", "")[:100]
        icon       = "✅" if status == "completed" else "❌"
        return self._send(
            f"{icon} Call {status.upper()} — {call_id[:8]}",
            f"Status: {status}\nPreview: {transcript}",
            priority=Priority.NORMAL, category=Category.CALL,
            tags=["telephone", status],
        )

    def campaign_milestone(self, campaign_id: str, event: str, details: str = "") -> bool:
        return self._send(
            f"🚗 Campaign {campaign_id} — {event}",
            details or event,
            priority=Priority.NORMAL, category=Category.CAMPAIGN,
            tags=["car", "campaign"],
        )

    def alert_team(self, title: str, message: str, urgent: bool = False) -> bool:
        priority = Priority.URGENT if urgent else Priority.HIGH
        return self._send(
            f"⚠️ {title}", message,
            priority=priority, category=Category.ALERT,
            tags=["warning", "alert"],
        )

    def deploy_event(self, event: str, details: str = "") -> bool:
        return self._send(
            f"🚀 Deploy: {event}", details or event,
            priority=Priority.NORMAL, category=Category.DEPLOY,
            tags=["rocket", "deploy"],
        )

    def health_check(self) -> Dict[str, Any]:
        return {
            "module":               self.MODULE_ID,
            "status":               self.STATUS,
            "backend":              self._backend.name,
            "active":               self.STATUS == STATUS_ACTIVE,
            "ntfy_configured":      NtfyBackend().is_configured(),
            "pushover_configured":  PushoverBackend().is_configured(),
            "fcm_configured":       FCMBackend().is_configured(),
            "ntfy_topic":           os.getenv("NTFY_TOPIC", "(not set)"),
        }


# ═══════════════════════════════════════════════════════
# CLI — python -m CommPlexEdge.modules.notifier
# ═══════════════════════════════════════════════════════

def cli():
    import argparse
    parser = argparse.ArgumentParser(description="CommPlexEdge Notifier CLI")
    parser.add_argument("--test",        action="store_true", help="Send test notification")
    parser.add_argument("--standup",     action="store_true", help="Send standup reminder")
    parser.add_argument("--qualified",   action="store_true", help="Send test qualified lead alert")
    parser.add_argument("--manual",      action="store_true", help="Send test manual review alert")
    parser.add_argument("--alert",       metavar="MESSAGE",   help="Send urgent alert")
    parser.add_argument("--title",       default="Arc Badlands CommPlex")
    args = parser.parse_args()

    module = NotifierModule()
    print(f"Notifier health: {json.dumps(module.health_check(), indent=2)}")

    if args.test:
        ok = module.alert_team("CommPlexEdge Notifier Test", "Arc Badlands notifier is operational ✅", urgent=False)
        print(f"✓ Test sent: {ok}")

    elif args.standup:
        ok = module.standup_reminder()
        print(f"✓ Standup reminder sent: {ok}")

    elif args.qualified:
        ok = module.qualified_lead_alert("Test Dealer — Fargo Ford", 25000.0, lead_id=99)
        print(f"✓ Qualified lead alert sent: {ok}")

    elif args.manual:
        ok = module.manual_review_alert("Price $25,000 not found in transcript text", lead_id=99)
        print(f"✓ Manual review alert sent: {ok}")

    elif args.alert:
        ok = module.alert_team(args.title, args.alert, urgent=True)
        print(f"✓ Alert sent: {ok}")

    else:
        parser.print_help()

    if module.STATUS == STATUS_STUB:
        print("\n⚠️  Notifier in STUB mode — set NTFY_TOPIC in .env to activate.")
        print("   Quick start: export NTFY_TOPIC=arc-badlands-kenyon")


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO)
    cli()
