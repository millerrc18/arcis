# SCOPE.md — Arcis Rebuild Charter

| | |
|---|---|
| **Status** | DRAFT v0.7 (2026-09-17). Binding once tagged `charter-v1`. |
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
| Decision cadence | Once per trading day, after the close ⟨CONFIRM⟩ | Daily bars only; the exact decision time is fixed in PREREGISTRATION.md |
| Capital | None until Q1 authorizes the live lane and the live-lane gates pass | Paper only before then |
| Account type | OPEN (OD-1) | Decided before the live lane |

## 2. Operating principles

1. **Research before plumbing.** The live lane is not built until Q1 authorizes it.
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
| Forward news recorder | `recorder` | 1 | yes | Capture-only polling of Alpaca news for the capture universe (current S&P 500 constituents, a superset of the S&P 100; D-011); append-only; first-seen timestamp per article version; fingerprint mode (metadata and hashes, no article text) until text rights are confirmed (OD-8); a daily universe snapshot, which is now the only point-in-time membership record |
| Point-in-time data plane | `data` | 3 | no | Alpaca daily bars (2016 onward) and corporate actions; forward membership from the recorder's daily universe snapshots; earnings dates where timing is known. No paid history vendor (D-013), so any pre-tag backtest is exploratory and survivorship-biased |
| Incumbent ranker | `strategy` | 4 | no | Pure functions implementing the frozen `incumbent_v1`; shared with the live lane |
| Research core | `research` | 4–5 | no | Conservative cost model (R06); metrics from the daily equity curve; conservative bracket simulator (R05); candidate-day ledger; trial ledger and registry; walk-forward with purge and embargo; version-pinned sequential boundaries |
| Text scoring for Q2/Q3 | `textscore` | after 5 | no | ProsusAI/finbert (ONNX INT8) plus one pinned general instruction model (candidate: Qwen3-14B Q5), schema-constrained, chosen on blinded human labels without looking at returns. Research only; no training code |

### 3.2 CORE — live lane (not started until Q1 authorizes it)

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
| I-13 | No article text, embeddings, or text-trained models are retained until Alpaca's written confirmation of those rights is recorded in §9 | R08: public terms do not clearly grant these rights | `recorder`, `textscore` |
| I-14 | LLM scoring fails closed: a schema failure, timeout, or out-of-range value records `LLM_SCORE_UNAVAILABLE`, is never retried improvisationally, and never drives a trade | R10 | `textscore` |
| I-15 | Decisions use the conservative simulator and cost specification. Touch fills, target-first ordering, stop-at-trigger fills, and similar variants are diagnostics only | R05, R06 | `research` |
| I-16 | Both repositories are public. No credentials, market data, news text, or personal records are ever committed to either | D-014 | all |

## 5. Build order

| Step | Deliverable | Done means |
|---|---|---|
| 0 | This file and PREREGISTRATION.md | Both tagged (`charter-v1`, `prereg-v1`) |
| 1 | Forward news recorder (sprint S01), in fingerprint mode | Scheduled polling running; `verify` passing; `gaps` clean for 7 consecutive days |
| 2 | Carry-forward inventory: a read-only pass over the old repo | Report listing every date range ever evaluated; a trial ledger (with daily return series where recoverable); specs recommended for porting; data sources needing point-in-time re-verification; the `incumbent_v1` definition with its hash; and the old fine-tuned model's training-data end date |
| 3 | Data plane | Alpaca coverage audited (start date, delisted symbols, adjustment behavior); forward membership snapshots ingested; corporate actions; availability timestamps; known-answer tests; the survivorship limits of any pre-tag history documented |
| 4 | Incumbent ranker, cost model, metrics | Ranker reproduces `incumbent_v1` on fixtures; cost model implements R06 with dated fees; metrics pass known-answer tests |
| 5 | Bracket simulator, candidate-day ledger, walk-forward harness, trial registry | Simulator implements the preregistered rules and reports ambiguity rates; harness runs end to end on a synthetic dataset with a known answer; sequential boundaries generated and archived |
| Q1 | Incumbent test | Exploratory historical check run once; forward information test evaluated at its looks; outcomes recorded in §9 |
| Q2/Q3 | Text questions | Stage A information test at its looks; Stage B strategy test only after Stage A |
| Live | Live lane, paper first | Only after Q1 authorizes it (PREREGISTRATION.md §2) |

Steps 1 and 2 run in parallel, alongside the written questions to Alpaca (OD-8). PREREGISTRATION.md is completed from the Step 2 report and tagged before Step 3 begins. The tag starts the forward evidence clock for Q1, so Steps 3 to 5 are built while that clock runs.

## 6. Change control

1. **Moving an item between CORE, DEFERRED, and CUT** requires a §9 entry that links the evidence for its gate and a tagged commit, and takes effect no earlier than the next trading session.
2. **New subpackage:** its §3 row must already be merged, with Active = yes, before the PR that creates it. CI enforces this.
3. **Limit or threshold increases** in the live lane follow the same next-session cooling-off.
4. **Every proposal names the gate it moves**, including proposals from Claude. A proposal that moves no gate goes to §10 and is not built.
5. **Sprint size:** at most 10 tasks; no source file over 400 lines; no function over 60 lines (CI-enforced).

## 7. Carry-forward policy

- Nothing is ported by default. Each port is a §9 decision.
- Eligible for porting: specs (walk-forward, bracket simulator, leakage detector, attribution ledger), the `incumbent_v1` definition, trial history, and data sources that pass point-in-time re-verification.
- Old-platform records are not evidence for Q1–Q3 unless they meet the new record schema and the evidence-window rule.
- The old repository is archived and stays read-only as reference. References to its issues are written as "old-repo issue N" so they never link to this repository's issues.

## 8. Open decisions

| ID | Decision | Needed before | Notes |
|---|---|---|---|
| OD-1 | Account type (cash or margin) | Live lane | Ask Alpaca whether an individual account can be cash-only (R11). Either way, enforce an internal no-borrow limit |
| OD-2 | Always-on host | Live lane (the recorder may run on the desktop until then) | Shield and OMS must not share a failure domain with the research/GPU machine |
| OD-3 | Pinned LLM configuration for Q3 | First scored forward day | Candidate Qwen3-14B Q5; backup Mistral Small 3.1 24B Q4; 12 GB options Gemma 3 12B or Qwen3-8B (R10). Final choice by R10's blinded label test, which needs retained text (OD-8) |
| OD-4 | Q1 minimum economic effect and the first real-money amount | `prereg-v1` tag | See PREREGISTRATION.md §2. Data subscriptions the live system needs count as running costs |
| OD-5 | News fallback if the current plan refuses Alpaca news access | Only if the S01 preflight fails | Do not build a fallback speculatively |
| OD-8 | Written confirmations from Alpaca | Text rights: before any text is retained. Brokerage behavior: before the live lane | Question lists in the research log (R08, R11) and RESEARCH-QUESTIONS.md |

## 9. Decision log

Entries marked (proposed) take effect at `charter-v1`.

| ID | Date | Decision | Evidence / rationale |
|---|---|---|---|
| D-001 | 2026-09-16 | Rebuild from scratch; the old platform becomes read-only reference | Scope outgrew visibility |
| D-002 | 2026-09-16 | Research (Q2/Q3) decides the LLM's role. LLM scoring for research is CORE and capped; the LLM in the live path is DEFERRED | The old platform never isolated LLM alpha |
| D-003 | 2026-09-16 | The forward news recorder is the first build | Clean LLM evidence only accrues in real time |
| D-004 | 2026-09-16 | Finnhub Premium lapsed on 2026-07-30. The Alpaca News API (Benzinga) is the primary news source, pending the S01 access preflight | Alpaca serves news history back to 2015 plus current news |
| D-005 | 2026-09-16 | (proposed) Scope freeze per §1 | Pending Ryan's confirmation |
| D-006 | 2026-09-16 | Research log R01–R11 adopted as the evidence base | Deep research with an AI critic review; unverified items are labeled in the log |
| D-007 | 2026-09-16 | (proposed) Q1 uses a one-time historical holdout plus a separate forward sequential test | R04 |
| D-008 | 2026-09-16 | (proposed) Q2/Q3 use a whole-universe one-day information test before any strategy test | R07 |
| D-009 | 2026-09-16 | (proposed) The conservative simulator and cost model are the decision specification | R05, R06 |
| D-010 | 2026-09-16 | (proposed) The recorder runs in fingerprint mode until text rights are confirmed | R08 |
| D-011 | 2026-09-16 | (proposed) The recorder captures current S&P 500 constituents | Forward capture cannot be added retroactively |
| D-012 | 2026-09-17 | Research universe is the point-in-time S&P 500, with the S&P 100 reported as a benchmark subset | Ryan's decision; R01 favors breadth, and breadth raises the information ratio that drives statistical power |
| D-013 | 2026-09-17 | No paid historical data vendor for now. Q1 becomes forward-first: a forward information test decides, and any pre-tag backtest is exploratory only | Ryan's decision. Revisit if the forward information test shows a signal worth confirming on clean history |
| D-014 | 2026-09-17 | Both repositories stay public | Ryan's decision. Keeps review possible from chat; makes I-16 load-bearing |

## 10. Idea parking lot

Good ideas that move no gate are recorded here and not built. Reviewed quarterly.

| Date | Idea | Gate it would need |
|---|---|---|
| — | — | — |

## 11. Documentation set

`README.md` (entry point and documentation map), `CLAUDE.md` (the rules every Claude Code session reads first), `SCOPE.md`, `PREREGISTRATION.md`, `CHANGELOG.md`, `docs/reference-architecture.md`, `docs/research/` (the research question queue, the research log, and saved reports), `docs/runbooks/`, `docs/sprints/`. Any other top-level document requires a change to this section first.

Every sprint ends by updating three things: the documentation map in `README.md` if it added a document, `CHANGELOG.md`, and its own sprint report.
