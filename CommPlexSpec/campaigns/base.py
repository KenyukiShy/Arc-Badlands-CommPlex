"""
CommPlexSpec/campaigns/base.py — Arc Badlands CommPlex Abstract Campaign Base
THE LAW — all campaigns across all domains must conform to this contract.

GoF Patterns:
  - Template Method:    run flow defined here; subclasses fill in content
  - Abstract Factory:  subclass provides vehicle_info, messages, contacts

SOLID:
  - SRP: campaign is a config object — modules do the sending
  - OCP: add new campaigns without touching modules
  - DIP: modules depend on BaseCampaign ABC, not concrete campaigns

Anti-Hallucination Guardrail:
  - verify_price() — static method; regex-checks reported price against raw text
  - Flags for MANUAL_REVIEW if price cannot be confirmed in source text

All campaigns:
  - Inherit BaseCampaign
  - Define SLUG (short CLI id), CAMPAIGN_ID (full id), vehicle_info, messages, contacts
  - Register automatically via CampaignRegistry
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Optional, List, Dict
from abc import ABC, abstractmethod


# ── Shared sender identity ────────────────────────────────────────────────────
# Single source of truth — all campaigns reference this

SENDER: Dict = {
    "name":              "Kenyon Jones",
    "email":             "kjonesmle@gmail.com",
    "phone":             "7018705235",
    "phone_display":     "(701) 870-5235",
    "zip":               "58523",
    "alt_name":          "Cynthia Ennis",
    "alt_phone":         "7019465731",
    "alt_phone_display": "(701) 946-5731",
}

# ── Contact lifecycle states ───────────────────────────────────────────────────

STATUS_PENDING       = "PENDING"
STATUS_SENT          = "SENT"
STATUS_FILLED        = "FILLED"
STATUS_SUBMITTED     = "SUBMITTED"
STATUS_REPLIED       = "REPLIED"
STATUS_FAILED        = "FAILED"
STATUS_SKIP          = "SKIP"

# CommPlex qualification states (used by SluiceEngine → API → Edge)
STATUS_QUALIFIED     = "QUALIFIED"
STATUS_REJECTED      = "REJECTED"
STATUS_MANUAL_REVIEW = "MANUAL_REVIEW"    # Anti-hallucination flag

ALL_STATUSES = {
    STATUS_PENDING, STATUS_SENT, STATUS_FILLED, STATUS_SUBMITTED,
    STATUS_REPLIED, STATUS_FAILED, STATUS_SKIP,
    STATUS_QUALIFIED, STATUS_REJECTED, STATUS_MANUAL_REVIEW,
}


# ── Contact dataclass ─────────────────────────────────────────────────────────

@dataclass
class Contact:
    """
    Single outreach target. Immutable identity, mutable status.

    Fields:
        name:   Display name (required)
        email:  Email address — used for 'email' method
        phone:  10-digit string — used for 'phone' / 'sms' method
        url:    Contact form URL — used for 'form' method
        tier:   Message tier key (maps to campaign.messages)
        method: 'email' | 'form' | 'phone' | 'sms'
        status: Lifecycle state (see STATUS_* constants)
        notes:  Internal operator notes
    """
    name:   str
    email:  Optional[str] = None
    phone:  Optional[str] = None
    url:    Optional[str] = None
    tier:   str           = "DEFAULT"
    method: str           = "email"
    status: str           = STATUS_PENDING
    notes:  str           = ""

    def is_reachable(self) -> bool:
        return bool(self.email or self.phone or self.url)

    def is_pending(self) -> bool:
        return self.status == STATUS_PENDING

    def channels(self) -> List[str]:
        out = []
        if self.email: out.append(f"email:{self.email}")
        if self.phone: out.append(f"phone:{self.phone}")
        if self.url:   out.append(f"form:{self.url[:40]}")
        return out

    def to_dict(self) -> Dict:
        return {
            "name":   self.name,
            "email":  self.email,
            "phone":  self.phone,
            "url":    self.url,
            "tier":   self.tier,
            "method": self.method,
            "status": self.status,
            "notes":  self.notes,
        }

    def __repr__(self):
        return (f"Contact({self.name!r} [{self.tier}/{self.method}] "
                f"status={self.status})")


# ── Abstract Campaign ─────────────────────────────────────────────────────────

class BaseCampaign(ABC):
    """
    Abstract base for all vehicle campaigns.
    GoF: Template Method — defines the structure; subclasses provide content.

    Each campaign is a self-contained config object.
    Modules (emailer, formfill, sms, phone) receive a campaign object
    and execute outreach against its contact list.
    """

    # Override in every subclass
    SLUG:        str = "base"          # CLI id: mkz, towncar, f350, jayco
    CAMPAIGN_ID: str = "BASE"          # Full id: MKZ_2016_HYBRID
    VERSION:     str = "1.0"

    SENDER: Dict = SENDER              # Shared across all campaigns

    # ── Abstract interface (must implement) ───────────────────────────────────

    @property
    @abstractmethod
    def vehicle_info(self) -> Dict:
        """
        Vehicle metadata. Recommended keys:
            display, vin, mileage, color, trim, title,
            location, asking, note, alert (optional)
        """
        ...

    @property
    @abstractmethod
    def messages(self) -> Dict[str, str]:
        """
        Tier-keyed message bodies. Must include 'DEFAULT'.
        Keys must match Contact.tier values used in contacts list.
        """
        ...

    @property
    @abstractmethod
    def contacts(self) -> List[Contact]:
        """
        Ordered contact list. Priority contacts first.
        Modules iterate this list in order.
        """
        ...

    # ── Anti-Hallucination Guardrail ──────────────────────────────────────────

    @staticmethod
    def verify_price(raw_text: str, reported_price: float) -> bool:
        """
        Anti-Hallucination Guard — THE LAW for all price verification.

        Checks that `reported_price` actually appears somewhere in `raw_text`.
        If it does NOT appear, the lead must be flagged for MANUAL_REVIEW.

        Use this before trusting any LLM-reported price.

        Args:
            raw_text:       Original transcript or email body (unmodified)
            reported_price: Price value returned by the AI classifier

        Returns:
            True  — price is verifiable in source text → proceed
            False — price NOT found in source text → FLAG for MANUAL_REVIEW

        Example:
            >>> BaseCampaign.verify_price("I'll take $25,000 for it.", 25000)
            True
            >>> BaseCampaign.verify_price("The car is in great shape.", 25000)
            False
        """
        if not raw_text or reported_price is None:
            return False

        text      = raw_text.lower()
        price_int = int(reported_price)

        # Build a set of representations to search for
        candidates = [
            str(price_int),                # 25000
            f"{price_int:,}",              # 25,000
            f"${price_int:,}",             # $25,000
            f"${price_int}",               # $25000
        ]

        # k-notation: 25k, 25.5k
        if price_int >= 1000:
            k_val = price_int / 1000
            candidates += [
                f"{k_val:.0f}k",           # 25k
                f"{k_val:.1f}k",           # 25.0k
                f"{k_val:.0f},000",        # 25,000 (via k)
            ]

        return any(c in text for c in candidates)

    @classmethod
    def flag_unverified_price(cls, raw_text: str, reported_price: float) -> str:
        """
        Convenience wrapper — returns STATUS_QUALIFIED or STATUS_MANUAL_REVIEW.
        Use in SluiceEngine or any module that receives an LLM price.
        """
        if cls.verify_price(raw_text, reported_price):
            return STATUS_QUALIFIED
        return STATUS_MANUAL_REVIEW

    # ── Concrete helpers (don't override unless needed) ───────────────────────

    @property
    def priority_contacts(self) -> List[Contact]:
        """High-priority contacts to process first. Override in subclass."""
        return []

    def get_message(self, tier: str) -> str:
        """Return message for tier; falls back to DEFAULT."""
        msgs = self.messages
        return msgs.get(tier, msgs.get("DEFAULT", ""))

    def get_subject(self, contact: Contact, prefix: str = "") -> str:
        """Build email subject line."""
        vehicle = self.vehicle_info.get("display", "Vehicle")
        return f"{prefix}Vehicle for Sale — {vehicle} | {self.SENDER['name']}"

    def pending_contacts(self, method: str = None) -> List[Contact]:
        """Return PENDING contacts, optionally filtered by method."""
        result = [c for c in self.contacts if c.is_pending()]
        if method:
            result = [c for c in result if c.method == method]
        return result

    def contacts_by_method(self) -> Dict[str, List[Contact]]:
        out: Dict[str, List[Contact]] = {}
        for c in self.contacts:
            out.setdefault(c.method, []).append(c)
        return out

    def contacts_by_tier(self) -> Dict[str, List[Contact]]:
        out: Dict[str, List[Contact]] = {}
        for c in self.contacts:
            out.setdefault(c.tier, []).append(c)
        return out

    def reset_pending(self):
        """Reset all contacts to PENDING. Use for test re-runs."""
        for c in self.contacts:
            c.status = STATUS_PENDING

    def summary(self) -> Dict:
        """Return summary dict for dashboards and CLI output."""
        all_c    = self.contacts
        info     = self.vehicle_info
        pending  = sum(1 for c in all_c if c.status == STATUS_PENDING)
        sent     = sum(1 for c in all_c if c.status in (STATUS_SENT, STATUS_FILLED, STATUS_SUBMITTED))
        replied  = sum(1 for c in all_c if c.status == STATUS_REPLIED)
        failed   = sum(1 for c in all_c if c.status == STATUS_FAILED)
        qualified = sum(1 for c in all_c if c.status == STATUS_QUALIFIED)

        return {
            "slug":           self.SLUG,
            "campaign_id":    self.CAMPAIGN_ID,
            "version":        self.VERSION,
            "vehicle":        info.get("display", self.CAMPAIGN_ID),
            "vin":            info.get("vin", ""),
            "location":       info.get("location", ""),
            "asking":         info.get("asking", ""),
            "title":          info.get("title", ""),
            "total_contacts": len(all_c),
            "pending":        pending,
            "sent":           sent,
            "replied":        replied,
            "failed":         failed,
            "qualified":      qualified,
            "alert":          info.get("alert"),
            "note":           info.get("note"),
        }

    def __repr__(self):
        s = self.summary()
        return (f"<{self.__class__.__name__} id={self.CAMPAIGN_ID} "
                f"contacts={s['total_contacts']} pending={s['pending']}>")


# ── Campaign Registry ─────────────────────────────────────────────────────────

class CampaignRegistry:
    """
    GoF: Registry / Singleton — auto-collects all BaseCampaign subclasses.
    Import and call get() to retrieve any campaign by slug.
    """
    _registry: Dict[str, type] = {}

    @classmethod
    def register(cls, campaign_cls: type):
        slug = getattr(campaign_cls, "SLUG", None)
        if slug and slug != "base":
            cls._registry[slug] = campaign_cls

    @classmethod
    def get(cls, slug: str) -> Optional[BaseCampaign]:
        klass = cls._registry.get(slug)
        return klass() if klass else None

    @classmethod
    def all_slugs(cls) -> List[str]:
        return list(cls._registry.keys())


def __init_subclass_hook__(cls, **kwargs):
    """Auto-register any BaseCampaign subclass on definition."""
    super(BaseCampaign, cls).__init_subclass__(**kwargs)
    CampaignRegistry.register(cls)

BaseCampaign.__init_subclass__ = classmethod(
    lambda cls, **kwargs: CampaignRegistry.register(cls)
)


# ── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("CommPlexSpec — BaseCampaign Anti-Hallucination Guardrail TEST")
    print("=" * 60)

    test_cases = [
        ("Price in text (number)",       "I'll take 25000 for it.",           25000,  True),
        ("Price in text ($XX,XXX)",       "My ask is $25,000 firm.",           25000,  True),
        ("Price in text (k-notation)",    "Asking 25k, take it or leave it.",  25000,  True),
        ("Price NOT in text (hallucin.)", "The car is in great shape.",        25000,  False),
        ("Price wrong amount",            "I want $30,000 for it.",            25000,  False),
        ("Edge: None transcript",         "",                                  25000,  False),
    ]

    all_pass = True
    for label, text, price, expected in test_cases:
        result = BaseCampaign.verify_price(text, price)
        status = "✅ PASS" if result == expected else "❌ FAIL"
        if result != expected:
            all_pass = False
        print(f"  {status} | {label}")
        print(f"         text={text[:50]!r} price={price} → {result} (expected {expected})")

    print()
    if all_pass:
        print("✅ Checkpoint: verify_price() anti-hallucination guardrail — ALL PASS")
    else:
        print("❌ Some tests failed — check guardrail logic")
