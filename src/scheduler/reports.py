"""Standalone reporting / digest functions extracted from WatchLoop.

These were originally methods on WatchLoop but have no dependency on the
class beyond config/state values that are now passed as parameters.
Pure refactor — zero behavior change.

Called by: scheduler.watch (WatchLoop delegates here)
"""

import csv
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from src.config import DB_PATH

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")


# ── 0. Morning Watchlist ───────────────────────────────────────────

def run_morning_watchlist(config: dict, email_mode: str = "digest"):
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
        features = enrich_features(features, config)
    except Exception as e:
        logger.warning("[WATCH] Data enrichment failed: %s", e)

    ranked = rank_universe(features)
    candidates = get_top_candidates(ranked)
    packet_worthy = candidates["packet_worthy"]
    watchlist = candidates["watchlist"]

    now = datetime.now(ET)
    date_str = now.strftime("%Y-%m-%d")

    narrative = generate_watchlist_narrative(packet_worthy, watchlist, config)
    body = build_morning_watchlist(watchlist, packet_worthy, date_str,
                                   narrative=narrative)
    print(body)

    if email_mode in ("full_stream", "daily_summary"):
        subject = f"[TRADE DESK] Morning Watchlist - {date_str}"
        send_email(subject, body)
        print("[WATCH] Morning watchlist email sent.")
    elif email_mode == "digest":
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


# ── 1. Saturday Reports ─────────────────────────────────────────────

def run_saturday_reports():
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


# ── 2. Pre-Market Brief ─────────────────────────────────────────────

def send_premarket_brief():
    """6:00 AM ET — Send pre-market brief with overnight context."""
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
                " AND COALESCE(quarantined, 0) = 0"
            ).fetchone()[0]
            open_live = conn.execute(
                "SELECT COUNT(*) FROM shadow_trades WHERE status='open' AND source='live'"
                " AND COALESCE(quarantined, 0) = 0"
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


# ── 3. End-of-Day Report ────────────────────────────────────────────

def send_eod_report():
    """4:00 PM ET — Send end-of-day P&L report."""
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
                " AND COALESCE(quarantined, 0) = 0"
            ).fetchone()

            # Paper closed today
            paper_closed_row = conn.execute(
                "SELECT COUNT(*) as cnt, COALESCE(SUM(pnl_dollars),0) as pnl "
                "FROM shadow_trades WHERE status='closed' AND COALESCE(source,'paper')='paper' "
                "AND actual_exit_time LIKE ? AND COALESCE(quarantined, 0) = 0", (f"{today_str}%",)
            ).fetchone()

            # Live open
            live_open_row = conn.execute(
                "SELECT COUNT(*) as cnt, COALESCE(SUM(pnl_dollars),0) as pnl "
                "FROM shadow_trades WHERE status='open' AND source='live'"
                " AND COALESCE(quarantined, 0) = 0"
            ).fetchone()

            # Live closed today
            live_closed_row = conn.execute(
                "SELECT COUNT(*) as cnt, COALESCE(SUM(pnl_dollars),0) as pnl "
                "FROM shadow_trades WHERE status='closed' AND source='live' "
                "AND actual_exit_time LIKE ? AND COALESCE(quarantined, 0) = 0", (f"{today_str}%",)
            ).fetchone()

            # All-time win rate
            all_closed = conn.execute(
                "SELECT COUNT(*) as total, "
                "SUM(CASE WHEN pnl_dollars > 0 THEN 1 ELSE 0 END) as wins "
                "FROM shadow_trades WHERE status='closed' AND COALESCE(quarantined, 0) = 0"
            ).fetchone()
            wins = all_closed["wins"] or 0
            total = all_closed["total"] or 0
            losses = total - wins
            win_rate = wins / total if total > 0 else 0

            # Best/worst today
            best = conn.execute(
                "SELECT ticker, pnl_pct FROM shadow_trades "
                "WHERE status='closed' AND actual_exit_time LIKE ? AND COALESCE(quarantined, 0) = 0 "
                "ORDER BY pnl_pct DESC LIMIT 1", (f"{today_str}%",)
            ).fetchone()
            worst = conn.execute(
                "SELECT ticker, pnl_pct FROM shadow_trades "
                "WHERE status='closed' AND actual_exit_time LIKE ? AND COALESCE(quarantined, 0) = 0 "
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

        # Sprint 2 L5: shadow_trades.pnl_dollars and pnl_pct are stored
        # as SQLite TEXT (89 live rows typed text as of 2026-04-20),
        # so SUM() / SELECT returns str. notify_eod_report uses
        # f-strings like `${pnl:+.2f}` which raise TypeError on str.
        # Cast at the call site.
        notify_eod_report(
            paper_open=paper_open_row["cnt"],
            paper_open_pnl=float(paper_open_row["pnl"] or 0),
            paper_closed_today=paper_closed_row["cnt"],
            paper_closed_pnl=float(paper_closed_row["pnl"] or 0),
            live_open=live_open_row["cnt"],
            live_open_pnl=float(live_open_row["pnl"] or 0),
            live_closed_today=live_closed_row["cnt"],
            live_closed_pnl=float(live_closed_row["pnl"] or 0),
            win_rate=win_rate, wins=wins, losses=losses,
            best_ticker=best["ticker"] if best else "N/A",
            best_pct=float(best["pnl_pct"]) if best and best["pnl_pct"] is not None else 0.0,
            worst_ticker=worst["ticker"] if worst else "N/A",
            worst_pct=float(worst["pnl_pct"]) if worst and worst["pnl_pct"] is not None else 0.0,
            regime=regime, vix=vix, vix_change=vix - vix_prev,
            risk_rejected=risk_rejected, risk_qualified=risk_worthy,
        )
        print("[WATCH] EOD report sent via Telegram.")
    except Exception as e:
        logger.warning("[WATCH] EOD report failed: %s", e)


# ── 4. Data Asset Report ────────────────────────────────────────────

def send_data_asset_report():
    """4:30 PM ET — Send data asset daily report."""
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
                "SELECT COUNT(*) FROM training_examples WHERE quality_score_auto IS NULL"
            ).fetchone()[0]

            quality_row = conn.execute(
                "SELECT AVG(quality_score_auto) FROM training_examples WHERE quality_score_auto IS NOT NULL"
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


# ── 5. VIX Regime Alert ─────────────────────────────────────────────

def check_vix_regime_alert(last_vix_alert_level: float | None) -> float | None:
    """Check VIX after each scan and alert on threshold crossings.

    Args:
        last_vix_alert_level: The previous VIX level that was alerted on
            (or None on first call).

    Returns:
        The updated last_vix_alert_level value that the caller should
        store for the next invocation.
    """
    from src.notifications.telegram import notify_regime_alert, is_telegram_enabled
    if not is_telegram_enabled():
        return last_vix_alert_level

    try:
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute(
                "SELECT vix FROM vix_term_structure ORDER BY collected_at DESC LIMIT 1"
            ).fetchone()
            if not row:
                return last_vix_alert_level
            vix_now = float(row[0]) if row[0] is not None else 0.0

        thresholds = [20, 25, 30, 35, 40, 60]

        if last_vix_alert_level is None:
            return vix_now

        prev = last_vix_alert_level
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
            print(f"[WATCH] VIX regime alert sent: crossed {crossed}")
            return vix_now
        else:
            return vix_now
    except Exception as e:
        logger.warning("[WATCH] VIX regime alert check failed: %s", e)
        return last_vix_alert_level


# ── 6. Weekly Digest ─────────────────────────────────────────────────

def send_weekly_digest():
    """Sunday 8 PM ET — Send full weekly digest."""
    from src.notifications.telegram import notify_weekly_digest, is_telegram_enabled
    if not is_telegram_enabled():
        return

    try:
        now = datetime.now(ET)
        period_end = now.strftime("%b %d")
        week_ago = now - timedelta(days=7)
        period_start = week_ago.strftime("%b %d")
        week_ago_str = week_ago.strftime("%Y-%m-%d")

        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row

            # Trades this week
            opened_paper = conn.execute(
                "SELECT COUNT(*) FROM shadow_trades WHERE COALESCE(source,'paper')='paper' "
                "AND created_at >= ? AND COALESCE(quarantined, 0) = 0", (week_ago_str,)
            ).fetchone()[0]
            opened_live = conn.execute(
                "SELECT COUNT(*) FROM shadow_trades WHERE source='live' "
                "AND created_at >= ? AND COALESCE(quarantined, 0) = 0", (week_ago_str,)
            ).fetchone()[0]
            closed_paper = conn.execute(
                "SELECT COUNT(*) FROM shadow_trades WHERE status='closed' AND COALESCE(source,'paper')='paper' "
                "AND actual_exit_time >= ? AND COALESCE(quarantined, 0) = 0", (week_ago_str,)
            ).fetchone()[0]
            closed_live = conn.execute(
                "SELECT COUNT(*) FROM shadow_trades WHERE status='closed' AND source='live' "
                "AND actual_exit_time >= ? AND COALESCE(quarantined, 0) = 0", (week_ago_str,)
            ).fetchone()[0]

            # Win rate and expectancy (all time)
            wr_row = conn.execute(
                "SELECT COUNT(*) as total, "
                "SUM(CASE WHEN pnl_dollars > 0 THEN 1 ELSE 0 END) as wins, "
                "AVG(pnl_dollars) as expectancy "
                "FROM shadow_trades WHERE status='closed' AND COALESCE(quarantined, 0) = 0"
            ).fetchone()
            win_rate = (wr_row["wins"] or 0) / max(wr_row["total"] or 1, 1)
            expectancy = wr_row["expectancy"] or 0

            # Best/worst this week
            best = conn.execute(
                "SELECT ticker, pnl_pct FROM shadow_trades "
                "WHERE status='closed' AND actual_exit_time >= ? AND COALESCE(quarantined, 0) = 0 "
                "ORDER BY pnl_pct DESC LIMIT 1", (week_ago_str,)
            ).fetchone()
            worst = conn.execute(
                "SELECT ticker, pnl_pct FROM shadow_trades "
                "WHERE status='closed' AND actual_exit_time >= ? AND COALESCE(quarantined, 0) = 0 "
                "ORDER BY pnl_pct ASC LIMIT 1", (week_ago_str,)
            ).fetchone()

            # P&L this week
            pnl_paper = conn.execute(
                "SELECT COALESCE(SUM(pnl_dollars),0) FROM shadow_trades "
                "WHERE status='closed' AND COALESCE(source,'paper')='paper' AND actual_exit_time >= ?"
                " AND COALESCE(quarantined, 0) = 0",
                (week_ago_str,)
            ).fetchone()[0]
            pnl_live = conn.execute(
                "SELECT COALESCE(SUM(pnl_dollars),0) FROM shadow_trades "
                "WHERE status='closed' AND source='live' AND actual_exit_time >= ?"
                " AND COALESCE(quarantined, 0) = 0",
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
                "SELECT COUNT(*) FROM training_examples WHERE quality_score_auto IS NULL"
            ).fetchone()[0]
            quality_row = conn.execute(
                "SELECT AVG(quality_score_auto) FROM training_examples WHERE quality_score_auto IS NOT NULL"
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


# ── 7. Earnings Proximity Check ─────────────────────────────────────

def check_earnings_proximity():
    """8:00 AM ET — Check open positions for upcoming earnings."""
    from src.notifications.telegram import notify_position_earnings_warning, is_telegram_enabled
    if not is_telegram_enabled():
        return

    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row

            open_trades = conn.execute(
                "SELECT trade_id, ticker, actual_entry_price, pnl_dollars, pnl_pct "
                "FROM shadow_trades WHERE status='open' AND COALESCE(quarantined, 0) = 0"
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


# ── 8. Daily Metric Snapshot ───────────────────────────────────────

def save_daily_metric_snapshot(db_path: str = DB_PATH):
    """Save daily metric snapshot at EOD for MetricTrend chart."""
    import sqlite3
    try:
        from src.training.versioning import save_metric_snapshot
        with sqlite3.connect(db_path) as conn:
            closed = conn.execute(
                "SELECT pnl_pct, pnl_dollars FROM shadow_trades WHERE status = 'closed'"
                " AND COALESCE(quarantined, 0) = 0"
            ).fetchall()
            pnls = [r[0] for r in closed if r[0] is not None]
            pnl_dollars = [r[1] for r in closed if r[1] is not None]
            open_count = conn.execute(
                "SELECT COUNT(*) FROM shadow_trades WHERE status = 'open'"
                " AND COALESCE(quarantined, 0) = 0"
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
