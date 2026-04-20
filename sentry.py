"""
CommPlex Sentry — v1.0
======================
Senior Cloud Architect / DevSecOps: Kenyon Jones
Project: commplex-493805 | Deployed: Cloud Run (background worker)

Four subsystems:
  1. CircuitBreaker    — Harmonic-Mean success-rate guard → PAUSE_OPERATIONS flag
  2. BillingWatchdog   — GCP budget + Twilio balance → ntfy.sh high-priority alert
  3. TanukiStats       — AM / HM / GM rolling math module (lead vol / speed / growth)
  4. RABifierBackoff   — Auto exponential-backoff + jitter on 429 RESOURCE_EXHAUSTED

Entry point: async main() — runs as a Cloud Run background worker via Procfile.
All state mutations are atomic; all external I/O is async; all secrets come from
GCP Secret Manager (never from env literals in production).
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import random
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Deque, Dict, Optional, Sequence

import httpx
from google.cloud import secretmanager_v1 as secretmanager
from twilio.rest import Client as TwilioClient

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SENTRY] %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("commplex.sentry")

# ---------------------------------------------------------------------------
# Constants — override via env vars in Cloud Run service config
# ---------------------------------------------------------------------------
GCP_PROJECT_ID: str = os.environ.get("GCP_PROJECT_ID", "commplex-493805")
SECRET_PAUSE_FLAG: str = os.environ.get("SECRET_PAUSE_FLAG", "PAUSE_OPERATIONS")
SECRET_TWILIO_SID: str = os.environ.get("SECRET_TWILIO_SID", "TWILIO_ACCOUNT_SID")
SECRET_TWILIO_TOKEN: str = os.environ.get("SECRET_TWILIO_TOKEN", "TWILIO_AUTH_TOKEN")
NTFY_TOPIC: str = os.environ.get("NTFY_TOPIC", "px10pro-commplex-z7x2-alert-hub")
NTFY_BASE_URL: str = "https://ntfy.sh"

# Circuit breaker thresholds
CB_WINDOW_SECONDS: int = int(os.environ.get("CB_WINDOW_SECONDS", "300"))   # 5 min
CB_SUCCESS_FLOOR: float = float(os.environ.get("CB_SUCCESS_FLOOR", "0.80"))  # 80%
CB_MIN_SAMPLE_SIZE: int = int(os.environ.get("CB_MIN_SAMPLE_SIZE", "10"))

# Billing / balance watchdog
TWILIO_LOW_WATER_MARK: float = float(os.environ.get("TWILIO_LOW_WATER_MARK", "20.00"))
GCP_BUDGET_LOW_PCT: float = float(os.environ.get("GCP_BUDGET_LOW_PCT", "0.85"))

# Polling cadence (seconds)
POLL_INTERVAL_CIRCUIT: int = int(os.environ.get("POLL_INTERVAL_CIRCUIT", "30"))
POLL_INTERVAL_BILLING: int = int(os.environ.get("POLL_INTERVAL_BILLING", "300"))
POLL_INTERVAL_STATS: int = int(os.environ.get("POLL_INTERVAL_STATS", "60"))

# RABifier backoff
BACKOFF_BASE: float = float(os.environ.get("BACKOFF_BASE", "2.0"))
BACKOFF_MAX: float = float(os.environ.get("BACKOFF_MAX", "512.0"))
BACKOFF_JITTER: float = float(os.environ.get("BACKOFF_JITTER", "0.3"))


# ---------------------------------------------------------------------------
# Enums & shared state
# ---------------------------------------------------------------------------
class OperationsState(Enum):
    ACTIVE = auto()
    PAUSED = auto()
    DEGRADED = auto()


@dataclass
class CallRecord:
    """A single resolved call event on the sliding window."""
    ts: float          # Unix timestamp
    success: bool
    duration_s: float  # qualification round-trip time in seconds (> 0)


@dataclass
class WaveRecord:
    """Per-wave aggregate for geometric growth tracking."""
    wave_id: str
    lead_count: int
    timestamp: float = field(default_factory=time.time)


@dataclass
class SentryState:
    """Shared mutable state — accessed only from the async event loop."""
    ops_state: OperationsState = OperationsState.ACTIVE
    rab_backoff_attempt: int = 0
    rab_backoff_until: float = 0.0          # epoch seconds
    last_pause_reason: str = ""
    last_alert_ts: Dict[str, float] = field(default_factory=dict)


# Singleton state — all coroutines share this
_state = SentryState()


# ---------------------------------------------------------------------------
# 1. TANUKI MATH MODULE
# ---------------------------------------------------------------------------
class TanukiStats:
    """
    Rolling statistical engine for CommPlex operational metrics.

      - Arithmetic Mean  → total lead volume (additive, equal weight)
      - Harmonic Mean    → 'true' qualification speed (penalises outlier delays)
      - Geometric Mean   → wave-to-wave scaling growth (multiplicative compounding)

    All three metrics are computed on deque-bounded sliding windows so memory
    is O(window_size) regardless of uptime.
    """

    def __init__(self, window: int = 100) -> None:
        self._lead_vol: Deque[int] = deque(maxlen=window)
        self._qual_times: Deque[float] = deque(maxlen=window)
        self._wave_leads: Deque[int] = deque(maxlen=window)

    # -- Ingestion -----------------------------------------------------------
    def record_lead_batch(self, count: int) -> None:
        """Call once per campaign batch ingestion."""
        self._lead_vol.append(max(count, 0))

    def record_qualification(self, duration_s: float) -> None:
        """Call when a lead is qualified/rejected. duration_s must be > 0."""
        if duration_s > 0:
            self._qual_times.append(duration_s)

    def record_wave(self, wave: WaveRecord) -> None:
        """Call at the end of each wave with its total lead count."""
        self._wave_leads.append(max(wave.lead_count, 1))  # ≥1 to avoid log(0)

    # -- Arithmetic Mean: total lead volume ----------------------------------
    def arithmetic_mean_volume(self) -> Optional[float]:
        """E[lead count per batch]. Equal weight — sensitive to large spikes."""
        if not self._lead_vol:
            return None
        return sum(self._lead_vol) / len(self._lead_vol)

    # -- Harmonic Mean: true qualification speed -----------------------------
    def harmonic_mean_speed(self) -> Optional[float]:
        """
        H = n / Σ(1/xᵢ)

        Harmonic mean of qualification times naturally down-weights pathological
        outliers (e.g. a 90-second stall caused by a dead number) without
        requiring explicit outlier removal.  Lower value = faster system.
        """
        if not self._qual_times:
            return None
        n = len(self._qual_times)
        try:
            return n / sum(1.0 / t for t in self._qual_times)
        except ZeroDivisionError:
            return None

    # -- Geometric Mean: wave-to-wave growth ---------------------------------
    def geometric_mean_growth(self) -> Optional[float]:
        """
        G = (∏xᵢ)^(1/n) = exp( (1/n) Σ ln(xᵢ) )

        Geometric mean of per-wave lead counts gives the 'true' compound
        growth rate between waves.  Computed in log-space for numerical safety.
        """
        if len(self._wave_leads) < 2:
            return None
        try:
            log_sum = sum(math.log(v) for v in self._wave_leads)
            return math.exp(log_sum / len(self._wave_leads))
        except (ValueError, ZeroDivisionError):
            return None

    def snapshot(self) -> Dict:
        return {
            "arithmetic_mean_volume": self.arithmetic_mean_volume(),
            "harmonic_mean_speed_s": self.harmonic_mean_speed(),
            "geometric_mean_growth": self.geometric_mean_growth(),
            "sample_sizes": {
                "lead_vol": len(self._lead_vol),
                "qual_times": len(self._qual_times),
                "waves": len(self._wave_leads),
            },
        }


# ---------------------------------------------------------------------------
# 2. CIRCUIT BREAKER
# ---------------------------------------------------------------------------
class CircuitBreaker:
    """
    Sliding-window circuit breaker using Harmonic Mean of success rates.

    A call is 'successful' if Twilio reports a completed/answered disposition.
    The Harmonic Mean penalises clusters of failures harder than the arithmetic
    mean — appropriate for telephony where a bad batch of numbers compounds.

    On trip: writes PAUSE_OPERATIONS='true' to GCP Secret Manager so every
    other CommPlex service that reads the flag will halt immediately.
    """

    def __init__(
        self,
        secret_client: secretmanager.SecretManagerServiceClient,
        window_s: int = CB_WINDOW_SECONDS,
        floor: float = CB_SUCCESS_FLOOR,
        min_samples: int = CB_MIN_SAMPLE_SIZE,
    ) -> None:
        self._client = secret_client
        self._window_s = window_s
        self._floor = floor
        self._min_samples = min_samples
        self._window: Deque[CallRecord] = deque()

    # -- Ingestion -----------------------------------------------------------
    def ingest(self, record: CallRecord) -> None:
        """Thread-safe append (called from the async loop only)."""
        self._window.append(record)

    def _prune(self) -> None:
        """Drop records older than the sliding window."""
        cutoff = time.time() - self._window_s
        while self._window and self._window[0].ts < cutoff:
            self._window.popleft()

    # -- Harmonic Mean of per-call success (0 or 1) --------------------------
    def _harmonic_success_rate(self, values: Sequence[float]) -> Optional[float]:
        """
        H = n / Σ(1/xᵢ)   where xᵢ ∈ {0.001, 1.0}

        We substitute 0.001 for failures (true zero → H=0 regardless of others).
        This makes the HM extremely sensitive to failure clusters.
        """
        if not values:
            return None
        safe = [v if v > 0 else 1e-3 for v in values]
        n = len(safe)
        try:
            return n / sum(1.0 / v for v in safe)
        except ZeroDivisionError:
            return None

    # -- Evaluation ----------------------------------------------------------
    async def evaluate(self) -> Optional[float]:
        """
        Prune → compute HM success rate → trip breaker if below floor.
        Returns the current HM rate, or None if window has too few samples.
        """
        self._prune()
        if len(self._window) < self._min_samples:
            return None  # not enough data yet

        values = [1.0 if r.success else 0.0 for r in self._window]
        rate = self._harmonic_success_rate(values)

        if rate is None:
            return None

        log.info(
            "CircuitBreaker | window=%ds samples=%d HM_success_rate=%.3f floor=%.2f",
            self._window_s, len(self._window), rate, self._floor,
        )

        if rate < self._floor and _state.ops_state == OperationsState.ACTIVE:
            await self._trip(rate)

        return rate

    async def _trip(self, rate: float) -> None:
        reason = (
            f"HM success rate {rate:.1%} fell below {self._floor:.0%} "
            f"over {self._window_s}s window ({len(self._window)} calls)"
        )
        log.critical("⚡ CIRCUIT BREAKER TRIPPED — %s", reason)
        _state.ops_state = OperationsState.PAUSED
        _state.last_pause_reason = reason
        await self._write_pause_flag("true", reason)
        await _ntfy_alert(
            title="🚨 CommPlex CIRCUIT BREAKER",
            message=reason,
            priority="urgent",
            tags=["rotating_light", "no_entry"],
        )

    async def _write_pause_flag(self, value: str, reason: str) -> None:
        """Add a new secret version to PAUSE_OPERATIONS in Secret Manager."""
        parent = (
            f"projects/{GCP_PROJECT_ID}/secrets/{SECRET_PAUSE_FLAG}"
        )
        payload = json.dumps({"state": value, "reason": reason, "ts": time.time()})
        try:
            self._client.add_secret_version(
                request={
                    "parent": parent,
                    "payload": {"data": payload.encode("utf-8")},
                }
            )
            log.info("SecretManager | %s updated → %s", SECRET_PAUSE_FLAG, value)
        except Exception as exc:  # noqa: BLE001
            log.error("SecretManager write failed: %s", exc)

    async def reset(self) -> None:
        """Manually clear the breaker (called by ops after remediation)."""
        if _state.ops_state == OperationsState.PAUSED:
            _state.ops_state = OperationsState.ACTIVE
            _state.last_pause_reason = ""
            await self._write_pause_flag("false", "manual reset by sentry")
            log.info("CircuitBreaker RESET — operations resumed.")


# ---------------------------------------------------------------------------
# 3. BILLING WATCHDOG
# ---------------------------------------------------------------------------
class BillingWatchdog:
    """
    Monitors two financial thresholds and fires ntfy alerts when breached.

      a) Twilio account balance < TWILIO_LOW_WATER_MARK
      b) GCP budget spend ≥ GCP_BUDGET_LOW_PCT of monthly budget

    Alerts are deduplicated — we won't re-alert the same condition within
    POLL_INTERVAL_BILLING seconds.
    """

    def __init__(
        self,
        twilio_client: TwilioClient,
        low_water: float = TWILIO_LOW_WATER_MARK,
        gcp_budget_pct: float = GCP_BUDGET_LOW_PCT,
    ) -> None:
        self._twilio = twilio_client
        self._low_water = low_water
        self._gcp_budget_pct = gcp_budget_pct

    # -- Twilio ---------------------------------------------------------------
    async def check_twilio_balance(self) -> Optional[float]:
        """
        Calls Twilio Balance API.  Returns current balance as float.
        Fires ntfy alert if balance < low water mark.
        """
        try:
            balance_record = self._twilio.api.v2010.balance.fetch()
            balance = float(balance_record.balance)
            currency = balance_record.currency

            log.info("Twilio balance: %.2f %s (LWM: %.2f)", balance, currency, self._low_water)

            if balance < self._low_water:
                alert_key = "twilio_low_balance"
                if _dedup_ok(alert_key, POLL_INTERVAL_BILLING):
                    await _ntfy_alert(
                        title="💸 Twilio Low Balance",
                        message=(
                            f"Balance {currency} {balance:.2f} is below the "
                            f"{currency} {self._low_water:.2f} low water mark. "
                            f"Top up immediately to avoid call interruption."
                        ),
                        priority="high",
                        tags=["warning", "money_with_wings"],
                    )
            return balance
        except Exception as exc:  # noqa: BLE001
            log.error("Twilio balance check failed: %s", exc)
            return None

    # -- GCP Billing ----------------------------------------------------------
    async def check_gcp_spend(self) -> None:
        """
        Reads the GCP_BUDGET_SPEND_PCT environment variable (set by Cloud Billing
        budget notification → Pub/Sub → Cloud Run env patch, or manually).
        Falls back gracefully if not available.

        In production: wire a Cloud Billing Budget notification to a Pub/Sub
        topic consumed by this sentry.  For now we read the env var that the
        budget notification Cloud Function writes to Secret Manager.
        """
        spend_pct_str = os.environ.get("GCP_BUDGET_SPEND_PCT")
        if spend_pct_str is None:
            log.debug("GCP_BUDGET_SPEND_PCT not set — skipping GCP spend check")
            return

        try:
            spend_pct = float(spend_pct_str)
        except ValueError:
            return

        log.info("GCP spend: %.1f%% of budget (alert threshold: %.0f%%)",
                 spend_pct * 100, self._gcp_budget_pct * 100)

        if spend_pct >= self._gcp_budget_pct:
            alert_key = "gcp_budget_high"
            if _dedup_ok(alert_key, POLL_INTERVAL_BILLING):
                await _ntfy_alert(
                    title="🔥 GCP Budget Alert",
                    message=(
                        f"GCP spend at {spend_pct:.0%} of monthly budget "
                        f"(threshold: {self._gcp_budget_pct:.0%}). "
                        f"Review Cloud Run and Cloud SQL costs immediately."
                    ),
                    priority="high",
                    tags=["fire", "chart_with_upwards_trend"],
                )


# ---------------------------------------------------------------------------
# 4. RABIFIER BACKOFF (Self-Healing on 429)
# ---------------------------------------------------------------------------
class RABifierBackoff:
    """
    Exponential backoff with full jitter for the RABifier call engine.

    On a 429 RESOURCE_EXHAUSTED (Twilio or GCP):
      1. Increment the attempt counter.
      2. Compute delay = min(BASE^attempt, MAX) * (1 ± jitter)
      3. Set _state.rab_backoff_until = now + delay
      4. Log + alert ops team.

    The calling engine should call `should_pause()` before each dial attempt.
    On a successful call, `reset()` clears the backoff state.
    """

    def __init__(
        self,
        base: float = BACKOFF_BASE,
        max_delay: float = BACKOFF_MAX,
        jitter: float = BACKOFF_JITTER,
    ) -> None:
        self._base = base
        self._max = max_delay
        self._jitter = jitter

    def should_pause(self) -> bool:
        """Return True if the backoff window has not yet expired."""
        if _state.rab_backoff_until <= 0:
            return False
        remaining = _state.rab_backoff_until - time.time()
        if remaining > 0:
            log.debug("RABifier paused for %.1fs (backoff attempt %d)",
                      remaining, _state.rab_backoff_attempt)
            return True
        return False

    async def on_429(self, error_body: str = "") -> float:
        """
        Called when a 429 is caught.  Returns the computed delay in seconds.
        Fully non-blocking — the caller decides whether to sleep or yield.
        """
        _state.rab_backoff_attempt += 1
        attempt = _state.rab_backoff_attempt

        raw_delay = min(self._base ** attempt, self._max)
        jitter_delta = raw_delay * self._jitter * (2 * random.random() - 1)
        delay = max(1.0, raw_delay + jitter_delta)

        _state.rab_backoff_until = time.time() + delay

        log.warning(
            "⚠️  RABifier 429 detected | attempt=%d delay=%.1fs | %s",
            attempt, delay, error_body[:200],
        )

        # Mark system as degraded (not paused — we recover automatically)
        _state.ops_state = OperationsState.DEGRADED

        alert_key = f"rab_429_attempt_{attempt}"
        if _dedup_ok(alert_key, delay):
            await _ntfy_alert(
                title=f"⚠️ RABifier Backoff — Attempt {attempt}",
                message=(
                    f"429 RESOURCE_EXHAUSTED detected. "
                    f"Auto-backing off {delay:.0f}s (attempt {attempt}). "
                    f"Will resume at {_fmt_ts(_state.rab_backoff_until)}."
                ),
                priority="default",
                tags=["warning", "hourglass"],
            )

        return delay

    async def reset(self) -> None:
        """Call on any successful response to clear backoff state."""
        if _state.rab_backoff_attempt > 0:
            log.info("RABifier backoff CLEARED after %d attempts.", _state.rab_backoff_attempt)
            _state.rab_backoff_attempt = 0
            _state.rab_backoff_until = 0.0
            if _state.ops_state == OperationsState.DEGRADED:
                _state.ops_state = OperationsState.ACTIVE

    async def wait_if_needed(self) -> None:
        """Async-safe helper: await this before each RABifier dial attempt."""
        while self.should_pause():
            await asyncio.sleep(min(5.0, _state.rab_backoff_until - time.time() + 0.1))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _dedup_ok(key: str, cooldown_s: float) -> bool:
    """Return True (and record timestamp) if alert is not in cooldown."""
    now = time.time()
    last = _state.last_alert_ts.get(key, 0)
    if now - last >= cooldown_s:
        _state.last_alert_ts[key] = now
        return True
    return False


def _fmt_ts(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%H:%M:%S UTC")


async def _ntfy_alert(
    title: str,
    message: str,
    priority: str = "default",
    tags: Optional[list[str]] = None,
) -> None:
    """
    POST an alert to the ntfy.sh hub.
    priority: min | low | default | high | urgent
    """
    headers = {
        "Title": title,
        "Priority": priority,
        "Tags": ",".join(tags or []),
        "Content-Type": "text/plain",
    }
    url = f"{NTFY_BASE_URL}/{NTFY_TOPIC}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, content=message.encode(), headers=headers)
            resp.raise_for_status()
            log.info("ntfy alert sent | title='%s' status=%d", title, resp.status_code)
    except Exception as exc:  # noqa: BLE001
        log.error("ntfy alert failed: %s", exc)


def _load_secret(client: secretmanager.SecretManagerServiceClient, name: str) -> str:
    """Fetch the latest version of a GCP secret and return its string value."""
    secret_path = f"projects/{GCP_PROJECT_ID}/secrets/{name}/versions/latest"
    response = client.access_secret_version(request={"name": secret_path})
    return response.payload.data.decode("utf-8").strip()


# ---------------------------------------------------------------------------
# 5. COMMPLEX SENTRY — Orchestrator
# ---------------------------------------------------------------------------
class CommPlexSentry:
    """
    Top-level orchestrator.  Runs three independent async polling loops:

      • _loop_circuit  — polls CircuitBreaker every POLL_INTERVAL_CIRCUIT s
      • _loop_billing  — polls BillingWatchdog every POLL_INTERVAL_BILLING s
      • _loop_stats    — prints TanukiStats snapshot every POLL_INTERVAL_STATS s

    A public `ingest_call()` method is the external API — CommPlexCore calls
    this for every resolved call event.  The RABifierBackoff is exposed so the
    core engine can call `sentry.backoff.on_429()` and `sentry.backoff.wait_if_needed()`.
    """

    def __init__(self) -> None:
        log.info("Initialising CommPlex Sentry …")
        self._secret_client = secretmanager.SecretManagerServiceClient()

        # Load Twilio creds from Secret Manager
        twilio_sid = _load_secret(self._secret_client, SECRET_TWILIO_SID)
        twilio_token = _load_secret(self._secret_client, SECRET_TWILIO_TOKEN)
        twilio_client = TwilioClient(twilio_sid, twilio_token)

        self.circuit = CircuitBreaker(self._secret_client)
        self.watchdog = BillingWatchdog(twilio_client)
        self.stats = TanukiStats()
        self.backoff = RABifierBackoff()

        log.info("Sentry subsystems online | project=%s topic=%s", GCP_PROJECT_ID, NTFY_TOPIC)

    # -- Public ingestion API ------------------------------------------------
    def ingest_call(self, success: bool, duration_s: float) -> None:
        """
        Called by CommPlexCore for every completed call event.
        Non-blocking — just appends to the sliding window.
        """
        self.circuit.ingest(CallRecord(
            ts=time.time(),
            success=success,
            duration_s=max(duration_s, 1e-3),
        ))
        self.stats.record_qualification(duration_s)

    def ingest_wave(self, wave_id: str, lead_count: int) -> None:
        """Called by CommPlexCore at the end of every wave."""
        self.stats.record_wave(WaveRecord(wave_id=wave_id, lead_count=lead_count))
        self.stats.record_lead_batch(lead_count)

    # -- Async polling loops -------------------------------------------------
    async def _loop_circuit(self) -> None:
        log.info("CircuitBreaker loop started (interval=%ds)", POLL_INTERVAL_CIRCUIT)
        while True:
            try:
                rate = await self.circuit.evaluate()
                if rate is not None:
                    log.info("CircuitBreaker | HM_rate=%.3f ops=%s",
                             rate, _state.ops_state.name)
            except Exception as exc:  # noqa: BLE001
                log.error("CircuitBreaker loop error: %s", exc)
            await asyncio.sleep(POLL_INTERVAL_CIRCUIT)

    async def _loop_billing(self) -> None:
        log.info("BillingWatchdog loop started (interval=%ds)", POLL_INTERVAL_BILLING)
        while True:
            try:
                balance = await self.watchdog.check_twilio_balance()
                await self.watchdog.check_gcp_spend()
                if balance is not None:
                    log.info("BillingWatchdog | twilio_balance=%.2f", balance)
            except Exception as exc:  # noqa: BLE001
                log.error("BillingWatchdog loop error: %s", exc)
            await asyncio.sleep(POLL_INTERVAL_BILLING)

    async def _loop_stats(self) -> None:
        log.info("TanukiStats loop started (interval=%ds)", POLL_INTERVAL_STATS)
        while True:
            await asyncio.sleep(POLL_INTERVAL_STATS)
            try:
                snap = self.stats.snapshot()
                log.info(
                    "TanukiStats | AM_vol=%.1f HM_speed=%.3fs GM_growth=%.2f | "
                    "samples(vol=%d qual=%d waves=%d)",
                    snap["arithmetic_mean_volume"] or 0,
                    snap["harmonic_mean_speed_s"] or 0,
                    snap["geometric_mean_growth"] or 0,
                    snap["sample_sizes"]["lead_vol"],
                    snap["sample_sizes"]["qual_times"],
                    snap["sample_sizes"]["waves"],
                )
            except Exception as exc:  # noqa: BLE001
                log.error("TanukiStats loop error: %s", exc)

    async def _startup_heartbeat(self) -> None:
        """Fire a startup alert so the team knows Sentry came online."""
        await _ntfy_alert(
            title="✅ CommPlex Sentry Online",
            message=(
                f"Sentry v1.0 started at {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}. "
                f"Circuit breaker armed ({CB_SUCCESS_FLOOR:.0%} floor / {CB_WINDOW_SECONDS}s window). "
                f"Twilio LWM: ${TWILIO_LOW_WATER_MARK:.2f}. "
                f"GCP budget alert: {GCP_BUDGET_LOW_PCT:.0%}."
            ),
            priority="default",
            tags=["white_check_mark", "shield"],
        )

    async def run(self) -> None:
        """Start all loops concurrently. Runs until cancelled."""
        await self._startup_heartbeat()
        await asyncio.gather(
            self._loop_circuit(),
            self._loop_billing(),
            self._loop_stats(),
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
async def main() -> None:
    sentry = CommPlexSentry()
    try:
        await sentry.run()
    except (KeyboardInterrupt, asyncio.CancelledError):
        log.info("Sentry shutdown requested — exiting cleanly.")


if __name__ == "__main__":
    asyncio.run(main())
