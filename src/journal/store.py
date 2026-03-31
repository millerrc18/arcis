"""SQLite journal storage for recommendations and shadow trades.

Called by: api.app, api.routes.packets, api.routes.shadow, api.routes.system, cli.commands, evaluation.cto_report, evaluation.feature_importance, evaluation.scorecard, main, packets.eod_recap, risk.governor, scheduler.watch, services.recap_service, services.review_service, services.scan_service, services.shadow_service, shadow_trading.executor, shadow_trading.reconcile, training.versioning
Calls: models
Owns tables: recommendations, shadow_trades, validation_results
Config keys: none
Tests: tests/test_change_detector.py, tests/test_digest_builder.py, tests/test_gate_evaluator.py, tests/test_live_trading.py, tests/test_reconcile.py, tests/test_review.py, tests/test_scorecard.py
"""

import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from src.models import TradePacket


SCHEMA = """
CREATE TABLE IF NOT EXISTS recommendations (
    recommendation_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    ticker TEXT NOT NULL,
    company_name TEXT,
    mode TEXT,
    setup_type TEXT,
    priority_score REAL,
    confidence_score REAL,
    packet_type TEXT,
    price_at_recommendation REAL,
    market_regime TEXT,
    sector_context TEXT,
    trend_state TEXT,
    relative_strength_state TEXT,
    pullback_depth_pct REAL,
    atr REAL,
    volume_state TEXT,
    recommendation TEXT,
    thesis_text TEXT,
    entry_zone TEXT,
    stop_level TEXT,
    target_1 TEXT,
    target_2 TEXT,
    expected_hold_period TEXT,
    position_size_dollars REAL,
    position_size_pct REAL,
    estimated_dollar_risk REAL,
    reasons_to_trade TEXT,
    reasons_to_pass TEXT,
    earnings_date TEXT,
    event_risk_flag TEXT,
    hold_window_overlaps_earnings INTEGER,
    event_risk_warning_text TEXT,
    conservative_sizing_applied INTEGER,
    packet_sent INTEGER,
    packet_sent_at TEXT,
    ryan_approved INTEGER,
    ryan_executed INTEGER,
    ryan_notes TEXT,
    shadow_entry_price REAL,
    shadow_entry_time TEXT,
    shadow_exit_price REAL,
    shadow_exit_time TEXT,
    shadow_pnl_dollars REAL,
    shadow_pnl_pct REAL,
    max_favorable_excursion REAL,
    max_adverse_excursion REAL,
    shadow_duration_days REAL,
    thesis_success INTEGER,
    assistant_postmortem TEXT,
    lesson_tag TEXT,
    user_grade TEXT,
    repeatable_setup INTEGER
);

CREATE TABLE IF NOT EXISTS shadow_trades (
    trade_id TEXT PRIMARY KEY,
    recommendation_id TEXT,
    ticker TEXT NOT NULL,
    direction TEXT DEFAULT 'long',
    status TEXT DEFAULT 'pending',
    entry_price REAL,
    stop_price REAL,
    target_1 REAL,
    target_2 REAL,
    planned_shares INTEGER,
    planned_allocation REAL,
    actual_entry_price REAL,
    actual_entry_time TEXT,
    actual_exit_price REAL,
    actual_exit_time TEXT,
    exit_reason TEXT,
    pnl_dollars REAL,
    pnl_pct REAL,
    max_favorable_excursion REAL,
    max_adverse_excursion REAL,
    duration_days INTEGER,
    earnings_adjacent INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    alpaca_order_id TEXT,
    order_type TEXT,
    timeout_days INTEGER DEFAULT 15,
    source TEXT DEFAULT 'paper',
    setup_type TEXT,
    setup_confidence REAL,
    signal_entry_price REAL,
    fill_entry_price REAL,
    entry_slippage_bps REAL,
    signal_exit_price REAL,
    fill_exit_price REAL,
    exit_slippage_bps REAL
);

-- Indexes for frequently queried columns
CREATE INDEX IF NOT EXISTS idx_recommendations_ticker ON recommendations(ticker);
CREATE INDEX IF NOT EXISTS idx_recommendations_created_at ON recommendations(created_at);
CREATE INDEX IF NOT EXISTS idx_shadow_trades_status ON shadow_trades(status);
CREATE INDEX IF NOT EXISTS idx_shadow_trades_ticker ON shadow_trades(ticker);
CREATE INDEX IF NOT EXISTS idx_shadow_trades_recommendation_id ON shadow_trades(recommendation_id);
CREATE INDEX IF NOT EXISTS idx_shadow_trades_created_at ON shadow_trades(created_at);
CREATE INDEX IF NOT EXISTS idx_shadow_trades_status_exit ON shadow_trades(status, actual_exit_time);
"""


def initialize_database(db_path: str = "ai_research_desk.sqlite3") -> None:
    path = Path(db_path)
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()
        # Migration: add model_version column if missing
        try:
            conn.execute("ALTER TABLE recommendations ADD COLUMN model_version TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # Column already exists

        # Migration: add order_type column to shadow_trades if missing
        try:
            conn.execute("ALTER TABLE shadow_trades ADD COLUMN order_type TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # Column already exists

        # Migration: add enriched_prompt column to recommendations if missing
        try:
            conn.execute("ALTER TABLE recommendations ADD COLUMN enriched_prompt TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # Column already exists

        # Migration: add llm_conviction columns
        try:
            conn.execute("ALTER TABLE recommendations ADD COLUMN llm_conviction INTEGER")
            conn.commit()
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE recommendations ADD COLUMN llm_conviction_reason TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass

        # Migration: add source column to shadow_trades for paper/live tracking
        try:
            conn.execute("ALTER TABLE shadow_trades ADD COLUMN source TEXT DEFAULT 'paper'")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # Column already exists

        # Validation results table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS validation_results (
                result_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                overall_status TEXT NOT NULL,
                checks_passed INTEGER NOT NULL,
                checks_failed INTEGER NOT NULL,
                checks_warning INTEGER NOT NULL,
                results_json TEXT NOT NULL
            )
        """)
        conn.commit()

        # Implementation Shortfall columns
        for _alter in [
            "ALTER TABLE shadow_trades ADD COLUMN signal_price REAL",
            "ALTER TABLE shadow_trades ADD COLUMN implementation_shortfall_bps REAL",
        ]:
            try:
                conn.execute(_alter)
            except sqlite3.OperationalError:
                pass  # Column already exists


def log_recommendation(
    packet: TradePacket,
    features: dict,
    score: float,
    qualification: str,
    db_path: str = "ai_research_desk.sqlite3",
    model_version: str = "base",
    enriched_prompt: str | None = None,
    llm_conviction: int | None = None,
    llm_conviction_reason: str | None = None,
) -> str:
    """Write a recommendation row to the journal and return the recommendation_id."""
    initialize_database(db_path)

    rec_id = str(uuid.uuid4())
    et = ZoneInfo("America/New_York")
    created_at = datetime.now(et).isoformat()

    # Parse targets into target_1 and target_2
    targets_parts = packet.targets.split("/")
    target_1 = targets_parts[0].strip() if len(targets_parts) >= 1 else None
    target_2 = targets_parts[1].strip() if len(targets_parts) >= 2 else None

    # Volume state description
    vol_ratio = features.get("volume_ratio_20d", None)
    if vol_ratio is not None:
        if vol_ratio < 0.8:
            volume_state = "contracting"
        elif vol_ratio > 1.2:
            volume_state = "expanding"
        else:
            volume_state = "normal"
    else:
        volume_state = None

    row = {
        "recommendation_id": rec_id,
        "created_at": created_at,
        "ticker": packet.ticker,
        "company_name": packet.company_name,
        "mode": "short_swing",
        "setup_type": packet.setup_type,
        "priority_score": score,
        "confidence_score": float(packet.confidence),
        "packet_type": "action_packet",
        "price_at_recommendation": features.get("current_price"),
        "trend_state": features.get("trend_state"),
        "relative_strength_state": features.get("relative_strength_state"),
        "pullback_depth_pct": features.get("pullback_depth_pct"),
        "atr": features.get("atr_14"),
        "volume_state": volume_state,
        "recommendation": packet.recommendation,
        "thesis_text": packet.deeper_analysis,
        "entry_zone": packet.entry_zone,
        "stop_level": packet.stop_invalidation,
        "target_1": target_1,
        "target_2": target_2,
        "expected_hold_period": packet.expected_hold_period,
        "position_size_dollars": packet.position_sizing.allocation_dollars,
        "position_size_pct": packet.position_sizing.allocation_pct,
        "estimated_dollar_risk": packet.position_sizing.estimated_risk_dollars,
        "earnings_date": features.get("earnings_date"),
        "event_risk_flag": features.get("event_risk_level", "none"),
        "hold_window_overlaps_earnings": 1 if features.get("hold_overlaps_earnings") else 0,
        "event_risk_warning_text": packet.event_risk if packet.event_risk != "Normal" else None,
        "conservative_sizing_applied": 1 if features.get("event_risk_level") in ("elevated", "imminent") else 0,
        "packet_sent": 0,
        "model_version": model_version,
        "enriched_prompt": enriched_prompt,
        "llm_conviction": llm_conviction,
        "llm_conviction_reason": llm_conviction_reason,
    }

    columns = ", ".join(row.keys())
    placeholders = ", ".join("?" for _ in row)
    values = list(row.values())

    with sqlite3.connect(db_path) as conn:
        conn.execute(f"INSERT INTO recommendations ({columns}) VALUES ({placeholders})", values)
        conn.commit()

    return rec_id


def get_todays_recommendations(db_path: str = "ai_research_desk.sqlite3") -> list[dict]:
    """Query recommendations created today (ET timezone)."""
    initialize_database(db_path)

    et = ZoneInfo("America/New_York")
    today_str = datetime.now(et).strftime("%Y-%m-%d")

    fields = [
        "recommendation_id", "ticker", "company_name", "recommendation",
        "entry_zone", "stop_level", "target_1", "target_2",
        "confidence_score", "priority_score",
    ]
    columns_sql = ", ".join(fields)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"SELECT {columns_sql} FROM recommendations WHERE created_at LIKE ?",
            (f"{today_str}%",),
        ).fetchall()

    return [dict(row) for row in rows]


# ── Shadow trade CRUD ─────────────────────────────────────────────────


def insert_shadow_trade(trade: dict, db_path: str = "ai_research_desk.sqlite3") -> str:
    """Insert a shadow trade record and return the trade_id."""
    initialize_database(db_path)
    trade_id = trade.get("trade_id", str(uuid.uuid4()))
    trade["trade_id"] = trade_id

    columns = ", ".join(trade.keys())
    placeholders = ", ".join("?" for _ in trade)
    values = list(trade.values())

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            f"INSERT INTO shadow_trades ({columns}) VALUES ({placeholders})", values
        )
        conn.commit()
    return trade_id


def update_shadow_trade(
    trade_id: str, updates: dict, db_path: str = "ai_research_desk.sqlite3"
) -> None:
    """Update fields on an existing shadow trade."""
    if not updates:
        return
    et = ZoneInfo("America/New_York")
    updates["updated_at"] = datetime.now(et).isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [trade_id]

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            f"UPDATE shadow_trades SET {set_clause} WHERE trade_id = ?", values
        )
        conn.commit()


def get_open_shadow_trades(db_path: str = "ai_research_desk.sqlite3") -> list[dict]:
    """Return all broker-open shadow trades, including pending exits."""
    initialize_database(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM shadow_trades WHERE status IN ('open', 'exit_pending') "
            "ORDER BY created_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def get_shadow_trade(
    trade_id: str, db_path: str = "ai_research_desk.sqlite3"
) -> dict | None:
    """Return a single shadow trade by ID, or None."""
    initialize_database(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM shadow_trades WHERE trade_id = ?", (trade_id,)
        ).fetchone()
    return dict(row) if row else None


def get_closed_shadow_trades(
    days: int = 30, db_path: str = "ai_research_desk.sqlite3"
) -> list[dict]:
    """Return closed shadow trades from the last N days."""
    initialize_database(db_path)
    et = ZoneInfo("America/New_York")
    cutoff = (datetime.now(et) - timedelta(days=days)).isoformat()

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM shadow_trades WHERE status = 'closed' AND actual_exit_time >= ? ORDER BY actual_exit_time DESC",
            (cutoff,),
        ).fetchall()
    return [dict(row) for row in rows]


def close_shadow_trade(
    trade_id: str,
    exit_price: float,
    exit_time: str,
    exit_reason: str,
    pnl_dollars: float,
    pnl_pct: float,
    db_path: str = "ai_research_desk.sqlite3",
) -> None:
    """Close a shadow trade with exit details."""
    update_shadow_trade(
        trade_id,
        {
            "status": "closed",
            "actual_exit_price": exit_price,
            "actual_exit_time": exit_time,
            "exit_reason": exit_reason,
            "pnl_dollars": pnl_dollars,
            "pnl_pct": pnl_pct,
        },
        db_path,
    )


def get_open_shadow_trade_for_ticker(
    ticker: str, db_path: str = "ai_research_desk.sqlite3"
) -> dict | None:
    """Return an open shadow trade for a given ticker, or None."""
    initialize_database(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM shadow_trades WHERE ticker = ? "
            "AND status IN ('pending', 'open', 'exit_pending') "
            "ORDER BY created_at DESC LIMIT 1",
            (ticker,),
        ).fetchone()
    return dict(row) if row else None


# ── Recommendation queries for review loop ────────────────────────────


def get_recommendation_by_id(
    recommendation_id: str, db_path: str = "ai_research_desk.sqlite3"
) -> dict | None:
    """Return a single recommendation by ID."""
    initialize_database(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM recommendations WHERE recommendation_id = ?",
            (recommendation_id,),
        ).fetchone()
    return dict(row) if row else None


def get_recommendations_by_ticker(
    ticker: str, limit: int = 10, db_path: str = "ai_research_desk.sqlite3"
) -> list[dict]:
    """Return recent recommendations for a ticker."""
    initialize_database(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM recommendations WHERE ticker = ? ORDER BY created_at DESC LIMIT ?",
            (ticker, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def get_recommendations_pending_review(
    db_path: str = "ai_research_desk.sqlite3",
) -> list[dict]:
    """Return recommendations where ryan_executed=1 and user_grade is null."""
    initialize_database(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM recommendations WHERE ryan_executed = 1 AND user_grade IS NULL ORDER BY created_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def update_recommendation(
    recommendation_id: str, updates: dict, db_path: str = "ai_research_desk.sqlite3"
) -> None:
    """Update fields on an existing recommendation."""
    if not updates:
        return
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [recommendation_id]

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            f"UPDATE recommendations SET {set_clause} WHERE recommendation_id = ?",
            values,
        )
        conn.commit()


def update_recommendation_review(
    recommendation_id: str, review_data: dict, db_path: str = "ai_research_desk.sqlite3"
) -> None:
    """Save review data for a recommendation."""
    update_recommendation(recommendation_id, review_data, db_path)


def get_all_shadow_trades(
    days: int = 30, db_path: str = "ai_research_desk.sqlite3"
) -> list[dict]:
    """Return all shadow trades (any status) from the last N days."""
    initialize_database(db_path)
    et = ZoneInfo("America/New_York")
    cutoff = (datetime.now(et) - timedelta(days=days)).isoformat()

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM shadow_trades WHERE created_at >= ? ORDER BY created_at DESC",
            (cutoff,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_recommendations_in_period(
    days: int = 7, db_path: str = "ai_research_desk.sqlite3"
) -> list[dict]:
    """Return all recommendations from the last N days."""
    initialize_database(db_path)
    et = ZoneInfo("America/New_York")
    cutoff = (datetime.now(et) - timedelta(days=days)).isoformat()

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM recommendations WHERE created_at >= ? ORDER BY created_at DESC",
            (cutoff,),
        ).fetchall()
    return [dict(row) for row in rows]
