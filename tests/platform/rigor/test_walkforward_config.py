"""Tests for WalkForwardConfig + DEFAULT_WINDOWS (R1)."""
from __future__ import annotations

import pytest

from src.platform.rigor.walkforward_config import (
    DEFAULT_WINDOWS,
    WalkForwardConfig,
    WalkForwardWindow,
)


def test_default_windows_count_is_five():
    assert len(DEFAULT_WINDOWS) == 5


def test_default_windows_cover_2019_to_2024():
    first = DEFAULT_WINDOWS[0]
    last = DEFAULT_WINDOWS[-1]
    assert first.test_start == "2019-01-01"
    assert last.test_end == "2024-09-30"


def test_default_windows_oos_non_overlapping():
    """Every OOS window must start strictly after the previous OOS ends."""
    for i in range(1, len(DEFAULT_WINDOWS)):
        prev = DEFAULT_WINDOWS[i - 1]
        curr = DEFAULT_WINDOWS[i]
        assert curr.test_start > prev.test_end, (
            f"OOS window {i} starts {curr.test_start}, overlaps window "
            f"{i - 1} that ends {prev.test_end}"
        )


def test_default_windows_is_strictly_before_oos():
    """R1 no-leakage: train_end < test_start for every window."""
    for i, w in enumerate(DEFAULT_WINDOWS):
        assert w.train_end < w.test_start, f"window {i} leaks"


def test_window_rejects_inverted_is_oos():
    with pytest.raises(ValueError, match="strictly before"):
        WalkForwardWindow("2020-01-01", "2022-12-31", "2020-06-01", "2021-01-01")


def test_window_rejects_invalid_iso():
    with pytest.raises(ValueError, match="ISO"):
        WalkForwardWindow("2020-01-01", "2020-12-31", "not-a-date", "2021-06-30")


def test_window_rejects_test_end_before_test_start():
    with pytest.raises(ValueError, match=">="):
        WalkForwardWindow("2019-01-01", "2019-12-31", "2020-06-01", "2020-01-01")


def test_config_defaults_are_valid():
    cfg = WalkForwardConfig(strategy_id="lazy_prices_v1")
    assert cfg.per_side_cost_bps == 0.5
    assert cfg.embargo_days == 5
    assert cfg.random_seed == 42
    assert cfg.bootcamp_override is False
    assert len(cfg.windows) == 5


def test_config_rejects_bootcamp_override_true():
    """R8(d): bootcamp must be False during walk-forward."""
    with pytest.raises(ValueError, match="R8"):
        WalkForwardConfig(
            strategy_id="lazy_prices_v1", bootcamp_override=True,
        )


def test_config_rejects_empty_windows():
    with pytest.raises(ValueError, match=">= 1 window"):
        WalkForwardConfig(strategy_id="x", windows=[])


def test_config_rejects_negative_embargo():
    with pytest.raises(ValueError, match=">="):
        WalkForwardConfig(strategy_id="x", embargo_days=-1)


def test_config_rejects_zero_heavy_tail_ratio():
    with pytest.raises(ValueError, match="heavy_tail"):
        WalkForwardConfig(strategy_id="x", heavy_tail_se_ratio=1.0)


def test_config_json_dict_round_trip_shape():
    cfg = WalkForwardConfig(strategy_id="lazy_prices_v1")
    d = cfg.as_json_dict()
    assert d["strategy_id"] == "lazy_prices_v1"
    assert d["bootcamp_override"] is False
    assert len(d["windows"]) == 5
    assert d["windows"][0]["test_start"] == "2019-01-01"


def test_config_custom_window_list_preserved():
    custom = [
        WalkForwardWindow("2020-01-01", "2020-12-31", "2021-01-01", "2021-06-30"),
    ]
    cfg = WalkForwardConfig(strategy_id="x", windows=custom)
    assert len(cfg.windows) == 1
    assert cfg.windows[0].test_end == "2021-06-30"


def test_config_alpha_power_bounds():
    with pytest.raises(ValueError):
        WalkForwardConfig(strategy_id="x", alpha=0.0)
    with pytest.raises(ValueError):
        WalkForwardConfig(strategy_id="x", alpha=1.0)
    with pytest.raises(ValueError):
        WalkForwardConfig(strategy_id="x", power=1.5)
