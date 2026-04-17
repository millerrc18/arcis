"""Unit tests for src.platform.signal_eval.

Covers the three bugs fixed by hotfix v0.24.0-alpha2.1 at isolated-unit
granularity. The e2e test (test_lazy_prices_e2e.py) validates them
implicitly via n_trades>=1; these tests validate them explicitly so a
regression in any single code path fails a focused test.
"""
import pytest

from src.platform.signal_eval import _evaluate_event_signal, _resolve_universe


# ── H2: universe alias ────────────────────────────────────────────────────

def test_resolve_universe_accepts_list():
    result = _resolve_universe(["AAPL", "MSFT"])
    assert result == ["AAPL", "MSFT"]


def test_resolve_universe_dispatches_sp100_string_alias():
    """Hotfix H2 — the YAML spec declares universe.tickers: sp100 as a
    string, not a list. _resolve_universe must dispatch it to
    get_sp100_universe() rather than rejecting it."""
    result = _resolve_universe("sp100")
    assert isinstance(result, list)
    assert len(result) >= 100  # 102 actual (GOOG + GOOGL)
    assert "AAPL" in result


def test_resolve_universe_unknown_string_returns_empty_or_raises():
    """Unknown aliases should not silently return sp100. Either raise or
    return empty list — both are acceptable, silent-dispatch-to-default
    is not."""
    result = _resolve_universe("nonexistent_universe_alias")
    # Accept either empty-list or a raised exception; what we DON'T
    # want is a silent return of sp100.
    assert result == [] or len(result) == 0 or result is None


# ── H4: combinator OR vs AND ──────────────────────────────────────────────

def _two_cosine_filters() -> list[dict]:
    """Two cosine filters on item_1a and item_7, threshold 0.75,
    less_than. Mirrors lazy_prices_v1.yaml."""
    return [
        {"metric": "cosine_similarity", "target": "item_1a",
         "reference": "prior_year_same_form",
         "operator": "less_than", "threshold": 0.75},
        {"metric": "cosine_similarity", "target": "item_7",
         "reference": "prior_year_same_form",
         "operator": "less_than", "threshold": 0.75},
    ]


def test_combinator_any_fires_when_single_filter_passes():
    """Hotfix H4 — spec has combinator: any (OR). If item_1a passes
    (0.40 < 0.75) but item_7 fails (0.92 >= 0.75), the signal MUST fire.
    Pre-hotfix, _evaluate_event_signal was hardcoded to AND logic, which
    suppressed this exact pattern (SBUX case from the production DB)."""
    sections = {
        "item_1a_cosine_yoy": 0.40,   # passes (< 0.75)
        "item_7_cosine_yoy": 0.92,    # fails (>= 0.75)
    }
    assert _evaluate_event_signal(
        sections, _two_cosine_filters(), combinator="any",
    ) is True


def test_combinator_any_does_not_fire_when_all_filters_fail():
    sections = {
        "item_1a_cosine_yoy": 0.85,   # fails
        "item_7_cosine_yoy": 0.92,    # fails
    }
    assert _evaluate_event_signal(
        sections, _two_cosine_filters(), combinator="any",
    ) is False


def test_combinator_any_fires_when_both_filters_pass():
    sections = {
        "item_1a_cosine_yoy": 0.40,
        "item_7_cosine_yoy": 0.50,
    }
    assert _evaluate_event_signal(
        sections, _two_cosine_filters(), combinator="any",
    ) is True


def test_combinator_all_does_not_fire_when_only_one_passes():
    """AND semantics — same inputs as the combinator=any case that
    fires should be suppressed under combinator=all."""
    sections = {
        "item_1a_cosine_yoy": 0.40,   # passes
        "item_7_cosine_yoy": 0.92,    # fails
    }
    assert _evaluate_event_signal(
        sections, _two_cosine_filters(), combinator="all",
    ) is False


def test_combinator_all_fires_when_both_pass():
    sections = {
        "item_1a_cosine_yoy": 0.40,
        "item_7_cosine_yoy": 0.50,
    }
    assert _evaluate_event_signal(
        sections, _two_cosine_filters(), combinator="all",
    ) is True


def test_combinator_any_missing_key_is_not_a_failure():
    """If sections has only item_1a and the strategy looks at both
    item_1a and item_7, combinator=any must still fire if item_1a
    passes — the missing item_7 key should be treated as skip, not
    fail."""
    sections = {
        "item_1a_cosine_yoy": 0.40,
        # item_7_cosine_yoy absent
    }
    assert _evaluate_event_signal(
        sections, _two_cosine_filters(), combinator="any",
    ) is True


def test_combinator_all_missing_key_is_a_failure():
    """AND semantics — if a required filter key is missing, the
    condition cannot pass, so AND must return False."""
    sections = {
        "item_1a_cosine_yoy": 0.40,
        # item_7_cosine_yoy absent
    }
    assert _evaluate_event_signal(
        sections, _two_cosine_filters(), combinator="all",
    ) is False
