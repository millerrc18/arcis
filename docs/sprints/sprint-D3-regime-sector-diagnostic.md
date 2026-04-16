# Sprint D3: Regime & Sector Classifier Diagnostic + GICS Backfill

**Authority:** SD#41 REVISED `docs/research/SD-41-REVISED-diagnostic-first-plan.md`
**Effort:** 1 weekend (8-10 hours including Ralph-loop)
**Branch:** `feat/regime-sector-diagnostic`
**Tag on merge:** `v0.20.0` (or co-tag with D1 if both ship together)
**Priority:** CRITICAL — gates all regime and sector levers
**Ralph-loop status:** First draft

---

## Goal

Diagnose why `regime_at_entry` is NULL for 67% of trades and NULL outperforms every labeled regime by 25+ points. Diagnose why `sector_context` is 100% NULL. Repair what can be repaired in this sprint (sector context via manual GICS lookup — overlap with D1). Document what requires a larger rebuild (regime classifier v2). Until this diagnostic closes, no lever that depends on regime or sector filtering can be tested.

This is a diagnostic sprint with some fix work included. Larger classifier rebuild is deferred to SD#35 follow-up.

---

## Background Context for CC

**The anomaly observed in forensic analysis:**

From `shadow_trades.regime_at_entry`:
| Regime | N | Win Rate | Mean pnl% |
|---|---|---|---|
| GREEN | 26 | 53.8% | +0.13% |
| **NULL** | **52** | **78.8%** | **+1.11%** |

From `recommendations.market_regime`:
| Regime | N | Win Rate | Mean pnl% |
|---|---|---|---|
| calm_uptrend | 7 | 42.9% | -0.14% |
| volatile_uptrend | 13 | 46.2% | +0.07% |
| **NULL** | **58** | **79.3%** | **+1.06%** |

**Why this is impossible under a correct regime classifier:**

A regime classifier should not systematically label the WORSE trades. The fact that NULL (un-classified) trades outperform every labeled regime by 25+ percentage points means the classifier is either:

**(a) Intermittent:** Runs rarely. When it runs, it happens to run during adverse conditions (e.g., only when volatility spikes, which correlates with worse outcomes).

**(b) Biased labels:** calm_uptrend may mean "tops immediately before retrace"; volatile_uptrend may mean "post-spike pullbacks that fail more often" — the label vocabulary itself is miscalibrated.

**(c) Schema-recent:** regime_at_entry was added to shadow_trades late. Older trades are NULL by construction. Newer trades happen to be in a worse regime period.

**Secondary problem:** `sector_context` is 100% NULL (0 of 78 trades). Any sector-based lever (the #3 Phase 1 lever in the forensic report — sector cap) cannot be tested without manual sector assignment.

Full context: `docs/research/deep-research/Arcis-Forensic-Analysis-2026-04-16.pdf` Section 4 and Section 10 table.

---

## Pre-Flight Checks

1. **Locate regime classifier source:**
   ```bash
   find src/ -name "*regime*" -type f | grep -v __pycache__
   grep -rn "market_regime\|regime_at_entry\|classify_regime" src/ --include="*.py" | grep -v test | head -10
   ```

2. **Query current regime distribution:**
   ```bash
   python -c "from src.storage.database import get_db; db=get_db(); [print(r) for r in db.execute('SELECT regime_at_entry, COUNT(*), AVG(pnl_pct) FROM shadow_trades WHERE actual_exit_time IS NOT NULL GROUP BY regime_at_entry').fetchall()]"
   ```

3. **Query sector context distribution:**
   ```bash
   python -c "from src.storage.database import get_db; db=get_db(); rows=db.execute('SELECT COUNT(*) FROM shadow_trades WHERE sector_context IS NULL').fetchone(); print(f'NULL sector_context: {rows[0]}')"
   ```

4. **Check when columns were added (schema history):**
   ```bash
   git log --all --source -- src/schema/registry.py | head -20
   # Or: git log -p src/schema/registry.py | grep -A 2 "regime_at_entry"
   ```

5. **Create feature branch:**
   ```bash
   git checkout -b feat/regime-sector-diagnostic
   ```

---

## Task List

### Task 1 — Audit the regime classifier code path

**Deliverable:** Document in `docs/research/regime-classifier-audit.md`:

1. **Where does regime classification happen?**
   - File and line references
   - What function is called, with what inputs
   - Is it called on every scan cycle, per-ticker, or separately?

2. **What are the possible label values?**
   - Expected: calm_uptrend, volatile_uptrend, bear, sideways, unknown, GREEN (?)
   - Is GREEN the same as calm_uptrend with a different label, or is it a different taxonomy?
   - Is there inconsistency between `regime_at_entry` (shadow_trades) and `market_regime` (recommendations)?

3. **What conditions cause NULL?**
   - Classifier not run at all?
   - Classifier runs but returns None?
   - Classifier raises exception that's silently swallowed?

4. **When was the classifier added?**
   - Via `git log` on the classifier file
   - Does the "NULL dominates" pattern correlate with older trades pre-dating the classifier?

Answer format:
```markdown
## Classifier Call Graph
- Trigger: [scheduler/watch.py:line_number]
- Logic: [src/classifiers/regime.py]
- Writes to: [where it's persisted]

## NULL Hypothesis Test Results
Date classifier added: YYYY-MM-DD
Trades before that date with NULL regime: __ of __
Trades after that date with NULL regime: __ of __
→ Hypothesis (c) [CONFIRMED / REJECTED]
```

### Task 2 — Verify hypothesis (a): classifier intermittence

For the 52 NULL-regime trades, pull additional context from data:
- VIX at entry time (or nearest available)
- SPY 5-day trailing return leading into entry
- S&P 100 breadth (% above 50-day MA)
- Number of concurrent positions at entry

For the 26 GREEN-regime trades, pull the same.

**Expected signature of hypothesis (a) being true:**
- NULL trades cluster at LOW VIX, POSITIVE SPY trailing return, HIGH breadth (benign conditions)
- GREEN trades cluster at HIGHER VIX, WORSE trailing conditions

If that's the pattern, the classifier doesn't run in benign conditions (perhaps its minimum-data-window condition fails when conditions are placid).

**Deliverable:** Add to the audit doc:

```markdown
## Hypothesis (a) Test: Classifier Intermittence

Condition means at entry time:
| Bucket | N | VIX mean | SPY 5d return | Breadth % |
|---|---|---|---|---|
| NULL regime | 52 | ? | ? | ? |
| GREEN regime | 26 | ? | ? | ? |

Interpretation: [If NULL < GREEN on VIX and > GREEN on breadth → classifier silent in benign regimes]
```

### Task 3 — Verify hypothesis (b): biased label vocabulary

For the 7 calm_uptrend trades and 13 volatile_uptrend trades (from recommendations), compute:
- Time between classification and entry (did market conditions change?)
- Forward 3-day SPY return after entry
- Whether the label preceded a SPY drawdown > 1%

**Expected signature of hypothesis (b) being true:**
- "calm_uptrend" labels systematically precede SPY pullbacks (the label is a top signal, not a buy-the-dip signal)
- "volatile_uptrend" labels occur after big moves that already happened

**Deliverable:** Add to audit doc:

```markdown
## Hypothesis (b) Test: Label Vocabulary Calibration

| Label | N | Forward 3d SPY | Label precedes SPY pullback? |
|---|---|---|---|
| calm_uptrend | 7 | ? | [Y/N] |
| volatile_uptrend | 13 | ? | [Y/N] |
| GREEN | 26 | ? | [Y/N] |

Interpretation: [If labels systematically precede drawdowns → vocabulary is miscalibrated]
```

### Task 4 — Classify the regime diagnosis

Based on Tasks 1-3, produce classification:

- **(a) Intermittence dominant:** Classifier needs to run more often / on all trades. Fix is straightforward scheduling.
- **(b) Vocabulary biased:** Classifier needs label rework. This is SD#35 (regime classifier v2) — NOT this sprint.
- **(c) Schema-recent dominant:** NULL is by construction for older trades. No action needed; metrics will self-correct as new trades accumulate. Backfill not possible without historical feature store.
- **Mixed:** Most likely. Document which hypothesis contributes what fraction.

### Task 5 — Sector context backfill (the immediate win)

**Hard dependency on Sprint D1:** Sprint D1 also creates `data/sp100-gics-lookup.csv` and a `realized_sector` column. If D1 has shipped, D3 just verifies population and moves on.

If D1 hasn't shipped yet, D3 should build the lookup CSV and backfill:

1. Build `data/sp100-gics-lookup.csv` — 102 tickers × 11 GICS sectors
2. Run backfill for `realized_sector` column on all 78 trades
3. Also attempt to backfill `sector_context` (the original column, 100% NULL) — this one may require reading the sector classifier code. If sector_context is computed at recommendation time and we can't easily backfill historically, document this and rely on `realized_sector` going forward.

**Coordinate with Sprint D1:** If both sprints run in parallel, avoid duplicating the CSV. D1 owns the CSV; D3 just consumes it.

### Task 6 — Forward fix: make the regime classifier run on every recommendation

If Task 4 reveals hypothesis (a) (intermittence), the fix is scheduler-level:

**File:** wherever the scan cycle generates recommendations — add a call to the regime classifier before writing the recommendation:

```python
# Before storing recommendation:
market_regime = classify_market_regime(
    vix=latest_vix,
    spy_5d_return=spy_5d,
    breadth_pct=breadth,
    timestamp=now
) or 'unknown'  # never write NULL; 'unknown' is explicit

recommendation['market_regime'] = market_regime
```

**Constraint:** If the classifier raises an exception or has missing inputs, write 'unknown' (NOT NULL). This makes future NULL → 'unknown' distinction explicit and prevents the forensic anomaly from recurring.

### Task 7 — Add 'unknown' as explicit regime category

Update the classifier to return 'unknown' explicitly instead of None when data is insufficient. This is a single-line change in most classifiers (`return 'unknown'` instead of `return None`).

**File:** `src/classifiers/regime.py` (or wherever)

Also update any UI/API surfaces that filter by regime to include 'unknown' as a legitimate bucket (not just a NULL-catchall).

### Task 8 — Dashboard: show regime distribution with explicit 'unknown' bucket

**File:** `frontend/src/pages/Dashboard.jsx` or similar

If there's currently a "By Regime" breakdown anywhere, ensure `unknown` shows as a distinct row rather than being collapsed with missing data. Add a tooltip: "Unknown = classifier had insufficient inputs. Investigate if this exceeds 20% of trades."

### Task 9 — Regression tests

**File:** `tests/classifiers/test_regime.py` (new or extend)

Minimum tests:
1. `test_classifier_returns_unknown_not_none_when_inputs_missing`
2. `test_classifier_labels_match_expected_vocabulary` — enumerate all valid labels; no new labels slip in
3. `test_backfill_sector_idempotent`
4. `test_recommendation_always_has_non_null_regime` — integration test

### Task 10 — Documentation updates

**Files:**
- `CHANGELOG.md` — v0.20.0 entry
- `RELEASES.md` — release notes
- `MASTER.md` — add Diagnostic D3 status section
- `docs/research/regime-classifier-audit.md` — the main deliverable from Tasks 1-4
- `docs/research/SD-35-regime-classifier-v2.md` — if audit surfaced hypothesis (b), update SD#35 to reflect new findings

**CHANGELOG entry:**
```markdown
## v0.20.0 (TBD)

### Diagnosed
- **Regime classifier anomaly.** NULL-regime trades outperformed labeled
  regimes by 25+ points per forensic analysis. Root cause: [INTERMITTENCE /
  VOCABULARY / SCHEMA-RECENT / MIXED]. See docs/research/regime-classifier-audit.md.

### Changed  
- Regime classifier now returns 'unknown' explicitly instead of NULL.
- Scan cycles write market_regime on every recommendation; no silent skip.
- Dashboard shows 'unknown' as distinct bucket.

### Added
- realized_sector populated for all 78 closed trades via manual GICS lookup.
- tests enforcing 'never NULL regime' invariant.

### Deferred
- Regime taxonomy rework (hypothesis b): SD#35 v2 scope expanded.
```

---

## Success Criteria

1. `docs/research/regime-classifier-audit.md` produced with hypothesis classification
2. All 78 closed trades have non-NULL `realized_sector`
3. New recommendations write 'unknown' instead of NULL regime when data insufficient
4. Dashboard shows regime distribution including 'unknown' bucket
5. All 4 new tests pass
6. No test regressions
7. `pytest tests/ --no-cov -q` passes
8. Frontend builds

---

## Commit Messages

```
audit(regime): document classifier call graph and NULL hypothesis tests
audit(regime): classify anomaly as [intermittence/vocabulary/schema-recent]
feat(classifiers): regime classifier returns 'unknown' instead of None
feat(scheduler): populate market_regime on every recommendation
feat(data): backfill realized_sector via GICS lookup for 78 trades
feat(frontend): dashboard shows 'unknown' as distinct regime bucket
test: regime classifier invariants + sector backfill idempotency
docs: SD#41 D3 complete, see regime-classifier-audit.md
```

---

## docs/sprint-checklist.md (final section)

- [ ] All 10 tasks completed or explicitly marked N/A
- [ ] regime-classifier-audit.md exists with classification verdict
- [ ] 78+ trades have non-NULL realized_sector
- [ ] No new recommendation writes NULL for market_regime
- [ ] 4 new tests pass
- [ ] No regressions elsewhere
- [ ] Frontend builds
- [ ] MASTER.md updated with D3 status
- [ ] CHANGELOG + RELEASES entries
- [ ] Tag v0.20.0 after merge

---

## Out-of-Scope

- Rewriting the regime classifier (that's SD#35 v2, separate sprint)
- Backfilling historical `market_regime` for pre-existing trades (no historical feature store)
- Changing the regime taxonomy labels (defer to SD#35)
- Touching D1's SPY excess work (parallel sprint, coordinate on shared CSV)
- Touching D2's attribution resolver audit (independent)

---

## Ralph-Loop Review Questions

1. **What if Task 4 shows hypothesis (c) dominates?** Then this sprint ships the 'unknown' fix but most value is future-only. Document it; move on.
2. **Can we truly backfill `sector_context`?** Probably not cleanly — it was computed at recommendation time with context that's gone. Populate `realized_sector` as the reliable field going forward; treat `sector_context` as legacy.
3. **What if the classifier IS running but returns None silently?** That's hypothesis (a) variant. Task 7 fixes it (return 'unknown' explicitly). Test covers it.
4. **Does the regime anomaly invalidate prior research?** Some of it, yes. Flag docs in `docs/research/` that cite regime-conditional findings (the MASTER update step does this).
5. **Should we delay D3 until D1 ships?** No. They share the GICS CSV, but both can run in parallel. Whichever ships first writes the CSV; the other consumes it.

---

*Ready for 3× Ralph-loop review before CC execution.*
