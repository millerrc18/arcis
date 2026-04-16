# Sprint D2: Attribution Resolver Audit (FINAL)

**Authority:** SD#41 REVISED `docs/research/SD-41-REVISED-diagnostic-first-plan.md`
**Effort:** 3-4 hours (investigation; fix sprint drafted separately if bug found)
**Branch:** `audit/attribution-resolver`
**Tag on merge:** none (audit doc only)
**Priority:** CRITICAL — LLM value claim confirmed or destroyed by this
**Ralph-loop status:** Pass 3 complete, grounded in actual resolver code

---

## Goal

Determine whether the forensic report's "100% loss on 1,600 resolved attribution pairs" finding represents (A) LLM filter alpha, (B) simulation methodology bug, or (C) pre-filter skew. Produce audit doc. Classify. If bug, draft separate follow-up fix spec.

**Until audit closes, no attribution claim may be cited in investor materials, training documentation, or strategy decisions.**

---

## Background Context for CC

**The forensic finding** (`docs/research/deep-research/Arcis-Forensic-Analysis-2026-04-16.pdf` §8):
- 1,582 `llm_rejected` pairs resolved; 100% reported as "loss" with -5.24% avg ranker-only pnl
- 114 `both_taken` pairs resolved; 100% reported as "loss" with -5.29% avg ranker-only pnl
- Zero "win" outcomes across 1,600 resolutions

**Actual resolver code** (from Pass 1 audit):

File: `src/attribution/logger.py`

```python
# Line 144: simulate_mechanical_outcome() - returns 'win', 'loss', or 'timeout'
# Outcome logic:
#   if any daily low <= stop_price: return 'loss'        (stop-first priority)
#   if any daily high >= target_price: return 'win'
#   else (no stop or target hit in timeout window): return 'timeout' at last close

# Line 174: resolve_pending_outcomes() - uses yfinance to fetch 8 days of OHLC
# Called from scheduler.watch at 4:30 PM ET
# Uses SAME stop/target parameters that were logged at recommendation time
```

**Critical observations from Pass 1:**
1. The simulation uses the SAME stop/target prices as the live trade — so hypothesis (B) "wrong parameters" is unlikely in the strict sense, but the **stop-first priority** could cause losses on bars where both stop and target appear in the same day (ambiguous intraday path — simulation pessimistically assumes stop hit first)
2. The outcome enum has THREE values: `win`, `loss`, `timeout`. The forensic report may have conflated `timeout` with `loss`. **This needs verification first.**
3. The resolver uses `auto_adjust=True` on yfinance — dividend adjustments could shift historical prices slightly, though this is usually < 0.5%

**Dataset access:** DB lives on Windows at `C:\arcis\data\ai_research_desk.sqlite3`. CC runs queries against this database directly (not via the repo — the repo has no DB).

---

## Pre-Flight Checks

```bash
# 1. Read the actual resolver code
python -c "
with open('src/attribution/logger.py') as f:
    content = f.read()
print('simulate_mechanical_outcome lines:')
start = content.find('def simulate_mechanical_outcome')
print(content[start:start+1500])
"

# 2. Query actual attribution_trades outcome distribution
python -c "
from src.config import DB_PATH
import sqlite3
conn = sqlite3.connect(DB_PATH)
print('By ranker_only_outcome:')
for r in conn.execute('SELECT ranker_only_outcome, COUNT(*), AVG(ranker_only_pnl_pct) FROM attribution_trades GROUP BY ranker_only_outcome').fetchall():
    print(f'  {r[0]}: n={r[1]}, avg_pnl={r[2]}')
print('')
print('By pair_type AND ranker_only_outcome:')
for r in conn.execute('SELECT pair_type, ranker_only_outcome, COUNT(*) FROM attribution_trades GROUP BY pair_type, ranker_only_outcome').fetchall():
    print(f'  {r[0]} / {r[1]}: n={r[2]}')
"

git checkout -b audit/attribution-resolver
```

**If Step 2 shows `timeout` has meaningful count and the forensic report only reported `loss`**, classification is already closer to **Hypothesis C / interpretation error** — the "100% loss" headline was an accidental conflation in the forensic writeup. Document this in the audit.

**If `loss` really does dominate with zero `timeout`**, proceed with deeper investigation for (A) vs (B).

---

## Task List

### Task 1 — Verify the forensic finding against real data

**Deliverable:** The query results from Pre-Flight Step 2, documented in the audit.

Three possible states:
- **State 1:** `timeout` + `loss` combined ≈ 1,600 with `win` ≈ 0. Forensic report conflated the two. Investigate why zero `win`.
- **State 2:** `loss` ≈ 1,600, `timeout` and `win` both ≈ 0. Very suspicious — stops firing on everything. Dig into why.
- **State 3:** Some other distribution. Document.

Record the exact counts in the audit doc as the ground truth for all subsequent analysis.

---

### Task 2 — Document simulation parameters from code

**Deliverable:** Section 1 of the audit doc.

Read `src/attribution/logger.py`:
- Lines ~60-120: `log_attribution_before_llm` — records `ranker_only_entry`, `ranker_only_stop`, `ranker_only_target` at scan time
- Line 144: `simulate_mechanical_outcome` — the actual bracket simulation
- Line 174: `resolve_pending_outcomes` — the yfinance-driven resolver

Extract and document:

```markdown
## Section 1 — Simulation Parameters (from src/attribution/logger.py)

**At attribution creation (log_attribution_before_llm):**
- Records: entry_price, stop_price, target_price
- Source of stop/target: whatever the ranker computed — typically
  entry * 0.97 stop and entry * 1.02 target for 2%/3% bracket
- Also records: ranker_score, llm_action (set later), pair_type

**In the simulation (simulate_mechanical_outcome, line 144):**
- Input: entry_price, stop_price, target_price, timeout_days=7, ohlcv list
- Iteration: day-by-day through ohlcv list (up to 7 days)
- Per day check (in this exact order):
    1. if low <= stop_price: return ('loss', stop_price, day_idx+1)
    2. if high >= target_price: return ('win', target_price, day_idx+1)
- If loop completes: return ('timeout', last_close, len(ohlcv))

**KNOWN PESSIMISM:** If a single day's bar has BOTH low <= stop AND
high >= target (gap or wide-range day), the simulation assumes stop hit
first. Live trading might have hit target first depending on intraday path.
This biases the resolver toward 'loss' for volatile days.

**Data source (resolve_pending_outcomes, line 174):**
- yfinance.download, auto_adjust=True
- Window: scan_timestamp date + 1 day through + 8 days
- Failures (empty data): skipped, row stays 'pending'
```

---

### Task 3 — Manual counterfactual on 10 resolved trades

**Deliverable:** Section 2 — CSV + table comparing manual vs resolver.

Pick 10 `llm_rejected` trades resolved as `loss` (or whatever the dominant outcome is from Task 1). Use stratified sampling:
- 3 from high ranker_score (top quartile)
- 3 from mid ranker_score
- 3 from low ranker_score
- 1 edge case (large negative ranker_only_pnl_pct)

For each, manually simulate using the SAME logic the resolver uses:

```python
# Save to /tmp/manual_counterfactual.py
import sqlite3
import yfinance as yf
from datetime import datetime, timedelta
from src.config import DB_PATH

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

# Replace with trade_ids chosen by stratified sampling
sample_ids = [...]  # 10 attribution_ids

for aid in sample_ids:
    row = conn.execute("""
        SELECT attribution_id, ticker, ranker_only_entry, ranker_only_stop,
               ranker_only_target, scan_timestamp, ranker_only_outcome,
               ranker_only_pnl_pct
        FROM attribution_trades WHERE attribution_id = ?
    """, (aid,)).fetchone()

    scan_date = row['scan_timestamp'][:10]
    start = (datetime.fromisoformat(scan_date) + timedelta(days=1)).strftime('%Y-%m-%d')
    end = (datetime.fromisoformat(scan_date) + timedelta(days=8)).strftime('%Y-%m-%d')
    data = yf.download(row['ticker'], start=start, end=end, progress=False, auto_adjust=True)

    if data.empty:
        print(f"{row['ticker']}: EMPTY DATA")
        continue

    # Manual simulation matching simulate_mechanical_outcome
    outcome = None
    exit_price = row['ranker_only_entry']
    days_held = 0
    for day_idx, (date, bar) in enumerate(data.iterrows()):
        days_held = day_idx + 1
        if bar['Low'] <= row['ranker_only_stop']:
            outcome = 'loss'
            exit_price = row['ranker_only_stop']
            break
        if bar['High'] >= row['ranker_only_target']:
            outcome = 'win'
            exit_price = row['ranker_only_target']
            break
    if outcome is None:
        outcome = 'timeout'
        exit_price = float(data.iloc[-1]['Close'])

    manual_pnl = (exit_price - row['ranker_only_entry']) / row['ranker_only_entry'] * 100
    agree = outcome == row['ranker_only_outcome']

    print(f"{row['ticker']} {scan_date}: "
          f"resolver={row['ranker_only_outcome']}({row['ranker_only_pnl_pct']:.2f}%) | "
          f"manual={outcome}({manual_pnl:.2f}%) | "
          f"agree={agree}")
```

Save output to `docs/research/attribution-audit-manual.csv` with columns:
`ticker, scan_date, resolver_outcome, resolver_pnl, manual_outcome, manual_pnl, agree, notes`

**Key question:** Do manual results agree with resolver on all 10?
- **All agree:** resolver is correct. Move to hypothesis (A) or (C) evaluation.
- **Some disagree:** resolver has a bug. Document the pattern (e.g., all disagreements are on gap days — that's the known pessimism from Task 2).

---

### Task 4 — Investigate the dominant-loss pattern

Based on Task 1 state:

**If State 2 (loss dominates):** Why are stops firing so often?

Run:
```python
# How often does the gap/wide-range pessimism apply?
import sqlite3, yfinance as yf
from datetime import datetime, timedelta
from src.config import DB_PATH

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

# Sample 20 rejected trades
rows = conn.execute("""
    SELECT attribution_id, ticker, ranker_only_entry, ranker_only_stop,
           ranker_only_target, scan_timestamp
    FROM attribution_trades
    WHERE ranker_only_outcome = 'loss' AND pair_type = 'llm_rejected'
    ORDER BY RANDOM() LIMIT 20
""").fetchall()

both_in_same_day_count = 0
for row in rows:
    scan_date = row['scan_timestamp'][:10]
    start = (datetime.fromisoformat(scan_date) + timedelta(days=1)).strftime('%Y-%m-%d')
    end = (datetime.fromisoformat(scan_date) + timedelta(days=8)).strftime('%Y-%m-%d')
    data = yf.download(row['ticker'], start=start, end=end, progress=False, auto_adjust=True)
    if data.empty:
        continue
    for _, bar in data.iterrows():
        stop_hit = bar['Low'] <= row['ranker_only_stop']
        target_hit = bar['High'] >= row['ranker_only_target']
        if stop_hit and target_hit:
            both_in_same_day_count += 1
            break
        if stop_hit or target_hit:
            break
print(f"Ambiguous path days (both stop+target on same bar): {both_in_same_day_count}/20")
```

If > 30% of rejected trades hit the "ambiguous path day" pattern, that's a material contributor to the 100% loss rate. The simulation is systematically pessimistic.

**If State 1 (timeout is non-zero):** Why is `win` still absent? Check whether `timeout` with positive pnl should count as a soft win.

---

### Task 5 — Check for pre-filter quality skew (Hypothesis C)

Compare score distributions for `llm_rejected` vs `both_taken`:

```python
import sqlite3
from src.config import DB_PATH
import statistics

conn = sqlite3.connect(DB_PATH)

# Rejected
rej = [r[0] for r in conn.execute(
    "SELECT ranker_score FROM attribution_trades WHERE pair_type='llm_rejected' AND ranker_score IS NOT NULL"
).fetchall()]
tkn = [r[0] for r in conn.execute(
    "SELECT ranker_score FROM attribution_trades WHERE pair_type='both_taken' AND ranker_score IS NOT NULL"
).fetchall()]

print(f"llm_rejected: n={len(rej)}, mean={statistics.mean(rej):.2f}, median={statistics.median(rej):.2f}")
print(f"both_taken:   n={len(tkn)}, mean={statistics.mean(tkn):.2f}, median={statistics.median(tkn):.2f}")
```

**If rejected scores are systematically lower** than taken scores, that's evidence for hypothesis (C) — the LLM was rejecting the lowest-quality setups, which naturally fail more often. But if BOTH sets show 100% loss rate at the ranker-only level, hypothesis (C) alone doesn't explain the anomaly.

---

### Task 6 — Classify and write the audit doc

**File:** `docs/research/attribution-resolver-audit.md` (new)

Structure:

```markdown
# Attribution Resolver Audit

**Date:** 2026-__-__
**Classification:** HYPOTHESIS [A / B / C / B+C mixed]
**Authority:** SD#41 REVISED D2
**Trigger:** Forensic report claimed 100% loss on 1,600 resolved pairs

## TL;DR

[2-3 sentences summarizing verdict]

## Section 1 — Actual Outcome Distribution

[table from Task 1: counts by pair_type × outcome]

**Was the forensic "100% loss" claim accurate?**
- [YES: loss really does dominate] OR
- [NO: timeout + loss combined ≈ total; report conflated]

## Section 2 — Simulation Parameters (from code)

[Task 2 output]

## Section 3 — Manual Counterfactual (10 trades)

[Table with agree/disagree, link to CSV]

Agreement rate: X/10
Disagreements were: [pattern description]

## Section 4 — Ambiguous-Path Day Pessimism Test

[Task 4 output]

Percentage of rejected trades hitting ambiguous path: X%
This contributes to the loss dominance by biasing toward stops.

## Section 5 — Pre-filter Skew Test

[Task 5 output]

Ranker score distribution: rejected = X.X median vs taken = Y.Y median
Gap: [large / small]

## Section 6 — Verdict

**Classification:** [A / B / C / mixed]

**Evidence strength:** [strong / moderate / weak]

**Reasoning:** [2-3 paragraphs]

**Action required:**
- If A: document carefully, cite with "requires replication" caveat
- If B: draft follow-up fix sprint; invalidate existing resolutions
- If C: document limitation, preserve resolver, adjust interpretation
- If mixed: typically B+C — documented and partially fixed

## Section 7 — Effect on Prior Claims

- "LLM rejects 100% losers" → [RESCIND / QUALIFY / SUPPORT]
- "LLM filter adds alpha" → [RESCIND / QUALIFY / SUPPORT]
- Training data citing rejection accuracy → [REMOVE / QUALIFY]

## Section 8 — Follow-Up Sprint (if needed)

[Link to sprint-attribution-resolver-fix.md if drafted]
```

---

### Task 7 — If bug confirmed, draft fix sprint

**File:** `docs/sprints/sprint-attribution-resolver-fix.md` (new, if needed)

Only if Task 6 classifies as Hypothesis B (clear methodology bug):

```markdown
# Sprint: Attribution Resolver Fix

**Depends on:** audit doc verdict classifying as hypothesis B
**Effort:** 1-2 hours + re-resolution of 1,825 pairs

## Specific fix required

[From Task 4 findings — e.g., "replace low-priority stop check with
intrabar path estimation using Close[-1] → High → Low → Close
approximation"]

## Migration

1. Add `resolution_version` column to `attribution_trades`
2. Mark all current rows as `resolution_version = 'v1_pessimistic_stop'`
3. Re-run resolver with fixed logic, tag as `resolution_version = 'v2_path_estimated'`
4. Both versions preserved for comparison

## Tests

Minimum 3 unit tests for the new simulation function covering:
- Clear stop-only day → loss
- Clear target-only day → win
- Ambiguous-path day → intrabar-estimated outcome
```

---

### Task 8 — Update MASTER.md

Add a Diagnostic D2 section referencing the audit:

```markdown
## Diagnostic D2 Status

- **Audit completed:** YYYY-MM-DD
- **Classification:** [A / B / C]
- **Audit doc:** `docs/research/attribution-resolver-audit.md`
- **Follow-up fix:** [needed / not needed]
- **Action:** [summary]
```

Also update any prior references to "LLM 100% rejection accuracy" with a link to this audit and an appropriate qualifier.

---

## Success Criteria

1. `docs/research/attribution-resolver-audit.md` exists with all 8 sections
2. Task 1 actual-counts query run; results documented
3. Task 3 manual counterfactual CSV committed at `docs/research/attribution-audit-manual.csv`
4. Classification verdict documented with evidence strength
5. If bug: follow-up sprint spec drafted
6. MASTER.md references the audit
7. No production code changes (audit-only sprint)

---

## Commit Messages

```
audit: verify attribution outcome distribution (D2 task 1)
audit: document resolver simulation parameters (D2 task 2)
audit: manual counterfactual on 10 resolved trades (D2 task 3)
audit: ambiguous-path pessimism test + pre-filter skew check
docs: attribution-resolver-audit.md verdict is [A|B|C]
sprints: attribution-resolver-fix spec (D2 task 7, conditional)
docs: update MASTER.md with D2 audit status
```

---

## Out-of-Scope

- Fixing the resolver (that's the conditional follow-up sprint)
- Retraining the LLM (gated on knowing LLM actually filters)
- Changing live trading parameters (unrelated)
- Re-resolving the 1,825 existing rows (follow-up sprint)

---

## 3× Ralph-Loop Summary

**Pass 1 (repo audit):** Found actual resolver code at `src/attribution/logger.py:144`. Discovered outcome enum has THREE values (win/loss/timeout) — the forensic "100% loss" may be a conflation. Found `simulate_mechanical_outcome` uses same bracket parameters as live trade, eliminating the "wrong parameters" hypothesis. Identified the key bias: stop-first priority on ambiguous-path days.

**Pass 2 (spec correction):** Reframed Task 1 to first verify the forensic claim itself. Added specific code-based investigation for ambiguous-path pessimism. Replaced generic "manual counterfactual" with runnable pseudocode matching actual resolver logic. Added pre-filter skew test.

**Pass 3 (tighten):** Reduced tasks from 8 to 8 (kept) but with specific exit criteria for each. Added branching logic (State 1/2/3) so CC knows how to proceed based on Task 1 output. Tightened verdict template. Made follow-up sprint conditional and explicit.

**Final confidence:** HIGH. Investigation is now data-driven: Task 1 output determines which hypotheses to evaluate, and each subsequent task has falsifiable criteria.
