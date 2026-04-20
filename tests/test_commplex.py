"""
tests/test_commplex.py — Arc Badlands CommPlex Full Test Suite
Domain: Cross-domain (CommPlexSpec + CommPlexCore + CommPlexAPI + CommPlexEdge)

Test categories:
    1.  CommPlexSpec — BaseCampaign ABCs, verify_price() anti-hallucination
    2.  CommPlexSpec — CampaignRegistry (abstract)
    3.  CommPlexCore — MKZCampaign sluice integration
    4.  CommPlexCore — TownCarCampaign
    5.  CommPlexCore — F350Campaign
    6.  CommPlexCore — JaycoCampaign
    7.  CommPlexCore — CampaignRegistry (concrete)
    8.  CommPlexCore — SluiceEngine (STUB mode)
    9.  CommPlexCore — GeminiFlashClassifier (STUB mode)
    10. CommPlexCore — Secrets module (ENV fallback)
    11. CommPlexAPI  — FastAPI gateway endpoints (httpx test client)
    12. CommPlexAPI  — Lead model + DB lifecycle
    13. CommPlexEdge — Notifier health + STUB mode
    14. Integration  — Campaign → Sluice → API → Notifier (dry-run, all STUB)
    15. Smoke tests  — Import all CommPlex modules cleanly

Run with:
    python -m pytest tests/test_commplex.py -v
    python -m pytest tests/test_commplex.py -v -k "sluice"
    python -m pytest tests/test_commplex.py -v -k "integration"
"""

import os
import sys
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ── Path setup ────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Set required env vars before any CommPlex import
os.environ.setdefault("VERTEX_STATUS",         "STUB")
os.environ.setdefault("DRY_RUN",               "true")
os.environ.setdefault("SLUICE_PRICE_STANDARD", "28500")
os.environ.setdefault("SLUICE_PRICE_AGGRESSIVE","24000")
os.environ.setdefault("SLUICE_MIN_YEAR",        "2020")
os.environ.setdefault("GCP_PROJECT_ID",         "commplex-493805")


# ══════════════════════════════════════════════════════════════════════════════
# 1. CommPlexSpec — BaseCampaign ABCs + Contact
# ══════════════════════════════════════════════════════════════════════════════

class TestCommPlexSpecBase:
    """Verify CommPlexSpec ABCs, Contact dataclass, and anti-hallucination guard."""

    @pytest.fixture
    def base_module(self):
        from CommPlexSpec.campaigns.base import (
            BaseCampaign, Contact, SENDER,
            STATUS_PENDING, STATUS_QUALIFIED, STATUS_MANUAL_REVIEW,
        )
        return dict(BaseCampaign=BaseCampaign, Contact=Contact, SENDER=SENDER,
                    STATUS_PENDING=STATUS_PENDING, STATUS_QUALIFIED=STATUS_QUALIFIED,
                    STATUS_MANUAL_REVIEW=STATUS_MANUAL_REVIEW)

    def test_contact_defaults(self, base_module):
        c = base_module["Contact"](name="Test Dealer")
        assert c.name == "Test Dealer"
        assert c.status == base_module["STATUS_PENDING"]
        assert c.tier == "DEFAULT"
        assert c.method == "email"
        assert c.email is None

    def test_contact_is_reachable_email(self, base_module):
        c = base_module["Contact"](name="X", email="x@example.com")
        assert c.is_reachable()

    def test_contact_is_reachable_phone(self, base_module):
        c = base_module["Contact"](name="X", phone="7015551234")
        assert c.is_reachable()

    def test_contact_is_reachable_url(self, base_module):
        c = base_module["Contact"](name="X", url="https://example.com/contact")
        assert c.is_reachable()

    def test_contact_not_reachable(self, base_module):
        c = base_module["Contact"](name="Ghost")
        assert not c.is_reachable()

    def test_contact_channels(self, base_module):
        c = base_module["Contact"](name="X", email="x@y.com", phone="7015551234")
        channels = c.channels()
        assert any("email" in ch for ch in channels)
        assert any("phone" in ch for ch in channels)

    def test_contact_to_dict_keys(self, base_module):
        c = base_module["Contact"](name="Test", email="t@t.com")
        d = c.to_dict()
        for key in ("name", "email", "phone", "url", "tier", "method", "status", "notes"):
            assert key in d

    def test_sender_identity_present(self, base_module):
        s = base_module["SENDER"]
        assert s["email"] == "kjonesmle@gmail.com"
        assert s["name"]  == "Kenyon Jones"
        assert s["phone"] == "7018705235"

    # ── verify_price anti-hallucination ──────────────────────────────────────

    def test_verify_price_plain_number(self, base_module):
        BC = base_module["BaseCampaign"]
        assert BC.verify_price("I'll take 25000 for it.", 25000) is True

    def test_verify_price_formatted(self, base_module):
        BC = base_module["BaseCampaign"]
        assert BC.verify_price("My ask is $25,000 firm.", 25000) is True

    def test_verify_price_k_notation(self, base_module):
        BC = base_module["BaseCampaign"]
        assert BC.verify_price("Asking 25k, take it or leave it.", 25000) is True

    def test_verify_price_hallucination(self, base_module):
        BC = base_module["BaseCampaign"]
        assert BC.verify_price("The car is in great shape.", 25000) is False

    def test_verify_price_wrong_amount(self, base_module):
        BC = base_module["BaseCampaign"]
        assert BC.verify_price("I want $30,000 for it.", 25000) is False

    def test_verify_price_empty_text(self, base_module):
        BC = base_module["BaseCampaign"]
        assert BC.verify_price("", 25000) is False

    def test_flag_unverified_price_qualified(self, base_module):
        BC = base_module["BaseCampaign"]
        status = BC.flag_unverified_price("Price is $25,000.", 25000)
        assert status == base_module["STATUS_QUALIFIED"]

    def test_flag_unverified_price_manual_review(self, base_module):
        BC = base_module["BaseCampaign"]
        status = BC.flag_unverified_price("No price here.", 25000)
        assert status == base_module["STATUS_MANUAL_REVIEW"]


# ══════════════════════════════════════════════════════════════════════════════
# 2. CommPlexCore — MKZ Campaign
# ══════════════════════════════════════════════════════════════════════════════

class TestMKZCampaign:
    """MKZ campaign — contacts, messages, Sluice integration, anti-hallucination."""

    @pytest.fixture
    def campaign(self):
        from CommPlexCore.campaigns.mkz import MKZCampaign
        return MKZCampaign()

    def test_slug_and_id(self, campaign):
        assert campaign.SLUG        == "mkz"
        assert campaign.CAMPAIGN_ID == "MKZ_2016_HYBRID"

    def test_vehicle_info_vin(self, campaign):
        assert campaign.vehicle_info["vin"] == "3LN6L2LUXGR630397"

    def test_luckys_is_priority_and_first(self, campaign):
        assert "Lucky" in campaign.priority_contacts[0].name
        assert "Lucky" in campaign.contacts[0].name

    def test_all_messages_present(self, campaign):
        msgs = campaign.messages
        for tier in ("LUCKY_OFFER", "TIER1_INSTANT", "TIER3_LOCAL", "DEFAULT"):
            assert tier in msgs
            assert len(msgs[tier]) > 100

    def test_get_message_fallback(self, campaign):
        msg = campaign.get_message("NONEXISTENT_TIER")
        assert len(msg) > 100

    def test_contacts_all_pending(self, campaign):
        assert all(c.status == "PENDING" for c in campaign.contacts)

    def test_contacts_all_reachable(self, campaign):
        assert all(c.is_reachable() for c in campaign.contacts)

    def test_summary_structure(self, campaign):
        s = campaign.summary()
        assert s["campaign_id"] == "MKZ_2016_HYBRID"
        assert s["total_contacts"] > 0
        assert s["pending"] == s["total_contacts"]

    def test_reset_pending(self, campaign):
        campaign.contacts[0].status = "SENT"
        campaign.reset_pending()
        assert all(c.status == "PENDING" for c in campaign.contacts)

    def test_qualify_inbound_stub(self, campaign):
        result = campaign.qualify_inbound(
            "I have a 2021 MKZ for $25,000.", "Test Dealer"
        )
        assert "status" in result

    def test_qualify_inbound_hallucination_flag(self, campaign):
        # Price not in transcript → MANUAL_REVIEW
        result = campaign.qualify_inbound("I have a 2021 MKZ in great condition.", "Test Dealer")
        # STUB mode: no price found → PENDING or REJECTED, not QUALIFIED
        assert result.get("status") != "QUALIFIED"


# ══════════════════════════════════════════════════════════════════════════════
# 3. CommPlexCore — TownCar Campaign
# ══════════════════════════════════════════════════════════════════════════════

class TestTownCarCampaign:
    @pytest.fixture
    def campaign(self):
        from CommPlexCore.campaigns.towncar import TownCarCampaign
        return TownCarCampaign()

    def test_slug_and_id(self, campaign):
        assert campaign.SLUG        == "towncar"
        assert campaign.CAMPAIGN_ID == "TOWNCAR_1988_SIGNATURE"

    def test_vin_correct(self, campaign):
        assert campaign.vehicle_info["vin"] == "1LNBM82FXJY779113"

    def test_bat_partner_is_priority(self, campaign):
        names = [c.name for c in campaign.priority_contacts]
        assert any("BaT" in n for n in names)

    def test_default_message_present(self, campaign):
        msg = campaign.get_message("DEFAULT")
        assert len(msg) > 100 and "Town Car" in msg

    def test_contacts_reachable(self, campaign):
        reachable = [c for c in campaign.contacts if c.is_reachable()]
        assert len(reachable) == len(campaign.contacts)

    def test_summary_valid(self, campaign):
        s = campaign.summary()
        assert s["total_contacts"] > 0


# ══════════════════════════════════════════════════════════════════════════════
# 4. CommPlexCore — F350 Campaign
# ══════════════════════════════════════════════════════════════════════════════

class TestF350Campaign:
    @pytest.fixture
    def campaign(self):
        from CommPlexCore.campaigns.f350 import F350Campaign
        return F350Campaign()

    def test_slug_and_id(self, campaign):
        assert campaign.SLUG        == "f350"
        assert campaign.CAMPAIGN_ID == "F350_2006_KING_RANCH"

    def test_vin_correct(self, campaign):
        assert campaign.vehicle_info["vin"] == "1FTWW31Y86EA12357"

    def test_bat_unicorn_tier_present(self, campaign):
        assert "BAT_UNICORN" in campaign.messages

    def test_priority_contacts_have_bat(self, campaign):
        names = [c.name for c in campaign.priority_contacts]
        assert any("BaT" in n for n in names)

    def test_reserve_price_in_info(self, campaign):
        assert campaign.vehicle_info["reserve"] == "$22,000"

    def test_summary_valid(self, campaign):
        s = campaign.summary()
        assert s["vin"] == "1FTWW31Y86EA12357"


# ══════════════════════════════════════════════════════════════════════════════
# 5. CommPlexCore — Jayco Campaign
# ══════════════════════════════════════════════════════════════════════════════

class TestJaycoCampaign:
    @pytest.fixture
    def campaign(self):
        from CommPlexCore.campaigns.jayco import JaycoCampaign
        return JaycoCampaign()

    def test_slug_and_id(self, campaign):
        assert campaign.SLUG        == "jayco"
        assert campaign.CAMPAIGN_ID == "JAYCO_2017_EAGLE_HT"

    def test_vin_correct(self, campaign):
        assert campaign.vehicle_info["vin"] == "1UJCJ0BPXH1P20237"

    def test_bat_note_in_info(self, campaign):
        note = campaign.vehicle_info.get("note", "")
        assert "BaT" in note and "5th wheel" in note.lower()

    def test_corral_sales_is_first_priority(self, campaign):
        assert "Corral" in campaign.priority_contacts[0].name

    def test_nd_cold_message_present(self, campaign):
        msg = campaign.get_message("ND_COLD")
        assert "Climate Shield" in msg

    def test_ga_title_in_info(self, campaign):
        assert campaign.vehicle_info.get("ga_title") == "770175206127980"


# ══════════════════════════════════════════════════════════════════════════════
# 6. CommPlexCore — CampaignRegistry
# ══════════════════════════════════════════════════════════════════════════════

class TestCampaignRegistry:
    def setup_method(self):
        """Reset registry between tests for isolation."""
        from CommPlexCore.campaigns.registry import CampaignRegistry
        CampaignRegistry.reset()

    def test_all_slugs_present(self):
        from CommPlexCore.campaigns.registry import CampaignRegistry
        slugs = CampaignRegistry.all_slugs()
        for expected in ("mkz", "towncar", "f350", "jayco"):
            assert expected in slugs

    def test_get_returns_fresh_instance(self):
        from CommPlexCore.campaigns.registry import CampaignRegistry
        a = CampaignRegistry.get("mkz")
        b = CampaignRegistry.get("mkz")
        assert a is not b  # Fresh instances, not same object

    def test_get_unknown_slug_returns_none(self):
        from CommPlexCore.campaigns.registry import CampaignRegistry
        assert CampaignRegistry.get("unknown_slug") is None

    def test_all_returns_four_campaigns(self):
        from CommPlexCore.campaigns.registry import CampaignRegistry
        all_c = CampaignRegistry.all()
        assert len(all_c) == 4

    def test_summaries_returns_list_of_dicts(self):
        from CommPlexCore.campaigns.registry import CampaignRegistry
        summaries = CampaignRegistry.summaries()
        assert len(summaries) == 4
        for s in summaries:
            assert "campaign_id" in s
            assert "vehicle" in s
            assert "total_contacts" in s

    def test_status_shows_loaded(self):
        from CommPlexCore.campaigns.registry import CampaignRegistry
        _ = CampaignRegistry.all_slugs()
        status = CampaignRegistry.status()
        assert status["loaded"] is True
        assert status["count"] == 4


# ══════════════════════════════════════════════════════════════════════════════
# 7. CommPlexCore — SluiceEngine (STUB mode)
# ══════════════════════════════════════════════════════════════════════════════

class TestSluiceEngine:
    @pytest.fixture
    def sluice(self):
        from CommPlexCore.gcp.vertex import SluiceEngine
        return SluiceEngine(mode="standard")

    @pytest.fixture
    def sluice_aggressive(self):
        from CommPlexCore.gcp.vertex import SluiceEngine
        return SluiceEngine(mode="aggressive")

    def test_qualify_passes_all_filters(self, sluice):
        result = sluice.qualify(
            {"price_detected": 25000, "vehicle_year": 2021, "reasoning": "test"},
            "I have a 2021 MKZ for $25,000."
        )
        assert result.qualified is True
        assert result.manual_review is False

    def test_reject_price_over_floor(self, sluice):
        result = sluice.qualify(
            {"price_detected": 32000, "vehicle_year": 2021, "reasoning": "test"},
            "I want $32,000 for my 2022 Lincoln."
        )
        assert result.qualified is False

    def test_reject_year_too_old(self, sluice):
        result = sluice.qualify(
            {"price_detected": 22000, "vehicle_year": 2018, "reasoning": "test"},
            "This is a 2018 model, asking $22,000."
        )
        assert result.qualified is False

    def test_manual_review_price_not_in_text(self, sluice):
        # Price reported by AI but NOT in the transcript text
        result = sluice.qualify(
            {"price_detected": 25000, "vehicle_year": 2021, "reasoning": "test"},
            "I have a 2021 MKZ in excellent condition."
        )
        assert result.manual_review is True
        assert result.qualified is False

    def test_reject_no_price(self, sluice):
        result = sluice.qualify(
            {"price_detected": None, "vehicle_year": 2021, "reasoning": "test"},
            "I have a 2021 Lincoln, let's discuss price."
        )
        assert result.qualified is False

    def test_aggressive_floor_lower(self, sluice_aggressive):
        # $23,500 — rejected by standard, accepted by aggressive
        result = sluice_aggressive.qualify(
            {"price_detected": 23500, "vehicle_year": 2021, "reasoning": "test"},
            "I can do $23,500 for the 2021 Lincoln."
        )
        assert result.qualified is True

    def test_result_has_all_fields(self, sluice):
        result = sluice.qualify(
            {"price_detected": 25000, "vehicle_year": 2021, "reasoning": "test"},
            "Price $25,000 for 2021 MKZ."
        )
        d = result.to_dict()
        for key in ("qualified", "price_detected", "vehicle_year", "reasoning",
                    "price_floor", "sluice_mode", "manual_review"):
            assert key in d


# ══════════════════════════════════════════════════════════════════════════════
# 8. CommPlexCore — GeminiFlashClassifier (STUB mode)
# ══════════════════════════════════════════════════════════════════════════════

class TestGeminiFlashClassifier:
    @pytest.fixture
    def clf(self):
        from CommPlexCore.gcp.vertex import GeminiFlashClassifier
        return GeminiFlashClassifier(sluice_mode="standard")

    def test_health_returns_dict(self, clf):
        h = clf.health()
        assert "status" in h
        assert h["status"] == "STUB"

    def test_classify_lead_qualifies(self, clf):
        result = clf.classify_lead("I have a 2021 MKZ for $25,000.")
        assert result.price_detected == 25000.0
        assert result.vehicle_year   == 2021
        assert result.qualified is True

    def test_classify_lead_rejects_price(self, clf):
        result = clf.classify_lead("I want $35,000 for my 2022 Lincoln.")
        assert result.qualified is False

    def test_classify_lead_rejects_year(self, clf):
        result = clf.classify_lead("This is a 2018 MKZ, asking $22,000.")
        assert result.qualified is False

    def test_classify_lead_no_price(self, clf):
        result = clf.classify_lead("I have a 2021 Lincoln, call me.")
        assert result.qualified is False

    def test_classify_lead_k_notation(self, clf):
        result = clf.classify_lead("Looking for 25k for my 2021 MKZ.")
        assert result.price_detected == 25000.0
        assert result.qualified is True

    def test_classify_dealer_stub(self, clf):
        tier = clf.classify_dealer("https://www.peddle.com/sell-car")
        assert tier == "DEFAULT"

    def test_suggest_followup_stub(self, clf):
        reply = clf.suggest_followup("Original message", "Dealer reply")
        assert isinstance(reply, str)


# ══════════════════════════════════════════════════════════════════════════════
# 9. CommPlexCore — Secrets module (ENV fallback)
# ══════════════════════════════════════════════════════════════════════════════

class TestSecretsModule:
    def test_get_secret_returns_env_fallback(self):
        os.environ["_TEST_SECRET_XYZ"] = "test_value_123"
        from CommPlexCore.gcp.secrets import get_secret, invalidate_cache
        invalidate_cache("_TEST_SECRET_XYZ")
        val = get_secret("_TEST_SECRET_XYZ")
        assert val == "test_value_123"
        del os.environ["_TEST_SECRET_XYZ"]

    def test_get_secret_missing_returns_empty(self):
        from CommPlexCore.gcp.secrets import get_secret, invalidate_cache
        invalidate_cache("_DEFINITELY_MISSING_SECRET_ABC")
        val = get_secret("_DEFINITELY_MISSING_SECRET_ABC")
        assert val == ""

    def test_require_secret_raises_on_missing(self):
        from CommPlexCore.gcp.secrets import require_secret
        with pytest.raises(ValueError, match="missing or still has placeholder"):
            require_secret("_DEFINITELY_MISSING_SECRET_ABC_REQUIRE")

    def test_require_secret_raises_on_placeholder(self):
        os.environ["_TEST_PLACEHOLDER"] = "REPLACE_WITH_REAL_VALUE"
        from CommPlexCore.gcp.secrets import require_secret, invalidate_cache
        invalidate_cache("_TEST_PLACEHOLDER")
        with pytest.raises(ValueError):
            require_secret("_TEST_PLACEHOLDER")
        del os.environ["_TEST_PLACEHOLDER"]

    def test_health_returns_dict(self):
        from CommPlexCore.gcp.secrets import health
        h = health()
        assert "mode" in h
        assert "project" in h
        assert h["mode"] in ("GCP", "ENV")

    def test_cache_invalidate(self):
        os.environ["_TEST_CACHE_SECRET"] = "cached_val"
        from CommPlexCore.gcp.secrets import get_secret, invalidate_cache
        get_secret("_TEST_CACHE_SECRET")          # populate cache
        invalidate_cache("_TEST_CACHE_SECRET")    # invalidate
        val2 = get_secret("_TEST_CACHE_SECRET")   # re-fetch from env
        assert val2 == "cached_val"
        del os.environ["_TEST_CACHE_SECRET"]

    def test_get_secret_batch(self):
        os.environ["_BATCH_A"] = "val_a"
        os.environ["_BATCH_B"] = "val_b"
        from CommPlexCore.gcp.secrets import get_secret_batch, invalidate_cache
        invalidate_cache("_BATCH_A"); invalidate_cache("_BATCH_B")
        result = get_secret_batch(["_BATCH_A", "_BATCH_B", "_BATCH_MISSING"])
        assert result["_BATCH_A"]       == "val_a"
        assert result["_BATCH_B"]       == "val_b"
        assert result["_BATCH_MISSING"] == ""
        del os.environ["_BATCH_A"]; del os.environ["_BATCH_B"]


# ══════════════════════════════════════════════════════════════════════════════
# 10. CommPlexEdge — Notifier STUB mode
# ══════════════════════════════════════════════════════════════════════════════

class TestNotifierModule:
    @pytest.fixture
    def notifier(self):
        # Ensure no real NTFY_TOPIC is set so we get STUB
        original = os.environ.pop("NTFY_TOPIC", None)
        from CommPlexEdge.modules.notifier import NotifierModule
        n = NotifierModule()
        if original:
            os.environ["NTFY_TOPIC"] = original
        return n

    def test_health_returns_dict(self, notifier):
        h = notifier.health_check()
        assert "module" in h
        assert "backend" in h

    def test_qualified_lead_alert_runs(self, notifier):
        with patch.object(notifier._backend, "send", return_value=True) as mock_send:
            result = notifier.qualified_lead_alert("Test Dealer", 25000.0, lead_id=1)
            assert mock_send.called

    def test_manual_review_alert_runs(self, notifier):
        with patch.object(notifier._backend, "send", return_value=True) as mock_send:
            result = notifier.manual_review_alert("Price not in transcript", lead_id=42)
            assert mock_send.called

    def test_ntfy_backend_not_configured_without_topic(self):
        from CommPlexEdge.modules.notifier import NtfyBackend
        original = os.environ.pop("NTFY_TOPIC", None)
        try:
            b = NtfyBackend()
            b.topic = "arc-badlands"  # default topic = not configured
            assert not b.is_configured()
        finally:
            if original:
                os.environ["NTFY_TOPIC"] = original


# ══════════════════════════════════════════════════════════════════════════════
# 11. CommPlexAPI — FastAPI Gateway (httpx test client)
# ══════════════════════════════════════════════════════════════════════════════

class TestCommPlexAPIGateway:
    @pytest.fixture
    def client(self):
        try:
            from fastapi.testclient import TestClient
            from CommPlexAPI.server.main import app
            return TestClient(app)
        except ImportError as e:
            pytest.skip(f"CommPlexAPI not importable: {e}")

    def test_health_endpoint(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["domain"] == "CommPlexAPI"

    def test_bland_webhook_voicemail_skipped(self, client):
        r = client.post("/webhook/bland", json={
            "call_id": "test-001", "status": "voicemail",
            "transcript": "", "campaign_id": "mkz"
        })
        assert r.status_code == 200
        assert r.json()["action"] == "skipped"

    def test_bland_webhook_no_transcript_skipped(self, client):
        r = client.post("/webhook/bland", json={
            "call_id": "test-002", "status": "completed",
            "transcript": "", "campaign_id": "mkz"
        })
        assert r.status_code == 200
        assert r.json()["action"] == "skipped"

    def test_bland_webhook_completed_returns_lead_id(self, client):
        r = client.post("/webhook/bland", json={
            "call_id":      "test-003",
            "status":       "completed",
            "transcript":   "I have a 2021 MKZ for $25,000.",
            "dealer_name":  "Test Dealer",
            "dealer_phone": "7015551234",
            "campaign_id":  "mkz",
        })
        assert r.status_code == 200
        data = r.json()
        assert "lead_id" in data

    def test_list_leads_returns_list(self, client):
        r = client.get("/leads")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_list_leads_invalid_status_returns_400(self, client):
        r = client.get("/leads?status=INVALID_STATUS_XYZ")
        assert r.status_code == 400

    def test_get_nonexistent_lead_returns_404(self, client):
        r = client.get("/leads/999999")
        assert r.status_code == 404

    def test_campaigns_endpoint_returns_list(self, client):
        r = client.get("/campaigns")
        assert r.status_code == 200
        assert "campaigns" in r.json()

    def test_run_campaign_dry_run(self, client):
        r = client.post("/campaigns/mkz/run", json={"dry_run": True, "module": "email"})
        assert r.status_code == 200
        data = r.json()
        assert data["dry_run"] is True


# ══════════════════════════════════════════════════════════════════════════════
# 12. CommPlexAPI — Lead model + DB
# ══════════════════════════════════════════════════════════════════════════════

class TestCommPlexAPIModels:
    @pytest.fixture(autouse=True)
    def setup_test_db(self, tmp_path):
        os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path}/test.db"
        try:
            from CommPlexAPI.models import init_db, Lead, LeadStatus, SessionLocal
            init_db()
            self.SessionLocal = SessionLocal
            self.Lead         = Lead
            self.LeadStatus   = LeadStatus
        except ImportError as e:
            pytest.skip(f"CommPlexAPI models not importable: {e}")

    def test_create_qualified_lead(self):
        db = self.SessionLocal()
        lead = self.Lead(
            dealer_name="Fargo Ford",
            dealer_phone="7015551234",
            price=25000.0,
            vehicle_year=2021,
            status=self.LeadStatus.QUALIFIED,
            campaign_id="mkz",
            raw_transcript="I have a 2021 MKZ for $25,000.",
        )
        db.add(lead); db.commit(); db.refresh(lead)
        assert lead.id is not None
        assert lead.status == self.LeadStatus.QUALIFIED
        db.close()

    def test_list_leads_filter_by_status(self):
        db = self.SessionLocal()
        for i, status in enumerate([self.LeadStatus.QUALIFIED, self.LeadStatus.REJECTED]):
            db.add(self.Lead(
                dealer_name=f"Dealer {i}", status=status, campaign_id="mkz"
            ))
        db.commit()
        qualified = db.query(self.Lead).filter(
            self.Lead.status == self.LeadStatus.QUALIFIED
        ).all()
        assert len(qualified) >= 1
        db.close()

    def test_lead_to_dict(self):
        db = self.SessionLocal()
        lead = self.Lead(dealer_name="X", status=self.LeadStatus.PENDING, campaign_id="mkz")
        db.add(lead); db.commit(); db.refresh(lead)
        d = lead.to_dict()
        assert d["dealer_name"] == "X"
        assert d["status"] == "PENDING"
        db.close()


# ══════════════════════════════════════════════════════════════════════════════
# 13. Integration — end-to-end pipeline (all STUB, no network)
# ══════════════════════════════════════════════════════════════════════════════

class TestIntegrationPipeline:
    """
    End-to-end Tracer Bullet: transcript → SluiceEngine → LeadResult → notify.
    All STUB mode — zero network calls.

    Methodology: Tracer Bullet (get one path working end-to-end with stubs first).
    """

    def test_mkz_qualify_pipeline(self):
        """MKZ qualified lead flows: transcript → Sluice → QUALIFIED result."""
        from CommPlexCore.campaigns.mkz import MKZCampaign
        from CommPlexCore.gcp.vertex import GeminiFlashClassifier

        campaign = MKZCampaign()
        clf      = GeminiFlashClassifier(sluice_mode="standard")
        result   = clf.classify_lead("I have a 2021 Lincoln MKZ for $25,000.")

        assert result.qualified is True
        # Anti-hallucination: price must be in transcript
        assert campaign.verify_price("I have a 2021 Lincoln MKZ for $25,000.", result.price_detected)

    def test_all_campaigns_qualify_pipeline(self):
        """All 4 campaigns can process an inbound lead without error."""
        from CommPlexCore.campaigns.registry import CampaignRegistry
        from CommPlexCore.gcp.vertex import GeminiFlashClassifier

        CampaignRegistry.reset()
        clf = GeminiFlashClassifier(sluice_mode="standard")

        for slug in CampaignRegistry.all_slugs():
            campaign = CampaignRegistry.get(slug)
            result   = clf.classify_lead("I have a 2021 vehicle for $25,000.")
            # Should not raise; result should be structured
            assert hasattr(result, "qualified")
            assert hasattr(result, "to_dict")

    def test_sluice_anti_hallucination_pipeline(self):
        """Full pipeline: AI reports price but transcript doesn't contain it → MANUAL_REVIEW."""
        from CommPlexCore.gcp.vertex import SluiceEngine
        from CommPlexSpec.campaigns.base import BaseCampaign

        transcript = "I have a 2021 Lincoln in great condition, let's talk."
        sluice = SluiceEngine(mode="standard")

        # AI says price is $25,000 but it's NOT in the transcript
        result = sluice.qualify(
            {"price_detected": 25000, "vehicle_year": 2021, "reasoning": "AI extracted"},
            transcript
        )
        # SluiceEngine's anti-hallucination filter should catch this
        assert result.manual_review is True
        # Double-check via Spec's guardrail
        assert BaseCampaign.verify_price(transcript, 25000) is False

    def test_registry_to_sluice_pipeline(self):
        """Registry → campaign → qualify_inbound works for all slugs."""
        from CommPlexCore.campaigns.registry import CampaignRegistry
        CampaignRegistry.reset()

        for slug in CampaignRegistry.all_slugs():
            campaign = CampaignRegistry.get(slug)
            if hasattr(campaign, "qualify_inbound"):
                result = campaign.qualify_inbound(
                    "I have a 2022 vehicle for $26,000.", "Test Dealer"
                )
                assert "status" in result


# ══════════════════════════════════════════════════════════════════════════════
# 14. Smoke Tests — all CommPlex modules importable
# ══════════════════════════════════════════════════════════════════════════════

class TestSmokeImports:
    """All CommPlex modules should import without error (STUB mode safe)."""

    def test_commplex_spec_base(self):
        from CommPlexSpec.campaigns.base import BaseCampaign, Contact, CampaignRegistry

    def test_commplexcore_vertex(self):
        from CommPlexCore.gcp.vertex import (
            GeminiFlashClassifier, SluiceEngine, get_classifier, get_sluice
        )

    def test_commplexcore_secrets(self):
        from CommPlexCore.gcp.secrets import get_secret, require_secret, health

    def test_commplexcore_mkz(self):
        from CommPlexCore.campaigns.mkz import MKZCampaign, get_campaign

    def test_commplexcore_towncar(self):
        from CommPlexCore.campaigns.towncar import TownCarCampaign, get_campaign

    def test_commplexcore_f350(self):
        from CommPlexCore.campaigns.f350 import F350Campaign, get_campaign

    def test_commplexcore_jayco(self):
        from CommPlexCore.campaigns.jayco import JaycoCampaign, get_campaign

    def test_commplexcore_registry(self):
        from CommPlexCore.campaigns.registry import CampaignRegistry, get_campaign, get_all_campaigns

    def test_commplex_api_models(self):
        try:
            from CommPlexAPI.models import Lead, LeadStatus, init_db
        except ImportError:
            pytest.skip("CommPlexAPI not installed")

    def test_commplex_edge_notifier(self):
        from CommPlexEdge.modules.notifier import (
            NotifierModule, NtfyBackend, MultiNotifier,
            Priority, Category
        )


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
