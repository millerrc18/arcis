# Old Platform Inventory — S02 Carry-Forward

**Legacy repo:** `millerrc18/arcis-legacy`
**HEAD SHA:** `78c788ec8592254bd77f5bcf856918ff282835a8` (2026-06-16, branch `main`)
**Inventory date:** 2026-10-04 · **Completed:** 2026-10-06 (corrections, verification, sprint report)
**Method:** GitHub clone, read-only, plus the cleaned local archive, read-only. No code, data, or credentials copied.

> Every claim cites the legacy commit SHA above. Paths are relative to the
> legacy repo root unless noted.

### Sources and citation keys

| Key | Source | Integrity |
|---|---|---|
| `@78c788ec` | `millerrc18/arcis-legacy` `main` HEAD `78c788ec8592254bd77f5bcf856918ff282835a8` | 2,501 tracked files and 1,875 commits, re-verified 2026-10-06 against a scratch copy of the archived `.git` |
| `archive 63a391c2` | `~/archive/arcis-legacy-2026-09-28/arcis-legacy-2026-09-28.tar.gz` (the cleaned archive; S02 T1's only permitted local source) | SHA-256 `63a391c26136bb76fe78b6a66610459d003a375279d8b32aeb02733cef1a5e50`, matches its `SHA256SUMS.txt` |
| `pg 246ccc1f` | `~/archive/arcis-legacy-2026-09-28/pg-halcyon-2026-07-15.finnhub-removed.sql.gz` (legacy Postgres at its 2026-07-15 shutdown, Finnhub tables emptied) | SHA-256 `246ccc1ff4f4408bd0e1df98671c15548b4bb15d72432030c7e558af44ba39c0`, matches `SHA256SUMS.txt` |
| `s02-extracts` | `~/archive/s02-extracts/` (targeted extracts from `archive 63a391c2`, made 2026-10-04; its `README.md` records the method) | Derived from `archive 63a391c2` |

The raw 2026-10-03 archive (`arcis-legacy-raw-2026-10-03`) holds credentials and Finnhub data and was never opened (its own README forbids use in the rebuild). Archive work on 2026-10-06 ran on copies: git objects were copied to a scratch directory outside the archive, and SQLite files were opened `mode=ro&immutable=1`.

---

## T1 — Repository snapshot

| Field | Value |
|---|---|
| HEAD | `78c788ec8592254bd77f5bcf856918ff282835a8` |
| Date | 2026-06-16 17:13:15 -0400 |
| Branch | `main` |
| Commits | 1,875 |
| Tracked files | 2,501 |

Main areas by file count: `tests/` (785), `docs/` (665), `src/` (513),
`.claude/` (304), `scripts/` (111), `frontend/` (68).

The legacy platform is an S&P 100 pullback-oriented systematic trading system
with LLM-in-the-loop scoring, paper-trading infrastructure (Alpaca), and an
extensive rigor/validation harness. The rebuild targets the S&P 500
(SCOPE D-012); the legacy strategy is not a direct port.

---

## T2 — Incumbent strategy definition: RESOLVED (from local archive)

**Update 2026-10-04:** The local archive yielded the missing definition.
Sprint F's evaluation document (`docs/sprints/sprint_F_evaluation.md`)
states:

> **Correction 2026-10-06:** the original text said this document was
> "recovered from local archive, not in GitHub clone". That is wrong. The
> file is present at `@78c788ec` (verified with `git cat-file`), and
> `s02-extracts/t2_candidates/INDEX.tsv` records it as "GitHub HEAD
> 78c788ec (no local-only version differs)". The GitHub-side pass missed it
> because it searched for YAML (`s02-extracts/README.md`, T2 finding 2). The
> same wrong phrase is in the comment header of `config/incumbent_v1.yaml`.
> That file is frozen, so its comment is left as is and corrected here.

> "Sprint F ports the **incumbent pullback ranker** onto the existing
> strategy-spec surface"

The incumbent is the **pullback ranker** — a mean-reversion strategy scoring
S&P 100 tickers 0–100 on pullback depth, trend state, relative strength, and
volatility signals. Full definition in `config/incumbent_v1.yaml`, sourced
line-by-line from the Sprint F doc's citations to:
- `src/ranking/ranker.py` (scoring bands, regime adjustments, sector RS)
- `src/features/engine.py` (feature computation)
- `src/features/enrichment.py` (post-scan dispatch)
- `src/data_enrichment/enricher.py` (enrichment orchestrator)

**Clarifications from local archive:**
- `lazy_prices_v1` (Cohen-Malloy-Nguyen 2020) was a **separate candidate**,
  formally **shelved** post-bootcamp (`status: shelved` in the `8b429217`
  variant, with revival criteria). It is NOT the incumbent.
- `post_audit_ruleset_v1` is a filter layer on `lazy_prices`, not the incumbent.
- **Local-only commits (corrected 2026-10-06).** The original text said "8
  truly unpushed local commits". `s02-extracts/t2_unpushed_commits.csv` does
  not support that number:

  | Set | Count | Meaning |
  |---|---|---|
  | Commits on no remote-tracking ref | **41** | Every CSV row: 37 in the C:\arcis repo, 4 in the OneDrive clone |
  | …of which present on GitHub `arcis-legacy` | 22 | `on_github_arcis_legacy=yes` (19 C:\arcis, 3 OneDrive): the local ref lagged, but the content reached GitHub |
  | …of which on **no** GitHub repo | **19** | `on_github_arcis_legacy=NO`: 18 C:\arcis commits dated 2026-05-21 → 2026-05-27, plus the OneDrive merge `b4f857d6` (2026-04-06) |

  The `s02-extracts/README.md` (T2 finding 5) independently gives 19. No
  subset of the CSV yields 8, and the original pass recorded no rule
  that would, so **the "8" is withdrawn as unsupported** rather than explained.
  The truly local-only set is the 19.

  **What they contain (verified 2026-10-06 from a scratch copy of
  `archive 63a391c2`'s `.git`):** all 18 C:\arcis commits are ops and test
  work: watch-loop and heartbeat fixes, NSSM mapping, telemetry, dual-GPU
  process control, lifecycle tests, a `run_backtest.py` flag deprecation
  (`245ce547`), and a log-path change in `config/arcis_config.yaml`
  (`e6eb3787`). None touches `src/features/`, `src/ranking/`, `src/strategy/`
  or `src/platform/specs/`. `d5b1f336` edits three `src/platform/` files, and
  every changed line there is a comment or help-text string. Each of the 18
  carries the same `src/features/engine.py` blob (`91588221…`) and
  `src/features/indicators.py` blob (`7b39d141…`) as `@78c788ec`. The
  OneDrive merge `b4f857d6` carries an earlier engine blob with identical
  classifier logic. None contains a strategy definition or a trial result.
- Three `lazy_prices_v1.yaml` variants recovered show evolution: `edf1cb1d`
  (earliest, no `derived_from`) → `24c1940e` (adds R8(a) `derived_from: null`)
  → `8b429217` (adds `status: shelved`).

**S&P 100 assumptions flagged** (SCOPE D-012): every threshold was tuned
against S&P 100 mega-cap liquidity. Listed in the YAML under
`sp100_assumptions`; require re-examination for S&P 500, never silent adoption.

No `incumbent_v1.yaml` existed in the legacy repository itself. The legacy
platform's own docs (`docs/sprints/incumbent_v1_yaml_evaluation.md`)
concluded extraction was BLOCKED for the LLM-bracket-pricing reason — but
the Sprint F doc provides the deterministic ranker rules, which are what
is frozen here. The LLM-in-the-loop bracket pricing remains excluded
(documented in the YAML).

---

## T3 — Reconciliation against what actually ran: PERFORMED (local archive)

**Update 2026-10-04:** The local archive yielded `t3_closed_trades.json` —
620 closed trades from the local databases, of which **287 are
`strategy_type: pullback`** (the incumbent), spanning 2026-03-24 to 2026-06-30
across 61 unique tickers.

A random sample of 20 pullback trades (seed 42) was checked against the
incumbent rules. **Discrepancies found:**

| # | Discrepancy | Severity |
|---|---|---|
| 1 | `ranking_at_entry` is all zeros (dead field), but `rec_priority_score` carries the live ranker output: 183/287 trades scored 60–100 (mean 84). | **RESOLVED 2026-10-04** — ranker scores verifiable via `rec_priority_score` |
| 2 | `regime_at_entry` is binary `GREEN`/`None` (150/137), not the detailed regime labels (`calm_uptrend`, `transitional`, etc.) in the Sprint F doc. | **MEDIUM** — regime adjustments unverifiable from records |
| 3 | 171/287 (60%) exits are `reconciled_stale`, not clean mechanical exits (`target_1`, `stop_loss`). Only 42/287 hit documented exit reasons. | **MEDIUM** — exit discipline unverifiable for majority |
| 4 | Mean PnL across 105 trades with numeric PnL: **+0.03%** (min −6.88%, max +8.23%). | INFO — consistent with the April forensic audit's ~zero excess |

**Candidate counts:** trades cluster 2–22 per entry date (e.g., 2026-03-24: 20
trades, 2026-04-01: 22 trades). With S&P 100 universe, the median daily
qualification rate is approximately 15–20% — recorded here for S03's planning
(SCOPE D-024). Exact median: left for S03 to compute from the full date series.

**Conclusion:** The frozen definition rests on the Sprint F document, **not**
on verified behavior. The records show pullback-labeled trades occurred, but
the scores and regimes that should explain *why* each trade was taken were
not captured. This is recorded as an UNRESOLVED item in the freeze block:
the definition is the best available, but its behavioral fidelity is
unproven. S03's exploratory historical check (PREREGISTRATION §2.4) is the
mechanism that will test whether the documented rules have edge.

GitHub-side assessment (superseded): no machine-readable decision records
existed in the clone. This finding is now moot.

### T3 verification and gaps (added 2026-10-06)

Re-checked against `s02-extracts/t3_closed_trades.json` (620 closed paper
trades from `archive 63a391c2` and `pg 246ccc1f`). Only labels, counts and
dates were read; no P&L was recomputed.

| Claim above | Re-check | Status |
|---|---|---|
| 287 trades with `strategy_type: pullback`, 2026-03-24 → 2026-06-30, 61 tickers | 287; 2026-03-24 → 2026-06-30; 61 tickers. By store: 107 bootcamp SQLite, 105 SQLite, 75 Postgres | Confirmed |
| `ranking_at_entry` dead; `rec_priority_score` 60–100 on 183/287 | `ranking_at_entry` is 0 (150) or null (137); `rec_priority_score` is non-null on 183, all in 60–100 | Confirmed |
| `regime_at_entry` `GREEN`/null 150/137 | 150 / 137 | Confirmed |
| 171/287 `reconciled_stale`; "only 42/287 hit documented exit reasons" | 171 confirmed. The 42 is `target_1` (22) + `stop_loss` (20). A further 13 are `target_1_hit`, which also names a documented exit, giving 55 if counted | **UNRESOLVED** (which exit labels count as documented) |
| "Random sample of 20 (seed 42)" | The 20 sampled trade IDs and the per-decision rule checks are not recorded anywhere in this repo, so the sample cannot be re-drawn or audited | **Gap**: the ≥20-decision requirement was met in count but is not reproducible |
| Per-decision candidate count and universe size (S02 T3 bullet 2) | Not recorded per sampled date. The "15–20%" estimate was superseded for planning by D-025 (5%, `docs/research/power-measurement.md`). For the record: in `pg 246ccc1f` `recommendations` (2026-05-21 → 07-02, 27 days, all `action_packet`/`Buy`), the median is 17 distinct tickers a day against the ~100-name S&P 100. This counts recommendations, not order-eligible candidates | Partially closed; no change to D-025 |

**New discrepancy (UNRESOLVED): which trades the incumbent produced.** 329 of
the 620 trades are labeled `strategy_type: mean_reversion` (2026-05-08 →
2026-07-02; 320 Postgres, 9 SQLite). The original T3 excluded them. But
every one links to a recommendation whose setup text is "Pullback in strong
trend / relative strength continuation", the incumbent's setup. The
cross-tab is: mean_reversion with pullback setup 329; pullback with pullback
setup 183; pullback with no recommendation 104; unlabeled 4. A separate
mean-reversion scanner did exist (`src/services/mr_scan_service.py`, called
from `src/scheduler/watch.py`; documented in `src/features/enrichment.py`
lines 9–14 @78c788ec). Either the label is right and the setup text is a
shared default, or these are incumbent trades with a wrong label. Both
candidates are recorded. `strategy_id` and `strategy_spec_hash` are empty on
every trade (`s02-extracts/README.md`, T3 finding 2), so the records cannot
settle it. Ledger row T5-016.

**Disagreement now noted:** T6's "Live/shadow paper trading" union ended
2026-04-21, but recorded closed trades run to **2026-07-02**. T6 is corrected
below.

---

## T4 — Freeze: COMPLETE

- `config/incumbent_v1.yaml` normalized and frozen 2026-10-04.
- SHA-256: `524dd858d95a08453167e46e976836601fe3f281b8d94f763cee843277e24b82`
- Recorded in the YAML's `frozen:` block with date and unresolved items.
- Verification script: `tools/verify_incumbent_freeze.py` (recomputes hash;
  exits 0 on match, 1 on mismatch). Verified working.

This is the hash PREREGISTRATION.md §1 refers to. After `prereg-v1` is tagged,
changing it creates a new trial.

**Unresolved at freeze** (in the YAML's `frozen.unresolved_at_freeze`):
1. T3 discrepancy: recorded scores/regimes don't reflect the documented ranker.
2. T3: 60% of exits are `reconciled_stale`, not mechanical.
3. S&P 100 thresholds flagged per SCOPE D-012.

---

## T5 — Trial ledger

**Counting rule:** one row per economically distinct configuration evaluated
against returns, as documented in sprint reports, validation docs, decision
records, or the CHANGELOG. A parameter sweep reported as a single experiment
counts once (conservative); each individually named parameter variation counts
separately (liberal).

> **Correction 2026-10-06.** The original table gave 13 / 13. The ledger
> then held **12** rows, not 13, and those rows were not 12 distinct
> configurations. Several are different analyses of the same paper cohort,
> and two are reruns of one spec hash. Four rows were added after checking
> the archive (below). The counts are restated with an explicit rule.

**Counting rule (restated 2026-10-06).** A *configuration* is a strategy
definition plus its parameters, identified by spec hash or config hash where
one exists. A row enters the count only if it was evaluated against *real*
market returns (paper, live, or historical). Synthetic framework-calibration
runs are listed but not counted.

- **Conservative:** one per clearly distinct configuration. Reruns of the same
  hash, and further analyses of the same cohort, collapse into one.
- **Liberal:** one per ledger row on real data, i.e. every separately
  reported evaluation or variant.

For the Deflated Sharpe audit, the **liberal** count is the stricter penalty.

| Count | Value | Rows |
|---|---|---|
| Conservative | **5** (6 if T5-016 is a distinct configuration; UNRESOLVED) | (1) incumbent pullback paper cohort: T5-001/002/003/005/014/015; (2) LLM-desk conviction cohort: T5-004; (3) `lazy_prices_v1` spec `ea78fed3…`: T5-009/011, plus T5-012, whose spec hash is unrecorded so it is not clearly distinct; (4) `post_audit_ruleset_v1` spec `463853b5…`: T5-010; (5) regime-scenario simulation, config `f2232925…`: T5-013 |
| Liberal | **13** | Every row except the three synthetic runs T5-006/007/008 |
| Executions (sensitivity) | **22** | Liberal, with T5-013 counted once per run (10 runs of one config at different code versions) |

**Verification against the archive (2026-10-06).**
- **Walk-forward.** `walkforward_results` holds 3 runs, all in the bootcamp
  SQLite copy (`archive 63a391c2`, `staging/databases/ai_research_desk_bootcamp_2026-04-24.sqlite3`).
  Their run_ids and spec hashes match T5-009, T5-010 and T5-011 exactly. The
  table is empty in the five later SQLite copies, the 2026-05-10 Render
  snapshot and `pg 246ccc1f`.
- **Empty registries.** `trials_registry`, `backtest_results` and
  `strategy_registry` have **0 rows in every archived store**. The legacy
  platform's own N_eff ledger was never populated, so this CSV is the only
  trial count.
- **Missing configuration found:** `simulation_results` holds 10 runs of one
  regime-scenario configuration (13 historical scenarios, 2015-06-01 →
  2022-10-31; `model_version=mechanical_brackets`, identical `config_json`,
  seed 42). These are 3 in the bootcamp DB (2026-04-09 to 04-19) and 7
  weekly runs in `pg 246ccc1f` (2026-05-10 to 06-28). This evaluation against
  historical returns was absent from the ledger and is now T5-013.
- **Missing analyses found:** two regime diagnostics of the incumbent paper
  cohort (`docs/diagnostics/regime-2026-04-18.md` and `-nonq.md` @78c788ec).
  These are now T5-014 and T5-015. They are the same configuration as
  T5-001, so they enter the liberal count only.
- **Not trials:** `strategy_promotion_events` (615 rows in `pg 246ccc1f`, and
  19 to 698 per SQLite copy) is entirely `strategy_id='nonexistent'` →
  `deprecated` test events. `validation_results` holds system health checks.
- **Local-only work:** none of the 19 commits on no GitHub repo and none of
  the 19 stashes (11 C:\arcis, 8 OneDrive; `s02-extracts/t2_stashes.txt`)
  adds a trial, a result file or a run record. The only stash file whose name
  matched is `tmp_design2/notification_sweep_report.md`, a notification audit.
- **Row fixes:** T5-004 and T5-005 had an extra empty column that shifted
  every later field one place right; both are realigned. T5-009/010/011
  `daily_returns_recoverable` now points at the archived per-trade rows. T5-012
  now records that its tables are empty.

Full ledger: `docs/research/trial-ledger.csv` (columns: `trial_id, date,
description, universe, period_start, period_end, variant_or_hash,
headline_result, daily_returns_recoverable, source_path`).

Headline findings from the ledger:
- **2026-04-16 forensic analysis** of 78 closed pullback trades: per-trade
  Sharpe 3.38 [CI 2.80, 3.96] but mean excess vs SPY only +0.039%/trade
  (t=0.098) — raw Sharpe was bull-market SPY beta capture, not alpha. This
  drove the excess-Sharpe gate redefinition (Sprint D1/D2/D3).
- **2026-04-18 forensic audit** of 88 closed trades: mean return 0.6547%,
  excess Sharpe −0.9539 with slippage; Wilcoxon p=0.4172 (excess ≈ 0).
- Walk-forward v1 canonical OOS windows 2019–2024 (see T6).
- Live Alpaca paper trades (CVS, NEE, NVDA, April 2026) surfaced executor
  quantity-asymmetry bugs, since fixed.

**Daily returns recoverability:** mostly `unknown` — per-trade ledgers lived in
the local `shadow_trades` SQLite/PostgreSQL databases, not in the repo. Where
the audit documents give summary statistics, those are recorded; no returns
were estimated.

Spot check (5 rows traced): T5-001 → `docs/diagnostics/forensic-audit-2026-04-18.md`;
T5-002 → `docs/research/sharpe-attribution-methodology.md`;
T5-003 → `docs/sprints/sprint-D1-spy-excess-instrumentation.md`;
walk-forward windows → `docs/sprints/SPRINT_walkforward_validation_v1.md`;
paper-trade bugs → `docs/sprints/fix_paper_exit_qty_asymmetry_evaluation.md`.
All present at the cited SHA (re-verified 2026-10-06, together with every
other `source_path` in the ledger that names a repo file).

---

## T6 — Date ranges ever evaluated

The original pass reported "21 ranges identified (full table in research
notes)". **That table is not in this repository**, and the research notes it
refers to are not named. That breaks S02 T6's "with a source for each".
Recorded as a gap. The rows below carry the sources that could be confirmed.

| Context | Union | Source |
|---|---|---|
| Walk-forward OOS (canonical) | 2019-01-01 → 2024-09-30 | ledger T5-009/010/011 period columns; `docs/sprints/SPRINT_walkforward_validation_v1.md` @78c788ec |
| Walk-forward IS train windows | 2017-01-01 → 2022-12-31 | original pass; per-row source not recorded |
| Regime-scenario simulation (added 2026-10-06) | **2015-06-01 → 2022-10-31**, in 13 windows: 2015-06→12, 2016-06→12, 2017 (full year and 06→11), 2018-01→04, 2018-10→2019-01, 2019-07→12, 2020-01→04, 2020-02→06, 2020-03→08, 2021-01→06, 2022-01→10, 2022-03→09 | `simulation_results` scenario dates, `pg 246ccc1f` and `archive 63a391c2` (ledger T5-013) |
| EDGAR filing corpus | 2019-01-08 → 2026-04-17 | original pass; per-row source not recorded |
| S&P 100 constituent reference | 2000-01-01 → 2023-09-18 | original pass; per-row source not recorded |
| Live/shadow paper trading (**corrected** 2026-10-06; was "→ 2026-04-21") | 2026-03-24 → **2026-07-02** | `s02-extracts/t3_closed_trades.json`: 620 closed trades; no closed trades created 2026-05-12 → 05-25 (`s02-extracts/README.md`, T3 finding 1) |
| OHLCV price prerequisite | 2019-01-01 → 2024-12-31 | original pass; per-row source not recorded |

**Union of historical evaluation (corrected):** 2015-06-01 → 2024-12-31
for price-based tests, plus the 2026-03-24 → 2026-07-02 paper period.

**Contamination note (PREREGISTRATION.md §2.4):** the exploratory historical
check runs on data the old platform already used (2015–2022 regime
simulations, 2017–2024 walk-forward windows, 2019–2026 filing corpus), so it
can only retire the strategy, never support it. The union above is the
contaminated region. The 2026-10-06 correction extends its start from 2017 to
**2015-06-01**, because the incumbent ranker itself was simulated on 2015–2016
windows (T5-013).

---

## T7 — Specs worth porting (recommend, do not port)

Seven specs recommended for **clean-room reimplementation** — no legacy code
copied. Each entry: what it did, where it lives, known issues.

### 1. Walk-forward framework (R1–R8 rigor clauses)
Rolling walk-forward with purge+embargo, MDE power gates, three-state outcome
(PASS/FAIL/INCONCLUSIVE). `src/platform/rigor/` (9 modules; runner owns
`walkforward_results`, `walkforward_trades`).
Known issues: 2026-04-19 smoke test ran on synthetic fallback in cloud;
cosine-similarity signal underpowered at 2019–2024 trade counts.
Not superseded. **Rationale:** the single most valuable carry-forward — a
working, audit-hardened anti-self-deception harness.

### 2. CPCV leakage detector
Combinatorial purged cross-validation (López de Prado 2018 §7.4).
`src/methods/cpcv.py`. Known issue: FRED rf wiring does network I/O in a
pure-statistics module. Not superseded. **Rationale:** second independent
backtest-validation leg beside walk-forward.

### 3. Bracket simulator
pct/ATR-based stop/target with floor/cap, strict no-lookahead ATR history.
`src/platform/backtest_engine.py::_compute_bracket_prices` (line 117).
Known issue: LLM-in-the-loop extraction BLOCKED April 2026; only deterministic
math is portable. Not superseded. **Rationale:** exact exit semantics for any
faithful trial ledger.

### 4. Regime scenario engine
13 regime scenarios + Monte Carlo (equity bounds, p95/p99 drawdown, ruin
probability). `src/simulation/engine.py`, `src/simulation/monte_carlo.py`.
Known issue: yfinance single price source, no corporate-action audit.
Not superseded. **Rationale:** cheap regime-robustness stress tests.

### 5. Attribution ledger schema
Two-phase alpha attribution (ranker vs LLM), table `attribution_trades`,
canonical `llm_action` values. `src/attribution/logger.py`.
Known issue: 2026-04-28 audit found 80 buy + 147 skip rows with non-canonical
labels silently excluded from t-tests. Not superseded. **Rationale:** template
for knowing whether an LLM layer adds or subtracts value.

### 6. Cost calibration module
Live-fill cost calibration from `shadow_trades`; per-side costs in
walk-forward (R4). `src/cost_model/calibration.py`,
`src/platform/rigor/walkforward_costs.py`. Known issue: calibrates from
paper fills, may not match live impact at size. Not superseded.
**Rationale:** costs are where paper strategies die.

### 7. Trials registry + Deflated Sharpe Ratio
`trials_registry` as N_eff source-of-truth per the False Strategy theorem;
DSR consumes N_eff. `src/platform/rigor/trials.py`, `src/platform/rigor/dsr.py`.
Known issue: documents a real paper-exposition inconsistency, handled with a
dual-V regression guard rather than an arbitrary pick. Not superseded.
**Rationale:** the multiple-testing ledger — third anti-self-deception pillar.

**Port as a unit:** walk-forward + CPCV + trials/DSR form a coherent harness;
porting one without the others loses the multiple-testing discipline.

---

## T8 — Data sources and stored data

### Vendors

| Vendor | Provided | Status |
|---|---|---|
| Alpaca | Paper + live brokerage APIs | Working at HEAD |
| **Finnhub** | Headlines + simple sentiment (NOT full text), insider, recommendations, ownership, filings | **DO NOT REUSE — license-restricted.** Premium lapsed 2026-07-30; Fundamental lapses 2026-10-30 |
| yfinance | OHLCV bars, options, VIX | Free; needs corporate-action/survivorship audit before Stage A |
| FRED | Macro indicators, DTB3 risk-free rate | Free |
| SEC EDGAR | Filings | Public |
| FINRA | REGSHO short volume | Public |
| CBOE | Put/call ratio (scrape) | Public; scrape-fragile |
| Fed | FOMC communications | Public |
| Google Trends | Search interest | Free |

### Stored data (formats; sizes not in repo)
- `data/`: 13 items including `simulation_cache/` (parquet OHLCV).
- `.cache/news`: pickled Finnhub payloads — **DO NOT REUSE**.
- Postgres `halcyon`: `walkforward_results`, `walkforward_trades`,
  `attribution_trades`, `simulation_results`, `sp100_historical_constituents`,
  `trials_registry`, `research_papers`, `research_docs`.
- SQLite legacy: `trials_registry`, DSR reads.

### License-restricted — never reuse
All Finnhub data and derived artifacts (news caches, DB rows, the nine
collector tables, training sets built on Finnhub feeds). Finnhub terms require
deletion on subscription end.

---

## T9 — Old fine-tuned model

| Field | Value | Source |
|---|---|---|
| Base model | Qwen3-8B | `src/llm/ollama_state.py:40` |
| Fine-tuned name | `halcyon-v1` (Ollama) | `src/llm/ollama_state.py:40` |
| Versions | `halcyon-v1.0.0`, `halcyon-latest` | `src/platform/specs/lazy_prices_v1.yaml:78` |
| Earlier name | `qwen3-8b-ft` | `docs/research/XML_Compliance_via_GBNF_Grammar_Enforcement.md` |
| Corpus | `stage1-001`: 67,528 walk-forward entries | `data/corpus/stage1-001/MANIFEST.md` |
| Corpus SHA-256 | `43c2e3edb2cd4bb450a890da388ec2ade49ce3205d67a0525f2bb74485606d93` | `data/corpus/stage1-001/MANIFEST.sha256` |
| **Last date in training data** | **2026-04-28** | corpus manifest (last `as_of`). The archive's `ADDENDUM.txt` (next to `archive 63a391c2`) gives 2026-04-26, taken from ISO dates inside the training prompts. Both versions are recorded. The manifest's later date is the conservative boundary, and Open question 5 already adopted it |
| GGUF artifact | `training_data/halcyon-latest.gguf` (~5 GB) | `src/training/trainer.py:302` |
| Weight hash | **Not found in repo** | searched `src/training/`, configs, docs |

**PREREGISTRATION.md §1.4 consequence:** the model may only be evaluated on
articles first seen after 2026-04-28. The corpus entries file and the `.gguf`
are not in the GitHub clone (gitignored); they live in the local archive.

---

## Carrying forward

1. **The incumbent definition** (`config/incumbent_v1.yaml`, frozen
   `524dd858…`): the pullback ranker from Sprint F, with T3 discrepancies
   explicitly recorded. This is the baseline every future trial is measured
   against.
2. **The rigor harness** (T7.1, T7.2, T7.7): walk-forward R1–R8 + CPCV +
   trials/DSR, as a clean-room reimplementation. This is the anti-self-deception
   machinery the charter demands, already debugged once.
3. **Bracket math** (T7.3): deterministic pct/ATR stop/target with floor/cap.
4. **Attribution schema** (T7.5) and **cost calibration loop** (T7.6): templates
   for honest LLM-value and net-of-cost measurement.
5. **Regime scenario catalog** (T7.4): 13 scenarios as a stress-test checklist.
6. **Trial ledger** (`docs/research/trial-ledger.csv`): 16 rows; 5
   conservative / 13 liberal / 22 executions (T5, restated 2026-10-06),
   feeding the Deflated Sharpe audit.
7. **Date-range union** (T6): the contamination region for PREREGISTRATION §2.4.
8. **Model training cutoff** (T9): 2026-04-28 — the Q3 eligibility boundary.
9. **T3 trade sample**: 287 pullback trades (2026-03-24 → 2026-06-30) now
   available for S03's qualification-rate planning.

## Not carrying forward

1. **The legacy implementation of the strategy** (corrected 2026-10-06; the
   original said "no extractable definition exists (T2 UNRESOLVED)", which
   contradicts T2 as resolved). The *definition* is carried forward as
   `incumbent_v1`. The legacy *code* and its S&P 100 tuning are not: the
   rebuild reimplements clean-room on the S&P 500 (D-012).
2. **Any Finnhub data or derived artifacts** (T8): license-restricted, must stay out.
3. **LLM-in-the-loop bracket pricing**: not portable to a static definition.
4. **yfinance as an unexamined price source**: reusable only after a
   corporate-action/survivorship audit.
5. **Any code**: clean-room reimplementation only, per S02 ground rules.

## Open questions for the CEO

1. **T2**: CONFIRMED 2026-10-04 — incumbent is the Sprint F pullback ranker.
2. **T3**: RESOLVED 2026-10-04 — `rec_priority_score` is the live score field (183/287 trades, 60–100). Remaining: binary regimes, 60% `reconciled_stale` exits.
3. **T4**: Freeze hash `524dd858…` recorded. Goes into PREREGISTRATION.md §1 at `prereg-v1` tag time (CEO agreed 2026-10-04).
4. **T7**: Confirm the seven specs are worth SCOPE.md §9 `(proposed)` entries
   for clean-room reimplementation, and their priority order.
5. **T9**: RESOLVED 2026-10-04 — corpus manifest hash (`43c2e3ed…`) SUFFICIENT for Q3 eligibility.

Added 2026-10-06. Each is `UNRESOLVED` until Ryan decides:

6. **T3: which trades did the incumbent produce?** 329 trades labeled
   `mean_reversion` link to pullback-setup recommendations (T3 verification).
   (a) They are a separate MR desk, so the incumbent's record is the 287
   pullback trades and the trial ledger's conservative count is 6; or
   (b) they are mislabeled incumbent trades, so the record is up to 616 and the
   conservative count stays 5.
7. **T3: documented exits.** Does `target_1_hit` (13 trades) count as a
   documented exit beside `target_1` and `stop_loss`? That makes 42 or 55 of
   287.
8. **T3: reproducibility.** The 20-trade sample (seed 42) was never listed.
   Accept the reconciliation as recorded, or re-draw and record a listed
   sample in a follow-up? Counts only, no returns.
9. **T6: the missing range table.** The original "21 ranges" table was never
   committed. Four union rows have no per-row source. Rebuild the table from
   `@78c788ec`, or accept the union as sourced above?
10. **T5: counting for the DSR audit.** Which count feeds the Deflated Sharpe
    N: conservative 5 (or 6), liberal 13, or executions 22? The liberal and
    execution counts penalize more.

## Errata and post-S02 findings (2026-10-06)

- **Freeze-file citations.** `config/incumbent_v1.yaml` says its code
  citations are at legacy SHA `78c788ec`. The `src/ranking/ranker.py` line
  numbers it copies from the Sprint F doc resolve at the **pre-port** ranker,
  commit `c02384e301112cbd617c969b319fec9b1a864d2b` (2026-04-21, parent of
  Sprint F's `0f472b0b`). At `78c788ec` the same scoring sits at
  `ranker.py:491-501`, and the score mapping is identical at both. This is a
  citation erratum only. The YAML stays unchanged, so its freeze hash
  `524dd858…` stays valid.
- **Classifier recovery (post-S02).** The 2026-10-06 classifier recon
  (`claude/arcis-classifier-recon-2026-10-06.md` in the project workspace,
  referred to as D-031; not yet entered in SCOPE §9) recovered the
  `trend_state` and `relative_strength_state` classifiers from
  `src/features/engine.py:99-141` and `src/features/indicators.py:94-110`
  @78c788ec. Each has five labels: trend `strong_uptrend`/`uptrend`/`neutral`/
  `downtrend`/`strong_downtrend`; RS `strong_outperformer`/`outperformer`/
  `neutral`/`underperformer`/`strong_underperformer`. The logic is identical
  in all 19 packed engine versions from 2026-03-24 to 06-05, in the 18
  local-only commits and in the orphaned blob, and it matches the labels
  recorded in `pg 246ccc1f` `recommendations`. Labels the YAML does not
  list scored 0 in the legacy ranker. Landing this needs a SCOPE §9 decision
  plus a PREREGISTRATION §5 amendment, kept outside the frozen YAML.

---

## Provenance

- Legacy clone: read-only, outside the working tree (`~/workspace/s02/`).
  Working tree verified clean; no modifications, no commits, no pushes to
  `arcis-legacy`.
- Nothing copied into this repo except this report, the trial-ledger CSV
  (metadata only — no article text, no market data), and the UNRESOLVED
  incumbent stub.
- Public-repo scan: see PR description.
- 2026-10-06 completion pass: `archive 63a391c2` and `pg 246ccc1f` were read
  only. Git objects were copied to a scratch directory outside the archive.
  SQLite was opened read-only and immutable. Only table names, row counts,
  run identifiers, labels and dates were read, with no P&L recomputed. Nothing
  was written to the archive or to `arcis-legacy`. No code, data, article
  text or credentials were added.
