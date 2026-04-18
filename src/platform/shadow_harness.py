"""Shadow-trading harness for research-platform strategies.

Called by: src.scheduler.watch (via Task 9's _run_platform_shadow_tick,
           which lands in the next task).
Calls: src.shadow_trading.alpaca_clients (startup verify),
       src.shadow_trading.alpaca_adapter (place/query/cancel orders),
       src.shadow_trading.reconcile (own-strategy reconcile),
       src.platform.risk.exposure_limits.check_pre_trade_limits (Sprint 3,
         wired in Task 7f).
Owns tables: shadow_trades (writes with desk='research_<strategy_id>').
Config keys: desks.{strategy_id} (transitively via alpaca_clients).
Tests: tests/platform/test_shadow_harness.py.

Per-strategy instance; one ShadowHarness per active research strategy.
Task 9's _run_platform_shadow_tick instantiates one and calls
run_one_tick(now) at the cadence declared in spec.raw['shadow_cadence_seconds'].

halt() closes this strategy's open positions only; never touches swing
or other research strategies.
"""
from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import datetime, timezone

from src.config import DB_PATH
from src.platform.strategy_spec import StrategySpec
from src.platform.risk.exposure_limits import check_pre_trade_limits
from src.shadow_trading.alpaca_adapter import (
    cancel_orders_for_ticker,
    get_account_info,
    get_order_status,
    place_bracket_order,
    place_paper_exit,
)
from src.shadow_trading.alpaca_clients import verify_accounts_distinct
from src.shadow_trading.reconcile import reconcile_paper_trades

logger = logging.getLogger(__name__)


class ShadowHarness:
    """Per-strategy live shadow-trading harness."""

    def __init__(
        self, strategy_spec: StrategySpec, db_path: str = DB_PATH,
    ) -> None:
        self.spec = strategy_spec
        self.strategy_id = strategy_spec.strategy_id
        self.desk = f"research_{self.strategy_id}"
        self.db_path = db_path
        # Startup guard — mis-configured shared-account setups fail fast
        # rather than silently interleaving trades.
        try:
            verify_accounts_distinct()
        except RuntimeError:
            logger.exception(
                "[HARNESS %s] verify_accounts_distinct failed — aborting init",
                self.strategy_id,
            )
            raise

    def run_one_tick(self, as_of: datetime) -> dict:
        """Called by watch loop at strategy's cadence.

        1. Reconcile own open positions.
        2. Find new candidates via strategy signal.
        3. For each candidate: check_pre_trade_limits (Task 7f) + place
           bracket order + write shadow_trades row.
        4. Return summary dict.
        """
        self._reconcile_open_positions()
        candidates = self._find_candidates(as_of)
        n_new = 0
        for cand in candidates:
            allowed, reason = self._is_within_hard_limits(cand)
            if not allowed:
                logger.info(
                    "[HARNESS %s] skipped %s: %s",
                    self.strategy_id, cand["ticker"], reason,
                )
                continue
            self._open_position(cand, as_of)
            n_new += 1
        return {
            "strategy_id": self.strategy_id,
            "as_of": as_of.isoformat(),
            "n_candidates": len(candidates),
            "n_new_positions": n_new,
        }

    def get_open_positions(self) -> list[dict]:
        """Return open shadow_trades rows tagged with this strategy's desk."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT * FROM shadow_trades "
                "WHERE desk = ? AND actual_exit_time IS NULL",
                (self.desk,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def halt(self) -> list[dict]:
        """Close all open positions for THIS strategy. Returns a list of
        {trade_id, ticker} for closed positions. Does NOT touch swing
        positions or other research strategies' positions."""
        closed = []
        for pos in self.get_open_positions():
            # Cancel any outstanding bracket orders first.
            try:
                cancel_orders_for_ticker(pos["ticker"], desk=self.desk)
            except Exception as e:
                logger.warning(
                    "[HARNESS %s] cancel bracket for %s failed: %s",
                    self.strategy_id, pos["ticker"], e,
                )
            # Submit market-close via research client.
            try:
                exit_result = place_paper_exit(
                    pos["ticker"],
                    shares=int(pos.get("actual_shares") or pos.get("planned_shares") or 1),
                    desk=self.desk,
                )
                logger.info(
                    "[HARNESS %s] halt closed %s: %s",
                    self.strategy_id, pos["ticker"], exit_result,
                )
                closed.append({
                    "trade_id": pos["trade_id"],
                    "ticker": pos["ticker"],
                })
            except Exception as e:
                logger.exception(
                    "[HARNESS %s] halt failed to close %s: %s",
                    self.strategy_id, pos["ticker"], e,
                )
        return closed

    # ── internal helpers ──────────────────────────────────────────────

    def _reconcile_open_positions(self) -> None:
        """Reconcile THIS strategy's shadow_trades against the research
        Alpaca paper account."""
        try:
            reconcile_paper_trades(
                desk=self.desk, dry_run=False, db_path=self.db_path,
            )
        except Exception:
            logger.exception(
                "[HARNESS %s] reconcile failed; tick continues without recon",
                self.strategy_id,
            )

    def _poll_order_status(self, order_id: str) -> dict:
        """Fetch one order's status via the research Alpaca client."""
        return get_order_status(order_id, desk=self.desk)

    def _find_candidates(self, as_of: datetime) -> list[dict]:
        """Query the strategy spec for new candidates at `as_of`.

        MVP PLACEHOLDER (v0.24.1 follow-up issue filed at tickets time):
        full signal-eval integration requires exposing
        src.platform.signal_eval.find_candidates_for_date(spec, db_path,
        as_of) or similar — reusing the event-driven dispatch logic from
        backtest_engine._run_event_driven but for a single as_of date.
        For Sprint 4 MVP, return empty + log a warning until that
        follow-up lands. The platform is correctly inert when no strategy
        has candidate-generation wired — NOT a bug.
        """
        logger.info(
            "[HARNESS %s] _find_candidates: returning [] (MVP placeholder; "
            "full signal_eval integration in v0.24.1)",
            self.strategy_id,
        )
        return []

    def _is_within_hard_limits(
        self, candidate: dict,
    ) -> tuple[bool, str | None]:
        """Delegate to Sprint 3's check_pre_trade_limits pure function.

        Gathers open positions for this strategy's desk (enriched with
        entry_price as current_price proxy — v0.24.1 will fetch live via
        get_current_price per position), reads NAV from the research Alpaca
        account (fallback $100K if offline), calls the concentration /
        leverage / drawdown guardrails.
        """
        current_positions = self.get_open_positions()
        # Enrich positions with current_price. For MVP, use entry_price as
        # proxy (v0.24.1 follow-up: fetch live via get_current_price per
        # position).
        enriched = [
            {
                "ticker": p["ticker"],
                "shares": int(p.get("planned_shares") or p.get("actual_shares") or 0),
                "current_price": float(p.get("entry_price") or 0.0),
            }
            for p in current_positions
        ]
        # NAV for the research desk — read via get_account_info(desk=self.desk).
        # Fallback to conservative $100K on any failure (offline, no account, etc.).
        try:
            acct = get_account_info(desk=self.desk)
            nav = float(acct.get("portfolio_value") or 100_000.0)
        except Exception as e:
            logger.warning(
                "[HARNESS %s] cannot fetch research NAV; using $100K fallback: %s",
                self.strategy_id, e,
            )
            nav = 100_000.0

        return check_pre_trade_limits(
            ticker=candidate["ticker"],
            proposed_shares=int(candidate.get("shares", 0)),
            proposed_price=float(candidate.get("price", 0.0)),
            current_positions=enriched,
            current_nav=nav,
            db_path=self.db_path,
        )

    def _open_position(self, candidate: dict, as_of: datetime) -> None:
        """Place bracket order via research Alpaca client; write shadow
        trade row with desk='research_<strategy_id>'."""
        ticker = candidate["ticker"]
        entry_result = place_bracket_order(
            ticker, desk=self.desk, **candidate.get("bracket_kwargs", {}),
        )
        trade_id = str(uuid.uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """INSERT INTO shadow_trades
                   (trade_id, ticker, planned_shares, actual_shares,
                    entry_price, actual_entry_price, desk,
                    research_thesis, strategy_spec_hash,
                    actual_entry_time, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    trade_id, ticker,
                    candidate.get("shares", 1),
                    entry_result.get("shares") or candidate.get("shares", 1),
                    candidate.get("price", 0.0),
                    entry_result.get("entry_price", candidate.get("price", 0.0)),
                    self.desk,
                    candidate.get("metadata", {}).get("thesis"),
                    candidate.get("metadata", {}).get("strategy_spec_hash"),
                    now_iso,
                    now_iso,
                    now_iso,
                ),
            )
            conn.commit()
        finally:
            conn.close()
