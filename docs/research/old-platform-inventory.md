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

## T2 — Incumbent strategy definition: UNRESOLVED

No `incumbent_v1.yaml` exists in the legacy repository. The legacy platform's
own documents conclude YAML extraction was **BLOCKED**:

- `docs/sprints/incumbent_v1_yaml_evaluation.md`
- `docs/sprints/incumbent_v1_yaml_research.md`

Blocking reasons:
1. **LLM-in-the-loop bracket pricing** — the strategy used an LLM to set
   bracket prices at runtime; a static YAML cannot capture this.
2. **Missing `daily_scan` runtime support** — the platform lacked runtime
   infrastructure to execute a YAML-defined daily scan.

Strategy source candidates (identified, not reconciled):

| Path | Role |
|---|---|
| `src/ranking/ranker.py` | Signal ranking |
| `src/platform/strategy_spec.py` | Strategy spec framework |
| `src/platform/_strategy_spec_ranking.py` | Ranking spec internals |
| `src/platform/specs/lazy_prices_v1.yaml` | Lazy-prices ruleset spec |
| `src/platform/specs/post_audit_ruleset_v1.yaml` | Post-audit ruleset spec |
| `src/features/engine.py` | Feature engine |
| `src/features/pullback_logistic.py` | Pullback logistic model |
| `src/services/scan_service.py` | Scan service |
| `docs/specs/strategy-schema.md` | Strategy schema documentation |

**S&P 100 assumptions flagged** (SCOPE D-012): every threshold in these
candidates was tuned against mega-cap S&P 100 liquidity. Any carried-forward
parameter must be re-examined against S&P 500 breadth, never adopted silently.

`config/incumbent_v1.yaml` in this repo records this UNRESOLVED state.
Resolution requires the local 37GB archive (local-only commits, stashes).

---

## T3 — Reconciliation against what actually ran: NOT PERFORMABLE (GitHub side)

T3 requires sampling ≥20 recorded decisions (signals, candidate lists, orders)
and checking each against extracted rules. **No machine-readable decision
records exist in the GitHub clone:**

- Zero database files tracked (`.db`, `.sqlite`, `.duckdb`).
- `src/shadow_trading/` (25 files) is code-only; data lived in local PostgreSQL.
- `data/corpus/stage1-001/entries.jsonl` (67,528 entries) not in clone.
- `docs/archive/sprint-receipts/` contains narratives, no decision logs.

**Finding:** the frozen definition would rest on documents alone — which is how
a rule that was never implemented becomes canon. The ≥20-decision sample must
come from the local archive's databases once transferred. This is recorded as
a finding, not a gap to guess across.

---

## T4 — Freeze: DEFERRED (no definition to freeze)

T4 requires normalizing `config/incumbent_v1.yaml` and recording its SHA-256.
With T2 UNRESOLVED, there is nothing to freeze. The freeze — and the
`tools/` hash-recomputation script — will be completed once the incumbent
definition is resolved from the local archive. This is the correct outcome:
freezing an invented definition would be worse than freezing nothing.

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

1. **The rigor harness** (T7.1, T7.2, T7.7): walk-forward R1–R8 + CPCV +
   trials/DSR, as a clean-room reimplementation. This is the anti-self-deception
   machinery the charter demands, already debugged once.
2. **Bracket math** (T7.3): deterministic pct/ATR stop/target with floor/cap.
3. **Attribution schema** (T7.5) and **cost calibration loop** (T7.6): templates
   for honest LLM-value and net-of-cost measurement.
4. **Regime scenario catalog** (T7.4): 13 scenarios as a stress-test checklist.
5. **Trial ledger** (`docs/research/trial-ledger.csv`): the 13-configuration
   record, feeding the Deflated Sharpe audit.
6. **Date-range union** (T6): the contamination region for PREREGISTRATION §2.4.
7. **Model training cutoff** (T9): 2026-04-28 — the Q3 eligibility boundary.

## Not carrying forward

1. **The strategy itself**: no extractable definition exists (T2 UNRESOLVED),
   and the legacy target was S&P 100 pullback vs the rebuild's S&P 500.
2. **Any Finnhub data or derived artifacts** (T8): license-restricted, must stay out.
3. **LLM-in-the-loop bracket pricing**: not portable to a static definition.
4. **yfinance as an unexamined price source**: reusable only after a
   corporate-action/survivorship audit.
5. **Any code**: clean-room reimplementation only, per S02 ground rules.

## Open questions for the CEO

1. **T2**: The incumbent definition is UNRESOLVED. Do you want to (a) wait for
   the local archive and attempt extraction from local-only commits/stashes,
   (b) declare the legacy strategy unrecoverable and define incumbent_v1 from
   the documented rulesets (`lazy_prices_v1.yaml`,
   `post_audit_ruleset_v1.yaml`) with explicit UNRESOLVED markers, or
   (c) something else?
2. **T3**: No recorded decisions exist GitHub-side. Should the ≥20-decision
   reconciliation sample come from the local archive databases, or is the
   document-only freeze acceptable with a written rationale?
3. **T4**: Freeze is deferred until T2 resolves. Confirm the freeze hash goes
   into PREREGISTRATION.md §1 at that time.
4. **T7**: Confirm the seven specs are worth SCOPE.md §9 `(proposed)` entries
   for clean-room reimplementation, and their priority order.
5. **T9**: The model weight hash is not in the repo. Is the corpus manifest
   hash (`43c2e3ed…`) sufficient for Q3 eligibility, or must the `.gguf` hash
   be recovered from the local archive?

---

## Provenance

- Legacy clone: read-only, outside the working tree (`~/workspace/s02/`).
  Working tree verified clean; no modifications, no commits, no pushes to
  `arcis-legacy`.
- Nothing copied into this repo except this report, the trial-ledger CSV
  (metadata only — no article text, no market data), and the UNRESOLVED
  incumbent stub.
- Public-repo scan: see PR description.
