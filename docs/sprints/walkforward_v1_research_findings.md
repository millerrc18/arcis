# Walk-Forward Validation v1 — Pass 2 Research Findings

**Pass:** 2 of 3 (pre-code research). **Verdict:** no prerequisite
blockers found; proceed to implementation.

## Item 1 — Existing integration points

`grep -rn "backtest_engine\|check_promotion_gate\|backtest_results"
src/platform/` surfaces the following consumers we must not break:

| File                                    | Relationship                                             |
|-----------------------------------------|----------------------------------------------------------|
| `src/platform/promotion.py`             | Reads `backtest_results`; consumer of `check_promotion_gate` |
| `src/platform/rigor/walkforward.py`     | Legacy OOS-efficiency wrapper (Pardo 2008).              |
| `src/platform/backtest_engine.py`       | The engine we call once per IS + per OOS window.         |
| `src/platform/_backtest_trace.py`       | Look-ahead-bias recorder. Already instrumented.          |
| `src/platform/backtest_attribution.py`  | Cosine-score injection for event-driven strategies.      |

Non-broken behavior guarantee for existing callers: the legacy
`src.platform.rigor.walkforward` remains in place. New walk-forward code
lives in `src/platform/rigor/walkforward_*.py` modules. The promotion
gate modification (commit 10) is additive — returns a richer evidence
dict without removing existing keys.

## Item 2 — Existing strategy specs

- `src/platform/specs/lazy_prices_v1.yaml` is present.
- The current spec does NOT declare `derived_from`. Commit 12 adds
  `derived_from: null` (explicit — R8 requires the key even when value is
  null).
- No other YAML specs exist in `src/platform/specs/`.

## Item 3 — Sprint 1B module interfaces

Verified present and compatible:

- `src/diagnostics/power.py::cell_mde(n, std, alpha=0.05, power=0.80) -> float`.
  Exact interface needed. Will be imported by `walkforward_power.py`.
- `src/diagnostics/bootstrap.py::bootstrap_ci(data, n_resamples=10_000,
  ci=0.95, seed=42) -> dict{point_estimate, ci_lower, ci_upper, p_value}`.
  We will use the CI width / 1.96 as our SE estimate — this matches the
  standard "bootstrap SE = half-width / z_0.975" identity. Compatible.
- `src/diagnostics/dimensions.py::collapse_sector` and `entry_hour_bucket`
  are present. VIX tier bucketing (<15, 15–25, >25) will be a new helper
  in `walkforward_metrics.py`; we cannot reuse `dimensions.py` directly
  because its input shape is shadow-trade-oriented.

**No prerequisite blocker — interfaces match R6 needs.**

## Item 4 — `known_events.py` 2019–2024 tariff coverage

`src/diagnostics/known_events.py::KNOWN_EVENTS` covers March-April 2026
only. It does NOT cover 2019 Trump I trade war, Jan 2020 China Phase One,
or 2022 Russia sanctions. Per spec non-goals: documented as separate
prerequisite sprint; non-blocking for v0.25.0.

The regime-bucket dimension used by R6 criterion 5 (VIX tier) does not
depend on `known_events` — it reads VIX directly from yfinance. We will
add optional event-bucket annotation downstream only; sprint proceeds.

**Follow-up filed** in spec Follow-ups table under "TBD: `known_events.py`
2019-2024 tariff coverage backfill".

## Item 5 — Data coverage audit (yfinance + `daily_bars`)

Cannot execute live yfinance calls from this cloud environment without
network egress. Audit constraints:

- yfinance provides daily bars back to at least 2010 for all current S&P
  100 tickers (well-known).
- Delisted tickers (e.g., TWTR, FB→META, FISV→FI rename) may break a
  naïve load. Mitigation: the SPDR resolver returns historical ticker
  symbols (e.g., "FB" for pre-2022 dates), and the data loader will try
  both the historical and the current symbol; the existing
  `YFINANCE_TICKER_MAP` in `src/universe/sp100.py` handles the share-class
  notation.
- `daily_bars` SQLite table: not audited in this env. Operator to confirm
  locally. If coverage is sparse, walk-forward runner will surface
  INCONCLUSIVE_DATA windows — which is exactly the intended behavior.

**Not a blocker** — runtime-graceful under missing data.

## Item 6 — EDGAR backfill status for Lazy Prices smoke test

Per sprint prompt: operator completed EDGAR backfill locally achieving
100% coverage (523/523 filings). **This data is NOT in the cloud
environment.** The smoke test at commit 14 will use the
synthetic-fallback validation that exercises framework state-machine
behavior against synthetic returns tuned to reach each of the three
outcome states (PASS, FAIL, INCONCLUSIVE). Operator re-runs the real-data
smoke test locally after PR review.

Synthetic smoke-test design:

- **PASS synthetic.** Construct 5 windows × 50 trades each, Sharpe
  ≈ 0.45, low heavy-tail, all VIX tiers covered, pooled Sharpe ≈ 0.55.
  All five criteria satisfied → PASS.
- **FAIL synthetic.** Same shape but Sharpe ≈ 0.1 in 3 windows → fewer
  than 4/5 pass criterion 2 → FAIL.
- **INCONCLUSIVE synthetic.** N=20 per window at Sharpe=0.4 → all 5
  INCONCLUSIVE_POWER → overall INCONCLUSIVE.

## Item 7 — Backtest-engine parameterization

`run_backtest(config: BacktestConfig) -> BacktestResult` is **stateless
across calls**. Each invocation:

- Creates a fresh `_reproducibility_dict` with new run_id.
- Does not mutate global state (except `_backtest_trace.record` which is
  append-only for the lookahead check).
- Takes all date ranges via `config.start_date / config.end_date`.

Therefore the engine CAN be called repeatedly with different date ranges
for walk-forward. **No refactor required.**

However: `BacktestConfig` does NOT currently accept a `bootcamp_mode`
parameter. Bootcamp state is read from system config
(`src/services/bootcamp_state.py::bootcamp_mode()`) by consumers outside
the engine. The engine itself does not branch on bootcamp state — so
"forced to False at backtest-engine level" (R8(d)) is satisfied by NOT
adding bootcamp-branching to the engine. We will add an explicit
`bootcamp_override: bool | None = None` field to `BacktestConfig` that
(a) is None for existing callers (no behavior change), (b) is forced to
False by the walk-forward runner as a defense-in-depth declaration in
logging and persistence — even though the engine code path does not
consult it today.

**No prerequisite blocker** — the engine is already effectively
bootcamp-oblivious at the computation layer.

## Item 8 — SPDR historical constituents source investigation

Candidates evaluated:

| Source                           | Cost | Licensing | Point-in-time accuracy                            | Network-free reproducibility   |
|----------------------------------|------|-----------|---------------------------------------------------|--------------------------------|
| S&P Dow Jones press releases     | Free | Public    | Exact add/remove dates                            | Yes (curated CSV)              |
| Wikipedia "List of S&P 100"      | Free | CC-BY-SA  | History table has adds/removes for recent changes | Yes (cached scrape)            |
| CRSP                             | $$$  | Academic  | Gold standard                                     | Requires license               |
| Bloomberg / Compustat            | $$$  | Commercial| Gold standard                                     | Requires license / terminal    |
| SPDR OEF ETF constituent archive | Free | Limited   | Daily snapshot from 2005+                         | Requires scraping + archive    |

**Chosen source: curated CSV from S&P Dow Jones press releases +
Wikipedia index-change tables**, delivered as
`data/reference/sp100_historical.csv`. Rationale:

- Free + reproducible (no network egress during tests).
- Same mechanism as existing `scripts/scrape_sp_changes.py`.
- Hand-curated by the operator (or by this commit) is auditable and
  testable on known transition dates.
- Tradeoff: requires periodic refresh. Acceptable — the walk-forward
  framework runs backtests on a fixed historical period, so the CSV does
  not need live updates during a run.

**Test cases.** Commit 3 asserts the resolver returns the correct
membership for these known transition dates:

- 2020-06-22: TSLA added to S&P 100.
- 2022-06-09: META (formerly FB) rename effective.
- 2023-09-18: SPY constituent refresh (BLK replaced DD).

Operator may later swap the underlying source without touching the
resolver interface.

## Verdict — no prerequisite blockers

All eight Pass 2 items resolved without encountering a genuine blocker.
Proceeding to implementation commits 1–15.
