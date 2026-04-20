"""
tests/test_sentry.py
====================
Unit tests for CommPlex Sentry — all four subsystems.
Run with: pytest tests/test_sentry.py -v
No live GCP/Twilio calls are made — all external clients are mocked.
"""

import asyncio
import math
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# We import from sentry directly — adjust path if needed
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import sentry as S
from sentry import (
    CallRecord,
    CircuitBreaker,
    CommPlexSentry,
    OperationsState,
    RABifierBackoff,
    TanukiStats,
    WaveRecord,
    _state,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_global_state():
    """Reset shared mutable state before every test."""
    _state.ops_state = OperationsState.ACTIVE
    _state.rab_backoff_attempt = 0
    _state.rab_backoff_until = 0.0
    _state.last_pause_reason = ""
    _state.last_alert_ts.clear()
    yield


@pytest.fixture
def mock_secret_client():
    client = MagicMock()
    client.add_secret_version = MagicMock(return_value=None)
    return client


@pytest.fixture
def circuit(mock_secret_client):
    return CircuitBreaker(
        secret_client=mock_secret_client,
        window_s=300,
        floor=0.80,
        min_samples=5,
    )


@pytest.fixture
def backoff():
    return RABifierBackoff(base=2.0, max_delay=64.0, jitter=0.0)


@pytest.fixture
def stats():
    return TanukiStats(window=50)


# ---------------------------------------------------------------------------
# TanukiStats — Arithmetic Mean
# ---------------------------------------------------------------------------
class TestArithmeticMean:
    def test_returns_none_when_empty(self, stats):
        assert stats.arithmetic_mean_volume() is None

    def test_single_batch(self, stats):
        stats.record_lead_batch(10)
        assert stats.arithmetic_mean_volume() == pytest.approx(10.0)

    def test_multiple_batches(self, stats):
        for v in [10, 20, 30]:
            stats.record_lead_batch(v)
        assert stats.arithmetic_mean_volume() == pytest.approx(20.0)

    def test_ignores_negative_counts(self, stats):
        stats.record_lead_batch(-5)  # clamped to 0
        stats.record_lead_batch(10)
        assert stats.arithmetic_mean_volume() == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# TanukiStats — Harmonic Mean
# ---------------------------------------------------------------------------
class TestHarmonicMean:
    def test_returns_none_when_empty(self, stats):
        assert stats.harmonic_mean_speed() is None

    def test_uniform_values(self, stats):
        for _ in range(4):
            stats.record_qualification(4.0)
        # H([4,4,4,4]) = 4 / (4 * 1/4) = 4
        assert stats.harmonic_mean_speed() == pytest.approx(4.0)

    def test_penalises_outlier(self, stats):
        """HM should be lower than AM when there's a large outlier."""
        values = [1.0, 1.0, 1.0, 1.0, 100.0]
        for v in values:
            stats.record_qualification(v)
        hm = stats.harmonic_mean_speed()
        am = sum(values) / len(values)  # 20.8
        assert hm < am
        # HM = 5 / (4 + 0.01) ≈ 1.244
        expected_hm = len(values) / sum(1.0 / v for v in values)
        assert hm == pytest.approx(expected_hm, rel=1e-4)

    def test_zero_duration_excluded(self, stats):
        """record_qualification with 0 should be ignored."""
        stats.record_qualification(0)
        assert stats.harmonic_mean_speed() is None  # nothing recorded


# ---------------------------------------------------------------------------
# TanukiStats — Geometric Mean
# ---------------------------------------------------------------------------
class TestGeometricMean:
    def test_returns_none_when_fewer_than_two_waves(self, stats):
        stats.record_wave(WaveRecord("w1", 100))
        assert stats.geometric_mean_growth() is None

    def test_two_equal_waves(self, stats):
        for i in range(2):
            stats.record_wave(WaveRecord(f"w{i}", 100))
        assert stats.geometric_mean_growth() == pytest.approx(100.0)

    def test_compounding_growth(self, stats):
        """G([2, 8]) = sqrt(16) = 4"""
        stats.record_wave(WaveRecord("w1", 2))
        stats.record_wave(WaveRecord("w2", 8))
        assert stats.geometric_mean_growth() == pytest.approx(4.0)

    def test_log_space_stable_for_large_values(self, stats):
        import math
        # 10 waves doubling in size — GM should equal geometric progression midpoint
        waves = [2 ** i for i in range(1, 11)]
        for i, w in enumerate(waves):
            stats.record_wave(WaveRecord(f"w{i}", w))
        gm = stats.geometric_mean_growth()
        expected = math.exp(sum(math.log(v) for v in waves) / len(waves))
        assert gm == pytest.approx(expected, rel=1e-6)


# ---------------------------------------------------------------------------
# CircuitBreaker
# ---------------------------------------------------------------------------
class TestCircuitBreaker:
    def _fill(self, cb, successes, failures):
        ts = time.time()
        for _ in range(successes):
            cb.ingest(CallRecord(ts=ts, success=True, duration_s=1.0))
        for _ in range(failures):
            cb.ingest(CallRecord(ts=ts, success=False, duration_s=1.0))

    @pytest.mark.asyncio
    async def test_no_trip_below_min_samples(self, circuit):
        circuit.ingest(CallRecord(ts=time.time(), success=False, duration_s=1.0))
        rate = await circuit.evaluate()
        assert rate is None
        assert _state.ops_state == OperationsState.ACTIVE

    @pytest.mark.asyncio
    async def test_no_trip_above_floor(self, circuit):
        self._fill(circuit, successes=9, failures=1)  # 90% success
        with patch("sentry._ntfy_alert", new_callable=AsyncMock):
            rate = await circuit.evaluate()
        assert rate is not None
        assert rate > 0.80
        assert _state.ops_state == OperationsState.ACTIVE

    @pytest.mark.asyncio
    async def test_trips_below_floor(self, circuit):
        """5 successes + 10 failures → HM rate << 0.80 → should trip."""
        self._fill(circuit, successes=5, failures=10)
        with patch("sentry._ntfy_alert", new_callable=AsyncMock) as mock_alert:
            rate = await circuit.evaluate()
        assert rate < 0.80
        assert _state.ops_state == OperationsState.PAUSED
        mock_alert.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_prunes_old_records(self, circuit):
        """Records outside the window should be dropped before evaluation."""
        old_ts = time.time() - 400  # outside 300s window
        for _ in range(20):
            circuit.ingest(CallRecord(ts=old_ts, success=False, duration_s=1.0))
        rate = await circuit.evaluate()
        assert rate is None  # pruned → below min_samples

    @pytest.mark.asyncio
    async def test_reset_clears_pause(self, circuit, mock_secret_client):
        _state.ops_state = OperationsState.PAUSED
        with patch("sentry._ntfy_alert", new_callable=AsyncMock):
            await circuit.reset()
        assert _state.ops_state == OperationsState.ACTIVE
        mock_secret_client.add_secret_version.assert_called_once()


# ---------------------------------------------------------------------------
# RABifierBackoff
# ---------------------------------------------------------------------------
class TestRABifierBackoff:
    @pytest.mark.asyncio
    async def test_no_pause_initially(self, backoff):
        assert backoff.should_pause() is False

    @pytest.mark.asyncio
    async def test_on_429_sets_backoff(self, backoff):
        with patch("sentry._ntfy_alert", new_callable=AsyncMock):
            delay = await backoff.on_429()
        assert delay >= 1.0
        assert _state.rab_backoff_attempt == 1
        assert _state.rab_backoff_until > time.time()
        assert backoff.should_pause() is True

    @pytest.mark.asyncio
    async def test_exponential_growth(self, backoff):
        """Each attempt should roughly double delay (base=2, jitter=0)."""
        delays = []
        with patch("sentry._ntfy_alert", new_callable=AsyncMock):
            for _ in range(5):
                d = await backoff.on_429()
                delays.append(d)
                # Reset backoff_until so should_pause doesn't block next call
                _state.rab_backoff_until = 0

        # delays: [2, 4, 8, 16, 32] — verify monotonic growth
        for i in range(1, len(delays)):
            assert delays[i] >= delays[i - 1]

    @pytest.mark.asyncio
    async def test_caps_at_max_delay(self, backoff):
        _state.rab_backoff_attempt = 100  # force huge attempt count
        with patch("sentry._ntfy_alert", new_callable=AsyncMock):
            delay = await backoff.on_429()
        assert delay <= backoff._max + backoff._max * backoff._jitter + 1

    @pytest.mark.asyncio
    async def test_reset_clears_state(self, backoff):
        _state.rab_backoff_attempt = 3
        _state.rab_backoff_until = time.time() + 999
        _state.ops_state = OperationsState.DEGRADED
        await backoff.reset()
        assert _state.rab_backoff_attempt == 0
        assert _state.rab_backoff_until == 0.0
        assert _state.ops_state == OperationsState.ACTIVE

    @pytest.mark.asyncio
    async def test_sets_degraded_not_paused(self, backoff):
        """A 429 should degrade but not fully pause operations."""
        with patch("sentry._ntfy_alert", new_callable=AsyncMock):
            await backoff.on_429()
        assert _state.ops_state == OperationsState.DEGRADED
        assert _state.ops_state != OperationsState.PAUSED


# ---------------------------------------------------------------------------
# Integration: CommPlexSentry.ingest_call feeds CircuitBreaker
# ---------------------------------------------------------------------------
class TestSentryIntegration:
    @pytest.mark.asyncio
    async def test_ingest_populates_circuit_window(self):
        with (
            patch("sentry._load_secret", return_value="dummy"),
            patch("sentry.TwilioClient"),
            patch("sentry.secretmanager.SecretManagerServiceClient"),
        ):
            sv = S.CommPlexSentry()
            for _ in range(10):
                sv.ingest_call(success=True, duration_s=1.5)
            assert len(sv.circuit._window) == 10
            assert sv.stats.harmonic_mean_speed() is not None

    @pytest.mark.asyncio
    async def test_ingest_wave_records_to_stats(self):
        with (
            patch("sentry._load_secret", return_value="dummy"),
            patch("sentry.TwilioClient"),
            patch("sentry.secretmanager.SecretManagerServiceClient"),
        ):
            sv = S.CommPlexSentry()
            sv.ingest_wave("wave_001", lead_count=50)
            sv.ingest_wave("wave_002", lead_count=100)
            gm = sv.stats.geometric_mean_growth()
            assert gm is not None
            assert gm == pytest.approx(math.sqrt(50 * 100), rel=1e-4)
