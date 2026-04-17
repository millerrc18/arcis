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
from src.scheduler.handler_registry import HandlerRegistryMixin
from src.scheduler.scorer import GuardedScorer

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")


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

            with sqlite3.connect(self.db_path) as conn:
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


class WatchLoop(HandlerRegistryMixin):
    """Automated daily cadence loop for the AI Research Desk."""

    def __init__(self, config: dict, email_mode: str | None = None,
                 overnight: bool = False):
        self.config = config
        self.overnight = overnight
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

        # VRAM handoff flags — RTX 3060 12GB shared between Ollama (inference)
        # and PyTorch (training). Evening handoff unloads Ollama, morning reloads it.
        self._vram_handoff_done = False
        self._morning_handoff_done = False

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
        self._last_bracket_check_time: datetime | None = None

        # Research synthesis + daily metrics
        self._research_synthesis_done = False
        self._daily_metric_snapshot_done = False

        # Email digest flags
        self._digest_premarket_done = False
        self._digest_midday_done = False
        self._digest_eod_done = False
        self._digest_evening_done = False
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
        # Scoring + VRAM handoffs
        self._daily_scored = 0
        self._vram_handoff_done = False
        self._morning_handoff_done = False
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

    def _is_market_open(self, now: datetime) -> bool:
        """Check if market is currently open (weekday, not holiday, between open and close).

        WHY this matters: scans, position monitoring, and bracket checks only
        run during market hours. Overnight tasks run outside this window.
        """
        if now.weekday() >= 5:  # Saturday=5, Sunday=6
            return False
        # Holiday check (#149) — fail-open so we don't miss a trading day
        try:
            from src.scheduler.holidays import is_market_holiday
            if is_market_holiday(check_date=now.date()):
                return False
        except Exception:
            pass  # If holiday module fails, assume market open — safer to scan unnecessarily
        market_open = now.replace(hour=self.market_open_hour,
                                  minute=self.market_open_minute, second=0)
        market_close = now.replace(hour=self.market_close_hour,
                                   minute=0, second=0)
        return market_open <= now < market_close

    def _check_digest_schedule(self):
        """Send scheduled email digests at configured times (digest mode only)."""
        if self.email_mode != "digest":
            return

        now = datetime.now(ET)
        # Only send digests on weekdays
        if now.weekday() >= 5:
            return

        h, m = now.hour, now.minute

        digest_cfg = self.config.get("email", {}).get("digest_times", {})
        premarket = digest_cfg.get("premarket", "07:30")
        midday = digest_cfg.get("midday", "12:00")
        eod = digest_cfg.get("eod", "16:15")
        evening = digest_cfg.get("evening", "20:00")

        from src.email.digest_builder import (
            build_premarket_digest,
            build_midday_digest,
            build_eod_digest,
            build_evening_digest,
        )
        from src.email.notifier import send_email

        def _should_send(target_time: str, flag_name: str) -> bool:
            th, tm = map(int, target_time.split(":"))
            if h == th and tm <= m < tm + 5:
                if not getattr(self, flag_name, False):
                    setattr(self, flag_name, True)
                    return True
            return False

        if _should_send(premarket, "_digest_premarket_done"):
            try:
                subject, body = build_premarket_digest()
                send_email(subject, body)
                logger.info("[DIGEST] Sent pre-market digest")
            except Exception as e:
                logger.error("[DIGEST] Pre-market digest failed: %s", e)

        if _should_send(midday, "_digest_midday_done"):
            try:
                subject, body = build_midday_digest()
                send_email(subject, body)
                logger.info("[DIGEST] Sent midday digest")
            except Exception as e:
                logger.error("[DIGEST] Midday digest failed: %s", e)

        if _should_send(eod, "_digest_eod_done"):
            try:
                subject, body = build_eod_digest()
                send_email(subject, body)
                logger.info("[DIGEST] Sent EOD digest")
            except Exception as e:
                logger.error("[DIGEST] EOD digest failed: %s", e)

        if _should_send(evening, "_digest_evening_done"):
            try:
                subject, body = build_evening_digest()
                send_email(subject, body)
                logger.info("[DIGEST] Sent evening digest")
            except Exception as e:
                logger.error("[DIGEST] Evening digest failed: %s", e)

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
        # can cause 30+ minute gaps during market hours. When detected, log
        # and alert so the operator knows scans were missed.
        if elapsed > 30 and self._is_market_open(now):
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
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                paper = conn.execute(
                    "SELECT COUNT(*) FROM shadow_trades WHERE status='open' AND source='paper'"
                    " AND COALESCE(quarantined, 0) = 0"
                ).fetchone()[0]
                live = conn.execute(
                    "SELECT COUNT(*) FROM shadow_trades WHERE status='open' AND source='live'"
                    " AND COALESCE(quarantined, 0) = 0"
                ).fetchone()[0]
                stats["open_paper"] = paper
                stats["open_live"] = live
                closed = conn.execute(
                    "SELECT COUNT(*) FROM shadow_trades WHERE status='closed'"
                    " AND COALESCE(quarantined, 0) = 0"
                ).fetchone()[0]
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
   DB: SQLite (WAL mode) | Render sync: active

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
        try:
            from src.notifications.telegram import notify_system_event, is_telegram_enabled
            if is_telegram_enabled():
                from src.training.versioning import get_active_model_name, get_training_example_counts
                _tg_model = get_active_model_name()
                if self.training_enabled:
                    _tg_counts = get_training_example_counts()
                    _tg_training = f"enabled ({_tg_counts.get('total', 0)} examples)"
                else:
                    _tg_training = "disabled"
                notify_system_event(
                    "ARCIS STARTED",
                    f"Model: {_tg_model}\nMode: {'Overnight' if self.overnight else 'Standard'}\nTraining: {_tg_training}"
                )
                print(" Telegram: connected (ok)")
            else:
                print(" Telegram: not configured")
        except Exception as e:
            logger.warning("[WATCH] Telegram startup notification failed: %s", e)
            print(" Telegram: not configured")

    def _run_morning_watchlist(self):
        """Execute the morning watchlist pipeline."""
        from src.scheduler.reports import run_morning_watchlist
        run_morning_watchlist(self.config, email_mode=getattr(self, 'email_mode', 'digest'))

    def _run_scan(self):
        """Execute a market-hours scan cycle.

        Delegates to universe_scanner.run_universe_scan() for the core
        pipeline, then handles state mutations (email, Telegram, metrics).
        """
        from src.scheduler.universe_scanner import run_universe_scan, ScanContext
        from src.email.notifier import send_email

        now = datetime.now(ET)
        _scan_num = getattr(self, "_scan_number", 0) + 1
        ctx = ScanContext(config=self.config, scan_id=f"s-{_scan_num:04d}")
        result = run_universe_scan(ctx)

        # Aborted scan (e.g., no SPY data) — just record metrics
        if result.aborted:
            self._record_scan_metrics(
                universe_count=result.universe_count, features_count=0,
                packet_worthy=0, llm_success=0, llm_total=0)
            return

        # Empty scan (no packet-worthy) — record and return
        if result.packet_worthy_count == 0:
            self._record_scan_metrics(
                universe_count=result.universe_count,
                features_count=result.features_count,
                packet_worthy=0, llm_success=0, llm_total=0)
            return

        self._trades_managed_today += result.packet_worthy_count

        # ── Email dispatch (uses self.email_mode, self._daily_packets) ──
        for pkt in result.packets_rendered:
            if self.email_mode == "full_stream":
                subject = f"[TRADE DESK] Action Packet - {pkt['ticker']}"
                send_email(subject, pkt["rendered"])
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
                from src.shadow_trading.reconcile import reconcile_paper_trades
                recon = reconcile_paper_trades(dry_run=False)
                closed = recon.get("marked_closed", [])
                if closed:
                    logger.info("[WATCH] Intra-day reconciliation closed %d stale trades: %s",
                                len(closed), closed)
                self._last_reconcile_time = now
            except Exception as e:
                logger.warning("[WATCH] Intra-day reconciliation failed: %s", e)

        # ── Telegram: scan-level notifications (uses self._scan_number) ──
        self._post_scan_notifications(result)

        # ── Scan metrics ──
        self._record_scan_metrics(
            universe_count=result.universe_count,
            features_count=result.features_count,
            packet_worthy=result.packet_worthy_count,
            llm_success=result.packet_worthy_count,
            llm_total=result.packet_worthy_count,
            conviction_parsed=result.conviction_parsed,
            conviction_total=result.conviction_total)

    def _run_mr_scan(self):
        """Run mean reversion scan after main scan."""
        from src.services.mr_scan_service import run_mr_scan
        result = run_mr_scan(self.config)
        if result.get("trades_opened", 0) > 0:
            logger.info("[WATCH] MR scan opened %d trades", result["trades_opened"])
        return result.get("status") != "error"

    def _post_scan_notifications(self, result):
        """Send Telegram notifications after a scan cycle."""
        try:
            from src.notifications.telegram import notify_scan_complete, is_telegram_enabled
            if is_telegram_enabled():
                notify_scan_complete(
                    packets_count=result.packet_worthy_count,
                    trades_opened=result.trades_opened,
                    trades_closed=result.trades_closed,
                )
        except Exception as e:
            logger.warning("[WATCH] notify_scan_complete failed: %s", e)

        try:
            from src.notifications.telegram import notify_scan_result, is_telegram_enabled
            if is_telegram_enabled():
                if not hasattr(self, '_scan_number'):
                    self._scan_number = 0
                self._scan_number += 1
                notify_scan_result(
                    scan_number=self._scan_number,
                    total_scanned=result.universe_count,
                    packet_worthy=result.packet_worthy_count,
                    watchlist=result.watchlist_count,
                )
        except Exception as e:
            logger.warning("[WATCH] notify_scan_result failed: %s", e)

        if not self._first_scan_done:
            self._first_scan_done = True
            try:
                from src.notifications.telegram import notify_first_scan_summary, is_telegram_enabled
                if is_telegram_enabled():
                    top_setups = [
                        (c["ticker"], c["score"]) for c in result.packet_worthy[:3]
                    ]
                    setup_type_counts: dict[str, int] = {}
                    for c in result.packet_worthy:
                        st = c.get("features", {}).get("setup_type", "unknown")
                        setup_type_counts[st] = setup_type_counts.get(st, 0) + 1
                    notify_first_scan_summary(
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
            except Exception as e:
                logger.warning("[WATCH] notify_first_scan_summary failed: %s", e)

    def _record_scan_metrics(self, *, universe_count: int = 0,
                             features_count: int = 0, packet_worthy: int = 0,
                             llm_success: int = 0, llm_total: int = 0,
                             conviction_parsed: int = 0, conviction_total: int = 0):
        """Write a row to scan_metrics for every scan cycle (success or failure)."""
        try:
            import sqlite3 as _sq
            if not hasattr(self, '_scan_number'):
                self._scan_number = 0
            self._scan_number += 1
            now = datetime.now(ET)
            with _sq.connect(DB_PATH) as conn:
                conn.execute(
                    "INSERT INTO scan_metrics "
                    "(id, scan_number, scan_time, universe_count, features_count, "
                    "scored_count, packet_worthy, risk_passed, paper_traded, "
                    "live_traded, llm_success, llm_total, llm_fallback, "
                    "avg_conviction, duration_seconds, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (self._scan_number, self._scan_number, now.strftime("%H:%M"), universe_count,
                     features_count, features_count, packet_worthy,
                     packet_worthy, packet_worthy, 0, llm_success, llm_total,
                     0, 0.0, 0.0, now.isoformat()),
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
            send_email(subject, body)
            print("[WATCH] EOD recap email sent.")
        else:
            print("[WATCH] EOD recap computed (digest mode — email sent via scheduled digest).")

    @staticmethod
    def _ensure_all_tables():
        """Create all expected SQLite tables on startup to prevent missing-table errors."""
        from src.schema.sqlite import create_all_tables, ensure_columns
        try:
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
        """Configure SQLite for production use."""
        import sqlite3
        try:
            conn = sqlite3.connect(DB_PATH)

            # Integrity check — abort before any writes if DB is corrupted
            result = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                logger.critical("[DB] INTEGRITY CHECK FAILED: %s", result)
                try:
                    from src.notifications.telegram import send_telegram
                    send_telegram("\U0001f534 DATABASE CORRUPTED \u2014 integrity check failed. Watch loop halted.")
                except Exception:
                    pass
                conn.close()
                import sys
                sys.exit(1)

            # Fix for #160: WAL mode + busy_timeout=5000ms prevents "database is locked"
            # errors when the API server and watch loop access SQLite concurrently.
            # NORMAL sync is safe with WAL (data survives process crash, not power loss).
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.close()
            logger.info("[DB] SQLite configured: WAL mode, synchronous=NORMAL, busy_timeout=5000ms")
        except SystemExit:
            raise
        except Exception as exc:
            logger.warning("[DB] SQLite configuration failed: %s", exc)

    @staticmethod
    def _check_row_counts():
        """Sanity-check that critical tables aren't unexpectedly empty."""
        import sqlite3
        try:
            conn = sqlite3.connect(DB_PATH)
            count = conn.execute("SELECT COUNT(*) FROM shadow_trades").fetchone()[0]
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
        import sqlite3
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

        # Start Render cloud sync background thread
        try:
            from src.sync.render_sync import start_render_sync
            sync_thread = start_render_sync(
                self.config,
                on_commands_pulled=_on_commands_pulled,
            )
            if sync_thread:
                print(" Render sync: enabled (ok)")
                print(" Command queue: enabled (ok)")
            else:
                print(" Render sync: disabled")
        except Exception as e:
            logger.debug("Render sync startup failed: %s", e)
            print(f" Render sync: error ({e})")

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
                now = datetime.now(ET)

                # Write heartbeat every iteration (~60s)
                try:
                    Path("data/watchdog.txt").write_text(now.isoformat())
                except Exception:
                    pass

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
                    if self._safe_run("Ollama warm-up", self._run_ollama_warmup):
                        self._ollama_warmup_done = True

                if (hour == 9 and now.minute < 5 and now.weekday() < 5
                        and not self._premarket_bracket_check_done):
                    # Fix for #257: only set done-flag on success
                    if self._safe_run(
                        "pre-market bracket check",
                        lambda: self._run_bracket_health_check("premarket"),
                    ):
                        self._premarket_bracket_check_done = True

                # 0.5. Daily AI Council (8:30 AM — after watchlist, before first scan)
                if (hour == 8 and now.minute >= 30 and not self._council_done):
                    # Fix for #257: only set done-flag on success
                    if self._safe_run("daily council", self._run_daily_council):
                        self._council_done = True

                # 0.7. Tier 4: Fundamentals refresh (daily at 7:30 AM)
                if (hour == 7 and now.minute >= 30 and not self._fundamentals_done
                        and now.weekday() < 5):
                    try:
                        from src.scheduler.fundamentals_refresh import run_fundamentals_refresh
                        # Fix for #257: only set done-flag on success
                        if self._safe_run("fundamentals refresh",
                                          lambda: run_fundamentals_refresh(self.config)):
                            self._fundamentals_done = True
                    except Exception as e:
                        logger.warning("[WATCH] Fundamentals refresh failed: %s", e)

                # 1. Morning watchlist
                if hour == self.morning_hour and not self._morning_done:
                    # Fix for #257: only set done-flag on success
                    if self._safe_run("morning watchlist", self._run_morning_watchlist):
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
                    if self._safe_run("EOD recap", self._run_eod_recap):
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
                        if self._safe_run("daily metric snapshot", self._save_daily_metric_snapshot):
                            self._daily_metric_snapshot_done = True
                    # 1C. EOD P&L report via Telegram
                    if not self._eod_report_done:
                        if self._safe_run("EOD Telegram report", self._send_eod_report):
                            self._eod_report_done = True
                        # ── Telegram: notify_daily_summary (after eod report) ──
                        try:
                            from src.notifications.telegram import notify_daily_summary, is_telegram_enabled
                            if is_telegram_enabled():
                                import sqlite3
                                with sqlite3.connect(DB_PATH) as _conn:
                                    _conn.row_factory = sqlite3.Row
                                    _today = datetime.now(ET).strftime("%Y-%m-%d")
                                    _open = _conn.execute(
                                        "SELECT COUNT(*) FROM shadow_trades WHERE status='open'"
                                        " AND COALESCE(quarantined, 0) = 0"
                                    ).fetchone()[0]
                                    _closed_today = _conn.execute(
                                        "SELECT COUNT(*) FROM shadow_trades WHERE status='closed' "
                                        "AND actual_exit_time LIKE ? AND COALESCE(quarantined, 0) = 0",
                                        (f"{_today}%",)
                                    ).fetchone()[0]
                                    _pnl_row = _conn.execute(
                                        "SELECT COALESCE(SUM(pnl_dollars),0) FROM shadow_trades "
                                        "WHERE status='closed' AND actual_exit_time LIKE ?"
                                        " AND COALESCE(quarantined, 0) = 0",
                                        (f"{_today}%",)
                                    ).fetchone()
                                    _total_pnl = _pnl_row[0] if _pnl_row else 0.0
                                notify_daily_summary(
                                    total_pnl=_total_pnl,
                                    open_trades=_open,
                                    closed_today=_closed_today,
                                )
                        except Exception as e:
                            logger.warning("[WATCH] notify_daily_summary failed: %s", e)

                # 4. Daily audit (4:15 PM ET)
                elif (hour == 16 and now.minute >= 15 and now.minute < 30
                      and not self._daily_audit_done):
                    # Fix for #257: only set done-flag on success
                    if self._safe_run("daily audit", self._run_daily_audit):
                        self._daily_audit_done = True
                    # Send daily scoring summary via Telegram
                    try:
                        from src.notifications.telegram import notify_scoring_summary, is_telegram_enabled
                        if is_telegram_enabled() and self._daily_scored > 0:
                            import sqlite3
                            with sqlite3.connect(DB_PATH) as conn:
                                backlog = conn.execute(
                                    "SELECT COUNT(*) FROM training_examples WHERE quality_score_auto IS NULL"
                                ).fetchone()[0]
                            notify_scoring_summary(self._daily_scored, backlog)
                    except Exception as e:
                        logger.warning("[WATCH] notify_scoring_summary failed: %s", e)

                # 4b. Daily system validation (4:30 PM ET)
                elif (hour == 16 and now.minute >= 30 and now.minute < 45
                      and not self._daily_validation_done):
                    try:
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
                        self._daily_validation_done = True
                    except Exception as e:
                        logger.warning("[WATCH] Validation failed: %s", e)

                # 4c. Daily build score snapshot (4:45 PM ET)
                if (hour == 16 and now.minute >= 45
                        and not self._daily_build_score_done):
                    try:
                        from src.evaluation.build_score import persist_build_score
                        result = persist_build_score()
                        logger.info(
                            "[WATCH] Build score persisted: %.1f",
                            result.get("build_score", 0),
                        )
                        self._daily_build_score_done = True
                    except Exception as e:
                        logger.warning("[WATCH] Build score persistence failed: %s", e)

                if (hour == 16 and now.minute >= 30 and now.minute < 35
                        and not self._postclose_bracket_check_done):
                    # Fix for #257: only set done-flag on success
                    if self._safe_run(
                        "post-close bracket check",
                        lambda: self._run_bracket_health_check("postclose"),
                    ):
                        self._postclose_bracket_check_done = True

                # 4b. Post-close paper reconciliation (4:30–4:35 PM ET)
                if (hour == 16 and now.minute >= 30 and now.minute < 35
                        and not self._postclose_reconcile_done):
                    # Fix for #257: only set done-flag on success
                    if self._safe_run(
                        "post-close reconciliation",
                        self._run_postclose_reconciliation,
                    ):
                        self._postclose_reconcile_done = True

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
                    ):
                        self._attribution_resolution_done = True

                # 5. Training data collection (after market close)
                elif (self.training_enabled and 16 <= hour < 22
                      and (hour > 16 or now.minute >= 30)
                      and not self._training_collection_done):
                    # Fix for #257: only set done-flags on success
                    if self._safe_run("training collection", self._run_training_collection):
                        self._training_collection_done = True
                    # 1D. Data asset report after training collection
                    if not self._data_asset_report_done:
                        if self._safe_run("data asset report", self._send_data_asset_report):
                            self._data_asset_report_done = True

                # 5. Overnight training trigger (5:00 PM ET)
                elif (self.training_enabled and hour == 17
                      and not self._training_run_done):
                    # Fix for #257: only set done-flag on success
                    if self._safe_run("training check", self._run_training_check):
                        self._training_run_done = True

                # 5b. Model regression check (5:05 PM ET, after market close)
                if (hour == 17 and now.minute >= 5 and now.minute < 15
                        and not self._model_regression_done):
                    if self._safe_run("model regression check",
                                      self._run_model_regression_check):
                        self._model_regression_done = True

                # 6. Saturday training report (9 AM ET)
                elif (self.training_enabled and now.weekday() == 5
                      and hour == 9 and not self._saturday_reports_done):
                    # Fix for #257: only set done-flag on success
                    if self._safe_run("Saturday reports", self._run_saturday_reports):
                        self._saturday_reports_done = True

                # H1. Research synthesis (Sunday 6 PM ET)
                elif (now.weekday() == 6 and hour == 18
                      and not self._research_synthesis_done):
                    # Fix for #257: only set done-flag on success
                    if self._safe_run("research synthesis", self._run_research_synthesis):
                        self._research_synthesis_done = True

                # 1H. Weekly digest (Sunday 8 PM ET)
                elif (now.weekday() == 6 and hour == 20
                      and not self._weekly_digest_done):
                    # Fix for #257: only set done-flag on success
                    if self._safe_run("weekly digest", self._send_weekly_digest):
                        self._weekly_digest_done = True

                # Weekly stress test (Sunday 9 PM ET)
                elif (now.weekday() == 6 and hour == 21
                      and not self._stress_test_done):
                    # Fix for #257: only set done-flag on success
                    if self._safe_run("weekly stress test", self._run_stress_test):
                        self._stress_test_done = True

                # Weekly simulation engine (Sunday 9:30 PM ET, after stress test)
                elif (now.weekday() == 6 and hour == 21 and now.minute >= 30
                      and not self._simulation_done):
                    if self._safe_run("weekly simulation", self._run_simulation_engine):
                        self._simulation_done = True

                # Action reminders (8 PM daily via Telegram)
                if hour == 20 and not self._action_reminders_done:
                    try:
                        from src.notifications.telegram_commands import check_action_reminders
                        from src.notifications.telegram import is_telegram_enabled
                        if is_telegram_enabled():
                            sent = check_action_reminders()
                            if sent:
                                logger.info("[WATCH] Action reminders sent: %s", sent)
                    except Exception as e:
                        logger.debug("[WATCH] Action reminders failed: %s", e)
                    self._action_reminders_done = True

                # 1L. Earnings proximity warning (8:00 AM weekdays)
                if (hour == 8 and now.minute < 5 and now.weekday() < 5
                        and not self._earnings_warning_done):
                    # Fix for #257: only set done-flag on success
                    if self._safe_run("earnings proximity", self._check_earnings_proximity):
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

                time.sleep(60)

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

    def _safe_run(self, name: str, func) -> bool:
        """Run a function with per-task exponential backoff error recovery.

        Returns True on success, False on exception.

        Fix for #147: Exponential backoff (10s -> 30s -> 60s cap).
        Fix for #231: Backoff is keyed per task name. A failing EDGAR collector
        only delays the next EDGAR attempt, not scans or reconciliation.
        Fix for #226: Callers must check return value before setting done-flags.
        Pattern: `if self._safe_run(...): self._done = True`
        """
        import traceback
        try:
            # Per-task backoff: wait before retrying a previously-failed task
            task_backoff = self._backoff.get(name, 0)
            if task_backoff > 0:
                print(f"[WATCH] Backoff: waiting {task_backoff}s before {name}...")
                time.sleep(task_backoff)
            func()
            # Success — reset backoff for this task only (not all tasks)
            self._consecutive_errors = 0
            self._backoff.pop(name, None)
            return True
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
            return False

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

    # ── VRAM Handoff Methods ─────────────────────────────────────────

    def _run_evening_handoff(self):
        """6:50 PM ET — Unload Ollama, launch overnight training subprocess."""
        from src.scheduler.overnight import run_evening_handoff
        self._vram_manager = run_evening_handoff(
            vram_manager=getattr(self, '_vram_manager', None))

    def _run_morning_handoff(self):
        """5:15 AM ET — Kill training subprocess, reload Ollama."""
        from src.scheduler.overnight import run_morning_handoff
        run_morning_handoff(vram_manager=getattr(self, '_vram_manager', None))

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
        import sqlite3
        try:
            from src.training.versioning import get_active_model_name
            current = get_active_model_name()
            with sqlite3.connect(DB_PATH) as conn:
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
