# B8 — LLM-set per-trade timeout (Pass 1 design)

> **Operator addition (2026-04-25):** This task did not exist in the original Track 1.5 sprint plan. It was added during Pass 1 review when the operator surfaced the design issue that B3's investigation pointed at: a single global `timeout_days=15` is the wrong shape for thesis-aware position management. The LLM at trade-open time has the per-trade context (conviction, key risk, regime) that should drive the expected holding window. This task adds the LLM-emitted value to the existing recommendation-and-trade pipeline.

## Pass 1 finding — what's wrong with the current model

`shadow_trades.timeout_days` exists in the schema (`src/schema/registry.py:229`, INTEGER DEFAULT 15) but in the bootcamp archive:

| State | Count |
|---|---|
| Closed timeout-tagged rows with `timeout_days` populated | 0 |
| Closed timeout-tagged rows with `timeout_days = NULL` | 4 (WMT, GOOG, plus 2 not in A2's investigation set) |
| Currently-open rows with `timeout_days` populated | 1 (open WMT, value=15) |

So when a trade times out today, the reconciliation predicate has no per-trade value to compare against — it's stuck with the default. WMT and GOOG closed at 8 calendar days, well below the 15-day default; without per-trade context we can't tell whether that was correct (the LLM thought it was a 5-day trade and the trade was already past expectation) or a defect (the executor used market days vs calendar days).

The LLM packet at trade-open time already contains:
- `Conviction:` integer (parsed today)
- `Key Risk:` text (emitted but discarded today — B4 will start parsing)
- `Thesis:` and `Catalyst:` longer text fields (captured)

Adding `Expected Holding Period: N days` to the same `<metadata>` block is a small extension of the existing parser path.

## Implementation plan (Pass 2)

### 1. Schema — `src/schema/registry.py`

Add `llm_timeout_days INTEGER` to BOTH:

- `recommendations` table — captures what the LLM said at recommendation time
- `shadow_trades` table — captures what was actually persisted at trade open (may differ if validation rejected the LLM's value)

Default: NULL (T1.05-style schema add via `validate-schema --fix`). Nullable because pre-B8 trades won't have it.

### 2. Prompt template

The packet system prompt at `src/llm/templates/...` (Pass 2 to confirm exact path; B4's investigation found the metadata block is in `PACKET_SYSTEM_PROMPT` constant). Add inside `<metadata>`:

```
Expected Holding Period: N days  (integer 1-60; your honest estimate of how long the thesis takes to play out before timeout)
```

Position the line near `Conviction:` and `Key Risk:` so the model treats it as a structured field, not narrative.

### 3. Parser — `src/llm/packet_writer.py:_parse_llm_response()`

Extend the existing parser (the same one B4 changes for `Key Risk:`) to also extract `Expected Holding Period:`. Single regex addition; reuses B4's parsing infrastructure.

```python
# Existing (B4 will add):
key_risk = _extract_metadata_field(text, "Key Risk")

# B8 adds:
holding_period_str = _extract_metadata_field(text, "Expected Holding Period")
llm_timeout_days = _parse_holding_period(holding_period_str)
```

`_parse_holding_period` does the validation (next section) and returns `Optional[int]`.

### 4. Validation

Sanity bounds on the LLM's value:

- 1 ≤ value ≤ 60 days → use as-is
- < 1 or > 60 → fall back to NULL + log `[LLM_TIMEOUT_INVALID] received={raw!r} ticker={ticker} fallback=NULL`
- Missing entirely → NULL (no warning — Pass 2 prompt may not always elicit it)
- Non-integer (e.g., "2 weeks") → NULL + warn

`shadow_trades.timeout_days` then chains: if `llm_timeout_days IS NOT NULL` use it, else fall back to global default 15. The chain happens in the executor at trade-open time (next section), not at reconciliation time.

### 5. Executor — trade-open path

`src/shadow_trading/executor.py` open path (around line 1000-1030 per B5's reading of the same file). At trade open, when populating the new `shadow_trades` row:

```python
shadow_trade.timeout_days = (
    recommendation.llm_timeout_days
    if recommendation.llm_timeout_days is not None
    else GLOBAL_DEFAULT_TIMEOUT_DAYS  # 15
)
```

This means by the time B3's reconciliation pass runs, `shadow_trades.timeout_days` is always populated (either with the LLM's value or the default). B3's COALESCE chain becomes simpler — it doesn't need to fall back through `recommendations` table at reconciliation time.

### 6. Service-layer wiring

- `src/services/scan_service.py` — pass `llm_timeout_days` to `log_recommendation` (coordinates with B4 — same signature change)
- `src/services/mr_scan_service.py` — same (per operator scope extension to mr_scan_service for B4 + B8)

### 7. Coordination with B4

B4 (`Key Risk` parsing) and B8 (`Expected Holding Period` parsing) touch identical files:

- `src/llm/packet_writer.py` (parser extension)
- `src/services/scan_service.py` + `mr_scan_service.py` (signature change for `log_recommendation`)
- LLM prompt template

**Pass 2 recommendation:** dispatch B4 + B8 as a single developer task. The parser change is one diff, the service signature change is one diff, the prompt change is one diff. Splitting into 2 tasks doubles the touch count without value.

If split is preferred for traceability, run B4 first (smaller change — reason text only), then B8 amends the same parser to also extract `Expected Holding Period`. Avoid concurrent execution to prevent merge conflicts.

### 8. Coordination with B3

B3's reconciliation predicate as designed today:

```sql
-- B3 design line 257 (Pass 1 pre-B8):
COALESCE(duration_days, ...) >= COALESCE(timeout_days, 15)
```

Post-B8, the predicate stays the same — but `timeout_days` is now reliably populated at trade-open time (executor stamps either the LLM value or the default). B3's `COALESCE(timeout_days, 15)` is a defensive fallback for pre-B8 rows; post-B8 trades won't need it.

**B3 design doc updated** in this same Pass 1 commit to add a note: "post-B8, `shadow_trades.timeout_days` is always populated; the COALESCE fallback to 15 is a backward-compat shim for pre-B8 rows only."

## Test strategy (Pass 2)

`tests/llm/test_timeout_persistence.py` (NEW) — coordinates with B4's `test_conviction_reason_persistence.py`. Could be one combined test file if the dispatch is one task.

| Case | Expected |
|---|---|
| LLM emits `Expected Holding Period: 30 days` | `recommendations.llm_timeout_days = 30`, `shadow_trades.timeout_days = 30` |
| LLM emits no holding period field | `llm_timeout_days = NULL`, `shadow_trades.timeout_days = 15` (default) |
| LLM emits `Expected Holding Period: 0 days` (out of range low) | `llm_timeout_days = NULL` + warning log; `shadow_trades.timeout_days = 15` |
| LLM emits `Expected Holding Period: 90 days` (out of range high) | Same as above |
| LLM emits `Expected Holding Period: 2 weeks` (non-integer) | Same as above |
| Reconciliation predicate uses per-trade value | Synthetic trade with `timeout_days=5` and `duration_days=8` → flagged as exceeding timeout |

## Schema design summary

```python
# src/schema/registry.py — recommendations table additions
ColumnDef(
    name="llm_timeout_days",
    type="INTEGER",
    nullable=True,
    description="LLM's estimated holding window in days (1-60). NULL if not emitted or out of range.",
),

# src/schema/registry.py — shadow_trades table addition (already has timeout_days; add llm_timeout_days
# for clarity/audit even though shadow_trades.timeout_days is the operative value)
ColumnDef(
    name="llm_timeout_days",
    type="INTEGER",
    nullable=True,
    description="What the LLM said at recommendation time. shadow_trades.timeout_days is the operative value (= llm_timeout_days OR global default).",
),
```

The dual-column structure (LLM-said vs operative) lets Stage 2 / Stage 3 evaluation answer "did the trade exit on its expected timeline" without losing the original LLM input. The operative `timeout_days` could equal the LLM value, or could equal the default if the LLM produced an invalid value — capturing both columns preserves the audit trail.

## Scope fence verification

Pass 2 files touched (anticipated):

| File | Why | Counts toward sprint scope? |
|---|---|---|
| `src/schema/registry.py` | Add 2 columns | Yes — schema add is sprint-acceptable per T1.05 pattern |
| `src/llm/packet_writer.py` | Parser extension | In B4's stated scope |
| `src/services/scan_service.py` | log_recommendation signature | In B4's stated scope |
| `src/services/mr_scan_service.py` | Same | Per operator scope extension |
| `src/shadow_trading/executor.py` | Stamp timeout_days at trade open | NEW — B8-specific. Coordinates with B5's open-path edit (non-overlapping per B5 design — B5 stamps `instrumentation_version`, B8 stamps `timeout_days`, both in trade-open prelude) |
| LLM prompt template path | Add prompt line | NEW — B8 + B4 share this file |
| `tests/llm/test_timeout_persistence.py` | New test file | New |

Total: 5-6 files (depending on prompt template path count). Sprint scope rule says ESCALATE if >2 files outside listed scope — B8 is the *operator-added* task, so by definition the operator authorizes its scope. Documenting for traceability.

Coordination with executor.py edits (4 tasks now touch this file):
- **B1** — exit path (lines ~1713-1964)
- **B5** — open path (~lines 1000-1030, module constant)
- **B8** — open path (same area as B5; stamps `timeout_days`)
- **B2.B** — exception handling sites (multiple locations)

Pass 2 ordering recommendation:
1. B5 (constant + open-path stamping for instrumentation_version)
2. **B8 (open-path stamping for timeout_days — overlaps with B5 area)**
3. B1 (exit path — non-overlapping with B5/B8)
4. B3 (taxonomy in writers + new reconciliation module — non-overlapping)
5. B2.A → B2.B → B2.C (exception sites — non-overlapping with B1/B5/B8 logic but same file for B2.B)

## Risks / unknowns

1. **Prompt elicitation rate** — when the LLM is first instructed to emit `Expected Holding Period`, the rate of compliance won't be 100%. B4's investigation found `Key Risk:` is emitted reliably; whether `Expected Holding Period:` will be emitted as reliably is empirical. The graceful-degradation path (fall back to default 15) handles non-emission, but Stage 2 evaluation needs a non-trivial sample of trades WITH the LLM value. Pass 2 should track elicitation rate as a metric.

2. **Bound validation cliff** — 1 ≤ value ≤ 60 is a guess. The current default 15 implies the operator's mental model is ~2-3 weeks. If the LLM consistently emits 90+ for long-duration plays, we'll either (a) widen the bound or (b) accept the LLM's input as the strategy's actual horizon. Pass 2 should make the bound configurable via `config/settings.local.yaml` so the operator can tune without code change.

3. **LLM retraining** — adding a new field to the prompt template may require retraining the fine-tuned `halcyon-v1` to honor it. Sprint anti-goal: "do NOT retrain the LLM." Pass 2 ships the prompt change + parser; if elicitation rate is too low to be useful, retraining belongs in a separate sprint.

4. **Backfill of pre-B8 trades** — out of scope. `recommendations.llm_timeout_days = NULL` for all pre-B8 rows is correct (the LLM was never asked). `shadow_trades.timeout_days` stays as it was (NULL or 15 default) for pre-B8 trades. The B5 instrumentation_version sentinel covers analytics filtering ("only count trades where the strategy had per-trade timeout intelligence" = `instrumentation_version >= 3`).

## Pass 2 commit message template

```
feat(llm): persist LLM-set per-trade timeout (Track 1.5 / B8)

Add Expected Holding Period: to the LLM packet metadata block. Parse
into recommendations.llm_timeout_days and persist to shadow_trades.
timeout_days at trade open (replacing global default 15).

Validation: 1 ≤ value ≤ 60 days; out-of-range falls back to default
with [LLM_TIMEOUT_INVALID] warning. Missing field → silent NULL fallback
to default.

Coordinates with B3 (reconciliation predicate uses per-trade value), B4
(same parser path), B5 (same trade-open prelude).

Closes Track 1.5 / B8 (operator-added task).
```
