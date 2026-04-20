"""
CommPlexCore/campaigns/registry.py — Campaign Registry
Domain: CommPlexCore (The Brain)

GoF: Registry + Singleton.
Maps SLUG → campaign class. Single import point for all campaigns.

Usage:
    from CommPlexCore.campaigns.registry import CampaignRegistry
    campaign = CampaignRegistry.get("mkz")
    all_campaigns = CampaignRegistry.all()

DESIGN LAW: All 4 campaigns are registered here. No campaign logic lives here —
this is a pure routing table. CommPlexSpec.CampaignRegistry handles the ABC side;
this module handles the concrete-class routing for CommPlexCore consumers.
"""

from __future__ import annotations
import logging
from typing import Dict, List, Optional, Type

logger = logging.getLogger(__name__)

# ── Import order: each module registers on import ────────────────────────────
# We import here to guarantee all are available. Lazy imports used to avoid
# circular dependency during testing.

def _load_campaigns() -> Dict[str, Type]:
    """Lazy-load all campaign classes. Returns SLUG → class mapping."""
    registry: Dict[str, Type] = {}
    try:
        from CommPlexCore.campaigns.mkz import MKZCampaign
        registry["mkz"] = MKZCampaign
    except ImportError as e:
        logger.warning(f"[Registry] MKZ not loaded: {e}")

    try:
        from CommPlexCore.campaigns.towncar import TownCarCampaign
        registry["towncar"] = TownCarCampaign
    except ImportError as e:
        logger.warning(f"[Registry] TownCar not loaded: {e}")

    try:
        from CommPlexCore.campaigns.f350 import F350Campaign
        registry["f350"] = F350Campaign
    except ImportError as e:
        logger.warning(f"[Registry] F350 not loaded: {e}")

    try:
        from CommPlexCore.campaigns.jayco import JaycoCampaign
        registry["jayco"] = JaycoCampaign
    except ImportError as e:
        logger.warning(f"[Registry] Jayco not loaded: {e}")

    return registry


class CampaignRegistry:
    """
    GoF: Registry / Singleton.
    Provides a single access point for all campaign classes and instances.

    REGISTRY_MAP: SLUG → campaign class (not instance — each call creates fresh)
    Use get()      for a fresh instance (stateful — contacts reset to PENDING)
    Use instance() for the module-level singleton (shared state — use carefully)
    """

    _registry: Optional[Dict[str, Type]] = None
    _instances: Dict[str, object] = {}

    @classmethod
    def _ensure_loaded(cls):
        if cls._registry is None:
            cls._registry = _load_campaigns()
            logger.info(f"[Registry] Loaded {len(cls._registry)} campaigns: {list(cls._registry.keys())}")

    @classmethod
    def get(cls, slug: str):
        """
        Return a fresh campaign instance by slug.
        Always returns a new instance — contacts start at PENDING.

        Args:
            slug: "mkz" | "towncar" | "f350" | "jayco"

        Returns:
            BaseCampaign subclass instance, or None if slug not found.
        """
        cls._ensure_loaded()
        klass = cls._registry.get(slug)
        if klass is None:
            logger.warning(f"[Registry] Unknown slug: {slug!r}. Available: {cls.all_slugs()}")
            return None
        return klass()

    @classmethod
    def instance(cls, slug: str):
        """
        Return the module-level singleton for a campaign slug.
        Creates once, reuses. State (contact statuses) persists between calls.

        Use for: long-running processes tracking send state per contact.
        Avoid for: test suites (use get() for isolation).
        """
        cls._ensure_loaded()
        if slug not in cls._instances:
            klass = cls._registry.get(slug)
            if klass is None:
                return None
            # Delegate to each module's get_campaign() singleton
            module_map = {
                "mkz":     "CommPlexCore.campaigns.mkz",
                "towncar": "CommPlexCore.campaigns.towncar",
                "f350":    "CommPlexCore.campaigns.f350",
                "jayco":   "CommPlexCore.campaigns.jayco",
            }
            try:
                import importlib
                mod = importlib.import_module(module_map[slug])
                cls._instances[slug] = mod.get_campaign()
            except (ImportError, AttributeError):
                cls._instances[slug] = klass()
        return cls._instances[slug]

    @classmethod
    def all(cls) -> List:
        """Return fresh instances of all registered campaigns."""
        cls._ensure_loaded()
        return [klass() for klass in cls._registry.values()]

    @classmethod
    def all_slugs(cls) -> List[str]:
        cls._ensure_loaded()
        return list(cls._registry.keys())

    @classmethod
    def all_instances(cls) -> Dict[str, object]:
        """Return singleton instances for all campaigns."""
        cls._ensure_loaded()
        return {slug: cls.instance(slug) for slug in cls._registry.keys()}

    @classmethod
    def summaries(cls) -> List[Dict]:
        """Return summary dicts for all campaigns — for dashboard and CLI."""
        return [c.summary() for c in cls.all()]

    @classmethod
    def reset(cls):
        """Reset the registry (clear cache). Used in testing."""
        cls._registry  = None
        cls._instances = {}

    @classmethod
    def status(cls) -> Dict:
        """Registry health — useful for /health endpoint."""
        cls._ensure_loaded()
        return {
            "registered": cls.all_slugs(),
            "count":      len(cls._registry),
            "loaded":     cls._registry is not None,
        }


# ── Convenience aliases ───────────────────────────────────────────────────────

def get_campaign(slug: str):
    """Top-level convenience: CampaignRegistry.get(slug)."""
    return CampaignRegistry.get(slug)

def get_all_campaigns() -> List:
    """Top-level convenience: CampaignRegistry.all()."""
    return CampaignRegistry.all()


if __name__ == "__main__":
    import json, logging
    logging.basicConfig(level=logging.INFO)

    print("=" * 60)
    print("CommPlexCore — CampaignRegistry Test")
    print("=" * 60)

    print(f"\nRegistry status: {CampaignRegistry.status()}")
    print(f"\nAvailable slugs: {CampaignRegistry.all_slugs()}")

    for slug in CampaignRegistry.all_slugs():
        c = CampaignRegistry.get(slug)
        if c:
            s = c.summary()
            print(f"\n  [{slug}] {s['vehicle']}")
            print(f"    VIN: {s['vin']} | Contacts: {s['total_contacts']} | Asking: {s['asking']}")
            if s.get("alert"):
                print(f"    ⚠  ALERT: {s['alert']}")

    print(f"\n✅ Registry checkpoint: {len(CampaignRegistry.all_slugs())} campaigns loaded.")
