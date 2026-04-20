"""python_plugin-kind find_candidates_for_date — Sprint B / #493.

Exercises the new python_plugin branch in src.platform.signal_eval,
plus confirms walk-forward still raises NotImplementedError through
backtest_engine.run_backtest (out-of-scope path unchanged).
"""
import sqlite3
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.platform.plugin_registry import (
    _clear_registry_for_tests,
    register_plugin,
)
from src.platform.signal_eval import find_candidates_for_date
from src.platform.strategy_plugin import Candidate, StrategyPlugin
from src.platform.strategy_spec import StrategySpec


MONDAY = datetime(2023, 11, 6)


@pytest.fixture(autouse=True)
def clean_registry():
    """Wipe plugin registry before and after each test — same pattern as
    tests/platform/test_strategy_plugin.py."""
    _clear_registry_for_tests()
    yield
    _clear_registry_for_tests()


def _bare_db(tmp_path) -> str:
    db = str(tmp_path / "test.db")
    sqlite3.connect(db).close()
    return db


def _plugin_spec(
    strategy_id: str = "pp_v1",
    plugin_ref: str | None = None,
    universe: dict | None = None,
    event_exclusion: dict | None = None,
) -> StrategySpec:
    entry: dict = {"kind": "python_plugin"}
    if plugin_ref:
        entry["plugin_ref"] = plugin_ref
    if event_exclusion:
        entry["event_exclusion"] = event_exclusion
    return StrategySpec(
        strategy_id=strategy_id,
        display_name=strategy_id.upper(),
        universe=universe or {"tickers": ["AAPL", "MSFT"]},
        entry=entry,
        exit={"kind": "mechanical", "timeout_days": 5,
              "stop": {"method": "pct", "value": 0.02},
              "target": {"method": "pct", "value": 0.03}},
        position_sizing={"method": "fixed_pct_equity", "pct": 0.15,
                         "max_concurrent": 2},
        attribution={"benchmark": "SPY_matched_window", "metrics": ["sharpe"]},
        raw={}, source="test",
    )


def _register_simple_plugin(plugin_id: str = "pp_v1"):
    """Register a plugin that returns one long Candidate per universe ticker."""
    @register_plugin
    class SimplePlugin(StrategyPlugin):
        def strategy_id(self) -> str:
            return plugin_id

        def find_candidates(self, as_of, universe, context):
            return [
                Candidate(
                    ticker=t, as_of=as_of, signal_direction="long",
                    signal_strength=0.7, metadata={"reason": "unit_test"},
                )
                for t in universe
            ]
    return SimplePlugin


# ── Dispatch ───────────────────────────────────────────────────────────────


def test_python_plugin_dispatches_to_registered_plugin(tmp_path):
    """spec.strategy_id matches a registered plugin → candidates returned."""
    _register_simple_plugin("pp_v1")
    db = _bare_db(tmp_path)
    spec = _plugin_spec(strategy_id="pp_v1")
    candidates = find_candidates_for_date(spec, db_path=db, as_of=MONDAY)
    assert {c["ticker"] for c in candidates} == {"AAPL", "MSFT"}
    for c in candidates:
        assert c["metadata"]["trigger"] == "python_plugin"
        assert c["metadata"]["signal_direction"] == "long"
        assert c["metadata"]["plugin_ref"] == "pp_v1"
        assert c["metadata"]["strategy_spec_hash"]
        assert c["metadata"]["reason"] == "unit_test"  # plugin-supplied preserved
        assert c["shares"] == 1
        assert c["price"] == 0.0
        assert c["signal_strength"] == 0.7


def test_python_plugin_honors_entry_plugin_ref_override(tmp_path):
    """entry.plugin_ref takes precedence over spec.strategy_id."""
    _register_simple_plugin("actual_plugin_id")
    db = _bare_db(tmp_path)
    spec = _plugin_spec(
        strategy_id="wrapper_id",  # no plugin registered under this id
        plugin_ref="actual_plugin_id",
    )
    candidates = find_candidates_for_date(spec, db_path=db, as_of=MONDAY)
    assert len(candidates) == 2
    assert all(c["metadata"]["plugin_ref"] == "actual_plugin_id" for c in candidates)


# ── Error paths ────────────────────────────────────────────────────────────


def test_python_plugin_missing_plugin_raises_keyerror(tmp_path):
    """No plugin registered for this strategy_id → KeyError with plugin_ref."""
    db = _bare_db(tmp_path)
    spec = _plugin_spec(strategy_id="not_registered_anywhere")
    with pytest.raises(KeyError, match="not_registered_anywhere"):
        find_candidates_for_date(spec, db_path=db, as_of=MONDAY)


def test_python_plugin_raising_bubbles_with_context(tmp_path):
    """Plugin's find_candidates raising is wrapped in RuntimeError
    with plugin_ref in the message; original is chained via __cause__."""
    @register_plugin
    class BoomPlugin(StrategyPlugin):
        def strategy_id(self) -> str:
            return "boom_v1"

        def find_candidates(self, as_of, universe, context):
            raise ValueError("internal plugin error")

    db = _bare_db(tmp_path)
    spec = _plugin_spec(strategy_id="boom_v1")
    with pytest.raises(RuntimeError, match="boom_v1") as exc_info:
        find_candidates_for_date(spec, db_path=db, as_of=MONDAY)
    assert isinstance(exc_info.value.__cause__, ValueError)
    assert "internal plugin error" in str(exc_info.value.__cause__)


def test_python_plugin_non_list_return_raises_typeerror(tmp_path):
    @register_plugin
    class BadReturnPlugin(StrategyPlugin):
        def strategy_id(self) -> str:
            return "bad_return"

        def find_candidates(self, as_of, universe, context):
            return "not a list"

    db = _bare_db(tmp_path)
    spec = _plugin_spec(strategy_id="bad_return")
    with pytest.raises(TypeError, match="must return list"):
        find_candidates_for_date(spec, db_path=db, as_of=MONDAY)


def test_python_plugin_wrong_item_type_raises_typeerror(tmp_path):
    """Plugin returns a list of dicts instead of Candidate dataclasses."""
    @register_plugin
    class DictReturnPlugin(StrategyPlugin):
        def strategy_id(self) -> str:
            return "dict_return"

        def find_candidates(self, as_of, universe, context):
            return [{"ticker": "AAPL"}]

    db = _bare_db(tmp_path)
    spec = _plugin_spec(strategy_id="dict_return")
    with pytest.raises(TypeError, match="expected Candidate"):
        find_candidates_for_date(spec, db_path=db, as_of=MONDAY)


# ── Filter-stack composition ───────────────────────────────────────────────


def test_python_plugin_dedupes_open_positions(tmp_path):
    """Candidates with tickers already open on research_<id> are skipped."""
    from src.schema.sqlite import create_all_tables
    _register_simple_plugin("pp_v1")
    db = str(tmp_path / "test.db")
    create_all_tables(db)
    conn = sqlite3.connect(db)
    conn.execute("""
        INSERT INTO shadow_trades
            (trade_id, ticker, planned_shares, entry_price, desk,
             source, status, direction, created_at, updated_at)
        VALUES ('t1', 'AAPL', 10, 100.0, 'research_pp_v1',
                'paper', 'open', 'long',
                '2023-11-04', '2023-11-04')
    """)
    conn.commit()
    conn.close()
    spec = _plugin_spec(strategy_id="pp_v1")
    candidates = find_candidates_for_date(spec, db_path=db, as_of=MONDAY)
    assert {c["ticker"] for c in candidates} == {"MSFT"}


def test_python_plugin_sector_filter_applied(tmp_path):
    """sector_filter narrows the universe BEFORE it reaches the plugin."""
    from src.universe.sectors import SECTOR_MAP

    seen_universes: list[list[str]] = []

    @register_plugin
    class InspectorPlugin(StrategyPlugin):
        def strategy_id(self) -> str:
            return "inspector"

        def find_candidates(self, as_of, universe, context):
            seen_universes.append(list(universe))
            return []

    db = _bare_db(tmp_path)
    spec = _plugin_spec(
        strategy_id="inspector",
        universe={"tickers": "sp100", "sector_filter": ["Technology"]},
    )
    find_candidates_for_date(spec, db_path=db, as_of=MONDAY)
    assert seen_universes, "plugin was not called"
    received = seen_universes[0]
    assert received, "plugin received empty universe"
    assert all(SECTOR_MAP.get(t) == "Technology" for t in received)


def test_python_plugin_event_exclusion_applied(tmp_path):
    """entry.event_exclusion short-circuits before dispatching to the plugin."""
    called = []

    @register_plugin
    class TrackedPlugin(StrategyPlugin):
        def strategy_id(self) -> str:
            return "tracked"

        def find_candidates(self, as_of, universe, context):
            called.append(True)
            return []

    db = _bare_db(tmp_path)
    spec = _plugin_spec(
        strategy_id="tracked",
        event_exclusion={"categories": ["Trade Policy"]},
    )
    with patch(
        "src.platform.signal_eval.is_excluded_event_date",
        return_value=True,
    ):
        assert find_candidates_for_date(spec, db_path=db, as_of=MONDAY) == []
    assert called == [], "plugin must not be called when event_exclusion fires"


def test_python_plugin_empty_universe_returns_empty_without_calling_plugin(tmp_path):
    """Empty universe → [] before plugin dispatch; plugin never called."""
    called = []

    @register_plugin
    class NeverCalledPlugin(StrategyPlugin):
        def strategy_id(self) -> str:
            return "never"

        def find_candidates(self, as_of, universe, context):
            called.append(True)
            return []

    db = _bare_db(tmp_path)
    spec = _plugin_spec(strategy_id="never", universe={"tickers": []})
    assert find_candidates_for_date(spec, db_path=db, as_of=MONDAY) == []
    assert called == []


# ── Regression guards ──────────────────────────────────────────────────────


def test_python_plugin_passes_correct_context_to_plugin(tmp_path):
    """Plugin receives context={'db_path', 'strategy_id'} with correct values."""
    received = {}

    @register_plugin
    class CtxPlugin(StrategyPlugin):
        def strategy_id(self) -> str:
            return "ctx"

        def find_candidates(self, as_of, universe, context):
            received.update(context)
            return []

    db = _bare_db(tmp_path)
    spec = _plugin_spec(strategy_id="ctx")
    find_candidates_for_date(spec, db_path=db, as_of=MONDAY)
    assert received.get("strategy_id") == "ctx"
    assert received.get("db_path") == db


def test_walkforward_path_still_raises_for_python_plugin():
    """Sprint B does NOT change backtest_engine. python_plugin through
    run_backtest still raises NotImplementedError — walk-forward unchanged."""
    from src.platform import backtest_engine
    import inspect
    src = inspect.getsource(backtest_engine.run_backtest)
    assert 'elif kind == "python_plugin":' in src
    assert "NotImplementedError" in src
    # And find_candidates_for_date is not called from run_backtest.
    assert "find_candidates_for_date" not in src


def test_scheduled_and_event_driven_branches_untouched(tmp_path):
    """Regression: Sprint A's scheduled path + event_driven path unchanged.
    Dispatch table: python_plugin is the third branch, not replacing the others."""
    db = _bare_db(tmp_path)
    # Scheduled spec still resolves normally.
    sched_spec = StrategySpec(
        strategy_id="sched_regression",
        display_name="S",
        universe={"tickers": ["AAPL"]},
        entry={"kind": "scheduled", "day_of_week": "Monday"},
        exit={"kind": "mechanical", "timeout_days": 5,
              "stop": {"method": "pct", "value": 0.02},
              "target": {"method": "pct", "value": 0.03}},
        position_sizing={"method": "fixed_pct_equity", "pct": 0.15},
        attribution={"benchmark": "SPY_matched_window", "metrics": []},
        raw={}, source="test",
    )
    candidates = find_candidates_for_date(sched_spec, db_path=db, as_of=MONDAY)
    assert len(candidates) == 1
    assert candidates[0]["metadata"]["trigger"] == "scheduled"
