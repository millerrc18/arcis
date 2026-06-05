"""Watch loop for automated daily cadence.

Simple Python loop — no APScheduler or cron dependencies.
Uses a PID lockfile (data/watch.lock) to prevent duplicate instances.

WHY a simple loop instead of APScheduler/cron:
  - Single-process architecture avoids coordination overhead for the
    many stateful daily tasks (40+ done-flags, VRAM handoff sequencing).
  - APScheduler's thread pool + SQLite WAL = busy_timeout headaches (#160).
  - Cron can't manage the 4-tier multi-cadence schedule (Strategy Decision #22:
    15m position monitor / 30m scans / 60m sentiment / daily enrichment).
  - Sleep recovery (#152) needs gap detection within the same process.

The loop runs every 60 seconds, checks ET time, and dispatches tasks based on
hour/minute windows with daily reset at midnight. All task execution goes through
_safe_run() which provides per-task exponential backoff (#147, #231).

Called by: cli.commands, main
Calls: services.scan_service, services.shadow_service, services.watchlist_service, data_collection.*, sync.render_sync
Owns tables: scan_metrics, log_entries
Owns files: data/watch.lock (PID lockfile), data/watchdog.txt (heartbeat)
Config keys: automation.scan_interval_minutes, automation.morning_watchlist_hour_et, automation.eod_recap_hour_et
Tests: tests/test_watch_bootstrap.py, tests/test_watch_resilience.py, tests/test_watch_import.py
"""

import os
import subprocess
import sys
import time
import signal
import logging
from collections import deque
from logging.handlers import RotatingFileHandler
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo

import sqlite3
import uuid

from dotenv import load_dotenv

load_dotenv()

from src.config import DB_PATH, load_config
from src.llm.client import is_llm_available
from src.notifications import safe_send
from src.scheduler.handler_registry import HandlerRegistryMixin
from src.scheduler.metrics import upsert_daily_metric
from src.scheduler.scorer import GuardedScorer
from src.utils.db import (
    DBError,
    _scalar,
    configure_sqlite_for_production,
    connect_db,
    connect_db_with_pg_retry,
)

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")

# Cooperative-then-hard stop budget for the GPU0 training subprocess. Generous
# enough for the in-loop StopOnFlagCallback to checkpoint and exit cleanly
# before stop_training_bounded escalates to a hard terminate (MAJOR-3).
_TRAINING_STOP_TIMEOUT_S = 120


class DBLogHandler(logging.Handler):
    """Log handler that writes structured entries to log_entries SQLite table.

    Captures WARNING+ by default. Keeps last 500 entries (prunes on write).
    WHY: Powers the frontend dashboard's live log viewer. Only WARNING+ to
    avoid flooding the table with debug noise during 30-minute scan cycles.
    """

    def __init__(self, db_path: str = DB_PATH, max_entries: int = 500):
        super().__init__(level=logging.WARNING)
        self.db_path = db_path
        self.max_entries = max_entries
        self._write_count = 0

    def emit(self, record: logging.LogRecord) -> None:
        try:
            log_id = str(uuid.uuid4())
            # Extract short module name for dashboard filtering (e.g., "executor" from "src.shadow_trading.executor")
            source = record.name.split(".")[-1] if "." in record.name else record.name
            message = record.getMessage()[:2000]  # Truncate to prevent SQLite bloat
            details = None
            ctx = getattr(record, "ctx", None)
            if ctx:
                import json
                details = json.dumps(ctx, separators=(",", ":"), default=str)[:5000]
            elif record.exc_info and record.exc_info[1]:
                details = str(record.exc_info[1])[:5000]

            with connect_db(self.db_path) as conn:
                conn.execute(
                    "INSERT INTO log_entries "
                    "(log_id, log_level, source, message, details_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (log_id, record.levelname, source, message, details,
                     datetime.now(ET).isoformat()),
                )
                self._write_count += 1
                # Prune every 50 writes, not every write, to amortize the DELETE cost
                if self._write_count % 50 == 0:
                    conn.execute(
                        "DELETE FROM log_entries WHERE log_id NOT IN "
                        "(SELECT log_id FROM log_entries ORDER BY created_at DESC LIMIT ?)",
                        (self.max_entries,),
                    )
                conn.commit()
        except Exception:
            pass  # GOTCHA: Never let logging crash the system — silent failure is correct here


# #618 — Sleep-recovery threshold helper. Pre-fix the inline check used
# `elapsed > 30` which equals scan_interval, so natural scheduler jitter
# (~30-32 min for a 30-min interval) fired the alert ~12 times/day. The
# 1.5x multiplier preserves true-positive detection of Windows sleep gaps
# (which are typically 60+ min) while filtering out routine jitter.
def _is_likely_sleep_gap(elapsed_min: float, scan_interval_min: int) -> bool:
    """Return True only when elapsed time exceeds 1.5× the scan interval —
    the buffer absorbs typical scheduler jitter (which is bounded by ~5%
    in practice but spikes occasionally) without missing actual gaps."""
    return elapsed_min > 1.5 * scan_interval_min


def _sc_query_running(service_name: str) -> bool:
    """Return True if `service_name` is in the RUNNING state per `sc query`.

    Runs `sc query <service_name>` via subprocess and parses the stdout for
    the string "RUNNING".  Returns False on any subprocess error, non-zero
    exit, or absent/stopped state.  Never raises.

    Reusable by T18 (runtime liveness monitor) — kept at module level.
    """
    try:
        result = subprocess.run(
            ["sc", "query", service_name],
            capture_output=True,
            text=True,
        )
        return "RUNNING" in result.stdout
    except Exception:
        return False


def _assert_ollama_watchdog_present() -> None:
    """Fail-fast guard: raise RuntimeError if ArcisOllamaWatchdog is not RUNNING.

    Called early in WatchLoop._run_sync_body() before any other startup work.
    Uses the code-level guard pattern (NOT DependOnService in SCM) to avoid
    the dependency-wedge that caused a 13-min loop-down (#SCM-wedge incident).

    Escape hatch: set ARCIS_SKIP_WATCHDOG_GUARD=1 to bypass the raise (useful
    in CI, dev environments, or when intentionally starting without the watchdog).
    """
    if _sc_query_running("ArcisOllamaWatchdog"):
        return
    if os.environ.get("ARCIS_SKIP_WATCHDOG_GUARD") == "1":
        logger.warning(
            "[WATCH] ARCIS_SKIP_WATCHDOG_GUARD=1 — skipping ArcisOllamaWatchdog check"
        )
        return
    logger.critical(
        "[WATCH] STARTUP BLOCKED: ArcisOllamaWatchdog service is NOT RUNNING. "
        "Start the service before launching the watch loop, or set "
        "ARCIS_SKIP_WATCHDOG_GUARD=1 to bypass this check."
    )
    raise RuntimeError(
        "ArcisOllamaWatchdog is not running. "
        "Start the service or set ARCIS_SKIP_WATCHDOG_GUARD=1 to bypass."
    )


def sweep_stale_diagnostic_runs(db_path: str, stale_after_hours: int = 24) -> int:
    """Mark stale diagnostic_runs rows as failed at watch-loop startup.

    Finds rows with status IN ('queued', 'running') whose created_at is older
    than stale_after_hours and transitions them to status='failed'. Uses
    'failed' (not a new 'stale' value) because the schema only allows
    'queued' | 'running' | 'completed' | 'failed' and we must not add a new
    value without a schema migration.

    Sets:
      - status = 'failed'
      - stderr_tail = watchdog message (includes timestamp and threshold)
      - completed_at = now (ET)
      - updated_at = now (ET)

    The cutoff is computed in UTC so that ISO string comparison in SQLite is
    consistent regardless of whether stored created_at values carry +00:00 or
    a local offset (lexicographic comparison of same-offset strings is correct).

    Returns count of rows transitioned.
    """
    from datetime import timedelta, timezone as _tz
    now_et = datetime.now(ET)
    now_utc = datetime.now(_tz.utc)
    cutoff = (now_utc - timedelta(hours=stale_after_hours)).isoformat()
    message = (
        f"Watchdog at watch-loop startup {now_et.isoformat()}: "
        f"stale-queued for >{stale_after_hours}h, no worker pickup"
    )
    now_iso = now_et.isoformat()
    with connect_db(db_path) as conn:
        cursor = conn.execute(
            """UPDATE diagnostic_runs
               SET status = 'failed',
                   stderr_tail = ?,
                   completed_at = ?,
                   updated_at = ?
               WHERE status IN ('queued', 'running')
                 AND created_at < ?""",
            (message, now_iso, now_iso, cutoff),
        )
        conn.commit()
        return cursor.rowcount


def _route_email_via_digest(
    *,
    event_type: str,
    severity: str,
    payload: dict,
    source_tag: str,
    subject: str,
    body: str,
) -> None:
    """#115 DD-20 revised + DD-30 revised: route an email-bound event through
    the email_digest aggregator with shadow-mode dual-write + firehose fallback.

    - In mode='shadow' or 'time_aligned' (DD-20 revised): ALSO call send_email
      so the operator inbox is unchanged during the hold-over week.
    - In mode='off': the queue is the sole consumer; no immediate send.
    - On (ImportError, ModuleNotFoundError) ONLY (DD-30 revised + DA-MIN-19):
      log at CRITICAL with FIREHOSE FALLBACK marker, best-effort Telegram
      alert, fall back to immediate send_email. AssertionError MUST propagate
      (assertion = real coverage gap, not silent firehose regression).
    """
    from src.email.notifier import send_email

    cfg = load_config() or {}
    mode = ((cfg.get("email", {}) or {}).get("dual_write_hold_over", {})
            or {}).get("mode", "shadow")
    try:
        from src.notifications.email_digest import enqueue_for_email_digest
        enqueue_for_email_digest(
            event_type,
            severity=severity,
            payload=payload,
            source_tag=source_tag,
        )
        if mode in ('shadow', 'time_aligned'):
            send_email(subject, body)
    except (ImportError, ModuleNotFoundError) as e:
        logger.critical(
            '[EMAIL] email_digest import failed — FIREHOSE FALLBACK MODE: %s', e
        )
        try:
            safe_send(
                'system_event',
                body=f'CRITICAL: email_digest aggregator import failed; '
                     f'firehose mode active. Error: {e}',
                severity='alert',
            )
        except Exception:
            pass
        send_email(subject, body)


class WatchLoop(HandlerRegistryMixin):
    """Automated daily cadence loop for the AI Research Desk."""

    def __init__(self, config: dict, email_mode: str | None = None,
                 overnight: bool = False, clock=None, sleep=None):
        self.config = config
        self.overnight = overnight
        # Injectable clock/sleep seams for the lifecycle simulator (T3).
        # Defaults reproduce prod behavior exactly: real now(ET) + time.sleep.
        self._clock = clock or (lambda: datetime.now(ET))
        self._sleep = sleep or time.sleep
        auto_cfg = config.get("automation", {})
        bootcamp_cfg = config.get("bootcamp", {})
        bootcamp_enabled = bootcamp_cfg.get("enabled", False)

        self.morning_hour = auto_cfg.get("morning_watchlist_hour_et", 8)
        self.eod_hour = auto_cfg.get("eod_recap_hour_et", 16)
        self.market_open_hour = auto_cfg.get("market_open_hour_et", 9)
        self.market_open_minute = auto_cfg.get("market_open_minute_et", 30)
        self.market_close_hour = auto_cfg.get("market_close_hour_et", 16)

        # Bootcamp overrides
        if bootcamp_enabled:
            self.scan_interval = bootcamp_cfg.get("scan_interval_minutes", 30)
            default_email_mode = bootcamp_cfg.get("email_mode", "full_stream")
        else:
            self.scan_interval = auto_cfg.get("scan_interval_minutes", 30)
            default_email_mode = "full_stream"

        self.email_mode = email_mode or default_email_mode
        self.bootcamp_enabled = bootcamp_enabled
        self.bootcamp_phase = bootcamp_cfg.get("phase", 1) if bootcamp_enabled else None

        # Training config
        training_cfg = config.get("training", {})
        self.training_enabled = training_cfg.get("enabled", False)

        # Daily state (in-memory, resets on restart and at midnight ET).
        # WHY in-memory instead of DB: avoids SQLite contention (#160) and
        # simplifies the daily reset. A restart mid-day re-runs tasks which
        # is the safe default (idempotent tasks, no duplicate trades thanks to #99).
        self._morning_done = False
        self._eod_done = False
        self._last_scan_time: datetime | None = None
        self._daily_packets: list = []
        self._today: date | None = None
        self._trades_managed_today = 0
        self._training_collection_done = False
        self._training_run_done = False
        self._saturday_reports_done = False
        self._daily_audit_done = False
        self._consecutive_errors = 0
        # Fix for #231: backoff is per-task, not global. A failing collector
        # must not delay unrelated tasks like scans or reconciliation.
        self._backoff: dict[str, int] = {}
        self._shutdown_requested = False
        self._scan_in_progress = False
        # Rolling window for instability detection: alert if >5 errors in last hour
        self._error_timestamps: deque = deque(maxlen=20)
        self._hourly_alert_sent = False

        # Overnight schedule flags — these run 7 days/week (Fix for #225: elif
        # was blocking weekend data collection). Only VRAM handoff and pre-market
        # tasks gate on is_weekday individually.
        self._post_close_done = False
        self._overnight_training_collection_done = False
        self._data_collection_done = False
        self._news_ingestion_done = False
        self._enrichment_precache_done = False
        self._1min_bar_collection_done = False
        self._pre_market_done = False

        # Between-scan scoring
        self._scorer = GuardedScorer()
        self._scoring_in_progress = False
        self._daily_scored = 0
        self._tg_last_update_id = 0

        # Training-lifecycle flags (dual-GPU re-cutover) — GPU0 trains overnight
        # concurrently with Ollama inference on GPU1; no VRAM handoff. Evening
        # launches training; morning + market-open ceiling stop it.
        self._evening_training_done = False
        self._morning_training_stop_done = False
        self._market_open_stop_done = False

        # Pre-market pipeline flags
        self._premarket_features_done = False
        self._premarket_training_done = False
        self._premarket_news_done = False
        self._premarket_candidates_done = False
        self._ollama_warmup_done = False
        self._council_done = False

        # Expanded notification flags
        self._premarket_brief_done = False
        self._first_scan_done = False
        self._eod_report_done = False
        self._data_asset_report_done = False
        self._weekly_digest_done = False
        self._last_vix_alert_level: float | None = None
        self._earnings_warning_done = False
        self._premarket_bracket_check_done = False
        self._postclose_bracket_check_done = False
        self._postclose_reconcile_done = False
        self._strategy_gate_done = False
        self._last_bracket_check_time: datetime | None = None

        # Research synthesis + daily metrics
        self._research_synthesis_done = False
        self._daily_metric_snapshot_done = False

        # Email digest flags
        self._digest_premarket_done = False
        self._digest_midday_done = False
        self._digest_eod_done = False
        self._digest_evening_done = False
        # #115 T8: new tier-based digest flags (preopen / postclose / weekly).
        # Coexist with the 4 deprecated done-flags above during the DD-20
        # dual-write hold-over.
        self._digest_preopen_done = False
        self._digest_postclose_done = False
        self._digest_weekly_done = False
        self._action_reminders_done = False
        self._daily_validation_done = False
        self._daily_build_score_done = False

        # Intra-day reconciliation throttle
        self._last_reconcile_time: datetime | None = None

        # Collector failure tracking: {collector_name: consecutive_failure_count}
        self._collector_failures: dict[str, int] = {}
        self._scan_number = 0

        # Console status heartbeat
        self._last_status_print: datetime | None = None
        self._reprint_banner_on_next_cycle = False

        # IB integration sprint: connection health monitoring
        self._ib_disconnect_alerted = False
        self._last_ib_health_check: datetime | None = None

        # Multi-cadence timing
        self._last_position_monitor_time: datetime | None = None
        self._last_sentiment_refresh_time: datetime | None = None
        self._fundamentals_done = False

        # Attribution outcome resolution
        self._attribution_resolution_done = False

        # Model regression check
        self._model_regression_done = False

        # Stress test scheduling
        self._stress_test_done = False

        # Simulation engine scheduling
        self._simulation_done = False
        # Trading-stats pulses — 3x per weekday (7:45, 12:00, 16:05 ET)
        self._stats_premarket_done = False
        self._stats_midday_done = False
        self._stats_postclose_done = False
        self._handlers: dict[str, list] = {}  # Phase A: see handler_registry.py

        # Sprint 4 Task 9: platform-tick rate-limiting state. One entry per
        # strategy_id; cleared on daily reset. Used by _run_platform_shadow_tick
        # to respect each strategy's shadow_cadence_seconds independently.
        self._last_platform_tick: dict[str, datetime] = {}

        # Tick: drift detector (Wave C T4, 30min cadence) — see manual_intervention_drift.py
        self._last_drift_detector_time: datetime | None = None

        # Tick: digest queue flush (T11 D2, configurable cadence default 60min)
        self._last_digest_queue_time: datetime | None = None

        # Tick: alert silence detector (T14 D5, 5-min cadence)
        self._last_alert_silence_time: datetime | None = None

        # T18: Runtime watchdog-liveness monitor (60s cadence).
        # _watchdog_last_known_running: None = never checked (no prior state).
        # Edge-triggered: alarm fires only on RUNNING→not-RUNNING transition.
        # Re-arms on recovery (not-RUNNING→RUNNING clears armed state).
        self._watchdog_liveness_last_check: datetime | None = None
        self._watchdog_last_known_running: bool | None = None

    def _reset_daily_state(self):
        """Reset daily flags at midnight ET.

        WHY reset everything: the system runs 24/7 and tasks are time-gated
        (e.g., morning watchlist at 8 AM, EOD at 4 PM). Flags prevent
        re-execution within the same day. At midnight they must reset so
        tomorrow's tasks fire on schedule.

        GOTCHA: Per-task backoff and collector failure counts also reset
        daily — a transient Finnhub outage yesterday should not delay
        tonight's collection.
        """
        self._morning_done = False
        self._eod_done = False
        self._last_scan_time = None
        self._daily_packets = []
        self._trades_managed_today = 0
        self._training_collection_done = False
        self._training_run_done = False
        self._saturday_reports_done = False
        self._daily_audit_done = False
        # Overnight flags
        self._post_close_done = False
        self._overnight_training_collection_done = False
        self._data_collection_done = False
        self._news_ingestion_done = False
        self._enrichment_precache_done = False
        self._1min_bar_collection_done = False
        self._pre_market_done = False
        # Scoring + training-lifecycle flags (daily reset)
        self._daily_scored = 0
        self._evening_training_done = False
        self._morning_training_stop_done = False
        self._market_open_stop_done = False
        # Pre-market pipeline
        self._premarket_features_done = False
        self._premarket_training_done = False
        self._premarket_news_done = False
        self._premarket_candidates_done = False
        self._ollama_warmup_done = False
        self._council_done = False
        # Expanded notification flags
        self._premarket_brief_done = False
        self._first_scan_done = False
        self._eod_report_done = False
        self._data_asset_report_done = False
        self._weekly_digest_done = False
        self._earnings_warning_done = False
        self._premarket_bracket_check_done = False
        self._postclose_bracket_check_done = False
        self._postclose_reconcile_done = False
        self._strategy_gate_done = False
        self._attribution_resolution_done = False
        self._model_regression_done = False
        self._stress_test_done = False
        self._simulation_done = False
        self._stats_premarket_done = False
        self._stats_midday_done = False
        self._stats_postclose_done = False
        self._last_bracket_check_time = None
        self._last_reconcile_time = None
        # Research + metrics
        self._research_synthesis_done = False
        self._daily_metric_snapshot_done = False
        # Email digest flags
        self._digest_premarket_done = False
        self._digest_midday_done = False
        self._digest_eod_done = False
        self._digest_evening_done = False
        # #115 T8: new tier-based digest flags (preopen / postclose / weekly).
        # Coexist with the 4 deprecated done-flags above during the DD-20
        # dual-write hold-over.
        self._digest_preopen_done = False
        self._digest_postclose_done = False
        self._digest_weekly_done = False
        self._action_reminders_done = False
        self._daily_validation_done = False
        self._daily_build_score_done = False
        self._scan_number = 0
        # IB integration sprint: reset disconnect alert daily
        self._ib_disconnect_alerted = False
        self._last_ib_health_check = None
        # Reset per-task backoff and collector failure tracking
        self._backoff.clear()
        self._collector_failures.clear()
        # Sprint 4 Task 9: clear platform-tick timestamps so each strategy
        # gets a fresh cadence window on the new trading day.
        self._last_platform_tick.clear()
        # Wave C T4: drift detector cadence reset
        self._last_drift_detector_time = None

    def _is_market_open(self, now: datetime) -> bool:
        """Check if market is currently open (weekday, not holiday, between open and close).

        WHY this matters: scans, position monitoring, and bracket checks only
        run during market hours. Overnight tasks run outside this window.

        Sprint 0 Wave 2a (HALF-DAY, T10): on NYSE early-close days
        (e.g., day after Thanksgiving, Christmas Eve), the market closes at
        13:00 ET instead of 16:00 ET. Without this check, scans/trades
        would fire 13:00-16:00 against a closed market.

        T14 D5: thin wrapper — delegates to holidays.is_market_open so the
        module-level function is reusable across monitoring code.
        """
        from src.scheduler.holidays import is_market_open as _is_open
        return _is_open(now)

    def _check_digest_schedule(self):
        """Send scheduled email digests at configured times (digest mode only).

        #115 T8 — Section 9.1: drives the new tier-based aggregator
        (`email_digest.flush_tier`) and the deprecated digest_builder branches
        under the DD-20-revised dual-write hold-over.

        Hold-over modes:
          shadow        → new flush_tier writes shadow files; OLD branches
                          fire send_email (operator inbox UNCHANGED).
          time_aligned  → new flush_tier sends real email; OLD midday +
                          evening SUPPRESSED; OLD premarket + EOD continue
                          to fire (time-aligned with new preopen/postclose).
          off           → new flush_tier sends real email; OLD branches
                          FULLY suppressed.
        """
        if self.email_mode != "digest":
            return
        now = self._clock()
        if now.weekday() >= 5:
            return
        email_cfg = self.config.get("email", {}) or {}
        self._check_email_tier_schedule(now, email_cfg)
        self._check_legacy_digest_schedule(now, email_cfg)

    def _check_email_tier_schedule(self, now, email_cfg):
        """#115 T8 — Fire flush_tier('preopen'|'postclose') in their 5-min windows.

        DD-07: per-tier `enabled` honored. DD-21: holiday-skip applies to
        daily tiers (preopen / postclose), NOT weekly.
        """
        h, m = now.hour, now.minute
        tier_times = email_cfg.get("tier_times", {}) or {}
        tiers_cfg = email_cfg.get("tiers", {}) or {}
        holidays_cfg = email_cfg.get("holidays", {}) or {}
        from src.notifications import email_digest as _email_digest
        from src.scheduler import holidays as _holidays_mod

        def _in_window(target_time: str) -> bool:
            th, tm = map(int, target_time.split(":"))
            return h == th and tm <= m < tm + 5

        for tier in ("preopen", "postclose"):
            done_attr = f"_digest_{tier}_done"
            if getattr(self, done_attr, False):
                continue
            enabled = (tiers_cfg.get(tier, {}) or {}).get("enabled", True)
            if not enabled:
                continue
            target = tier_times.get(tier, "07:30" if tier == "preopen" else "17:00")
            if not _in_window(target):
                continue
            skip_on_holiday = holidays_cfg.get(
                f"skip_{tier}_on_market_holidays", True,
            )
            if skip_on_holiday and _holidays_mod.is_market_holiday(
                check_date=now.date(),
            ):
                continue
            try:
                _email_digest.flush_tier(tier=tier)
                logger.info("[DIGEST] flush_tier(%s) dispatched", tier)
            except Exception as e:
                logger.error("[DIGEST] flush_tier(%s) failed: %s", tier, e)
            setattr(self, done_attr, True)

    def _check_legacy_digest_schedule(self, now, email_cfg):
        """#115 T8 — Deprecated digest_builder branches (DD-20 hold-over).

        Fires the legacy 4-slot digest_builder send_email paths, suppressed
        according to the hold-over mode (off / time_aligned / shadow).
        """
        h, m = now.hour, now.minute
        holdover_cfg = email_cfg.get("dual_write_hold_over", {}) or {}
        hold_over_mode = holdover_cfg.get("mode", "shadow")

        def _suppress_old(slot: str) -> bool:
            if hold_over_mode == "off":
                return True
            if hold_over_mode == "time_aligned" and slot in ("midday", "evening"):
                return True
            return False

        digest_cfg = email_cfg.get("digest_times", {}) or {}
        slots = {
            "premarket": (digest_cfg.get("premarket", "07:30"),
                          "_digest_premarket_done", "build_premarket_digest"),
            "midday":    (digest_cfg.get("midday", "12:00"),
                          "_digest_midday_done", "build_midday_digest"),
            "eod":       (digest_cfg.get("eod", "16:15"),
                          "_digest_eod_done", "build_eod_digest"),
            "evening":   (digest_cfg.get("evening", "20:00"),
                          "_digest_evening_done", "build_evening_digest"),
        }
        from src.email import digest_builder as _db
        from src.email.notifier import send_email

        for slot, (target, flag_name, builder_name) in slots.items():
            th, tm = map(int, target.split(":"))
            if not (h == th and tm <= m < tm + 5):
                continue
            if getattr(self, flag_name, False):
                continue
            setattr(self, flag_name, True)
            if _suppress_old(slot):
                continue
            try:
                subject, body = getattr(_db, builder_name)()
                send_email(subject, body)
                logger.info("[DIGEST] Sent %s digest", slot)
            except Exception as e:
                logger.error("[DIGEST] %s digest failed: %s", slot, e)

    def _maybe_flush_email_weekly_tier(self, now):
        """Fire flush_tier('weekly') at Sun 18:00 ET (5-min window).

        #115 T8 — Section 9.1: weekly tier. DD-21: holiday-skip does NOT
        apply to weekly (Sundays are non-trading anyway).
        """
        if self.email_mode != "digest":
            return
        email_cfg = self.config.get("email", {}) or {}
        tiers_cfg = email_cfg.get("tiers", {}) or {}
        weekly_enabled = (tiers_cfg.get("weekly", {}) or {}).get("enabled", True)
        if not weekly_enabled:
            return
        if self._digest_weekly_done:
            return
        if now.weekday() != 6 or now.hour != 18 or now.minute >= 5:
            return
        from src.notifications import email_digest as _email_digest
        try:
            _email_digest.flush_tier(tier="weekly")
            logger.info("[DIGEST] flush_tier(weekly) dispatched")
        except Exception as e:
            logger.error("[DIGEST] flush_tier(weekly) failed: %s", e)
        self._digest_weekly_done = True

    def _should_scan(self, now: datetime) -> bool:
        """Check if enough time has passed since last scan.

        Strategy Decision #22: Tier 2 scans run every 30 minutes during
        market hours. The scan_interval is configurable (default 30min,
        bootcamp may override).
        """
        if not self._is_market_open(now):
            return False
        if self._last_scan_time is None:
            return True
        elapsed = (now - self._last_scan_time).total_seconds() / 60

        # Fix for #152: Sleep recovery detection. Windows 11 sleep/hibernate
        # can cause 30+ minute gaps during market hours.
        # #618 — threshold raised from `>30` (literal scan_interval) to
        # `>1.5*scan_interval` because natural scheduler jitter (~30-32 min
        # for a 30-min interval) was firing the alert ~12 times/day.
        if _is_likely_sleep_gap(elapsed, self.scan_interval) and self._is_market_open(now):
            logger.warning(
                "[WATCH] Possible sleep recovery detected: %.0f min since last scan "
                "(expected %d min). Resuming scans.",
                elapsed, self.scan_interval,
            )
            try:
                from src.notifications.telegram import send_telegram
                send_telegram(
                    f"Sleep recovery: {elapsed:.0f}min gap detected during market hours. Resuming scans."
                )
            except Exception:
                pass  # Telegram optional

        return elapsed >= self.scan_interval

    def _get_live_stats(self) -> dict:
        """Query live system stats for banner/heartbeat. Never raises.

        GOTCHA: This is called in the main loop's display path. Any exception
        here would crash the status heartbeat, so everything is wrapped in
        try/except with N/A fallbacks. Alpaca API call adds ~200ms latency.
        """
        stats = {
            "open_paper": "N/A", "open_live": "N/A",
            "equity": "N/A", "buying_power": "N/A",
            "today_pnl": "N/A",
            "phase_trades": "N/A", "phase_required": 50,
            "last_audit": "N/A", "audit_age": "",
        }
        try:
            with connect_db(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                _row = conn.execute(
                    "SELECT COUNT(*) FROM shadow_trades WHERE status='open' AND source='paper'"
                    " AND COALESCE(quarantined, 0) = 0"
                ).fetchone()
                paper = _scalar(_row)
                _row = conn.execute(
                    "SELECT COUNT(*) FROM shadow_trades WHERE status='open' AND source='live'"
                    " AND COALESCE(quarantined, 0) = 0"
                ).fetchone()
                live = _scalar(_row)
                stats["open_paper"] = paper
                stats["open_live"] = live
                _row = conn.execute(
                    "SELECT COUNT(*) FROM shadow_trades WHERE status='closed'"
                    " AND COALESCE(quarantined, 0) = 0"
                ).fetchone()
                closed = _scalar(_row)
                stats["phase_trades"] = closed
                # Today's closed P&L
                today_str = datetime.now(ET).strftime("%Y-%m-%d")
                closed_today = conn.execute(
                    "SELECT COALESCE(SUM(pnl_dollars), 0) FROM shadow_trades "
                    "WHERE status='closed' AND actual_exit_time LIKE ?"
                    " AND COALESCE(quarantined, 0) = 0",
                    (f"{today_str}%",)
                ).fetchone()
                stats["today_pnl"] = round(float(closed_today[0] or 0), 2)
                # Last audit
                audit_row = conn.execute(
                    "SELECT overall_assessment, created_at FROM audit_reports "
                    "ORDER BY created_at DESC LIMIT 1"
                ).fetchone()
                if audit_row:
                    stats["last_audit"] = audit_row["overall_assessment"] or "unknown"
                    created = audit_row["created_at"]
                    if created:
                        from datetime import datetime as _dt
                        try:
                            age_s = (datetime.now(ET) - _dt.fromisoformat(created).replace(
                                tzinfo=ET if created[-1] != 'Z' else None
                            )).total_seconds()
                            hours = int(age_s / 3600)
                            stats["audit_age"] = f"({hours}h ago)" if hours < 48 else f"({hours // 24}d ago)"
                        except Exception:
                            stats["audit_age"] = ""
        except Exception as e:
            logger.debug("[WATCH] _get_live_stats DB error: %s", e)
        # Alpaca account
        try:
            from src.shadow_trading.alpaca_adapter import get_account_info
            acct = get_account_info()
            if acct:
                stats["equity"] = f"${float(acct.get('equity', 0)):,.0f}"
                stats["buying_power"] = f"${float(acct.get('buying_power', 0)):,.0f}"
        except Exception as e:
            logger.debug("[WATCH] _get_live_stats Alpaca error: %s", e)
        # IB integration sprint: live broker connection status
        try:
            from src.trading.broker_factory import get_live_broker
            broker = get_live_broker(self.config)
            stats["ib_connected"] = broker.is_connected()
            stats["live_broker"] = self.config.get("live_trading", {}).get("broker", "alpaca")
        except Exception:
            stats["ib_connected"] = False
            stats["live_broker"] = "unknown"
        return stats

    def _print_banner(self):
        """Print the startup banner with live system state."""
        now = datetime.now(ET)
        llm_status = "connected" if is_llm_available() else "not available"
        shadow_cfg = self.config.get("shadow_trading", {})
        shadow_status = "enabled" if shadow_cfg.get("enabled", False) else "disabled"

        bootcamp_str = (f"enabled (Phase {self.bootcamp_phase})"
                        if self.bootcamp_enabled else "disabled")

        from src.training.versioning import get_active_model_name, get_training_example_counts
        model_name = get_active_model_name()

        config_model = self.config.get("llm", {}).get("model", "qwen3:8b")
        if model_name and model_name != "base" and model_name != config_model:
            logger.warning(
                "Config model is '%s' but active trained model is '%s' — "
                "inference will use the trained model",
                config_model, model_name,
            )

        if self.training_enabled:
            t_counts = get_training_example_counts()
            training_str = f"enabled ({t_counts['total']} examples)"
        else:
            training_str = "disabled"

        live = self._get_live_stats()

        # IB integration sprint: show live broker in banner
        live_broker_name = self.config.get("live_trading", {}).get("broker", "alpaca").upper()

        # DB engine label — reflects Phase 3 cutover gate (post-Sprint 5).
        # Matches the routing check in src.utils.db.connect_db (gate + PG URL).
        _db_url = os.environ.get("DATABASE_URL", "")
        _pg_active = (
            os.environ.get("ARCIS_PG_CUTOVER_ENABLED") == "1"
            and _db_url.startswith("postgres")
        )
        db_engine_label = "PostgreSQL (Docker)" if _pg_active else "SQLite (WAL mode)"

        print(f"""
{'='*45}
 ARCIS - WATCH MODE
{'='*45}
 Time: {now.strftime('%Y-%m-%d %H:%M:%S')} ET
 LLM: {llm_status} ({model_name})
 Shadow Trading: {shadow_status}
 Bootcamp: {bootcamp_str} — {live['phase_trades']}/{live['phase_required']} trades
 Training: {training_str}

 Portfolio:
   Open positions: {live['open_paper']} paper / {live['open_live']} live
   Account equity: {live['equity']} | Buying power: {live['buying_power']}
   Today P&L: ${live['today_pnl'] if isinstance(live['today_pnl'], (int, float)) else 'N/A'}

 Schedule:
   Morning watchlist: {self.morning_hour}:00 ET
   Market scans: every {self.scan_interval} min ({self.market_open_hour}:{self.market_open_minute:02d}-{self.market_close_hour}:00 ET)
   EOD recap: {self.eod_hour}:00 ET
   Overnight: {'enabled' if self.overnight else 'disabled'}

 System:
   Live broker: {live_broker_name}
   Last audit: {live['last_audit']} {live['audit_age']}
   DB: {db_engine_label}

 Press Ctrl+C to stop.
{'='*45}
""")
        self._last_status_print = now
        self._reprint_banner_on_next_cycle = False

    def _print_status_heartbeat(self):
        """Print compact 4-line status block (every 60 min during market hours)."""
        now = datetime.now(ET)
        live = self._get_live_stats()
        time_str = now.strftime("%H:%M")
        print(f"\n{'─'*3} ARCIS STATUS ({time_str} ET) {'─'*30}")
        print(f" Phase 1: {live['phase_trades']}/{live['phase_required']} | "
              f"{live['open_paper']} open | Equity: {live['equity']} | "
              f"Today P&L: ${live['today_pnl'] if isinstance(live['today_pnl'], (int, float)) else 'N/A'}")
        last_scan = self._last_scan_time.strftime("%H:%M") if self._last_scan_time else "none"
        print(f" Last scan: {last_scan} | Audit: {live['last_audit']} | Sync: OK")
        print(f"{'─'*46}\n")

        # Send Telegram startup notification
        from src.training.versioning import get_active_model_name, get_training_example_counts
        _tg_model = get_active_model_name()
        if self.training_enabled:
            _tg_counts = get_training_example_counts()
            _tg_training = f"enabled ({_tg_counts.get('total', 0)} examples)"
        else:
            _tg_training = "disabled"
        safe_send(
            "system_event",
            event="ARCIS STARTED",
            detail=f"Model: {_tg_model}\nMode: {'Overnight' if self.overnight else 'Standard'}\nTraining: {_tg_training}",
        )
        print(" Telegram: connected (ok)")

    def _run_morning_watchlist(self):
        """Execute the morning watchlist pipeline."""
        from src.scheduler.reports import run_morning_watchlist
        run_morning_watchlist(self.config, email_mode=getattr(self, 'email_mode', 'digest'))

    def _run_scan(self):
        """Execute a market-hours scan cycle.

        Delegates to universe_scanner.run_universe_scan() for the core
        pipeline, then handles state mutations (email, Telegram, metrics).
        """
        # Graceful PAUSE gate (design D10): when the operator has engaged a
        # graceful pause, skip the autonomous scan/recommend/execute work.
        # This blocks NEW autonomous actions only — position monitoring and
        # reconciliation run on separate _safe_run tasks and stay alive.
        # Distinct from the governor's hard kill switch (which uses a halt
        # file); this is a cheap single-row DB read.
        from src.console.pause import is_paused
        if is_paused():
            logger.info("[PAUSE] Graceful pause active — skipping scan cycle")
            return

        from src.scheduler.universe_scanner import run_universe_scan, ScanContext
        from src.email.notifier import send_email

        now = datetime.now(ET)
        scan_started_at = time.time()
        _scan_num = getattr(self, "_scan_number", 0) + 1
        ctx = ScanContext(config=self.config, scan_id=f"s-{_scan_num:04d}")
        result = run_universe_scan(ctx)

        # Aborted scan (e.g., no SPY data) — just record metrics. Still
        # refresh live_prices: open positions from prior scans need fresh
        # quotes even when today's scan can't run (PR #910 review).
        if result.aborted:
            self._refresh_live_prices()
            self._record_scan_metrics(
                universe_count=result.universe_count, features_count=0,
                packet_worthy=0, llm_success=0, llm_total=0,
                avg_conviction=0.0,
                duration_seconds=time.time() - scan_started_at)
            return

        # Empty scan (no packet-worthy) — record and return. Same reasoning
        # as aborted: refresh live_prices for prior open positions.
        if result.packet_worthy_count == 0:
            self._refresh_live_prices()
            self._record_scan_metrics(
                universe_count=result.universe_count,
                features_count=result.features_count,
                packet_worthy=0, llm_success=0, llm_total=0,
                avg_conviction=0.0,
                duration_seconds=time.time() - scan_started_at)
            return

        self._trades_managed_today += result.packet_worthy_count

        # ── Email dispatch (uses self.email_mode, self._daily_packets) ──
        for pkt in result.packets_rendered:
            if self.email_mode == "full_stream":
                subject = f"[TRADE DESK] Action Packet - {pkt['ticker']}"
                _route_email_via_digest(
                    event_type='action_packet',
                    severity='normal',
                    payload={
                        'ticker': pkt.get('ticker'),
                        'rendered': pkt['rendered'],
                        'subject': subject,
                    },
                    source_tag='email:postclose',
                    subject=subject,
                    body=pkt["rendered"],
                )
                print(f"  -> Email sent for {pkt['ticker']}")
            elif self.email_mode == "daily_summary":
                self._daily_packets.append(pkt["rendered"])
                if len(self._daily_packets) > 200:
                    self._daily_packets = self._daily_packets[-100:]
            elif self.email_mode == "digest":
                pass  # Handled by scheduled midday/EOD digest

        # ── Intra-day reconciliation (uses self._last_reconcile_time) ─��
        # Fix for #182: Reconciliation crash was taking down scans. Now throttled
        # to every 15 min (900s) and isolated in try/except.
        if (self._last_reconcile_time is None or
                (now - self._last_reconcile_time).total_seconds() > 900):
            try:
                from src.shadow_trading.reconcile_dispatch import reconcile_all_paper_trades
                all_recon = reconcile_all_paper_trades(dry_run=False)
                total_closed: list = []
                for desk, recon in all_recon.items():
                    total_closed.extend(recon.get("marked_closed", []))
                if total_closed:
                    logger.info("[WATCH] Intra-day reconciliation closed %d stale trades: %s",
                                len(total_closed), total_closed)
                self._last_reconcile_time = now
            except Exception as e:
                logger.warning("[WATCH] Intra-day reconciliation failed: %s", e)

        # ── Telegram: scan-level notifications (uses self._scan_number) ──
        self._post_scan_notifications(result)

        # ── Refresh live_prices for open positions (PR #910 review) ──
        # Runs after the scan so packets-just-opened are included in the
        # ticker set queried by _refresh_live_prices. Outside the early-
        # return paths above so prior-day open positions still get fresh
        # quotes on aborted/empty scans too.
        self._refresh_live_prices()

        # ── Scan metrics ──
        # avg_conviction: mean of llm_conviction from packets if available.
        # TODO(#1057): wire real per-packet conviction list from result when
        # universe_scanner.ScanResult exposes it (source: src/scheduler/universe_scanner.py).
        # Proxy: conviction_parsed/conviction_total gives parse rate, not mean conviction.
        _avg_conviction = 0.0
        if result.conviction_total > 0:
            _avg_conviction = result.conviction_parsed / result.conviction_total
        self._record_scan_metrics(
            universe_count=result.universe_count,
            features_count=result.features_count,
            packet_worthy=result.packet_worthy_count,
            llm_success=result.packet_worthy_count,
            llm_total=result.packet_worthy_count,
            conviction_parsed=result.conviction_parsed,
            conviction_total=result.conviction_total,
            avg_conviction=_avg_conviction,
            duration_seconds=time.time() - scan_started_at)

    def _run_mr_scan(self):
        """Run mean reversion scan after main scan."""
        from src.services.mr_scan_service import run_mr_scan
        result = run_mr_scan(self.config)
        if result.get("trades_opened", 0) > 0:
            logger.info("[WATCH] MR scan opened %d trades", result["trades_opened"])
        return result.get("status") != "error"

    def _run_platform_shadow_tick(self) -> None:
        """Tick every active research-platform strategy once per cadence.

        Uses interval-gating (spec line 991-994), NOT inline dispatch like
        _run_mr_scan. Each strategy has its own shadow_cadence_seconds from
        spec.raw; checked independently.

        Failures on one strategy are logged and isolated — swing trading
        continues. The tick timestamp is recorded BEFORE running so a
        deterministic crash doesn't cause an infinite retry loop.
        """
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from src.platform.promotion import get_strategies_by_status
        from src.platform.shadow_harness import ShadowHarness
        from src.platform.strategy_spec import load_spec

        ET = ZoneInfo("America/New_York")
        # now_et is passed to run_one_tick (harness needs wall-clock context).
        # gate_now is naive for internal elapsed-time comparisons so that
        # _last_platform_tick entries stored as naive datetimes stay consistent.
        now_et = datetime.now(ET)
        gate_now = datetime.now()
        try:
            active = get_strategies_by_status(
                ["shadow_trading"],
                db_path=getattr(self, "_db_path", None) or DB_PATH,
            )
        except Exception:
            logger.exception("[PLATFORM] get_strategies_by_status failed")
            return

        for strategy_id in active:
            try:
                spec = load_spec(strategy_id)
                interval = int(spec.raw.get("shadow_cadence_seconds", 600))
                last_tick = self._last_platform_tick.get(strategy_id)
                if last_tick is not None and (gate_now - last_tick).total_seconds() < interval:
                    continue
                # Record the tick BEFORE running so a crash doesn't leave
                # us retrying on every outer-loop iteration.
                self._last_platform_tick[strategy_id] = gate_now
                harness = ShadowHarness(spec)
                result = harness.run_one_tick(now_et)
                logger.info(
                    "[PLATFORM] ticked %s: %d new positions",
                    strategy_id, result.get("n_new_positions", 0),
                )
            except Exception:
                logger.exception(
                    "[PLATFORM] tick failed for %s — swing continues",
                    strategy_id,
                )

    def _fetch_broker_positions_for_drift(self):
        """Return dict[ticker, BrokerPosition] from Alpaca; None on outage."""
        from src.monitoring.manual_intervention_drift import BrokerPosition
        from src.shadow_trading.alpaca_adapter import get_all_positions
        try:
            raw = get_all_positions()
            return {
                p["symbol"]: BrokerPosition(
                    ticker=p["symbol"],
                    status="open" if float(p.get("qty", 0)) > 0 else "closed",
                )
                for p in raw
            }
        except Exception as exc:
            logger.warning("[DRIFT] Broker fetch failed — treating as outage: %s", exc)
            return None

    def _fetch_db_positions_for_drift(self):
        """Return dict[ticker, DBPosition] from shadow_trades; raises MonitoringDataError."""
        from src.monitoring.manual_intervention_drift import DBPosition
        from src.monitoring.errors import MonitoringDataError
        from src.shadow_trading._status_sql import active_in_clause
        try:
            with connect_db(DB_PATH) as conn:
                placeholders, active_values = active_in_clause()
                rows = conn.execute(
                    f"SELECT ticker, status FROM shadow_trades "
                    f"WHERE status IN ({placeholders})",
                    active_values,
                ).fetchall()
                return {r["ticker"]: DBPosition(ticker=r["ticker"], status=r["status"]) for r in rows}
        except DBError as exc:
            raise MonitoringDataError(f"DB position fetch failed: {exc}") from exc

    def tick_drift_detector(self) -> None:
        """Tick: drift detector (Wave C T4, 30min cadence) — see manual_intervention_drift.py.

        Calls safe_send for each finding. Detector itself MUST NOT call safe_send
        (enforced by tests/monitoring/test_drift_detector_no_recursion.py).
        Done-flag set INSIDE try per CLAUDE.md "_safe_run returns bool" rule.
        """
        from pathlib import Path
        from src.monitoring.manual_intervention_drift import detect_drift
        from src.monitoring.errors import MonitoringDataError

        state_path = Path("data/drift_detector_state.json")
        now = datetime.now()

        if (
            self._last_drift_detector_time is not None
            and (now - self._last_drift_detector_time).total_seconds() < 1800
        ):
            return

        try:
            broker_positions = self._fetch_broker_positions_for_drift()
            db_positions = self._fetch_db_positions_for_drift()

            with connect_db(DB_PATH) as pe_conn:
                findings = detect_drift(
                    broker_positions=broker_positions,
                    db_positions=db_positions,
                    threshold_minutes=30,
                    state_path=state_path,
                    conn=pe_conn,
                )

            for finding in findings:
                try:
                    safe_send(
                        "manual_intervention_drift",
                        payload=finding.as_dict(),
                        severity="high",
                    )
                except Exception as notify_exc:
                    logger.warning("[DRIFT] Notify failed for %s: %s", finding.ticker, notify_exc)

            self._last_drift_detector_time = now

        except (MonitoringDataError, sqlite3.Error) as exc:
            logger.error("[DRIFT] tick_drift_detector failed: %s", exc)
            self._backoff["drift_detector"] = self._backoff.get("drift_detector", 0) + 1

    def tick_digest_queue(self) -> None:
        """Tick: digest queue flush (T11 D2, configurable cadence default 60min).

        Drains notifications_digest_queue rows with flush_status='pending'.
        Dispatcher calls _do_dispatch directly (bypassing safe_send policy re-gating,
        since each row was already policy-gated at enqueue time).
        Done-flag set INSIDE try per CLAUDE.md "_safe_run returns bool" rule.
        Backoff keyed to 'digest_queue' per-task.
        Config read from self.config (same reference used by the rest of the loop).
        """
        from src.notifications.digest_queue import DigestQueue
        from src.notifications.errors import NotificationsError
        from src.notifications.telegram import _do_dispatch, _load_config_for_safe_send

        try:
            notif_cfg = (self.config.get("notifications") or {})
            flush_minutes = int(notif_cfg.get("digest_flush_minutes", 60))
        except (TypeError, ValueError):
            flush_minutes = 60

        now = datetime.now()
        if (
            self._last_digest_queue_time is not None
            and (now - self._last_digest_queue_time).total_seconds() < flush_minutes * 60
        ):
            return

        def _real_dispatcher(row_payload: dict) -> None:
            event_type = row_payload.get("event_type", "")
            severity = row_payload.get("severity", "normal")
            kwargs = {k: v for k, v in row_payload.items() if k not in ("event_type", "severity")}
            _do_dispatch(event_type, kwargs, severity, ["telegram"])

        try:
            try:
                cfg = _load_config_for_safe_send()
            except Exception:
                cfg = None
            with connect_db(DB_PATH) as conn:
                q = DigestQueue(conn, config=cfg)
                result = q.flush(dispatcher=_real_dispatcher)
            logger.info(
                "[DIGEST] flush complete: successes=%d failures=%d abandoned=%d",
                result.successes, result.failures, result.abandoned,
            )
            self._last_digest_queue_time = now

        except (NotificationsError, sqlite3.Error) as exc:
            logger.error("[DIGEST] tick_digest_queue failed: %s", exc)
            self._backoff["digest_queue"] = self._backoff.get("digest_queue", 0) + 1

    def tick_alert_silence(self) -> None:
        """Tick: alert silence detector (T14 D5, 5-min cadence).

        Calls check_alert_silence to detect notification silence during market
        hours. Fires every 5 minutes. Side-effects (safe_send + platform_events)
        are handled inside check_alert_silence.
        Done-flag set INSIDE try per CLAUDE.md "_safe_run returns bool" rule.
        Backoff keyed to 'alert_silence' per-task.
        """
        from src.monitoring.alert_silence import check_alert_silence

        now = datetime.now(ET)
        if (
            self._last_alert_silence_time is not None
            and (now - self._last_alert_silence_time).total_seconds() < 5 * 60
        ):
            return

        try:
            check_alert_silence(now_et=now, threshold_minutes=60)
            self._last_alert_silence_time = now

        except Exception as exc:
            logger.error("[ALERT_SILENCE] tick_alert_silence failed: %s", exc)
            self._backoff["alert_silence"] = self._backoff.get("alert_silence", 0) + 1

    # ── T18: Runtime watchdog-liveness monitor ──────────────────────────────

    def _ollama_watchdog_metric_fresh(self, db_path: str = DB_PATH) -> bool:
        """Return True if today's gpu_health_ollama_ok metric is positive.

        Reads the schedule_metrics table for a row with metric_name =
        'gpu_health_ollama_ok' and metric_date = today (ET). Returns True
        when the value is > 0, False when absent or zero. Never raises.
        """
        try:
            today = datetime.now(ET).strftime("%Y-%m-%d")
            with connect_db(db_path) as conn:
                row = conn.execute(
                    "SELECT metric_value FROM schedule_metrics "
                    "WHERE metric_date = ? AND metric_name = ?",
                    (today, "gpu_health_ollama_ok"),
                ).fetchone()
            if row is None:
                return False
            return float(row[0] or 0) > 0
        except Exception:
            return False

    def tick_watchdog_liveness(self) -> None:
        """Tick: runtime liveness monitor for ArcisOllamaWatchdog (~60s cadence).

        Authoritative signal: _sc_query_running("ArcisOllamaWatchdog").
        Corroborating signal: gpu_health_ollama_ok metric freshness.

        Edge-triggered: emits a loud Telegram alarm via safe_send ONLY on a
        RUNNING→not-RUNNING transition (or fresh→stale corroboration). Re-arms
        on recovery so a subsequent outage re-alerts.

        Fail-soft: never raises. A broken alarm path must not break the tick.
        Cadence gate: ~60s, tracked by _watchdog_liveness_last_check.
        """
        now = datetime.now()
        if (
            self._watchdog_liveness_last_check is not None
            and (now - self._watchdog_liveness_last_check).total_seconds() < 60
        ):
            return

        try:
            is_running = _sc_query_running("ArcisOllamaWatchdog")
        except Exception:
            is_running = False

        self._watchdog_liveness_last_check = now

        prev = self._watchdog_last_known_running

        if is_running:
            # Recovery path: was not-RUNNING (or first check) → now RUNNING.
            # Update state; no alarm on recovery itself.
            self._watchdog_last_known_running = True
        else:
            # Not running — check for transition
            if prev is True:
                # RUNNING → not-RUNNING: edge-triggered alarm
                try:
                    metric_ok = self._ollama_watchdog_metric_fresh()
                    corroboration = "" if metric_ok else " (metric also stale)"
                    safe_send(
                        "system_event",
                        event="WATCHDOG DOWN",
                        detail=(
                            f"ArcisOllamaWatchdog is NOT RUNNING{corroboration}. "
                            "NSSM may have silently given up. Manual inspection required."
                        ),
                        severity="critical",
                    )
                except Exception:
                    pass
            self._watchdog_last_known_running = False

    # ── end T18 ──────────────────────────────────────────────────────────────

    def _post_scan_notifications(self, result):
        """Send Telegram notifications after a scan cycle."""
        safe_send(
            "scan_complete",
            packets_count=result.packet_worthy_count,
            trades_opened=result.trades_opened,
            trades_closed=result.trades_closed,
        )

        if not hasattr(self, '_scan_number'):
            self._scan_number = 0
        self._scan_number += 1
        safe_send(
            "scan_result",
            scan_number=self._scan_number,
            total_scanned=result.universe_count,
            packet_worthy=result.packet_worthy_count,
            watchlist=result.watchlist_count,
        )

        if not self._first_scan_done:
            # Fire-once marker: set BEFORE the notification attempt so that a
            # notification failure does NOT cause the summary to re-send on the
            # next scan. This is intentionally different from the canonical
            # `if self._safe_run(...): self._flag_done = True` pattern used for
            # retry-discipline (22 other sites). Here, the scan has already
            # succeeded — this flag gates a one-time informational summary, not
            # a task that should retry on failure. (#709 audit: correct-as-is)
            self._first_scan_done = True
            top_setups = [
                (c["ticker"], c["score"]) for c in result.packet_worthy[:3]
            ]
            setup_type_counts: dict[str, int] = {}
            for c in result.packet_worthy:
                st = c.get("features", {}).get("setup_type", "unknown")
                setup_type_counts[st] = setup_type_counts.get(st, 0) + 1
            safe_send(
                "first_scan_summary",
                total_scanned=result.universe_count,
                packet_worthy=result.packet_worthy_count,
                watchlist=result.watchlist_count,
                trades_opened_paper=result.trades_opened,
                trades_opened_live=0,
                top_setups=top_setups,
                setup_type_counts=setup_type_counts,
                llm_success=result.packet_worthy_count,
                llm_total=result.packet_worthy_count,
                llm_fallback=0,
            )

    def _record_scan_metrics(self, *, universe_count: int = 0,
                             features_count: int = 0, packet_worthy: int = 0,
                             llm_success: int = 0, llm_total: int = 0,
                             conviction_parsed: int = 0, conviction_total: int = 0,
                             avg_conviction: float = 0.0, duration_seconds: float = 0.0):
        """Write a row to scan_metrics for every scan cycle (success or failure)."""
        try:
            if not hasattr(self, '_scan_number'):
                self._scan_number = 0
            self._scan_number += 1
            now = datetime.now(ET)
            with connect_db(DB_PATH) as conn:
                conn.execute(
                    "INSERT INTO scan_metrics "
                    "(scan_number, scan_time, universe_count, features_count, "
                    "scored_count, packet_worthy, risk_passed, paper_traded, "
                    "live_traded, llm_success, llm_total, llm_fallback, "
                    "avg_conviction, duration_seconds, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (self._scan_number, now.strftime("%H:%M"), universe_count,
                     features_count, features_count, packet_worthy,
                     packet_worthy, packet_worthy, 0, llm_success, llm_total,
                     0, avg_conviction, duration_seconds, now.isoformat()),
                )
                conn.commit()
            # Structured cycle summary for AI agent review (#314)
            logger.info(
                "[WATCH] Scan cycle #%d complete",
                self._scan_number,
                extra={"ctx": {
                    "event": "scan_summary",
                    "scan_id": f"s-{self._scan_number:04d}",
                    "scan_number": self._scan_number,
                    "universe": universe_count,
                    "features": features_count,
                    "qualified": packet_worthy,
                    "llm_success": llm_success,
                    "llm_total": llm_total,
                    "conviction_none_rate": round(
                        1 - (llm_success / llm_total), 2) if llm_total > 0 else 0.0,
                }},
            )
            # #329: Log conviction parse rate separately from LLM success rate
            if conviction_total > 0:
                logger.info(
                    "[WATCH] Conviction parse rate: %d/%d (%.0f%%)",
                    conviction_parsed, conviction_total,
                    conviction_parsed / conviction_total * 100,
                )
            logger.info("[WATCH] Recorded scan_metrics #%d (packets=%d)",
                        self._scan_number, packet_worthy)
        except Exception as e:
            logger.warning("[WATCH] Failed to record scan_metrics: %s", e)

        # System metrics collection every 5 scans (~5 minutes at default cadence)
        if self._scan_number % 5 == 0:
            try:
                from src.monitoring.system_metrics import collect_system_snapshot
                collect_system_snapshot(DB_PATH)
            except Exception as e:
                logger.debug("[WATCH] System metrics collection failed: %s", e)

    def _refresh_live_prices(self):
        """Fetch current quotes for all open shadow trades and UPSERT to live_prices.

        Lazy-imports `fetch_latest_quotes` to keep the hard dependency on the
        Alpaca SDK contained to the function that actually uses it (matches
        the pattern at line 592 for `get_account_info`). PR #910 review note.
        """
        from src.shadow_trading.alpaca_adapter import fetch_latest_quotes

        try:
            with connect_db(DB_PATH) as conn:
                rows = conn.execute(
                    "SELECT DISTINCT ticker FROM shadow_trades WHERE status = 'open'"
                ).fetchall()
            tickers = [r[0] for r in rows if r[0]]
        except Exception as e:
            logger.warning("[WATCH] _refresh_live_prices: failed to query open trades: %s", e)
            return

        if not tickers:
            logger.debug("[WATCH] _refresh_live_prices: no open trades, skipping")
            return

        try:
            quotes = fetch_latest_quotes(tickers)
        except Exception as e:
            logger.warning("[WATCH] _refresh_live_prices: quote fetch failed: %s", e)
            return

        if not quotes:
            logger.warning("[WATCH] _refresh_live_prices: no quotes returned for %d tickers", len(tickers))
            return

        try:
            with connect_db(DB_PATH) as conn:
                for ticker, q in quotes.items():
                    conn.execute(
                        "INSERT INTO live_prices (ticker, price, bid, ask, as_of, source) "
                        "VALUES (?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT(ticker) DO UPDATE SET "
                        "price=excluded.price, bid=excluded.bid, ask=excluded.ask, "
                        "as_of=excluded.as_of, source=excluded.source",
                        (ticker, q["price"], q.get("bid"), q.get("ask"), q["as_of"], "alpaca"),
                    )
                conn.commit()
            logger.info("[WATCH] Refreshed live_prices for %d tickers (alpaca)", len(quotes))
        except Exception as e:
            logger.warning("[WATCH] _refresh_live_prices: UPSERT failed: %s", e)

    def _run_eod_recap(self):
        """Execute the EOD recap pipeline."""
        from src.data_ingestion.market_data import fetch_ohlcv, fetch_spy_benchmark
        from src.features.engine import compute_all_features
        from src.journal.store import get_todays_recommendations
        from src.packets.eod_recap import build_eod_recap
        from src.ranking.ranker import rank_universe, get_top_candidates
        from src.universe.sp100 import get_sp100_universe
        from src.email.notifier import send_email

        print("[WATCH] Running EOD recap pipeline...")
        universe = get_sp100_universe()
        ohlcv = fetch_ohlcv(universe)
        spy = fetch_spy_benchmark()

        if spy.empty:
            print("[WATCH] ERROR: Could not fetch SPY benchmark. Skipping EOD recap.")
            return

        features = compute_all_features(ohlcv, spy)
        ranked = rank_universe(features)
        candidates = get_top_candidates(ranked)
        journal_entries = get_todays_recommendations()

        now = datetime.now(ET)
        date_str = now.strftime("%Y-%m-%d")

        body = build_eod_recap(candidates["packet_worthy"], candidates["watchlist"],
                               journal_entries, date_str)

        # Append daily summary buffer if in daily_summary mode
        if self.email_mode == "daily_summary" and self._daily_packets:
            body += "\n\n" + "=" * 60 + "\nDAILY PACKET SUMMARY\n" + "=" * 60 + "\n"
            body += "\n\n".join(self._daily_packets)
            # #164: clear buffer after sending EOD digest to prevent unbounded growth
            self._daily_packets = []

        print(body)

        if self.email_mode != "digest":
            subject = f"[TRADE DESK] EOD Recap - {date_str}"
            _route_email_via_digest(
                event_type='eod_recap_email',
                severity='normal',
                payload={'subject': subject, 'body': body, 'date_str': date_str},
                source_tag='email:postclose',
                subject=subject,
                body=body,
            )
            print("[WATCH] EOD recap email sent.")
        else:
            print("[WATCH] EOD recap computed (digest mode — email sent via scheduled digest).")

    @staticmethod
    def _ensure_all_tables():
        """Create all expected SQLite tables on startup to prevent missing-table errors."""
        from src.schema.sqlite import create_all_tables, ensure_columns
        try:
            # Postgres self-heal: post-cutover the watch loop runs against PG
            # (DATABASE_URL set), but only the SQLite schema was ensured here —
            # so a wiped/drifted PG schema never re-synced from the registry
            # (2026-06-02 notifications_digest_queue/notifications_sent ERROR
            # loop). Mirror connect_db's PG routing EXACTLY (db.py:621-623): PG is
            # the live store only when the cutover gate is ON *and* DATABASE_URL is
            # postgres. Gating on BOTH avoids halting the loop on a PG hiccup when
            # it is actually running on SQLite (gate off). Idempotent path; inside
            # the same try so a PG-ensure failure follows the existing fatal
            # contract; fast timeouts so a down/locked PG fails fast.
            _pg_gate = os.environ.get("ARCIS_PG_CUTOVER_ENABLED") == "1"
            _pg_url = os.environ.get("DATABASE_URL", "").strip()
            if _pg_gate and _pg_url.startswith("postgres"):
                from src.schema.postgres import create_all_tables as _pg_create_all_tables
                import psycopg2
                try:
                    _added = _pg_create_all_tables(_pg_url, connect_timeout=5, lock_timeout_ms=10000)
                    logger.info("[WATCH] Postgres registry schema verified/created (%d column(s) added)", len(_added))
                except psycopg2.errors.InsufficientPrivilege as _own_exc:
                    # #129 forward-fix: post-cutover the PG has a SPLIT-OWNERSHIP schema
                    # (#92) — tables like 'recommendations' are owned by role 'halcyon',
                    # so ALTER / CREATE INDEX issued by 'halcyon_app' raise
                    # "must be owner of table ...". This is EXPECTED and benign: Phase-1
                    # CREATE TABLE IF NOT EXISTS already committed (any genuinely-missing
                    # table — the self-heal's actual purpose — is provisioned), and the
                    # non-owned tables are managed by their owner. SKIP, do NOT halt.
                    # Mirrors startup_checks.py:337. A genuinely-unreachable PG raises
                    # psycopg2.OperationalError instead, which still propagates to the
                    # fatal contract below — fail-fast on a down write-target is preserved.
                    logger.info(
                        "[WATCH] Postgres schema: tables owned by another role skipped (expected): %s",
                        _own_exc,
                    )
            create_all_tables(DB_PATH)
            ensure_columns(DB_PATH)
            logger.info("[WATCH] All SQLite tables verified/created")

            # Populate research docs from markdown files
            try:
                from src.data_collection.docs_collector import populate_research_docs
                result = populate_research_docs()
                logger.info("[WATCH] Research docs: %s", result)
            except Exception as e:
                logger.debug("[WATCH] Docs population failed: %s", e)
        except Exception as exc:
            logger.critical("[WATCH] SCHEMA CREATION FAILED: %s — cannot continue", exc)
            try:
                from src.notifications.telegram import send_telegram
                send_telegram(f"\U0001f534 SCHEMA CREATION FAILED: {exc} — watch loop halted")
            except Exception:
                pass
            import sys
            sys.exit(1)

    @staticmethod
    def _configure_database():
        """Configure the database for production use (Sprint 5 T2.12).

        Engine-agnostic startup path:

        - connect_db_with_pg_retry(DB_PATH, max_attempts=5, backoff_seconds=30)
          replaces the bare connect_db(DB_PATH). On PG transient failures the
          helper retries with 30s backoff up to 5 attempts; on exhaustion it
          writes data/watchdog.txt and calls sys.exit(1) (M3 fast-exit).
        - configure_sqlite_for_production(conn) replaces the inline PRAGMA
          cluster (busy_timeout, journal_mode=WAL, synchronous=NORMAL,
          integrity_check). The helper internally checks
          isinstance(conn, PostgresConnectionWrapper) and no-ops + warns on
          PG, so this call is safe to make unconditionally.

        M3 invariant — SystemExit must propagate, not be swallowed:
          connect_db_with_pg_retry exits with code 1 on PG exhaustion,
          raising SystemExit. SystemExit inherits from BaseException, NOT
          Exception, so `except Exception` below does NOT catch it. The
          explicit `except SystemExit: raise` pass-through is belt-and-braces
          insurance against a future refactor accidentally widening the
          handler. Without this propagation, the watch loop would become a
          zombie-watchdog that survives DB outages instead of being restarted
          by NSSM. Tests pinning this invariant live in
          tests/test_watch_pragma_isolation.py.
        """
        try:
            conn = connect_db_with_pg_retry(
                DB_PATH, max_attempts=5, backoff_seconds=30,
            )
            try:
                configure_sqlite_for_production(conn)
            finally:
                conn.close()
            logger.info(
                "[DB] Configured: WAL mode, synchronous=NORMAL, "
                "busy_timeout=30000ms (PG path is no-op)"
            )
        except RuntimeError as exc:
            # configure_sqlite_for_production raises RuntimeError on
            # integrity_check failure. Surface via Telegram + sys.exit(1) so
            # NSSM restarts cleanly.
            if "integrity_check" in str(exc):
                logger.critical("[DB] INTEGRITY CHECK FAILED: %s", exc)
                try:
                    from src.notifications.telegram import send_telegram
                    send_telegram("\U0001f534 DATABASE CORRUPTED \u2014 integrity check failed. Watch loop halted.")
                except Exception:
                    pass
                import sys
                sys.exit(1)
            logger.warning("[DB] Configuration failed: %s", exc)
        except SystemExit:
            # M3 invariant: connect_db_with_pg_retry calls sys.exit(1) on PG
            # exhaustion; integrity_check branch above also re-exits.
            # SystemExit inherits from BaseException so the `except Exception`
            # below does NOT catch it; this explicit pass-through is
            # belt-and-braces against a future refactor.
            raise
        except Exception as exc:
            logger.warning("[DB] Configuration failed: %s", exc)

    @staticmethod
    def _check_row_counts():
        """Sanity-check that critical tables aren't unexpectedly empty."""
        try:
            conn = connect_db(DB_PATH)
            row = conn.execute("SELECT COUNT(*) FROM shadow_trades").fetchone()
            count = _scalar(row)
            conn.close()
            if count == 0:
                logger.warning("[DB] shadow_trades is empty \u2014 possible fresh database or corruption recovery")
                try:
                    from src.notifications.telegram import send_telegram
                    send_telegram("\u26a0\ufe0f Database has 0 shadow trades \u2014 verify this is expected")
                except Exception:
                    pass
        except Exception as exc:
            logger.warning("[DB] Row count check failed: %s", exc)

    def _backup_database(self):
        """Create a daily backup of the SQLite database using the Online Backup API."""
        from pathlib import Path

        backup_dir = Path("backups")
        backup_dir.mkdir(exist_ok=True)

        backup_path = backup_dir / f"halcyon_{datetime.now(ET).strftime('%Y%m%d')}.sqlite3"
        try:
            src = sqlite3.connect(DB_PATH)
            dst = sqlite3.connect(str(backup_path))
            src.backup(dst)
            dst.close()
            src.close()

            # Prune old backups (keep last 7)
            backups = sorted(backup_dir.glob("halcyon_*.sqlite3"))
            for old in backups[:-7]:
                old.unlink()

            logger.info("[DB] Backup created: %s", backup_path.name)
        except Exception as exc:
            logger.warning("[DB] Backup failed: %s", exc)

    # ── PID lockfile to prevent duplicate watch loops ──────────────────
    LOCKFILE = Path("data/watch.lock")

    @staticmethod
    def _is_pid_alive(pid: int) -> bool:
        """Check if a process is alive (cross-platform)."""
        if sys.platform == "win32":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            SYNCHRONIZE = 0x00100000
            handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # exists but we lack permission

    def _acquire_lock(self):
        """Acquire PID lockfile. Exits if another watch loop is running."""
        self.LOCKFILE.parent.mkdir(exist_ok=True)
        if self.LOCKFILE.exists():
            try:
                old_pid = int(self.LOCKFILE.read_text().strip())
                if self._is_pid_alive(old_pid):
                    logger.error(
                        "[WATCH] Another watch loop is running (PID %d). Exiting.",
                        old_pid,
                    )
                    print(f"[WATCH] ERROR: Another watch loop is already running (PID {old_pid})")
                    print(f"[WATCH] Kill it first:  taskkill /PID {old_pid} /F")
                    sys.exit(1)
                else:
                    logger.warning(
                        "[WATCH] Removing stale lockfile (was PID %s)",
                        self.LOCKFILE.read_text().strip(),
                    )
                    self.LOCKFILE.unlink(missing_ok=True)
            except ValueError:
                self.LOCKFILE.unlink(missing_ok=True)
        self.LOCKFILE.write_text(str(os.getpid()))
        logger.info("[WATCH] Acquired lockfile (PID %d)", os.getpid())
        # atexit catches normal Python exits (SystemExit, sys.exit, top-of-module
        # exceptions); Python's signal.signal on Windows only catches a few
        # signals. Neither catches `taskkill /F` — Windows force-kill sends no
        # interceptable signal, so a stale lockfile after force-kill is
        # expected. The startup path already detects and removes stale locks,
        # so this is belt-and-suspenders for normal shutdowns only.
        import atexit
        atexit.register(self._release_lock)

    def _release_lock(self):
        """Release PID lockfile if it belongs to this process."""
        try:
            if self.LOCKFILE.exists():
                if self.LOCKFILE.read_text().strip() == str(os.getpid()):
                    self.LOCKFILE.unlink(missing_ok=True)
                    logger.info("[WATCH] Released lockfile")
        except Exception:
            pass

    def _run_sync_body(self):
        """Main watch loop. Checks every 60 seconds.

        Architecture: A single while-loop that sleeps 60s between iterations.
        Each iteration checks the current ET time and dispatches tasks based on
        hour/minute windows. The numbered sections below correspond to the
        daily cadence timeline:

          0. Ollama warm-up (9:25 AM) — warm CUDA kernels before first scan
          0.5. AI Council (8:30 AM) — regime assessment before market open
          1. Morning watchlist (8:00 AM) — rank universe, email top picks
          1.5. Position monitor (every 15m) — Tier 1, Strategy Decision #22
          2. Market scans (every 30m) — Tier 2, the core pipeline
          2.5. Sentiment refresh (every 60m) — Tier 3
          3. EOD recap (4:00 PM) — daily summary
          4. Audit + validation + build score (4:15-4:45 PM)
          5. Training collection + trigger (4:30-5:00 PM)
          6. Saturday reports (Saturday 9 AM)
          7. Between-scan scoring (market hours, gaps between scans)
          8. Status logging
          9. Telegram command polling

          Overnight (--overnight flag, outside market hours):
            5:15 AM — Morning VRAM handoff (Ollama reload)
            5:30 PM — Post-close capture
            6:00 PM — Training collection
            6:50 PM — Evening VRAM handoff (training subprocess)
            9:30 PM — Data collection (12+ collectors)
            10:00 PM — News ingestion
            11:00 PM — Enrichment pre-cache
            6:00 AM — Pre-market refresh
        """
        self._acquire_lock()

        # T5: code-level startup guard for ArcisOllamaWatchdog (no DependOnService
        # in SCM — a wedge there caused a 13-min loop-down; we guard in code instead).
        _assert_ollama_watchdog_present()

        # Logging is already configured by main.py → setup_logging() which sets up
        # console + rotating file handler (logs/arcis.log). Only add the DB handler
        # here for the dashboard log viewer. Do NOT add another file handler — that
        # caused every message to appear twice (once per handler).
        root = logging.getLogger()

        # Guard against duplicate DB handlers on restart
        if not any(isinstance(h, DBLogHandler) for h in root.handlers):
            db_handler = DBLogHandler()
            root.addHandler(db_handler)

        self._print_banner()

        # Ensure all expected tables exist
        self._ensure_all_tables()

        # Configure SQLite for production use (WAL mode) + integrity check
        self._configure_database()

        # Sanity-check critical table row counts
        self._check_row_counts()

        # Watchdog: clear any diagnostic_runs rows stuck in queued/running (#56)
        try:
            swept = sweep_stale_diagnostic_runs(DB_PATH)
            if swept:
                logger.warning("[WATCH] Watchdog swept %d stale diagnostic_run(s) to failed", swept)
            else:
                logger.info("[WATCH] Watchdog: no stale diagnostic_runs found")
        except Exception as exc:
            logger.warning("[WATCH] Stale diagnostic_runs sweep failed: %s", exc)

        # Phase B: register handlers for the extracted overnight schedule.
        # Inline time-window blocks below still fire for non-extracted tasks;
        # overnight handlers fire via _dispatch_sync inside the tick loop.
        self._register_default_handlers()

        # SD#41 — Announce IB cold-storage state once at startup. Subsequent code
        # paths (broker_factory, executor, reconcile) also gate on this flag, but
        # logging it here gives operators a single unambiguous status line.
        if not self.config.get("trading", {}).get("ib_enabled", False):
            logger.info("[WATCH] IB integration dormant per SD#41. Alpaca-only mode.")

        # Validate starting capital
        capital = self.config.get("risk", {}).get("starting_capital", 0)
        if capital < 10000:
            logger.warning("[WATCH] ⚠️ starting_capital is $%d — this seems low for paper trading. Expected $100,000.", capital)
            print(f" ⚠️ WARNING: starting_capital is ${capital:,} — expected $100,000 for paper trading")

        # Apply dashboard config overrides
        try:
            from src.config_overrides import get_effective_config
            self.config = get_effective_config(self.config)
            logger.info("[WATCH] Config overrides applied")
        except Exception as e:
            logger.debug("Config overrides not available: %s", e)

        # Command executor callback for sync thread
        def _on_commands_pulled(commands):
            try:
                from src.commands.executor import execute_commands
                execute_commands(commands, self.config)
            except Exception as exc:
                logger.error("[WATCH] Command execution failed: %s", exc)

        # Render cloud sync removed in SP5 §J5/§J6 Phase 3-revised (one-DB
        # cutover): Postgres is now the production database; there is no
        # remote PG to sync TO. The local watch loop writes directly to PG
        # via connect_db() when ARCIS_PG_CUTOVER_ENABLED=1. The
        # `_on_commands_pulled` callback path that this block previously
        # wired into the render_sync thread is now invoked via the cloud
        # dashboard's command endpoints; see src/api/cloud_routes/commands.py.
        print(" Render sync: removed (one-DB cutover)")

        # Register signal handlers for graceful shutdown
        def _handle_shutdown(signum, frame):
            sig_name = signal.Signals(signum).name
            logger.info("[WATCH] Received %s — initiating graceful shutdown", sig_name)
            print(f"\n[WATCH] Received {sig_name} — shutting down gracefully...")
            self._shutdown_requested = True

        try:
            signal.signal(signal.SIGTERM, _handle_shutdown)
        except ValueError:
            pass  # Not main thread — handler already registered in run()
        # Write initial heartbeat
        Path("data").mkdir(exist_ok=True)
        Path("data/watchdog.txt").write_text(datetime.now(ET).isoformat())

        try:
            while not self._shutdown_requested:
                now = self._clock()

                # Write heartbeat every iteration (~60s)
                try:
                    Path("data/watchdog.txt").write_text(now.isoformat())
                except Exception:
                    pass
                # DB-side heartbeat for platform_events (T7 / #67)
                try:
                    from src.notifications.platform_events import write_heartbeat  # lazy import
                    write_heartbeat()
                    logger.debug("[WATCH] platform_events heartbeat written")
                except Exception as exc:
                    logger.warning("[WATCH] platform_events heartbeat failed: %s", exc)

                # Reset daily state at midnight
                today = now.date()
                if self._today is not None and today != self._today:
                    self._reset_daily_state()
                    print(f"[WATCH] New day: {today}. Daily state reset.")
                    self._reprint_banner_on_next_cycle = True
                self._today = today

                # Phase B: fire registered on_tick handlers (overnight schedule
                # lives here — see src/scheduler/watch_handlers.py).
                self._dispatch_sync("on_tick", now)

                hour = now.hour
                time_str = now.strftime("%H:%M")

                # 0. Ollama warm-up (9:25 AM — before first scan)
                if (hour == 9 and now.minute >= 25 and now.minute < 30
                        and not self._ollama_warmup_done):
                    # Fix for #257: only set done-flag on success
                    if self._safe_run("Ollama warm-up", self._run_ollama_warmup).is_healthy:
                        self._ollama_warmup_done = True

                if (hour == 9 and now.minute < 5 and now.weekday() < 5
                        and not self._premarket_bracket_check_done):
                    # Fix for #257: only set done-flag on success
                    if self._safe_run(
                        "pre-market bracket check",
                        lambda: self._run_bracket_health_check("premarket"),
                    ).is_healthy:
                        self._premarket_bracket_check_done = True

                # 0.5. Daily AI Council (8:30 AM — after watchlist, before first scan)
                if (hour == 8 and now.minute >= 30 and not self._council_done):
                    # Fix for #257: only set done-flag on success
                    if self._safe_run("daily council", self._run_daily_council).is_healthy:
                        self._council_done = True

                # 0.7. Tier 4: Fundamentals refresh (daily at 7:30 AM)
                if (hour == 7 and now.minute >= 30 and not self._fundamentals_done
                        and now.weekday() < 5):
                    try:
                        from src.scheduler.fundamentals_refresh import run_fundamentals_refresh
                        # Fix for #257: only set done-flag on success
                        if self._safe_run("fundamentals refresh",
                                          lambda: run_fundamentals_refresh(self.config)).is_healthy:
                            self._fundamentals_done = True
                    except Exception as e:
                        logger.warning("[WATCH] Fundamentals refresh failed: %s", e)

                # 1. Morning watchlist
                if hour == self.morning_hour and not self._morning_done:
                    # Fix for #257: only set done-flag on success
                    if self._safe_run("morning watchlist", self._run_morning_watchlist).is_healthy:
                        self._morning_done = True

                # 1.5. Tier 1: Position monitor (every 15 min during market hours)
                # Strategy Decision #22: 4-tier multi-cadence scanning.
                # Tier 1 (15m): position monitoring, bracket health
                # Tier 2 (30m): full universe scan
                # Tier 3 (60m): sentiment refresh
                # Tier 4 (daily): fundamentals, data collection
                if (self.market_open_hour <= hour < self.market_close_hour
                    and now.weekday() < 5
                    and (not self._last_position_monitor_time
                         or (now - self._last_position_monitor_time).total_seconds() > 900)):
                    try:
                        from src.scheduler.position_monitor import run_position_monitor
                        self._safe_run("position monitor",
                                       lambda: run_position_monitor(self.config))
                        self._last_position_monitor_time = now
                    except Exception as e:
                        logger.warning("[WATCH] Position monitor failed: %s", e)

                # 2. Market hours scan (Tier 2: every 30 min)
                if self._should_scan(now):
                    if self._scan_in_progress:
                        logger.warning("[WATCH] Previous scan still running — skipping this cycle")
                    else:
                        print(f"[WATCH] {time_str} ET -- market open, scanning...")
                        self._scan_in_progress = True
                        try:
                            self._safe_run("scan", self._run_scan)
                        finally:
                            self._scan_in_progress = False
                        self._last_scan_time = now
                    # 1E. Check VIX regime alert after each scan
                    self._safe_run("VIX regime check", self._check_vix_regime_alert)

                    # 1F. Mean reversion scan (after main scan)
                    self._safe_run("MR scan", self._run_mr_scan)

                # 2.5. Tier 3: Sentiment refresh (every 60 min during market hours)
                if (self.market_open_hour <= hour < self.market_close_hour
                    and now.weekday() < 5
                    and (not self._last_sentiment_refresh_time
                         or (now - self._last_sentiment_refresh_time).total_seconds() > 3600)):
                    try:
                        from src.scheduler.sentiment_scanner import run_sentiment_refresh
                        self._safe_run("sentiment refresh",
                                       lambda: run_sentiment_refresh(self.config))
                        self._last_sentiment_refresh_time = now
                    except Exception as e:
                        logger.warning("[WATCH] Sentiment refresh failed: %s", e)

                # 3. EOD recap
                elif hour == self.eod_hour and not self._eod_done:
                    # Fix for #257: only set done-flags on success
                    if self._safe_run("EOD recap", self._run_eod_recap).is_healthy:
                        self._eod_done = True
                    # Check for risk tier transition (Strategy Decision #26)
                    try:
                        from src.risk.governor import check_tier_transition
                        transition = check_tier_transition(self.config, DB_PATH)
                        if transition:
                            msg = (
                                f"\U0001f4ca RISK TIER CHANGE\n"
                                f"Equity: ${transition['equity']:,.2f}\n"
                                f"Previous: {transition['prev_tier']}\n"
                                f"New: {transition['new_tier']}\n"
                                f"Max risk/trade: {transition['new_risk_pct']:.1%}"
                            )
                            logger.info("[RISK] %s", msg)
                            notify_cfg = self.config.get("risk", {}).get("risk_scaling", {})
                            if notify_cfg.get("notify_on_transition", True):
                                from src.notifications.telegram import send_telegram, is_telegram_enabled
                                if is_telegram_enabled():
                                    send_telegram(msg)
                    except Exception as e:
                        logger.debug("[RISK] Tier transition check skipped: %s", e)
                    # H2. Daily metric snapshot (every trading day, not just Saturday)
                    if not self._daily_metric_snapshot_done:
                        if self._safe_run("daily metric snapshot", self._save_daily_metric_snapshot).is_healthy:
                            self._daily_metric_snapshot_done = True
                    # 1C. EOD P&L report via Telegram
                    if not self._eod_report_done:
                        if self._safe_run("EOD Telegram report", self._send_eod_report).is_healthy:
                            self._eod_report_done = True
                        # ── Telegram: notify_daily_summary (after eod report) ──
                        with connect_db(DB_PATH) as _conn:
                            _conn.row_factory = sqlite3.Row
                            _today = datetime.now(ET).strftime("%Y-%m-%d")
                            _row = _conn.execute(
                                "SELECT COUNT(*) FROM shadow_trades WHERE status='open'"
                                " AND COALESCE(quarantined, 0) = 0"
                            ).fetchone()
                            _open = _scalar(_row)
                            _row = _conn.execute(
                                "SELECT COUNT(*) FROM shadow_trades WHERE status='closed' "
                                "AND actual_exit_time LIKE ? AND COALESCE(quarantined, 0) = 0",
                                (f"{_today}%",)
                            ).fetchone()
                            _closed_today = _scalar(_row)
                            _pnl_row = _conn.execute(
                                "SELECT COALESCE(SUM(pnl_dollars),0) FROM shadow_trades "
                                "WHERE status='closed' AND actual_exit_time LIKE ?"
                                " AND COALESCE(quarantined, 0) = 0",
                                (f"{_today}%",)
                            ).fetchone()
                            _total_pnl = _pnl_row[0] if _pnl_row else 0.0
                        safe_send(
                            "daily_summary",
                            total_pnl=_total_pnl,
                            open_trades=_open,
                            closed_today=_closed_today,
                        )

                # 4. Daily audit (4:15 PM ET)
                elif (hour == 16 and now.minute >= 15 and now.minute < 30
                      and not self._daily_audit_done):
                    # Fix for #257: only set done-flag on success
                    if self._safe_run("daily audit", self._run_daily_audit).is_healthy:
                        self._daily_audit_done = True
                    # Send daily scoring summary via Telegram
                    if self._daily_scored > 0:
                        with connect_db(DB_PATH) as conn:
                            _row = conn.execute(
                                "SELECT COUNT(*) FROM training_examples WHERE quality_score_auto IS NULL"
                            ).fetchone()
                            backlog = _scalar(_row)
                        safe_send("scoring_summary", scored_today=self._daily_scored, backlog=backlog)

                # 4b. Daily system validation (4:30 PM ET)
                # Sprint 0 Wave 2a (DONE-FLAG-A, T9): wrap in _safe_run so the
                # done-flag is conditional on success and per-task backoff
                # is wired in (matches the discipline of every other done-flag
                # block and the CLAUDE.md "_safe_run returns bool" rule).
                elif (hour == 16 and now.minute >= 30 and now.minute < 45
                      and not self._daily_validation_done):
                    if self._safe_run("daily validation", self._run_daily_validation).is_healthy:
                        self._daily_validation_done = True

                # 4c. Daily build score snapshot (4:45 PM ET)
                # Sprint 0 Wave 2a (DONE-FLAG-B, T9): wrap in _safe_run so the
                # done-flag is conditional on success and per-task backoff
                # is wired in.
                if (hour == 16 and now.minute >= 45
                        and not self._daily_build_score_done):
                    if self._safe_run("daily build score", self._run_daily_build_score).is_healthy:
                        self._daily_build_score_done = True

                if (hour == 16 and now.minute >= 30 and now.minute < 35
                        and not self._postclose_bracket_check_done):
                    # Fix for #257: only set done-flag on success
                    if self._safe_run(
                        "post-close bracket check",
                        lambda: self._run_bracket_health_check("postclose"),
                    ).is_healthy:
                        self._postclose_bracket_check_done = True

                # 4b. Post-close paper reconciliation (4:30–4:35 PM ET)
                if (hour == 16 and now.minute >= 30 and now.minute < 35
                        and not self._postclose_reconcile_done):
                    # Fix for #257: only set done-flag on success
                    if self._safe_run(
                        "post-close reconciliation",
                        self._run_postclose_reconciliation,
                    ).is_healthy:
                        self._postclose_reconcile_done = True

                # 4b2. Daily methodology gate sweep (16:35 ET — after post-close
                # reconcile). Evaluates all shadow_trading + backtested strategies
                # and persists gate_proposal events. Sprint 2 T4.
                # Late-import inside the method body: top-level import of
                # platform.promotion creates a circular-import risk (promotion.py
                # imports from src.config which triggers watch.py's own import
                # chain). This pattern matches how attribution_resolution_and_notify
                # is imported at its call site above.
                if (
                    hour == 16
                    and now.minute >= 35
                    and not self._strategy_gate_done
                ):
                    from src.platform.promotion import (
                        run_daily_gate_for_all_active_strategies,
                    )
                    if self._safe_run(
                        "strategy methodology gate",
                        lambda: run_daily_gate_for_all_active_strategies(
                            db_path=DB_PATH,
                            notify=self._notify_gate_proposal,
                        ),
                    ).is_healthy:
                        self._strategy_gate_done = True

                # 4c. Attribution outcome resolution (after market close)
                # Window widened from 4:30-4:35 to 4:15-22:00 so NSSM restarts
                # don't miss the window. The resolver is idempotent — safe to retry.
                if (16 <= hour < 22 and (hour > 16 or now.minute >= 15)
                        and not self._attribution_resolution_done):
                    from src.scheduler.overnight import run_attribution_resolution_and_notify
                    # Fix for #257: only set done-flag on success
                    if self._safe_run(
                        "attribution outcome resolution",
                        run_attribution_resolution_and_notify,
                    ).is_healthy:
                        self._attribution_resolution_done = True

                # 5. Training data collection (after market close)
                elif (self.training_enabled and 16 <= hour < 22
                      and (hour > 16 or now.minute >= 30)
                      and not self._training_collection_done):
                    # Fix for #257: only set done-flags on success
                    if self._safe_run("training collection", self._run_training_collection).is_healthy:
                        self._training_collection_done = True
                    # 1D. Data asset report after training collection
                    if not self._data_asset_report_done:
                        if self._safe_run("data asset report", self._send_data_asset_report).is_healthy:
                            self._data_asset_report_done = True

                # 5. Overnight training trigger (5:00 PM ET)
                elif (self.training_enabled and hour == 17
                      and not self._training_run_done):
                    # Fix for #257: only set done-flag on success
                    if self._safe_run("training check", self._run_training_check).is_healthy:
                        self._training_run_done = True

                # 5b. Model regression check (5:05 PM ET, after market close)
                if (hour == 17 and now.minute >= 5 and now.minute < 15
                        and not self._model_regression_done):
                    if self._safe_run("model regression check",
                                      self._run_model_regression_check).is_healthy:
                        self._model_regression_done = True

                # 6. Saturday training report (9 AM ET)
                elif (self.training_enabled and now.weekday() == 5
                      and hour == 9 and not self._saturday_reports_done):
                    # Fix for #257: only set done-flag on success
                    if self._safe_run("Saturday reports", self._run_saturday_reports).is_healthy:
                        self._saturday_reports_done = True

                # H1. Research synthesis (Sunday 6 PM ET)
                elif (now.weekday() == 6 and hour == 18
                      and not self._research_synthesis_done):
                    # Fix for #257: only set done-flag on success
                    if self._safe_run("research synthesis", self._run_research_synthesis).is_healthy:
                        self._research_synthesis_done = True

                # 1H. Weekly digest (Sunday 8 PM ET)
                elif (now.weekday() == 6 and hour == 20
                      and not self._weekly_digest_done):
                    # Fix for #257: only set done-flag on success
                    if self._safe_run("weekly digest", self._send_weekly_digest).is_healthy:
                        self._weekly_digest_done = True

                # Weekly stress test (Sunday 9 PM ET)
                elif (now.weekday() == 6 and hour == 21
                      and not self._stress_test_done):
                    # Fix for #257: only set done-flag on success
                    if self._safe_run("weekly stress test", self._run_stress_test).is_healthy:
                        self._stress_test_done = True

                # Weekly simulation engine (Sunday 9:30 PM ET, after stress test)
                elif (now.weekday() == 6 and hour == 21 and now.minute >= 30
                      and not self._simulation_done):
                    if self._safe_run("weekly simulation", self._run_simulation_engine).is_healthy:
                        self._simulation_done = True

                # #115 T8 — Email weekly tier (Sunday 18:00 ET, 5-min window).
                # Independent `if` (not elif) so it fires alongside research
                # synthesis at the same Sun 18:00 slot. Holiday-skip does NOT
                # apply to weekly (DD-21). The Telegram-style Sunday 8 PM
                # weekly_digest above is left untouched (scope-fence T8).
                self._maybe_flush_email_weekly_tier(now)

                # Action reminders (8 PM daily via Telegram)
                # Sprint 0 Wave 2a (DONE-FLAG-C, T9): the done-flag was set
                # OUTSIDE the try block, so any raise from check_action_reminders
                # would still mark the day done and lock out retries until the
                # next midnight reset. Now wrapped in _safe_run so the flag is
                # only set on success and per-task backoff applies (matches
                # the discipline of every other done-flag block).
                if hour == 20 and not self._action_reminders_done:
                    if self._safe_run("action reminders", self._run_action_reminders).is_healthy:
                        self._action_reminders_done = True

                # 1L. Earnings proximity warning (8:00 AM weekdays)
                if (hour == 8 and now.minute < 5 and now.weekday() < 5
                        and not self._earnings_warning_done):
                    # Fix for #257: only set done-flag on success
                    if self._safe_run("earnings proximity", self._check_earnings_proximity).is_healthy:
                        self._earnings_warning_done = True

                # Overnight schedule: 14 handlers in src/scheduler/watch_handlers.py
                # registered by _register_default_handlers() and dispatched via
                # _dispatch_sync("on_tick", now) above. See Phase B in
                # docs/sprints/sprint-asyncio-handler-refactor.md.

                # 7. Between-scan scoring (market hours only)
                if self._is_market_open(now) and self._scorer.is_scoring_window():
                    if not self._scoring_in_progress:
                        self._scoring_in_progress = True
                        try:
                            result = self._scorer.score_batch()
                            if result["scored"] > 0:
                                self._daily_scored += result["scored"]
                                print(f"[WATCH] Scored {result['scored']} examples "
                                      f"({result['remaining']} remaining, "
                                      f"stopped: {result['stopped_reason']})")
                        except Exception as e:
                            logger.debug("[WATCH] Scoring error: %s", e)
                        finally:
                            self._scoring_in_progress = False

                if self._is_market_open(now):
                    if (
                        self._last_bracket_check_time is None
                        or (now - self._last_bracket_check_time).total_seconds() >= 300
                    ):
                        self._safe_run(
                            "intraday bracket check",
                            lambda: self._run_bracket_health_check("intraday"),
                        )
                        self._last_bracket_check_time = now

                # 8. Status log
                if not (self._should_scan(now) or
                        (hour == self.morning_hour and not self._morning_done) or
                        (hour == self.eod_hour and not self._eod_done)):
                    if self._is_market_open(now):
                        scored_str = (f", {self._daily_scored} scored"
                                      if self._daily_scored > 0 else "")
                        print(f"[WATCH] {time_str} ET -- market open, next scan in "
                              f"{self._minutes_until_next_scan(now):.0f} min{scored_str}")
                    elif not (self.overnight and now.weekday() < 5):
                        print(f"[WATCH] {time_str} ET -- market closed")

                # 9. Poll Telegram commands
                try:
                    from src.notifications.telegram_commands import (
                        poll_commands, handle_command,
                    )
                    from src.notifications.telegram import send_telegram, is_telegram_enabled
                    if is_telegram_enabled():
                        commands, self._tg_last_update_id = poll_commands(
                            self._tg_last_update_id
                        )
                        for cmd in commands:
                            response = handle_command(cmd["command"], cmd["args"])
                            send_telegram(response)
                except Exception as e:
                    logger.warning("[WATCH] Telegram command polling failed: %s", e)

                # Email digest schedule (sends 4 daily digests in digest mode)
                self._check_digest_schedule()

                # Periodic status heartbeat (every 60 min during market hours)
                is_mkt = (self.market_open_hour <= now.hour < self.market_close_hour
                          and now.weekday() < 5)
                if (is_mkt
                    and (not self._last_status_print
                         or (now - self._last_status_print).total_seconds() > 3600)):
                    self._print_status_heartbeat()
                    self._last_status_print = now

                # Reprint full banner on significant events
                if self._reprint_banner_on_next_cycle:
                    self._print_banner()

                # IB integration sprint: check IB connection health every ~5 min
                # during market hours. Only runs when live_trading.broker == "ib"
                # and live_trading.enabled == True. Avoids alert spam via
                # _ib_disconnect_alerted flag.
                live_cfg = self.config.get("live_trading", {})
                # SD#41 — Skip IB health check entirely when cold-stored.
                ib_globally_enabled = self.config.get("trading", {}).get("ib_enabled", False)
                if (ib_globally_enabled
                        and live_cfg.get("broker") == "ib"
                        and live_cfg.get("enabled", False)
                        and self._is_market_open(now)):
                    ib_check_due = (
                        self._last_ib_health_check is None
                        or (now - self._last_ib_health_check).total_seconds() >= 300
                    )
                    if ib_check_due:
                        self._last_ib_health_check = now
                        try:
                            from src.trading.broker_factory import get_live_broker
                            broker = get_live_broker(self.config)
                            if not broker.is_connected():
                                logger.error(
                                    "[WATCH] IB broker disconnected during market hours"
                                )
                                if not self._ib_disconnect_alerted:
                                    self._ib_disconnect_alerted = True
                                    try:
                                        from src.notifications.telegram import (
                                            send_telegram, is_telegram_enabled,
                                        )
                                        if is_telegram_enabled():
                                            send_telegram(
                                                "\U0001f534 IB DISCONNECTED during market hours "
                                                "— attempting reconnect..."
                                            )
                                    except Exception:
                                        pass
                                # Attempt reconnect via broker internals
                                try:
                                    broker._ensure_connected()
                                    if broker.is_connected():
                                        logger.info(
                                            "[WATCH] IB broker reconnected successfully"
                                        )
                                        self._ib_disconnect_alerted = False
                                        try:
                                            from src.notifications.telegram import (
                                                send_telegram, is_telegram_enabled,
                                            )
                                            if is_telegram_enabled():
                                                send_telegram(
                                                    "\u2705 IB reconnected successfully"
                                                )
                                        except Exception:
                                            pass
                                except Exception as reconn_exc:
                                    logger.error(
                                        "[WATCH] IB reconnect failed: %s", reconn_exc
                                    )
                            else:
                                # Connection is healthy — clear alert flag so a
                                # future disconnect triggers a fresh alert
                                if self._ib_disconnect_alerted:
                                    self._ib_disconnect_alerted = False
                        except Exception as ib_exc:
                            logger.debug(
                                "[WATCH] IB health check error: %s", ib_exc
                            )

                # Sprint 4 Task 9: platform tick — research strategies on their
                # own cadence (spec line 991-994). Runs every outer cycle so the
                # per-strategy interval-gating inside the method stays responsive.
                # _run_platform_shadow_tick already isolates per-strategy failures;
                # wrap in _safe_run so a top-level exception can't kill swing.
                self._safe_run("platform shadow tick", self._run_platform_shadow_tick)

                # Tick: drift detector (Wave C T4, 30min cadence) — see manual_intervention_drift.py
                # Internal cadence gate: fires every 30 min. safe_send called here,
                # NOT inside the detector (recursion-hazard guard).
                if self._safe_run("drift detector", self.tick_drift_detector):
                    pass  # cadence managed by _last_drift_detector_time

                # Tick: digest queue flush (T11 D2, configurable cadence default 60min)
                # T12 D3 will replace stub dispatcher with real safe_send wiring.
                if self._safe_run("digest queue", self.tick_digest_queue):
                    pass  # cadence managed by _last_digest_queue_time

                # Tick: alert silence detector (T14 D5, 5-min cadence)
                if self._safe_run("alert silence", self.tick_alert_silence):
                    pass  # cadence managed by _last_alert_silence_time

                # Tick: runtime watchdog-liveness monitor (T18, ~60s cadence)
                # Emits a loud alarm on RUNNING→not-RUNNING transition.
                # Fail-soft — never blocks the trading path.
                if self._safe_run("watchdog liveness", self.tick_watchdog_liveness):
                    pass  # cadence managed by _watchdog_liveness_last_check

                self._sleep(60)

        except (KeyboardInterrupt, SystemExit):
            print(f"\nShutting down watch mode...")
            print(f"Final shadow status:")
            print(f"  {self._trades_managed_today} trades managed today")
            print("Goodbye.")
        except Exception as fatal_exc:
            import traceback
            logger.critical("[WATCH] Fatal exception escaped main loop: %s", fatal_exc)
            logger.critical(traceback.format_exc())
            try:
                from src.notifications.telegram import send_telegram
                send_telegram(
                    f"🚨 <b>FATAL</b>: Watch loop crashed\n<code>{fatal_exc}</code>"
                )
            except Exception:
                pass
            raise
        finally:
            self._release_lock()

    def _register_default_handlers(self) -> None:
        """Wire the Phase B on_tick handlers. Called once at startup."""
        from functools import partial
        from src.scheduler.watch_handlers import ALL_HANDLERS
        for handler in ALL_HANDLERS:
            bound = partial(handler, self)
            bound.__name__ = handler.__name__
            self.on("on_tick")(bound)

    def _safe_run(self, name: str, func) -> "CollectorResult":
        """Run a function with per-task exponential backoff error recovery.

        Returns a CollectorResult (post-T19 flip; DD-15 r3): an ``ok`` result
        when ``func`` completes without raising (if ``func`` itself returns a
        CollectorResult, that result is returned verbatim), or a ``failed``
        result carrying the exception text. Gating callers branch on
        ``.is_healthy`` — never on bare object truthiness, since a
        CollectorResult is object-truthy for EVERY status (DD-15 r3 / §207).

        Fix for #147: Exponential backoff (10s -> 30s -> 60s cap).
        Fix for #231: Backoff is keyed per task name. A failing EDGAR collector
        only delays the next EDGAR attempt, not scans or reconciliation.
        Fix for #226: Callers must check .is_healthy before setting done-flags.
        Pattern: `if self._safe_run(...).is_healthy: self._done = True`
        """
        import traceback

        from src.data_collection.result import CollectorResult
        try:
            # Per-task backoff: wait before retrying a previously-failed task
            task_backoff = self._backoff.get(name, 0)
            if task_backoff > 0:
                print(f"[WATCH] Backoff: waiting {task_backoff}s before {name}...")
                time.sleep(task_backoff)
            outcome = func()
            # Success — reset backoff for this task only (not all tasks)
            self._consecutive_errors = 0
            self._backoff.pop(name, None)
            if isinstance(outcome, CollectorResult):
                return outcome
            return CollectorResult.ok_from_count(name, 0)
        except Exception as e:
            self._consecutive_errors += 1
            self._error_timestamps.append(time.time())
            # Exponential backoff: 10s, 30s, 60s, cap 60s — per task (#147)
            current = self._backoff.get(name, 0)
            if current == 0:
                self._backoff[name] = 10
            elif current < 60:
                self._backoff[name] = min(current * 3, 60)
            logger.error("[WATCH] Error in %s: %s", name, e)
            logger.error(traceback.format_exc())
            print(f"[WATCH] ERROR in {name}: {e} (error {self._consecutive_errors}, backoff {self._backoff.get(name, 0)}s)")
            # Instability alert: >5 errors in last hour
            cutoff = time.time() - 3600
            recent = sum(1 for t in self._error_timestamps if t > cutoff)
            if recent > 5 and not self._hourly_alert_sent:
                self._hourly_alert_sent = True
                try:
                    from src.notifications.telegram import send_telegram
                    send_telegram(f"\u26a0\ufe0f Watch loop unstable \u2014 {recent} exceptions in last hour")
                except Exception:
                    pass
            elif recent <= 5:
                self._hourly_alert_sent = False
            return CollectorResult.failed(name, errors=[str(e)])

    def _run_bracket_health_check(self, context: str) -> None:
        """Run bracket health monitoring for the requested scheduler context."""
        from src.shadow_trading.bracket_monitor import check_bracket_health

        result = check_bracket_health(context=context)
        logger.info(
            "[WATCH] Bracket check (%s): %d/%d protected",
            context,
            result.get("protected", 0),
            result.get("checked", 0),
        )

    def _run_postclose_reconciliation(self):
        """Reconcile paper positions against Alpaca and send Telegram summary."""
        from src.scheduler.overnight import run_postclose_reconciliation
        run_postclose_reconciliation()

    def _run_daily_audit(self):
        """Run the daily auditor agent."""
        from src.scheduler.overnight import run_daily_audit
        run_daily_audit()

    def _run_daily_validation(self):
        """4:30 PM ET — Run full system validator and notify Telegram on result.

        Sprint 0 Wave 2a (DONE-FLAG-A): extracted from inline try/except so the
        block can use _safe_run discipline (per-task backoff + conditional
        done-flag).
        """
        from src.evaluation.system_validator import (
            run_full_validation, save_validation_result,
        )
        from src.notifications.telegram import (
            notify_validation_summary, is_telegram_enabled,
        )
        result = run_full_validation()
        save_validation_result(result)
        if is_telegram_enabled():
            notify_validation_summary(result)
        logger.info(
            "[WATCH] Validation complete: %s (%dP/%dW/%dF)",
            result["overall_status"],
            result["checks_passed"],
            result["checks_warning"],
            result["checks_failed"],
        )

    def _run_daily_build_score(self):
        """4:45 PM ET — Persist the daily build-score snapshot.

        Sprint 0 Wave 2a (DONE-FLAG-B): extracted from inline try/except so the
        block can use _safe_run discipline.
        """
        from src.evaluation.build_score import persist_build_score
        result = persist_build_score()
        logger.info(
            "[WATCH] Build score persisted: %.1f",
            result.get("build_score", 0),
        )

    def _notify_gate_proposal(self, strategy_id: str, evidence: dict) -> None:
        """Emit a Telegram-friendly digest when the methodology gate issues a
        promote proposal for strategy_id.

        Sprint 2 T4: stub implementation. Logs the decision and, when Telegram
        is enabled, sends a concise one-line summary. Full digest formatting is
        deferred to T9 (operator runbook sprint).
        """
        decision = evidence.get("methodology_gate", {}).get("decision")
        logger.info(
            "[METHODOLOGY_GATE] proposal for %s: decision=%s",
            strategy_id,
            decision,
        )
        try:
            from src.notifications.telegram import send_telegram, is_telegram_enabled
            if is_telegram_enabled():
                send_telegram(
                    f"[METHODOLOGY_GATE] {strategy_id}: decision={decision}"
                )
        except Exception:
            logger.debug(
                "[METHODOLOGY_GATE] Telegram notify failed for %s", strategy_id
            )

    def _run_action_reminders(self):
        """8 PM ET — Send daily Telegram action reminders.

        Sprint 0 Wave 2a (DONE-FLAG-C): extracted from inline try/except so the
        block can use _safe_run discipline. Pre-fix, the done-flag was set
        OUTSIDE the try block, so any raise inside check_action_reminders
        marked the day done anyway and locked out retries.
        """
        from src.notifications.telegram_commands import check_action_reminders
        from src.notifications.telegram import is_telegram_enabled
        if is_telegram_enabled():
            sent = check_action_reminders()
            if sent:
                logger.info("[WATCH] Action reminders sent: %s", sent)

    def _run_training_collection(self):
        """Collect training data from closed trades."""
        from src.scheduler.overnight import run_training_collection
        run_training_collection()

    def _run_training_check(self):
        """Check if fine-tuning should be triggered."""
        from src.scheduler.overnight import run_training_check
        run_training_check()

    def _run_saturday_reports(self):
        """Generate and send Saturday training and CTO reports."""
        from src.scheduler.overnight import run_saturday_reports
        run_saturday_reports(db_path=DB_PATH)

    # ── Overnight Schedule Methods ────────────────────────────────────

    def _log_overnight_task(self, task_name: str, status: str,
                            started_at: str, finished_at: str | None = None,
                            result: str | None = None, error: str | None = None):
        """Log overnight task result to activity log."""
        from src.scheduler.overnight import log_overnight_task
        log_overnight_task(task_name, status, started_at, finished_at=finished_at,
                           result=result, error=error)

    def _run_model_regression_check(self):
        """5:05 PM ET — Check if current model underperforms previous on live trades."""
        from src.scheduler.overnight import run_model_regression_check
        run_model_regression_check()

    def _run_post_close_capture(self):
        """5:30 PM ET — Capture final closing prices, update MFE/MAE on open positions."""
        from src.scheduler.overnight import run_post_close_capture
        run_post_close_capture()

    def _run_overnight_training_collection(self):
        """6:00 PM ET — Collect training examples from today's closed trades."""
        from src.scheduler.overnight import run_overnight_training_collection
        run_overnight_training_collection()

    def _run_news_ingestion(self):
        """10:00 PM ET — Full universe news pull and caching."""
        from src.scheduler.overnight import run_news_ingestion
        run_news_ingestion()

    def _run_enrichment_precache(self):
        """11:00 PM ET — Pre-fetch fundamentals, insider data, macro for all tickers."""
        from src.scheduler.overnight import run_enrichment_precache
        run_enrichment_precache(self.config)

    def _run_1min_bar_collection(self):
        """11:30 PM ET — Collect 1-minute OHLCV bars for S&P 100 (Phase 6 intraday)."""
        from src.scheduler.overnight import run_1min_bar_collection
        run_1min_bar_collection()

    def _run_pre_market_refresh(self):
        """6:00 AM ET — Quick pre-market data check before morning watchlist."""
        from src.scheduler.overnight import run_pre_market_refresh
        run_pre_market_refresh()

    def _run_data_collection(self):
        """9:30 PM ET — Comprehensive market data collection."""
        from src.scheduler.overnight import run_data_collection
        run_data_collection(db_path=DB_PATH,
                            collector_failures=getattr(self, '_collector_failures', None))

    def _minutes_until_next_scan(self, now: datetime) -> float:
        """Calculate minutes until next scan is due."""
        if self._last_scan_time is None:
            return 0
        elapsed = (now - self._last_scan_time).total_seconds() / 60
        return max(0, self.scan_interval - elapsed)

    # ── Training-Lifecycle Methods (dual-GPU) ────────────────────────

    def _emit_training_health(self, detail: str) -> None:
        # Restored from T8 (commit 27ddc305) — dropped during v0.36.50 squash.
        try:
            upsert_daily_metric(
                "gpu_health_training_ok", 1.0,
                f'{{"gpu":"0","detail":"{detail}"}}',
            )
        except Exception as exc:
            logger.debug("[WATCH] gpu_health_training_ok metric failed: %s", exc)
        try:
            safe_send("gpu_health", direction="training", success=True, detail=detail)
        except Exception as exc:
            logger.debug("[WATCH] gpu_health event failed: %s", exc)

    def _run_evening_training_launch(self):
        """18:30-04:00 ET, market closed — launch the overnight GPU0 training run."""
        from src.training.trainer import run_fine_tune
        run_fine_tune()
        self._emit_training_health("evening training launched")

    def _run_morning_training_stop(self):
        """5:15 AM ET — stop the overnight GPU0 training subprocess (bounded)."""
        from src.training import training_control
        training_control.stop_training_bounded(_TRAINING_STOP_TIMEOUT_S)
        self._emit_training_health("morning training stop")

    def _run_market_open_training_stop(self):
        """>= 09:25 ET hard-ceiling safety net — stop GPU0 training (bounded)."""
        from src.training import training_control
        training_control.stop_training_bounded(_TRAINING_STOP_TIMEOUT_S)
        self._emit_training_health("market-open training stop")

    # ── AI Council ────────────────────────────────────────────────

    def _run_daily_council(self):
        """8:30 AM ET — Run the daily AI Council session."""
        from src.scheduler.overnight import run_daily_council
        run_daily_council()

    # ── Ollama Warm-Up ─────────────────────────────────────────────

    def _run_ollama_warmup(self):
        """9:25 AM ET — Full-length warm-up inference before first scan."""
        from src.scheduler.overnight import run_ollama_warmup
        run_ollama_warmup()

    # ── Pre-Market Pipeline Methods ──────────────────────────────────

    # ── Expanded Notification Methods ────────────────────────────────

    def _send_premarket_brief(self):
        """6:00 AM ET — Send pre-market brief with overnight context."""
        from src.scheduler.reports import send_premarket_brief
        send_premarket_brief()

    def _send_eod_report(self):
        """4:00 PM ET — Send end-of-day P&L report."""
        from src.scheduler.reports import send_eod_report
        send_eod_report()

    def _send_data_asset_report(self):
        """4:30 PM ET — Send data asset daily report."""
        from src.scheduler.reports import send_data_asset_report
        send_data_asset_report()

    def _check_vix_regime_alert(self):
        """Check VIX after each scan and alert on threshold crossings."""
        from src.scheduler.reports import check_vix_regime_alert
        self._last_vix_alert_level = check_vix_regime_alert(
            getattr(self, '_last_vix_alert_level', None))

    def _send_weekly_digest(self):
        """Sunday 8 PM ET — Send full weekly digest."""
        from src.scheduler.reports import send_weekly_digest
        send_weekly_digest()

    def _check_earnings_proximity(self):
        """8:00 AM ET — Check open positions for upcoming earnings."""
        from src.scheduler.reports import check_earnings_proximity
        check_earnings_proximity()

    def _run_premarket_rolling_features(self):
        """6:02 AM ET — Pre-compute rolling features for faster scans."""
        from src.scheduler.overnight import run_premarket_rolling_features
        run_premarket_rolling_features()

    def _run_premarket_training(self):
        """7:00 AM ET — Verify Ollama + generate self-blinded training data."""
        from src.scheduler.overnight import run_premarket_training
        run_premarket_training()

    def _run_premarket_news_scoring(self):
        """8:02 AM ET — Score overnight news for market impact."""
        from src.scheduler.overnight import run_premarket_news_scoring
        run_premarket_news_scoring()

    def _run_premarket_candidates(self):
        """9:00 AM ET — Pre-analyze candidates for first scan."""
        from src.scheduler.overnight import run_premarket_candidates
        run_premarket_candidates()

    def _run_stress_test(self):
        """Run historical stress test across all 3 crisis scenarios."""
        from src.scheduler.overnight import run_stress_test
        run_stress_test()

    def _run_simulation_engine(self):
        """Run full 13-scenario simulation with Monte Carlo."""
        from src.scheduler.overnight import run_simulation_engine
        return run_simulation_engine()

    def _model_version_changed(self) -> bool:
        """Check if model version changed since last stress test."""
        try:
            from src.training.versioning import get_active_model_name
            current = get_active_model_name()
            with connect_db(DB_PATH) as conn:
                row = conn.execute(
                    "SELECT model_version FROM stress_test_results "
                    "ORDER BY created_at DESC LIMIT 1"
                ).fetchone()
            return row is None or row[0] != current
        except Exception:
            return False

    def _run_research_synthesis(self):
        """Sunday 6 PM ET — Run weekly research synthesis."""
        from src.scheduler.overnight import run_research_synthesis
        run_research_synthesis()

    def _save_daily_metric_snapshot(self):
        """Save daily metric snapshot at EOD for MetricTrend chart."""
        from src.scheduler.reports import save_daily_metric_snapshot
        save_daily_metric_snapshot(db_path=DB_PATH)

    def _wf_reconciler_retry_count(
        self, db_path: str, strategy_id: str, code_git_sha: str
    ) -> int:
        """Return the number of recent auto-fire failure events for this (strategy, sha).

        Covers spawn_failed + skipped_no_corpus + timeout within the last 24 hours.
        Returns 0 on any DB error so the caller proceeds with the fire attempt.
        """
        # Engine-portable retry-cap check (PM PR #1100 review).
        # Both `json_extract(...)` and `datetime('now', '-24 hours')` are
        # SQLite-only — they crash on Postgres with UndefinedFunction. After
        # Sprint 5 Phase 3 cutover this reconciler runs against Postgres, so
        # we fetch candidate rows with the event_type IN-filter + a Python-
        # computed cutoff timestamp passed as a `?`-bound parameter, then
        # parse payload_json + match strategy_id/code_git_sha in Python.
        # Same anti-pattern as PR #1076 (task #124) and T14 PR #1099 DA-1
        # freshness check (fixed pre-merge).
        from datetime import datetime, timedelta, timezone
        import json as _json
        from src.utils.db import connect_db
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        try:
            conn = connect_db(db_path)
            try:
                rows = conn.execute(
                    """
                    SELECT payload_json FROM platform_events
                    WHERE event_type IN (
                      'walkforward_auto_fire_spawn_failed',
                      'walkforward_auto_fire_skipped_no_corpus',
                      'walkforward_auto_fire_timeout'
                    )
                    AND created_at > ?
                    """,
                    (cutoff,),
                ).fetchall()
            finally:
                conn.close()
            count = 0
            for row in rows:
                try:
                    payload = _json.loads(row[0]) if row[0] else {}
                    if (payload.get("strategy_id") == strategy_id
                            and payload.get("code_git_sha") == code_git_sha):
                        count += 1
                except (_json.JSONDecodeError, TypeError):
                    continue
            return count
        except Exception as exc:
            logger.warning("[WF_RECONCILER] Retry-cap check failed for %s: %s", strategy_id, exc)
            return 0

    def _wf_reconciler_emit_giveup(
        self, db_path: str, strategy_id: str, backtest_id: str,
        code_git_sha: str, retry_count: int,
    ) -> None:
        """Emit walkforward_auto_fire_giveup event and log. Best-effort — never raises."""
        from src.utils.db import connect_db
        import json as _json
        try:
            conn = connect_db(db_path)
            payload = _json.dumps({
                "strategy_id": strategy_id,
                "backtest_result_id": backtest_id,
                "code_git_sha": code_git_sha,
                "retry_count": retry_count,
            })
            conn.execute(
                "INSERT INTO platform_events (event_type, severity, payload_json, source) "
                "VALUES (?, ?, ?, ?)",
                ("walkforward_auto_fire_giveup", "warning", payload, "wf_reconciler"),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.warning("[WF_RECONCILER] Failed to write giveup event for %s: %s", strategy_id, exc)
        logger.warning(
            "[WF_RECONCILER] Giving up on %s (backtest=%s) after %d attempts",
            strategy_id, backtest_id, retry_count,
        )

    def _run_walkforward_reconciler(self, db_path: str | None = None) -> None:
        """Hourly during market hours — find orphan backtests and auto-fire missing runs.

        Orphan: backtest_results row created within 7 days with no matching
        walkforward_results.derived_from_backtest_id. Retry-cap at 3 failures
        (spawn_failed + skipped_no_corpus + timeout) within 24h → giveup event.
        Never raises — failures are logged and the loop continues.
        """
        from src.platform.walkforward_autofire import auto_fire_walkforward
        from src.utils.db import connect_db

        _db_path = db_path or getattr(self, "_db_path", None) or DB_PATH
        # Engine-portable orphan-backtest scan (PM PR #1100 review).
        # SQLite-only `datetime('now', '-7 days')` would crash on Postgres;
        # use Python-computed cutoff passed as a `?`-bound parameter (sibling
        # of the retry-cap fix above, both same anti-pattern as PR #1076).
        from datetime import datetime, timedelta, timezone
        _orphan_cutoff = (
            datetime.now(timezone.utc) - timedelta(days=7)
        ).isoformat()
        try:
            conn = connect_db(_db_path)
            try:
                orphans = conn.execute(
                    """
                    SELECT br.result_id AS backtest_id,
                           br.strategy_id,
                           br.code_git_sha
                    FROM backtest_results br
                    LEFT JOIN walkforward_results wr
                      ON wr.derived_from_backtest_id = br.result_id
                    WHERE wr.run_id IS NULL
                      AND br.created_at > ?
                    """,
                    (_orphan_cutoff,),
                ).fetchall()
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("[WF_RECONCILER] Failed to query orphan backtests: %s", exc)
            return

        for row in orphans:
            strategy_id = row[1] if not hasattr(row, "keys") else row["strategy_id"]
            backtest_id = row[0] if not hasattr(row, "keys") else row["backtest_id"]
            code_git_sha = row[2] if not hasattr(row, "keys") else row["code_git_sha"]

            retry_count = self._wf_reconciler_retry_count(_db_path, strategy_id, code_git_sha)
            if retry_count >= 3:
                self._wf_reconciler_emit_giveup(_db_path, strategy_id, backtest_id, code_git_sha, retry_count)
                continue

            try:
                auto_fire_walkforward(
                    strategy_id=strategy_id,
                    backtest_result_id=backtest_id,
                    db_path=_db_path,
                )
            except Exception as exc:
                logger.warning(
                    "[WF_RECONCILER] auto_fire_walkforward failed for %s: %s",
                    strategy_id, exc,
                )
