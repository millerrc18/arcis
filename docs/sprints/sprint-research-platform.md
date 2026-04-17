# Sprint: Arcis Strategy Research Platform (v0.24.0)

**Authority:**
- Deep research: `docs/research/deep-research/research-desk-design-report.md` (Lazy Prices + ML-SUE as first strategy candidate)
- Skeptical review: `docs/research/2026-04-16-research-desk-sprint-review.md` (killed the prior MVP spec by exposing EDGAR data crisis + 11 Alpaca call sites)
- User pivot: Ryan wants a **strategy research platform**, not a second production desk. Supersedes `docs/sprints/sprint-research-desk-mvp.md` which is now archived.

**Branch:** `feat/research-platform`
**Tag on merge:** v0.24.0
**Effort:** 40-60 hours, honestly. Compressed to a single weekend.
**Priority:** Ambitious — user explicitly accepted the risk of shipping partial work.

---

## Executive Summary

Build infrastructure for **systematically proposing, backtesting, shadow-trading, and promoting strategy candidates** — not a second production desk. The platform is agnostic to the strategy it's evaluating. First strategy loaded into it will be Lazy Prices (once EDGAR data crisis is repaired), but the platform itself is strategy-independent.

Four components:

1. **Backtest harness** — deterministic historical replay of any strategy spec, with SPY-matched excess-Sharpe, regime attribution, transaction costs, and statistical significance testing
2. **Strategy specification format** — YAML for simple/declarative strategies, Python plugins for complex ones, with a common interface both fulfill
3. **Shadow-trading harness** — runs a validated strategy spec against live market data on a second Alpaca paper account, logging paper fills with full attribution
4. **Promotion pipeline** — tracks each strategy's lifecycle (proposed → backtested → shadow → live) with explicit gates at each boundary

**What the platform is not:** a general-purpose quantitative framework. It's purpose-built for Arcis's specific universe (S&P 100), timeframe (daily bars, 2-30 day holds), and infrastructure (Alpaca, SQLite, Qwen 8B). Do not generalize beyond what our actual strategies need.

---

## Honest Risk Assessment

This spec is **60-80 hours of work** compressed into a weekend. That is not going to fit. Three things will happen:

1. Some tasks will be cut. Sections marked **[CUT-CANDIDATE]** are the first to go.
2. Some tasks will be stubbed — interface created, implementation deferred. Sections marked **[STUB-OK]** can ship as interfaces without full functionality.
3. At least one task will have a bug we don't catch until next weekend. The backtest harness is the highest-risk component — a bug there invalidates every evaluation.

Explicit success criteria at three tiers:

- **Minimum Viable Product (weekend baseline, ~20h):** Backtest harness + YAML strategy spec + Lazy Prices YAML spec + first backtest result. No shadow-trading, no promotion pipeline, no LLM integration.
- **Target (stretch, ~40h):** Above + Python strategy plugin interface + shadow-trading harness skeleton + promotion pipeline database schema + one dashboard page.
- **Ambitious (full spec, ~60h):** All four components functional + LLM-assisted strategy proposal + live Lazy Prices candidate running on second Alpaca account + full dashboard integration.

I'm going to write the full spec. Ryan (and CC) will decide what survives the weekend.

---

## EDGAR Data Crisis Pre-Flight

The skeptical review confirmed **0/3,362 EDGAR filings have populated `full_text` or `sections_json`**. Any strategy depending on filing text (Lazy Prices) is dead-on-arrival.

**This is Task 0.** It must be fixed before any filing-dependent strategy can be validated. It is separated from the platform work so it can be done in parallel by CC or triaged later if time runs out.

**Task 0 — Repair EDGAR fetch pipeline (3-6h, CUT-CANDIDATE if needed)**

Run diagnostic on `src/data_collection/edgar_collector.py:_fetch_filing_text`:

```bash
python -c "
from src.data_collection.edgar_collector import _fetch_filing_text
# Pick a known recent filing and try to fetch text directly
from src.config import DB_PATH; import sqlite3
c = sqlite3.connect(DB_PATH); c.row_factory = sqlite3.Row
row = c.execute('SELECT * FROM edgar_filings WHERE form_type = \"10-K\" ORDER BY filing_date DESC LIMIT 1').fetchone()
print('Testing fetch for:', row['ticker'], row['filing_url'])
text = _fetch_filing_text(row['filing_url'])
print('Got text:', text is not None, 'length:', len(text) if text else 0)
"
```

If `None`: diagnose the failure path. Likely causes (in priority order):
1. Filing URL format changed (SEC may have moved from EdgarOnline/PDF to iXBRL-only)
2. User-Agent string rejected by SEC (they require contact info)
3. Redirect handling (SEC often 301 → 302 → final HTML)
4. Rate limit (they return 429 or 403 silently)

Fix the root cause, then backfill. Backfill approach:

```python
# scripts/backfill_edgar_fulltext.py
# Iterate all rows with full_text IS NULL, fetch, populate sections_json
# Rate limit: 3 req/sec (conservative under SEC's 10/sec)
# Expected runtime: 3362 rows / 3 = ~20 min
```

**Critical:** This is upstream of everything else. If Task 0 fails, the Lazy Prices strategy can't be validated; it gets loaded into the platform but returns 0 candidates and flags `insufficient_filing_data`.

---

## Reusable Infrastructure (Pass 2 + 3 audit — DO NOT reimplement)

Before writing any code, know what already exists. Reusing these saves ~40% of implementation time and avoids reintroducing bugs we already fixed.

| Need | Existing module | Notes |
|---|---|---|
| OHLCV cached loader | `src/simulation/cache.py:fetch_cached_ohlcv` | Parquet-cached yfinance with MultiIndex fix. Task 3 wraps this, does NOT reimplement. |
| SPY benchmark + excess returns | `src/analytics/spy_benchmark.py:spy_return_over_range, excess_return` | D1 instrumentation. Call directly. |
| Stop/target/timeout simulation | `src/attribution/logger.py:simulate_mechanical_outcome` | Production-audited (yesterday's forensic work). Returns `(outcome, exit_price, days_held)`. Reuse in Task 4. |
| Pattern reference for backtest structure | `src/evaluation/backtester.py` | Pullback-specific but proves the pattern. STUDY before writing Task 4. |
| Transaction cost constants | `src/simulation/engine.py:TRANSACTION_COSTS` (3 bps slippage, 1.5 bps spread, 0 commission) | Match these exactly for cross-comparability. |
| Sector classification | `src/universe/sectors.py` + `data/reference/sp100-gics-lookup.csv` | Already populated 100% of swing trades. |
| Regime classification | `src/features/regime.py` or call spy_benchmark which does it | D3 fix. |
| Universe | `src/universe/sp100.py:get_sp100_universe` | 100 tickers; sp500 module doesn't exist. |
| Schema / migration | `src/schema/registry.py` + `src/schema/sqlite.py:ensure_columns` | Idempotent, runs every watch loop startup. |
| Render sync | `src/sync/render_sync.py` supports `incremental`, `full`, `latest_only` modes | All three new tables use appropriate mode. |

**What does NOT exist (must be built):**
- Strategy specification format (YAML or Python plugin) — Task 1, 2
- General (strategy-agnostic) backtest engine — Task 4 (wraps simulate_mechanical_outcome)
- Shadow-trading harness for research strategies — Task 7
- Per-desk Alpaca client factory — required by Task 7 (see abandoned MVP spec's Task 3 for pattern)
- Strategy registry / promotion pipeline — Task 10
- Platform dashboard page — Task 12

---



```
┌─────────────────────────────────────────────────────────────────┐
│  Strategy Research Platform                                      │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ Strategy     │  │ Backtest     │  │ Shadow-Trade │          │
│  │ Specs        │──▶ Harness      │──▶ Harness      │──┐       │
│  │ (YAML + Py)  │  │              │  │              │  │       │
│  └──────────────┘  └──────────────┘  └──────────────┘  │       │
│         │                 │                 │           ▼       │
│         │                 │                 │     ┌──────────┐ │
│         │                 │                 │     │Promotion │ │
│         └────────────────┬┴─────────────────┘     │ Pipeline │ │
│                          │                         └──────────┘ │
│                          ▼                                       │
│                   ┌───────────────┐                             │
│                   │ Strategy      │                             │
│                   │ Registry      │                             │
│                   │ (DB table)    │                             │
│                   └───────────────┘                             │
└─────────────────────────────────────────────────────────────────┘
       │                          │                      │
       │ reads                    │ writes               │
       ▼                          ▼                      ▼
┌──────────────┐      ┌──────────────┐       ┌──────────────┐
│ ohlcv_bars   │      │ backtest_    │       │ shadow_trades│
│ edgar_filings│      │ results      │       │ (desk=       │
│ analyst_...  │      │ backtest_    │       │  research_*) │
│ (read-only)  │      │ trades       │       │              │
└──────────────┘      └──────────────┘       └──────────────┘
```

**Desks** (from the abandoned spec) are now called **research_candidates** — any strategy in the platform's pipeline. Once a candidate graduates via the promotion pipeline, it becomes a production desk (which is a separate sprint). This sprint does not produce any production desks.

---

## Task List

13 tasks across 4 components. Each task is independently committable.

### Component A: Strategy Specification Format

#### Task 1 — Strategy spec schema (1.5h)

**Files:**
- `docs/specs/strategy-schema.md` (new — documents the schema)
- `src/platform/__init__.py` (new module)
- `src/platform/strategy_spec.py` (new — loader + validator)
- `src/platform/specs/lazy_prices.yaml` (new — first example)
- `src/platform/specs/connors_rsi2.yaml` (new — second example for future loading)

**Schema (YAML form):**

```yaml
# src/platform/specs/lazy_prices.yaml
spec_version: 1
strategy_id: lazy_prices_v1
display_name: Lazy Prices (Cohen-Malloy-Nguyen 2020)

description: >
  Enter long positions on stocks with low cosine similarity between current
  and prior-year 10-K/10-Q Risk Factors and MD&A sections. Fundamental
  drift effect with 14-28 day holds.

citation: Cohen, Malloy, Nguyen (JF 2020). ~188 bps/month alpha (t=2.76).

universe:
  tickers: sp100                # or explicit list [AAPL, MSFT, ...]

entry:
  kind: event_driven            # 'scheduled' | 'event_driven' | 'python_plugin'
  event_table: edgar_filings
  event_filter:
    form_type: [10-K, 10-Q]
    filing_date_within_days: 5
  signal:
    # Structured filters — interpreted by BacktestHarness.evaluate_signal
    - metric: cosine_similarity
      target: item_1a            # Risk Factors
      reference: prior_year_same_form
      operator: less_than
      threshold: 0.75            # bottom-quartile = more-changed
    - metric: cosine_similarity
      target: item_7             # MD&A (10-K) — item_2 for 10-Q
      reference: prior_year_same_form
      operator: less_than
      threshold: 0.75
    # Either signal passing = enter (OR, not AND)
    combinator: any

exit:
  kind: mechanical
  timeout_days: 21
  stop:
    method: atr_based
    atr_period: 14
    multiplier: 3.0
    floor_pct: 0.05
    cap_pct: 0.12
  target:
    method: atr_based
    atr_period: 14
    multiplier: 6.0
    floor_pct: 0.10
    cap_pct: 0.25

position_sizing:
  method: fixed_pct_equity
  pct: 0.15
  max_concurrent: 5

attribution:
  benchmark: SPY_matched_window
  metrics: [raw_sharpe, excess_sharpe, win_rate, profit_factor, max_drawdown]

llm_enhancement:
  # Optional — if provided, LLM gate runs before order placement
  enabled: false                # v0.24.0 MVP: disabled
  model: halcyon-v1.0.0
  role: structured_extraction
  prompt_template: lazy_prices_research_prompt
  validation: verbatim_quote_grounded
```

**Loader signature:**

```python
# src/platform/strategy_spec.py
from dataclasses import dataclass
from pathlib import Path

@dataclass
class StrategySpec:
    strategy_id: str
    display_name: str
    universe: dict
    entry: dict
    exit: dict
    position_sizing: dict
    attribution: dict
    llm_enhancement: dict
    raw: dict                     # original loaded dict
    source: str                   # 'yaml:path' or 'python:class_name'

def load_spec_from_yaml(path: Path) -> StrategySpec:
    """Load + validate a YAML strategy spec. Raises on invalid schema."""

def validate_spec(spec: dict) -> tuple[bool, list[str]]:
    """Return (is_valid, errors). Enforces required keys, type constraints."""

def list_available_specs(specs_dir: Path = Path("src/platform/specs")) -> list[StrategySpec]:
    """Discover and load all YAML specs in directory."""
```

**Tests:**
- `tests/platform/test_strategy_spec.py`
  - `test_load_lazy_prices_yaml_valid`
  - `test_load_connors_rsi2_yaml_valid`
  - `test_reject_spec_missing_strategy_id`
  - `test_reject_spec_invalid_universe`
  - `test_reject_spec_unknown_entry_kind`
  - `test_list_available_specs_finds_both`

**Acceptance:** Both sample YAMLs load. Validator rejects malformed specs with actionable error messages.

---

#### Task 2 — Python plugin strategy interface (1.5h) [CUT-CANDIDATE if time pressed]

**File:** `src/platform/strategy_plugin.py` (new)

**Interface:**

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class Candidate:
    """A strategy's proposed trade before bracket/risk checks."""
    ticker: str
    as_of: str                    # ISO timestamp
    signal_direction: str         # 'long' | 'short'
    signal_strength: float        # 0.0 to 1.0 — determines sizing
    metadata: dict                # strategy-specific (e.g., {'filing_accession': '...'})

class StrategyPlugin(ABC):
    """Python plugin interface for complex strategies.

    YAML specs can implement any declarative strategy. Strategies that
    need custom signal computation (ML models, multi-source synthesis,
    etc) use this Python interface instead.
    """

    @abstractmethod
    def strategy_id(self) -> str: ...

    @abstractmethod
    def find_candidates(self, as_of: str, universe: list[str],
                        context: dict) -> list[Candidate]:
        """Scan universe at `as_of` date. Context contains 'db_path'
        and any other platform-provided resources.
        """

    def validate_candidate(self, candidate: Candidate,
                           market_data: dict) -> bool:
        """Optional: plugin-specific validation. Default: always True."""
        return True
```

**Registry:**

```python
# src/platform/plugin_registry.py
_PLUGINS: dict[str, type[StrategyPlugin]] = {}

def register_plugin(cls: type[StrategyPlugin]) -> type[StrategyPlugin]:
    """Decorator to register a strategy plugin."""
    instance = cls()
    _PLUGINS[instance.strategy_id()] = cls
    return cls

def get_plugin(strategy_id: str) -> StrategyPlugin | None:
    cls = _PLUGINS.get(strategy_id)
    return cls() if cls else None
```

**Tests:** `tests/platform/test_strategy_plugin.py` — mock plugin, verify registration and retrieval.

**[CUT-CANDIDATE]:** YAML-only specs cover Lazy Prices, Connors RSI(2), and most simple strategies. Defer Python plugins to v0.24.1 if time is tight.

---

### Component B: Backtest Harness (the load-bearing work)

#### Task 3 — OHLCV data access layer (1.5h)

**File:** `src/platform/data_loader.py` (new, thin wrapper)

**Pass 2 correction:** `src/simulation/cache.py:fetch_cached_ohlcv` already does parquet caching + yfinance fallback + MultiIndex handling. There is **no `ohlcv_bars` SQLite table** — OHLCV in Arcis comes from parquet files at `data/simulation_cache/` or live yfinance calls. Task 3 is a thin adapter over the existing cache module, NOT a reimplementation.

```python
# src/platform/data_loader.py
"""Platform data-access adapter.

Called by: src.platform.backtest_engine
Calls: src.simulation.cache (fetch_cached_ohlcv), src.analytics.spy_benchmark
Owns tables: none
Config keys: none
Tests: tests/platform/test_data_loader.py

This module exists to give the backtest engine a single clean import
surface. Under the hood, it delegates to:
  - src/simulation/cache.py:fetch_cached_ohlcv for ticker OHLCV (parquet cached)
  - src/analytics/spy_benchmark.py:spy_return_over_range for SPY benchmark
  - src/universe/sp100.py:get_sp100_universe for universe membership
"""

from __future__ import annotations

import pandas as pd
from src.simulation.cache import fetch_cached_ohlcv
from src.analytics.spy_benchmark import spy_return_over_range


def load_ohlcv_range(ticker: str, start: str, end: str) -> pd.DataFrame | None:
    """Delegate to simulation.cache. Returns None on missing data."""
    return fetch_cached_ohlcv(ticker, start, end)


def load_spy_return(entry_iso: str, exit_iso: str) -> float | None:
    """Delegate to analytics.spy_benchmark. Returns None on missing data."""
    return spy_return_over_range(entry_iso, exit_iso)


def load_universe_as_of(universe_tag: str, date: str) -> list[str]:
    """S&P 100 membership. Static for MVP (current membership only).

    LIMITATION: no point-in-time universe corrections. A stock that
    joined SPX in 2022 will be in the 2015 backtest universe. This is a
    known bias; acceptable for MVP, must be fixed before live capital.
    """
    if universe_tag == "sp500":
        # No sp500 module exists; fall back with warning.
        import logging
        logging.getLogger(__name__).warning(
            "[PLATFORM] sp500 universe requested but not implemented; "
            "falling back to sp100"
        )
    from src.universe.sp100 import get_sp100_universe
    return get_sp100_universe()
```

**Tests:** `tests/platform/test_data_loader.py`
- `test_load_ohlcv_aapl_returns_dataframe` (with cached parquet or mock)
- `test_load_ohlcv_missing_ticker_returns_none`
- `test_load_spy_return_matches_benchmark_module` (verify delegation works)
- `test_load_universe_sp500_falls_back_to_sp100_with_warning`

**Acceptance:** Adapter works; backtest engine imports from here, not from simulation/cache directly (keeps platform module boundary clean).

---

#### Task 4 — Backtest engine core (4h, HIGH RISK)

**File:** `src/platform/backtest_engine.py` (new)

**Pass 2 corrections (critical reuse):**
1. `src/attribution/logger.py:simulate_mechanical_outcome` already implements deterministic stop/target/timeout logic with no look-ahead. **Reuse it directly** rather than reimplementing bracket logic. It was audited in yesterday's forensic work and is production-correct.
2. `src/evaluation/backtester.py` exists and proves the overall pattern (load OHLCV → iterate days → run signal → track portfolio → compute metrics). It's pullback-specific (hardcoded ranker + features); our job is generalizing over the signal source via `StrategySpec`. Study this file before writing Task 4.
3. `src/analytics/spy_benchmark.py:spy_return_over_range` and `excess_return` already handle SPY-matched attribution. Call these directly.

This is the load-bearing component. Get it wrong and every evaluation is wrong.

```python
# src/platform/backtest_engine.py
"""Strategy-agnostic historical replay harness.

Reuses:
  - src.attribution.logger.simulate_mechanical_outcome for bracket outcomes
  - src.analytics.spy_benchmark.spy_return_over_range for excess returns
  - src.platform.data_loader.load_ohlcv_range for OHLCV (wraps simulation.cache)

Pattern reference (study before writing): src.evaluation.backtester
"""

from dataclasses import dataclass, field
from src.attribution.logger import simulate_mechanical_outcome
from src.analytics.spy_benchmark import spy_return_over_range, excess_return
from src.platform.data_loader import load_ohlcv_range

@dataclass
class BacktestConfig:
    strategy: StrategySpec  # Python plugins in Tier 5; MVP is YAML-only
    start_date: str
    end_date: str
    initial_capital: float = 100_000.0
    # Cost model matches src/simulation/engine.py:TRANSACTION_COSTS exactly
    # so platform backtests are comparable to scenario-engine backtests.
    commission_bps: float = 0
    slippage_bps: float = 3
    spread_bps: float = 1.5
    random_seed: int = 42

@dataclass
class BacktestTrade:
    trade_id: str
    ticker: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    shares: int
    pnl_dollars: float
    pnl_pct: float
    exit_reason: str              # 'win' | 'loss' | 'timeout' (matches simulate_mechanical_outcome)
    hold_days: int
    spy_return_over_hold: float   # from spy_return_over_range
    excess_return: float          # from excess_return
    realized_sector: str | None
    regime_at_entry: str | None
    metadata: dict = field(default_factory=dict)

@dataclass
class BacktestResult:
    strategy_id: str
    config: BacktestConfig
    trades: list[BacktestTrade]
    equity_curve: list[tuple[str, float]]
    metrics: dict
    reproducibility: dict

def run_backtest(config: BacktestConfig) -> BacktestResult:
    """Deterministic historical replay.

    Algorithm:
    1. For each trading day in [start, end]:
       a. For each ticker: get OHLCV slice, evaluate strategy signal
       b. If signal fires: compute ATR-based stop/target from entry bar
       c. Call simulate_mechanical_outcome to get exit
       d. Apply transaction costs on entry AND exit (2x the one-side bps)
       e. Compute SPY-matched excess via spy_return_over_range + excess_return
    2. Aggregate trades into equity curve
    3. Compute metrics (Task 5 delegates)
    4. Return BacktestResult
    """
```

**Key design decisions (non-negotiable):**
- **Deterministic.** Same inputs → same outputs.
- **No look-ahead.** Signal on day N uses only data ≤ day N. Entry on day N+1 open (matches live-trading behavior).
- **Reuse `simulate_mechanical_outcome`.** Do not reimplement stop/target logic.
- **Graceful degradation.** Missing ticker data for a day → skip that ticker that day. Do not crash.
- **Event-driven for event strategies.** YAML spec's `entry.kind: event_driven` means signal only fires on event days (filing, earnings); backtest iterates events, not every day.

**Validation — the hand-computed test:**

```python
# tests/platform/test_backtest_validation.py
def test_backtest_matches_hand_computed_example():
    """Trivial strategy with manually computed expected output.

    Setup:
    - Ticker AAPL, 2023-06-01 to 2023-06-30 (22 trading days)
    - Strategy: 'buy every Monday close, 2% stop / 3% target / 5-day timeout'
    - Entry prices, stop hits, exit prices hand-computed from known yfinance data
    - 4 Mondays in range → 4 entries expected

    Assert:
    - len(trades) == 4
    - trades[0].pnl_pct within 0.01% of hand-computed
    - metrics['total_return'] within 0.05% of hand-computed
    - metrics['excess_sharpe'] computed (non-null)
    """
```

Without this test the harness can silently drift and nobody notices. This test is the single most important piece of work in Tier 1. **If this test doesn't pass, do not ship the backtest engine.**

**Tests (minimum 8):**
- `test_backtest_matches_hand_computed_example` — above
- `test_backtest_no_lookahead_bias` — strategy that tries to peek at day N+1 → caught
- `test_backtest_handles_missing_data` — inject NaN for one ticker → backtest continues
- `test_backtest_determinism` — run twice with same seed → identical output
- `test_backtest_applies_transaction_costs` — zero-return trade shows cost drag
- `test_backtest_spy_excess_computed` — every trade has non-null excess_return
- `test_backtest_regime_attribution_present` — every trade has regime_at_entry (from spy_benchmark module)
- `test_backtest_drawdown_correct` — constructed equity curve, max_dd matches manual

**Acceptance:** Hand-computed test passes. Run Connors RSI(2) on 2020-2024 and get a result in <2min. Inspect output trades manually; verify they look sensible. If trades look wrong, STOP — the bug is in the engine, not the strategy.

---

#### Task 5 — Metrics computation (1.5h)

**File:** `src/platform/metrics.py` (new)

Extracts metrics computation so the backtest engine stays focused on simulation:

```python
def compute_sharpe(returns: list[float], periods_per_year: int = 252) -> float | None:
def compute_excess_sharpe(excess_returns: list[float], periods_per_year: int = 252) -> float | None:
def compute_sortino(returns: list[float], periods_per_year: int = 252) -> float | None:
def compute_calmar(total_return: float, max_drawdown: float) -> float:
def compute_max_drawdown(equity_curve: list[tuple[str, float]]) -> tuple[float, str, str]:
def compute_profit_factor(trades: list[BacktestTrade]) -> float | None:
def compute_deflated_sharpe(sharpe: float, n: int, skew: float = 0, kurtosis: float = 3) -> float:
    """López de Prado / Bailey 2014 deflated Sharpe for multiple-testing correction."""

def compute_all_metrics(trades: list[BacktestTrade],
                        equity_curve: list[tuple[str, float]]) -> dict:
    """Returns all metrics as a dict. Used by BacktestResult.metrics."""
```

**Tests:** Standard unit tests for each function with known-good inputs.

---

#### Task 6 — Backtest CLI + result persistence (1.5h)

**Files:**
- `scripts/run_backtest.py` (new — CLI runner)
- `src/schema/registry.py` (EDIT — add `backtest_results` + `backtest_trades` tables)

**Schema additions:**

```python
# src/schema/registry.py — add two tables

_register(TableDef(
    name="backtest_results",
    description="Platform backtest engine results — one row per backtest run",
    columns=[
        ColumnDef("result_id", "TEXT", nullable=False),      # UUID
        ColumnDef("strategy_id", "TEXT", nullable=False),
        ColumnDef("spec_version", "INTEGER", nullable=False),
        ColumnDef("spec_hash", "TEXT", nullable=False),      # SHA of spec dict
        ColumnDef("start_date", "TEXT", nullable=False),
        ColumnDef("end_date", "TEXT", nullable=False),
        ColumnDef("initial_capital", "REAL"),
        ColumnDef("total_trades", "INTEGER"),
        ColumnDef("total_return_pct", "REAL"),
        ColumnDef("sharpe", "REAL"),
        ColumnDef("excess_sharpe", "REAL"),
        ColumnDef("deflated_sharpe", "REAL"),
        ColumnDef("sortino", "REAL"),
        ColumnDef("calmar", "REAL"),
        ColumnDef("max_drawdown_pct", "REAL"),
        ColumnDef("win_rate", "REAL"),
        ColumnDef("profit_factor", "REAL"),
        ColumnDef("code_git_sha", "TEXT"),
        ColumnDef("created_at", "TEXT", nullable=False),
    ],
    primary_key="result_id",
    indexes=[
        IndexDef("idx_backtest_strategy_date", ["strategy_id", "end_date"]),
    ],
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="created_at",
))

_register(TableDef(
    name="backtest_trades",
    description="Individual trades from a backtest run",
    columns=[
        ColumnDef("trade_id", "TEXT", nullable=False),
        ColumnDef("result_id", "TEXT", nullable=False),
        ColumnDef("ticker", "TEXT", nullable=False),
        ColumnDef("entry_date", "TEXT", nullable=False),
        ColumnDef("exit_date", "TEXT"),
        ColumnDef("entry_price", "REAL"),
        ColumnDef("exit_price", "REAL"),
        ColumnDef("shares", "INTEGER"),
        ColumnDef("pnl_dollars", "REAL"),
        ColumnDef("pnl_pct", "REAL"),
        ColumnDef("exit_reason", "TEXT"),
        ColumnDef("hold_days", "INTEGER"),
        ColumnDef("spy_return_over_hold", "REAL"),
        ColumnDef("excess_return", "REAL"),
        ColumnDef("realized_sector", "TEXT"),
        ColumnDef("regime_at_entry", "TEXT"),
    ],
    primary_key="trade_id",
    indexes=[
        IndexDef("idx_backtest_trades_result", ["result_id"]),
    ],
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="entry_date",
))
```

**CLI:**

```bash
python scripts/run_backtest.py \
    --strategy lazy_prices_v1 \
    --start 2020-01-01 \
    --end 2024-12-31 \
    --output-format json \
    --persist
```

**Tests:**
- `test_backtest_persists_to_db`
- `test_spec_hash_changes_on_modification`
- `test_run_id_uuid_generated`

---

### Component C: Shadow-Trading Harness

#### Task 7 — Shadow-trading harness (5h) [STUB-OK if time pressed]

**File:** `src/platform/shadow_harness.py` (new)

Runs a validated strategy against live market data, logging paper fills without touching the production executor.

**Why a separate harness instead of reusing `src/shadow_trading/executor.py`:** The production executor is tightly coupled to the pullback-in-uptrend strategy's assumptions (bracket orders, specific exit logic, swing-specific risk). A general-purpose research platform needs to evaluate strategies with completely different shapes. The shadow harness is the "is this worth running on real capital" gate.

**Interface:**

```python
class ShadowHarness:
    def __init__(self, strategy_spec: StrategySpec,
                 alpaca_account: str = "research"):
        """alpaca_account maps to desks.{name}.alpaca_key_env in config."""

    def run_one_tick(self, as_of: datetime) -> dict:
        """Called by watch loop at strategy's cadence.

        1. Load current positions for this strategy (by strategy_id tag)
        2. Check exit conditions on open positions → close if warranted
        3. Call strategy.find_candidates(as_of, universe, context)
        4. For each candidate passing risk checks:
           - Place bracket order via Alpaca (research account)
           - Log to shadow_trades with desk='research_<strategy_id>'
        5. Return summary dict
        """

    def get_open_positions(self) -> list[dict]:
        """Query shadow_trades where desk LIKE 'research_{strategy_id}' AND open."""

    def halt(self) -> None:
        """Close all open positions via research Alpaca client. Used by kill switch."""
```

**Key architectural notes:**
- Shadow harness writes to `shadow_trades` table with `desk='research_<strategy_id>'` convention (e.g., `research_lazy_prices_v1`). This preserves desk-filtering semantics from the abandoned MVP spec.
- Uses the per-desk Alpaca client pattern from the abandoned spec (Task 3 there) — `get_client(desk)` in `src/shadow_trading/alpaca_clients.py`.
- **CRITICAL (from skeptical review):** Also patch `src/shadow_trading/reconcile.py` and `src/shadow_trading/bracket_monitor.py` to route by desk. These are the 11 Alpaca call sites the review flagged.

**[STUB-OK]:** If time pressure hits Task 7, ship the interface + one happy-path integration test, defer full reconcile/bracket_monitor integration to v0.24.1. Document the gap clearly in code comments.

**Tests:**
- `test_harness_opens_position_via_research_client`
- `test_harness_writes_shadow_trade_with_correct_desk`
- `test_harness_reconcile_uses_research_client` (CRITICAL per skeptical review)
- `test_harness_bracket_monitor_uses_research_client` (CRITICAL per skeptical review)
- `test_harness_halt_closes_only_this_strategy`

---

#### Task 8 — Research-desk schema additions (1h)

**File:** `src/schema/registry.py` (EDIT — same columns as abandoned spec, different convention)

Add to `shadow_trades`:

```python
ColumnDef("desk", "TEXT", default="swing",
          description="'swing' (Phase 1) or 'research_<strategy_id>' "
                      "(platform shadow-trades). Platform trades use "
                      "research_lazy_prices_v1 etc."),
ColumnDef("research_thesis", "TEXT"),
ColumnDef("strategy_spec_hash", "TEXT",
          description="SHA of the strategy spec at entry time — lets us "
                      "detect and filter out trades generated by an old "
                      "version of the spec after a parameter change."),
```

Add index: `IndexDef("idx_shadow_trades_desk", ["desk"])`.

Same migration behavior as the abandoned spec — 85 existing rows get `desk='swing'` via DEFAULT.

**Tests:** Same as abandoned spec's Task 2.

---

#### Task 9 — Watch loop platform integration (2h)

**File:** `src/scheduler/watch.py` (EDIT)

Add a new method that dispatches to every active shadow harness:

```python
def _run_platform_shadow_tick(self):
    """Tick every active research-platform strategy once.

    CRITICAL (from skeptical review): uses interval-gating pattern like
    _last_sentiment_refresh_time, NOT the inline pattern from _run_mr_scan.

    Each strategy has its own cadence_seconds; this method checks each
    one independently.
    """
    from src.platform.shadow_harness import ShadowHarness
    from src.platform.strategy_spec import list_available_specs
    from src.platform.promotion import get_strategies_by_status

    now = datetime.now(ET)
    active = get_strategies_by_status(["shadow_trading"])
    for strategy_id in active:
        spec = load_spec(strategy_id)
        interval = spec.raw.get("shadow_cadence_seconds", 600)
        last_tick = self._last_platform_tick.get(strategy_id)
        if last_tick is None or (now - last_tick).total_seconds() >= interval:
            self._safe_run(
                f"platform shadow tick: {strategy_id}",
                lambda s=strategy_id: ShadowHarness(load_spec(s)).run_one_tick(now),
            )
            self._last_platform_tick[strategy_id] = now
```

**Init:** `self._last_platform_tick: dict[str, datetime] = {}` in `WatchLoop.__init__`.

**Reset:** Add to `_reset_daily_state`: `self._last_platform_tick.clear()`.

**Tests:**
- `test_platform_tick_respects_cadence`
- `test_platform_tick_runs_each_strategy_independently`
- `test_platform_tick_failure_does_not_kill_swing`

---

### Component D: Promotion Pipeline

#### Task 10 — Strategy registry + promotion states (2h)

**Files:**
- `src/schema/registry.py` (EDIT — add `strategy_registry` table)
- `src/platform/promotion.py` (new)

**Schema:**

```python
_register(TableDef(
    name="strategy_registry",
    description="Registry of all strategies in the research platform lifecycle",
    columns=[
        ColumnDef("strategy_id", "TEXT", nullable=False),
        ColumnDef("display_name", "TEXT", nullable=False),
        ColumnDef("spec_source", "TEXT", nullable=False),     # yaml path or python class
        ColumnDef("current_status", "TEXT", nullable=False),  # proposed | backtested | shadow_trading | production | deprecated
        ColumnDef("current_spec_hash", "TEXT", nullable=False),
        ColumnDef("created_at", "TEXT", nullable=False),
        ColumnDef("last_status_change", "TEXT", nullable=False),
        ColumnDef("notes", "TEXT"),
    ],
    primary_key="strategy_id",
    sync_to_postgres=True,
    sync_mode="full",              # small table, full sync
))

_register(TableDef(
    name="strategy_promotion_events",
    description="Append-only log of strategy promotion/demotion events",
    columns=[
        ColumnDef("event_id", "INTEGER", nullable=False),
        ColumnDef("strategy_id", "TEXT", nullable=False),
        ColumnDef("from_status", "TEXT"),
        ColumnDef("to_status", "TEXT", nullable=False),
        ColumnDef("triggered_by", "TEXT", nullable=False),   # 'manual' | 'auto_gate'
        ColumnDef("gate_result_json", "TEXT"),               # evidence for auto promotions
        ColumnDef("timestamp", "TEXT", nullable=False),
    ],
    primary_key="event_id",
    indexes=[
        IndexDef("idx_promotion_strategy_time", ["strategy_id", "timestamp"]),
    ],
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="timestamp",
))
```

**Promotion logic:**

```python
# src/platform/promotion.py

STATUSES = {"proposed", "backtested", "shadow_trading", "production", "deprecated"}

PROMOTION_GATES = {
    ("proposed", "backtested"): {
        "min_backtest_runs": 1,
        "min_backtest_trades": 30,
        "min_backtest_excess_sharpe": 0.5,
        "max_max_drawdown_pct": 0.20,
    },
    ("backtested", "shadow_trading"): {
        "manual_only": True,       # explicit human promotion
    },
    ("shadow_trading", "production"): {
        "min_shadow_trades": 30,
        "min_excess_sharpe_shadow": 0.5,
        "min_excess_sharpe_tstat": 1.65,
        "manual_confirmation": True,
    },
}

def check_promotion_gate(strategy_id: str, target_status: str,
                         db_path: str = DB_PATH) -> tuple[bool, dict]:
    """Check if strategy meets gate for target_status. Returns (passes, evidence)."""

def promote(strategy_id: str, target_status: str,
            triggered_by: str = "manual",
            db_path: str = DB_PATH) -> None:
    """Promote strategy. Logs to strategy_promotion_events. Raises on gate failure."""

def demote(strategy_id: str, reason: str,
           db_path: str = DB_PATH) -> None:
    """Move strategy to 'deprecated'. Halts any shadow trading."""

def get_strategies_by_status(statuses: list[str],
                              db_path: str = DB_PATH) -> list[str]:
    """Return strategy_ids currently in given statuses."""
```

**Tests:**
- `test_promote_backtested_to_shadow_requires_manual`
- `test_promote_shadow_to_production_checks_all_gates`
- `test_promote_writes_event_log`
- `test_demote_halts_shadow_trading`
- `test_gate_failure_returns_evidence_dict`

---

### Component E: First Strategy + Dashboard

#### Task 11 — Lazy Prices strategy as YAML spec (3h)

**Files:**
- `src/platform/specs/lazy_prices.yaml` (exists from Task 1, now used)
- `src/platform/features/cosine_similarity.py` (new — pure cosine function, no DB access)
- `src/platform/features/event_providers.py` (new — DB-backed event lookup)
- `src/data_collection/edgar_collector.py` (EDIT — add item_1a regex)

**Approach:** The YAML spec's `event_filter` + `signal` blocks are interpreted by the backtest engine via "feature providers" — pluggable functions that compute signals on demand.

```python
# src/platform/features/cosine_similarity.py
def cosine_similarity_yoy(
    ticker: str, accession: str, section_key: str, db_path: str,
) -> float | None:
    """Read sections_json for current + prior-year same-form filing,
    return cosine similarity. None if either side missing.
    """

# Backtest engine's signal evaluator maps YAML metric names to these
# provider functions via a registry.
```

**Pre-requisite (from Task 0):** EDGAR `sections_json` must be populated for at least 70% of filings. Without this, the backtest returns 0 candidates for Lazy Prices.

**If Task 0 not complete by this point:** Ship the YAML spec + feature providers + backtest-engine wiring anyway. Backtest will produce `candidates=0` with a `low_filing_data_coverage` warning. The platform is demonstrably correct; the data is demonstrably missing.

**Tests:**
- `test_lazy_prices_cosine_computation_matches_manual`
- `test_lazy_prices_backtest_with_real_data` (requires populated sections_json)
- `test_lazy_prices_backtest_returns_zero_with_empty_sections_json`

---

#### Task 12 — Dashboard: Strategy Research page (3h) [STUB-OK]

**File:** `frontend/src/pages/StrategyResearch.jsx` (new)
**Route:** Add `/research-platform` to router

Four sections:

1. **Strategy Registry table** — all strategies with current status, last backtest date, backtest Sharpe, shadow trades count
2. **Backtest Results grid** — per strategy, historical backtest results with key metrics
3. **Shadow Trading status** — per active shadow strategy, open positions count, today P&L, excess-Sharpe on shadow trades
4. **Promotion Events log** — last 20 promotion/demotion events

**API endpoints needed:** Add to `src/api/cloud_routes/platform.py` (new):

- `GET /api/platform/strategies` → list
- `GET /api/platform/strategies/{id}` → detail
- `GET /api/platform/backtest-results?strategy_id=...` → historical runs
- `GET /api/platform/promotion-events?limit=20` → recent events

**[STUB-OK]:** If time-pressed, ship a skeleton page that just lists strategies from the registry. Defer backtest result views and promotion event views to v0.24.1.

**Tests:** `test_platform_routes_registered`, `test_list_strategies_returns_registry_rows`.

---

#### Task 13 — Docs sweep + MASTER.md + activation plan (1.5h)

**Files:**
- `MASTER.md` (EDIT) — add Section: Research Platform (between Sections 8 and 9)
- `RELEASES.md` (EDIT) — v0.24.0 entry
- `CHANGELOG.md` (EDIT) — v0.24.0 block
- `README.md` (EDIT) — version badge + brief platform mention
- `docs/platform/activation-guide.md` (new) — how to load a strategy into the platform

**Activation guide content:**

```markdown
# Loading a New Strategy

1. Create `src/platform/specs/<strategy_id>.yaml` following schema in
   `docs/specs/strategy-schema.md`
2. Run a backtest: `python scripts/run_backtest.py --strategy <id> --start ... --end ...`
3. Review results via dashboard or direct SQL query
4. If backtest passes gate (see `src/platform/promotion.py:PROMOTION_GATES`),
   promote to shadow-trading:
   `python -m src.platform.promotion promote <id> shadow_trading`
5. Watch loop picks up the new strategy on next platform tick
6. Monitor via dashboard's Strategy Research page

## Gates

- Proposed → Backtested: automatic on first successful backtest meeting thresholds
- Backtested → Shadow: manual (Ryan confirms)
- Shadow → Production: manual + all statistical gates met

## Halting a Strategy

`python -m src.platform.promotion demote <id> "reason"`

Sets status to deprecated, closes open positions via research Alpaca client.
```

---

## Go/No-Go Criteria

Before merging, ALL must be true:

1. `pytest tests/ -x` passes with pass count ≥ baseline + new tests
2. `cd frontend && npm run build` succeeds
3. Hand-computed backtest validation test passes (Task 4's critical test)
4. `python scripts/run_backtest.py --strategy lazy_prices_v1 --start 2020-01-01 --end 2024-12-31` either produces a result with trades, OR returns `candidates=0 filing_data_coverage=<x>%` without exceptions
5. Watch loop starts cleanly with no `strategy_registry` entries in `shadow_trading` status (platform inert until strategies are promoted)
6. All 85 existing `shadow_trades` rows have `desk='swing'`
7. Strategy Research dashboard page renders (even if stubbed)

---

## Honest Task Priority

If the weekend runs short, ship tasks in this order:

**Tier 1 — foundation (must ship, ~10h):** T1 (spec schema), T3 (data loader), T4 (backtest engine), T5 (metrics), T6 (persistence)

**Tier 2 — evaluate a real strategy (~6h):** T11 (Lazy Prices spec), Task 0 (EDGAR fix — concurrent with above)

**Tier 3 — platform lifecycle (~5h):** T8 (schema additions), T10 (promotion pipeline)

**Tier 4 — live deployment (~8h):** T7 (shadow harness), T9 (watch loop integration)

**Tier 5 — surfaces (~4h):** T2 (Python plugin), T12 (dashboard), T13 (docs)

**If Tier 1+2 ship:** Platform exists, Lazy Prices has a validated backtest, everything else is v0.24.1.
**If Tier 1+2+3 ship:** Platform has full lifecycle; shadow trading is plumbed but not connected to watch loop (runs via CLI only).
**If Tier 1+2+3+4 ship:** Full target scope.
**If all 5 ship:** Ambitious plan achieved.

---

## Out-of-Scope (Explicit Deferrals)

- LLM-assisted strategy proposal (the platform can load strategies but doesn't generate them)
- Walk-forward backtesting (point-in-time splits) — MVP uses static in-sample evaluation
- Portfolio-level optimization across strategies — each strategy sizes independently
- Live-trading promotion from shadow (production desks are not part of the platform; they're separate code)
- Multi-process / multi-GPU strategy execution — single-process synchronous MVP
- Real-time dashboard updates — polling refresh only
- Jupyter notebook integration for strategy research
- Cross-strategy correlation monitoring
- Strategy parameter optimization / hyperparameter search
- Any second-Alpaca-account work deferred from abandoned MVP spec (the shadow harness uses the research Alpaca account, but the 11-call-site fix is Tier 4 work)

---

## Risk Mitigations

| Risk | Mitigation |
|---|---|
| Backtest engine has a silent bug | Hand-computed validation test (Task 4). Non-negotiable. |
| EDGAR data still broken at merge time | Task 0 runs independently. Platform ships regardless; Lazy Prices just returns 0 candidates with clear warning. |
| Weekend time pressure kills Tier 4+5 | Tier-based success criteria. Ship Tier 1+2 minimum. |
| Shadow harness misroutes trades to swing account | Per-desk Alpaca client assertion pattern from abandoned spec. 11-call-site fix must be thorough. |
| Strategy spec format changes require schema migrations | `spec_version: 1` field in YAML. Future breaking changes bump version; loader checks. |
| New tables break render_sync | All new tables declared with proper `sync_to_postgres=True` + mode. `ensure_columns` runs every sync cycle. |
| Lazy Prices backtest produces overly-optimistic results | Deflated Sharpe computation (Task 5) discounts for multiple-testing. Reporting includes both raw and deflated. |

---

*Ralph loop: this is Pass 1. Pass 2 corrections will come from actual repo grep (done via CC sprint execution with the tool search in context). Commit on merge with a prominent TODO list for v0.24.1.*
