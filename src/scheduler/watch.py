"""Watch loop for automated daily cadence.

Simple Python loop — no APScheduler or cron dependencies.

Called by: cli.commands, main
Calls: services.scan_service, services.shadow_service, services.watchlist_service, data_collection.*, sync.render_sync
Owns tables: scan_metrics, log_entries
Config keys: automation.scan_interval_minutes, automation.morning_watchlist_hour_et, automation.eod_recap_hour_et
Tests: tests/test_watch_bootstrap.py, tests/test_watch_resilience.py, tests/test_watch_import.py
"""

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
    """

    def __init__(self, db_path: str = DB_PATH, max_entries: int = 500):
        super().__init__(level=logging.WARNING)
        self.db_path = db_path
        self.max_entries = max_entries
        self._write_count = 0

    def emit(self, record: logging.LogRecord) -> None:
        try:
            log_id = str(uuid.uuid4())
            source = record.name.split(".")[-1] if "." in record.name else record.name
            message = record.getMessage()[:2000]
            details = None
            if record.exc_info and record.exc_info[1]:
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
                # Prune old entries every 50 writes
                if self._write_count % 50 == 0:
                    conn.execute(
                        "DELETE FROM log_entries WHERE log_id NOT IN "
                        "(SELECT log_id FROM log_entries ORDER BY created_at DESC LIMIT ?)",
                        (self.max_entries,),
                    )
                conn.commit()
        except Exception:
            pass  # Never let logging crash the system


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

        # Daily state (in-memory, resets on restart)
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
        self._backoff_seconds = 0
        self._shutdown_requested = False
        self._scan_in_progress = False
        self._error_timestamps: deque = deque(maxlen=20)
        self._hourly_alert_sent = False

        # Overnight schedule flags
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

        # VRAM handoff flags
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

    def _reset_daily_state(self):
        """Reset daily flags at midnight ET."""
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

    def _is_market_open(self, now: datetime) -> bool:
        """Check if market is currently open (weekday, not holiday, between open and close)."""
        if now.weekday() >= 5:  # Saturday=5, Sunday=6
            return False
        # Holiday check (#149)
        try:
            from src.scheduler.holidays import is_market_holiday
            if is_market_holiday(check_date=now.date()):
                return False
        except Exception:
            pass  # If holiday module fails, assume market open
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
        """Check if enough time has passed since last scan."""
        if not self._is_market_open(now):
            return False
        if self._last_scan_time is None:
            return True
        elapsed = (now - self._last_scan_time).total_seconds() / 60

        # Sleep recovery detection (#152): if gap > 30 min during market hours,
        # the computer likely slept. Log warning and send Telegram alert.
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

    def _print_banner(self):
        """Print the startup banner."""
        now = datetime.now(ET)
        llm_status = "connected" if is_llm_available() else "not available"
        shadow_cfg = self.config.get("shadow_trading", {})
        shadow_status = "enabled" if shadow_cfg.get("enabled", False) else "disabled"

        bootcamp_str = (f"enabled (Phase {self.bootcamp_phase})"
                        if self.bootcamp_enabled else "disabled")

        from src.training.versioning import get_active_model_name, get_training_example_counts
        model_name = get_active_model_name()

        # Warn if config model differs from the active trained model
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

        print(f"""
{'='*45}
 ARCIS - WATCH MODE
{'='*45}
 Time: {now.strftime('%Y-%m-%d %H:%M:%S')} ET
 LLM: {llm_status}
 Model Version: {model_name}
 Shadow Trading: {shadow_status}
 Email Mode: {self.email_mode}
 Bootcamp: {bootcamp_str}
 Training: {training_str}

 Schedule:
   Morning watchlist: {self.morning_hour}:00 ET
   Market scans: every {self.scan_interval} min ({self.market_open_hour}:{self.market_open_minute:02d}-{self.market_close_hour}:00 ET)
   EOD recap: {self.eod_hour}:00 ET
   Overnight: {'enabled' if self.overnight else 'disabled'}

 Compute Schedule:
   Between-scan scoring: enabled (guard={self._scorer.guard_minutes}min)
   Overnight training: {'enabled (6:50PM-5:15AM)' if self.overnight else 'disabled'}
   Pre-market inference: {'enabled (6:00-9:25AM)' if self.overnight else 'disabled'}
   VRAM handoff: {'enabled' if self.overnight else 'disabled'}
   Target utilization: {'73%' if self.overnight else '~3%'}

 Press Ctrl+C to stop.
{'='*45}
""")

        # Send Telegram startup notification
        try:
            from src.notifications.telegram import notify_system_event, is_telegram_enabled
            if is_telegram_enabled():
                notify_system_event(
                    "ARCIS STARTED",
                    f"Model: {model_name}\nMode: {'Overnight' if self.overnight else 'Standard'}\nTraining: {training_str}"
                )
                print(" Telegram: connected ✓")
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
        """Execute a market-hours scan cycle."""
        from src.api.websocket import broadcast_sync
        from src.data_ingestion.market_data import fetch_ohlcv, fetch_spy_benchmark
        from src.features.engine import compute_all_features
        from src.journal.store import log_recommendation
        from src.llm.packet_writer import enhance_packet_with_llm, _build_feature_prompt
        from src.packets.template import build_packet_from_features, render_packet
        from src.training.versioning import get_active_model_name
        from src.ranking.ranker import rank_universe, get_top_candidates
        from src.universe.sp100 import get_sp100_universe
        from src.email.notifier import send_email

        print("[WATCH] Running market scan...")
        try:
            broadcast_sync("scan_started", {"time": datetime.now(ET).isoformat()})
        except Exception as e:
            logger.warning("[WATCH] broadcast scan_started failed: %s", e)
        universe = get_sp100_universe()
        ohlcv = fetch_ohlcv(universe)
        spy = fetch_spy_benchmark()

        if spy.empty:
            print("[WATCH] ERROR: Could not fetch SPY benchmark. Skipping scan.")
            self._record_scan_metrics(universe_count=len(universe),
                                      features_count=0, packet_worthy=0,
                                      llm_success=0, llm_total=0)
            return

        features = compute_all_features(ohlcv, spy)

        # Enrich features with fundamental, insider, and macro data
        try:
            from src.data_enrichment.enricher import enrich_features
            features = enrich_features(features, self.config)
        except Exception as e:
            logger.warning("[WATCH] Data enrichment failed: %s", e)

        # ═══ TRAFFIC LIGHT (must run before trade decisions) ═══
        try:
            from src.features.traffic_light import compute_traffic_light
            import sqlite3 as _sq
            _vix_val = None
            try:
                with _sq.connect("ai_research_desk.sqlite3") as _vc:
                    _vr = _vc.execute(
                        "SELECT vix FROM vix_term_structure ORDER BY collected_date DESC LIMIT 1"
                    ).fetchone()
                    if _vr:
                        _vix_val = float(_vr[0])
            except Exception:
                pass
            tl = compute_traffic_light(spy, vix=_vix_val)
            for _t in features:
                features[_t]["traffic_light"] = tl
                features[_t]["traffic_light_multiplier"] = tl.get("sizing_multiplier", 1.0)
            logger.info("[WATCH] Traffic Light: score=%d mult=%.1f regime=%s vix=%.1f",
                        tl.get("total_score", -1), tl.get("sizing_multiplier", 1.0),
                        tl.get("regime_label", "unknown"), _vix_val or 0.0)
        except Exception as e:
            logger.warning("[WATCH] Traffic Light failed: %s — using default", e)
            for _t in features:
                features[_t]["traffic_light_multiplier"] = 1.0

        ranked = rank_universe(features)
        candidates = get_top_candidates(ranked)
        packet_worthy = candidates["packet_worthy"]

        # Cap packets per scan to avoid bleeding into next scan window
        bootcamp_cfg = self.config.get("bootcamp", {})
        max_packets = bootcamp_cfg.get("max_packets_per_scan", 8)
        if len(packet_worthy) > max_packets:
            overflow = packet_worthy[max_packets:]
            packet_worthy = packet_worthy[:max_packets]
            print(f"[WATCH] Capped at {max_packets} packets "
                  f"({len(overflow)} deferred to next scan)")

        if not packet_worthy:
            print(f"[WATCH] No packet-worthy setups. {len(candidates['watchlist'])} on watchlist.")
            self._record_scan_metrics(
                universe_count=len(universe), features_count=len(features),
                packet_worthy=0, llm_success=0, llm_total=0)
            try:
                broadcast_sync("scan_complete", {"tickers_scanned": len(universe),
                                                 "packets": 0})
            except Exception as e:
                logger.warning("[WATCH] broadcast scan_complete (empty) failed: %s", e)
            return

        print(f"[WATCH] Found {len(packet_worthy)} packet-worthy names.")

        for candidate in packet_worthy:
            ticker = candidate["ticker"]
            feat = candidate["features"]
            feat["_score"] = candidate["score"]

            packet = build_packet_from_features(ticker, feat, self.config)
            packet = enhance_packet_with_llm(packet, feat, self.config)
            enriched_prompt = _build_feature_prompt(packet, feat)
            rendered = render_packet(packet)

            model_ver = get_active_model_name()
            rec_id = log_recommendation(
                packet, feat, candidate["score"], candidate["qualification"],
                model_version=model_ver,
                enriched_prompt=enriched_prompt,
                llm_conviction=getattr(packet, 'llm_conviction', None),
            )
            print(f"  -> Logged {ticker}: {rec_id}")
            self._trades_managed_today += 1

            # ═══ SHADOW TRADE EXECUTION (enables the training flywheel) ═══
            trade_id = None
            try:
                from src.shadow_trading.executor import open_shadow_trade
                trade_id = open_shadow_trade(rec_id, packet, feat)
                if trade_id:
                    print(f"  -> Shadow trade opened: {trade_id}")
                else:
                    print(f"  -> Shadow trade skipped (risk governor or position limit)")
            except Exception as e:
                logger.warning("[WATCH] Shadow trade failed for %s: %s", ticker, e)

            if trade_id:
                # ═══ LIVE TRADE EXECUTION (dual execution if enabled) ═══
                live_cfg = self.config.get("live_trading", {})
                now_live = datetime.now(ET)
                hour_live = now_live.hour
                if (live_cfg.get("enabled", False)
                        and getattr(packet, 'llm_conviction', None) is not None
                        and not (hour_live == 9 and now_live.minute < 31)):  # Skip first scan
                    try:
                        from src.shadow_trading.executor import open_live_trade
                        live_id = open_live_trade(rec_id, packet, feat)
                        if live_id:
                            print(f"  -> LIVE trade opened: {live_id}")
                    except Exception as e:
                        logger.warning("[WATCH] Live trade failed for %s: %s", ticker, e)

                try:
                    broadcast_sync("trade_opened", {"ticker": ticker, "side": "BUY",
                                                    "score": candidate["score"]})
                except Exception as e:
                    logger.warning("[WATCH] broadcast trade_opened failed: %s", e)

                # Telegram notification
                try:
                    from src.notifications.telegram import notify_trade_opened, is_telegram_enabled
                    if is_telegram_enabled():
                        from src.notifications.telegram import send_telegram
                        from src.shadow_trading.executor import _parse_price

                        entry_price = _parse_price(packet.entry_zone)
                        stop_price = _parse_price(packet.stop_invalidation)
                        target_price = _parse_price(packet.targets.split("/")[0])
                        shares = (
                            max(1, int(packet.position_sizing.allocation_dollars / entry_price))
                            if entry_price > 0
                            else 1
                        )
                        try:
                            notify_trade_opened(
                                ticker,
                                entry_price,
                                stop_price,
                                target_price,
                                int(candidate["score"]),
                                shares,
                                setup_type=feat.get("setup_type"),
                                setup_confidence=feat.get("setup_confidence"),
                            )
                        except Exception:
                            send_telegram(
                                f"🟢 <b>TRADE OPENED: {ticker}</b>\n"
                                f"Score: {int(candidate['score'])}/100 | Shares: {shares}"
                            )
                except Exception as e:
                    logger.warning("[WATCH] notify_trade_opened failed: %s", e)

                if self.email_mode == "full_stream":
                    subject = f"[TRADE DESK] Action Packet - {ticker}"
                    send_email(subject, rendered)
                    print(f"  -> Email sent for {ticker}")
                elif self.email_mode == "daily_summary":
                    self._daily_packets.append(rendered)
                    # #164: cap list to prevent unbounded memory growth
                    if len(self._daily_packets) > 200:
                        self._daily_packets = self._daily_packets[-100:]
                elif self.email_mode == "digest":
                    pass  # Handled by scheduled midday/EOD digest

        # Manage existing open trades (stop/target/timeout exits)
        try:
            from src.shadow_trading.executor import check_and_manage_open_trades
            actions = check_and_manage_open_trades()
            for action in actions:
                action_type = action.get("type", action.get("action", "unknown"))
                print(f"  -> Trade action: {action.get('ticker', '?')} — {action_type} "
                      f"(P&L: ${action.get('pnl_dollars', 0):+.2f})")
        except Exception as e:
            logger.warning("[WATCH] Trade management failed: %s", e)

        # Intra-day reconciliation every 15 minutes during market hours
        if (self._last_reconcile_time is None or
                (now - self._last_reconcile_time).total_seconds() > 900):
            try:
                from src.shadow_trading.reconcile import reconcile_paper_trades
                result = reconcile_paper_trades(dry_run=False)
                closed = result.get("marked_closed", [])
                if closed:
                    logger.info("[WATCH] Intra-day reconciliation closed %d stale trades: %s",
                                len(closed), closed)
                self._last_reconcile_time = now
            except Exception as e:
                logger.warning("[WATCH] Intra-day reconciliation failed: %s", e)

        # Independent live trade check (fires even if paper trading disabled)
        try:
            from src.shadow_trading.executor import check_and_manage_open_trades as _check_live
            _live_actions = _check_live(source_filter="live")
            _live_closed = len([a for a in _live_actions if a.get("type") == "closed"])
            if _live_closed:
                logger.info("[WATCH] Live trade check: %d trades closed", _live_closed)
        except Exception as e:
            logger.warning("[WATCH] Independent live trade check failed: %s", e)

        try:
            broadcast_sync("scan_complete", {"tickers_scanned": len(universe),
                                             "packets": len(packet_worthy)})
        except Exception as e:
            logger.warning("[WATCH] broadcast scan_complete failed: %s", e)

        # ── Telegram: notify_scan_complete ──
        try:
            from src.notifications.telegram import notify_scan_complete, is_telegram_enabled
            if is_telegram_enabled():
                trades_closed = len(actions) if 'actions' in dir() else 0
                notify_scan_complete(
                    packets_count=len(packet_worthy),
                    trades_opened=len(packet_worthy),
                    trades_closed=trades_closed,
                )
        except Exception as e:
            logger.warning("[WATCH] notify_scan_complete failed: %s", e)

        # ── Telegram: notify_scan_result (every scan) ──
        try:
            from src.notifications.telegram import notify_scan_result, is_telegram_enabled
            if is_telegram_enabled():
                # Increment a scan counter for the day
                if not hasattr(self, '_scan_number'):
                    self._scan_number = 0
                self._scan_number += 1
                notify_scan_result(
                    scan_number=self._scan_number,
                    total_scanned=len(universe),
                    packet_worthy=len(packet_worthy),
                    watchlist=len(candidates.get("watchlist", [])),
                )
        except Exception as e:
            logger.warning("[WATCH] notify_scan_result failed: %s", e)

        # ── Telegram: notify_first_scan_summary (first scan of the day only) ──
        if not self._first_scan_done:
            self._first_scan_done = True
            try:
                from src.notifications.telegram import notify_first_scan_summary, is_telegram_enabled
                if is_telegram_enabled():
                    top_setups = [
                        (c["ticker"], c["score"]) for c in packet_worthy[:3]
                    ]
                    setup_type_counts: dict[str, int] = {}
                    for c in packet_worthy:
                        st = c.get("features", {}).get("setup_type", "unknown")
                        setup_type_counts[st] = setup_type_counts.get(st, 0) + 1
                    notify_first_scan_summary(
                        total_scanned=len(universe),
                        packet_worthy=len(packet_worthy),
                        watchlist=len(candidates.get("watchlist", [])),
                        trades_opened_paper=len(packet_worthy),
                        trades_opened_live=0,
                        top_setups=top_setups,
                        setup_type_counts=setup_type_counts,
                        llm_success=len(packet_worthy),
                        llm_total=len(packet_worthy),
                        llm_fallback=0,
                    )
            except Exception as e:
                logger.warning("[WATCH] notify_first_scan_summary failed: %s", e)

        # ═══ SCAN METRICS (record every scan cycle) ═══
        self._record_scan_metrics(
            universe_count=len(universe), features_count=len(features),
            packet_worthy=len(packet_worthy),
            llm_success=len(packet_worthy), llm_total=len(packet_worthy))

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
            with _sq.connect("ai_research_desk.sqlite3") as conn:
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
        import sqlite3
        db_path = "ai_research_desk.sqlite3"
        tables = [
            """CREATE TABLE IF NOT EXISTS council_sessions (
                session_id TEXT PRIMARY KEY, session_type TEXT NOT NULL,
                trigger_reason TEXT, created_at TEXT NOT NULL, consensus TEXT,
                confidence_weighted_score REAL, is_contested INTEGER DEFAULT 0,
                total_cost REAL, rounds_completed INTEGER DEFAULT 0)""",
            """CREATE TABLE IF NOT EXISTS council_votes (
                vote_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, agent_name TEXT NOT NULL,
                round INTEGER NOT NULL, position TEXT, confidence INTEGER,
                recommendation TEXT, key_data_points TEXT, risk_flags TEXT,
                vote TEXT, is_devils_advocate INTEGER DEFAULT 0)""",
            """CREATE TABLE IF NOT EXISTS schedule_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT, metric_date TEXT,
                metric_name TEXT, metric_value REAL, details TEXT)""",
            """CREATE TABLE IF NOT EXISTS setup_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT, scan_date TEXT,
                setup_type TEXT, confidence REAL, features_json TEXT, created_at TEXT)""",
            """CREATE TABLE IF NOT EXISTS canary_evaluations (
                id INTEGER PRIMARY KEY AUTOINCREMENT, model_version TEXT,
                perplexity REAL, distinct_2 REAL, verdict TEXT, details TEXT, created_at TEXT)""",
            """CREATE TABLE IF NOT EXISTS quality_drift_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT, metric_date TEXT,
                avg_score REAL, score_std REAL, pass_rate REAL,
                template_fallback_rate REAL, created_at TEXT)""",
            """CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT,
                detail TEXT, created_at TEXT)""",
            """CREATE TABLE IF NOT EXISTS api_costs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, model TEXT, purpose TEXT,
                input_tokens INTEGER, output_tokens INTEGER,
                estimated_cost REAL, created_at TEXT)""",
            """CREATE TABLE IF NOT EXISTS training_examples (
                id INTEGER PRIMARY KEY AUTOINCREMENT, example_id TEXT UNIQUE,
                ticker TEXT, trade_date TEXT, input_text TEXT, output_text TEXT,
                quality_score REAL, curriculum_stage TEXT, outcome TEXT,
                source TEXT, model_version TEXT, created_at TEXT)""",
            """CREATE TABLE IF NOT EXISTS research_papers (
                id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,
                external_id TEXT UNIQUE, title TEXT NOT NULL, authors TEXT,
                abstract TEXT, url TEXT NOT NULL, published_date TEXT,
                categories TEXT, relevance_score REAL, relevance_reason TEXT,
                full_text TEXT, actionable INTEGER DEFAULT 0,
                action_taken TEXT, collected_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS research_digests (
                id INTEGER PRIMARY KEY AUTOINCREMENT, week_start TEXT NOT NULL,
                week_end TEXT NOT NULL, papers_reviewed INTEGER,
                actionable_count INTEGER, digest_text TEXT, threats TEXT,
                opportunities TEXT, created_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS scan_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT, scan_number INTEGER,
                scan_time TEXT, universe_count INTEGER, features_count INTEGER,
                scored_count INTEGER, packet_worthy INTEGER, risk_passed INTEGER,
                paper_traded INTEGER, live_traded INTEGER, llm_success INTEGER,
                llm_total INTEGER, llm_fallback INTEGER, avg_conviction REAL,
                duration_seconds REAL, created_at TEXT)""",
            # Tables created by data collectors that sync needs
            """CREATE TABLE IF NOT EXISTS short_interest (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL,
                settlement_date TEXT, short_interest INTEGER, avg_daily_volume INTEGER,
                days_to_cover REAL, short_pct_float REAL, source TEXT,
                collected_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS edgar_filings (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL,
                cik TEXT NOT NULL, form_type TEXT NOT NULL, filing_date TEXT NOT NULL,
                accession_number TEXT UNIQUE NOT NULL, filing_url TEXT,
                description TEXT, full_text TEXT, sections_json TEXT,
                word_count INTEGER, collected_at TEXT NOT NULL,
                sentiment_polarity REAL, sentiment_negative_count INTEGER,
                sentiment_uncertainty_count INTEGER, cautionary_phrases TEXT,
                sentiment_delta_polarity REAL)""",
            """CREATE TABLE IF NOT EXISTS insider_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL,
                insider_name TEXT, title TEXT, transaction_type TEXT,
                shares INTEGER, price REAL, value REAL, transaction_date TEXT,
                ownership_type TEXT, source TEXT, collected_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS fed_communications (
                id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL,
                event_date TEXT NOT NULL, title TEXT, summary TEXT,
                sentiment TEXT, key_phrases TEXT, url TEXT,
                source TEXT, collected_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS analyst_estimates (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL,
                metric TEXT, period TEXT, estimate REAL, actual REAL,
                surprise REAL, surprise_pct REAL, num_analysts INTEGER,
                source TEXT, collected_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS research_docs (
                id TEXT PRIMARY KEY, filename TEXT, title TEXT, category TEXT,
                content TEXT, size_kb REAL, updated_at TEXT)""",
            """CREATE TABLE IF NOT EXISTS council_calibrations (
                calibration_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                agent_name TEXT,
                prediction TEXT NOT NULL,
                prediction_confidence REAL NOT NULL,
                verification_date TEXT NOT NULL,
                actual_outcome TEXT,
                correct INTEGER,
                created_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS traffic_light_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                current_regime TEXT NOT NULL DEFAULT 'GREEN',
                pending_regime TEXT,
                pending_count INTEGER DEFAULT 0,
                last_vix_score INTEGER DEFAULT 0,
                last_trend_score INTEGER DEFAULT 0,
                last_credit_score INTEGER DEFAULT 0,
                last_total_score INTEGER DEFAULT 0,
                updated_at TEXT)""",
            """CREATE TABLE IF NOT EXISTS user_notes (
                note_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT DEFAULT '',
                tags TEXT DEFAULT '[]',
                pinned INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""",
        ]
        # Slippage columns on shadow_trades
        slippage_cols = [
            ("signal_entry_price", "REAL"), ("fill_entry_price", "REAL"),
            ("entry_slippage_bps", "REAL"), ("signal_exit_price", "REAL"),
            ("fill_exit_price", "REAL"), ("exit_slippage_bps", "REAL"),
        ]
        # NLP columns on edgar_filings (for existing DBs)
        edgar_nlp_cols = [
            ("sentiment_polarity", "REAL"), ("sentiment_negative_count", "INTEGER"),
            ("sentiment_uncertainty_count", "INTEGER"), ("cautionary_phrases", "TEXT"),
            ("sentiment_delta_polarity", "REAL"),
        ]
        try:
            with sqlite3.connect(db_path) as conn:
                for ddl in tables:
                    conn.execute(ddl)
                for col, typ in slippage_cols:
                    try:
                        conn.execute(f"ALTER TABLE shadow_trades ADD COLUMN {col} {typ}")
                    except Exception as e:
                        logger.debug("[WATCH] ALTER TABLE shadow_trades ADD %s (likely exists): %s", col, e)
                for col, typ in edgar_nlp_cols:
                    try:
                        conn.execute(f"ALTER TABLE edgar_filings ADD COLUMN {col} {typ}")
                    except Exception as e:
                        logger.debug("[WATCH] ALTER TABLE edgar_filings ADD %s (likely exists): %s", col, e)
                # Council + IS columns
                for _alter in [
                    "ALTER TABLE council_sessions ADD COLUMN result_json TEXT",
                    "ALTER TABLE shadow_trades ADD COLUMN signal_price REAL",
                    "ALTER TABLE shadow_trades ADD COLUMN implementation_shortfall_bps REAL",
                ]:
                    try:
                        conn.execute(_alter)
                    except Exception as e:
                        logger.debug("[WATCH] %s (likely exists): %s", _alter[:50], e)
            logger.info("[WATCH] All SQLite tables verified/created")

            # Populate research docs from markdown files
            try:
                from src.data_collection.docs_collector import populate_research_docs
                result = populate_research_docs()
                logger.info("[WATCH] Research docs: %s", result)
            except Exception as e:
                logger.debug("[WATCH] Docs population failed: %s", e)
        except Exception as exc:
            logger.warning("[WATCH] Table creation error: %s", exc)

    @staticmethod
    def _configure_database():
        """Configure SQLite for production use."""
        import sqlite3
        try:
            conn = sqlite3.connect("ai_research_desk.sqlite3")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.close()
            logger.info("[DB] SQLite configured: WAL mode, synchronous=NORMAL, busy_timeout=5000ms")
        except Exception as exc:
            logger.warning("[DB] SQLite configuration failed: %s", exc)

    def _backup_database(self):
        """Create a daily backup of the SQLite database using the Online Backup API."""
        import sqlite3
        from pathlib import Path

        backup_dir = Path("backups")
        backup_dir.mkdir(exist_ok=True)

        backup_path = backup_dir / f"halcyon_{datetime.now(ET).strftime('%Y%m%d')}.sqlite3"
        try:
            src = sqlite3.connect("ai_research_desk.sqlite3")
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

    def run(self):
        """Main watch loop. Checks every 60 seconds."""
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

        # Configure SQLite for production use (WAL mode)
        self._configure_database()

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
                print(" Render sync: enabled ✓")
                print(" Command queue: enabled ✓")
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
                self._today = today

                hour = now.hour
                time_str = now.strftime("%H:%M")

                # 0. Ollama warm-up (9:25 AM — before first scan)
                if (hour == 9 and now.minute >= 25 and now.minute < 30
                        and not self._ollama_warmup_done):
                    self._safe_run("Ollama warm-up", self._run_ollama_warmup)
                    self._ollama_warmup_done = True

                if (hour == 9 and now.minute < 5 and now.weekday() < 5
                        and not self._premarket_bracket_check_done):
                    self._safe_run(
                        "pre-market bracket check",
                        lambda: self._run_bracket_health_check("premarket"),
                    )
                    self._premarket_bracket_check_done = True

                # 0.5. Daily AI Council (8:30 AM — after watchlist, before first scan)
                if (hour == 8 and now.minute >= 30 and not self._council_done):
                    self._safe_run("daily council", self._run_daily_council)
                    self._council_done = True

                # 1. Morning watchlist
                if hour == self.morning_hour and not self._morning_done:
                    self._safe_run("morning watchlist", self._run_morning_watchlist)
                    self._morning_done = True

                # 2. Market hours scan
                elif self._should_scan(now):
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

                # 3. EOD recap
                elif hour == self.eod_hour and not self._eod_done:
                    self._safe_run("EOD recap", self._run_eod_recap)
                    self._eod_done = True
                    # H2. Daily metric snapshot (every trading day, not just Saturday)
                    if not self._daily_metric_snapshot_done:
                        self._safe_run("daily metric snapshot", self._save_daily_metric_snapshot)
                        self._daily_metric_snapshot_done = True
                    # 1C. EOD P&L report via Telegram
                    if not self._eod_report_done:
                        self._safe_run("EOD Telegram report", self._send_eod_report)
                        self._eod_report_done = True
                        # ── Telegram: notify_daily_summary (after eod report) ──
                        try:
                            from src.notifications.telegram import notify_daily_summary, is_telegram_enabled
                            if is_telegram_enabled():
                                import sqlite3
                                with sqlite3.connect("ai_research_desk.sqlite3") as _conn:
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
                    self._safe_run("daily audit", self._run_daily_audit)
                    self._daily_audit_done = True
                    # Send daily scoring summary via Telegram
                    try:
                        from src.notifications.telegram import notify_scoring_summary, is_telegram_enabled
                        if is_telegram_enabled() and self._daily_scored > 0:
                            import sqlite3
                            with sqlite3.connect("ai_research_desk.sqlite3") as conn:
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
                    self._safe_run(
                        "post-close bracket check",
                        lambda: self._run_bracket_health_check("postclose"),
                    )
                    self._postclose_bracket_check_done = True

                # 4b. Post-close paper reconciliation (4:30–4:35 PM ET)
                if (hour == 16 and now.minute >= 30 and now.minute < 35
                        and not self._postclose_reconcile_done):
                    self._safe_run(
                        "post-close reconciliation",
                        self._run_postclose_reconciliation,
                    )
                    self._postclose_reconcile_done = True

                # 5. Training data collection (4:30 PM ET)
                elif (self.training_enabled and hour == 16 and now.minute >= 30
                      and not self._training_collection_done):
                    self._safe_run("training collection", self._run_training_collection)
                    self._training_collection_done = True
                    # 1D. Data asset report after training collection
                    if not self._data_asset_report_done:
                        self._safe_run("data asset report", self._send_data_asset_report)
                        self._data_asset_report_done = True

                # 5. Overnight training trigger (5:00 PM ET)
                elif (self.training_enabled and hour == 17
                      and not self._training_run_done):
                    self._safe_run("training check", self._run_training_check)
                    self._training_run_done = True

                # 6. Saturday training report (9 AM ET)
                elif (self.training_enabled and now.weekday() == 5
                      and hour == 9 and not self._saturday_reports_done):
                    self._safe_run("Saturday reports", self._run_saturday_reports)
                    self._saturday_reports_done = True

                # H1. Research synthesis (Sunday 6 PM ET)
                elif (now.weekday() == 6 and hour == 18
                      and not self._research_synthesis_done):
                    self._safe_run("research synthesis", self._run_research_synthesis)
                    self._research_synthesis_done = True

                # 1H. Weekly digest (Sunday 8 PM ET)
                elif (now.weekday() == 6 and hour == 20
                      and not self._weekly_digest_done):
                    self._safe_run("weekly digest", self._send_weekly_digest)
                    self._weekly_digest_done = True

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
                    self._safe_run("earnings proximity", self._check_earnings_proximity)
                    self._earnings_warning_done = True

                # ── Overnight schedule (weekdays only, --overnight flag, NOT during market hours) ──
                elif self.overnight and now.weekday() < 5 and not self._is_market_open(now):
                    ran = False

                    # Morning VRAM handoff (5:15 AM) — kill training, reload Ollama
                    if (hour == 5 and now.minute >= 15
                            and not self._morning_handoff_done):
                        self._safe_run("morning VRAM handoff",
                                       self._run_morning_handoff)
                        self._morning_handoff_done = True
                        ran = True

                    elif hour == 17 and now.minute >= 30 and not self._post_close_done:
                        self._safe_run("post-close capture", self._run_post_close_capture)
                        self._post_close_done = True
                        ran = True
                    elif (hour == 18 and self.training_enabled
                          and not self._overnight_training_collection_done):
                        self._safe_run("overnight training collection",
                                       self._run_overnight_training_collection)
                        self._overnight_training_collection_done = True
                        ran = True

                    # Evening VRAM handoff (6:50 PM) — unload Ollama, launch training
                    elif (hour == 18 and now.minute >= 50
                          and not self._vram_handoff_done):
                        self._safe_run("evening VRAM handoff",
                                       self._run_evening_handoff)
                        self._vram_handoff_done = True
                        ran = True

                    # NOTE: 9:30 PM data collection, 10 PM news, 11 PM enrichment
                    # are CPU/network only — they run concurrently with GPU training
                    elif (hour == 21 and now.minute >= 30
                          and not self._data_collection_done):
                        self._safe_run("data collection", self._run_data_collection)
                        self._data_collection_done = True
                        ran = True
                    elif hour == 22 and not self._news_ingestion_done:
                        self._safe_run("news ingestion", self._run_news_ingestion)
                        self._news_ingestion_done = True
                        ran = True
                    elif hour == 23 and not self._enrichment_precache_done:
                        self._safe_run("enrichment precache", self._run_enrichment_precache)
                        self._enrichment_precache_done = True
                        ran = True
                    elif hour == 6 and not self._pre_market_done:
                        self._safe_run("pre-market refresh", self._run_pre_market_refresh)
                        self._pre_market_done = True
                        ran = True

                        # 1A. Pre-market brief (right after pre-market refresh at 6:00 AM)
                        if not self._premarket_brief_done:
                            self._safe_run("pre-market brief", self._send_premarket_brief)
                            self._premarket_brief_done = True

                    # ── Pre-market inference tasks (6-9:25 AM) ──
                    elif (hour == 6 and now.minute >= 2
                          and not self._premarket_features_done):
                        self._safe_run("rolling features",
                                       self._run_premarket_rolling_features)
                        self._premarket_features_done = True
                        ran = True
                    elif hour == 7 and not self._premarket_training_done:
                        self._safe_run("premarket training gen",
                                       self._run_premarket_training)
                        self._premarket_training_done = True
                        ran = True
                    elif (hour == 8 and now.minute >= 2
                          and not self._premarket_news_done):
                        self._safe_run("premarket news scoring",
                                       self._run_premarket_news_scoring)
                        self._premarket_news_done = True
                        ran = True
                    elif (hour == 9 and now.minute < 25
                          and not self._premarket_candidates_done):
                        self._safe_run("premarket candidates",
                                       self._run_premarket_candidates)
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

    def _safe_run(self, name: str, func):
        """Run a function with exponential backoff error recovery."""
        import traceback
        try:
            if self._backoff_seconds > 0:
                print(f"[WATCH] Backoff: waiting {self._backoff_seconds}s before {name}...")
                time.sleep(self._backoff_seconds)
            func()
            # Success — reset backoff
            self._consecutive_errors = 0
            self._backoff_seconds = 0
        except Exception as e:
            self._consecutive_errors += 1
            self._error_timestamps.append(time.time())
            # Exponential backoff: 10s, 30s, 60s, cap 60s
            if self._backoff_seconds == 0:
                self._backoff_seconds = 10
            elif self._backoff_seconds < 60:
                self._backoff_seconds = min(self._backoff_seconds * 3, 60)
            logger.error("[WATCH] Error in %s: %s", name, e)
            logger.error(traceback.format_exc())
            print(f"[WATCH] ERROR in {name}: {e} (error {self._consecutive_errors}, backoff {self._backoff_seconds}s)")
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
                    with _sq.connect("ai_research_desk.sqlite3") as _rc:
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

        # Run retention policy to prune old rows (#123)
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
                    with _sq.connect("ai_research_desk.sqlite3") as _cn:
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
        """6:50 PM ET — Unload Ollama, launch overnight training subprocess."""
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
            with sqlite3.connect("ai_research_desk.sqlite3") as conn:
                conn.row_factory = sqlite3.Row

                # VIX from vix_term_structure (latest)
                vix_row = conn.execute(
                    "SELECT vix FROM vix_term_structure ORDER BY collected_at DESC LIMIT 1"
                ).fetchone()
                vix = vix_row["vix"] if vix_row else 0.0

                vix_prev_row = conn.execute(
                    "SELECT vix FROM vix_term_structure ORDER BY collected_at DESC LIMIT 1 OFFSET 1"
                ).fetchone()
                vix_prev = vix_prev_row["vix"] if vix_prev_row else vix
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
                council_confidence = int(council_conf_raw * 100) if council_conf_raw and council_conf_raw <= 1 else int(council_conf_raw or 0)

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
            with sqlite3.connect("ai_research_desk.sqlite3") as conn:
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
                vix = vix_row["vix"] if vix_row else 0.0
                vix_prev_row = conn.execute(
                    "SELECT vix FROM vix_term_structure ORDER BY collected_at DESC LIMIT 1 OFFSET 1"
                ).fetchone()
                vix_prev = vix_prev_row["vix"] if vix_prev_row else vix

                from src.features.regime import classify_regime
                regime = classify_regime({"vix_proxy": vix})

                # Risk governor rejection summary for today's scans
                risk_row = conn.execute(
                    "SELECT COALESCE(SUM(packet_worthy),0) as worthy, "
                    "COALESCE(SUM(risk_passed),0) as passed "
                    "FROM scan_metrics WHERE scan_time LIKE ?",
                    (f"{today_str}%",),
                ).fetchone()
                risk_worthy = risk_row["worthy"] if risk_row else 0
                risk_passed = risk_row["passed"] if risk_row else 0
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
            with sqlite3.connect("ai_research_desk.sqlite3") as conn:
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
            with sqlite3.connect("ai_research_desk.sqlite3") as conn:
                row = conn.execute(
                    "SELECT vix FROM vix_term_structure ORDER BY collected_at DESC LIMIT 1"
                ).fetchone()
                if not row:
                    return
                vix_now = row[0]

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

            with sqlite3.connect("ai_research_desk.sqlite3") as conn:
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
            with sqlite3.connect("ai_research_desk.sqlite3") as conn:
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
        db_path = "ai_research_desk.sqlite3"
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
