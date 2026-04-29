"""Tests for src/evaluation/subgroup_analysis.py (#81 / Sprint 1.B Wave C).

Coverage:
- Each partitioner correctly groups trades into expected buckets
- Aggregate sums across partitions equal the unpartitioned total (no trades lost)
- Empty subgroup returns trade_count=0, metrics=None
- Per-partition Sharpe matches canonical_sharpe.raw_sharpe directly
- Robust to missing fields: trades without sector → 'unknown' partition
- Traffic Light takes precedence over regime_label when both present

Test fixtures use simple synthetic trade dicts; no actual backtest run.
"""
from __future__ import annotations

import pytest

from src.evaluation.subgroup_analysis import (
    TOP_5_SECTORS,
    _compute_metrics,
    _max_drawdown_pct,
    _partition_by_llm_conviction,
    _partition_by_regime,
    _partition_by_sector,
    _partition_by_year,
    partition_by_subgroups,
)


def _t(**kwargs) -> dict:
    """Helper: build a minimal trade dict with sane defaults + overrides."""
    base = {"pnl_pct": 1.0, "date": "2024-06-15", "ticker": "AAPL"}
    base.update(kwargs)
    return base


# ── Partition by regime ──────────────────────────────────────────────────────


def test_partition_by_regime_uses_traffic_light_when_present():
    """traffic_light field takes precedence over regime field."""
    trades = [
        _t(traffic_light="GREEN", regime="BULL_LOW_VOL"),
        _t(traffic_light="GREEN", regime="BEAR_EARLY"),
        _t(traffic_light="RED", regime="BULL_LOW_VOL"),
    ]
    parts = _partition_by_regime(trades)
    assert set(parts.keys()) == {"GREEN", "RED"}
    assert len(parts["GREEN"]) == 2
    assert len(parts["RED"]) == 1


def test_partition_by_regime_falls_back_to_regime_label():
    """Without traffic_light, partition by regime_label."""
    trades = [
        _t(regime="BULL_LOW_VOL"),
        _t(regime="BULL_LOW_VOL"),
        _t(regime="CORRECTION"),
    ]
    parts = _partition_by_regime(trades)
    assert set(parts.keys()) == {"BULL_LOW_VOL", "CORRECTION"}
    assert len(parts["BULL_LOW_VOL"]) == 2


def test_partition_by_regime_unknown_when_neither_present():
    """Trade with no regime info goes to 'unknown' bucket."""
    trades = [{"pnl_pct": 1.0}]
    parts = _partition_by_regime(trades)
    assert "unknown" in parts


# ── Partition by year ────────────────────────────────────────────────────────


def test_partition_by_year_extracts_from_date():
    trades = [
        _t(date="2024-06-15"),
        _t(date="2024-12-31"),
        _t(date="2025-01-01"),
        _t(date="2026-04-01"),
    ]
    parts = _partition_by_year(trades)
    assert set(parts.keys()) == {2024, 2025, 2026}
    assert len(parts[2024]) == 2


def test_partition_by_year_falls_back_to_actual_exit_time():
    trades = [
        {"pnl_pct": 1.0, "actual_exit_time": "2025-03-15T10:00:00"},
    ]
    parts = _partition_by_year(trades)
    assert 2025 in parts


def test_partition_by_year_unknown_for_bad_date():
    trades = [{"pnl_pct": 1.0, "date": "not-a-date"}]
    parts = _partition_by_year(trades)
    assert -1 in parts


# ── Partition by sector ──────────────────────────────────────────────────────


def test_partition_by_sector_top_5_separate():
    trades = [_t(sector=s) for s in TOP_5_SECTORS]
    parts = _partition_by_sector(trades)
    for s in TOP_5_SECTORS:
        assert s in parts
        assert len(parts[s]) == 1


def test_partition_by_sector_others_bucketed():
    trades = [
        _t(sector="Energy"),
        _t(sector="Industrials"),
        _t(sector="Real Estate"),
    ]
    parts = _partition_by_sector(trades)
    assert "Other" in parts
    assert len(parts["Other"]) == 3


def test_partition_by_sector_missing_under_unknown():
    trades = [{"pnl_pct": 1.0}, {"pnl_pct": 1.0, "sector": ""}]
    parts = _partition_by_sector(trades)
    assert parts["unknown"] == trades


# ── Partition by LLM conviction ──────────────────────────────────────────────


def test_partition_by_llm_conviction_three_tiers():
    trades = [
        _t(llm_conviction="low"),
        _t(llm_conviction="medium"),
        _t(llm_conviction="high"),
        _t(llm_conviction="medium"),
    ]
    parts = _partition_by_llm_conviction(trades)
    assert set(parts.keys()) == {"low", "medium", "high"}
    assert len(parts["medium"]) == 2


def test_partition_by_llm_conviction_unknown_for_missing_or_invalid():
    trades = [
        _t(),  # missing
        _t(llm_conviction="extremely_high"),  # not in spec
    ]
    parts = _partition_by_llm_conviction(trades)
    assert "unknown" in parts
    assert len(parts["unknown"]) == 2


# ── Per-partition metrics ───────────────────────────────────────────────────


def test_compute_metrics_basic():
    trades = [_t(pnl_pct=1.0), _t(pnl_pct=-0.5), _t(pnl_pct=2.0)]
    m = _compute_metrics(trades)
    assert m["trade_count"] == 3
    assert m["mean_return"] == pytest.approx((1.0 - 0.5 + 2.0) / 3, rel=1e-3)
    assert m["win_rate"] == pytest.approx(2 / 3, rel=1e-3)
    assert m["sharpe"] is not None
    assert m["max_drawdown_pct"] is not None


def test_compute_metrics_empty_partition():
    m = _compute_metrics([])
    assert m["trade_count"] == 0
    assert m["mean_return"] is None
    assert m["win_rate"] is None
    assert m["sharpe"] is None
    assert m["max_drawdown_pct"] is None


def test_compute_metrics_single_trade_sharpe_is_none():
    """Sharpe undefined for n<2; should return None not raise."""
    m = _compute_metrics([_t(pnl_pct=1.0)])
    assert m["trade_count"] == 1
    assert m["sharpe"] is None


def test_compute_metrics_sharpe_matches_canonical():
    """Per-partition sharpe must match canonical raw_sharpe directly."""
    from src.analytics.canonical_sharpe import raw_sharpe

    pnls = [1.5, -0.5, 2.0, -1.0, 1.0, 0.5]
    trades = [_t(pnl_pct=p) for p in pnls]
    m = _compute_metrics(trades)
    expected = raw_sharpe([p / 100.0 for p in pnls])
    assert m["sharpe"] == pytest.approx(expected, rel=1e-4)


def test_max_drawdown_monotone_increasing():
    """No drawdown when all PnLs are positive."""
    assert _max_drawdown_pct([1.0, 2.0, 0.5]) == 0.0


def test_max_drawdown_after_loss():
    """Drawdown exists after a losing trade."""
    dd = _max_drawdown_pct([5.0, -10.0, 1.0])
    assert dd is not None
    assert dd > 0


# ── Top-level partition_by_subgroups ─────────────────────────────────────────


def _walkforward_fixture() -> dict:
    """Synthetic walkforward result with trades across all four subgroups."""
    return {
        "folds": [
            {
                "trades": [
                    _t(pnl_pct=2.0, traffic_light="GREEN", date="2024-06-15",
                       sector="Technology", llm_conviction="high"),
                    _t(pnl_pct=-1.0, traffic_light="GREEN", date="2024-12-15",
                       sector="Technology", llm_conviction="high"),
                ],
            },
            {
                "trades": [
                    _t(pnl_pct=1.5, traffic_light="YELLOW", date="2025-03-15",
                       sector="Health Care", llm_conviction="medium"),
                    _t(pnl_pct=-0.5, traffic_light="RED", date="2026-01-15",
                       sector="Energy", llm_conviction="low"),
                ],
            },
        ],
    }


def test_partition_by_subgroups_returns_all_four_subgroups():
    result = partition_by_subgroups(_walkforward_fixture())
    assert set(result.keys()) == {"regime", "year", "sector", "llm_conviction"}


def test_partition_by_subgroups_aggregate_count_matches_input():
    """Sum of trade_count across partitions of any subgroup = total trades."""
    fixture = _walkforward_fixture()
    total = sum(len(f["trades"]) for f in fixture["folds"])
    result = partition_by_subgroups(fixture)
    for subgroup_name, partitions in result.items():
        partition_total = sum(p["trade_count"] for p in partitions.values())
        assert partition_total == total, (
            f"Subgroup '{subgroup_name}' lost trades: "
            f"input={total}, partition_total={partition_total}"
        )


def test_partition_by_subgroups_regime_uses_traffic_light():
    result = partition_by_subgroups(_walkforward_fixture())
    assert set(result["regime"].keys()) == {"GREEN", "YELLOW", "RED"}
    assert result["regime"]["GREEN"]["trade_count"] == 2


def test_partition_by_subgroups_sector_top_5_plus_other():
    result = partition_by_subgroups(_walkforward_fixture())
    # Energy is not in top 5 → goes to "Other"
    assert "Other" in result["sector"]
    assert result["sector"]["Other"]["trade_count"] == 1
    assert result["sector"]["Technology"]["trade_count"] == 2


def test_partition_by_subgroups_empty_walkforward_result():
    """No folds = no trades = empty subgroup partitions."""
    result = partition_by_subgroups({"folds": []})
    for subgroup_partitions in result.values():
        assert subgroup_partitions == {}


def test_partition_by_subgroups_handles_missing_trades_key():
    """Fold without 'trades' key (defensive — should treat as empty)."""
    result = partition_by_subgroups({"folds": [{"fold_idx": 0}, {"trades": []}]})
    for subgroup_partitions in result.values():
        assert subgroup_partitions == {}


def test_partition_by_subgroups_missing_sector_under_unknown():
    """Trades without sector field still get partitioned (under 'unknown')."""
    fixture = {"folds": [{"trades": [_t(pnl_pct=1.0)]}]}
    result = partition_by_subgroups(fixture)
    assert "unknown" in result["sector"]
    assert result["sector"]["unknown"]["trade_count"] == 1
