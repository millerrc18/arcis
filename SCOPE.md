# SCOPE.md — Arcis Rebuild Charter

| | |
|---|---|
| **Status** | v1.0 (2026-09-27). Binding since the `charter-v1` tag. Every change goes through §6. |
| **Owner** | Ryan decides. |
| **Maintainer** | Claude (CTO) proposes changes; every change lands through §6. |
| **Executor** | Claude Code builds only what §3 marks CORE and Active. |
| **North star** | `docs/reference-architecture.md` describes what good looks like. Nothing in it is in scope unless this file says so. |
| **Evidence base** | `docs/research/research-log.md` (entries R01–R11) |

This file is the boundary of the system. If a component is not in §3, it does not get built.
The old platform grew one reasonable-sounding sprint at a time until nobody could see all of it.
This charter exists so that cannot happen twice.

Items marked **⟨CONFIRM⟩** need Ryan's sign-off before the `charter-v1` tag.

---

## 1. Scope freeze

| Dimension | Frozen value | Notes |
|---|---|---|
| Broker | Alpaca | One broker, one API surface |
| Asset class | US equities | |
| Universe | S&P 500, point-in-time membership; the S&P 100 is reported as a benchmark subset | D-012. Breadth is the main lever on statistical power now that Q1 is forward-only |
| Direction | Long-only | Removes borrow, locates, and short-sale handling |
| Strategies | One: the incumbent pullback-in-uptrend ranker (`incumbent_v1`) | A second strategy is a DEFERRED item, not a roadmap slot |
| Entry | Limit order | |
| Exit | Broker-held bracket (stop and take-profit), plus a time exit | |
| Holding period | 2–15 trading days | |
| Decision cadence | Once per trading day, after the close | Daily bars only; the exact decision time is fixed in PREREGISTRATION.md. Monitoring is continuous: broker-held brackets, resting limit orders, and the 10-minute recorder. Intraday entry decisions are parked in §10 |
| Capital | None until Stage A passes, Stage B's paper plumbing check holds, and the §2.3 limits are set. Then a $2,000 live canary; the $5,000 first real-money stage follows only after the canary's fill-quality check (PREREGISTRATION.md §2.2–2.3; D-021, D-022) | A paper-only lane may run from Step P (D-017) |
| Account type | OPEN (OD-1) | Decided before the live lane |

## 2. Operating principles

1. **Research before capital.** No real money is committed until Q1 authorizes it. A paper-only live lane may be built from Step P, once `prereg-v1` has frozen the strategy and Step 4's ranker exists, so Stage B's execution evidence accrues while Stage A runs. It never holds real-money keys (D-017).
2. **Every component has a simpler incumbent it must beat**, net of costs and after deflation for the number of trials.
3. **No behavioral change without a new release.** No online learning, no autonomous retraining, no edits to a running system's config.
4. **The platform dying is a safe state.** Every open position carries a broker-held stop that outlives the process.
5. **Fail closed.** Missing config, an unknown order state, or stale data blocks new risk. Nothing falls back to a silent default.
6. **Evidence windows are model-specific.** A model is evaluated only on data dated after the latest date in any of its training data, pretraining or fine-tuning.

## 3. Component ledger

**CORE** = build in its simplest form, in step order. **DEFERRED** = may not exist in code until its gate is met. **CUT** = not built; the named replacement covers the need.

Packages are subpackages of `src/arcis/`. CI fails if a subpackage exists that is not listed below with **Active = yes**. Active flips to yes in the first PR of a step, and only after the previous step's "done means" is met (§5).

### 3.1 CORE — research lane

| Component | Package | Step | Active | Simplest form |
|---|---|---|---|---|
| Forward news recorder | `recorder` | 1 | yes | Capture-only polling of Alpaca news for the capture universe (current S&P 500 constituents, a superset of the S&P 100; D-011); append-only; first-seen timestamp per article version; full article text stored by default under the data root (D-018), with fingerprint mode (metadata and hashes only) kept as the fallback if Alpaca refuses in writing; a daily universe snapshot, which is now the only point-in-time membership record |
| Point-in-time data plane | `data` | 3 | no | Alpaca daily bars (2016 onward) and corporate actions; forward membership from the recorder's daily universe snapshots; earnings dates where timing is known. No paid history vendor (D-013), so any pre-tag backtest is exploratory and survivorship-biased |
| Incumbent ranker | `strategy` | 4 | yes | Pure functions implementing the frozen `incumbent_v1`; shared with the live lane |
| Research core | `research` | 4–5 | yes | Conservative cost model (R06); metrics from the daily equity curve; conservative bracket simulator (R05); candidate-day ledger; trial ledger and registry; walk-forward with purge and embargo; version-pinned sequential boundaries |
| Text scoring for Q2/Q3 | `textscore` | after 5 | no | ProsusAI/finbert (ONNX INT8) plus one pinned general instruction model (candidate: Qwen3-14B Q5), schema-constrained, chosen on blinded human labels without looking at returns. Research only; no training code |

### 3.2 CORE — live lane (paper-only from Step P; real money only after Q1 authorizes it)

| Component | Package | Active | Simplest form |
|---|---|---|---|
| Sizer | `sizing` | no | Volatility-targeted equal risk; max positions; sector cap; wash-sale-aware lots; internal no-borrow limit |
| Entry builder | `execution` | no | One limit order with broker-held bracket legs |
| Policy shield | `shield` | no | Separate process; sole holder of trading keys; deterministic pre-trade checks |
| Order state machine | `oms` | no | Deterministic client order IDs; intent persisted before submission; explicit UNKNOWN state; no blind retry; single-instance lease |
| Reconciliation | `recon` | no | REST state as the ledger and the trade-update stream as the fast signal; independent watchdog; four safety modes: NORMAL, BLOCK_NEW_RISK, CANCEL_ONLY, HALTED |
| Decision record | `records` | no | Append-only; schema-validated; exit provenance on every close |

### 3.3 DEFERRED — each enters only through its gate

| Item | Gate (evidence recorded in §9) |
|---|---|
| LLM in the live decision path | Q3 and its strategy test pass, then the live-lane gates |
| Fine-tuning, GRPO, training corpus, training pipeline | Q3 passes, then Q4 is registered and passes |
| Learned ranker challengers (linear, then gradient-boosted trees) | Q1 resolved; each challenger is a registered trial and beats the incumbent net of costs after deflation |
| Temporal neural model | Beats the best tree model net of costs after deflation |
| Convex portfolio optimizer | A second strategy is live, or more than 10 concurrent positions |
| Learned execution | Live fill history, plus position sizes where market impact is measurable |
| Second strategy | Q1 authorizes the live lane and the live lane completes its canary stage |
| Cross-strategy risk reservations | A second strategy passes walk-forward |
| Real-time news streaming (websocket) | Evidence that polling misses information the decision schedule needs |
| Vintage-model historical controls (ChronoBERT, ChronoGPT-Instruct, DatedGPT) | Forward text results justify historical support, and text rights are confirmed |
| Structured earnings-timing feed | Evidence that the earnings exclusion window costs too many opportunities |
| Dashboard or UI | Live lane running, plus a named operator decision that generated reports cannot support |

### 3.4 CUT at this scale

| Not built | Replacement |
|---|---|
| Depth, auction-state, and sequence-gap feeds | Quote sanity check at submit: fresh, uncrossed, spread within bound, not halted |
| Child-order schedules, urgency, impact models | One limit order |
| FIX drop copy | Alpaca trade-update stream plus REST polling |
| Manipulation surveillance | One working order set per symbol; no cancel-replace loops |
| Active-standby failover | Single-instance lease; broker-held stops make downtime safe |
| Dual authorization | Next-session cooling-off plus a tagged commit (§6) |
| Short selling, borrow, locates | Long-only |
| Options, futures, crypto | Out of charter; would require a new charter |
| Multi-agent council, research collectors, alternative-data pipelines | Out of charter; a specific collector needs its own ledger row and gate |

## 4. Invariants

Each invariant is enforced by a test or CI check once its owning package is Active.

| ID | Invariant | Origin | Owner |
|---|---|---|---|
| I-1 | No entry order is valid without broker-held protective legs | Months of live trades with no broker-side stop or target (before old-repo issue 651) | `execution`, `shield` |
| I-2 | Every open position has broker-confirmed, executable protective sell quantity equal to its size, except inside a logged cancel-and-replace. A mismatch blocks new entries, and protection is never cancelled because the process failed | Same; R11 | `recon` |
| I-3 | Every exit records provenance: strategy, bracket, operator, or safety mode. Operator exits are excluded from strategy statistics by default | Manual recovery exits inflated the bootcamp win rate | `records`, `research` |
| I-4 | A trade or candidate record cannot close incomplete. Incomplete records are excluded, never imputed | Only 16 of 320 bootcamp rows had trustworthy exits | `records`, `research` |
| I-5 | Performance comes from one tested metrics module using the daily marked-to-market equity curve | Sharpe overstated ~2.24× (√252 applied to ~50 trades a year) | `research` |
| I-6 | Config is schema-validated with required keys and no unknown keys; a process refuses to start otherwise | A strategy was silently disabled by a missing config key | all |
| I-7 | Data and record stores live outside cloud-sync folders and outside the repo; restores are tested | SQLite on OneDrive caused a full data loss (old-repo issue 181) | all |
| I-8 | No performance comparison runs before the cost model exists | The cost module needed fixing before attribution was valid | `research` |
| I-9 | Tax lots are tracked, and a wash-sale flag is visible to sizing | In a taxable account, buying a name within 30 days of selling it at a loss triggers the wash-sale rule, and this strategy re-enters the same names often | `sizing` |
| I-10 | At most one running instance per process type | Reference architecture's split-brain risk, scaled down | all long-running processes |
| I-11 | Evaluation datasets reject any item dated inside a model's training window | LLM memorization of in-window outcomes | `textscore`, `research` |
| I-12 | No blind exception handling in order or data paths; an unknown outcome becomes an explicit UNKNOWN state | Ghost positions; catch-all handling in order submission (old-repo issue 353) | all |
| I-13 | Article text is retained only from Alpaca's News API (D-018), only under the data root, and never committed (I-7, I-16). Text from any other source, including the old platform's archive, is never retained or reused. No model is trained or fine-tuned on retained text until Alpaca's written confirmation of that right is recorded in §9. A written refusal of storage rights requires removing retained text | R08: public terms do not clearly grant these rights. Storage risk accepted in D-018; training still gated | `recorder`, `textscore` |
| I-14 | LLM scoring fails closed: a schema failure, timeout, or out-of-range value records `LLM_SCORE_UNAVAILABLE`, is never retried improvisationally, and never drives a trade | R10 | `textscore` |
| I-15 | Decisions use the conservative simulator and cost specification. Touch fills, target-first ordering, stop-at-trigger fills, and similar variants are diagnostics only. The one deliberate exception is the open-plus-buffer fill for an entry whose open is at or below the limit, which the specification adopts as primary (D-020) | R05, R06; D-020 | `research` |
| I-16 | Both repositories are public. No credentials, market data, news text, or personal records are ever committed to either | D-014 | all |

## 5. Build order

| Step | Deliverable | Done means |
|---|---|---|
| 0 | This file | Tagged `charter-v1`: every ⟨CONFIRM⟩ item settled, every Priority A research question answered (including RQ-12), no document citing a retired OD, and no entry in §9 still marked proposed |
| 1 | Forward news recorder (sprint S01), storing full text (D-018) | Scheduled polling running; `verify` passing; `gaps` clean for 7 consecutive days |
| 2 | Carry-forward inventory: a read-only pass over the old repo | Report listing every date range ever evaluated; a trial ledger (with daily return series where recoverable); specs recommended for porting; data sources needing point-in-time re-verification; the `incumbent_v1` definition with its hash; and the old fine-tuned model's training-data end date |
| 2m | Pre-tag power measurement (sprint S03) | Minimum detectable effects for PREREGISTRATION.md §2.1 and §3.2 measured on the S&P 500 panel and recorded there; no statistic conditioned on a signal (D-024) |
| 2t | PREREGISTRATION.md completed from the Step 2 report and the Step 2m figures | Tagged `prereg-v1`. This tag starts the forward evidence clock for Q1 (PREREGISTRATION.md §2.1). Step 0 does not require it |
| 3 | Data plane | Alpaca coverage audited (start date, delisted symbols, adjustment behavior); forward membership snapshots ingested; corporate actions; availability timestamps; known-answer tests; the survivorship limits of any pre-tag history documented |
| 4 | Incumbent ranker, cost model, metrics | Ranker reproduces `incumbent_v1` on fixtures; cost model implements R06 with dated fees; metrics pass known-answer tests |
| 5 | Bracket simulator, candidate-day ledger, walk-forward harness, trial registry | Simulator implements the preregistered rules and reports ambiguity rates; harness runs end to end on a synthetic dataset with a known answer; sequential boundaries generated and archived |
| P | Paper-only live lane: `sizing`, `execution`, `shield`, `oms`, `recon`, `records` (D-017) | Starts once Step 4 is done, because orders need the frozen ranker; runs alongside Step 5. Places each day's paper orders after `t_d`, with I-1, I-2, I-10, and I-12 enforced, and holds paper keys only. Its fills are Stage B evidence and never enter the §2.1 test series |
| Q1 | Incumbent test | Exploratory historical check run once; forward information test evaluated at its looks; outcomes recorded in §9 |
| Q2/Q3 | Text questions | Stage A information test at its looks; Stage B strategy test only after Stage A |
| Live | Real-money trading: a $2,000 canary to 60 closed trades, then $5,000, doubling per 150 closed trades to at most $40,000 | The canary only after Stage A passes and Stage B's paper plumbing check holds; the $5,000 stage only after the canary's fill-quality check; the §2.3 kill rule applies throughout (PREREGISTRATION.md §2.2–2.3; D-021, D-022) |

Steps 1 and 2 run in parallel, alongside the written questions to Alpaca (OD-8). PREREGISTRATION.md is completed from the Step 2 report and tagged before Step 3 begins. S03 (Step 2m) runs once S01 has merged and S02 T4 has frozen the incumbent, and finishes before the tag. The tag starts the forward evidence clock for Q1, so Steps 3 to 5 are built while that clock runs.

## 6. Change control

1. **Moving an item between CORE, DEFERRED, and CUT** requires a §9 entry that links the evidence for its gate and a tagged commit, and takes effect no earlier than the next trading session.
2. **New subpackage:** its §3 row must already be merged, with Active = yes, before the PR that creates it. CI enforces this.
3. **Limit or threshold increases** in the live lane follow the same next-session cooling-off.
4. **Every proposal names the gate it moves**, including proposals from Claude. A proposal that moves no gate goes to §10 and is not built.
5. **Sprint size:** at most 10 tasks; no source file over 400 lines; no function over 60 lines (CI-enforced).
6. **Every §9 decision names the documents it supersedes.** A decision that changes the universe, the data plane, the evidence base, or any preregistered quantity is not complete until the affected rows in `docs/research/research-log.md` (Current Decision Index and Supersession Map), PREREGISTRATION.md, and `docs/research/RESEARCH-QUESTIONS.md` are updated in the same PR. CI fails if any tracked document cites an `OD-N` absent from §8, or a `PREREGISTRATION.md` section number that does not exist.

## 7. Carry-forward policy

- Nothing is ported by default. Each port is a §9 decision.
- Eligible for porting: specs (walk-forward, bracket simulator, leakage detector, attribution ledger), the `incumbent_v1` definition, trial history, and data sources that pass point-in-time re-verification.
- Old-platform records are not evidence for Q1–Q3 unless they meet the new record schema and the evidence-window rule.
- The old repository is archived and stays read-only as reference. References to its issues are written as "old-repo issue N" so they never link to this repository's issues.

## 8. Open decisions

| ID | Decision | Needed before | Notes |
|---|---|---|---|
| OD-1 | Account type (cash or margin) | Real-money trading | Ask Alpaca whether an individual account can be cash-only (R11). Either way, enforce an internal no-borrow limit |
| OD-2 | Always-on host | Real-money trading. The recorder and the paper lane may run on the desktop until then; days it is off produce no paper orders (D-017) | Shield and OMS must not share a failure domain with the research/GPU machine once real money is at stake |
| OD-3 | Pinned LLM configuration for Q3 | First scored forward day | Candidate Qwen3-14B Q5; backup Mistral Small 3.1 24B Q4; 12 GB options Gemma 3 12B or Qwen3-8B (R10). Final choice by R10's blinded label test, which needs retained text (OD-8) |
| OD-5 | News fallback if the current plan refuses Alpaca news access | Only if the S01 preflight fails | Do not build a fallback speculatively |
| OD-8 | Written confirmations from Alpaca | Text rights: before any model is trained on retained text; a written refusal requires removing it (D-018). Brokerage behavior: before real-money trading | Question lists in the research log (R08, R11) and RESEARCH-QUESTIONS.md |

**Retired.** OD-4 (Q1 minimum economic effect and first real-money amount) settled by D-022. OD-6 (research universe) settled by D-012. OD-7 (paid historical data vendor) settled by D-013. All three are removed from the table above; no document may cite them as open. Retired IDs are never reused.

## 9. Decision log

An entry marked (proposed) takes effect only once approved. Every proposed entry is approved or withdrawn before `charter-v1`, and none takes effect by default (D-019).

| ID | Date | Decision | Evidence / rationale |
|---|---|---|---|
| D-001 | 2026-09-16 | Rebuild from scratch; the old platform becomes read-only reference | Scope outgrew visibility |
| D-002 | 2026-09-16 | Research (Q2/Q3) decides the LLM's role. LLM scoring for research is CORE and capped; the LLM in the live path is DEFERRED | The old platform never isolated LLM alpha |
| D-003 | 2026-09-16 | The forward news recorder is the first build | Clean LLM evidence only accrues in real time |
| D-004 | 2026-09-16 | Finnhub Premium lapsed on 2026-07-30. The Alpaca News API (Benzinga) is the primary news source, pending the S01 access preflight | Alpaca serves news history back to 2015 plus current news |
| D-005 | 2026-09-16 | Scope freeze per §1 | Ryan approved 2026-09-23, including the once-daily cadence. Intraday entry decisions parked in §10 |
| D-006 | 2026-09-16 | Research log R01–R11 adopted as the evidence base | Deep research with an AI critic review; unverified items are labeled in the log |
| D-007 | 2026-09-16 | (withdrawn, never took effect) Q1 uses a one-time historical holdout plus a separate forward sequential test. **Superseded by D-015 before sign-off:** PREREGISTRATION.md v0.4 removed the gating historical holdout and replaced the portfolio-alpha forward test with the §2.1 cross-sectional information test. Do not approve as written | R04; withdrawn per D-015 |
| D-008 | 2026-09-16 | Q2/Q3 use a whole-universe one-day information test before any strategy test | R07. Ryan approved 2026-09-23 |
| D-009 | 2026-09-16 | The conservative simulator and cost model are the decision specification | R05, R06. Ryan approved 2026-09-23 |
| D-010 | 2026-09-16 | (withdrawn, never took effect) The recorder runs in fingerprint mode until text rights are confirmed. **Superseded by D-018:** full text is stored now, and fingerprint mode remains as the fallback | R08; withdrawn per D-018 |
| D-011 | 2026-09-16 | The recorder captures current S&P 500 constituents | Forward capture cannot be added retroactively. Ryan approved 2026-09-23 |
| D-012 | 2026-09-17 | Research universe is the point-in-time S&P 500, with the S&P 100 reported as a benchmark subset | Ryan's decision; R01 favors breadth, and breadth raises the information ratio that drives statistical power |
| D-013 | 2026-09-17 | No paid historical data vendor for now. Q1 becomes forward-first: a forward information test decides, and any pre-tag backtest is exploratory only | Ryan's decision. Revisit if the forward information test shows a signal worth confirming on clean history |
| D-014 | 2026-09-17 | Both repositories stay public | Ryan's decision. Keeps review possible from chat; makes I-16 load-bearing |
| D-015 | 2026-09-19 | Q1 is decided by a forward cross-sectional information test (PREREGISTRATION.md §2.1), not by portfolio alpha. The pre-tag historical check is non-gating and can only retire (§2.4). Portfolio alpha is monitored, never treated as proof (§2.5). Capital additionally requires the §2.3 risk limits | D-013 removed the paid vendor, so no clean historical holdout exists, and R04's formula gives 80% power at three years and 10% tracking error only near 16% annual alpha. The information test compares qualified against unqualified names within the same date, which this sample size can decide. The charter records plainly that capital would be committed while portfolio-level alpha remains statistically unproven. Ryan approved 2026-09-23 |
| D-016 | 2026-09-23 | No LICENSE file: all rights reserved. The README states it explicitly (S01 T2) | Ryan's decision. Public visibility serves review (D-014), not reuse. Withholding a license is reversible; granting one is not, for copies already taken under it |
| D-017 | 2026-09-23 | A paper-only live lane is built from Step P, so Stage B's execution evidence accrues while Stage A runs. Paper P&L is visible to the operator but is never a scheduled look. The lane may run on the desktop until real money (OD-2) | Ryan's decision. Stage B checks execution fidelity, which does not depend on whether the edge exists, so running it in parallel brings first capital about 12–18 months forward. Amends §1 (capital), §2 principle 1, §3.2, §5 Steps P and Live, §8 OD-1, OD-2 and OD-8, and PREREGISTRATION.md §2.2 |
| D-018 | 2026-09-23 | The recorder stores full article text from Alpaca's News API now, without waiting for written confirmation. Fingerprint mode stays as the fallback. D-010 is withdrawn | Ryan's decision. R08 found that Alpaca's public terms do not clearly grant storage rights; the risk is accepted, not resolved. OD-8a is still sent: a written refusal requires removing retained text and reverting to fingerprint mode, and training or fine-tuning on the text stays blocked until written confirmation (I-13). Amends §3.1, §4 I-13, §5 Step 1, §8 OD-8, S01, S02, and the research log |
| D-019 | 2026-09-23 | No entry marked proposed takes effect by default. Each is approved or withdrawn before `charter-v1`, and Step 0's gate requires that none remain | Ryan's decision. The old rule let proposals enact silently at the tag: D-007 would have enacted a Q1 design that v0.4 had already replaced, and D-010 a storage mode Ryan had not approved. Amends §5 Step 0 and the §9 header |
| D-020 | 2026-09-24 | For an entry whose next-session open is at or below the buy limit, the primary simulated fill is the open plus the adverse buffer, never above the limit. Fill at the limit and no fill are reported sensitivities | Ryan's decision. R05 rule 3 prices these fills at the limit and does not assume the opening price improvement. A resting buy limit above the open is marketable at the open, so it fills at or near the opening price in practice. The departure from R05 rule 3 is deliberate, and I-15 names it as the one exception. Alpaca's handling of queued DAY limits at the open joins the OD-8 brokerage questions. Amends §4 I-15, PREREGISTRATION.md §1.1, RESEARCH-QUESTIONS.md, and the research log's Supersession Map |
| D-021 | 2026-09-24 | Stage B's simulator-fidelity check has two parts. Paper validates plumbing only. Fill quality is measured on a $2,000 live canary (two ~$1,000 positions) that starts only after Stage A passes and runs to 60 closed trades, against preregistered tolerances: mean slippage no worse than the simulator's buffer plus 5 bp, entry fill rate within ±10 percentage points, stop fills within 10 bp on average | Ryan's decision. R11: Alpaca paper "lacks real queue, impact, and live slippage behavior" and validates API state handling, not fill quality, so paper cannot supply the fill evidence §2.2 asked of it. The 5 bp tolerance is a fifth of the 25 bp minimum effect. The canary adds about a year before the $5,000 stage, returning part of D-017's head start; the paper lane still proves the plumbing in advance. Amends §1 (capital), §5 Live, and PREREGISTRATION.md §2.2 |
| D-022 | 2026-09-24 | Settles OD-4 and the §2.3 limits. Minimum effect: 25 bp net per trade. First real-money amount: $5,000. Kill rule: a 25% drawdown, or a one-sided 90% upper bound on live net edge per trade below zero after 150 closed trades. Scaling: each doubling after 150 more closed trades with the estimate holding, capped at $40,000. Canary trades count toward every 150-trade tally, and the drawdown applies from the canary's first trade | Ryan's decision. 25 bp is about 7.4% a year on R01's basis, above R01's 4% gate at 100–150 trades a year. $5,000 keeps positions near $1,000, the bottom of R06's calibrated range. At 150 trades the edge test fires only above ~0.52% average loss per trade on R01's 5% per-trade SD. Canary trades use real-sized orders under the same strategy, so they are valid live evidence. Amends §5 Live, §8 OD-4, and PREREGISTRATION.md §2.1 and §2.3 |
| D-023 | 2026-09-24 | Finnhub is out of scope. D-004 recorded only that Finnhub Premium lapsed on 2026-07-30; a Finnhub Fundamental 1 plan remains active until 2026-10-30 and lapses without renewal. No Finnhub data is archived or used | Ryan's decision. Finnhub's terms require that "all data must be deleted should your subscription to that data ends" and forbid sharing "data or derived results" without written approval. Both repositories are public (D-014), so any Finnhub-derived result Arcis recorded would be redistribution. Fundamental 1 costs $50 a month, more than the edge would earn on the $5,000 stage. The key in the legacy project's `.env` is already invalid (HTTP 401). Amends S02 T8 |
| D-024 | 2026-09-24 | The pre-tag power measurement is its own sprint, S03 (Step 2m): at most five tasks, no ledger row, run after S01 merges and S02 T4 freezes the incumbent, and finished before `prereg-v1`. It measures second moments across all stock-days and simulates power with synthetic effects on randomly chosen stock-days. It never reads `incumbent_v1` or conditions any statistic on a signal | Ryan's decision. PREREGISTRATION.md §2.1 and §3.2 require the minimum detectable effects measured on the actual panel before tagging, but RESEARCH-QUESTIONS.md scheduled the measurement for Step 3, after the tag, and neither S01 nor S02 performed it. A rough calculation puts the 24-month §2.1 effect between about 15 and 32 bp, depending on how often the incumbent qualifies, straddling the 25 bp minimum effect. Splitting historical returns by the incumbent's qualification would be an unregistered look at Q1 (PREREGISTRATION.md §0 rule 5), so S02 T3 now records legacy candidate counts to supply the qualification rate. Amends §5, S02 T3, RESEARCH-QUESTIONS.md, PREREGISTRATION.md §2.1 and §3.2, and the research log's Supersession Map |
| D-025 | 2026-10-04 | The §2.1 planning qualification rate is set as a forward design parameter: 5% of S&P 500 stock-days (≈25 names/day). This supersedes D-024's provision that S02 T3's legacy candidate counts supply the rate: the legacy archive contains only closed trades (287 pullback trades, median 4/day), not daily qualification records, so the exact rate could not be computed. The 5% rate is a CEO design decision for the S&P 500 universe, recorded before `prereg-v1`. | Ryan's decision 2026-10-04. The legacy lower bound is ~4% on S&P 100 (trades ⊂ qualifiers); 5% on S&P 500 scales sensibly and gives 98% power at the 25 bp minimum effect (24-mo MDE 18.3 bp). The 25 bp crossover is at q≈2.9%. Amends D-024, PREREGISTRATION.md §2.1, and the research log's Supersession Map |
| D-026 | 2026-10-05 | Sector-RS banding is absolute Set A on weighted_excess vs SPY (pp): ≥ +5 → 25, 0 to +5 → 15, −5 to 0 → 5, < −5 → 0. Rank-based banding is rejected. | CEO decision 2026-10-05, informed by the independently validated 2016–2024 sector-momentum distribution (P10 −7.39 / P25 −3.98 / P50 −0.58 / P75 +2.60 / P90 +5.91 pp, n=1,123 sector-months; data, provenance, and clean-room repro in `arcis-data/sector_rs/`). +5pp ≈ P88 and −5pp ≈ P19, so the bands split tail/middle sensibly. Rank-based banding was rejected because it discards magnitude — "25 points" would mean something different every month — while absolute thresholds keep the score's meaning constant across regimes. `incumbent_v1.yaml` pins only the band values [25, 15, 5, 0], never the mapping rule, so this is an implementation decision under the CEO-judgment mandate, not a change to a preregistered value; the frozen YAML is untouched. It is recorded in PREREGISTRATION.md §5 as a dated post-tag amendment, which is the designated venue for such decisions. Amends S05 |
| D-027 | 2026-10-05 | Feature lookback windows are pinned: pullback depth = 60 trading sessions; sector-RS weighted-excess windows = 21 / 63 / 126 trading sessions (1m / 3m / 6m). | CEO decision 2026-10-05. `incumbent_v1.yaml` pins the sector-RS blend weights (0.20/0.50/0.30) and band values but no window lengths and no pullback lookback, so this is an implementation decision under the CEO-judgment mandate resolving underspecification, not a change to a preregistered value; the frozen YAML is untouched. Recorded in PREREGISTRATION.md §5 as a dated post-tag amendment. Amends S05 |
| D-028 | 2026-10-05 | Band boundary operators adopt the recovered Sprint F legacy operators, superseding S05's fail-closed boundary decision: pullback −3.0 → 25 and −8.0 → 25 (first-match-wins); distance-to-SMA20 −1.0 → 10; volume ratio 0.8 → 0 (strict < 0.8); IV rank 25 → 0 (strict < 25). | CEO decision 2026-10-05. The frozen YAML states ranges ([−8,−3], [−5,−1], [null, 0.8], [null, 25]) without inclusivities, and S05's initial "YAML silent → raise" reading was wrong: the Sprint F evaluation document (line-cited to the legacy ranker, recovered 2026-10-05) records the actual operators, so adopting them resolves underspecification with recovered ground truth rather than inventing it. Recorded in PREREGISTRATION.md §5 as a dated post-tag amendment. Amends S05 |
| D-030 (proposed) | 2026-10-06 | Settlement-aware SEC charge dates: T+3 before 2017-09-05, T+2 from 2017-09-05 through 2024-05-27, T+1 from 2024-05-28. Supersedes the S07 sprint's T+1-for-all-history prescription. | Developer-proposed correction 2026-10-06, pending CEO sign-off. PREREGISTRATION.md §1.2 says charges apply "≈ settlement"; US settlement was T+3/T+2 before the 2024-05-28 move to T+1, so T+1-for-all-history bills the wrong SEC rate on pre-2024 trades. This resolves underspecification toward the preregistered intent, not a new rule. Flagged in S07 Deviations. Amends S07 |

## 10. Idea parking lot

Good ideas that move no gate are recorded here and not built. Reviewed quarterly.

| Date | Idea | Gate it would need |
|---|---|---|
| 2026-09-23 | Intraday entry decisions: a second decision cadence alongside the daily one | Treated as a second strategy (§3.3): Q1 authorizes the live lane and the canary stage completes. Also needs its own research question (the R01 evidence is daily-bar), an intraday simulator, and a paid real-time data plan. The recorder's 10-minute first-seen timestamps preserve the data to test it |

## 11. Documentation set

`README.md` (entry point and documentation map), `CLAUDE.md` (the rules every Claude Code session reads first), `SCOPE.md`, `PREREGISTRATION.md`, `CHANGELOG.md`, `docs/reference-architecture.md`, `docs/research/` (the research question queue, the research log, and saved reports), `docs/runbooks/`, `docs/sprints/`. Any other top-level document requires a change to this section first.

Every sprint ends by updating three things: the documentation map in `README.md` if it added a document, `CHANGELOG.md`, and its own sprint report.
