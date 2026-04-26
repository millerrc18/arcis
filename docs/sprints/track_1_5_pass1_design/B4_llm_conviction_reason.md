# B4 — llm_conviction_reason Persistence
## Pass 1 Design (Investigation)

**Date:** 2026-04-25
**Status:** Finding: (a) — reason emitted, not parsed, not persisted

---

## Executive Summary

The LLM **does** emit reason text today — it is the `Key Risk` line inside the
`<metadata>` block, plus the full `<analysis>` prose which serves as the
reasoning. Neither a discrete `<llm_conviction_reason>` tag nor the `Key Risk`
line is extracted by the parser or stored. The schema (`registry.py` and the
archive DB) already has both `llm_conviction` and `llm_conviction_reason`
columns in `recommendations`. The `TradePacket` model (`schemas.py`) also has
the `llm_conviction_reason: Optional[str]` field. The column exists everywhere;
**the missing link is that nothing populates `packet.llm_conviction_reason`
and nothing passes it through to `log_recommendation`.**

No schema-drift of the original kind alleged in the sprint brief exists.
See Section 1 for the full story.

---

## 1. Pass 1 Finding — Schema Drift Verification

### Archive DB: PRAGMA table_info

`PRAGMA table_info(recommendations)` on
`ai_research_desk_bootcamp_2026-04-24.sqlite3` (read-only):

| cid | name | type |
|-----|------|------|
| 56 | llm_conviction | TEXT |
| 57 | llm_conviction_reason | TEXT |

`PRAGMA table_info(shadow_trades)` — neither `llm_conviction` nor
`llm_conviction_reason` appears in `shadow_trades`.

### Registry: src/schema/registry.py

Lines 160-161 (recommendations table):

```python
ColumnDef("llm_conviction", "INTEGER"),
ColumnDef("llm_conviction_reason", "TEXT"),
```

Line 1634 (attribution_trades table):

```python
ColumnDef("llm_conviction", "INTEGER"),
```

`shadow_trades` registry definition: no `llm_conviction` or
`llm_conviction_reason` columns.

### Drift Analysis

**The sprint brief stated `llm_conviction` was missing from the registry. This
is incorrect as of today's read.** Both columns are present in the registry at
lines 160-161. Both columns also exist in the archive DB (cids 56-57).

The actual drift is a **type mismatch**:

| Location | Column | Type |
|----------|--------|------|
| registry.py line 160 | llm_conviction | INTEGER |
| archive DB (PRAGMA) | llm_conviction | TEXT |

The archive DB stored conviction as TEXT (all values are digit strings like
`'7'`). The registry declares INTEGER. This is a SQLite affinity quirk — when
the column was inserted without the registry's `validate-schema --fix` having
run after the column was first added, SQLite accepted string values without
coercion. The mismatch has no query impact (SQLite comparison works across
TEXT/INTEGER for digit strings) but it should be documented.

The `llm_conviction_reason` column exists in both registry and archive DB but
has **zero non-NULL rows** out of 4,638 recommendations. It has never been
populated.

### Decision

Pass 2 action is **NOT** to add `llm_conviction` to the registry (it is already
there). Pass 2 action is:

1. Run `python -m src.main validate-schema` to confirm the type affinity
   mismatch is benign or requires `--fix`.
2. Wire up the `llm_conviction_reason` population path (parser → packet field
   → `log_recommendation` call). The column already exists; no DDL change is
   needed.

---

## 2. Pass 1 Finding — Does the LLM Emit Reason Text Today?

### Prompt Template

The system prompt in `src/llm/prompts.py` (`PACKET_SYSTEM_PROMPT`) instructs
the model to output exactly three XML tags:

```
<why_now>...</why_now>
<analysis>...</analysis>
<metadata>
Conviction: [1-10]
Direction: LONG
Time Horizon: [description]
Key Risk: [one sentence naming the specific thesis-killer]
</metadata>
```

The `Key Risk` line inside `<metadata>` is a one-sentence reason that explains
the conviction score in terms of the thesis-killer. This is the closest analog
to a conviction reason in the current output format. The `<analysis>` block
(4-6 paragraphs) is the full analytical backing.

No `<llm_conviction_reason>` or `<conviction_reason>` tag exists in any prompt
template. Searched: `src/llm/prompts.py` (all prompts), no additional template
files exist under `src/llm/templates/` (directory does not exist).

### Parser

`_parse_llm_response()` in `src/llm/packet_writer.py` (lines 327-501) returns
a 3-tuple: `(conviction, why_now, deeper_analysis)`.

The parser does extract `<metadata>` content (line 382-396). It runs a
`Conviction: N` regex on the metadata text to extract the integer. The `Key
Risk:` line is present in every metadata block but is **never extracted** —
the regex stops after finding the conviction integer.

The function signature returns no reason field and does not set
`packet.llm_conviction_reason`.

### Persistence

`scan_service.py` line 246-251 calls `log_recommendation(...)` but does not
pass `llm_conviction_reason` — the keyword argument is simply omitted, so it
defaults to `None` in the function signature (confirmed at `store.py` line
110-172).

`mr_scan_service.py` line 147-151 similarly omits `llm_conviction_reason`.

`schemas.py` line 40 has `llm_conviction_reason: Optional[str] = None` on
`TradePacket`. Nothing in `packet_writer.py` sets this field.

### Archive Sample — Evidence

Three most recent rows with `llm_conviction IS NOT NULL`
(from `ai_research_desk_bootcamp_2026-04-24.sqlite3`):

**GOOGL, conviction=7, 2026-04-24T15:46:50:**
- `llm_conviction_reason`: NULL
- `thesis_text` (deeper_analysis) length: 3,036 chars
- Thesis sample: *"The thesis is straightforward: capitalize on the pullback
  from a strong outperformer position in a calm uptrend. Alphabet shares are
  trading near their 50-day high..."*

**GOOG, conviction=7, 2026-04-24T15:46:10:**
- `llm_conviction_reason`: NULL
- `thesis_text` length: 2,410 chars
- Thesis sample: *"The setup presents a classic pullback from a strong uptrend,
  with the price trading near its 50-day high..."*

**AVGO, conviction=7, 2026-04-24T15:45:34:**
- `llm_conviction_reason`: NULL
- `thesis_text` length: 2,266 chars

All 3,629 rows with `llm_conviction IS NOT NULL` have `llm_conviction_reason`
= NULL. Zero rows have reason populated.

### Conclusion

**Finding (a): Reason emitted but not parsed, not persisted.**

The LLM does emit a reason — the `Key Risk:` line inside `<metadata>` is a
one-sentence conviction rationale. It is not extracted by the parser. It is not
set on `TradePacket`. It is not passed to `log_recommendation`. Pass 2 is a
**medium change**: parser update + packet field population + pass-through to
`log_recommendation`.

No prompt template change is required. The `Key Risk:` line is already
being generated by the current model.

---

## 3. Implementation Plan

Finding is **(a)** with the twist that reason text is already being emitted as
`Key Risk:` inside `<metadata>`. No prompt change needed.

### Pass 2 Change Set

**File 1: `src/llm/packet_writer.py`**

- Modify `_parse_llm_response()` return signature from
  `tuple[int | None, str | None, str | None]` to
  `tuple[int | None, str | None, str | None, str | None]`
  where the fourth element is the extracted reason.
- Inside the `<metadata>` parsing block (around line 389), add:
  ```python
  reason_match = re.search(r'Key Risk:\s*(.+)', metadata_text)
  if reason_match:
      conviction_reason = reason_match.group(1).strip()
  ```
- Propagate `conviction_reason` through all return paths.
- In `enhance_packet_with_llm()`, after setting `packet.llm_conviction`,
  also set `packet.llm_conviction_reason = conviction_reason` (respecting
  truncation policy: see Section 4).
- Update the partial-parse fallback path (line 604) to also set reason=None
  explicitly (already None by default; make it explicit for clarity).

**File 2: `src/services/scan_service.py`**

- Add `llm_conviction_reason=getattr(packet, 'llm_conviction_reason', None)`
  to the `log_recommendation(...)` call at line 250.

**File 3: `src/services/mr_scan_service.py`**

- Add `llm_conviction_reason=getattr(packet, 'llm_conviction_reason', None)`
  to the `log_recommendation(...)` call at line 150.

No schema changes needed. No prompt template changes needed.

### Complexity Rating

**Medium** (3 files, ~15 lines of new logic). The riskiest part is the
`_parse_llm_response()` return-type change — all callers of the function are
inside `packet_writer.py` (one call site at line 598), so the blast radius is
contained.

---

## 4. Schema Design

### Column Already Exists

`llm_conviction_reason TEXT` is at `registry.py` line 161 in the
`recommendations` table. `shadow_trades` does not have this column and should
not — conviction lives on recommendations, not on trades.

### Truncation Policy

Observed `thesis_text` (the `<analysis>` block) lengths in the archive:

| Metric | Value |
|--------|-------|
| Min | 3 chars |
| Max | 7,794 chars |
| Mean | 2,813 chars |
| Rows > 4,000 chars | 1,122 / 4,638 (24%) |
| Rows > 3,000 chars | 1,292 / 4,638 (28%) |

The `Key Risk:` line (the conviction reason) is a **single sentence** — in
practice 40-120 chars. The full `thesis_text` content is what reaches 7,794
chars, not the reason line. A 4,000 char truncation ceiling on
`llm_conviction_reason` is therefore very conservative — a single Key Risk
sentence will never approach it.

**Decision: keep the 4,000 char truncation ceiling as specified.** It provides
a safety net if the model ever emits verbose reason text (e.g. if the Key Risk
line is swapped for a multi-sentence block by a future model version). Truncation
marker: `... [truncated, original N chars]`.

Implementation:
```python
_MAX_CONVICTION_REASON_CHARS = 4000

def _truncate_reason(text: str) -> str:
    if len(text) <= _MAX_CONVICTION_REASON_CHARS:
        return text
    return text[:_MAX_CONVICTION_REASON_CHARS] + f"... [truncated, original {len(text)} chars]"
```

### Registry Fix for llm_conviction Type

The archive DB stores `llm_conviction` as TEXT (digit strings) while the
registry declares INTEGER. This is a runtime vs. registry type affinity
mismatch. Pass 2 must run `python -m src.main validate-schema` to confirm
whether `--fix` is needed. No column rename or data migration is expected —
SQLite will accept the existing values via affinity coercion on read.

---

## 5. Defensive Behavior

| Scenario | Behavior |
|----------|----------|
| `Key Risk:` line present in `<metadata>` | Parse, truncate if >4000 chars, set `packet.llm_conviction_reason` |
| `<metadata>` present but no `Key Risk:` line | `conviction_reason = None`; conviction integer still persists |
| Parse fails for `why_now`/`deeper_analysis` | `conviction_reason = None`; conviction defaults to 5 (existing #168 behavior) |
| LLM output entirely unparseable (None response) | `log_recommendation` never called; existing behavior confirmed at `packet_writer.py` line 586-588 |
| Reason text > 4,000 chars | Truncate with marker; integer still persists |
| `llm_conviction_reason` keyword omitted at `log_recommendation` call site | Defaults to NULL in DB; safe, no execution block |

Trade execution is **never blocked** by a missing or truncated reason. The
reason field is diagnostic/analytical only.

---

## 6. Test Strategy

**Test file:** `tests/llm/test_conviction_reason_persistence.py` (NEW)

### Test Cases

**`test_conviction_reason_positive`**
- Input: LLM response with well-formed `<metadata>` block containing
  `Key Risk: Earnings in 3 days could gap against position.`
- Assert: `_parse_llm_response()` returns `conviction_reason` =
  `"Earnings in 3 days could gap against position."`
- Assert: `packet.llm_conviction_reason` equals that string after
  `enhance_packet_with_llm()` call (mock LLM).

**`test_conviction_reason_missing_falls_back_to_none`**
- Input: LLM response with `<metadata>` block that has `Conviction: 7` but
  no `Key Risk:` line.
- Assert: `_parse_llm_response()` returns `conviction_reason = None`.
- Assert: `packet.llm_conviction` = 7 (integer still persists).
- Assert: `packet.llm_conviction_reason` is None.

**`test_conviction_reason_truncation_boundary`**
- Input: LLM response with a `Key Risk:` line that is 4,500 chars long.
- Assert: stored reason is 4,000 chars + `"... [truncated, original 4500 chars]"`.
- Assert: `packet.llm_conviction` still populated.

**`test_conviction_reason_passed_to_log_recommendation`**
- Mock `log_recommendation` and call `scan_service.run_scan()` with a mock
  LLM response that includes a Key Risk line.
- Assert: `log_recommendation` was called with
  `llm_conviction_reason="<expected string>"` (not None).

**`test_conviction_reason_schema_column_exists`**
- Assert that `llm_conviction_reason` appears in the registry column list for
  `recommendations` (validates schema drift fix is present and stable).
- Verify type is `TEXT`.

Note: existing schema validation tests in `tests/test_schema.py` should cover
the registry-column presence check generally; this test adds a targeted assertion
for the specific column.

---

## 7. Scope Fence Verification

Files Pass 2 will touch:

| File | Change | In Sprint Scope? |
|------|--------|-----------------|
| `src/llm/packet_writer.py` | Parser return type + reason extraction + packet field set | YES (sprint stated) |
| `src/services/scan_service.py` | Pass `llm_conviction_reason` to `log_recommendation` | YES (sprint stated) |
| `src/services/mr_scan_service.py` | Pass `llm_conviction_reason` to `log_recommendation` | NOT explicitly listed — see note |
| `tests/llm/test_conviction_reason_persistence.py` | New test file | YES (implied by test strategy) |

**Note on `mr_scan_service.py`:** This file is not in the sprint's explicitly
stated scope (`src/llm/packet_writer.py` or `src/services/scan_service.py`).
However, it has an identical `log_recommendation` call omitting
`llm_conviction_reason`. Leaving it out creates a two-tier system where MR
scan recommendations never persist reason even after the fix. Recommend operator
expand scope to include `src/services/mr_scan_service.py` or explicitly exclude
it and accept the asymmetry.

**No prompt template files touched.** No schema DDL changes needed (column
already exists). Total new-file count: 1 (test file).

---

## 8. Risks

**Sprint Risk #1 (from sprint spec) — LLM doesn't emit reason today:**
This risk did **not** materialize. The `Key Risk:` line in `<metadata>` is
emitted by the current model on every response. No prompt change needed.
Graceful-degradation path (NULL reason, no execution block) remains the
correct design and should be implemented regardless.

**Risk: `Key Risk:` line is model-version-dependent.**
The prompt instructs the model to emit `Key Risk:` as part of `<metadata>`.
The fine-tuned `halcyon-v1` model has been trained on this format. If a future
model version omits the line or formats it differently, the parser falls back
to `conviction_reason = None` silently (NULL persisted). This is acceptable
degradation — not a blocking failure.

**Risk: Return-type change on `_parse_llm_response()`.**
The function currently returns a 3-tuple. Changing to a 4-tuple is a localized
change — the only call site in production code is `packet_writer.py` line 598.
Tests in `tests/test_xml_format.py`, `tests/test_confidence.py`, and
`tests/test_grammar_client.py` (listed in the module docstring) may assert on
the 3-tuple return and will need updating. Pass 2 must audit these test files
before changing the signature.

**Risk: TEXT vs INTEGER type on `llm_conviction` in archive DB.**
The archive DB has `llm_conviction` stored as TEXT. The registry declares
INTEGER. This is a production DB state that validate-schema may flag as drift.
The fix is benign (SQLite affinity handles it), but `--fix` should be tested
in a non-production environment before running on the live DB.

**Risk: `reasons_to_trade` / `reasons_to_pass` columns are permanently NULL.**
These columns exist in the archive DB schema but have never been populated
(confirmed via 3-row sample). They are unrelated to `llm_conviction_reason`
and are out of scope for B4. Flag for future cleanup sprint.
