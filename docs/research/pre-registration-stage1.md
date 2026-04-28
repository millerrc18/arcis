# Pre-Registration — Stage 1 Walk-Forward Validation

**Status:** DRAFT — operator input required for sections marked `[TODO operator]`

**Filing date:** 2026-04-28 (locked at commit time — see git history of this file for any subsequent amendments)

**Purpose:** This document commits Halcyon Lab / Arcis to a hypothesis, success criteria, and analysis methodology BEFORE running the Stage 1 walk-forward backtest. It binds future-us to a pre-defined verdict on whether the system has demonstrated edge, instead of retrofitting narrative around whatever results show up.

**Why now:** Sprint 1.A.x + 1.A.x.1 fixed the **universe-correctness** layer (no survivorship bias, no ticker-rename bias for Tier A+B events). The next class of bias to close is **researcher degrees-of-freedom** — the family of subtle ways an honest researcher can subconsciously massage a "passing" result out of marginal data. Pre-registration is the standard tool for closing that gap.

**Binding clause:** Once this document is committed to git on `main`, the success and failure thresholds are fixed. Subsequent amendments require their own commit with explicit rationale, and any amendment made AFTER seeing intermediate backtest results is documented as a methodology change (which weakens the strength of the conclusion accordingly).

---

## Section 1 — Hypothesis (operator-authored)

> What edge does Arcis claim to have, in 1-3 sentences?

**[TODO operator]** Free-form. Examples of well-formed hypotheses (NOT what to commit — examples only):
- *"Arcis identifies SP100 pullback-in-uptrend setups whose 5-day forward return outperforms a market-cap-weighted SP100 buy-and-hold by ≥0.X% per trade after costs, consistently across regime conditions."*
- *"The fine-tuned LLM (halcyon-v1) ranks SP100 setup candidates such that the top-decile candidates produce statistically significantly better forward returns than randomly-selected SP100 candidates over a multi-year horizon."*
- *"Arcis's combined ranker + LLM scoring identifies asymmetric-payoff trade setups (positive expected value with bounded downside) at a rate that exceeds the deterministic ranker alone, justifying the LLM cost."*

The hypothesis should be:
- **Falsifiable** — could be refuted by the data
- **Specific** — references a measurable quantity, not "good performance"
- **Pre-committed** — would NOT be edited based on what the data shows

**Operator-committed hypothesis (2026-04-28):**

> The pullback-in-uptrend strategy executed via Arcis's signal pipeline produces excess Sharpe ≥ 0.5 (at t ≥ 2.0) vs SP100 buy-and-hold over 150+ OOS trades in the walk-forward window, measured on actual trade returns (entry to exit per system rules). Alpha must be attributable to the pullback entry timing rather than universe selection or market beta — verified by tracking the deterministic-ranker-only shadow portfolio in parallel as a secondary diagnostic.

This hypothesis pre-commits the following downstream choices (so the §4 sub-decisions are already partially settled):
- §4.1 primary metric = (a) Excess Sharpe vs SP100 buy-and-hold
- §4.2 primary threshold = (a) ≥ 0.5
- §4.3 statistical-significance threshold = (a) t ≥ 2.0
- §4.4 sample-size minimum = (a) ≥ 150 OOS trades

The "deterministic-ranker-only shadow portfolio in parallel" is captured under §6 subgroup analyses as a *secondary diagnostic*, not a primary criterion — failing the secondary diagnostic doesn't fail the primary hypothesis, but a passing primary with a failing secondary triggers a deeper investigation (the LLM-edge question becomes the next sprint's focus).

---

## Section 2 — Pre-specified universe & data

These are settled by Sprint 1.A.x + 1.A.x.1 (no operator input needed):

- **Universe:** SP100 point-in-time via `pit.get_sp100_at(<as_of>)`. Tier A + Tier B corp-action coverage (PCLN/BKNG, KRFT/KHC, UTX+RTN/RTX, EMC, YHOO, CELG, S, FB/META).
- **Coverage range:** 2015-03-19 → 2026-04-28 (per `pit.get_data_range()`).
- **Data source:** `data/reference/sp100_history.json` regenerated 2026-04-28 from Wikipedia + curated `_CURATED_CHANGES`. Idempotent.
- **Out-of-coverage handling:** `UniverseDataMissing` raised (no silent fallback).
- **Pre-2015 backfill:** out of scope (#799 — separate sprint). Walk-forward windows fully inside coverage range.

**[NO operator input needed]**

---

## Section 3 — Walk-forward methodology

### 3.1 — Walk-forward style: **(a) Anchored expanding window** ✓ committed

Train on all data up to T, test on T → T+N, advance T forward, retrain on all-data-up-to-new-T. Maximum information per fit. Preferred when sample size is the binding constraint, which it is for SP100 with ~11 years of coverage.

### 3.2 — Train/test split timeline: **(b) Walk-forward in N folds** ✓ committed

Split test period into N successive folds, train-from-start before each fold (anchored expanding from §3.1). Balances fold-by-fold readability with statistical power. CPCV remains the formal gate's statistical arbiter (`src/methods/promotion_gate.py`); this Stage 1 doc uses simpler walk-forward.

### 3.3 — Number of test folds: **(c) 8 folds × ~4 months each** ✓ committed

From 2023-09 onward through end of coverage. Expected trades per fold: ~150/8 ≈ 19, above the §3.5 underpowered threshold.

### 3.4 — Embargo / purge: **(c) 21 trading days (~1 month)** ✓ committed

Full earnings-cycle buffer. Earnings cycles can leak across train/test if features include forward-looking metrics; one month is safe.

### 3.5 — Underpowered-fold reporting (operator addition)

**Rule:** Folds with **fewer than 15 trades** are flagged as `underpowered` and reported **separately**, not merged into the aggregate. They are excluded from the primary Sharpe / t-statistic calculations. They appear in the report as a footnote with their own count, return, and a "underpowered: insufficient sample for inference" disclosure.

Why: Without this rule, a fold that happens to produce only 3 trades with high Sharpe (e.g., quiet markets when no setups fire) can dominate or distort the aggregate when averaged in. The 15-trade floor reflects that conclusions about Sharpe / win-rate require sample sizes too small to support a claim.

**Implementation note for Sprint 1.B:** the walk-forward harness must compute trades-per-fold and apply the `underpowered` flag at compute time, not after seeing aggregate results.

---

## Section 4 — Success criteria

### 4.1 — Primary metric

`[OPERATOR PICK ONE]`

- **(a) Excess Sharpe vs SP100 buy-and-hold** — uses `src/analytics/canonical_sharpe.py` with `mode='spy_relative'`. Pure alpha measure.
- **(b) Raw Sharpe** — annualized return / annualized vol. Doesn't control for market beta.
- **(c) PSR (Probabilistic Sharpe Ratio)** — Sharpe + uncertainty. Already implemented in `src/methods/psr.py`. Statistically rigorous but harder to communicate.
- **(d) MinTRL** (Minimum Track-Record Length) — answers "how many more trades to reach a target Sharpe with confidence?" Not a primary metric per se; better as a power assessment companion.

PM rec: **(a) Excess Sharpe vs SP100** — controls for the market exposure that survivorship-corrected SP100 buy-and-hold would have given for free. Most defensible alpha claim.

### 4.2 — Primary success threshold

`[OPERATOR PICK ONE — depends on 4.1]`

If 4.1 = (a) Excess Sharpe vs SP100:
- **(a) ≥ 0.5** — SD#25 target as already specified in CLAUDE.md / methodology-toolkit.md
- **(b) ≥ 0.3** — More permissive; matches "small but consistent edge"
- **(c) ≥ 0.7** — Strict; matches "investment-grade alpha"

PM rec: **(a) ≥ 0.5** — already operator-specified as the SD#25 target. Don't move goalposts.

### 4.3 — Statistical-significance threshold

`[OPERATOR PICK ONE]`

- **(a) t-statistic ≥ 2.0** (one-sided) — ~2.5% null-rejection probability. SD#25's stated threshold.
- **(b) t-statistic ≥ 1.65** — 5% null-rejection (one-sided). Lower bar.
- **(c) t-statistic ≥ 2.6** — 0.5% null-rejection. Stricter.
- **(d) Use PSR ≥ 0.95** instead of t — probabilistic Sharpe exceeding 0.5 with 95% confidence.

PM rec: **(a) t ≥ 2.0** — matches SD#25 target.

### 4.4 — Sample-size minimum

`[OPERATOR PICK ONE]`

- **(a) ≥ 150 OOS trades** — SD#25's stated target
- **(b) ≥ 100 OOS trades** — Smaller; permissible for smaller-edge strategies
- **(c) ≥ 250 OOS trades** — Larger; tighter sampling distribution
- **(d) Use Bailey-LdP MinTRL** — sample-size requirement is data-driven from observed Sharpe and vol; if observed Sharpe is high, fewer trades suffice; if marginal, more required.

PM rec: **(d) MinTRL** — already implemented in `src/analytics/instrumentation_filter.py`. Adapts to actual observed strength rather than a fixed number.

### 4.5 — Drawdown ceiling: **(a) Max drawdown ≤ 15%** ✓ committed

Conservative — suitable for live capital. Operator override of PM rec (b ≤ 20%) toward stricter posture.

### 4.6 — Combination operator: **(c) `promotion_gate.py` 4-of-5 vote AS FORMAL PASS, AND (a) ALL §4.x pass AS SANITY** ✓ committed

The formal gate is `src/methods/promotion_gate.py`'s 4-of-5 vote (PSR, PBO, MC permutation, White RC, IS-vs-OOS). The sanity supplement requires that §4.2–4.5 ALL pass simultaneously. A passing gate with a failing sanity check (or vice versa) blocks promotion until the inconsistency is resolved.

---

## Section 5 — Failure criteria (the binding part)

These commit you in advance to abandoning specific paths if results show specific patterns. Without explicit failure criteria, "abandon" never happens — only "tweak and re-run."

### 5.1 — Hard fail (strategy abandoned, no further iteration on this approach) ✓ committed

- **(a) Sharpe < 0** over OOS sample — strategy is anti-edge
- **(b) Significance test t-statistic < 0** — strategy is opposite of hypothesized direction
- **(d) Sample-size below 50 OOS trades** — insufficient power to conclude anything; methodology fails, not strategy
- **(e) Promotion gate fails 5-of-5** — confirmation when (a)/(b)/(d) doesn't fire but every gate test rejects

(c) "Max drawdown > 35%" was **dropped** from the hard-fail list. Rationale: §4.5 already requires drawdown ≤ 15% for success. A drawdown of 16-35% fails success via §4.5 and lands in §5.2 soft-fail; a drawdown >35% additionally hits §5.1(a) anti-edge in nearly all cases. The standalone tripwire is redundant with the §4.5 cascade and would only matter in the edge case of "high Sharpe + huge drawdown" which itself indicates a methodology bug worth investigating, not a clean abandonment.

### 5.2 — Soft fail (no live deploy, but worth one more iteration) ✓ committed

- **(b) Sharpe ≥ 0.3 but t < 2** — Promising but insufficient sample; gather more data
- **(c) Sharpe + drawdown both pass but only in 2-3 of 8 folds** — regime-dependent, doesn't generalize

Implicit catch-all: anything failing §4 success criteria but not hitting §5.1 hard-fail conditions lands here.

### 5.3 — Forbidden actions after seeing results

These are tripwires — committed in advance — to prevent the most common forms of researcher-degree-of-freedom abuse.

**Operator-accepted as binding (2026-04-28):**

- ❌ **Re-running with different `arcis:` model versions until one passes** — the model is part of the test, not a free parameter
- ❌ **Cherry-picking time windows** ("excluding 2020 because pandemic") — pre-committed window stands
- ❌ **Cherry-picking subgroups** ("it works in tech but fails in financials, so we'll only trade tech") — unless tech-only was pre-committed in §6
- ❌ **Adjusting cost model post-hoc** until results improve
- ❌ **Adding ad-hoc filters** ("drop trades with unusual implied vol") that weren't pre-specified
- ❌ **Lowering the success threshold** because it's "close to passing"

These do NOT prevent legitimate methodology fixes (e.g., a confirmed bug in feature computation, a mis-specified cost). Legitimate fixes require:
1. The fix is justified by something OTHER than wanting better results
2. The fix is committed to the codebase under its own PR
3. After the fix, the entire pre-registered protocol is re-run from scratch

---

## Section 6 — Pre-specified subgroup analyses

Subgroups that we commit to looking at IN ADVANCE. Reporting subgroup outcomes is fine; cherry-picking the best one is not.

**Operator-committed subgroups (2026-04-28): (a) + (b) + (c) + (e) — four subgroups**

- **(a) By regime** (Traffic Light: GREEN / YELLOW / RED via `src/features/traffic_light.py`) — tests whether Traffic Light gating adds value
- **(b) By calendar year** (2024, 2025, 2026) — tests whether the strategy is regime-stable across years
- **(c) By GICS sector** (top 5 sectors — Tech, Health Care, Financials, Communication Services, Consumer Discretionary) — tests whether alpha is broad-based or sector-concentrated
- **(e) By LLM conviction** (low / medium / high tier per `arcis:v1.0.0`'s output) — tests whether LLM conviction is calibrated and adds rank signal

(d) volatility regime and (f) trade duration are NOT pre-specified for this Stage 1 test. They may be added to a future pre-registration if a follow-up sprint warrants it.

**Plus** the secondary diagnostic from §1: deterministic-ranker-only shadow portfolio in parallel — pre-committed comparator that runs alongside primary, used to attribute alpha to LLM-vs-ranker.

⚠️ **Subgroups are EXPLORATORY** (see §8.1) — reported and discussed, but **NOT used for the binary pass/fail decision**. They do not enter the multiple-testing correction count.

---

## Section 7 — What does NOT count as success

A list of common failure modes that, if they occur, mean we DO NOT declare success even if the headline numbers pass.

**Operator-accepted as binding (2026-04-28):**

- ❌ Headline Sharpe passes but only 1-2 outlier trades drive the entire P&L
- ❌ Most P&L comes from a single concentrated month/regime
- ❌ Best-performing fold is >2x the next-best fold (regime-dependent, not generalizable)
- ❌ LLM conviction is uncorrelated with outcome (model doesn't add value over the deterministic ranker)
- ❌ Win rate < 35% but Sharpe passes via tail trades (high concentration risk in live trading)

These are **diagnostic checks** — applied after the primary result is computed but committed in advance. If any fire, the success claim is qualified.

---

## Section 8 — Statistical methodology

Most of this is settled by existing infrastructure (the methodology toolkit). Operator confirms which gate is binding:

### 8.1 — Multiple-testing correction: **(c) None — single primary metric** ✓ committed

§4.1 commits to a single primary metric (excess Sharpe vs SP100). No multiple-testing correction is needed for the **primary** decision because there is one test.

**Subgroup analyses are EXPLORATORY** (§6 commitment): the four subgroups (regime, year, sector, LLM conviction) plus the deterministic-ranker secondary diagnostic are **reported but NOT used for the binary pass/fail decision**. They do **not** enter the multiple-testing correction count.

If a future sprint elevates a subgroup to a primary criterion (e.g., "the strategy must pass in EVERY regime"), that future sprint's pre-registration must add the multiple-testing correction. This Stage 1 deliberately keeps the bar single: pass or fail on the aggregate excess Sharpe + significance + DD ceiling + sample size.

### 8.2 — Promotion gate: **(a) `src/methods/promotion_gate.py` 4-of-5 vote** ✓ committed

Formal gate as already specified in `docs/methodology-toolkit.md`. Gates: PSR, PBO, MC permutation, White RC, IS-vs-OOS. Already implemented + tested + tied to the promotion-decision flow.

---

## Section 9 — Pre-commit verification

**Operator-confirmed 2026-04-28 (Ryan Miller):**

- [x] All TODO sections filled in
- [x] Hypothesis is falsifiable, specific, and pre-committed (operator-authored verbatim — see §1)
- [x] Success thresholds bind — operator commits not to lower them after seeing results
- [x] Failure thresholds bind — operator commits to abandon strategy if §5.1 fires
- [x] Forbidden actions list (§5.3) is accepted as binding
- [x] Pre-specified subgroups (§6) are committed — no post-hoc subgroup discovery

This document is binding as of the commit date. Any subsequent amendment requires its own commit with rationale, and amendments made AFTER intermediate backtest results are visible are documented as methodology changes (which weakens the strength of the resulting conclusion accordingly).

---

## Sprint 1.B kick-off readiness

Once this document is committed to `main`, Sprint 1.B (T22 methodology wiring) is unblocked from a pre-registration standpoint. The actual Sprint 1.B PR's job is to wire `src/methods/promotion_gate.py` from the shelf into the production promotion path so that the test we just pre-registered is the one that fires automatically when a new model version is trained.

---

## Reference docs

- `docs/methodology-toolkit.md` — decision tree + worked example for the methodology shelf modules
- `src/methods/promotion_gate.py` — 4-of-5 vote orchestrator
- `src/methods/cpcv.py` — purged walk-forward CV
- `src/methods/psr.py` — PSR / DSR / MinTRL
- `src/analytics/canonical_sharpe.py` — Sharpe single-source-of-truth
- `src/analytics/instrumentation_filter.py` — MinTRL power assessment
- `src/universe/pit.py` — Sprint 1.A.x + 1.A.x.1 PIT loader (Tier A + B corp-action coverage)
