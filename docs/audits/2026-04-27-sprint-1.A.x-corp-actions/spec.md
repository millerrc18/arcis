# Sprint 1.A.x — Corporate-Action Handling for SP100 PIT (#803)

## Goal

Extend `_CURATED_CHANGES` in `scripts/build_sp100_history.py` to handle **rename / merger / spinoff** events in addition to the existing add/remove records. This single fix resolves THREE downstream gaps surfaced across PR #802 and PR #813 reviews:

1. **PIT universe correctness** — pre-2018 snapshots have BKNG instead of PCLN, pre-2015-07 have KHC instead of KRFT, pre-2020-04 have RTX instead of UTX+RTN. Backtests using these dates get wrong tickers.
2. **Text-masking completeness** — `pit.get_all_historical_tickers()` (PR #813 T2) returns only the union of CURRENT-NAMED tickers; PCLN/KRFT/UTX/RTN/EMC/YHOO etc. are missing → un-redacted in training text.
3. **Future PIT consumers** — anything that builds on the SP100 history JSON inherits the same blind spot.

Originating tracker: **#803** (HIGH, escalated by PR #813 review).

## Operator-resolved decisions (settled before dispatch)

1. **Schema for type-tagged events:**
   ```python
   {"date": "2018-02-27", "type": "rename", "from": "PCLN", "to": "BKNG"}
   {"date": "2020-04-03", "type": "merger", "from": ["UTX", "RTN"], "to": "RTX"}
   {"date": "2015-07-06", "type": "rename", "from": "KRFT", "to": "KHC"}  # functionally a rename of surviving entity
   ```
   Spinoffs (rare for SP100) supported in schema but not currently expected.

2. **Reverse-application logic in `build_history_table()`** — when walking backwards through changes from today:
   - **rename**: replace `to` ticker with `from` ticker in all snapshots BEFORE `date`
   - **merger**: replace `to` ticker with BOTH `from` tickers in all snapshots BEFORE `date` (note: this can violate the 100-ticker invariant temporarily — record the merger date carefully so subsequent additions/removals also reverse-apply correctly)
   - **spinoff**: replace BOTH `from` tickers with `to` ticker in all snapshots BEFORE `date` (rare)

3. **Pair with validator spot-checks** (#804, MEDIUM): land #803 + #804 together so the new event records can't silently regress. Spot-check assertions like `(2015-03-19, "PCLN", True)`, `(2015-03-19, "BKNG", False)` at JSON-build time.

4. **Out of scope**: pre-2015 backfill (#799 — separate sprint).

## Required deliverables

### 1. Pre-flight enumeration — `docs/audits/2026-04-27-sprint-1.A.x-corp-actions/pre-flight.md`

Comprehensive list of SP100 corporate actions 2015-01-01 through today. Authoritative sources to consult:
- S&P Dow Jones Indices press releases (announcements of index changes)
- Wikipedia "List of S&P 100 companies" change history (less authoritative but often more complete)
- The existing `scripts/scrape_sp_changes.py::get_sp100_known_changes` (current curated source)
- PR #802 + PR #813 reviews (operator independently verified PCLN/BKNG, KRFT/KHC, UTX+RTN/RTX, EMC, YHOO, TWX-removed-twice)

Per-event table:
| date | type | from | to | source URL | confidence |
|---|---|---|---|---|---|

**STOP if pre-flight finds blockers** — operator decides before dispatch (e.g., if a corporate action is hard to verify or the tickers' SP100 status during transition is ambiguous).

### 2. Schema + logic — `scripts/build_sp100_history.py`

- Extend `_CURATED_CHANGES` with type-tagged event records per Decision 1
- Update `build_history_table()` to handle each type's reverse-application per Decision 2
- Maintain idempotency: re-running the script produces byte-identical JSON
- Maintain ticker count invariant: snapshots must have 95-105 tickers (allow ±5 around 100 to absorb merger transitions)

### 3. Validator spot-checks — `scripts/build_sp100_history.py::_validate_table()` (closes #804)

```python
HISTORICAL_TICKER_CHECKS = [
    ("2015-03-19", "PCLN", True),   # PCLN should be in 2015 snapshot (pre-rename)
    ("2015-03-19", "BKNG", False),  # BKNG should NOT be in 2015 snapshot
    ("2018-06-18", "BKNG", True),   # BKNG should be in post-rename snapshots
    ("2015-09-18", "UTX", True),
    ("2020-12-21", "RTX", True),
    ("2020-12-21", "UTX", False),
    ("2015-03-19", "KRFT", True),   # pre-rename
    ("2015-03-19", "KHC", False),   # pre-merger
    ("2015-09-30", "KHC", True),
    # add more from pre-flight enumeration
]
```

Each entry: `(snapshot_date, ticker, expected_present)`. Validator fails loudly if any spot-check fails post-build.

### 4. Regenerate `data/reference/sp100_history.json`

Run the updated scraper script. Verify output:
- Idempotent (re-run = byte-identical)
- All validator spot-checks pass
- Snapshot count 17 (existing) or higher if new dates surface

### 5. Tests

- `tests/scripts/test_build_sp100_history.py` (existing, +N new):
  - `test_corporate_action_rename_reverse_applies` — synthetic fixture with PCLN→BKNG, verify pre-rename snapshot has PCLN
  - `test_corporate_action_merger_reverse_applies` — synthetic UTX+RTN→RTX, verify pre-merger snapshot has both
  - `test_validator_catches_missing_historical_ticker` — fixture without PCLN at 2015 should fail validation
  - `test_get_all_historical_tickers_includes_renamed_tickers` (in `tests/universe/test_pit.py` since the helper lives in pit.py) — after JSON regeneration, PCLN/KRFT/UTX/RTN should be in the union

### 6. Docs

- Update `scripts/build_sp100_history.py` module docstring to document the event-type schema
- Update PR #802's data caveat documentation to reflect the fix (move "ticker-rename bias" from "known caveat" to "fixed in #803")

## Acceptance gates

1. **Pre-flight enumeration** — operator approves the corporate-action list before implementation dispatches
2. **Validator spot-checks PASS** on the regenerated JSON
3. **Cross-check sample backtest dates**: `pit.get_sp100_at("2015-06-01")` includes PCLN (not BKNG); `pit.get_sp100_at("2017-01-01")` includes UTX + RTN (not RTX)
4. **Text-masking superset**: `pit.get_all_historical_tickers()` includes PCLN, KRFT, UTX, RTN, EMC (if it was SP100), YHOO (if it was SP100)
5. **No new test_repo_structure.py violations** — script size stays under 400 lines and individual functions under 60

## Reference docs

- **#803** — originating tracker (HIGH, post-#813 escalation)
- **#804** — validator spot-checks (MEDIUM, lands together)
- **#805** — TWX-removed-twice verification (LOW, may resolve as side-effect)
- PR #802 — Sprint 1.A.0 (loader)
- PR #813 — Sprint 1.A.1 (T10 migration; T5b text-masking now consumes the union helper)
- PR #802 review by operator — independent verification of PCLN/KRFT/UTX/RTN events
- PR #813 review by operator — independent verification + EMC, YHOO additions

## Strict-rigor receipts (per PR #749 + #806)

- Spec committed as deliverable 0 to `sprint/1.A.x-corp-actions/base` (PR #806 rule)
- Pre-flight committed as deliverable 1 (per Sprint 1.A.0 / 1.A.1 pattern)
- Worktree-isolated agents (SD-06)
- Per-deliverable commits (DR-05)
- PR body regenerated from final git log (DR-06)
- Pre-existing failures from canon doc (CQ-07)
- `test_repo_structure.py` output disclosed (#731)
- No skip / xfail / weakening / autouse-suppression
- Branch_pushed verification per PR #806 — Developer agents MUST push before reporting DONE

## Out of scope

- **Pre-2015 backfill** (#799) — separate sprint
- **Real-time corporate-action ingestion** — manual updates only for now (Sprint 1.X follow-up if needed)
- **Sprint 1.B walk-forward wiring** — comes immediately after this lands

## Coding-team skill notes

PM dispatches Planner for pre-flight first (enumeration is the Planner's primary deliverable). After operator approves enumeration, Developer implements the schema + logic + validator. QA Reviewer always; Performance Reviewer NOT required (one-shot script, not hot path); Security Reviewer NOT required (no auth, no user input — uses static curated list).

If the Planner exhausts its turn budget on enumeration (precedent from Sprint 1.A.0 + 1.A.1), PM takes over the enumeration phase directly using WebFetch on S&P Dow Jones Indices announcements.
