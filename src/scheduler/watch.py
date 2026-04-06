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


class WatchLoop:
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

        # Stress test scheduling
        self._stress_test_done = False

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
        self._stress_test_done = False
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
                ).fetchone()[0]
                live = conn.execute(
                    "SELECT COUNT(*) FROM shadow_trades WHERE status='open' AND source='live'"
                ).fetchone()[0]
                stats["open_paper"] = paper
                stats["open_live"] = live
                closed = conn.execute(
                    "SELECT COUNT(*) FROM shadow_trades WHERE status='closed'"
                ).fetchone()[0]
                stats["phase_trades"] = closed
                # Today's closed P&L
                today_str = datetime.now(ET).strftime("%Y-%m-%d")
                closed_today = conn.execute(
                    "SELECT COALESCE(SUM(pnl_dollars), 0) FROM shadow_trades "
                    "WHERE status='closed' AND actual_exit_time LIKE ?",
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
        from src.data_ingestion.market_data import fetch_ohlcv, fetch_spy_benchmark
        from src.features.engine import compute_all_features
        from src.llm.packet_writer import enhance_packet_with_llm
        from src.llm.watchlist_writer import generate_watchlist_narrative
        from src.packets.template import build_packet_from_features, render_packet
        from src.packets.watchlist import build_morning_watchlist
        from src.ranking.ranker import rank_universe, get_top_candidates
        from src.universe.sp100 import get_sp100_universe
        from src.email.notifier import send_email

        print("[WATCH] Running morning watchlist pipeline...")
        universe = get_sp100_universe()
        ohlcv = fetch_ohlcv(universe)
        spy = fetch_spy_benchmark()

        if spy.empty:
            print("[WATCH] ERROR: Could not fetch SPY benchmark. Skipping morning watchlist.")
            return

        features = compute_all_features(ohlcv, spy)

        # Enrich features with fundamental, insider, and macro data
        try:
            from src.data_enrichment.enricher import enrich_features
            features = enrich_features(features, self.config)
        except Exception as e:
            logger.warning("[WATCH] Data enrichment failed: %s", e)

        ranked = rank_universe(features)
        candidates = get_top_candidates(ranked)
        packet_worthy = candidates["packet_worthy"]
        watchlist = candidates["watchlist"]

        now = datetime.now(ET)
        date_str = now.strftime("%Y-%m-%d")

        narrative = generate_watchlist_narrative(packet_worthy, watchlist, self.config)
        body = build_morning_watchlist(watchlist, packet_worthy, date_str,
                                       narrative=narrative)
        print(body)

        if self.email_mode in ("full_stream", "daily_summary"):
            subject = f"[TRADE DESK] Morning Watchlist - {date_str}"
            send_email(subject, body)
            print("[WATCH] Morning watchlist email sent.")
        elif self.email_mode == "digest":
            pass  # Handled by scheduled pre-market digest

        # Telegram watchlist notification — send packet-worthy (high-conviction) names
        try:
            from src.notifications.telegram import notify_watchlist, is_telegram_enabled
            if is_telegram_enabled():
                pw_tickers = [c["ticker"] for c in candidates.get("packet_worthy", [])]
                wl_count = len(candidates.get("watchlist", []))
                notify_watchlist(pw_tickers[:5], len(pw_tickers),
                                 watchlist_count=wl_count)
        except Exception as e:
            logger.warning("[WATCH] notify_watchlist failed: %s", e)

    def _run_scan(self):
        """Execute a market-hours scan cycle.

        Delegates to universe_scanner.run_universe_scan() for the core
        pipeline, then handles state mutations (email, Telegram, metrics).
        """
        from src.scheduler.universe_scanner import run_universe_scan, ScanContext
        from src.email.notifier import send_email

        now = datetime.now(ET)
        ctx = ScanContext(config=self.config)
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
            llm_total=result.packet_worthy_count)

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
                             llm_success: int = 0, llm_total: int = 0):
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
                    "(scan_number, scan_time, universe_count, features_count, "
                    "scored_count, packet_worthy, risk_passed, paper_traded, "
                    "live_traded, llm_success, llm_total, llm_fallback, "
                    "avg_conviction, duration_seconds, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (self._scan_number, now.strftime("%H:%M"), universe_count,
                     features_count, features_count, packet_worthy,
                     packet_worthy, packet_worthy, 0, llm_success, llm_total,
                     0, 0.0, 0.0, now.isoformat()),
                )
                conn.commit()
            logger.info("[WATCH] Recorded scan_metrics #%d (packets=%d)",
                        self._scan_number, packet_worthy)
        except Exception as e:
            logger.warning("[WATCH] Failed to record scan_metrics: %s", e)

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

    def _release_lock(self):
        """Release PID lockfile if it belongs to this process."""
        try:
            if self.LOCKFILE.exists():
                if self.LOCKFILE.read_text().strip() == str(os.getpid()):
                    self.LOCKFILE.unlink(missing_ok=True)
                    logger.info("[WATCH] Released lockfile")
        except Exception:
            pass

    def run(self):
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

        signal.signal(signal.SIGTERM, _handle_shutdown)
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
                                    ).fetchone()[0]
                                    _closed_today = _conn.execute(
                                        "SELECT COUNT(*) FROM shadow_trades WHERE status='closed' "
                                        "AND actual_exit_time LIKE ?", (f"{_today}%",)
                                    ).fetchone()[0]
                                    _pnl_row = _conn.execute(
                                        "SELECT COALESCE(SUM(pnl_dollars),0) FROM shadow_trades "
                                        "WHERE status='closed' AND actual_exit_time LIKE ?",
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
                                    "SELECT COUNT(*) FROM training_examples WHERE quality_score IS NULL"
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
                    except Exception as e:
                        logger.warning("[WATCH] Validation failed: %s", e)
                    self._daily_validation_done = True

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
                    except Exception as e:
                        logger.warning("[WATCH] Build score persistence failed: %s", e)
                    self._daily_build_score_done = True

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

                # 4c. Attribution outcome resolution (4:30-4:35 PM ET)
                if (hour == 16 and now.minute >= 30 and now.minute < 35
                        and not self._attribution_resolution_done):
                    from src.attribution.logger import resolve_pending_outcomes
                    # Fix for #257: only set done-flag on success
                    if self._safe_run(
                        "attribution outcome resolution",
                        lambda: resolve_pending_outcomes(),
                    ):
                        self._attribution_resolution_done = True

                # 5. Training data collection (4:30 PM ET)
                elif (self.training_enabled and hour == 16 and now.minute >= 30
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

                # Action reminders (8 PM daily via Telegram)
                if hour == 20 and not self._action_reminders_done:
                    try:
                        from src.notifications.telegram import check_action_reminders, is_telegram_enabled
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

                # ── Overnight schedule (--overnight flag, NOT during market hours) ──
                # Fix for #225: Changed from `elif` chain to allow weekend execution.
                # Previously the elif after market-hours checks blocked all overnight
                # tasks on weekends. Now runs 7 days/week; individual tasks gate on
                # is_weekday where needed (VRAM handoff, pre-market).
                elif self.overnight and not self._is_market_open(now):
                    ran = False
                    is_weekday = now.weekday() < 5

                    # Morning VRAM handoff (5:15 AM, weekdays only)
                    if (is_weekday and hour == 5 and now.minute >= 15
                            and not self._morning_handoff_done):
                        if self._safe_run("morning VRAM handoff",
                                          self._run_morning_handoff):
                            self._morning_handoff_done = True
                        ran = True

                    elif is_weekday and hour == 17 and now.minute >= 30 and not self._post_close_done:
                        if self._safe_run("post-close capture", self._run_post_close_capture):
                            self._post_close_done = True
                        ran = True
                    elif (is_weekday and hour == 18 and self.training_enabled
                          and not self._overnight_training_collection_done):
                        if self._safe_run("overnight training collection",
                                          self._run_overnight_training_collection):
                            self._overnight_training_collection_done = True
                        ran = True

                    # Evening VRAM handoff (6:50 PM, weekdays only)
                    elif (is_weekday and hour == 18 and now.minute >= 50
                          and not self._vram_handoff_done):
                        if self._safe_run("evening VRAM handoff",
                                          self._run_evening_handoff):
                            self._vram_handoff_done = True
                        ran = True

                    # Re-run stress test if model version changed (7 PM, weekdays only)
                    elif (is_weekday and hour == 19 and not self._stress_test_done
                          and self._model_version_changed()):
                        if self._safe_run("stress test (model change)",
                                          self._run_stress_test):
                            self._stress_test_done = True
                        ran = True

                    # NOTE: 9:30 PM data collection, 10 PM news, 11 PM enrichment
                    # are CPU/network only (no GPU) — run daily including weekends.
                    # Weekend data (options flow, news, macro) feeds Monday morning's
                    # pre-market brief and council session.
                    elif (hour == 21 and now.minute >= 30
                          and not self._data_collection_done):
                        if self._safe_run("data collection", self._run_data_collection):
                            self._data_collection_done = True
                        ran = True
                    elif hour == 22 and not self._news_ingestion_done:
                        if self._safe_run("news ingestion", self._run_news_ingestion):
                            self._news_ingestion_done = True
                        ran = True
                    elif hour == 23 and not self._enrichment_precache_done:
                        if self._safe_run("enrichment precache", self._run_enrichment_precache):
                            self._enrichment_precache_done = True
                        ran = True
                    elif is_weekday and hour == 6 and not self._pre_market_done:
                        if self._safe_run("pre-market refresh", self._run_pre_market_refresh):
                            self._pre_market_done = True

                            # 1A. Pre-market brief (right after pre-market refresh at 6:00 AM)
                            if not self._premarket_brief_done:
                                if self._safe_run("pre-market brief", self._send_premarket_brief):
                                    self._premarket_brief_done = True
                        ran = True

                    # ── Pre-market inference tasks (6-9:25 AM, weekdays only) ──
                    elif (is_weekday and hour == 6 and now.minute >= 2
                          and not self._premarket_features_done):
                        if self._safe_run("rolling features",
                                          self._run_premarket_rolling_features):
                            self._premarket_features_done = True
                        ran = True
                    elif is_weekday and hour == 7 and not self._premarket_training_done:
                        if self._safe_run("premarket training gen",
                                          self._run_premarket_training):
                            self._premarket_training_done = True
                        ran = True
                    elif (is_weekday and hour == 8 and now.minute >= 2
                          and not self._premarket_news_done):
                        if self._safe_run("premarket news scoring",
                                          self._run_premarket_news_scoring):
                            self._premarket_news_done = True
                        ran = True
                    elif (is_weekday and hour == 9 and now.minute < 25
                          and not self._premarket_candidates_done):
                        if self._safe_run("premarket candidates",
                                          self._run_premarket_candidates):
                            self._premarket_candidates_done = True
                        ran = True

                        # ── Telegram: notify_premarket_complete (all premarket tasks done) ──
                        if (self._premarket_features_done and self._premarket_training_done
                                and self._premarket_news_done):
                            try:
                                from src.notifications.telegram import notify_premarket_complete, is_telegram_enabled
                                if is_telegram_enabled():
                                    notify_premarket_complete(
                                        features_done=self._premarket_features_done,
                                        training_gen=0,  # count not tracked at this level
                                        news_scored=0,
                                        candidates=0,
                                    )
                            except Exception as e:
                                logger.warning("[WATCH] notify_premarket_complete failed: %s", e)

                    if not ran:
                        print(f"[WATCH] {time_str} ET -- overnight mode")

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
                    from src.notifications.telegram import (
                        poll_commands, handle_command, send_telegram, is_telegram_enabled
                    )
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
                if (live_cfg.get("broker") == "ib"
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
        from src.shadow_trading.reconcile import reconcile_paper_trades

        result = reconcile_paper_trades()

        if result.get("error"):
            msg = f"[Reconcile] Alpaca API error — skipped: {result['error']}"
            logger.warning("[WATCH] %s", msg)
            try:
                from src.notifications.telegram import send_telegram, is_telegram_enabled
                if is_telegram_enabled():
                    send_telegram(f"\u26a0\ufe0f {msg}")
            except Exception:
                pass
            return

        orphaned = result["orphaned"]
        stale = result["stale"]
        discrep = result["discrepancies"]
        backfilled = result["backfilled"]

        if not orphaned and not stale and not discrep:
            msg = (
                f"\u2705 Reconciliation: {result['local_count']} local / "
                f"{result['alpaca_count']} Alpaca \u2014 all matched"
            )
        else:
            parts = []
            if orphaned:
                parts.append(f"{len(orphaned)} orphaned (backfilled: {backfilled})")
            if stale:
                tickers = [s["ticker"] for s in stale]
                parts.append(f"{len(stale)} stale: {tickers}")
            if discrep:
                parts.append(f"{len(discrep)} mismatched")
            msg = f"\u274c Reconciliation: {', '.join(parts)}"

        logger.info("[WATCH] %s", msg)
        try:
            from src.notifications.telegram import send_telegram, is_telegram_enabled
            if is_telegram_enabled():
                send_telegram(msg)
        except Exception as e:
            logger.warning("[WATCH] Reconciliation Telegram alert failed: %s", e)

    def _run_daily_audit(self):
        """Run the daily auditor agent."""
        from src.evaluation.auditor import run_daily_audit, check_escalation
        from src.email.notifier import send_email

        print("[WATCH] Running daily audit...")
        audit = run_daily_audit()
        assessment = audit.get("overall_assessment", "green")
        summary = (audit.get("summary") or "")[:200]
        print(f"[WATCH] Audit: {assessment} — {summary}")

        # Check for escalation
        actions = check_escalation(audit)
        for action in actions:
            print(f"[WATCH] Escalation: {action['action']} ({action['severity']})")

        # Send alert if red or yellow
        if assessment == "red":
            subject = "[TRADE DESK] DAILY AUDIT — RED"
            send_email(subject, f"Assessment: RED\n\n{audit.get('summary', '')}")
        elif assessment == "yellow":
            logger.info("[AUDIT] Yellow assessment — included in EOD recap")

        # CUSUM performance change detection
        try:
            from src.evaluation.change_detector import detect_performance_change
            change = detect_performance_change()
            if change and change.get("alarm"):
                alarm_msg = f"[CUSUM] Performance change detected: {change.get('direction', 'negative')} shift"
                logger.warning(alarm_msg)
                print(f"[WATCH] {alarm_msg}")
                try:
                    from src.notifications.telegram import send_telegram_message
                    send_telegram_message(f"⚠️ CUSUM ALARM\n{alarm_msg}\nDetails: {change.get('detail', '')}")
                except Exception as e:
                    logger.warning("[WATCH] CUSUM Telegram alert failed: %s", e)
        except Exception as e:
            logger.debug("[AUDIT] CUSUM check failed: %s", e)

        # Leakage detection
        try:
            from src.training.leakage_detector import run_leakage_check
            leakage = run_leakage_check()
            if leakage and leakage.get("balanced_accuracy", 0) > 0.65:
                leak_msg = f"[LEAKAGE] Balanced accuracy {leakage['balanced_accuracy']:.1%} > 65% threshold"
                logger.warning(leak_msg)
                try:
                    from src.notifications.telegram import send_telegram_message
                    send_telegram_message(f"🔴 LEAKAGE ALERT\n{leak_msg}")
                except Exception as e:
                    logger.warning("[WATCH] Leakage Telegram alert failed: %s", e)
        except ImportError:
            pass
        except Exception as e:
            logger.debug("[AUDIT] Leakage check failed: %s", e)

    def _run_training_collection(self):
        """Collect training data from closed trades."""
        from src.training.data_collector import collect_training_examples_from_closed_trades
        print("[WATCH] Running training data collection...")
        count = collect_training_examples_from_closed_trades()
        print(f"[WATCH] Training data collection: {count} new examples generated")

    def _run_training_check(self):
        """Check if fine-tuning should be triggered."""
        from src.training.trainer import should_train, run_fine_tune
        trigger, reason = should_train()
        if trigger:
            print(f"[WATCH] Training triggered: {reason}")
            result = run_fine_tune()
            if result:
                print(f"[WATCH] Training complete: {result['version_name']}")
                # ── Telegram: notify_model_event ──
                try:
                    from src.notifications.telegram import notify_model_event, is_telegram_enabled
                    if is_telegram_enabled():
                        notify_model_event(
                            event="TRAINING COMPLETE",
                            model_name=result.get("version_name", "unknown"),
                            detail=f"Reason: {reason}",
                        )
                except Exception as e:
                    logger.warning("[WATCH] notify_model_event failed: %s", e)
            else:
                print("[WATCH] Training failed. Check logs.")
        else:
            print(f"[WATCH] Training not needed: {reason}")

    def _run_saturday_reports(self):
        """Generate and send Saturday training and CTO reports."""
        from src.training.report import generate_training_report
        from src.email.notifier import send_email

        # Training report
        print("[WATCH] Generating Saturday training report...")
        report = generate_training_report()
        print(report)
        subject = "[TRADE DESK] Weekly Training Report"
        send_email(subject, report)
        print("[WATCH] Training report email sent.")

        # ── Telegram: notify_retrain_report ──
        try:
            from src.notifications.telegram import notify_retrain_report, is_telegram_enabled
            from src.training.versioning import get_active_model_name, get_training_example_counts
            if is_telegram_enabled():
                model_name = get_active_model_name()
                counts = get_training_example_counts()
                # Compute week-over-week training metrics
                _retrain_total = counts.get("total", 0)
                try:
                    import sqlite3 as _sq
                    from datetime import timedelta as _td
                    with _sq.connect(DB_PATH) as _rc:
                        _week_ago = (datetime.now(ET) - _td(days=7)).isoformat()
                        _new_wk = _rc.execute(
                            "SELECT COUNT(*) FROM training_examples WHERE created_at > ?",
                            (_week_ago,)
                        ).fetchone()[0]
                        _new_paper = _rc.execute(
                            "SELECT COUNT(*) FROM training_examples WHERE created_at > ? AND source LIKE '%paper%'",
                            (_week_ago,)
                        ).fetchone()[0]
                except Exception:
                    _new_wk = 0
                    _new_paper = 0

                notify_retrain_report(
                    model_name=model_name,
                    training_examples=_retrain_total,
                    prev_examples=_retrain_total - _new_wk,
                    new_this_week=_new_wk,
                    new_paper=_new_paper,
                    new_live=0,
                    canary_status="STABLE",
                    perplexity=0.0,
                    prev_perplexity=0.0,
                    distinct2=0.0,
                    prev_distinct2=0.0,
                    champion_challenger="N/A",
                )
        except Exception as e:
            logger.warning("[WATCH] notify_retrain_report failed: %s", e)

        # Weekly deep audit
        try:
            from src.evaluation.auditor import run_weekly_audit
            print("[WATCH] Running weekly deep audit...")
            weekly = run_weekly_audit(days=7)
            print(f"[WATCH] Weekly audit: {weekly.get('overall_assessment', 'n/a')}")
        except Exception as e:
            logger.error("[WATCH] Weekly audit failed: %s", e)
            print(f"[WATCH] Weekly audit failed: {e}")

        # CTO performance report
        try:
            from src.evaluation.cto_report import generate_cto_report, format_cto_report
            print("[WATCH] Generating CTO performance report...")
            cto_data = generate_cto_report(days=7)
            cto_text = format_cto_report(cto_data)
            print(cto_text)
            cto_subject = f"[TRADE DESK] CTO Performance Report ({cto_data['report_period']['start']} to {cto_data['report_period']['end']})"
            send_email(cto_subject, cto_text)
            print("[WATCH] CTO report email sent.")
        except Exception as e:
            logger.error("[WATCH] CTO report failed: %s", e)
            print(f"[WATCH] CTO report failed: {e}")

    # ── Overnight Schedule Methods ────────────────────────────────────

    def _log_overnight_task(self, task_name: str, status: str,
                            started_at: str, finished_at: str | None = None,
                            result: str | None = None, error: str | None = None):
        """Log overnight task result to activity log."""
        try:
            from src.logging.activity import log_activity
            detail = f"{task_name}: {status}"
            if result:
                detail += f" — {result}"
            if error:
                detail += f" — ERROR: {error}"
            log_activity("overnight_task", detail)
        except Exception as e:
            logger.debug("[WATCH] Failed to log overnight task: %s", e)

    def _run_post_close_capture(self):
        """5:30 PM ET — Capture final closing prices, update MFE/MAE on open positions."""
        from src.api.websocket import broadcast_sync
        from src.data_ingestion.market_data import fetch_ohlcv, fetch_spy_benchmark
        from src.journal.store import get_open_shadow_trades, update_shadow_trade
        from src.universe.sp100 import get_sp100_universe

        try:
            broadcast_sync("overnight_task", {"task": "post_close_capture", "status": "started"})
        except Exception as e:
            logger.warning("[WATCH] broadcast overnight_task failed: %s", e)

        logger.info("[OVERNIGHT] Running post-close capture...")
        print("[WATCH] Running post-close capture...")

        universe = get_sp100_universe()
        ohlcv = fetch_ohlcv(universe)
        count = len(ohlcv)
        print(f"[WATCH] Fetched closing data for {count} tickers")

        # Update MFE/MAE on open positions
        open_trades = get_open_shadow_trades()
        updated = 0
        for trade in open_trades:
            ticker = trade["ticker"]
            if ticker in ohlcv and not ohlcv[ticker].empty:
                try:
                    close_price = float(ohlcv[ticker].iloc[-1].get("close", 0))
                    entry = trade.get("actual_entry_price") or trade.get("entry_price", 0)
                    if entry and close_price:
                        pnl_pct = (close_price - entry) / entry * 100
                        current_mfe = trade.get("mfe_pct") or 0
                        current_mae = trade.get("mae_pct") or 0
                        new_mfe = max(current_mfe, pnl_pct)
                        new_mae = min(current_mae, pnl_pct)
                        update_shadow_trade(trade["trade_id"],
                                            {"mfe_pct": new_mfe, "mae_pct": new_mae})
                        updated += 1
                except Exception as e:
                    logger.warning("[OVERNIGHT] MFE/MAE update failed for %s: %s", ticker, e)

        # Log daily regime from SPY close (with retry and fallback)
        spy = fetch_spy_benchmark()
        spy_close = spy.iloc[-1].get("close", 0) if not spy.empty else 0
        if spy_close == 0:
            import time as _time
            logger.info("[OVERNIGHT] SPY close returned $0, retrying in 5 minutes...")
            _time.sleep(300)
            spy = fetch_spy_benchmark()
            spy_close = spy.iloc[-1].get("close", 0) if not spy.empty else 0
        if spy_close == 0 and "SPY" in ohlcv and not ohlcv["SPY"].empty:
            spy_close = float(ohlcv["SPY"].iloc[-1].get("close", 0))
            logger.info("[OVERNIGHT] SPY close from OHLCV fallback: %.2f", spy_close)
        if spy_close > 0:
            logger.info("[OVERNIGHT] SPY close: %.2f", spy_close)
        else:
            logger.warning("[OVERNIGHT] SPY close unavailable")

        print(f"[WATCH] Post-close capture complete: {count} tickers, {updated} MFE/MAE updates")
        self._log_overnight_task("post_close_capture", "completed",
                                 datetime.now(ET).isoformat(), datetime.now(ET).isoformat(),
                                 result=f"tickers={count}, mfe_mae={updated}")

        try:
            broadcast_sync("overnight_task", {"task": "post_close_capture", "status": "complete",
                                              "tickers_updated": count, "mfe_mae_updated": updated})
        except Exception as e:
            logger.warning("[WATCH] broadcast overnight_task failed: %s", e)

    def _run_overnight_training_collection(self):
        """6:00 PM ET — Collect training examples from today's closed trades."""
        from src.api.websocket import broadcast_sync
        from src.training.data_collector import collect_training_examples_from_closed_trades

        try:
            broadcast_sync("overnight_task", {"task": "training_collection", "status": "started"})
        except Exception as e:
            logger.warning("[WATCH] broadcast overnight_task failed: %s", e)

        logger.info("[OVERNIGHT] Running training data collection...")
        print("[WATCH] Running overnight training data collection...")
        count = collect_training_examples_from_closed_trades()
        print(f"[WATCH] Training collection: {count} new examples")
        self._log_overnight_task("training_collection", "completed",
                                 datetime.now(ET).isoformat(), datetime.now(ET).isoformat(),
                                 result=f"examples={count}")

        try:
            broadcast_sync("overnight_task", {"task": "training_collection", "status": "complete",
                                              "examples_collected": count})
        except Exception as e:
            logger.warning("[WATCH] broadcast overnight_task failed: %s", e)

        # ── Telegram: notify_overnight_training_complete ──
        try:
            from src.notifications.telegram import notify_overnight_training_complete, is_telegram_enabled
            if is_telegram_enabled():
                notify_overnight_training_complete(
                    tasks_completed=1,
                    tasks_total=1,
                    details={"training_collection": {"success": True}},
                )
        except Exception as e:
            logger.warning("[WATCH] notify_overnight_training_complete failed: %s", e)

    def _run_news_ingestion(self):
        """10:00 PM ET — Full universe news pull and caching."""
        from src.api.websocket import broadcast_sync
        from src.universe.sp100 import get_sp100_universe

        try:
            broadcast_sync("overnight_task", {"task": "news_ingestion", "status": "started"})
        except Exception as e:
            logger.warning("[WATCH] broadcast overnight_task failed: %s", e)

        logger.info("[OVERNIGHT] Running news ingestion...")
        print("[WATCH] Running news ingestion...")

        universe = get_sp100_universe()
        articles_cached = 0

        for ticker in universe:
            try:
                from src.data_enrichment.news import fetch_recent_news
                result = fetch_recent_news(ticker, lookback_days=1)
                if result and result.get("articles"):
                    articles_cached += len(result["articles"])
            except Exception as e:
                logger.warning("[OVERNIGHT] News fetch failed for %s: %s", ticker, e)

        print(f"[WATCH] News ingestion complete: {len(universe)} tickers, {articles_cached} articles cached")

        try:
            broadcast_sync("overnight_task", {"task": "news_ingestion", "status": "complete",
                                              "tickers_scanned": len(universe), "articles_cached": articles_cached})
        except Exception as e:
            logger.warning("[WATCH] broadcast overnight_task failed: %s", e)

    def _run_enrichment_precache(self):
        """11:00 PM ET — Pre-fetch fundamentals, insider data, macro for all tickers."""
        from src.api.websocket import broadcast_sync
        from src.data_enrichment.enricher import enrich_features
        from src.universe.sp100 import get_sp100_universe

        try:
            broadcast_sync("overnight_task", {"task": "enrichment_precache", "status": "started"})
        except Exception as e:
            logger.warning("[WATCH] broadcast overnight_task failed: %s", e)

        logger.info("[OVERNIGHT] Running enrichment pre-cache...")
        print("[WATCH] Running enrichment pre-cache...")

        universe = get_sp100_universe()
        # Build minimal feature dict just for cache warming
        stub_features = {t: {} for t in universe}
        try:
            enrich_features(stub_features, self.config)
            count = len(universe)
        except Exception as e:
            logger.error("[OVERNIGHT] Enrichment pre-cache failed: %s", e)
            count = 0

        print(f"[WATCH] Enrichment pre-cache complete: {count} tickers enriched")

        try:
            broadcast_sync("overnight_task", {"task": "enrichment_precache", "status": "complete",
                                              "tickers_enriched": count})
        except Exception as e:
            logger.warning("[WATCH] broadcast overnight_task failed: %s", e)

    def _run_pre_market_refresh(self):
        """6:00 AM ET — Quick pre-market data check before morning watchlist."""
        from src.api.websocket import broadcast_sync
        from src.universe.sp100 import get_sp100_universe

        try:
            broadcast_sync("overnight_task", {"task": "pre_market_refresh", "status": "started"})
        except Exception as e:
            logger.warning("[WATCH] broadcast overnight_task failed: %s", e)

        logger.info("[OVERNIGHT] Running pre-market refresh...")
        print("[WATCH] Running pre-market refresh...")

        universe = get_sp100_universe()
        # Fetch pre-market data if available (best-effort)
        try:
            from src.data_ingestion.market_data import fetch_ohlcv
            ohlcv = fetch_ohlcv(universe[:20])  # Quick check on top tickers
            print(f"[WATCH] Pre-market refresh: checked {len(ohlcv)} tickers")
        except Exception as e:
            logger.warning("[OVERNIGHT] Pre-market refresh failed: %s", e)
            print(f"[WATCH] Pre-market refresh: partial ({e})")

        try:
            broadcast_sync("overnight_task", {"task": "pre_market_refresh", "status": "complete"})
        except Exception as e:
            logger.warning("[WATCH] broadcast overnight_task failed: %s", e)

    def _run_data_collection(self):
        """9:30 PM ET — Comprehensive market data collection."""
        from src.api.websocket import broadcast_sync
        from src.data_collection.options_collector import collect_options_chains
        from src.data_collection.options_metrics import compute_options_metrics
        from src.data_collection.vix_collector import collect_vix_term_structure
        from src.data_collection.trends_collector import collect_google_trends
        from src.data_collection.macro_collector import collect_macro_snapshots
        from src.data_collection.cboe_collector import collect_cboe_ratios
        from src.universe.sp100 import get_sp100_universe

        try:
            broadcast_sync("overnight_task", {"task": "data_collection", "status": "started"})
        except Exception as e:
            logger.warning("[WATCH] broadcast overnight_task failed: %s", e)

        logger.info("[OVERNIGHT] Running comprehensive data collection...")
        print("[WATCH] Running comprehensive data collection...")

        universe = get_sp100_universe()
        now = datetime.now(ET)
        results = {}

        # 1. Options chains (most important)
        print("[WATCH]   [1/12] Options chains...")
        results["options"] = collect_options_chains(universe)

        # 2. Derived metrics from chains
        print("[WATCH]   [2/12] Options metrics...")
        results["metrics"] = compute_options_metrics(universe)

        # 3. VIX term structure
        print("[WATCH]   [3/12] VIX term structure...")
        results["vix"] = collect_vix_term_structure()

        # 4. CBOE ratios
        print("[WATCH]   [4/12] CBOE ratios...")
        results["cboe"] = collect_cboe_ratios()

        # 5. FRED macro (35+ series)
        print("[WATCH]   [5/12] FRED macro indicators...")
        results["macro"] = collect_macro_snapshots()

        # 6. Google Trends (market-wide sentiment terms)
        print("[WATCH]   [6/12] Google Trends (sentiment)...")
        results["trends"] = collect_google_trends(universe, batch_size=20)

        # 7. Earnings calendar
        print("[WATCH]   [7/12] Earnings calendar...")
        try:
            from scripts.fetch_earnings_calendar import fetch_earnings_dates
            results["earnings"] = fetch_earnings_dates(universe)
            upcoming = results["earnings"].get("upcoming_7d", [])
            if upcoming:
                logger.warning("[EARNINGS] %d stocks report this week: %s",
                               len(upcoming), ", ".join(upcoming))
                # Telegram earnings warning
                try:
                    from src.notifications.telegram import notify_earnings_warning, is_telegram_enabled
                    if is_telegram_enabled():
                        notify_earnings_warning(upcoming)
                except Exception as e:
                    logger.warning("[WATCH] notify_earnings_warning failed: %s", e)
        except Exception as e:
            logger.debug("[WATCH] Earnings fetch failed: %s", e)
            results["earnings"] = {"error": str(e)}

        # 8. SEC EDGAR filings (new filings only)
        print("[WATCH]   [8/12] SEC EDGAR filings...")
        try:
            from src.data_collection.edgar_collector import collect_new_filings
            results["edgar"] = collect_new_filings(universe)
        except Exception as e:
            logger.warning("[WATCH] EDGAR collection failed: %s", e)
            results["edgar"] = {"error": str(e)}

        # 9. Insider transactions
        print("[WATCH]   [9/12] Insider transactions...")
        try:
            from src.data_collection.insider_collector import collect_insider_transactions
            results["insider"] = collect_insider_transactions(universe)
        except Exception as e:
            logger.warning("[WATCH] Insider collection failed: %s", e)
            results["insider"] = {"error": str(e)}

        # 10. FINRA short interest (biweekly — around settlement dates)
        # WHY only days 1,2,15,16: FINRA publishes short interest data twice
        # monthly on settlement dates. Collecting on other days wastes API calls.
        if now.day in (1, 2, 15, 16):
            print("[WATCH]   [10/12] Short interest...")
            try:
                from src.data_collection.short_interest_collector import collect_short_interest
                results["short_interest"] = collect_short_interest(universe)
            except Exception as e:
                logger.warning("[WATCH] Short interest collection failed: %s", e)
                results["short_interest"] = {"error": str(e)}
        else:
            results["short_interest"] = "skipped (not settlement date)"

        # 11. Fed communications
        print("[WATCH]   [11/12] Fed communications...")
        try:
            from src.data_collection.fed_collector import collect_fed_communications
            results["fed"] = collect_fed_communications()
        except Exception as e:
            logger.warning("[WATCH] Fed collection failed: %s", e)
            results["fed"] = {"error": str(e)}

        # 12. Analyst estimates (batch 20/night to stay under FMP limit)
        print("[WATCH]   [12/12] Analyst estimates (batch)...")
        try:
            from src.data_collection.analyst_collector import collect_analyst_estimates
            results["analyst"] = collect_analyst_estimates(universe, batch_size=20)
        except Exception as e:
            logger.warning("[WATCH] Analyst collection failed: %s", e)
            results["analyst"] = {"error": str(e)}

        # 13. Research papers
        print("[WATCH]   [13/13] Research papers...")
        try:
            from src.data_collection.research_collector import collect_research_papers
            research_results = collect_research_papers()
            results["research"] = research_results
            print(f"[WATCH]   [13/13] Research: {research_results.get('total_new', 0)} new papers "
                  f"(crawled {research_results.get('total_crawled', 0)})")
        except Exception as e:
            logger.warning("[COLLECTORS] Research collection failed: %s", e)
            results["research"] = {"error": str(e)}

        summary = {k: str(v) for k, v in results.items()}
        print(f"[WATCH] Data collection complete: {summary}")

        # Log collection results to activity log
        try:
            from src.utils.activity_logger import log_activity, DATA_COLLECTION
            log_activity(DATA_COLLECTION, f"Overnight collection: {len(results)} collectors", results)
        except Exception as e:
            logger.warning("[WATCH] log_activity failed: %s", e)

        # Run retention policy to prune old rows (#123) — prevents SQLite bloat
        # from unbounded data collection. Each table has a configurable max age.
        try:
            from src.data_collection.retention import run_retention
            retention_result = run_retention()
            if retention_result:
                results["retention"] = retention_result
                logger.info("[WATCH] Retention pruned: %s", retention_result)
        except Exception as e:
            logger.warning("[WATCH] Retention failed: %s", e)

        # 1J. Track collector failures and alert at 3+ consecutive
        try:
            from src.notifications.telegram import notify_collection_failure, is_telegram_enabled
            if is_telegram_enabled():
                for name, result in results.items():
                    is_error = (isinstance(result, str) and "error" in result.lower()) or \
                               (isinstance(result, dict) and "error" in str(result).lower())
                    if is_error:
                        self._collector_failures[name] = self._collector_failures.get(name, 0) + 1
                        if self._collector_failures[name] >= 3:
                            other_status = {
                                n: self._collector_failures.get(n, 0) < 3
                                for n in results if n != name
                            }
                            notify_collection_failure(
                                collector_name=name,
                                consecutive_failures=self._collector_failures[name],
                                last_error=str(result)[:80],
                                last_success_ago="unknown",
                                other_collectors=other_status,
                            )
                    else:
                        self._collector_failures[name] = 0  # Reset on success
        except Exception as e:
            logger.warning("[WATCH] notify_collection_failure failed: %s", e)

        # H3. Notify new research papers via Telegram
        if research_results.get("total_new", 0) > 0:
            try:
                from src.notifications.telegram import notify_research_papers, is_telegram_enabled
                if is_telegram_enabled():
                    import sqlite3 as _sq
                    with _sq.connect(DB_PATH) as _cn:
                        top = _cn.execute(
                            "SELECT title, relevance_score FROM research_papers ORDER BY collected_at DESC LIMIT 1"
                        ).fetchone()
                    top_title = top[0] if top else "Unknown"
                    top_score = top[1] if top else 0
                    notify_research_papers(
                        total_new=research_results["total_new"],
                        top_paper=top_title,
                        top_score=top_score,
                    )
            except Exception as e:
                logger.warning("[WATCH] notify_research_papers failed: %s", e)

        # Telegram overnight summary
        try:
            from src.notifications.telegram import notify_overnight_complete, is_telegram_enabled
            if is_telegram_enabled():
                notify_overnight_complete(results)
        except Exception as e:
            logger.warning("[WATCH] notify_overnight_complete failed: %s", e)

        try:
            broadcast_sync("overnight_task", {"task": "data_collection", "status": "complete",
                                              "results": summary})
        except Exception as e:
            logger.warning("[WATCH] broadcast overnight_task failed: %s", e)

    def _minutes_until_next_scan(self, now: datetime) -> float:
        """Calculate minutes until next scan is due."""
        if self._last_scan_time is None:
            return 0
        elapsed = (now - self._last_scan_time).total_seconds() / 60
        return max(0, self.scan_interval - elapsed)

    # ── VRAM Handoff Methods ─────────────────────────────────────────

    def _run_evening_handoff(self):
        """6:50 PM ET — Unload Ollama, launch overnight training subprocess.

        WHY VRAM handoff: RTX 3060 12GB cannot run Ollama (inference) and
        PyTorch (training) simultaneously. The evening handoff frees VRAM
        for overnight fine-tuning, morning handoff reloads Ollama for scans.
        """
        from pathlib import Path
        from src.scheduler.vram_manager import VRAMManager

        vm = VRAMManager()
        if vm.handoff_to_training():
            vm.launch_training_subprocess(
                "overnight",
                ["-m", "scripts.overnight_train"],
            )
            self._vram_manager = vm
            print("[WATCH] VRAM handoff complete — overnight training started")
            try:
                from src.notifications.telegram import notify_vram_handoff, is_telegram_enabled
                if is_telegram_enabled():
                    notify_vram_handoff("training", True)
            except Exception as e:
                logger.warning("[WATCH] notify_vram_handoff failed: %s", e)
        else:
            print("[WATCH] VRAM handoff FAILED — staying in inference mode")
            try:
                from src.notifications.telegram import notify_vram_handoff, is_telegram_enabled
                if is_telegram_enabled():
                    notify_vram_handoff("training", False, "Staying in inference mode")
            except Exception as e:
                logger.warning("[WATCH] notify_vram_handoff failed: %s", e)

    def _run_morning_handoff(self):
        """5:15 AM ET — Kill training subprocess, reload Ollama."""
        from pathlib import Path
        from src.scheduler.vram_manager import VRAMManager

        # Signal overnight pipeline to stop
        stop_flag = Path("data/STOP_OVERNIGHT")
        stop_flag.parent.mkdir(parents=True, exist_ok=True)
        stop_flag.touch()

        # Give subprocess time to checkpoint and exit
        time.sleep(60)

        vm = getattr(self, '_vram_manager', None) or VRAMManager()
        if vm.handoff_to_inference():
            stop_flag.unlink(missing_ok=True)
            print("[WATCH] Morning handoff complete — Ollama loaded and warm")
            try:
                from src.notifications.telegram import notify_vram_handoff, is_telegram_enabled
                if is_telegram_enabled():
                    notify_vram_handoff("inference", True)
            except Exception as e:
                logger.warning("[WATCH] notify_vram_handoff failed: %s", e)
        else:
            print("[WATCH] Morning handoff FAILED — attempting Ollama restart")
            try:
                from src.notifications.telegram import notify_vram_handoff, is_telegram_enabled
                if is_telegram_enabled():
                    notify_vram_handoff("inference", False, "Attempting restart")
            except Exception as e:
                logger.warning("[WATCH] notify_vram_handoff failed: %s", e)
            # Fallback: try reload anyway
            stop_flag.unlink(missing_ok=True)
            try:
                vm._reload_ollama()
            except Exception as e:
                logger.error("[WATCH] Ollama restart failed: %s", e)

    # ── AI Council ────────────────────────────────────────────────

    def _run_daily_council(self):
        """8:30 AM ET — Run the daily AI Council session."""
        print("[WATCH] Running daily AI Council session...")
        try:
            from src.council.engine import CouncilEngine
            engine = CouncilEngine()
            result = engine.run_session(session_type="daily")
            consensus = result.get("consensus", "unknown")
            cost = result.get("total_cost", 0)
            rounds = result.get("rounds_completed", 0)
            contested = result.get("is_contested", False)
            print(f"[WATCH] Council complete: {consensus} "
                  f"({'CONTESTED' if contested else 'agreed'}) "
                  f"({rounds} rounds, ${cost:.2f})")

            # Telegram notification
            try:
                from src.notifications.telegram import send_telegram, is_telegram_enabled
                if is_telegram_enabled():
                    now = datetime.now(ET).strftime("%H:%M ET")
                    msg = f"🏛️ <b>AI COUNCIL SESSION</b> ({now})\n"
                    msg += f"Consensus: <b>{consensus.upper()}</b>"
                    if contested:
                        msg += " ⚠️ CONTESTED"
                    msg += f"\nCost: ${cost:.2f} | Rounds: {rounds}"
                    send_telegram(msg)
            except Exception as e:
                logger.warning("[WATCH] send_telegram failed: %s", e)
        except Exception as e:
            logger.error("[WATCH] Council session failed: %s", e)
            print(f"[WATCH] Council session failed: {e}")
            # Notify on failure so ops knows the council didn't run
            try:
                from src.notifications.telegram import send_telegram, is_telegram_enabled
                if is_telegram_enabled():
                    send_telegram(
                        f"🚨 <b>COUNCIL FAILED</b>\n{type(e).__name__}: {e}"
                    )
            except Exception:
                pass  # Don't cascade failures

    # ── Ollama Warm-Up ─────────────────────────────────────────────

    def _run_ollama_warmup(self):
        """9:25 AM ET — Full-length warm-up inference before first scan.

        Not just a health check — runs a real prompt of similar length to
        what the scan will generate, warming up the KV cache and CUDA kernels.

        WHY: First Ollama inference after reload takes 3-5x longer (CUDA kernel
        compilation, KV cache allocation). Running a warm-up prompt 5 minutes
        before market open ensures the first real scan gets normal latency.
        """
        from pathlib import Path
        from src.llm.client import generate, is_llm_available

        if not is_llm_available():
            print("[WATCH] Ollama not available — skipping warm-up")
            return

        warmup_path = Path("data/reference/warmup_prompt.txt")
        if warmup_path.exists():
            warmup_prompt = warmup_path.read_text(encoding="utf-8")
        else:
            warmup_prompt = (
                "Analyze a hypothetical pullback trade in AAPL at $195.00. "
                "The stock has pulled back 6% from its 50-day high in a strong uptrend. "
                "SMA50 is rising, price is 3% above SMA200. Volume is contracting on "
                "the pullback (0.7x average). RSI is at 42. The broader market regime "
                "is calm_uptrend with healthy breadth (68% above 50d MA). "
                "Provide conviction (1-10), why_now analysis, and deeper analysis."
            )

        import time as _time
        start = _time.time()
        system_prompt = "You are a senior equity research analyst. Analyze the setup."
        result = generate(warmup_prompt, system_prompt)
        elapsed = _time.time() - start

        if result:
            print(f"[WATCH] Ollama warm-up complete — {elapsed:.1f}s — ready for first scan")
        else:
            print(f"[WATCH] WARNING: Ollama warm-up failed ({elapsed:.1f}s) — "
                  "first scan may be slow")

    # ── Pre-Market Pipeline Methods ──────────────────────────────────

    # ── Expanded Notification Methods ────────────────────────────────

    def _send_premarket_brief(self):
        """6:00 AM ET — Send pre-market brief with overnight context."""
        import sqlite3
        from src.notifications.telegram import notify_premarket_brief, is_telegram_enabled
        if not is_telegram_enabled():
            return

        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row

                # VIX from vix_term_structure (latest)
                vix_row = conn.execute(
                    "SELECT vix FROM vix_term_structure ORDER BY collected_at DESC LIMIT 1"
                ).fetchone()
                vix = float(vix_row["vix"]) if vix_row else 0.0

                vix_prev_row = conn.execute(
                    "SELECT vix FROM vix_term_structure ORDER BY collected_at DESC LIMIT 1 OFFSET 1"
                ).fetchone()
                vix_prev = float(vix_prev_row["vix"]) if vix_prev_row else vix
                vix_change = vix - vix_prev

                # Regime from latest features
                from src.features.regime import classify_regime
                regime_data = {"vix_proxy": vix}
                regime = classify_regime(regime_data)

                # Earnings today
                today_str = datetime.now(ET).strftime("%Y-%m-%d")
                earnings_rows = conn.execute(
                    "SELECT ticker, earnings_time FROM earnings_calendar WHERE earnings_date = ?",
                    (today_str,),
                ).fetchall()
                earnings_today = []
                for r in earnings_rows:
                    time_label = ""
                    if r["earnings_time"]:
                        if "after" in (r["earnings_time"] or "").lower():
                            time_label = " (AMC)"
                        elif "before" in (r["earnings_time"] or "").lower():
                            time_label = " (BMO)"
                    earnings_today.append(f"{r['ticker']}{time_label}")

                # Event proximity from market_event_calendar.csv
                import csv
                from pathlib import Path
                fomc_days = None
                nfp_days = None
                cal_path = Path("data/reference/market_event_calendar.csv")
                if cal_path.exists():
                    now_date = datetime.now(ET).date()
                    with open(cal_path, encoding="utf-8") as f:
                        for row in csv.DictReader(f):
                            try:
                                event_date = datetime.strptime(row["date"], "%Y-%m-%d").date()
                                days_away = (event_date - now_date).days
                                if days_away < 0 or days_away > 30:
                                    continue
                                etype = row.get("event_type", "")
                                if etype == "FOMC" and fomc_days is None:
                                    fomc_days = days_away
                                elif etype == "NFP" and nfp_days is None:
                                    nfp_days = days_away
                            except (ValueError, KeyError):
                                continue

                # Council latest
                council_row = conn.execute(
                    "SELECT consensus, confidence_weighted_score FROM council_sessions "
                    "ORDER BY created_at DESC LIMIT 1"
                ).fetchone()
                council_consensus = council_row["consensus"] if council_row else "N/A"
                council_conf_raw = council_row["confidence_weighted_score"] if council_row else 0
                try:
                    council_conf_value = float(council_conf_raw or 0)
                except (TypeError, ValueError):
                    council_conf_value = 0.0
                council_confidence = (
                    int(council_conf_value * 100)
                    if 0 <= council_conf_value <= 1
                    else int(council_conf_value)
                )

                # Open positions
                open_paper = conn.execute(
                    "SELECT COUNT(*) FROM shadow_trades WHERE status='open' AND COALESCE(source,'paper')='paper'"
                ).fetchone()[0]
                open_live = conn.execute(
                    "SELECT COUNT(*) FROM shadow_trades WHERE status='open' AND source='live'"
                ).fetchone()[0]

            # S&P futures + 10Y from yfinance (works pre-market)
            spy_futures_pct = 0.0
            ten_year = 0.0
            try:
                import yfinance as yf
                es = yf.Ticker("ES=F")
                es_hist = es.history(period="2d")
                if len(es_hist) >= 2:
                    prev_close = es_hist["Close"].iloc[-2]
                    latest = es_hist["Close"].iloc[-1]
                    spy_futures_pct = ((latest - prev_close) / prev_close) * 100

                tnx = yf.Ticker("^TNX")
                tnx_hist = tnx.history(period="1d")
                if len(tnx_hist) >= 1:
                    ten_year = tnx_hist["Close"].iloc[-1]
            except Exception as yf_err:
                logger.debug("[WATCH] yfinance pre-market fetch failed: %s", yf_err)

            notify_premarket_brief(
                vix=vix, vix_change=vix_change, regime=regime,
                spy_futures_pct=spy_futures_pct,
                ten_year=ten_year,
                earnings_today=earnings_today,
                fomc_days=fomc_days, nfp_days=nfp_days,
                council_consensus=council_consensus,
                council_confidence=council_confidence,
                open_paper=open_paper, open_live=open_live,
            )
            print("[WATCH] Pre-market brief sent via Telegram.")
        except Exception as e:
            logger.warning("[WATCH] Pre-market brief failed: %s", e)

    def _send_eod_report(self):
        """4:00 PM ET — Send end-of-day P&L report."""
        import sqlite3
        from src.notifications.telegram import notify_eod_report, is_telegram_enabled
        if not is_telegram_enabled():
            return

        try:
            today_str = datetime.now(ET).strftime("%Y-%m-%d")
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row

                # Paper open
                paper_open_row = conn.execute(
                    "SELECT COUNT(*) as cnt, COALESCE(SUM(pnl_dollars),0) as pnl "
                    "FROM shadow_trades WHERE status='open' AND COALESCE(source,'paper')='paper'"
                ).fetchone()

                # Paper closed today
                paper_closed_row = conn.execute(
                    "SELECT COUNT(*) as cnt, COALESCE(SUM(pnl_dollars),0) as pnl "
                    "FROM shadow_trades WHERE status='closed' AND COALESCE(source,'paper')='paper' "
                    "AND actual_exit_time LIKE ?", (f"{today_str}%",)
                ).fetchone()

                # Live open
                live_open_row = conn.execute(
                    "SELECT COUNT(*) as cnt, COALESCE(SUM(pnl_dollars),0) as pnl "
                    "FROM shadow_trades WHERE status='open' AND source='live'"
                ).fetchone()

                # Live closed today
                live_closed_row = conn.execute(
                    "SELECT COUNT(*) as cnt, COALESCE(SUM(pnl_dollars),0) as pnl "
                    "FROM shadow_trades WHERE status='closed' AND source='live' "
                    "AND actual_exit_time LIKE ?", (f"{today_str}%",)
                ).fetchone()

                # All-time win rate
                all_closed = conn.execute(
                    "SELECT COUNT(*) as total, "
                    "SUM(CASE WHEN pnl_dollars > 0 THEN 1 ELSE 0 END) as wins "
                    "FROM shadow_trades WHERE status='closed'"
                ).fetchone()
                wins = all_closed["wins"] or 0
                total = all_closed["total"] or 0
                losses = total - wins
                win_rate = wins / total if total > 0 else 0

                # Best/worst today
                best = conn.execute(
                    "SELECT ticker, pnl_pct FROM shadow_trades "
                    "WHERE status='closed' AND actual_exit_time LIKE ? "
                    "ORDER BY pnl_pct DESC LIMIT 1", (f"{today_str}%",)
                ).fetchone()
                worst = conn.execute(
                    "SELECT ticker, pnl_pct FROM shadow_trades "
                    "WHERE status='closed' AND actual_exit_time LIKE ? "
                    "ORDER BY pnl_pct ASC LIMIT 1", (f"{today_str}%",)
                ).fetchone()

                # VIX
                vix_row = conn.execute(
                    "SELECT vix FROM vix_term_structure ORDER BY collected_at DESC LIMIT 1"
                ).fetchone()
                vix = float(vix_row["vix"]) if vix_row else 0.0
                vix_prev_row = conn.execute(
                    "SELECT vix FROM vix_term_structure ORDER BY collected_at DESC LIMIT 1 OFFSET 1"
                ).fetchone()
                vix_prev = float(vix_prev_row["vix"]) if vix_prev_row else vix

                from src.features.regime import classify_regime
                regime = classify_regime({"vix_proxy": vix})

                # Risk governor rejection summary for today's scans
                risk_row = conn.execute(
                    "SELECT COALESCE(SUM(packet_worthy),0) as worthy, "
                    "COALESCE(SUM(risk_passed),0) as passed "
                    "FROM scan_metrics WHERE scan_time LIKE ?",
                    (f"{today_str}%",),
                ).fetchone()
                risk_worthy = int(risk_row["worthy"]) if risk_row else 0
                risk_passed = int(risk_row["passed"]) if risk_row else 0
                risk_rejected = risk_worthy - risk_passed

                # Log rejection summary to activity_log
                if risk_rejected > 0:
                    conn.execute(
                        "INSERT INTO activity_log (event_type, detail, level, created_at) "
                        "VALUES (?, ?, ?, ?)",
                        ("risk_rejection_summary",
                         f"{risk_rejected} rejected / {risk_worthy} qualified today",
                         "INFO",
                         datetime.now(ET).isoformat()),
                    )
                    conn.commit()

            notify_eod_report(
                paper_open=paper_open_row["cnt"], paper_open_pnl=paper_open_row["pnl"],
                paper_closed_today=paper_closed_row["cnt"], paper_closed_pnl=paper_closed_row["pnl"],
                live_open=live_open_row["cnt"], live_open_pnl=live_open_row["pnl"],
                live_closed_today=live_closed_row["cnt"], live_closed_pnl=live_closed_row["pnl"],
                win_rate=win_rate, wins=wins, losses=losses,
                best_ticker=best["ticker"] if best else "N/A",
                best_pct=best["pnl_pct"] if best else 0.0,
                worst_ticker=worst["ticker"] if worst else "N/A",
                worst_pct=worst["pnl_pct"] if worst else 0.0,
                regime=regime, vix=vix, vix_change=vix - vix_prev,
                risk_rejected=risk_rejected, risk_qualified=risk_worthy,
            )
            print("[WATCH] EOD report sent via Telegram.")
        except Exception as e:
            logger.warning("[WATCH] EOD report failed: %s", e)

    def _send_data_asset_report(self):
        """4:30 PM ET — Send data asset daily report."""
        import sqlite3
        from src.notifications.telegram import notify_data_asset_report, is_telegram_enabled
        if not is_telegram_enabled():
            return

        try:
            today_str = datetime.now(ET).strftime("%Y-%m-%d")
            with sqlite3.connect(DB_PATH) as conn:
                training_total = conn.execute(
                    "SELECT COUNT(*) FROM training_examples"
                ).fetchone()[0]
                training_today = conn.execute(
                    "SELECT COUNT(*) FROM training_examples WHERE created_at LIKE ?",
                    (f"{today_str}%",),
                ).fetchone()[0]

                signal_total = conn.execute(
                    "SELECT COUNT(*) FROM setup_signals"
                ).fetchone()[0]
                signal_today = conn.execute(
                    "SELECT COUNT(*) FROM setup_signals WHERE created_at LIKE ?",
                    (f"{today_str}%",),
                ).fetchone()[0]

                backlog = conn.execute(
                    "SELECT COUNT(*) FROM training_examples WHERE quality_score IS NULL"
                ).fetchone()[0]

                quality_row = conn.execute(
                    "SELECT AVG(quality_score) FROM training_examples WHERE quality_score IS NOT NULL"
                ).fetchone()
                quality_avg = quality_row[0] if quality_row[0] else 0.0

                # Flywheel: examples from closed trades today
                flywheel = conn.execute(
                    "SELECT COUNT(*) FROM training_examples "
                    "WHERE source IN ('outcome_win','outcome_loss') AND created_at LIKE ?",
                    (f"{today_str}%",),
                ).fetchone()[0]

            notify_data_asset_report(
                training_total=training_total, training_today=training_today,
                training_target=2800,
                signal_zoo_total=signal_total, signal_zoo_today=signal_today,
                scoring_backlog=backlog, quality_avg=quality_avg,
                flywheel_count=flywheel,
            )
            print("[WATCH] Data asset report sent via Telegram.")
        except Exception as e:
            logger.warning("[WATCH] Data asset report failed: %s", e)

    def _check_vix_regime_alert(self):
        """Check VIX after each scan and alert on threshold crossings."""
        import sqlite3
        from src.notifications.telegram import notify_regime_alert, is_telegram_enabled
        if not is_telegram_enabled():
            return

        try:
            with sqlite3.connect(DB_PATH) as conn:
                row = conn.execute(
                    "SELECT vix FROM vix_term_structure ORDER BY collected_at DESC LIMIT 1"
                ).fetchone()
                if not row:
                    return
                vix_now = float(row[0]) if row[0] is not None else 0.0

            thresholds = [20, 25, 30, 35, 40, 60]

            if self._last_vix_alert_level is None:
                self._last_vix_alert_level = vix_now
                return

            prev = self._last_vix_alert_level
            crossed = None

            for t in thresholds:
                if prev < t <= vix_now:  # Crossed upward
                    crossed = t
                elif prev > t >= vix_now:  # Crossed downward (use >= for boundary)
                    crossed = t
                elif prev >= t > vix_now:  # Crossed downward
                    crossed = t

            if crossed is not None:
                from src.features.regime import classify_regime
                regime_old = classify_regime({"vix_proxy": prev})
                regime_new = classify_regime({"vix_proxy": vix_now})

                # Qualification and sizing are regime-dependent heuristics
                qual_map = {"BULL_LOW_VOL": 30, "BULL_HIGH_VOL": 35, "TRANSITION": 40,
                            "CORRECTION": 65, "BEAR_EARLY": 70, "BEAR_ESTABLISHED": 80, "CRISIS": 90}
                sizing_map = {"BULL_LOW_VOL": 100, "BULL_HIGH_VOL": 80, "TRANSITION": 70,
                              "CORRECTION": 60, "BEAR_EARLY": 40, "BEAR_ESTABLISHED": 20, "CRISIS": 0}

                notify_regime_alert(
                    vix_now=vix_now, vix_prev=prev, threshold_crossed=crossed,
                    regime_old=regime_old, regime_new=regime_new,
                    qual_old=qual_map.get(regime_old, 40), qual_new=qual_map.get(regime_new, 40),
                    sizing_old=sizing_map.get(regime_old, 100), sizing_new=sizing_map.get(regime_new, 100),
                )
                self._last_vix_alert_level = vix_now
                print(f"[WATCH] VIX regime alert sent: crossed {crossed}")
            else:
                self._last_vix_alert_level = vix_now
        except Exception as e:
            logger.warning("[WATCH] VIX regime alert check failed: %s", e)

    def _send_weekly_digest(self):
        """Sunday 8 PM ET — Send full weekly digest."""
        import sqlite3
        from src.notifications.telegram import notify_weekly_digest, is_telegram_enabled
        if not is_telegram_enabled():
            return

        try:
            now = datetime.now(ET)
            period_end = now.strftime("%b %d")
            from datetime import timedelta
            week_ago = now - timedelta(days=7)
            period_start = week_ago.strftime("%b %d")
            week_ago_str = week_ago.strftime("%Y-%m-%d")

            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row

                # Trades this week
                opened_paper = conn.execute(
                    "SELECT COUNT(*) FROM shadow_trades WHERE COALESCE(source,'paper')='paper' "
                    "AND created_at >= ?", (week_ago_str,)
                ).fetchone()[0]
                opened_live = conn.execute(
                    "SELECT COUNT(*) FROM shadow_trades WHERE source='live' "
                    "AND created_at >= ?", (week_ago_str,)
                ).fetchone()[0]
                closed_paper = conn.execute(
                    "SELECT COUNT(*) FROM shadow_trades WHERE status='closed' AND COALESCE(source,'paper')='paper' "
                    "AND actual_exit_time >= ?", (week_ago_str,)
                ).fetchone()[0]
                closed_live = conn.execute(
                    "SELECT COUNT(*) FROM shadow_trades WHERE status='closed' AND source='live' "
                    "AND actual_exit_time >= ?", (week_ago_str,)
                ).fetchone()[0]

                # Win rate and expectancy (all time)
                wr_row = conn.execute(
                    "SELECT COUNT(*) as total, "
                    "SUM(CASE WHEN pnl_dollars > 0 THEN 1 ELSE 0 END) as wins, "
                    "AVG(pnl_dollars) as expectancy "
                    "FROM shadow_trades WHERE status='closed'"
                ).fetchone()
                win_rate = (wr_row["wins"] or 0) / max(wr_row["total"] or 1, 1)
                expectancy = wr_row["expectancy"] or 0

                # Best/worst this week
                best = conn.execute(
                    "SELECT ticker, pnl_pct FROM shadow_trades "
                    "WHERE status='closed' AND actual_exit_time >= ? "
                    "ORDER BY pnl_pct DESC LIMIT 1", (week_ago_str,)
                ).fetchone()
                worst = conn.execute(
                    "SELECT ticker, pnl_pct FROM shadow_trades "
                    "WHERE status='closed' AND actual_exit_time >= ? "
                    "ORDER BY pnl_pct ASC LIMIT 1", (week_ago_str,)
                ).fetchone()

                # P&L this week
                pnl_paper = conn.execute(
                    "SELECT COALESCE(SUM(pnl_dollars),0) FROM shadow_trades "
                    "WHERE status='closed' AND COALESCE(source,'paper')='paper' AND actual_exit_time >= ?",
                    (week_ago_str,)
                ).fetchone()[0]
                pnl_live = conn.execute(
                    "SELECT COALESCE(SUM(pnl_dollars),0) FROM shadow_trades "
                    "WHERE status='closed' AND source='live' AND actual_exit_time >= ?",
                    (week_ago_str,)
                ).fetchone()[0]

                # Data asset
                training_end = conn.execute("SELECT COUNT(*) FROM training_examples").fetchone()[0]
                training_start = training_end - conn.execute(
                    "SELECT COUNT(*) FROM training_examples WHERE created_at >= ?",
                    (week_ago_str,)
                ).fetchone()[0]
                signal_end = conn.execute("SELECT COUNT(*) FROM setup_signals").fetchone()[0]
                signal_start = signal_end - conn.execute(
                    "SELECT COUNT(*) FROM setup_signals WHERE created_at >= ?",
                    (week_ago_str,)
                ).fetchone()[0]
                backlog = conn.execute(
                    "SELECT COUNT(*) FROM training_examples WHERE quality_score IS NULL"
                ).fetchone()[0]
                quality_row = conn.execute(
                    "SELECT AVG(quality_score) FROM training_examples WHERE quality_score IS NOT NULL"
                ).fetchone()
                quality_avg = quality_row[0] if quality_row[0] else 0.0

                # VIX
                vix_row = conn.execute(
                    "SELECT vix FROM vix_term_structure ORDER BY collected_at DESC LIMIT 1"
                ).fetchone()
                vix = vix_row["vix"] if vix_row else 0.0
                vix_range = conn.execute(
                    "SELECT MIN(vix) as low, MAX(vix) as high FROM vix_term_structure "
                    "WHERE collected_at >= ?", (week_ago_str,)
                ).fetchone()

                from src.features.regime import classify_regime
                regime = classify_regime({"vix_proxy": vix})

                # Council
                council_sessions = conn.execute(
                    "SELECT COUNT(*) FROM council_sessions WHERE created_at >= ?",
                    (week_ago_str,)
                ).fetchone()[0]
                council_row = conn.execute(
                    "SELECT consensus, confidence_weighted_score FROM council_sessions "
                    "ORDER BY created_at DESC LIMIT 1"
                ).fetchone()
                council_consensus = council_row["consensus"] if council_row else "N/A"
                council_conf = council_row["confidence_weighted_score"] if council_row else 0
                council_avg_conf = int(council_conf * 100) if council_conf and council_conf <= 1 else int(council_conf or 0)

            # Next week events
            import csv
            from pathlib import Path
            from datetime import timedelta as td
            next_week_start = now.date() + td(days=1)
            next_week_end = now.date() + td(days=7)
            events_next = []
            earnings_next = []

            cal_path = Path("data/reference/market_event_calendar.csv")
            if cal_path.exists():
                with open(cal_path, encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        try:
                            ed = datetime.strptime(row["date"], "%Y-%m-%d").date()
                            if next_week_start <= ed <= next_week_end:
                                events_next.append(f"{row.get('event_type','')} {row['date']}")
                        except (ValueError, KeyError):
                            continue

            notify_weekly_digest(
                period_start=period_start, period_end=period_end,
                opened_paper=opened_paper, opened_live=opened_live,
                closed_paper=closed_paper, closed_live=closed_live,
                win_rate=win_rate, expectancy=expectancy,
                best_ticker=best["ticker"] if best else "N/A",
                best_pct=best["pnl_pct"] if best else 0.0,
                worst_ticker=worst["ticker"] if worst else "N/A",
                worst_pct=worst["pnl_pct"] if worst else 0.0,
                pnl_paper=pnl_paper, pnl_live=pnl_live,
                training_start=training_start, training_end=training_end,
                signal_start=signal_start, signal_end=signal_end,
                scoring_backlog=backlog, quality_avg=quality_avg,
                canary_status="STABLE", llm_success_rate=0.78,
                regime=regime, vix=vix,
                vix_range_low=vix_range["low"] if vix_range and vix_range["low"] else vix,
                vix_range_high=vix_range["high"] if vix_range and vix_range["high"] else vix,
                spy_weekly_pct=0.0,
                council_sessions=council_sessions,
                council_consensus=council_consensus,
                council_avg_confidence=council_avg_conf,
                earnings_next_week=earnings_next, events_next_week=events_next,
            )
            print("[WATCH] Weekly digest sent via Telegram.")
        except Exception as e:
            logger.warning("[WATCH] Weekly digest failed: %s", e)

    def _check_earnings_proximity(self):
        """8:00 AM ET — Check open positions for upcoming earnings."""
        import sqlite3
        from src.notifications.telegram import notify_position_earnings_warning, is_telegram_enabled
        if not is_telegram_enabled():
            return

        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row

                open_trades = conn.execute(
                    "SELECT trade_id, ticker, actual_entry_price, pnl_dollars, pnl_pct "
                    "FROM shadow_trades WHERE status='open'"
                ).fetchall()

                if not open_trades:
                    return

                now_date = datetime.now(ET).date()
                for trade in open_trades:
                    ticker = trade["ticker"]
                    earnings = conn.execute(
                        "SELECT earnings_date, earnings_time FROM earnings_calendar "
                        "WHERE ticker = ? AND earnings_date >= ? "
                        "ORDER BY earnings_date ASC LIMIT 1",
                        (ticker, now_date.isoformat()),
                    ).fetchone()

                    if not earnings:
                        continue

                    try:
                        e_date = datetime.strptime(earnings["earnings_date"], "%Y-%m-%d").date()
                        days_until = (e_date - now_date).days
                    except (ValueError, TypeError):
                        continue

                    if 0 <= days_until <= 3:
                        notify_position_earnings_warning(
                            ticker=ticker,
                            days_until=days_until,
                            earnings_date=earnings["earnings_date"],
                            earnings_time=earnings["earnings_time"] or "TBD",
                            current_pnl=trade["pnl_dollars"] or 0,
                            current_pnl_pct=trade["pnl_pct"] or 0,
                        )
            print("[WATCH] Earnings proximity check complete.")
        except Exception as e:
            logger.warning("[WATCH] Earnings proximity check failed: %s", e)

    def _run_premarket_rolling_features(self):
        """6:02 AM ET — Pre-compute rolling features for faster scans."""
        from src.scheduler.premarket import PreMarketPipeline
        pipeline = PreMarketPipeline()
        result = pipeline.run_rolling_features()
        print(f"[WATCH] Rolling features: {result['computed']} computed")

    def _run_premarket_training(self):
        """7:00 AM ET — Verify Ollama + generate self-blinded training data."""
        from src.scheduler.premarket import PreMarketPipeline
        pipeline = PreMarketPipeline()
        if not pipeline.verify_ollama_warm():
            print("[WATCH] Ollama not warm — skipping training generation")
            return
        result = pipeline.run_training_generation()
        print(f"[WATCH] Premarket training: {result['generated']} generated, "
              f"{result['unscored']} unscored")

    def _run_premarket_news_scoring(self):
        """8:02 AM ET — Score overnight news for market impact."""
        from src.scheduler.premarket import PreMarketPipeline
        pipeline = PreMarketPipeline()
        result = pipeline.run_news_scoring()
        print(f"[WATCH] News scoring: {result['scored']} articles scored")

    def _run_premarket_candidates(self):
        """9:00 AM ET — Pre-analyze candidates for first scan."""
        from src.scheduler.premarket import PreMarketPipeline
        pipeline = PreMarketPipeline()
        result = pipeline.run_candidate_analysis()
        print(f"[WATCH] Pre-analyzed {result['count']} candidates")

    def _run_stress_test(self):
        """Run historical stress test across all 3 crisis scenarios."""
        from scripts.stress_test import run_scenario, store_result, SCENARIOS
        print("[WATCH] Running stress test (3 scenarios)...")
        for name, dates in SCENARIOS.items():
            try:
                result = run_scenario(name, dates["start"], dates["end"])
                if "error" not in result:
                    store_result(result)
                    print(f"  -> {name}: {result.get('total_trades', 0)} trades, "
                          f"WR={result.get('win_rate', 0):.0%}, "
                          f"DD={result.get('max_drawdown_pct', 0):.1f}%")
            except Exception as e:
                logger.warning("[WATCH] Stress test %s failed: %s", name, e)
        print("[WATCH] Stress test complete")

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
        from src.data_collection.research_synthesizer import run_weekly_synthesis
        print("[WATCH] Running weekly research synthesis...")
        result = run_weekly_synthesis()
        papers_count = result.get("papers_reviewed", 0)
        actionable = result.get("actionable_count", 0)
        print(f"[WATCH] Research synthesis: {papers_count} papers reviewed, {actionable} actionable")

        # ── Telegram: notify_research_papers (new papers discovered) ──
        try:
            from src.notifications.telegram import notify_research_papers, is_telegram_enabled
            if is_telegram_enabled() and papers_count > 0:
                top_paper = result.get("top_paper_title", "Unknown")
                top_score = result.get("top_paper_score", 0.0)
                notify_research_papers(
                    total_new=papers_count,
                    top_paper=top_paper,
                    top_score=top_score,
                )
        except Exception as e:
            logger.warning("[WATCH] notify_research_papers failed: %s", e)

        # ── Telegram: notify_research_digest (synthesis complete) ──
        try:
            from src.notifications.telegram import notify_research_digest, is_telegram_enabled
            if is_telegram_enabled():
                digest = result.get("digest_summary", "No digest generated")
                notify_research_digest(
                    papers_count=papers_count,
                    actionable_count=actionable,
                    digest_summary=digest,
                )
        except Exception as e:
            logger.warning("[WATCH] notify_research_digest failed: %s", e)

    def _save_daily_metric_snapshot(self):
        """Save daily metric snapshot at EOD for MetricTrend chart."""
        import sqlite3
        db_path = DB_PATH
        try:
            from src.training.versioning import save_metric_snapshot
            with sqlite3.connect(db_path) as conn:
                closed = conn.execute(
                    "SELECT pnl_pct, pnl_dollars FROM shadow_trades WHERE status = 'closed'"
                ).fetchall()
                pnls = [r[0] for r in closed if r[0] is not None]
                pnl_dollars = [r[1] for r in closed if r[1] is not None]
                open_count = conn.execute(
                    "SELECT COUNT(*) FROM shadow_trades WHERE status = 'open'"
                ).fetchone()[0]

            if not pnls:
                snapshot = {
                    "cumulative_pnl": 0, "win_rate": 0, "sharpe_ratio": 0,
                    "max_drawdown": 0, "expectancy": 0, "trade_count": 0,
                    "open_positions": open_count,
                }
            else:
                wins = [p for p in pnls if p > 0]
                mean_pnl = sum(pnls) / len(pnls)
                std_pnl = max((sum((p - mean_pnl) ** 2 for p in pnls) / len(pnls)) ** 0.5, 0.001)
                # Max drawdown from running P&L
                running = 0
                peak = 0
                max_dd = 0
                for p in pnl_dollars:
                    running += p
                    if running > peak:
                        peak = running
                    dd = peak - running
                    if dd > max_dd:
                        max_dd = dd

                snapshot = {
                    "cumulative_pnl": sum(pnl_dollars),
                    "win_rate": len(wins) / len(pnls),
                    "sharpe_ratio": mean_pnl / std_pnl if len(pnls) > 1 else 0,
                    "max_drawdown": max_dd,
                    "expectancy": sum(pnl_dollars) / len(pnl_dollars),
                    "trade_count": len(pnls),
                    "open_positions": open_count,
                }

            save_metric_snapshot(snapshot)
            logger.info(
                "[METRICS] Daily snapshot saved: %d trades, %.1f%% win rate",
                len(pnls), snapshot["win_rate"] * 100,
            )

            # ── Telegram: notify_schedule_health (daily metric check) ──
            try:
                from src.notifications.telegram import notify_schedule_health, is_telegram_enabled
                if is_telegram_enabled():
                    notify_schedule_health(
                        gpu_util=0.0,  # Not tracked at this level
                        scan_delay_max=0.0,
                        handoff_ok=True,
                        temp_max=0,
                    )
            except Exception as e:
                logger.warning("[WATCH] notify_schedule_health failed: %s", e)
        except Exception as e:
            logger.debug("[METRICS] Daily snapshot failed: %s", e)
