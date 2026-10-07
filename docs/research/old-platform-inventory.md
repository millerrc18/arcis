# Old Platform Inventory — S02 Carry-Forward

**Legacy repo:** `millerrc18/arcis-legacy`
**HEAD SHA:** `78c788ec8592254bd77f5bcf856918ff282835a8` (2026-06-16, branch `main`)
**Inventory date:** 2026-10-04
**Method:** GitHub clone, read-only. No code, data, or credentials copied.

> Every claim cites the legacy commit SHA above. Paths are relative to the
> legacy repo root unless noted.

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
Sprint F's evaluation document (`docs/sprints/sprint_F_evaluation.md`,
recovered from local archive, not in GitHub clone) states:

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
- The 8 truly unpushed local commits (from `t2_unpushed_commits.csv`) are all
  infrastructure/ops (auditor, GPU, telemetry, scheduler) — none contain
  strategy definitions.
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

| Count | Value |
|---|---|
| Conservative (distinct configurations) | 13 |
| Liberal (every parameter variation named) | 13 |

(Both counts coincide: the 13 ledger rows each describe a distinct experiment;
no finer-grained parameter enumerations were found documented separately.)

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
All present at the cited SHA.

---

## T6 — Date ranges ever evaluated

21 ranges identified (full table in research notes). Union of evaluated ranges:

| Context | Union |
|---|---|
| Walk-forward OOS (canonical) | 2019-01-01 → 2024-09-30 |
| Walk-forward IS train windows | 2017-01-01 → 2022-12-31 |
| EDGAR filing corpus | 2019-01-08 → 2026-04-17 |
| S&P 100 constituent reference | 2000-01-01 → 2023-09-18 |
| Live/shadow paper trading | 2026-03-24 → 2026-04-21 |
| OHLCV price prerequisite | 2019-01-01 → 2024-12-31 |

**Contamination note (PREREGISTRATION.md §2.4):** the exploratory historical
check runs on data the old platform already used (2017–2024 walk-forward
windows, 2019–2026 filing corpus), so it can only retire the strategy, never
support it. The union above is the contaminated region.

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
| **Last date in training data** | **2026-04-28** | corpus manifest (last `as_of`) |
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
6. **Trial ledger** (`docs/research/trial-ledger.csv`): the 13-configuration
   record, feeding the Deflated Sharpe audit.
7. **Date-range union** (T6): the contamination region for PREREGISTRATION §2.4.
8. **Model training cutoff** (T9): 2026-04-28 — the Q3 eligibility boundary.
9. **T3 trade sample**: 287 pullback trades (2026-03-24 → 2026-06-30) now
   available for S03's qualification-rate planning.

## Not carrying forward

1. **The strategy itself**: no extractable definition exists (T2 UNRESOLVED),
   and the legacy target was S&P 100 pullback vs the rebuild's S&P 500.
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

---

## Provenance

- Legacy clone: read-only, outside the working tree (`~/workspace/s02/`).
  Working tree verified clean; no modifications, no commits, no pushes to
  `arcis-legacy`.
- Nothing copied into this repo except this report, the trial-ledger CSV
  (metadata only — no article text, no market data), and the UNRESOLVED
  incumbent stub.
- Public-repo scan: see PR description.
