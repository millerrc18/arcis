"""/api/platform/* endpoints for the research platform dashboard.

Called by: frontend/src/pages/StrategyResearch.jsx + PlatformStatusWidget
           (Task 12a + 12d).
Calls: src.platform.promotion (registry reads + promote/demote),
       src.platform.strategy_spec (load YAML), src.platform.backtest_engine,
       src.platform.backtest_persist.
Owns tables: reads strategy_registry, backtest_results, backtest_trades,
             strategy_promotion_events (via promotion module).
Config keys: none.
Tests: tests/platform/test_platform_api.py.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.config import DB_PATH

logger = logging.getLogger(__name__)

router = APIRouter()

# verify_auth is injected at registration time from cloud_app.py to avoid
# a circular import. The module-level name is set by _register_platform_router.
verify_auth = None


def _read_rows(sql: str, params: tuple = ()) -> list[dict]:
    """Run a read-only query against Postgres (if DATABASE_URL is set) or
    local SQLite (dev mode).

    Reason: this module is registered into cloud_app.py AND used in local
    dev. Previously it always used sqlite3 — which silently creates an
    empty DB on Render, so SELECTs failed. Gate on DATABASE_URL so the
    cloud path reads from Render Postgres.

    Placeholder convention: pass `?`-style SQL. Converted to `%s` for
    Postgres automatically. SQLs in this module do not contain literal `?`.
    """
    database_url = os.environ.get("DATABASE_URL", "")
    if database_url:
        import psycopg2
        import psycopg2.extras
        pg_sql = sql.replace("?", "%s")
        with psycopg2.connect(database_url) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(pg_sql, params)
                return [dict(r) for r in cur.fetchall()]
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _read_one(sql: str, params: tuple = ()) -> dict | None:
    rows = _read_rows(sql, params)
    return rows[0] if rows else None


# ── GET endpoints ─────────────────────────────────────────────────────

@router.get("/api/platform/strategies")
async def list_strategies() -> list[dict]:
    return _read_rows(
        """SELECT s.*,
                  b.deflated_sharpe AS last_dsr,
                  b.max_drawdown_pct AS last_max_dd,
                  b.total_trades AS last_n_trades,
                  b.created_at AS last_backtest_at
           FROM strategy_registry s
           LEFT JOIN (
               SELECT strategy_id, MAX(created_at) AS max_created
               FROM backtest_results
               GROUP BY strategy_id
           ) latest ON latest.strategy_id = s.strategy_id
           LEFT JOIN backtest_results b ON
               b.strategy_id = s.strategy_id AND b.created_at = latest.max_created
           ORDER BY s.last_status_change DESC"""
    )


@router.get("/api/platform/strategies/{strategy_id}")
async def strategy_detail(strategy_id: str) -> dict:
    row = _read_one(
        "SELECT * FROM strategy_registry WHERE strategy_id = ?",
        (strategy_id,),
    )
    if not row:
        raise HTTPException(
            status_code=404, detail=f"strategy {strategy_id!r} not found",
        )
    body = dict(row)
    try:
        from src.platform.strategy_spec import load_spec
        spec = load_spec(strategy_id)
        body["spec"] = spec.raw
    except FileNotFoundError:
        body["spec"] = None
    return body


@router.get("/api/platform/backtest-results")
async def backtest_results(
    strategy_id: str | None = Query(None),
    limit: int = Query(20, ge=1, le=500),
) -> list[dict]:
    if strategy_id:
        return _read_rows(
            """SELECT * FROM backtest_results WHERE strategy_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (strategy_id, limit),
        )
    return _read_rows(
        "SELECT * FROM backtest_results ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )


@router.get("/api/platform/backtest-trades")
async def backtest_trades(result_id: str) -> list[dict]:
    return _read_rows(
        "SELECT * FROM backtest_trades WHERE result_id = ? ORDER BY entry_date",
        (result_id,),
    )


@router.get("/api/platform/promotion-events")
async def promotion_events(
    strategy_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
) -> list[dict]:
    if strategy_id:
        return _read_rows(
            """SELECT * FROM strategy_promotion_events WHERE strategy_id = ?
               ORDER BY timestamp DESC LIMIT ?""",
            (strategy_id, limit),
        )
    return _read_rows(
        "SELECT * FROM strategy_promotion_events "
        "ORDER BY timestamp DESC LIMIT ?",
        (limit,),
    )


# ── POST endpoints ────────────────────────────────────────────────────


class BacktestKickoffReq(BaseModel):
    strategy_id: str
    start_date: str
    end_date: str


@router.post("/api/platform/backtests", status_code=status.HTTP_202_ACCEPTED)
async def trigger_backtest(req: BacktestKickoffReq) -> dict:
    from src.platform.strategy_spec import load_spec
    try:
        load_spec(req.strategy_id)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"strategy spec not found: {req.strategy_id}",
        )
    result_id = str(uuid.uuid4())
    asyncio.create_task(_run_backtest_async(req, result_id))
    return {"result_id": result_id, "status": "running"}


async def _run_backtest_async(req: BacktestKickoffReq, result_id: str) -> None:
    """Run backtest in background + persist result."""
    try:
        from src.platform.backtest_engine import BacktestConfig, run_backtest
        from src.platform.backtest_persist import persist_backtest_result
        from src.platform.strategy_spec import load_spec
        spec = load_spec(req.strategy_id)
        cfg = BacktestConfig(
            strategy=spec,
            start_date=req.start_date,
            end_date=req.end_date,
        )
        result = run_backtest(cfg)
        persist_backtest_result(
            result, db_path=DB_PATH,
            git_sha=os.environ.get("RENDER_GIT_COMMIT", "unknown"),
        )
        try:
            from src.notifications.platform_events import notify_backtest_complete
            notify_backtest_complete(
                strategy_id=req.strategy_id,
                result_id=result_id,
                passed_gate_a=(result.metrics.get("deflated_sharpe") or 0) >= 0.95,
            )
        except Exception:
            logger.exception(
                "[PLATFORM] notify_backtest_complete failed (non-fatal)",
            )
    except Exception:
        logger.exception(
            "[PLATFORM] async backtest %s failed", result_id,
        )


class PromoteReq(BaseModel):
    strategy_id: str
    target_status: str
    confirmation_token: str
    justification_note: str = Field(..., min_length=40)


@router.post("/api/platform/promotions")
async def promote_strategy(req: PromoteReq) -> dict:
    """Manual promotion. Production transitions require two-step 24h delay."""
    from src.platform.promotion import STATUSES, promote

    if req.target_status not in STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"unknown target_status: {req.target_status!r}",
        )

    if req.target_status == "production":
        stamp = _check_or_record_production_attempt(
            req.strategy_id, req.confirmation_token,
        )
        if stamp["status"] == "awaiting_delay":
            from fastapi import Response
            return Response(
                content=json.dumps({
                    "status": "awaiting_delay",
                    "delay_until": stamp["delay_until"],
                }),
                status_code=202,
                media_type="application/json",
            )

    from_row = sqlite3.connect(DB_PATH).execute(
        "SELECT current_status FROM strategy_registry WHERE strategy_id = ?",
        (req.strategy_id,),
    ).fetchone()
    from_status = from_row[0] if from_row else "unknown"

    try:
        promote(
            strategy_id=req.strategy_id,
            target_status=req.target_status,
            triggered_by="manual",
            justification_note=req.justification_note,
            db_path=DB_PATH,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    try:
        from src.notifications.platform_events import notify_strategy_promoted
        notify_strategy_promoted(req.strategy_id, from_status, req.target_status)
    except Exception:
        logger.exception("[PLATFORM] notify_strategy_promoted failed")
    return {"status": "promoted", "target_status": req.target_status}


def _check_or_record_production_attempt(
    strategy_id: str, confirmation_token: str,
) -> dict:
    """Enforce 24h delay between first and second production-promotion
    attempts via a marker in strategy_registry.notes (JSON blob)."""
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "SELECT notes FROM strategy_registry WHERE strategy_id = ?",
            (strategy_id,),
        ).fetchone()
        notes = json.loads(row[0]) if row and row[0] else {}
        prior = notes.get("production_attempt")
        now = datetime.now(timezone.utc)

        if prior is None or prior.get("token") != confirmation_token:
            notes["production_attempt"] = {
                "token": confirmation_token,
                "at": now.isoformat(),
            }
            conn.execute(
                "UPDATE strategy_registry SET notes = ? "
                "WHERE strategy_id = ?",
                (json.dumps(notes), strategy_id),
            )
            conn.commit()
            delay_until = (now + timedelta(hours=24)).isoformat()
            return {"status": "awaiting_delay", "delay_until": delay_until}

        prior_at = datetime.fromisoformat(prior["at"])
        if (now - prior_at) < timedelta(hours=24):
            return {
                "status": "awaiting_delay",
                "delay_until": (prior_at + timedelta(hours=24)).isoformat(),
            }

        # Delay satisfied — clear marker and proceed
        del notes["production_attempt"]
        conn.execute(
            "UPDATE strategy_registry SET notes = ? WHERE strategy_id = ?",
            (json.dumps(notes), strategy_id),
        )
        conn.commit()
        return {"status": "ready"}
    finally:
        conn.close()


class DemoteReq(BaseModel):
    strategy_id: str
    reason: str = Field(..., min_length=20)


@router.post("/api/platform/demotions")
async def demote_strategy(req: DemoteReq) -> dict:
    from src.platform.promotion import demote
    try:
        demote(
            strategy_id=req.strategy_id, reason=req.reason, db_path=DB_PATH,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    try:
        from src.notifications.platform_events import notify_strategy_demoted
        notify_strategy_demoted(req.strategy_id, req.reason)
    except Exception:
        logger.exception("[PLATFORM] notify_strategy_demoted failed")
    return {"status": "deprecated"}
