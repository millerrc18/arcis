# Training Collection Investigation — 2026-04-22

## Scope
Investigate why completed trades are not producing new `training_examples`.

## Method
- Static code-path audit from trade close/reconcile through training collection.
- Runtime checks via unit tests targeting collector/reconcile paths.
- Schema + config gate review.

## Executive findings

### 1) Training collection is **not event-driven at trade close**
Training examples are generated only when collection jobs run (manual action or scheduler), not at the moment a trade closes.

- Collector entrypoint: `collect_training_examples_from_closed_trades()`.
- Scheduled call: `run_overnight_training_collection()` (6:00 PM ET), and manual `/actions/collect-training` path.

**Operational implication:** if trades close intraday, no new examples appear until the collection job runs.

---

### 2) Eligibility query is strict and excludes several common "completed" states
A trade is eligible only if all of the following are true:

1. `shadow_trades.status = 'closed'`
2. `COALESCE(shadow_trades.quarantined, 0) = 0`
3. `shadow_trades.recommendation_id` joins to `recommendations.recommendation_id` (inner join)
4. `recommendation_id` is not already present in `training_examples`

**Operational implication:** trades in `needs_manual_review`, `exit_failed`, `exit_pending`, or trades with missing/unjoinable `recommendation_id` are silently excluded.

---

### 3) Recent reconcile behavior increases `needs_manual_review` terminal rows
Reconcile logic intentionally marks problematic exits as `needs_manual_review` (e.g., `exit_overshoot_detected`, `qty_mismatch_partial_fill`) instead of `closed`.

**Operational implication:** these trades can look "completed" from an operator perspective but are intentionally ineligible for training collection.

---

### 4) Collection can return zero with no hard crash when Claude generation is unavailable
`generate_training_example()` returns `None` when:
- `anthropic` package is missing,
- API key is missing/placeholder,
- API call fails.

Collector then warns and skips each row.

**Operational implication:** collection job may finish successfully with `0` examples even when closed trades exist.

---

### 5) Ingestion gate can reject generated outputs and halt low-compliance batches
`validate_training_example()` rejects outputs that fail XML/tag or formatting constraints. If attempted >= 10 and compliance drops below 90%, batch halts.

**Operational implication:** jobs can process candidates but store little/none if model output format drifts.

## Evidence collected

### Code-path evidence (primary)
- `src/training/data_collector.py`
  - strict eligibility SQL (`status='closed'`, non-quarantined, inner join, dedupe)
  - per-row skip on Stage-1 generation failure
  - ingestion-gate validation before insert
- `src/scheduler/overnight.py`
  - overnight training collection runner
- `src/api/routes/actions.py`
  - manual collect-training action
- `src/shadow_trading/reconcile.py`
  - transitions to `needs_manual_review` for overshoot/mismatch conditions
- `src/training/claude_client.py`
  - returns `None` when API key/package/call unavailable
- `src/training/ingestion_gate.py`
  - format validation + batch halt threshold

### Runtime test evidence
- `pytest -q tests/test_self_blinding.py tests/test_data_collectors.py -k "training_examples_from_closed_trades or TrainingDataCollectorPnlTypeSafety"`
  - pass, collector logic behaves as coded for happy-path and type-safety cases.
- `pytest -q tests/shadow_trading/test_reconcile_partial_fill_mismatch.py`
  - pass, reconcile intentionally routes mismatch cases to `needs_manual_review`.

## Most likely root-cause candidates (ranked)

1. **Trades are ending in `needs_manual_review` rather than `closed`.**
2. **Trades are `closed` but missing joinable `recommendation_id` rows.**
3. **Collector is running, but generation is skipped due to Anthropic/API environment state.**
4. **Collector is running, generation succeeds, but ingestion-gate rejection rate is high.**
5. **Operator expects immediate at-close ingestion, but system is scheduled/batch-driven.**

## Recommended next diagnostic queries (production DB)

Run these in order to localize the failure point quickly:

```sql
-- A. What terminal states are we actually ending in?
SELECT status, COUNT(*)
FROM shadow_trades
GROUP BY status
ORDER BY COUNT(*) DESC;

-- B. "Completed" but ineligible due to state
SELECT COUNT(*) AS needs_manual_review_n
FROM shadow_trades
WHERE status = 'needs_manual_review';

-- C. Closed trades eligible before rec join
SELECT COUNT(*) AS closed_clean_n
FROM shadow_trades
WHERE status='closed' AND COALESCE(quarantined,0)=0;

-- D. Closed trades dropped by missing recommendation join
SELECT COUNT(*) AS closed_missing_rec_join_n
FROM shadow_trades st
LEFT JOIN recommendations r
  ON st.recommendation_id = r.recommendation_id
WHERE st.status='closed'
  AND COALESCE(st.quarantined,0)=0
  AND r.recommendation_id IS NULL;

-- E. Closed+joined trades already consumed
SELECT COUNT(*) AS already_collected_n
FROM shadow_trades st
JOIN recommendations r ON st.recommendation_id = r.recommendation_id
WHERE st.status='closed'
  AND COALESCE(st.quarantined,0)=0
  AND st.recommendation_id IN (
    SELECT recommendation_id
    FROM training_examples
    WHERE recommendation_id IS NOT NULL
  );

-- F. Remaining candidates right now
SELECT COUNT(*) AS candidates_now
FROM shadow_trades st
JOIN recommendations r ON st.recommendation_id = r.recommendation_id
WHERE st.status='closed'
  AND COALESCE(st.quarantined,0)=0
  AND st.recommendation_id NOT IN (
    SELECT recommendation_id
    FROM training_examples
    WHERE recommendation_id IS NOT NULL
  );
```

## Conclusion
The collection pipeline is functioning as a strict filtered batch process. The strongest failure mode for "completed trade but no training example" is eligibility mismatch (`needs_manual_review` / missing recommendation linkage), followed by generation availability and ingestion-gate rejection.
