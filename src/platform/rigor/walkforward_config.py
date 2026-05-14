"""Walk-forward validation config + default windows (R1).

Called by: src.platform.rigor.walkforward_runner (Sprint walkforward-v1).
Calls: none.
Owns tables: none.
Config keys: none.
Tests: tests/platform/rigor/test_walkforward_config.py.

Separate module so the runner stays under the 400-line ceiling and so the
config can be imported by the CLI and by tests without pulling in the
runner's heavier dependencies.

R1 canonical windows — five non-overlapping 2019-01-01 → 2024-09-30 OOS
windows, each with a two-calendar-year IS flank, as documented in
docs/sprints/SPRINT_walkforward_validation_v1.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Sequence

from src.scheduler.holidays import subtract_trading_days


SHARPE_MIN_PER_WINDOW = 0.3
MDE_MAX_PER_WINDOW = 0.3
POOLED_SHARPE_MIN = 0.5
MAX_DRAWDOWN_CAP_PCT = 0.20
MIN_TRADES_PER_WINDOW = 10
MIN_VIX_TIERS_REPRESENTED = 2
# v0.25.4 (#538): below this many days, OOS test span is too short to
# carry meaningful seasonal coverage. 365 = 1 calendar year. The
# canonical 15-month windows clear this comfortably (~456 days); a
# truncated tail-window like v0.25.3's 273-day Window 4 trips it.
MIN_WINDOW_DURATION_DAYS = 365
WINDOWS_PASSING_CRITERION_2 = 4  # ≥4 of 5
INCONCLUSIVE_WINDOW_THRESHOLD = 2  # ≥2 flips overall to INCONCLUSIVE
DEFAULT_EMBARGO_DAYS = 5
DEFAULT_PER_SIDE_COST_BPS = 0.5
DEFAULT_RANDOM_SEED = 42
DEFAULT_ALPHA = 0.05
DEFAULT_POWER = 0.80
HEAVY_TAIL_SE_RATIO = 1.5
DEFAULT_BOOTSTRAP_RESAMPLES = 10_000


@dataclass(frozen=True)
class WalkForwardWindow:
    """One IS/OOS pair. Dates are inclusive ISO yyyy-mm-dd strings."""

    train_start: str
    train_end: str
    test_start: str
    test_end: str

    def __post_init__(self) -> None:
        for attr in ("train_start", "train_end", "test_start", "test_end"):
            value = getattr(self, attr)
            if not isinstance(value, str) or len(value) != 10:
                raise ValueError(
                    f"WalkForwardWindow.{attr} must be 'YYYY-MM-DD', got {value!r}"
                )
            try:
                date.fromisoformat(value)
            except ValueError as e:
                raise ValueError(
                    f"WalkForwardWindow.{attr} not a valid ISO date: {value!r}"
                ) from e
        if self.train_end >= self.test_start:
            raise ValueError(
                f"train_end ({self.train_end}) must be strictly before "
                f"test_start ({self.test_start}) — no IS/OOS leakage"
            )
        if self.test_end < self.test_start:
            raise ValueError(
                f"test_end ({self.test_end}) must be >= test_start "
                f"({self.test_start})"
            )


# R1 default windows. Each OOS is 15 months; last is 9 months to respect
# the 2024-09-30 data cutoff. IS windows are two calendar years each.
DEFAULT_WINDOWS: tuple[WalkForwardWindow, ...] = (
    WalkForwardWindow("2017-01-01", "2018-12-31", "2019-01-01", "2020-03-31"),
    WalkForwardWindow("2018-01-01", "2019-12-31", "2020-04-01", "2021-06-30"),
    WalkForwardWindow("2019-01-01", "2020-12-31", "2021-07-01", "2022-09-30"),
    WalkForwardWindow("2020-01-01", "2021-12-31", "2022-10-01", "2023-12-31"),
    WalkForwardWindow("2021-01-01", "2022-12-31", "2024-01-01", "2024-09-30"),
)


@dataclass
class WalkForwardConfig:
    """Full walk-forward run configuration.

    Every field has a default; an all-default config is a valid v0.25.0
    canonical run. Overrides are supported for power-testing, debugging,
    and future non-S&P 100 runs.
    """

    strategy_id: str
    windows: Sequence[WalkForwardWindow] = field(default_factory=lambda: DEFAULT_WINDOWS)
    universe_tag: str = "sp100"
    embargo_days: int = DEFAULT_EMBARGO_DAYS
    per_side_cost_bps: float = DEFAULT_PER_SIDE_COST_BPS
    random_seed: int = DEFAULT_RANDOM_SEED
    alpha: float = DEFAULT_ALPHA
    power: float = DEFAULT_POWER
    heavy_tail_se_ratio: float = HEAVY_TAIL_SE_RATIO
    bootstrap_resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES
    # Threshold tuning knobs — kept here so every criterion has ONE source
    # of truth. Override only via explicit kw for tests; production uses
    # defaults.
    sharpe_min: float = SHARPE_MIN_PER_WINDOW
    mde_max: float = MDE_MAX_PER_WINDOW
    pooled_sharpe_min: float = POOLED_SHARPE_MIN
    max_drawdown_cap_pct: float = MAX_DRAWDOWN_CAP_PCT
    min_trades_per_window: int = MIN_TRADES_PER_WINDOW
    min_vix_tiers: int = MIN_VIX_TIERS_REPRESENTED
    min_window_duration_days: int = MIN_WINDOW_DURATION_DAYS
    # SP-WF-004 (Sprint 6 Wave B T3): optional excess-Sharpe gate per window.
    # None = use raw Sharpe threshold only (no behavior change for existing callers).
    # When set, compute_window_metrics checks excess Sharpe (rf-adjusted) >= this min.
    excess_sharpe_min: float | None = None
    # SP-WF-010: when set, T8's runner delegates to the canonical filesystem
    # gate at src.evaluation.walkforward._gate_corpus_or_raise — which loads
    # data/corpus/<corpus_id>/manifest.json and verifies admissibility +
    # window coverage. When None, the gate is bypassed (backward-compat path,
    # no behavior change for existing callers).
    corpus_id: str | None = None
    # R8 defense-in-depth: forced False at the config layer. Runner asserts.
    bootcamp_override: bool = False

    def __post_init__(self) -> None:
        if not self.windows:
            raise ValueError("WalkForwardConfig.windows must have >= 1 window")
        if self.embargo_days < 0:
            raise ValueError("embargo_days must be >= 0")
        if self.per_side_cost_bps < 0:
            raise ValueError("per_side_cost_bps must be >= 0")
        if not (0 < self.alpha < 1):
            raise ValueError("alpha must be in (0, 1)")
        if not (0 < self.power < 1):
            raise ValueError("power must be in (0, 1)")
        if self.heavy_tail_se_ratio <= 1.0:
            raise ValueError(
                "heavy_tail_se_ratio must be > 1.0 (otherwise every dist is heavy)"
            )
        if self.bootcamp_override is True:
            # R8(d): bootcamp must be False during walk-forward. An operator
            # who flipped this back to True likely misunderstands the firewall.
            raise ValueError(
                "R8 violation: bootcamp_override must be False during walk-forward"
            )

    def as_json_dict(self) -> dict:
        """Serialize to a JSON-safe dict for persistence into
        walkforward_results.config_json. Preserves window list."""
        return {
            "strategy_id": self.strategy_id,
            "universe_tag": self.universe_tag,
            "embargo_days": self.embargo_days,
            "per_side_cost_bps": self.per_side_cost_bps,
            "random_seed": self.random_seed,
            "alpha": self.alpha,
            "power": self.power,
            "heavy_tail_se_ratio": self.heavy_tail_se_ratio,
            "bootstrap_resamples": self.bootstrap_resamples,
            "sharpe_min": self.sharpe_min,
            "mde_max": self.mde_max,
            "pooled_sharpe_min": self.pooled_sharpe_min,
            "max_drawdown_cap_pct": self.max_drawdown_cap_pct,
            "min_trades_per_window": self.min_trades_per_window,
            "min_vix_tiers": self.min_vix_tiers,
            "min_window_duration_days": self.min_window_duration_days,
            "excess_sharpe_min": self.excess_sharpe_min,
            "corpus_id": self.corpus_id,
            "bootcamp_override": self.bootcamp_override,
            "windows": [
                {
                    "train_start": w.train_start, "train_end": w.train_end,
                    "test_start": w.test_start, "test_end": w.test_end,
                }
                for w in self.windows
            ],
        }


def build_walkforward_windows(
    anchor: date,
    n_windows: int = 5,
    is_trading_days: int = 504,
    oos_trading_days: int = 315,
    embargo_trading_days: int = 21,
) -> list[tuple[date, date, date, date]]:
    """Generate (train_start, train_end, test_start, test_end) tuples
    matching DEFAULT_WINDOWS shape, with all arithmetic via subtract_trading_days.

    Builds n_windows non-overlapping IS/OOS pairs going backward from anchor.
    The most-recent window's test_end equals anchor; each prior window's
    test_end is set to one trading day before the next window's train_start.
    All boundary arithmetic uses subtract_trading_days from
    src.scheduler.holidays to honor NYSE holidays without calendar-day
    approximation.

    The train_end < test_start invariant (no IS/OOS leakage) is enforced by
    the embargo_trading_days gap separating train_end from test_start.

    Args:
        anchor: end date of the most-recent OOS window (inclusive).
        n_windows: number of IS/OOS pairs to generate.
        is_trading_days: length of each in-sample region in trading days (~2yr).
        oos_trading_days: length of each out-of-sample region in trading days (~15mo).
        embargo_trading_days: trading-day gap between train_end and test_start.

    Returns:
        List of (train_start, train_end, test_start, test_end) date tuples,
        ordered oldest-first (chronological).
    """
    raw: list[tuple[date, date, date, date]] = []
    current_test_end = anchor
    for _ in range(n_windows):
        test_start = subtract_trading_days(current_test_end, oos_trading_days - 1)
        train_end = subtract_trading_days(test_start, embargo_trading_days)
        train_start = subtract_trading_days(train_end, is_trading_days - 1)
        raw.append((train_start, train_end, test_start, current_test_end))
        current_test_end = subtract_trading_days(train_start, 1)
    return list(reversed(raw))
