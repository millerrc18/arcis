# Sprint: Arcis Strategy Research Platform (v0.24.0)

**Authority:**
- Deep research: `docs/research/deep-research/research-desk-design-report.md` (Lazy Prices + ML-SUE as first strategy candidate)
- Skeptical review: `docs/research/2026-04-16-research-desk-sprint-review.md` (killed the prior MVP spec by exposing EDGAR data crisis + ~12 Alpaca call sites)
- Backtest rigor: `docs/research/deep-research/backtest-rigor-retrofit-plan.pdf` (Bailey-López de Prado 2014 DSR + CSCV + walk-forward — replaces naive Sharpe ≥ 0.5 gate)
- Correlation/risk: `docs/research/deep-research/correlation-risk-monitoring-blueprint.pdf` (Longin-Solnik tail correlation + Carhart+QMJ factor decomp + Millennium/Citadel exposure architecture translated to retail)
- User pivot: Ryan wants a **strategy research platform**, not a second production desk. Supersedes `docs/sprints/sprint-research-desk-mvp.md` which is now archived.

**Branch:** `feat/research-platform`
**Tag on merge:** v0.24.0
**Effort:** 50-72 hours, honestly. Compressed to a single weekend. User explicitly accepted ambitious scope twice (once for platform vs. desk, once for full-rigor retrofit in v0.24.0).
**Priority:** Ambitious — full rigor baked in from day one. First backtest results will be trustworthy, not suspect.

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

This spec is **50-72 hours of work** compressed into a weekend. That is not going to fit. Three things will happen:

1. Some tasks will be cut. Sections marked **[CUT-CANDIDATE]** are the first to go.
2. Some tasks will be stubbed — interface created, implementation deferred.
3. At least one task will have a bug we don't catch until next weekend. The backtest harness (Task 4) and DSR implementation (Task 5b) are the highest-risk components — bugs there invalidate every evaluation.

Explicit success criteria at three tiers:

- **Minimum Viable Product (weekend baseline, ~20h):** Backtest harness + DSR gate + hand-computed validation test + Lazy Prices YAML spec + defensive dashboard desk filtering. No shadow-trading, no correlation monitoring, no dedicated platform page.
- **Target (stretch, ~45h):** Above + CSCV/walk-forward + promotion pipeline + shadow-trading harness + correlation monitoring schema + hard exposure limits.
- **Ambitious (full spec, ~72h):** All components + factor decomposition + PELT change detection + full dashboard platform page + action buttons + home widget + Telegram event notifications.

**Estimate trajectory:**
- Pass 1 was 40-60h
- Pass 2+3 infrastructure-reuse audit saved ~8h
- Task 12 expansion added ~4h for proper dashboard synergy
- Rigor retrofit (DSR + CSCV + walk-forward in Task 5) added ~3h
- Correlation monitoring stack (new Task 11b) added ~6h
- Net: 50-72h.

**The "why bake rigor in now" decision:** The alternative was to ship the platform this weekend with `excess_sharpe ≥ 0.5` as the promotion gate, discover in v0.24.1 that ~50% of passing strategies were noise (per Bailey-López de Prado 2014), and retrofit. Ryan chose to front-load the rigor so that Lazy Prices' first backtest result is trustworthy the day it completes — not after a retrofit next month.

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

## Architecture

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
│ parquet cache│      │ backtest_    │       │ shadow_trades│
│ edgar_filings│      │ results      │       │ (desk=       │
│ analyst_...  │      │ backtest_    │       │  research_*) │
│ (read-only)  │      │ trades       │       │              │
└──────────────┘      └──────────────┘       └──────────────┘
```

**Desks** (from the abandoned spec) are now called **research_candidates** — any strategy in the platform's pipeline. Once a candidate graduates via the promotion pipeline, it becomes a production desk (which is a separate sprint). This sprint does not produce any production desks.

---

## Task List

Task 0 (EDGAR data repair, separable) plus 14 tasks across 5 components (A-E). Each task is independently committable.

### Component A: Strategy Specification Format

#### Task 1 — Strategy spec schema (1.5h)

**Files:**
- `docs/specs/strategy-schema.md` (new — documents the schema)
- `src/platform/__init__.py` (new module)
- `src/platform/strategy_spec.py` (new — loader + validator)
- `src/platform/specs/lazy_prices.yaml` (new — first example; full YAML below)

**Note:** A second example strategy (Connors RSI(2), Quality+Momentum, etc.) can be loaded in a follow-up sprint. For this weekend, Lazy Prices is the single tenant that exercises the platform end-to-end. Do not invent YAML contents for untested strategies.

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

def load_spec(strategy_id: str,
              specs_dir: Path = Path("src/platform/specs")) -> StrategySpec:
    """Load spec by strategy_id — resolves to <specs_dir>/<strategy_id>.yaml.
    Used by Task 9's watch-loop integration. Raises FileNotFoundError if
    the spec file does not exist.
    """

def validate_spec(spec: dict) -> tuple[bool, list[str]]:
    """Return (is_valid, errors). Enforces required keys, type constraints."""

def list_available_specs(specs_dir: Path = Path("src/platform/specs")) -> list[StrategySpec]:
    """Discover and load all YAML specs in directory."""
```

**Tests:**
- `tests/platform/test_strategy_spec.py`
  - `test_load_lazy_prices_yaml_valid`
  - `test_reject_spec_missing_strategy_id`
  - `test_reject_spec_invalid_universe`
  - `test_reject_spec_unknown_entry_kind`
  - `test_list_available_specs_finds_lazy_prices`
  - `test_load_spec_by_id_resolves_yaml_path`
  - `test_load_spec_by_id_raises_on_missing`

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
from src.platform.strategy_spec import StrategySpec
from src.attribution.logger import simulate_mechanical_outcome
from src.analytics.spy_benchmark import spy_return_over_range, excess_return
from src.platform.data_loader import load_ohlcv_range

@dataclass
class BacktestConfig:
    strategy: StrategySpec  # Python plugins (Task 2) are Tier 7; MVP is YAML-only
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
- **Reuse `simulate_mechanical_outcome`.** Do not reimplement stop/target logic. The function signature is `(entry_price, stop_price, target_price, timeout_days, ohlcv) -> (outcome, exit_price, days_held)` where outcome is `'win' | 'loss' | 'timeout'`.
- **Graceful degradation.** Missing ticker data for a day → skip that ticker that day. Do not crash.
- **Event-driven dispatch.** For strategies with `entry.kind: event_driven`: the backtest loop first enumerates matching event rows from the strategy's declared `event_table` (e.g., `edgar_filings` for Lazy Prices, `analyst_estimates` for earnings-surprise strategies) within the backtest date range. For each event row, it evaluates the YAML `signal` filters; on pass, it opens a trade at the next-day open using OHLCV from `load_ohlcv_range`. This means event strategies iterate events (sparse), not days (dense). For `entry.kind: scheduled` strategies, iterate every trading day in the range.

**Validation — the hand-computed tests (TWO required):**

```python
# tests/platform/test_backtest_validation.py

def test_backtest_matches_hand_computed_example_scheduled():
    """SCHEDULED-kind validation: trivial time-based strategy.

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

def test_backtest_matches_hand_computed_example_event_driven():
    """EVENT-DRIVEN validation: event-anchored strategy using edgar_filings.

    Why this is separate (W1 finding): the scheduled-kind test above only
    exercises the day-iteration code path. Event-driven strategies (like
    Lazy Prices) use a different code path that enumerates event rows from
    edgar_filings / analyst_estimates, then prices via OHLCV. A bug in the
    event dispatcher would NOT be caught by the scheduled test.

    Setup:
    - Seed a temp SQLite DB with 3 synthetic edgar_filings rows for AAPL,
      MSFT, GOOGL on specific dates in 2023 with pre-computed cosine
      similarity values (0.40, 0.85, 0.60 — only the first is below 0.75)
    - Strategy: 'enter on 10-K filing with cosine < 0.75, 3x ATR stop, 6x ATR target, 21d timeout'
    - Only AAPL should trigger entry (cosine 0.40 < 0.75)
    - Entry at next-day open, exit hand-computed from OHLCV

    Assert:
    - len(trades) == 1
    - trades[0].ticker == 'AAPL'
    - trades[0].metadata['filing_accession'] == seeded accession
    - trades[0].entry_date is the trading day AFTER the filing date
    - trades[0].pnl_pct within 0.01% of hand-computed value
    - MSFT and GOOGL filings did NOT produce trades (filter worked)
    """
```

Without BOTH tests, the harness has untrusted code paths. This pair is the single most important piece of work in Tier 1. **If either test doesn't pass, do not ship the backtest engine.**

**Tests (minimum 9):**
- `test_backtest_matches_hand_computed_example_scheduled` — above
- `test_backtest_matches_hand_computed_example_event_driven` — above (separate code path, MUST NOT skip)
- `test_backtest_no_lookahead_bias` — strategy that tries to peek at day N+1 → caught
- `test_backtest_handles_missing_data` — inject NaN for one ticker → backtest continues
- `test_backtest_determinism` — run twice with same seed → identical output
- `test_backtest_applies_transaction_costs` — zero-return trade shows cost drag
- `test_backtest_spy_excess_computed` — every trade has non-null excess_return
- `test_backtest_regime_attribution_present` — every trade has regime_at_entry (from spy_benchmark module)
- `test_backtest_drawdown_correct` — constructed equity curve, max_dd matches manual

**Acceptance:** BOTH hand-computed tests pass (scheduled AND event-driven — separate code paths). Run the trivial "buy every Monday" strategy on AAPL for 2023-06-01 to 2023-06-30 and get a deterministic result. Inspect output trades manually; verify they look sensible. If trades look wrong, STOP — the bug is in the engine, not the strategy.

---

#### Task 5 — Metrics, DSR, CSCV, walk-forward (4h, HIGH RIGOR)

**Authority:** Deep research `docs/research/deep-research/backtest-rigor-retrofit-plan.pdf` (Bailey, Borwein, López de Prado & Zhu 2014, "The Probability of Backtest Overfitting"; Bailey & López de Prado 2014, "The Deflated Sharpe Ratio", JPM 40(5):94-107).

**Files:**
- `src/platform/metrics.py` (new — basic metrics)
- `src/platform/rigor/dsr.py` (new — Deflated Sharpe)
- `src/platform/rigor/cscv.py` (new — CSCV / PBO)
- `src/platform/rigor/walkforward.py` (new — rolling walk-forward)
- `src/platform/rigor/__init__.py` (new)

**Why this task expanded from 1.5h to 4h:** The honest annualized-Sharpe hurdle for 30 serial strategies with ρ≈0.2 assumed strategy correlation is **~1.0-1.3, not 0.5**. Without DSR as the primary gate, 50% of passing strategies will be noise. The deep research report provides verified Python implementation with a unit test reproducing the paper's p.9 worked example to four decimals.

**5a — Basic metrics (`src/platform/metrics.py`, 1h)**

```python
def compute_sharpe(returns: list[float], periods_per_year: int = 252) -> float | None:
def compute_excess_sharpe(excess_returns: list[float], periods_per_year: int = 252) -> float | None:
def compute_sortino(returns: list[float], periods_per_year: int = 252) -> float | None:
def compute_calmar(total_return: float, max_drawdown: float) -> float:
def compute_max_drawdown(equity_curve: list[tuple[str, float]]) -> tuple[float, str, str]:
def compute_profit_factor(trades: list[BacktestTrade]) -> float | None:

def compute_all_metrics(trades: list[BacktestTrade],
                        equity_curve: list[tuple[str, float]],
                        survivorship_haircut_bps: int = 75) -> dict:
    """Returns all metrics. survivorship_haircut_bps subtracts from
    annualized return before computing downstream metrics. Default
    75 bps/yr matches deep research recommendation for short-hold
    strategies; use 200 for momentum, 100 for other."""
```

**5b — Deflated Sharpe Ratio (`src/platform/rigor/dsr.py`, 1h)**

This IS the primary promotion gate. Current spec's `excess_sharpe ≥ 0.5` is replaced by `DSR ≥ 0.95`.

```python
"""Deflated Sharpe Ratio — Bailey & López de Prado (2014) JPM 40(5):94-107.

Verified implementation from deep research retrofit plan. Reproduces
paper's p.9 worked example (SR_ann=2.5, T=1250, N=100, skew=-3, kurt=10)
to 4 decimals: DSR ≈ 0.9004, SR*_0_ann ≈ 0.5429.

Called by: src.platform.promotion (primary gate), CLI via run_backtest.py
Owns tables: trials_registry (see Task 10)
Tests: tests/platform/rigor/test_dsr.py
"""

import warnings
import numpy as np
import pandas as pd
from scipy.stats import norm, skew as _skew, kurtosis as _kurt

EULER_MASCHERONI = 0.5772156649015328606


def expected_max_sr(n_trials: int, trials_sr_variance: float) -> float:
    """E[max SR] across n_trials assuming SRs are i.i.d. Normal(0, V).
    Bailey-López de Prado 2014 Eq. (8)."""
    if n_trials < 2:
        return 0.0
    g = EULER_MASCHERONI
    z1 = norm.ppf(1.0 - 1.0 / n_trials)
    z2 = norm.ppf(1.0 - 1.0 / (n_trials * np.e))
    return float(np.sqrt(trials_sr_variance) * ((1 - g) * z1 + g * z2))


def probabilistic_sharpe_ratio(sr_hat: float, sr_benchmark: float,
                                T: int, skew_: float, kurt_: float) -> float:
    """PSR = Prob(SR_true > sr_benchmark | sample). Bailey-López de
    Prado 2014 Eq. (2). Uses Pearson (non-excess) kurtosis — Normal = 3."""
    denom_in = 1.0 - skew_ * sr_hat + ((kurt_ - 1.0) / 4.0) * sr_hat ** 2
    if denom_in <= 0:
        warnings.warn("PSR denominator non-positive; small-sample pathology",
                      RuntimeWarning)
        return float("nan")
    z = (sr_hat - sr_benchmark) * np.sqrt(T - 1) / np.sqrt(denom_in)
    return float(norm.cdf(z))


def deflated_sharpe_ratio(trade_returns: pd.Series,
                          n_trials: int,
                          trials_sr_variance: float | None = None) -> dict:
    """Deflated Sharpe Ratio. Returns dict with DSR, PSR, components.

    Args:
        trade_returns: per-trade returns (NOT daily, NOT annualized)
        n_trials: cumulative N_eff across ALL backtests run to date
            (counts parameter combinations, not just final strategies)
        trials_sr_variance: V[SR_n]. If None, uses 1/T null.

    Returns dict: {SR_hat, skew, kurt, T, E_SR_max, PSR, DSR}
    DSR is scale-invariant; annualize only for display.
    """
    r = pd.Series(trade_returns).dropna().astype(float)
    T = len(r)
    if T < 30:
        warnings.warn(f"T={T}<30; DSR unreliable. Use PSR as primary "
                      "gate at this sample size.", RuntimeWarning)
    sr_hat = r.mean() / r.std(ddof=1)
    g3 = float(_skew(r, bias=False))
    g4 = float(_kurt(r, fisher=False, bias=False))
    if trials_sr_variance is None:
        trials_sr_variance = 1.0 / T
        warnings.warn("trials_sr_variance missing; using 1/T null",
                      RuntimeWarning)
    sr_star_0 = expected_max_sr(n_trials, trials_sr_variance)
    return {
        "SR_hat": sr_hat, "skew": g3, "kurt": g4, "T": T,
        "E_SR_max": sr_star_0,
        "PSR": probabilistic_sharpe_ratio(sr_hat, 0.0, T, g3, g4),
        "DSR": probabilistic_sharpe_ratio(sr_hat, sr_star_0, T, g3, g4),
    }
```

**Critical — effective N counting:** N_trials counts EVERY parameter combination ever tested, not just final strategies. If you test 30 strategies each with 10 parameter grid points, N_eff = 300. Maintain `trials_registry` table (see Task 10) with every backtest ever run. Per-strategy backtests and per-param-sweep backtests both increment N_eff globally.

**Unit test reproducing paper's p.9 example (non-negotiable):**

```python
def test_dsr_paper_example():
    """Bailey-López de Prado 2014 p.9: SR_ann=2.5, 250 obs/yr, T=1250,
    N=100, skew=-3, kurt=10 → DSR=0.9004, SR*_0_ann=0.5429."""
    SR = 2.5 / np.sqrt(250)
    V = 0.5 / 250
    N, T, g3, g4 = 100, 1250, -3.0, 10.0
    g = 0.5772156649
    sr0 = np.sqrt(V) * ((1-g)*norm.ppf(1-1/N) + g*norm.ppf(1-1/(N*np.e)))
    assert abs(sr0 * np.sqrt(250) - 0.5429) < 0.002
    num = (SR - sr0) * np.sqrt(T - 1)
    denom = np.sqrt(1 - g3*SR + (g4-1)/4 * SR**2)
    dsr = norm.cdf(num/denom)
    assert abs(dsr - 0.9004) < 0.003
```

**5c — CSCV / PBO (`src/platform/rigor/cscv.py`, 1h)**

Combinatorially Symmetric Cross-Validation (Bailey et al. 2014). Input: T×N daily-PnL matrix (T daily observations × N strategy configs). Partition rows into S=16 blocks → C(16,8) = 12,870 train/test pairs. For each split, compute IS-best strategy's OOS rank, logit-transform. **PBO = fraction of splits where IS-winner lands below OOS median.**

```python
def pbo_from_pnl_matrix(pnl_matrix: pd.DataFrame, S: int = 16) -> dict:
    """Probability of Backtest Overfitting per Bailey et al. 2014.

    Args:
        pnl_matrix: T rows (daily obs) × N cols (strategy configs).
            Wide form. Missing days = NaN (handled by dropna).
        S: number of partitions. 16 is paper's canonical; adjust only
            if T < 256 (then S = T // 16 with warning).

    Returns:
        {PBO, logit_distribution, performance_degradation_points}
        PBO > 0.5 = likely overfit; reject strategy.
    """
```

Known failures (per deep research): blind to look-ahead bugs, regime shifts outside sample, homogeneous-strategy degeneracy (Vojtko-Padyšák 2021). Treat PBO as one filter among many, not a silver bullet.

**When to use CSCV:** Run when any backtest involves parameter sweeps. Pure single-config backtests don't need CSCV (DSR handles between-strategy selection bias; CSCV addresses within-strategy grid-search bias).

**5d — Rolling walk-forward (`src/platform/rigor/walkforward.py`, 1h)**

Pardo 2008 annual train/test slide. Per deep research, use 3y train / 1y test sliding annually, or 6mo/1mo if data is short. Output: concatenated OOS equity curve per strategy.

```python
def run_walkforward(strategy_spec, start_date: str, end_date: str,
                    train_years: int = 3, test_years: int = 1) -> dict:
    """Rolling walk-forward. Slides train/test windows across history.

    For each fold:
      1. Train: fit any strategy parameters on train window (for rule-based
         strategies with no fitted params, this is a no-op + sanity check)
      2. Test: run backtest on test window, collect OOS trades
    Concatenates all OOS trades and computes:
      - OOS Sharpe (per fold + aggregate)
      - OOS efficiency = OOS_SR / IS_SR
      - Concatenated equity curve

    Returns dict: {folds, aggregate_oos_trades, oos_equity_curve,
                   oos_sharpe, oos_efficiency}
    """
```

**Pardo's rule:** OOS efficiency should exceed 0.5 (concatenated OOS Sharpe should be at least half of in-sample Sharpe). If OOS efficiency < 0.3, strategy is overfit. This becomes a secondary gate.

**Tests for Task 5 (minimum 12):**
- `test_dsr_paper_example_reproduction` — DSR paper p.9 to 4 decimals (NON-NEGOTIABLE)
- `test_psr_benchmark_comparison` — PSR output matches paper Eq. (2) on known inputs
- `test_expected_max_sr_monotonic_in_n` — E[max SR] grows with N
- `test_dsr_handles_negative_denominator` — clip + NaN + warning
- `test_dsr_small_sample_warns` — T<30 triggers RuntimeWarning
- `test_pbo_rejects_overfit_strategy` — seeded PnL matrix with known IS/OOS divergence
- `test_pbo_accepts_stable_strategy` — seeded stable-performer returns PBO<0.2
- `test_pbo_handles_S16_T252` — paper's canonical config
- `test_walkforward_concatenated_trades_correct_count`
- `test_walkforward_oos_efficiency_computed`
- `test_walkforward_flags_strategy_with_efficiency_below_threshold`
- `test_survivorship_haircut_applied_to_annualized_return`

**Acceptance:** DSR paper-example test passes. CSCV on synthetic overfit strategy returns PBO > 0.8. Walk-forward on a trivially-stable strategy returns efficiency > 0.8.

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
- Shadow harness writes to `shadow_trades` table with `desk='research_<strategy_id>'` convention (e.g., `research_lazy_prices_v1`). This is the filtering key for all desk-aware queries.
- **Per-desk Alpaca client pattern (inline, since the abandoned MVP spec reference is not authoritative here):** Create `src/shadow_trading/alpaca_clients.py` with a `get_client(desk: str) -> TradingClient` function that reads `desks.{desk}.alpaca_key_env` and `desks.{desk}.alpaca_secret_env` from config, resolves the env var values, and returns a `TradingClient(api_key=..., secret_key=..., paper=True)` with `client.desk_tag = desk` attached for assertion guardrails. Cache per-desk; threadsafe. Add `verify_accounts_distinct()` that calls `get_client('swing').get_account().account_number` vs `get_client('research').get_account().account_number` and raises if they match (prevents the "both desks pointing at the same paper account" bug).
- **CRITICAL (Pass 2 verification):** reconcile.py is **active**, not dormant. `reconcile_paper_trades` is called from `src/scheduler/overnight.py:27`, `src/scheduler/position_monitor.py:69`, `src/scheduler/watch.py:685`; `reconcile_live_trades` is called from `src/cli/commands.py:405`. Threading `desk` through these call paths is required before any research strategy goes `shadow_trading` active — otherwise reconcile will poll the swing account for positions that live on the research account, silently 404, and may attempt to close research positions via the wrong client.
- **Call-site map (Pass 2 verified):** 12 internal calls inside `src/shadow_trading/alpaca_adapter.py` (all use `_get_trading_client()` or `_get_data_client()` helpers, lines 163, 184, 222, 277, 321, 340, 369, 390, 408, 440, 463, 485). External callers: `src/shadow_trading/executor.py:697`, `src/shadow_trading/reconcile.py` (active), `src/shadow_trading/bracket_monitor.py`, `src/services/shadow_service.py`. **The correct patch strategy:** modify `_get_trading_client` and `_get_data_client` to accept optional `desk` kwarg defaulting to the current swing-config behavior; then thread `desk` through the 4 external call sites. One helper change covers 12 call sites.

**[STUB-OK]:** If time pressure hits Task 7, ship the interface + one happy-path integration test, defer full reconcile/bracket_monitor integration to v0.24.1. Document the gap clearly in code comments.

**Tests:**
- `test_harness_opens_position_via_research_client`
- `test_harness_writes_shadow_trade_with_correct_desk`
- `test_harness_reconcile_uses_research_client` (CRITICAL per skeptical review)
- `test_harness_bracket_monitor_uses_research_client` (CRITICAL per skeptical review)
- `test_harness_halt_closes_only_this_strategy`

---

#### Task 8 — Schema: add desk tag to shadow_trades (1h)

**File:** `src/schema/registry.py` (EDIT)

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

**Migration behavior:** `ensure_columns` runs on every watch-loop startup (`src/schema/sqlite.py:112`). On first run after this schema change, it will ALTER TABLE to add the three new columns. All 85 existing `shadow_trades` rows get `desk='swing'` via the DEFAULT clause. `research_thesis` and `strategy_spec_hash` stay NULL on existing rows (acceptable — they only apply to research trades).

**Tests** (`tests/test_schema_desk_columns.py`):
- `test_shadow_trades_has_desk_column`
- `test_shadow_trades_has_research_thesis_column`
- `test_shadow_trades_has_strategy_spec_hash_column`
- `test_existing_rows_backfill_desk_to_swing` — create SQLite DB without desk column, insert 3 rows, run `ensure_columns`, verify all 3 now have `desk='swing'`
- `test_desk_index_present`

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

#### Task 10 — Strategy registry + promotion states + trials_registry (3h, was 2h)

**Files:**
- `src/schema/registry.py` (EDIT — add 3 tables: strategy_registry, strategy_promotion_events, trials_registry)
- `src/platform/promotion.py` (new)

**Authority for gate thresholds:** `docs/research/deep-research/backtest-rigor-retrofit-plan.pdf`. Current `excess_sharpe ≥ 0.5` is replaced by `DSR ≥ 0.95 confidence`; the honest raw-Sharpe equivalent is 1.0-1.3 annualized for 30 serial strategies.

**Schema (3 tables):**

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
        ColumnDef("expected_factor_profile_json", "TEXT",
                  description="Per-strategy declared expected factor loadings "
                              "(e.g., {'UMD': [0.2, 0.6], 'MKT': [0.3, 0.7]}) — "
                              "used by correlation-monitor to flag style drift. "
                              "Deep research correlation report §'Factor "
                              "decomposition' second rule."),
        ColumnDef("survivorship_haircut_bps", "INTEGER",
                  description="Haircut applied to annualized returns: 75 for "
                              "short-hold, 200 for momentum, 100 otherwise."),
        ColumnDef("created_at", "TEXT", nullable=False),
        ColumnDef("last_status_change", "TEXT", nullable=False),
        ColumnDef("notes", "TEXT"),
    ],
    primary_key="strategy_id",
    sync_to_postgres=True,
    sync_mode="full",
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
        ColumnDef("gate_result_json", "TEXT"),
        ColumnDef("justification_note", "TEXT"),             # required for manual
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

_register(TableDef(
    name="trials_registry",
    description="Global trials log for Deflated Sharpe N_eff counter. "
                "Every backtest ever run — including parameter sweeps — "
                "creates a row here. DSR reads cumulative N_eff from this table.",
    columns=[
        ColumnDef("trial_id", "TEXT", nullable=False),       # UUID
        ColumnDef("strategy_id", "TEXT", nullable=False),
        ColumnDef("spec_hash", "TEXT", nullable=False),
        ColumnDef("params_searched_json", "TEXT"),           # if a sweep, what params
        ColumnDef("n_params_searched", "INTEGER", default="1"),
        ColumnDef("sr_raw", "REAL"),
        ColumnDef("sr_ann", "REAL"),
        ColumnDef("n_trades", "INTEGER"),
        ColumnDef("skew", "REAL"),
        ColumnDef("kurt", "REAL"),
        ColumnDef("passed_dsr_gate", "INTEGER", default="0"),
        ColumnDef("created_at", "TEXT", nullable=False),
    ],
    primary_key="trial_id",
    indexes=[
        IndexDef("idx_trials_strategy_created", ["strategy_id", "created_at"]),
    ],
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="created_at",
))
```

**Promotion logic (DSR-based gates):**

```python
# src/platform/promotion.py

STATUSES = {"proposed", "backtested", "shadow_trading", "production", "deprecated"}

# DSR-based gates per deep research retrofit plan.
# Honest annualized-Sharpe hurdle at N=30 serial trials ≈ 1.0-1.3 raw.
PROMOTION_GATES = {
    ("proposed", "backtested"): {
        "min_backtest_runs": 1,
        "min_backtest_trades": 30,
        "min_dsr": 0.95,                # Bailey-López de Prado 2014
        "max_pbo": 0.50,                # CSCV — only if params were swept
        "min_oos_efficiency": 0.30,     # walk-forward — Pardo 2008
        "max_max_drawdown_pct": 0.20,
        "requires_survivorship_haircut_applied": True,
    },
    ("backtested", "shadow_trading"): {
        "manual_only": True,
        "requires_justification_note": True,      # ≥40 chars
    },
    ("shadow_trading", "production"): {
        "min_shadow_trades": 30,
        "min_dsr_shadow": 0.95,
        "min_shadow_duration_days": 60,
        "manual_confirmation": True,
        "requires_justification_note": True,
        "requires_24h_delay": True,     # two-step confirmation
    },
}

def check_promotion_gate(strategy_id: str, target_status: str,
                         db_path: str = DB_PATH) -> tuple[bool, dict]:
    """Check if strategy meets gate for target_status. Returns (passes, evidence).

    Evidence includes: dsr, pbo (if applicable), oos_efficiency, n_trades,
    max_dd, n_eff_used_for_dsr. All values appear in the promotion event
    log so historical gate decisions are reproducible.
    """

def promote(strategy_id: str, target_status: str,
            triggered_by: str = "manual",
            justification_note: str | None = None,
            db_path: str = DB_PATH) -> None:
    """Promote strategy. Logs to strategy_promotion_events. Raises on gate failure.

    `justification_note` is REQUIRED for manual promotions (W2 — decision
    fatigue mitigation). Must be ≥40 characters. Raises ValueError if
    triggered_by='manual' and justification_note is None/too-short.
    """

def demote(strategy_id: str, reason: str,
           db_path: str = DB_PATH) -> None:
    """Move strategy to 'deprecated'. Halts shadow trading AND closes open
    positions via the research Alpaca client (G6 — rollback story).

    `reason` is REQUIRED and must be ≥20 characters. Stored in
    strategy_promotion_events.gate_result_json as {'reason': '<text>'}.
    Raises ValueError if reason is absent or too short.

    See activation-guide.md 'Halting a Strategy' for full procedure:
    cancels brackets, submits market-close, waits for fills, flags any
    non-filling positions for manual review.
    """

def pause(strategy_id: str, db_path: str = DB_PATH) -> None:
    """Emergency halt — move strategy back to 'backtested' status.

    Differs from demote(): pause() does NOT close open positions. Use
    when a code bug is suspected and panic-closing based on the bug
    would be worse than holding. Ryan reviews positions manually.

    Use demote() for 'this strategy is done'; use pause() for
    'something looks wrong, let me investigate'.
    """

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
- `test_manual_promote_rejects_missing_justification` (W2 — justification required)
- `test_manual_promote_rejects_short_justification` (<40 chars fails)
- `test_auto_gate_promote_allows_missing_justification` (automatic promotions exempt)
- `test_demote_rejects_missing_reason` (<20 chars or None → ValueError)

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

#### Task 11b — Correlation & risk monitoring stack (6h)

**Authority:** `docs/research/deep-research/correlation-risk-monitoring-blueprint.pdf` (Longin-Solnik 2001; Ang-Chen 2002; Carhart 1997; Asness-Frazzini-Pedersen 2019; Ledoit-Wolf 2003; Truong-Oudre-Vayatis 2020).

**Why this task exists (was missing in Pass 1-3):** When 2+ strategies run concurrently in shadow/production, hidden factor overlap is the #1 risk. Two strategies with Pearson correlation 0.30 in calm periods can spike to 0.70+ in crises (Longin-Solnik 2001 tail correlation asymmetry). Pod shops (Millennium, Citadel, Point72) converged on remarkably consistent architectures because they've all learned this. Retail translation exists and runs in standard Python libraries.

**Files:**
- `src/platform/risk/__init__.py` (new)
- `src/platform/risk/correlation.py` (new — Spearman + Pearson + exceedance)
- `src/platform/risk/factor_decomp.py` (new — Carhart 4 + QMJ regression)
- `src/platform/risk/exposure_limits.py` (new — hard caps enforced pre-trade)
- `src/platform/risk/change_detection.py` (new — PELT via ruptures)
- `src/platform/risk/alerting.py` (new — tiered Telegram/dashboard alerts)
- `src/schema/registry.py` (EDIT — add 2 tables: `correlation_matrices`, `factor_loadings`)
- `tests/platform/risk/` (new test dir)

**11b.1 — Schema additions**

```python
_register(TableDef(
    name="correlation_matrices",
    description="Daily rolling strategy correlation snapshots. "
                "Stored long-form (one row per strategy pair per method per date).",
    columns=[
        ColumnDef("date", "TEXT", nullable=False),
        ColumnDef("method", "TEXT", nullable=False),        # 'pearson' | 'spearman' | 'neg_exceedance'
        ColumnDef("strategy_a", "TEXT", nullable=False),
        ColumnDef("strategy_b", "TEXT", nullable=False),
        ColumnDef("value", "REAL"),
        ColumnDef("window_days", "INTEGER", nullable=False),
        ColumnDef("n_observations", "INTEGER"),             # actual obs used (may be < window)
    ],
    primary_key="date, method, strategy_a, strategy_b, window_days",
    indexes=[
        IndexDef("idx_corr_date", ["date"]),
        IndexDef("idx_corr_pair", ["strategy_a", "strategy_b"]),
    ],
    sync_to_postgres=True, sync_mode="incremental", sync_time_column="date",
))

_register(TableDef(
    name="factor_loadings",
    description="Rolling factor regression results per strategy.",
    columns=[
        ColumnDef("date", "TEXT", nullable=False),
        ColumnDef("strategy_id", "TEXT", nullable=False),
        ColumnDef("factor", "TEXT", nullable=False),        # 'MKT' | 'SMB' | 'HML' | 'UMD' | 'QMJ' | 'alpha'
        ColumnDef("beta", "REAL"),
        ColumnDef("tstat_hac", "REAL"),                     # HAC standard error
        ColumnDef("r2", "REAL"),
        ColumnDef("window_days", "INTEGER", nullable=False),
        ColumnDef("n_observations", "INTEGER"),
    ],
    primary_key="date, strategy_id, factor, window_days",
    indexes=[
        IndexDef("idx_factor_strategy_date", ["strategy_id", "date"]),
    ],
    sync_to_postgres=True, sync_mode="incremental", sync_time_column="date",
))
```

**11b.2 — Correlation measurement stack (2h)**

```python
# src/platform/risk/correlation.py
"""Three-layer correlation measurement per Longin-Solnik 2001 / Ang-Chen 2002.

Called by: scheduler.watch (daily + weekly refresh), dashboard API
Owns tables: correlation_matrices
Tests: tests/platform/risk/test_correlation.py
"""

def compute_rolling_spearman(pnl_df: pd.DataFrame, window: int = 63) -> pd.DataFrame:
    """Primary monitor — robust to outliers (scipy.stats.spearmanr).
    Returns long-form DataFrame with (date, pair, value)."""

def compute_rolling_pearson(pnl_df: pd.DataFrame, window: int = 63) -> pd.DataFrame:
    """Secondary — compare to Spearman. Gap >0.15 = fat-tail driver flag."""

def compute_neg_exceedance_correlation(pnl_df: pd.DataFrame,
                                        window: int = 252,
                                        threshold_pct: float = 0.10) -> pd.DataFrame:
    """Longin-Solnik 2001 tail correlation. Filter both series to days
    where both returns lie below 10th percentile of their marginal,
    compute Pearson on filtered set. ~25 obs per pair at default settings —
    noisy but usable as comparative signal. Flag when neg > pos exceedance
    (asymmetric tail dependence)."""

def detect_correlation_regime_shifts(pnl_df: pd.DataFrame) -> list[dict]:
    """Emit WARN when rolling 30-day Spearman crosses 0.5 for 5+
    consecutive days (CUSUM-style persistence filter to reduce false
    positives). Returns list of {pair, breach_start, breach_end, value}."""
```

**11b.3 — Factor decomposition (2h)**

Use Carhart 4-factor (MKT + SMB + HML + UMD) + QMJ as baseline per deep research. Daily Ken French data via `pandas-datareader`, QMJ from AQR datasets.

```python
# src/platform/risk/factor_decomp.py
import pandas as pd
import statsmodels.api as sm
from pandas_datareader import data as pdr

def load_factor_data(start: str, end: str) -> pd.DataFrame:
    """Daily factors from Ken French + AQR QMJ.
    FF3 (Mkt-RF, SMB, HML, RF) + UMD (momentum) + QMJ (AQR).

    Cache to data/factor_data/{start}_{end}.parquet (similar pattern
    to simulation/cache.py for OHLCV).
    """
    ff = pdr.DataReader('F-F_Research_Data_5_Factors_2x3_daily',
                        'famafrench', start, end)[0] / 100
    mom = pdr.DataReader('F-F_Momentum_Factor_daily',
                         'famafrench', start, end)[0] / 100
    # QMJ: https://www.aqr.com/Insights/Datasets/Quality-Minus-Junk-Factors-Daily
    # Cache locally on first fetch — QMJ is not on pandas-datareader
    qmj = _load_qmj_from_aqr_csv(start, end)
    return ff.join(mom).join(qmj)

def decompose_strategy(
    trade_returns: pd.Series, factors: pd.DataFrame, window: int = 126
) -> dict:
    """Rolling Carhart+QMJ regression with Newey-West HAC standard errors.

    Returns dict:
      - full_regression: {alpha, MKT, SMB, HML, UMD, QMJ, r2, tstats}
      - rolling_betas: DataFrame indexed by date, columns per factor
      - alpha_tstat_hac: scalar — if |t|<2.0, strategy is factor exposure not alpha
    """
    df = pd.concat([trade_returns.rename('r'), factors], axis=1).dropna()
    df['xr'] = df['r'] - df['RF']
    X = sm.add_constant(df[['MKT', 'SMB', 'HML', 'UMD', 'QMJ']])
    full = sm.OLS(df['xr'], X).fit(cov_type='HAC', cov_kwds={'maxlags': 5})
    # rolling window loop...
    return {...}

def compare_to_expected_profile(
    strategy_id: str, realized_betas: dict,
    expected_profile: dict, db_path: str,
) -> list[dict]:
    """Per deep research: every strategy publishes expected factor profile
    before going live (strategy_registry.expected_factor_profile_json).
    Flag any realized beta outside declared range. This catches
    implementation bugs that P&L alone won't reveal."""
```

**11b.4 — Hard exposure limits (1h)**

Pre-trade enforcement — hooks into both swing executor and research shadow harness.

```python
# src/platform/risk/exposure_limits.py
"""Hard exposure limits enforced pre-trade. NEVER overridden during drawdown.

Based on Millennium/Citadel architecture translated to retail scale:
  - Single-name: 6% of NAV (aggregate across strategies, ticker is unit of risk)
  - GICS sector: 25% of NAV (aggregate)
  - Gross leverage: 1.5x
  - Book drawdown circuit breaker: 8% from high-water mark

Soft limits (trigger review, not auto-halt): cross-strategy 63-day Spearman
>0.5 sustained 5 days; factor beta on any single factor >0.5 aggregated
across all strategies; 21-day book vol >150% of 252-day average.
"""

HARD_LIMITS = {
    "max_single_name_pct_of_nav": 0.06,
    "max_sector_pct_of_nav": 0.25,
    "max_gross_leverage": 1.5,
    "book_drawdown_circuit_breaker_pct": 0.08,  # from high-water mark
}

SOFT_LIMITS = {
    "max_pair_spearman_63d": 0.50,
    "max_pair_spearman_persistence_days": 5,
    "max_aggregate_factor_beta": 0.50,
    "max_vol_ratio_21d_vs_252d": 1.50,
}

def check_pre_trade_limits(
    ticker: str, proposed_shares: int, proposed_price: float,
    current_positions: list[dict], current_nav: float, db_path: str,
) -> tuple[bool, str]:
    """Pre-trade hard-limit check. Returns (allowed, reason_if_blocked)."""

def check_book_drawdown_circuit_breaker(db_path: str) -> tuple[bool, float]:
    """Returns (within_limits, drawdown_pct). If drawdown exceeds
    threshold, ALL new entries blocked until manual reset (no auto-reset —
    requires human decision)."""

def get_soft_limit_breaches(db_path: str) -> list[dict]:
    """Returns list of active soft-limit breaches for dashboard display.
    Does NOT block trades — advisory only."""
```

**11b.5 — Change-point detection (0.5h)**

```python
# src/platform/risk/change_detection.py
"""PELT change-point detection on factor betas per Truong-Oudre-Vayatis 2020."""
import ruptures as rpt

def detect_beta_regime_changes(
    beta_series: pd.Series, penalty_multiplier: float = 3.0,
) -> list[int]:
    """RBF kernel PELT on rolling beta time series. Emit WARN on detected
    breakpoints (style drift / regime change in factor exposure).

    Calibrate penalty empirically: pen = penalty_multiplier * sigma^2 * log(n).
    Typical: run weekly on each strategy/factor pair. BOCPD deferred to
    v0.25+ if intraday monitoring ever added."""
    sigma = beta_series.std()
    n = len(beta_series)
    pen = penalty_multiplier * sigma**2 * np.log(n)
    algo = rpt.Pelt(model="rbf").fit(beta_series.values)
    return algo.predict(pen=pen)
```

**11b.6 — Tiered alerting (0.5h)**

```python
# src/platform/risk/alerting.py
"""Tiered alert system per deep research — avoids alert fatigue.

INFO: daily digest at market close. No Telegram push.
WARN: Telegram, business hours only (9:30-16:00 ET).
CRITICAL: Telegram with retry, 24/7.

Deduplication: hash alert content, suppress if same hash in last 60 min.
Snooze: Telegram bot accepts /snooze <alert_type> <duration>.
"""

ALERT_TIERS = {
    "INFO": {"channels": ["dashboard_digest"]},
    "WARN": {"channels": ["telegram"], "business_hours_only": True},
    "CRITICAL": {"channels": ["telegram_retry"], "business_hours_only": False},
}

def emit_alert(tier: str, category: str, message: str, context: dict) -> None:
    """Emit tiered alert. Deduplicates via hash(category + context)."""
```

**Tests (minimum 15):**
- `test_spearman_matches_scipy_on_known_inputs`
- `test_pearson_spearman_divergence_flags_fat_tails`
- `test_neg_exceedance_correlation_longin_solnik_symmetry`
- `test_correlation_persistence_filter_requires_5_days`
- `test_factor_decomposition_carhart_4_factor_matches_statsmodels`
- `test_factor_alpha_tstat_hac_flags_nonalpha_strategy`
- `test_factor_expected_profile_comparison_flags_drift`
- `test_hard_limit_blocks_single_name_over_6pct`
- `test_hard_limit_blocks_sector_over_25pct`
- `test_drawdown_circuit_breaker_blocks_all_entries`
- `test_soft_limit_correlation_breach_returned_not_blocked`
- `test_pelt_detects_known_breakpoint`
- `test_alert_deduplicates_within_60min_window`
- `test_alert_tier_warn_respects_business_hours`
- `test_alert_tier_critical_fires_24_7`

**Acceptance:**
- Spearman/Pearson/exceedance all computed correctly on synthetic data with known correlations
- Factor decomposition on SPY (should load 1.0 on MKT, ~0 elsewhere) validates the regression
- Hard limits enforced — write a test that attempts a 7% single-name position, assert it's rejected
- PELT detects a known synthetic regime break at the right index
- Alert dedup suppresses second identical alert within 60 min

**[STUB-OK caveat]:** If time-pressed, ship 11b.1 + 11b.2 + 11b.4 (schema + correlation + hard limits) as minimum. Factor decomp + PELT + alerting defer to v0.24.1 since they only matter once 2+ strategies run concurrently (≥ weeks away).

---

#### Task 12 — Dashboard: full platform integration (7h)

**Scope expanded (was 3h [STUB-OK]).** Covers five layers of dashboard-platform integration identified during Pass 3 review: dedicated platform page, defensive desk filtering on existing pages, action buttons for manual promotion gates, main dashboard widget, and Telegram wiring for platform events.

**Files (new):**
- `frontend/src/pages/StrategyResearch.jsx` — dedicated platform page
- `frontend/src/components/PlatformStatusWidget.jsx` — home-screen widget
- `src/api/cloud_routes/platform.py` — API surface
- `src/notifications/platform_events.py` — Telegram event wiring

**Files (edit — defensive integrations):**
- `frontend/src/pages/Dashboard.jsx` — add desk filter to all aggregate widgets
- `src/api/cloud_routes/trades.py` — accept `?desk=` query param on `/api/shadow/sharpe-attribution`, `/api/shadow/open`, `/api/shadow/closed`, `/api/shadow/metrics`, `/api/shadow/account` (Pass 2 verified all shadow endpoints live in `trades.py`, NOT a separate `shadow.py` — there is no `shadow.py` in cloud_routes)
- `frontend/src/App.jsx` — register new `/research-platform` route
- `frontend/src/components/Nav.jsx` — add Research Platform link

---

**12a — Dedicated /research-platform page (3h)**

Four sections, fully interactive (not stubbed):

1. **Strategy Registry table** — rows per strategy with columns: name, status, current spec version, last backtest date, last backtest excess-Sharpe, shadow trades count, actions. Clicking a row expands to the detail view.
2. **Strategy Detail (expandable row)** — YAML spec contents, backtest history grid, shadow-trading status, promotion events timeline, manual action buttons.
3. **Backtest Results grid** — sortable by date/strategy/excess-Sharpe/DD. Row click opens equity curve modal. **Pass 2 verification:** `EquityCurveChart.jsx` does NOT exist in `frontend/src/components/`. Build a new `BacktestEquityChart.jsx` that uses Recharts' `LineChart` / `Area` primitives (same pattern as existing `Attribution.jsx`, `Council.jsx`, `Dashboard.jsx` which all import Recharts directly into pages). Shared `MetricTrend.jsx` component in `frontend/src/components/` can be studied for the chart styling pattern.
4. **Promotion Events log** — last 50 events, filterable by strategy, color-coded by action type (promote=green, demote=red, gate-fail=yellow).

**API endpoints** (in `src/api/cloud_routes/platform.py`):
- `GET /api/platform/strategies` → list with embedded latest backtest summary
- `GET /api/platform/strategies/{id}` → full detail including YAML spec
- `GET /api/platform/backtest-results?strategy_id=...&limit=20` → historical runs
- `GET /api/platform/backtest-trades?result_id=...` → individual trades for equity curve
- `GET /api/platform/promotion-events?strategy_id=...&limit=50` → recent events

---

**12b — Manual action buttons (1.5h)**

The six manual touchpoints (M1–M6 from the lifecycle diagram) each get a dashboard surface where reasonable:

| Action | Surface | Confirmation |
|---|---|---|
| M1 Write spec | File editor (stays in code) | — |
| M2 Trigger backtest | Button on Strategy Detail: "Run Backtest" | Date-range modal |
| M3 Revise rejected | File editor (stays in code) | — |
| M4 Approve to shadow | Button: "Promote to Shadow Trading" | Modal showing gate evidence + typed confirmation + **required justification note** |
| M5 Demote | Button: "Halt & Demote" | Typed confirmation of strategy_id + **required reason text** |
| M6 Promote to production | Button: "Promote to Production" | Two-step: typed confirmation + date-delayed (24h wait period) + **required justification note** |

**Decision fatigue mitigation (W2 finding):** M4 and M6 each require a free-text justification note that gets stored in `strategy_promotion_events.gate_result_json` (already a JSON column). This makes rubber-stamping physically uncomfortable — Ryan has to type *why* each approval is happening. After 10-20 promotions accumulated over time, the notes become their own dataset: patterns in what Ryan approves vs. rejects can inform future gate-threshold calibration. Minimum length: 40 characters (enforced server-side).

**API endpoints** for actions:
- `POST /api/platform/backtests` — `{strategy_id, start_date, end_date}` → kicks off async backtest, returns `result_id`
- `POST /api/platform/promotions` — `{strategy_id, target_status, confirmation_token, justification_note}` → calls `promote()` from Task 10. Rejects if `justification_note` is absent or <40 chars.
- `POST /api/platform/demotions` — `{strategy_id, reason}` → calls `demote()`. Rejects if `reason` is absent or <20 chars.

Backtest kickoff is asynchronous (runs in a background task). Page polls `/api/platform/backtest-results` to detect completion. For MVP, the async runner is a subprocess — no Celery, no job queue.

---

**12c — Defensive desk filtering on existing pages (1h)**

Prevents research P&L from silently contaminating swing metrics.

- **Dashboard.jsx:** add a `deskFilter` dropdown (default: `"swing"` only) above all aggregate widgets. All queries for P&L, win rate, equity curve, excess-Sharpe accept a `?desk=` param.
- **`src/api/cloud_routes/trades.py`:** accept optional `?desk=` query param on every `/api/shadow/*` endpoint listed in the Files section above. Default behavior when param absent: return `swing` only (backward-compat — the endpoints were built for swing evaluation). Note: there is no `/api/shadow/status` endpoint in the current codebase; Pass 2 grep confirmed the live endpoints are `/api/shadow/open`, `/api/shadow/closed`, `/api/shadow/sharpe-attribution`, `/api/shadow/metrics`, `/api/shadow/account`.
- **`TradeHistory.jsx`:** confirm the desk filter dropdown lists all distinct `desk` values currently present in `shadow_trades` (query at render time), not a hardcoded list. The abandoned MVP spec's Task 10 added a basic desk dropdown; that work has not shipped, so CC builds the dropdown fresh.

**Semantics decision:** `desk=all` sums across desks; `desk=swing` filters to swing only; `desk=research_*` wildcards all research strategies; `desk=research_lazy_prices_v1` filters to one strategy. Server-side SQL uses `WHERE desk = ?` or `WHERE desk LIKE ?` depending on wildcard presence.

---

**12d — Home-screen platform status widget (1h)**

A compact card on the main dashboard showing:
- Strategies in each status (count with color badge)
- Number awaiting manual review ("1 strategy ready for shadow approval →")
- Last backtest completion timestamp
- Link to the full `/research-platform` page

Fits in the existing dashboard's card grid. Only renders if at least one strategy exists in `strategy_registry`.

---

**12e — Telegram notification wiring (0.5h)**

In `src/notifications/platform_events.py` (new):

```python
def notify_backtest_complete(strategy_id, result_id, passed_gate_a: bool): ...
def notify_shadow_gate_ready(strategy_id, evidence: dict): ...
def notify_strategy_promoted(strategy_id, from_status, to_status): ...
def notify_strategy_demoted(strategy_id, reason): ...
```

Called from:
- `src/platform/backtest_engine.py::run_backtest` on completion
- `src/platform/promotion.py::check_promotion_gate` when a new gate is first satisfied (once per gate, not per check)
- `src/platform/promotion.py::promote` and `::demote`

Prefix all platform-event Telegram notifications with `[RESEARCH]` (same convention as existing trade notifications — see `src/notifications/telegram.py`).

---

**Tests (minimum 8):**
- `test_platform_strategies_endpoint_returns_registry_rows`
- `test_platform_backtest_trigger_endpoint_runs_async`
- `test_platform_promotion_endpoint_requires_confirmation_token`
- `test_sharpe_attribution_desk_filter_swing_only`
- `test_sharpe_attribution_desk_filter_all_sums_desks`
- `test_dashboard_widget_renders_zero_strategies_gracefully`
- `test_telegram_backtest_complete_fires_once`
- `test_telegram_gate_ready_not_duplicate_fired` (idempotent — don't spam on re-check)

**Acceptance:**
- `npm run build` passes
- Visit `/research-platform` → see strategy list (empty if no strategies yet)
- Home dashboard renders platform widget correctly with zero strategies
- Existing `/trades` history and main `/` dashboard still work with pre-existing 85 swing trades
- SQL: running `SELECT * FROM shadow_trades WHERE desk != 'swing'` returns zero rows at merge time (platform inert)

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
   `python -m src.platform.promotion promote <id> shadow_trading --justification "..."`
5. Watch loop picks up the new strategy on next platform tick
6. Monitor via dashboard's Strategy Research page

## Gates

- Proposed → Backtested: automatic on first successful backtest meeting thresholds
- Backtested → Shadow: manual (Ryan confirms with ≥40-char justification note)
- Shadow → Production: manual + all statistical gates met + ≥40-char justification

## Halting a Strategy (Demotion)

`python -m src.platform.promotion demote <id> --reason "..."`

(Reason must be ≥20 chars.)

### What demote() does — complete rollback procedure

1. Sets `strategy_registry.current_status = 'deprecated'` for the strategy_id.
2. Writes append-only row to `strategy_promotion_events` with `to_status='deprecated'`
   and the reason text.
3. Queries open positions: `SELECT * FROM shadow_trades WHERE desk = 'research_<id>'
   AND actual_exit_time IS NULL`.
4. For each open position:
   a. Retrieves the research-desk Alpaca client via
      `src.shadow_trading.alpaca_clients.get_client('research')`.
   b. Cancels any outstanding bracket orders (stop/target) for the ticker
      via the research client.
   c. Submits a market-close order via the research client.
   d. Waits up to 30 seconds for the fill notification.
   e. On fill: updates `shadow_trades.actual_exit_time`, `actual_exit_price`,
      computes `pnl_pct` / `pnl_dollars` / `excess_return` / `spy_return_over_hold`,
      and sets `exit_reason = 'strategy_demoted'`.
   f. On timeout: flags the row with `exit_reason = 'strategy_demoted_manual_close_required'`
      and fires a Telegram alert. Ryan manually closes via the Alpaca web UI.
5. Removes the strategy from the watch loop's `_last_platform_tick` dict
   (prevents the now-demoted strategy from being ticked on the next cycle).
6. Sends Telegram notification: `[RESEARCH] Strategy <id> demoted. Reason: <text>.
   N positions closed, M flagged for manual review.`

### Rollback for mid-deployment bugs (emergency — not a normal demotion)

If a strategy is producing bad trades due to a code bug (not a statistical
underperformance), and you want to halt WITHOUT marking the strategy as
deprecated:

`python -m src.platform.promotion pause <id>`

This sets `current_status` back to `'backtested'`. The watch loop stops
ticking the strategy, but open positions are LEFT OPEN (to avoid
panic-closing based on a code bug that might be wrong). Ryan must then
manually review positions and decide to close or hold via the Alpaca UI.

Use `pause` for "something looks wrong, let me investigate" and `demote`
for "this strategy is definitively done."
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
7. Strategy Research dashboard page renders without console errors (full content if Tier 6 shipped; skeleton strategy list if only defensive integration shipped)

---

## Honest Task Priority

If the weekend runs short, ship tasks in this order:

**Tier 1 — foundation with rigor (must ship, ~14h):** T1 (spec schema), T3 (data loader), T4 (backtest engine), T5a+5b (metrics + DSR — MANDATORY, DSR is the promotion gate), T6 (persistence). The DSR paper-example test passing is the quality bar that decides whether Tier 1 is trustworthy.

**Tier 2 — evaluate a real strategy (~6-9h):** T11 (Lazy Prices spec, 3h), Task 0 (EDGAR fix, 3-6h — concurrent with above where possible).

**Tier 3 — rigor completion + platform lifecycle (~8h):** T5c (CSCV, 1h), T5d (walk-forward, 1h), T8 (schema additions, 1h), T10 (promotion pipeline with trials_registry, 3h), survivorship haircut plumbing (~1h).

**Tier 4 — defensive dashboard integration + minimal risk monitoring (~4h):** T12c (desk filtering — non-negotiable before any research strategy goes active, 1h). T11b.1 + T11b.4 (correlation schema + hard exposure limits, 3h). Hard caps must exist in code before any second strategy reaches `shadow_trading` status.

**Tier 5 — live deployment (~8h):** T7 (shadow harness, 5h), T9 (watch loop integration, 2h), cost calibration from 85 swing trades (1h — O1).

**Tier 6 — dashboard platform surfaces (~6h):** T12a (dedicated /research-platform page), T12b (action buttons), T12d (home widget), T12e (Telegram events)

**Tier 7 — full risk monitoring (~3h):** T11b.2/3/5/6 (factor decomposition, change detection, alerting — less urgent because only relevant after 2+ strategies run concurrently).

**Tier 8 — nice-to-haves (~3h):** T2 (Python plugin), T13 (docs)

**Total effort:** 50-72h realistic. Pass 3 reuse audit saved ~8h off the Pass 1 estimate; Task 12 expansion added ~4h; rigor retrofit (Task 5 expansion + Task 11b) added ~12h.

**If Tier 1+2 ship:** Backtest harness with DSR gate exists, Lazy Prices has a validated backtest, everything else is v0.24.1. Minimum-viable rigorous outcome.
**If Tier 1+2+3 ship:** Full rigor stack (DSR + CSCV + walk-forward + survivorship haircut) + promotion pipeline.
**If Tier 1+2+3+4 ship:** Platform has full lifecycle AND defensive dashboard integration AND hard exposure limits — safe to enable research strategies without contaminating swing metrics.
**If Tier 1+2+3+4+5 ship:** Live shadow trading. Full target scope.
**If all 8 ship:** Ambitious plan achieved with full dashboard UX and correlation monitoring.

**Critical sequencing notes (hard gates, not preferences):**
1. Task 5b (DSR) must land before ANY backtest result is trusted. The `excess_sharpe ≥ 0.5` gate is known too loose by ~2× per deep research.
2. Tier 4 defensive dashboard filtering must land BEFORE any `desks.research.enabled: true` flip. Otherwise main dashboard numbers silently lie.
3. Hard exposure limits (T11b.4) must land BEFORE any second strategy reaches `shadow_trading`. Otherwise unconstrained aggregate exposure risk.

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
- Any second-Alpaca-account work deferred from abandoned MVP spec (the shadow harness uses the research Alpaca account, but the 12-call-site fix — see Task 7 — lands in Tier 5, alongside the shadow harness itself)

---

## Risk Mitigations

| Risk | Mitigation |
|---|---|
| Backtest engine has a silent bug | Hand-computed validation test (Task 4). Non-negotiable. |
| EDGAR data still broken at merge time | Task 0 runs independently. Platform ships regardless; Lazy Prices just returns 0 candidates with clear warning. |
| Weekend time pressure kills Tier 5-7 | Tier-based success criteria. Tier 1+2+3+4 ship as v0.24.0-infra; live deployment (Tier 5) + dashboard surfaces (Tier 6) + nice-to-haves (Tier 7) defer to v0.24.1. |
| Shadow harness misroutes trades to swing account | Per-desk Alpaca client factory with `verify_accounts_distinct` assertion. 12-call-site fix via modifying the two `_get_trading_client` / `_get_data_client` helpers — see Task 7 for the exact patch strategy. |
| reconcile.py polls swing account for research positions | Task 7 threads desk through `reconcile_paper_trades` and `reconcile_live_trades` call paths. Must land before any `shadow_trading` activation. |
| Strategy spec format changes require schema migrations | `spec_version: 1` field in YAML. Future breaking changes bump version; loader checks. |
| New tables break render_sync | All new tables declared with proper `sync_to_postgres=True` + mode. `ensure_columns` runs every sync cycle. |
| Lazy Prices backtest produces overly-optimistic results | Deflated Sharpe computation (Task 5) discounts for multiple-testing. Reporting includes both raw and deflated. |
| Dashboard conflates swing + research P&L after activation | Tier 4 (Task 12c) defensive desk filtering lands BEFORE any strategy reaches `shadow_trading` status. Hard gate per "Critical sequencing note". |

---

## CI Requirements

- All existing guardrail tests must continue to pass (`pytest tests/ -x`)
- `tests/test_project_layout.py` (file-size guardrails, if present) — no new src/ file >400 lines, no function >60 lines
- `cd frontend && npm run build` must succeed
- `scripts/verify_docs.py` (if present) — CHANGELOG, RELEASES, README badges updated
- `scripts/daily_repo_audit.py` — no new audit findings introduced by this sprint

**Platform-specific tests that must pass on green:**
- `tests/platform/test_backtest_validation.py::test_backtest_matches_hand_computed_example_scheduled` — scheduled-kind code path
- `tests/platform/test_backtest_validation.py::test_backtest_matches_hand_computed_example_event_driven` — event-driven code path (separate validation; a bug here affects Lazy Prices)
- If either fails, the backtest engine is not trustworthy and nothing else in this sprint is salvageable
- `tests/test_schema_desk_columns.py::test_existing_rows_backfill_desk_to_swing` — if this fails, the 85 historical swing trades lose their desk attribution

---

*Ralph-looped three times against live repo state (2026-04-17): Pass 1 found 29 inconsistencies, Pass 2 grep-verified 15 claims against the actual codebase (catching the nonexistent `EquityCurveChart.jsx`, the wrong endpoint file `shadow.py`, reconcile.py active status, and the missing `load_spec(strategy_id)` helper), Pass 3 applied all corrections. Spec is ready for CC execution. Remaining uncertainties are data-dependent (Task 0 EDGAR fix feasibility) and tier-feasibility-dependent (40-60h compressed into a weekend).*
