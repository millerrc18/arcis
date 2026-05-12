"""Council agent data gathering from repo-native tables.

Called by: council/agents.py
Calls: evaluation/hshs_live.py
Owns tables: none
Config keys: none
Tests: none
"""

import logging
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.config import DB_PATH
from src.council.errors import CouncilAgentDataError
from src.utils.db import connect_db
from src.shadow_trading.exit_reason import outcome_stats_filter_sql

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


def _query_db(query: str, params: tuple = (), db_path: str = DB_PATH) -> list[dict]:
    """Execute a read query and return rows as list of dicts."""
    with connect_db(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


def _days_since(entry_time, now: datetime) -> int:
    """Return integer days elapsed between `entry_time` and `now`.

    Cross-engine days-held arithmetic for shadow_trades.actual_entry_time
    (Sprint 5 §J5/§J6 Phase 2 T2.9 — replaces SQLite-only julianday()).

    Accepts both an ISO-8601 string (SQLite TEXT column) and a datetime
    instance (psycopg2 may surface TIMESTAMP as datetime). Naive entry
    times are coerced to the ET tz so subtraction with the ET-aware `now`
    succeeds. Returns 0 on None / parse failure rather than raising —
    the caller's f-string would have rendered `0d` for SQL NULL anyway
    (`position['days'] or 0`).
    """
    if entry_time is None:
        return 0
    if isinstance(entry_time, datetime):
        parsed = entry_time
    else:
        try:
            parsed = datetime.fromisoformat(str(entry_time))
        except (TypeError, ValueError):
            return 0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ET)
    return (now - parsed).days


def gather_tactical_data(db_path: str = DB_PATH) -> str:
    """Gather market microstructure and short-term data for Tactical Operator."""
    parts = []
    try:
        with connect_db(db_path) as conn:
            conn.row_factory = sqlite3.Row

            try:
                vix = conn.execute(
                    "SELECT vix, vix9d, vix3m FROM vix_term_structure "
                    "ORDER BY collected_date DESC LIMIT 1"
                ).fetchone()
                if vix:
                    parts.append(
                        f"VIX: {vix['vix']:.1f} | VIX9D: {vix['vix9d']:.1f} | VIX3M: {vix['vix3m']:.1f}"
                    )
                    if vix["vix"] and vix["vix3m"]:
                        structure = (
                            "contango (complacency)"
                            if vix["vix"] < vix["vix3m"]
                            else "backwardation (fear)"
                        )
                        parts.append(f"Term structure: {structure}")
            except sqlite3.Error as exc:
                logger.debug("[COUNCIL] Tactical VIX query: %s", exc)

            try:
                tl = conn.execute(
                    "SELECT current_regime, last_total_score FROM traffic_light_state WHERE id = 1"
                ).fetchone()
                if tl:
                    parts.append(
                        f"Traffic Light: {tl['current_regime']} (score {tl['last_total_score']}/6)"
                    )
            except sqlite3.Error:
                pass

            try:
                scans = conn.execute(
                    "SELECT scan_time, packet_worthy, llm_success, llm_total, avg_conviction "
                    "FROM scan_metrics ORDER BY created_at DESC LIMIT 5"
                ).fetchall()
                if scans:
                    parts.append("\nRecent scans:")
                    for scan in scans:
                        fallback = ""
                        if scan["llm_total"] and scan["llm_total"] > 0:
                            fallback = (
                                f" fallback={((scan['llm_total'] - (scan['llm_success'] or 0)) / scan['llm_total'] * 100):.0f}%"
                            )
                        parts.append(
                            f"  {scan['scan_time']}: {scan['packet_worthy']} packets, "
                            f"conv {scan['avg_conviction']:.1f}{fallback}"
                        )
            except sqlite3.Error as exc:
                logger.debug("[COUNCIL] Tactical scan query: %s", exc)

            try:
                # Cross-engine days_held: fetch actual_entry_time as a string and
                # compute (now - entry).days in Python. SQLite's julianday() has
                # no Postgres equivalent (Sprint 5 §J5/§J6 Phase 2 T2.9).
                positions = conn.execute(
                    "SELECT st.ticker, st.pnl_pct, r.sector_context as sector, "
                    "st.actual_entry_time "
                    "FROM shadow_trades st "
                    "LEFT JOIN recommendations r ON st.recommendation_id = r.recommendation_id "
                    "WHERE st.status = 'open' AND COALESCE(st.quarantined, 0) = 0"
                    " ORDER BY st.pnl_pct DESC"
                ).fetchall()
                if positions:
                    now_local = datetime.now(ET)
                    winners = sum(1 for position in positions if float(position["pnl_pct"] or 0) > 0)
                    total_pnl = sum(float(position["pnl_pct"] or 0) for position in positions)
                    parts.append(
                        f"\nOpen positions ({len(positions)}): {winners} green, "
                        f"{len(positions) - winners} red, aggregate {total_pnl:+.1f}%"
                    )
                    for position in positions[:8]:
                        emoji = "📈" if float(position["pnl_pct"] or 0) > 0 else "📉"
                        days_held = _days_since(position["actual_entry_time"], now_local)
                        parts.append(
                            f"  {emoji} {position['ticker']} ({position['sector'] or '?'}): "
                            f"{(position['pnl_pct'] or 0):+.1f}% ({days_held}d)"
                        )
                else:
                    parts.append("\nNo open positions.")
            except sqlite3.Error as exc:
                logger.debug("[COUNCIL] Tactical positions query: %s", exc)

    except CouncilAgentDataError as exc:
        logger.warning("[COUNCIL] Tactical data gather failed: %s", exc)

    return "\n".join(parts) if parts else "No tactical data available."


def gather_strategic_data(db_path: str = DB_PATH) -> str:
    """Gather portfolio strategy and phase gate data for Strategic Architect."""
    parts = []
    try:
        with connect_db(db_path) as conn:
            conn.row_factory = sqlite3.Row

            try:
                closed = conn.execute(
                    "SELECT COUNT(*) as n FROM shadow_trades WHERE status = 'closed'"
                    f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
                ).fetchone()
                total = conn.execute(
                    "SELECT COUNT(*) as n FROM shadow_trades WHERE COALESCE(quarantined, 0) = 0"
                ).fetchone()
                n_closed = closed["n"] if closed else 0
                n_open = (total["n"] if total else 0) - n_closed
                parts.append(f"Trades: {n_closed} closed, {n_open} open")
                parts.append(f"Phase 1 gate: {n_closed}/50 ({n_closed / 50 * 100:.0f}%)")
            except sqlite3.Error as exc:
                logger.debug("[COUNCIL] Strategic trade count: %s", exc)

            try:
                pnl = conn.execute(
                    "SELECT SUM(pnl_dollars) as total, AVG(pnl_pct) as avg, "
                    "COUNT(CASE WHEN pnl_dollars > 0 THEN 1 END) as wins, COUNT(*) as n "
                    "FROM shadow_trades WHERE status = 'closed' AND pnl_dollars IS NOT NULL"
                    f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
                ).fetchone()
                if pnl and pnl["n"] > 0:
                    win_rate = pnl["wins"] / pnl["n"] * 100
                    parts.append(
                        f"P&L: ${pnl['total']:.2f} total, {pnl['avg']:.2f}% avg, "
                        f"{win_rate:.0f}% WR ({pnl['wins']}/{pnl['n']})"
                    )
            except sqlite3.Error as exc:
                logger.debug("[COUNCIL] Strategic P&L: %s", exc)

            try:
                training = conn.execute(
                    "SELECT COUNT(*) as n, AVG(quality_score) as q FROM training_examples"
                ).fetchone()
                if training:
                    quality = (
                        f", avg quality {training['q']:.1f}"
                        if training["q"]
                        else ", no quality scores"
                    )
                    parts.append(f"\nTraining: {training['n']} examples{quality}")
            except sqlite3.Error:
                pass

            try:
                from src.evaluation.hshs_live import compute_hshs

                hshs = compute_hshs(db_path)
                parts.append(f"HSHS: {hshs.get('hshs', 0):.1f}/100 (phase: {hshs.get('phase', '?')})")
                for dimension, value in hshs.get("dimensions", {}).items():
                    parts.append(f"  {dimension}: {value:.0f}")
            except (CouncilAgentDataError, ImportError, AttributeError, sqlite3.Error):
                pass

            try:
                versions = conn.execute("SELECT COUNT(*) as n FROM model_versions").fetchone()
                if versions:
                    parts.append(f"Model versions trained: {versions['n']}")
            except sqlite3.Error:
                pass

    except CouncilAgentDataError as exc:
        logger.warning("[COUNCIL] Strategic data gather failed: %s", exc)

    return "\n".join(parts) if parts else "No strategic data available."


def gather_risk_data(db_path: str = DB_PATH) -> str:
    """Gather risk and concentration data for Red Team."""
    parts = []
    try:
        with connect_db(db_path) as conn:
            conn.row_factory = sqlite3.Row

            try:
                sectors = conn.execute(
                    "SELECT r.sector_context as sector, COUNT(*) as n, SUM(st.planned_allocation) as alloc "
                    "FROM shadow_trades st "
                    "LEFT JOIN recommendations r ON st.recommendation_id = r.recommendation_id "
                    "WHERE st.status = 'open' AND r.sector_context IS NOT NULL "
                    "AND COALESCE(st.quarantined, 0) = 0 "
                    "GROUP BY r.sector_context ORDER BY n DESC"
                ).fetchall()
                if sectors:
                    parts.append("Sector concentration (open):")
                    for sector in sectors:
                        allocation = f" (${sector['alloc']:.0f})" if sector["alloc"] else ""
                        parts.append(f"  {sector['sector']}: {sector['n']} positions{allocation}")
                else:
                    parts.append("No open positions for sector analysis.")
            except sqlite3.Error as exc:
                logger.debug("[COUNCIL] Risk sector: %s", exc)

            try:
                losses = conn.execute(
                    "SELECT ticker, pnl_pct, exit_reason, actual_exit_time "
                    "FROM shadow_trades WHERE status = 'closed' AND pnl_pct < 0 "
                    "AND COALESCE(quarantined, 0) = 0 "
                    "ORDER BY actual_exit_time DESC LIMIT 5"
                ).fetchall()
                if losses:
                    parts.append("\nRecent losses:")
                    for loss in losses:
                        parts.append(
                            f"  {loss['ticker']}: {loss['pnl_pct']:.1f}% "
                            f"({loss['exit_reason']}) {(loss['actual_exit_time'] or '')[:10]}"
                        )
            except sqlite3.Error as exc:
                logger.debug("[COUNCIL] Risk losses: %s", exc)

            try:
                # Cross-engine 7-day cutoff: compute in Python so the SQL is
                # engine-agnostic. SQLite's datetime('now') has no Postgres
                # equivalent (Sprint 5 §J5/§J6 Phase 2.5 T3 — same pattern as
                # gather_innovation_data's week_ago/month_ago precedent).
                week_ago = (datetime.now(ET) - timedelta(days=7)).isoformat()
                fallback = conn.execute(
                    "SELECT SUM(llm_success) as ok, SUM(llm_total) as total "
                    "FROM scan_metrics WHERE created_at > ?",
                    (week_ago,),
                ).fetchone()
                if fallback and fallback["total"] and fallback["total"] > 0:
                    rate = (1 - fallback["ok"] / fallback["total"]) * 100
                    status = "⚠️ ELEVATED" if rate > 20 else "✓ normal"
                    parts.append(f"\n7-day fallback rate: {rate:.1f}% ({status})")
            except sqlite3.Error:
                pass

            try:
                cumulative = conn.execute(
                    "SELECT SUM(pnl_dollars) as total FROM shadow_trades WHERE status = 'closed'"
                    f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
                ).fetchone()
                if cumulative and cumulative["total"] is not None:
                    parts.append(f"Cumulative closed P&L: ${cumulative['total']:.2f}")
            except sqlite3.Error:
                pass

            try:
                mae = conn.execute(
                    "SELECT ticker, MIN(max_adverse_excursion) as worst_mae "
                    "FROM shadow_trades WHERE status = 'closed' AND max_adverse_excursion IS NOT NULL"
                    f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
                ).fetchone()
                if mae and mae["worst_mae"] is not None:
                    parts.append(f"Worst MAE (single trade): {mae['worst_mae']:.1f}%")
            except sqlite3.Error:
                pass

    except CouncilAgentDataError as exc:
        logger.warning("[COUNCIL] Risk data gather failed: %s", exc)

    return "\n".join(parts) if parts else "No risk data available."


def gather_innovation_data(db_path: str = DB_PATH) -> str:
    """Gather ML pipeline and training data for Innovation Engine."""
    parts = []
    try:
        with connect_db(db_path) as conn:
            conn.row_factory = sqlite3.Row

            now = datetime.now(ET)
            week_ago = (now - timedelta(days=7)).isoformat()
            month_ago = (now - timedelta(days=30)).isoformat()

            try:
                total = conn.execute("SELECT COUNT(*) as n FROM training_examples").fetchone()
                new_week = conn.execute(
                    "SELECT COUNT(*) as n FROM training_examples WHERE created_at > ?",
                    (week_ago,),
                ).fetchone()
                new_month = conn.execute(
                    "SELECT COUNT(*) as n FROM training_examples WHERE created_at > ?",
                    (month_ago,),
                ).fetchone()
                parts.append(
                    f"Training data: {total['n']} total, +{new_week['n']} this week, +{new_month['n']} this month"
                )
            except sqlite3.Error:
                pass

            try:
                quality = conn.execute(
                    "SELECT AVG(quality_score) as avg, MIN(quality_score) as min, "
                    "MAX(quality_score) as max, "
                    "COUNT(CASE WHEN quality_score IS NULL OR quality_score = 0 THEN 1 END) as unscored "
                    "FROM training_examples"
                ).fetchone()
                if quality:
                    if quality["avg"]:
                        parts.append(
                            f"Quality: avg={quality['avg']:.1f}, range [{quality['min']:.0f}-{quality['max']:.0f}], "
                            f"{quality['unscored']} unscored"
                        )
                    else:
                        parts.append(f"Quality: {quality['unscored']} unscored")
            except sqlite3.Error:
                pass

            try:
                sources = conn.execute(
                    "SELECT source, COUNT(*) as n FROM training_examples "
                    "GROUP BY source ORDER BY n DESC"
                ).fetchall()
                if sources:
                    parts.append("\nSources:")
                    for source in sources:
                        parts.append(f"  {source['source'] or 'unknown'}: {source['n']}")
            except sqlite3.Error:
                pass

            try:
                stages = conn.execute(
                    "SELECT curriculum_stage, COUNT(*) as n FROM training_examples "
                    "WHERE curriculum_stage IS NOT NULL GROUP BY curriculum_stage"
                ).fetchall()
                if stages:
                    parts.append("Curriculum:")
                    for stage in stages:
                        parts.append(f"  {stage['curriculum_stage']}: {stage['n']}")
            except sqlite3.Error:
                pass

            try:
                fallback = conn.execute(
                    "SELECT DATE(created_at) as day, "
                    "CAST(SUM(llm_total - COALESCE(llm_success, 0)) AS FLOAT) / "
                    "NULLIF(SUM(llm_total), 0) * 100 as fb_pct "
                    "FROM scan_metrics WHERE llm_total > 0 "
                    "GROUP BY DATE(created_at) ORDER BY day DESC LIMIT 7"
                ).fetchall()
                if fallback:
                    parts.append("\nFallback rate (7 days):")
                    for row in fallback:
                        parts.append(f"  {row['day']}: {row['fb_pct']:.1f}%")
            except sqlite3.Error:
                pass

    except CouncilAgentDataError as exc:
        logger.warning("[COUNCIL] Innovation data gather failed: %s", exc)

    return "\n".join(parts) if parts else "No innovation data available."


def gather_macro_data(db_path: str = DB_PATH) -> str:
    """Gather macroeconomic and regime data for Macro Navigator."""
    parts = []
    try:
        with connect_db(db_path) as conn:
            conn.row_factory = sqlite3.Row

            try:
                indicators = [
                    ("DFF", "Fed Funds Rate"),
                    ("T10Y2Y", "10Y-2Y Spread"),
                    ("T10Y3M", "10Y-3M Spread"),
                    ("BAMLH0A0HYM2", "HY Spread (OAS)"),
                    ("UNRATE", "Unemployment"),
                ]
                lines = []
                for series_id, label in indicators:
                    row = conn.execute(
                        "SELECT value, collected_date FROM macro_snapshots "
                        "WHERE series_id = ? ORDER BY collected_date DESC LIMIT 1",
                        (series_id,),
                    ).fetchone()
                    if row:
                        lines.append(f"  {label}: {row['value']:.2f} ({row['collected_date']})")
                if lines:
                    parts.append("Macro indicators:")
                    parts.extend(lines)
            except sqlite3.Error as exc:
                logger.debug("[COUNCIL] Macro indicators: %s", exc)

            try:
                spread = conn.execute(
                    "SELECT value FROM macro_snapshots "
                    "WHERE series_id = 'T10Y2Y' ORDER BY collected_date DESC LIMIT 1"
                ).fetchone()
                if spread:
                    value = spread["value"]
                    if value < 0:
                        parts.append(f"\n⚠️ Yield curve INVERTED ({value:.2f}%)")
                    elif value < 0.5:
                        parts.append(f"\nYield curve flat ({value:.2f}%)")
                    else:
                        parts.append(f"\nYield curve normal ({value:.2f}%)")
            except sqlite3.Error:
                pass

            try:
                high_yield = conn.execute(
                    "SELECT value FROM macro_snapshots "
                    "WHERE series_id = 'BAMLH0A0HYM2' ORDER BY collected_date DESC LIMIT 1"
                ).fetchone()
                # Cross-engine 365-day cutoff: compute in Python so the SQL
                # is engine-agnostic (Sprint 5 §J5/§J6 Phase 2.5 T3). Uses ET
                # for consistency with the rest of agent_data; collected_date
                # is stored as ISO 'YYYY-MM-DD' so string comparison works.
                year_ago = (datetime.now(ET) - timedelta(days=365)).date().isoformat()
                average = conn.execute(
                    "SELECT AVG(value) as avg FROM macro_snapshots "
                    "WHERE series_id = 'BAMLH0A0HYM2' AND collected_date > ?",
                    (year_ago,),
                ).fetchone()
                if high_yield and average and average["avg"]:
                    z_score = (high_yield["value"] - average["avg"]) / max(0.1, abs(average["avg"] * 0.15))
                    status = "tight" if z_score < 0 else "normal" if z_score < 1 else "widening" if z_score < 2 else "STRESS"
                    parts.append(f"Credit: {status} (HY OAS z ≈ {z_score:.1f})")
            except sqlite3.Error:
                pass

            try:
                sectors = conn.execute(
                    "SELECT r.sector_context as sector, AVG(st.pnl_pct) as avg, COUNT(*) as n "
                    "FROM shadow_trades st "
                    "LEFT JOIN recommendations r ON st.recommendation_id = r.recommendation_id "
                    "WHERE st.status = 'closed' AND r.sector_context IS NOT NULL "
                    "AND COALESCE(st.quarantined, 0) = 0 "
                    "GROUP BY r.sector_context HAVING n >= 2 ORDER BY avg DESC"
                ).fetchall()
                if sectors:
                    parts.append("\nSector performance (closed trades):")
                    for sector in sectors:
                        emoji = "🟢" if sector["avg"] > 0 else "🔴"
                        parts.append(f"  {emoji} {sector['sector']}: {sector['avg']:+.1f}% ({sector['n']})")
            except sqlite3.Error:
                pass

    except CouncilAgentDataError as exc:
        logger.warning("[COUNCIL] Macro data gather failed: %s", exc)

    return "\n".join(parts) if parts else "No macro data available."
