# Sprint D2: Attribution Resolver Methodology Audit

**Authority:** SD#41 REVISED `docs/research/SD-41-REVISED-diagnostic-first-plan.md`
**Effort:** 3-4 hours (primarily investigation + documentation; code changes depend on findings)
**Branch:** `audit/attribution-resolver`
**Tag on merge:** none (audit doc only) — follow-up fix sprint if bugs found
**Priority:** CRITICAL — LLM value claim is either confirmed or destroyed by this
**Ralph-loop status:** First draft

---

## Goal

Determine whether the attribution resolver's reported "100% loss on 1,600 resolved pairs" is:

**(A)** Genuine evidence the LLM is an extraordinary filter (rejecting 100% losers)
**(B)** A methodology bug in the ranker-only counterfactual (bracket parameters produce structural losses)
**(C)** Pre-filter quality skew (rejected trades are systematically worst, amplified by conservative bracket choice)

Produce `docs/research/attribution-resolver-audit.md` classifying the finding. If (B) or (C), open a follow-up fix sprint. Until this audit closes, **no attribution claim may be cited in training documentation, investor materials, or strategy decisions.**

This is an audit sprint, not a feature sprint. Most of the deliverable is a written analysis document.

---

## Background Context for CC

**The problem discovered in forensic analysis:**

| Pair Type | Total | Resolved | Winners (ranker-only) | Losers (ranker-only) |
|---|---|---|---|---|
| llm_rejected | 1,582 | 1,406 | **0** | **1,406** |
| both_taken | 118 | 114 | **0** | **114** |
| unknown | 125 | 80 | **0** | **80** |

Zero winners across 1,600 resolutions. Average ranker-only P&L on rejected pairs: -5.24%. On both_taken pairs: -5.29%.

**Why this is suspicious:**
Under random chance, a ranker strategy in a bull-market period (SPY +12% in 22 days) should produce roughly 55-65% winners. Zero winners is statistically implausible unless (a) the LLM filter is extraordinary OR (b) the simulation is biased.

**The three hypotheses to distinguish:**

- **A (LLM genius):** The LLM correctly rejected 1,406 trades that would have all lost on the ranker-only bracket scheme. Requires extraordinary evidence.
- **B (methodology bug):** The ranker-only bracket is systemically unfavorable. Examples: too-tight target / too-wide stop; mandatory loss-label on timeout; using stop at entry as "loss" regardless of intraday path; simulation exits at worst-of-day instead of close.
- **C (pre-filter skew):** Rejected trades are the lowest-conviction setups. Combined with (B) or with realistic brackets, they naturally fail more often. The 100% failure rate is still suspicious but less so.

Full context: `docs/research/deep-research/Arcis-Forensic-Analysis-2026-04-16.pdf` Section 8.

---

## Pre-Flight Checks

1. **Locate attribution resolver source:**
   ```bash
   find src/ -name "*attribution*" -type f | grep -v __pycache__
   grep -rn "ranker_only_outcome\|attribution_trades\|resolver" src/ --include="*.py" | grep -v test | head -10
   ```
   Record the paths found.

2. **Query current attribution state:**
   ```bash
   python -c "from src.storage.database import get_db; db=get_db(); rows=db.execute('SELECT pair_type, ranker_only_outcome, COUNT(*) FROM attribution_trades GROUP BY pair_type, ranker_only_outcome').fetchall(); [print(r) for r in rows]"
   ```
   Confirm the 0-winner, all-loser pattern.

3. **Sample 20 rejected trades for manual inspection:**
   ```sql
   SELECT ticker, entry_date, ranker_score, llm_conviction,
          ranker_only_pnl_pct, ranker_only_outcome,
          ranker_only_exit_reason, ranker_only_exit_date
   FROM attribution_trades
   WHERE pair_type = 'llm_rejected' AND ranker_only_outcome = 'loss'
   ORDER BY RANDOM() LIMIT 20;
   ```

4. **Create feature branch:**
   ```bash
   git checkout -b audit/attribution-resolver
   ```

---

## Task List

### Task 1 — Locate and read the resolver source code

**Objective:** Find every file involved in computing `ranker_only_outcome` and `ranker_only_pnl_pct`. Likely candidates based on repo structure:

- `src/attribution/` or `src/shadow_trading/attribution_resolver.py`
- `src/scheduler/watch.py` (where resolver is triggered)
- Any `*resolve*` or `*attribution*` file

Produce a file map with line numbers for:
- Where the ranker-only counterfactual is simulated
- What bracket parameters (stop %, target %, timeout days) are used
- How "win" vs "loss" vs "timeout" is decided
- What happens if the simulation can't resolve (timeout handling)
- Whether real historical OHLC data is used or synthetic assumptions

### Task 2 — Document the exact simulation parameters

**Deliverable:** Section 1 of the audit doc with:

```markdown
## Resolver Simulation Parameters (as found in code)

- **Stop price:** entry × __%  OR  entry - (__% of entry) [WHICH]
- **Target 1:** entry × __%  OR  entry + (__% of entry) [WHICH]
- **Target 2 (if any):** __
- **Timeout:** __ days
- **Data source:** yfinance / alpaca historical / synthetic [WHICH]
- **Bar resolution:** daily / intraday [WHICH]
- **Exit priority order:** (e.g., stop first, then target, then timeout)
- **Timeout resolution:** marked as "loss" / "timeout" / based on sign of pnl
- **Intrabar logic:** stop checked against intraday low? Or only close?
- **Slippage / fees:** included? How?
```

Compare these parameters to the LIVE Arcis parameters:
- Live: 2% target, 3% stop, 7-day timeout
- Ranker-only sim: **? ? ?**

If the ranker-only sim uses DIFFERENT parameters from live, that's immediate smoking gun for Hypothesis (B).

### Task 3 — Manual counterfactual on 10 rejected trades

**Deliverable:** Section 2 of audit doc — a table with manual calculation.

Pick 10 llm_rejected trades spanning different tickers and dates. For each:

1. Pull OHLC for 7 trading days after entry_date from yfinance
2. Manually simulate: 2% target, 3% stop, 7-day timeout — same as LIVE trading
3. Record what the simulation produces: target_hit, stop_hit, or timeout (with sign of pnl at timeout close)
4. Compare to what the resolver said

**Example table:**

| # | Ticker | Entry Date | Entry Price | Manual Sim Result | Resolver Result | Agreement? |
|---|---|---|---|---|---|---|
| 1 | AAPL | 2026-03-24 | $185.42 | Target hit day 3, +2.1% | Loss, -5.24% | **DISAGREE** |
| ... | | | | | | |

**Key question:** Does manual sim (with LIVE parameters) show winners where the resolver shows only losers?

- If **YES** on many trades → Hypothesis (B) confirmed. Resolver is using wrong parameters.
- If **NO** → Either Hypothesis (A) or resolver uses same parameters but different intrabar logic.

### Task 4 — Check for "mandatory loss" bugs

Specifically audit for:

- **Timeout always marked as loss:** Is a timeout automatically labeled "loss" regardless of whether the exit-close price is positive?
- **Stop label on entry:** Is the stop distance computed from entry price correctly, or is there a sign error making "stop hit" trigger on any negative intraday move?
- **Bracket inversion:** Is the stop-price above the entry (for longs) and target below? Swap bug?
- **Data alignment:** Does the resolver use the correct date range? Off-by-one errors?
- **Survivor bias:** Are rejected trades that would have been winners being filtered out before reaching the resolver?

For each of these, either confirm "not present" with evidence or flag as "possible bug, investigate further."

### Task 5 — Determine the classification verdict

Based on Tasks 1-4, classify the finding as:

**Hypothesis A (LLM genius) — evidence required:**
- Manual simulations broadly confirm resolver results
- Parameters match live trading
- No obvious bugs in simulation logic
- → Accept with caveats; document as likely genuine alpha but note extraordinary claim

**Hypothesis B (methodology bug) — evidence:**
- Manual simulations with live parameters produce winners where resolver doesn't
- Specific parameter mismatch found (e.g., wider stop, no target)
- Timeout handling produces mechanical losses
- → Open follow-up fix sprint; invalidate current attribution data

**Hypothesis C (pre-filter skew) — evidence:**
- Manual sims agree with resolver on many trades
- But ranker score distribution for rejected trades is systematically low
- → Preserve current resolver but document limitation; rejected trades are not a random sample

### Task 6 — Write the audit document

**File:** `docs/research/attribution-resolver-audit.md`

Template:

```markdown
# Attribution Resolver Audit

**Date:** 2026-__-__
**Auditor:** CC
**Trigger:** SD#41 REVISED Diagnostic 2 — 100% loss rate on 1,600 resolved pairs

## TL;DR

**Classification: HYPOTHESIS _ — [GENUINE | BUG | SKEW]**

[1-paragraph summary]

## Section 1 — Simulation Parameters (as found in code)

[file paths with line numbers]
[parameter table]
[comparison to live parameters]

## Section 2 — Manual Counterfactual (10 trades)

[table of 10 trades with manual vs resolver comparison]
[agreement rate]

## Section 3 — Bug Checks

[each of the 5 potential bugs from Task 4 with verdict]

## Section 4 — Verdict and Recommendation

**Classification:** [A / B / C]

**Evidence weight:** [strong / moderate / weak]

**Recommended action:**
- If A: accept resolver output; cite carefully with "extraordinary filter" caveat; continue monitoring
- If B: open fix sprint to correct simulation parameters; invalidate current attribution data; re-resolve 1,825 pairs with correct logic
- If C: preserve resolver but add "pre-filter skew" caveat to all attribution reports

## Section 5 — Until Further Notice

Regardless of classification:
- No investor material may cite "100% LLM filter accuracy" until this audit closes
- Training data generation should not use attribution "LLM rejection" as ground truth
- MASTER.md should reference this audit doc next to any LLM value claim

## Appendix A — Code snippets

[paste of the simulation logic with line numbers]

## Appendix B — Raw manual-sim data

[link to CSV of the 10 manual sim results]
```

### Task 7 — If bug found, scope the fix sprint

If Hypothesis B or C with actionable fix, draft a one-page spec for the follow-up:

**File:** `docs/sprints/sprint-attribution-resolver-fix.md` (new, <200 lines)

Include:
- What's broken
- What the correct behavior should be
- Parameter change or logic change needed
- Migration path for the 1,825 existing attribution rows (re-resolve with correct logic)
- Test cases that would have caught this

### Task 8 — Update MASTER.md and SD#41 REVISED

Add a section to MASTER.md referencing this audit:

```markdown
## Diagnostic D2 Status

- Audit completed: YYYY-MM-DD
- Classification: [A / B / C]
- Audit doc: docs/research/attribution-resolver-audit.md
- Follow-up sprint (if any): docs/sprints/sprint-attribution-resolver-fix.md
```

---

## Success Criteria

1. `docs/research/attribution-resolver-audit.md` exists with all 5 sections populated
2. At least 10 trades manually counterfactual-tested
3. Classification verdict (A/B/C) documented with evidence weight
4. If bug: follow-up fix sprint spec exists
5. MASTER.md references the audit result
6. No code changes beyond audit doc (this is pure investigation; fix sprint is separate)

---

## Commit Messages

```
audit(attribution): document resolver simulation parameters
audit(attribution): manual counterfactual on 10 llm_rejected trades
audit(attribution): classify as hypothesis [A/B/C] with evidence
docs: attribution resolver audit complete, update MASTER.md
```

If fix sprint drafted:
```
sprints: draft attribution resolver fix spec (SD#41 D2 follow-up)
```

---

## Out-of-Scope

- Actually fixing the resolver (that's the follow-up sprint if needed)
- Retraining the LLM (that's downstream of knowing whether attribution is trustworthy)
- Changing live trading parameters
- Touching the LLM filter itself

---

## Ralph-Loop Review Questions

1. **Why 10 manual counterfactuals and not 100?** 10 is enough to detect systematic bugs. If parameter mismatch is found, all 1,825 are suspect. Going to 100 is overkill for classification.
2. **What if manual sim results are ambiguous?** Report distribution. If 5/10 agree, that's still informative — it suggests partial bug or pre-filter + real effect mix.
3. **Who decides A vs B vs C?** CC based on evidence. Ryan reviews. Confidence level should be stated ("moderate evidence for B").
4. **What if the resolver uses data Arcis can't access?** Unlikely but possible. Document it and flag as design flaw.

---

*Ready for 3× Ralph-loop review before CC execution.*
