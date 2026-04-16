# Attribution Resolver Audit

**Date:** 2026-04-16
**Classification:** **HYPOTHESIS B — simulation methodology bug (data-shape defect)**
**Evidence strength:** **OVERWHELMING** (1,600/1,600 rows carry the bug's universal fingerprint)
**Authority:** SD#41 REVISED / Sprint D2
**Trigger:** Forensic report claimed 100% loss on ~1,600 resolved attribution pairs

---

## TL;DR

The forensic "100% loss" number is **real but the explanation is not LLM-filter alpha.**
`simulate_mechanical_outcome` in `src/attribution/logger.py:144` receives OHLCV bars where
`bar.get("Low", ...)` returns `0` on every row, because recent `yfinance.download`
returns a **MultiIndex** with tuple keys (`('Low', 'AAPL')`) rather than the
string key `"Low"` the simulator expects. `0 <= stop_price` is always true, so the
stop-first check trips on bar 1, every time. This deterministically writes
`outcome='loss'` with `pnl_pct = (stop − entry)/entry × 100` for every resolved row.

**The fingerprint is universal:** in the 1,600 resolved rows, 1,600 have
`pnl_pct` exactly equal to `(stop − entry) / entry × 100`. Zero exceptions.
No real market path can produce that distribution.

**All pre-audit attribution claims are rescinded.** See Section 7.

---

## Section 1 — Actual Outcome Distribution

Ground truth from the live DB (`C:/arcis/data/ai_research_desk.sqlite3`), queried 2026-04-16:

| pair_type     | ranker_only_outcome | n     | avg_pnl_pct |
|---------------|---------------------|-------|-------------|
| `both_taken`  | `loss`              | 114   | −5.290      |
| `both_taken`  | `pending`           | 6     | —           |
| `llm_rejected`| `loss`              | 1,406 | −5.242      |
| `llm_rejected`| `pending`           | 314   | —           |
| `unknown`     | `loss`              | 80    | −4.845      |
| `unknown`     | `pending`           | 50    | —           |
| **Total**     | **resolved**        | **1,600** | **−5.225**  |
| **Total**     | **pending**         | **370**   | —           |

**Was the forensic "100% loss" claim accurate?**
**YES, numerically** — 1,600 / 1,600 resolved rows are `loss`. But the cause is not what the forensic report implied.

**Zero `win` outcomes. Zero `timeout` outcomes.** That alone is physically implausible for real market paths across 1,600 random 7-day windows in 2026 (a bull year with ~55–60% positive-day frequency on large-caps). State 2 is real and it points to a systematic bug, not market reality.

---

## Section 2 — Simulation Parameters (from code)

Source: `src/attribution/logger.py`, read verbatim 2026-04-16.

### At attribution creation — `log_attribution_before_llm` (line 26)

- Records: `entry_price`, `stop_price`, `target_price`, `ranker_score`, `scan_timestamp`
- Stop / target are whatever the ranker passed in — typically
  `entry × (1 − stop_pct)` and `entry × (1 + target_pct)` from the risk governor
- `ranker_only_outcome` starts as `'pending'` (string literal)
- `pair_type` is set in phase 2 by `log_attribution_after_llm` to
  `'both_taken'` | `'llm_rejected'` | `'unknown'`

### In the simulator — `simulate_mechanical_outcome` (line 144)

```python
def simulate_mechanical_outcome(entry_price, stop_price, target_price,
                                 timeout_days, ohlcv):
    for day_idx, bar in enumerate(ohlcv):
        low = bar.get("Low", bar.get("low", 0))       # ← BUG SITE
        high = bar.get("High", bar.get("high", 0))
        close = bar.get("Close", bar.get("close", 0))
        if low <= stop_price:
            return "loss", stop_price, day_idx + 1
        if high >= target_price:
            return "win", target_price, day_idx + 1
    if ohlcv:
        last_close = ohlcv[-1].get("Close", ohlcv[-1].get("close", entry_price))
        return "timeout", last_close, len(ohlcv)
    return "timeout", entry_price, 0
```

### Resolver — `resolve_pending_outcomes` (line 174)

```python
data = yf.download(row["ticker"], start=..., end=..., progress=False, auto_adjust=True)
ohlcv = data.reset_index().to_dict("records")
outcome, exit_price, days = simulate_mechanical_outcome(..., ohlcv)
```

### The defect

`yfinance.download("AAPL", ...)` in current versions returns a DataFrame with
**MultiIndex columns**:

```
[('Close', 'AAPL'), ('High', 'AAPL'), ('Low', 'AAPL'), ('Open', 'AAPL'), ('Volume', 'AAPL')]
```

`data.reset_index().to_dict("records")` emits per-row dicts keyed by those **tuples**:

```python
{('Date',''): Timestamp(...),
 ('Close','AAPL'): 255.63, ('High','AAPL'): 256.18,
 ('Low','AAPL'): 253.33,  ('Open','AAPL'): 254.08, ('Volume','AAPL'): 40059400}
```

`bar.get("Low", bar.get("low", 0))` misses — `"Low"` isn't a key — returns the
default `0`. Then `low (=0) <= stop_price` is **always** true, so the stop-first
branch fires on **bar 1, for every ticker, for every pair**.

The outcome is therefore always `('loss', stop_price, 1)` and the computed
`pnl_pct = (stop_price − entry_price) / entry_price × 100` is literally the
negative of the stop-distance.

**Empirically reproduced in this audit** (see Section 4 fingerprint test):
1,600/1,600 resolved rows have `pnl_pct` exactly equal to
`(stop − entry)/entry × 100`. The bug is deterministic and universal.

---

## Section 3 — Manual Counterfactual (7 trades)

Stratified sample of `llm_rejected` / `loss` rows, re-simulated against yfinance
using the same logic **but with correct column access** (flatten the MultiIndex
before iterating). Full CSV at `docs/research/attribution-audit-manual.csv`.

| ticker | scan_date  | resolver outcome (pnl%)  | manual outcome (pnl%) | agree |
|--------|------------|--------------------------|-----------------------|-------|
| XOM    | 2026-04-09 | loss (−8.02)             | timeout (−2.10)       | ❌    |
| EXC    | 2026-04-08 | loss (−3.84)             | **win (+2.88)**       | ❌    |
| CVS    | 2026-04-10 | loss (−4.76)             | loss (−4.76)          | ✅    |
| AMD    | 2026-04-07 | loss (−9.69)             | **win (+7.27)**       | ❌    |
| KO     | 2026-04-06 | loss (−3.07)             | timeout (−0.53)       | ❌    |
| CSCO   | 2026-04-06 | loss (−5.30)             | **win (+3.97)**       | ❌    |
| BKNG   | 2026-04-06 | loss (−13.99)            | loss (−13.99)         | ✅    |

**Agreement rate: 2 / 7 (≈29%).**

Intended sample size was 10. Two of the three "low ranker_score" slots returned
no rows because the `ranker_score < 40` band has no `llm_rejected / loss` rows
on this dataset — every `llm_rejected` pair has `score ≥ 59`. No substantive
conclusion hinges on 7 vs 10; the fingerprint test (Section 4) examines all 1,600.

**Disagreement pattern:** the 5 disagreements are all cases where the real market
either (a) hit the target cleanly (EXC, AMD, CSCO: all real `win`) or (b) ranged
flat within brackets (XOM, KO: both `timeout`). The 2 agreements (CVS, BKNG) are
coincidences — the real market *did* hit the stop in those 7-day windows.

The bug forces every outcome to `loss` at `stop_price`. When reality agrees, it
looks right by accident; when reality is `win` or `timeout`, the resolver is
silently wrong.

---

## Section 4 — Fingerprint Test (replaces ambiguous-path pessimism test)

The ambiguous-path pessimism test from the sprint spec becomes moot once the
resolver bug is identified — it only matters if stops were legitimately firing.
Instead, I ran the bug's universal fingerprint check:

> If the bug is "`low=0` on every bar triggers stop-first", then every resolved
> `loss` row must have `pnl_pct` exactly equal to `(stop − entry) / entry × 100`.

```python
SELECT COUNT(*) FROM attribution_trades
WHERE ranker_only_outcome = 'loss'
  AND ABS(ranker_only_pnl_pct - ROUND((ranker_only_stop - ranker_only_entry)
                                       / ranker_only_entry * 100, 2)) < 0.01
```

**Result: 1,600 / 1,600 match exactly. Zero rows differ.**

No real market path can produce a distribution where every single trade exits at
exactly the pre-declared stop. The probability of that under any non-degenerate
market model is effectively zero. This is the bug's signature.

---

## Section 5 — Pre-filter Skew Test

Score distributions for the two pair types:

| pair_type     | n     | mean  | median | stdev | min  | max   |
|---------------|-------|-------|--------|-------|------|-------|
| `llm_rejected`| 1,720 | 78.50 | 77.00  | 11.10 | 59.0 | 100.0 |
| `both_taken`  | 120   | 82.29 | 77.00  | 10.02 | 60.0 | 100.0 |

**Delta (taken − rejected) medians: 0.00**

Score distributions overlap almost entirely. The mean skew is small (3.8
points) and well within the stdev. Pre-filter skew **cannot** explain a 100%
loss rate — if the LLM were rejecting lower-quality setups that naturally fail
more often, we'd expect a clear score gap and asymmetric outcome distributions.
Neither is present.

Hypothesis C (pre-filter skew) is **rejected** as a material contributor.

---

## Section 6 — Verdict

### Classification: **HYPOTHESIS B — simulation methodology bug**

### Evidence strength: **OVERWHELMING**

### Reasoning

Three independent lines of evidence all point to the same defect:

1. **Code inspection** — `simulate_mechanical_outcome` calls `bar.get("Low", ...)`
   on a dict keyed by tuples like `('Low', 'AAPL')`. The string-literal miss
   returns default 0. Confirmed by executing the same `yf.download →
   reset_index → to_dict('records')` sequence the resolver uses and observing
   `low=0, high=0, close=0` on every bar.

2. **Manual counterfactual** — 5 of 7 re-simulated trades disagree with the
   resolver; 3 of those 5 were real `win` outcomes misclassified as `loss`.
   The 2 agreements are stop-hit coincidences.

3. **Universal bug fingerprint** — all 1,600 resolved rows have `pnl_pct`
   exactly equal to `(stop − entry)/entry × 100`. That distribution is
   impossible under any real market model.

Hypotheses A (LLM filter alpha) and C (pre-filter skew) are both **rejected**:

- **A rejected:** the bug generates identical `loss` outcomes regardless of
  LLM decision (`both_taken` and `llm_rejected` both show 100% loss with
  effectively identical mean pnl, −5.29% vs −5.24%). If the LLM were
  rejecting future losers, we'd expect the ranker-only column to show that
  the rejected set's real market outcomes were systematically worse than the
  taken set's. With a broken resolver, that signal is undetectable —
  everything is forced to `loss`.
- **C rejected:** score distributions overlap (median 77 vs 77) and the mean
  gap is 3.8 points. Pre-filter skew cannot produce a 100% failure rate.

### Action required

**Follow-up fix sprint:** `docs/sprints/sprint-attribution-resolver-fix.md` (drafted in this PR).

The fix has three parts:
1. Flatten the MultiIndex to strings before iterating (1-line change).
2. Add unit tests so this can't regress.
3. Re-resolve the 1,600 compromised rows, tagged with a `resolution_version`
   column so the old (buggy) and new (correct) values are both preserved for
   comparison.

---

## Section 7 — Effect on Prior Claims

All attribution-derived claims made before this audit are **compromised** and must not be cited until the resolver is fixed and rows are re-resolved.

| Claim                                              | Status    |
|----------------------------------------------------|-----------|
| "LLM rejects 100% of losers"                       | **RESCIND** — artifact of resolver bug |
| "LLM filter adds alpha" (per attribution metrics)  | **RESCIND** — cannot be measured on current data |
| "−5.24% avg ranker-only pnl on rejected"           | **RESCIND** — equals stop-distance, not market return |
| "Zero wins on rejected tickers"                    | **RESCIND** — resolver cannot produce `win` |
| Training examples citing rejection accuracy        | **REMOVE** from training corpus until re-resolved |

**Policy:** Until this audit closes via the fix-sprint merge and a
re-resolution run with non-zero `win` count, no attribution claim may be
cited in investor materials, training documentation, onboarding decks, CTO
reports, or strategy decision records. This policy is effective immediately
and expires only upon successful completion of the fix sprint.

---

## Section 8 — Follow-Up Sprint

**Spec:** `docs/sprints/sprint-attribution-resolver-fix.md`

Summary:
- **Fix** — normalize yfinance MultiIndex columns to strings before
  building the `ohlcv` list in `resolve_pending_outcomes`.
- **Migration** — add `resolution_version` column on `attribution_trades`;
  tag existing rows `v1_multiindex_bug`; re-resolve under `v2_fixed`.
- **Tests** — at least 3 unit tests: MultiIndex-frame input returns real
  outcomes, flat-columns-frame input returns the same outcome, missing
  yfinance data leaves `pending`.

---

*Audit closed 2026-04-16. Fix sprint awaits separate PR.*
