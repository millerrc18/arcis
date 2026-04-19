# Sprint: Walk-Forward Validation Framework v1

**Branch:** `feat/walkforward-validation-v1` (cloud execution branch: `claude/walkforward-validation-v1-IpQw2`)
**Target tag:** v0.25.0
**Owner:** Platform
**Status:** IN PROGRESS — Pass 3 redlines applied in this commit.

> **Pass 3 Redline Audit Trail:** This document reflects redlines 1–7 applied
> from the Ralph Loop Pass 1 / Pass 2 / Pass 3 artifacts produced on the
> operator's local machine. The Pass 1 and Pass 2 markdown artifacts will be
> committed to `docs/sprints/redline-history/` separately. Until those land,
> this file is the authoritative spec.

---

## Mission

Build the walk-forward validation framework that every future strategy must
pass before promotion to `shadow_trading` or real capital. The April 18
forensic audit demonstrated that a single backtest cannot distinguish alpha
from SPY beta at the trade counts we realistically obtain, and that
regime-averaged backtests hide failure modes that kill real capital. This
framework is the referee.

Three specific traps it closes:

1. **Regime-averaged false positives.** Strategy wins in 2021 bull, loses in
   2022 bear, nets out "OK" aggregate — single backtest passes, walk-forward
   catches it.
2. **Underpowered false positives.** Strategy shows Sharpe ≈ 0.4 on 30 trades —
   looks good, but SE is so large the measurement is statistical noise. The
   MDE gate (R6) catches it.
3. **Bootcamp-derivation circularity.** Rules discovered from analyzing
   specific trades, then "validated" on those same trades. The R8 firewall
   catches it.

---

## Scope

In addition to the core framework, this sprint pulls in three items originally
deferred to v0.25.1:

1. Dashboard `/walkforward-results` page.
2. SPDR historical-constituents integration (point-in-time S&P 100 2019-2023).
3. Runtime heuristic for suspicious `derived_from: null`.

Sprint is ~15 implementation commits plus four Ralph Loop ceremony commits
(19 total). This is above the ≤10-task guideline — load-bearing infrastructure
exception, operator-approved.

---

## Rigor requirements (R1–R8 — non-negotiable)

### R1 — Window design

Default walk-forward uses five non-overlapping OOS windows spanning
2019-01-01 through 2024-09-30:

| # | IS train window         | OOS test window         |
|---|-------------------------|-------------------------|
| 1 | 2017-01-01 → 2018-12-31 | 2019-01-01 → 2020-03-31 |
| 2 | 2018-01-01 → 2019-12-31 | 2020-04-01 → 2021-06-30 |
| 3 | 2019-01-01 → 2020-12-31 | 2021-07-01 → 2022-09-30 |
| 4 | 2020-01-01 → 2021-12-31 | 2022-10-01 → 2023-12-31 |
| 5 | 2021-01-01 → 2022-12-31 | 2024-01-01 → 2024-09-30 |

Each IS window is two calendar years; OOS windows are 15 months (last is
9 months to respect latest available data). Windows are parameterizable;
defaults above are the canonical v0.25.0 configuration.

### R2 — Purge and embargo

To prevent train/test leakage from overlapping hold periods and information
that straddles boundaries:

- **Purge.** Remove from the IS window any trade whose hold window overlaps
  the OOS boundary (entry before boundary, exit after).
- **Embargo.** Remove from the OOS window any trade whose entry falls within
  `embargo_days` of the boundary (default 5 trading days).

Both operate on the `entry_date` / `exit_date` of each trade; embargo runs
on OOS side only.

### R3 — No survivorship bias (point-in-time universe)

The universe at any OOS entry date must reflect S&P 100 membership *as of
that date*, not current membership. The `sp100_historical_constituents`
table is populated before the runner and queried via a point-in-time
resolver. See SPDR integration (commit 3).

### R4 — Transaction costs

Every trade is charged symmetric per-side transaction cost (0.5 bp entry +
0.5 bp exit; 1.0 bp round-trip). Costs apply to every reported metric —
no metric is gross-of-cost.

### R5 — Determinism

Given `(strategy_spec, data_cutoff, random_seed)`, a walk-forward run
produces identical results. Seed is propagated into config; spec hash is
recorded with each run.

### R6 — Three-state outcome + MDE gate [REDLINE 1]

Every walk-forward run produces one of three **outcome states**:

- **PASS** — all criteria satisfied.
- **FAIL** — at least one criterion failed AND statistical power was
  sufficient to detect failure.
- **INCONCLUSIVE** — too few trades to distinguish a true failure from noise,
  regardless of observed values.

#### Criteria

1. **Coverage.** Each window has ≥10 completed trades. If <10, that window
   is INCONCLUSIVE_DATA. ≥2 windows INCONCLUSIVE_DATA → overall INCONCLUSIVE.
2. **Individual windows.** ≥4 of 5 windows satisfy BOTH `Sharpe ≥ 0.3` AND
   `MDE ≤ 0.3`, computed at 80% power. The MDE uses Lo (2002):

   ```
   SE(Sharpe) = sqrt( (1 + 0.5 · Sharpe²) / N_effective )
   ```

   where `N_effective` is the Newey-West lag-adjusted count at
   `lag = max_holding_period`. If the bootstrap SE exceeds `1.5 × parametric_SE`,
   the return distribution is heavy-tailed and we substitute the bootstrap SE
   (10,000 resamples, `src/diagnostics/bootstrap.py`). Windows where MDE > 0.3
   at 80% power are marked INCONCLUSIVE_POWER rather than FAIL. ≥2 windows
   INCONCLUSIVE_POWER → overall INCONCLUSIVE.
3. **Pooled Sharpe.** Across all OOS trades pooled, Sharpe ≥ 0.5
   (with cost applied).
4. **Drawdown cap.** No individual window has max drawdown > 20%.
5. **Regime coverage.** Across the five OOS windows, at least 2 distinct
   VIX tier buckets are represented (low <15, medium 15–25, high >25).

#### Outcome state logic

```
if count(window.state == INCONCLUSIVE_DATA) >= 2:
    overall = INCONCLUSIVE(reason="coverage")
elif count(window.state == INCONCLUSIVE_POWER) >= 2:
    overall = INCONCLUSIVE(reason="power")
elif any criterion 1–5 fails:
    overall = FAIL(reason=...)
else:
    overall = PASS
```

`check_promotion_gate` returns a **structured result** — not boolean —
with `outcome_state` and `reason` fields. See commit 10.

### R7 — Deterministic spec / hash / seed recording

Every run writes the strategy spec hash, code git SHA, data cutoff, and
random seed into `walkforward_results`. Re-running with identical inputs
must produce byte-identical metrics (modulo timestamp columns).

### R8 — Strategy identity firewall and bootcamp provenance [REDLINE 2]

Walk-forward is only valid when the OOS data is truly out of sample — that
is, the strategy rules were NOT fitted from, inspired by, or otherwise
tuned against trades that overlap the OOS windows. Without this firewall,
a "walk-forward PASS" is the circularity trap described in the mission
statement.

The firewall has five clauses:

- **(a) `derived_from` is a required field** on every strategy spec. It can
  be explicit `null` for organic / literature-derived strategies. When
  non-null, its structure is:

  ```yaml
  derived_from:
    source_type: forensic_audit_ruleset | bootcamp_backtest | shadow_trading_cohort | other
    source_run_id: <run_id or audit_id>
    source_trade_ids: [optional list]
    source_date_range: {start: YYYY-MM-DD, end: YYYY-MM-DD}
  ```

- **(b) Framework-level overlap assertion** runs before any walk-forward
  window executes. For every declared `source_date_range`, the assertion
  verifies that it has **zero overlap** with any of the five OOS windows.
  If any overlap exists, the run raises `R8ViolationError` and aborts —
  no partial results are written. `derived_from: null` skips the assertion.

- **(c) No inherited credit** from source strategy backtests or metrics.
  If a spec declares `derived_from`, its walk-forward result MUST be
  computed from scratch — it cannot import Sharpe / trade sets from the
  source run.

- **(d) Bootcamp mode is forced to False** at the backtest-engine level
  during walk-forward runs, regardless of system config. This is belt-and-
  suspenders defense against any lookahead path that keys off the bootcamp
  flag.

- **(e) PR body R8 declaration.** The PR body must include a sentence of the
  form: "R8 compliance: `<spec>.derived_from == null` / `overlap verified
  zero for source_date_range [...]`." PR reviewers verify this honor-system
  declaration.

**Honor-system limitation.** The framework cannot detect undeclared
provenance — a developer could lie about `derived_from: null`. Mitigation
is commit 8's runtime heuristic (WARNING when spec file first commit is
within 30 days of a forensic audit on the same strategy family AND
`derived_from == null`).

---

## Architecture

```
src/platform/rigor/
├── walkforward_config.py        # WalkForwardConfig + defaults (commit 2)
├── walkforward_universe.py      # SPDR point-in-time resolver (commit 3)
├── walkforward_purging.py       # Purge + embargo (commit 4)
├── walkforward_costs.py         # Per-side cost application (commit 5)
├── walkforward_metrics.py       # Regime-conditional metrics (commit 6)
├── walkforward_power.py         # MDE + Newey-West (commit 7)
├── walkforward_firewall.py      # R8 firewall + runtime heuristic (commit 8)
└── walkforward_runner.py        # Main runner (commit 9)

scripts/backtest/
└── run_walkforward.py           # CLI wrapper (commit 11)

src/api/cloud_routes/
└── walkforward.py               # Backend route (commit 13)

frontend/src/pages/
└── WalkforwardResults.jsx       # Dashboard page (commit 13)
```

The existing `src/platform/rigor/walkforward.py` is the OOS-efficiency /
Pardo-2008-style wrapper used by the current promotion gate. It is **not
removed** — it remains the legacy signal for the existing promotion path.
The new framework lives alongside under the `walkforward_*` module
namespace. The new promotion logic (commit 10) preferentially reads from
the new `walkforward_results` table; falls back to the legacy path when
no new-style result exists (soft migration).

---

## Schema additions (commit 1)

Three new tables added to `src/schema/registry.py`:

### `walkforward_results`

One row per walk-forward run. Columns include `run_id` (PK), `strategy_id`,
`spec_hash`, `code_git_sha`, `random_seed`, `outcome_state`, `reason`,
`pooled_sharpe`, `pooled_mde`, `heavy_tail_flag`, `n_windows`,
`derived_from_source_type`, `derived_from_source_run_id`,
`effective_universe_size`, `created_at`.

### `walkforward_trades`

Per-window trade list. Columns include `trade_id` (PK), `run_id` (FK),
`window_index`, `ticker`, `entry_date`, `exit_date`, `pnl_pct`,
`exit_reason`, `vix_at_entry`, `is_in_is_window`, `sharpe_observed`
(per-window), `bootstrap_se`, `mde_value` (per-window).

### `sp100_historical_constituents`

Point-in-time S&P 100 membership. Columns include `ticker` (PK1), `added_date`
(PK2), `removed_date` (nullable — still a constituent if NULL),
`company_name`, `reason`. Loaded from `data/reference/sp100_historical.csv`
via the loader in commit 3.

All three are registered with `sync_to_postgres=True, sync_mode="incremental"`.

---

## Execution order (implementation commits)

See the cloud-execution prompt for the canonical numbered list. Short version:

1. **Schema** — new tables + migration tests.
2. **`WalkForwardConfig`** — dataclass + defaults + tests.
3. **SPDR resolver** — loader + populator + point-in-time resolver + tests.
4. **Purge/embargo** — `walkforward_purging.py` + boundary tests.
5. **Costs** — per-side cost application + tests.
6. **Metrics** — regime-conditional metrics + bootstrap SE sanity check.
7. **Power gate** — MDE via `src/diagnostics/power.py` + Newey-West.
8. **R8 firewall** — validation, overlap assertion, forced bootcamp=False,
   runtime heuristic.
9. **Runner** — `walkforward_runner.py` + three-state logic + integration tests.
10. **Promotion gate** — `check_promotion_gate` returns structured result
    with `outcome_state` + `reason`.
11. **CLI wrapper** — `scripts/backtest/run_walkforward.py`.
12. **Lazy Prices spec** — add `derived_from: null`.
13. **Dashboard** — React page + backend route.
14. **Smoke test** — Lazy Prices walk-forward with cloud synthetic fallback.
15. **Pass 3 self-review + docs update.**

---

## Lazy Prices smoke test [REDLINE 4]

Lazy Prices v1 spec sets `derived_from: null` (literature-derived from
Cohen-Malloy-Nguyen 2020). The smoke test verifies:

- R8(a) accepts `null` without error.
- R8(b) overlap assertion is skipped for non-derived strategies.
- All three outcome paths (PASS, FAIL, INCONCLUSIVE) are reachable when
  given synthetic returns tuned to hit each state.

**Cloud-execution note.** When running in a cloud / remote environment
without access to the operator's local EDGAR database, the smoke test uses
a **synthetic fallback** that exercises framework state-machine behavior
on synthetic trade streams tuned to hit PASS, FAIL, and INCONCLUSIVE.
The operator re-runs against real EDGAR data locally after PR review.

**Expected result on real data.** Must NOT report PASS. The forensic audit
established that cosine-similarity signal alone is underpowered at the
trade counts obtained on 2019-2024 data. A real-data PASS would indicate
a framework bug. Most likely outcome on real data: INCONCLUSIVE (coverage
or power).

---

## Non-goals (explicit exclusions for v0.25.0)

- Incumbent strategy walk-forward — v0.26.1, requires v0.26.0 YAML-ification.
- Post-audit ruleset walk-forward (morning-only + Defensive + tariff-excluded) —
  v0.26.2. Post-audit ruleset will be treated as a derived strategy under R8.
- Second strategy spec — v0.27.x.
- CPCV upgrade — v0.30.x.
- Non-contiguous `source_date_range` support — v0.30.x.
- Backtest-engine refactoring — HALT if needed; never refactor + feature.
- `known_events.py` 2019-2024 tariff coverage backfill — separate prerequisite
  sprint if audit reveals sparse.

---

## Operator hand-off [REDLINE 5]

On landing this sprint, operator:

1. Re-runs the Lazy Prices smoke test locally against real EDGAR data.
   Expected: FAIL or INCONCLUSIVE. If PASS, halt and investigate.
2. Verifies the `/walkforward-results` page renders correctly on
   halcyonlab.app.
3. Confirms SPDR historical constituent source choice (commit 3 docs the
   picked source and tradeoffs).
4. Pushes Pass 1 / Pass 2 / Pass 3 redline markdown artifacts from local
   machine to `docs/sprints/redline-history/`.

**Incumbent transition path.** A separate v0.26.0 YAML-ification sprint is
gated on this sprint landing. v0.26.1 runs incumbent walk-forward. v0.26.2
runs the post-audit ruleset walk-forward — both as derived strategies
under R8.

---

## PR body format [REDLINE 6]

The PR body for this sprint must include:

1. **R1–R8 verification.** One sentence per requirement with file/function
   references.
2. **Lazy Prices smoke test summary.** 5 per-window Sharpes, 5 MDEs,
   5 outcome states, pooled Sharpe, heavy-tail flag count.
3. **R8 compliance check.** Literal `derived_from` declaration from the
   spec; overlap verification result.
4. **Three-state outcome propagation audit.** Trace PASS / FAIL /
   INCONCLUSIVE through walkforward → results table → check_promotion_gate
   → dashboard.
5. **Self-review of fragile parts.** 3–5 items with failure mode and
   catching test each.
6. **Operator manual verification needed.** Explicit list (at minimum:
   real-data smoke run, live dashboard render).
7. **Follow-ups filed** (see Follow-ups below).

---

## Follow-ups [REDLINE 7]

| Sprint      | Description                                                          |
|-------------|----------------------------------------------------------------------|
| v0.25.1     | Dashboard enhancements (may split).                                  |
| v0.26.0     | Incumbent YAML-ification (prerequisite for incumbent walk-forward).  |
| v0.26.1     | Incumbent walk-forward run.                                          |
| v0.26.2     | Post-audit ruleset walk-forward (as R8 derived strategy).            |
| v0.27.x     | Second strategy spec.                                                |
| v0.30.x     | CPCV upgrade from walk-forward.                                      |
| v0.30.x     | Non-contiguous `source_date_range` support.                          |
| TBD         | `known_events.py` 2019-2024 tariff coverage backfill (if sparse).    |

Items 2, 3, 6 in the original cloud prompt scope (SPDR, runtime heuristic,
dashboard) are done in this sprint — not in follow-ups.

---

## Test count [REDLINE 3]

≥30 tests covering R1–R8 + SPDR resolver + heuristic warning + dashboard
backend. Baseline before sprint: 98 tests in platform/rigor + diagnostics
modules (full suite enforces CI ≥1339). Sprint must not drop aggregate.

---

## Bootcamp-mode caveat

All Sharpe / gate reasoning in this framework caveats: strict-mode
thresholds (DSR ≥ 0.95, PBO ≤ 0.50, OOS_eff ≥ 0.30) are not yet enforced
at the system level. Walk-forward v1 IS part of the strict-mode gate stack
but does not flip bootcamp off at the system level. That is a separate
operator decision (see v0.26.0 sprint plan).
