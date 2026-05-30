# Sprint 1.A.x.1 — Tier B Corporate Actions for SP100 PIT (#803 follow-up)

## Goal

Extend `_CURATED_CHANGES` in `scripts/build_sp100_history.py` with **Tier B** corporate-action records to close the residual ticker-rename / merger / acquisition bias remaining after Sprint 1.A.x's Tier A coverage. Same schema and reverse-application logic as 1.A.x — this sprint is purely about adding more events.

After this sprint, backtests should be unbiased for **at least four additional ticker-rename/removal events** that have been observed in SP100 between 2015 and today.

Originating tracker: **#803** (the same tracker as 1.A.x; this sprint is the explicit Tier B follow-up).

## Tier B confirmed events (4)

Operator-verified during Sprint 1.A.x execution. All event dates confirmed against authoritative source (S&P press releases or equivalent). Ready for `_CURATED_CHANGES` insertion as-is.

### Event 1 — FB → META rename

- **Date:** 2022-06-09 ✓ verified
- **Schema:** `{"date": "2022-06-09", "type": "rename", "from": "FB", "to": "META"}`
- **Bias window:** ~2.5 years of pre-rename data fixed

### Event 2 — CELG removal-via-acquisition

- **Date:** 2019-11-20 ✓ verified
- **Schema:** `{"date": "2019-11-20", "type": "removal-via-acquisition", "from": "CELG"}`
- **Acquirer:** Bristol Myers Squibb
- **Bias window:** 4+ years of pre-removal data fixed (CELG appears in pre-2019-11 snapshots)

### Event 3 — S (Sprint Corp.) removal-via-acquisition

- **Date:** 2020-04-01 ✓ verified
- **Schema:** `{"date": "2020-04-01", "type": "removal-via-acquisition", "from": "S"}`
- **Acquirer:** T-Mobile (TMUS)
- **Bias window:** 5+ years of pre-removal data fixed (S appears in pre-2020-04 snapshots)

### Event 4 — DWDP → DOW rename (Decision (a) — operator confirmed)

- **Date:** 2019-04-02
- **Schema:** `{"date": "2019-04-02", "type": "rename", "from": "DWDP", "to": "DOW"}`
- **Decision rationale:** Treat the DowDuPont split as a rename (DWDP → DOW only) rather than a multi-entity spinoff. Reasons:
  - Today's SP100 contains DOW only (not CTVA, not DD)
  - Treating it as a spinoff to [DOW, CTVA, DD] would over-attribute SP100 membership to CTVA and DD if they never actually entered the index
  - The rename schema already exists and handles this case correctly; spinoff handling for partial-entity-only-survives-in-SP100 is more complex and not needed for this sprint
- **Bias window:** ~3 years of pre-2019-04 data fixed (DWDP appears in pre-rename snapshots)

## Explicitly skipped (Tier C — not in SP100 or unverifiable)

- **T → WBD spinoff** (2022-04-08): WBD was never an SP100 constituent. T retained AT&T core; no SP100 impact.
- **GE → GEHC spinoff** (2023-01-04): GEHC is in SP500 but not SP100. No SP100 impact.
- **GOOG/GOOGL share class** (2014-04-03): Pre-coverage (before 2015-03-19). #799 territory.

## Operator-resolved decisions (settled before dispatch)

These mirror Sprint 1.A.x's settled decisions for consistency:

1. **Schema:** Use the existing type-tagged event schema from Sprint 1.A.x (rename / merger / spinoff / removal-via-acquisition). No new event types needed for Tier B.

2. **Validator updates:** Extend `_HISTORICAL_TICKER_CHECKS` in `_validate_table()` with at-least-one-above + at-least-one-below assertions per new event (mirroring the Tier A spot-check pattern from #804).

3. **Smoke backtest updates:** Extend `SPOT_CHECKS` in `scripts/smoke_backtest_pit.py` with the new event boundaries so the smoke check regression-locks Tier B too.

4. **Out of scope:** Pre-2015 backfill (#799 — separate sprint). Real-time corporate-action ingestion (Sprint 1.X — separate). Tier C events (T→WBD, GE→GEHC, GOOG/GOOGL).

## Required deliverables

Mirror of Sprint 1.A.x's task graph, scaled to Tier B's smaller scope:

### 1. Pre-flight verification — `docs/audits/2026-04-28-sprint-1.A.x.1-tier-b/pre-flight.md`

For each Tier B event the operator confirms:
- S&P press release URL (or other authoritative source)
- Verified date in YYYY-MM-DD form
- Bias window estimate (years of biased data this fixes)

PM-direct (per Sprint 1.A.x precedent — Planner-cap concerns now resolved by PR #817's bump, but the work is small enough PM-direct is faster).

### 2. `_CURATED_CHANGES` extension — `scripts/build_sp100_history.py`

Add 4 records (operator-confirmed during spec drafting):
```python
{"date": "2019-04-02", "type": "rename", "from": "DWDP", "to": "DOW"},
{"date": "2019-11-20", "type": "removal-via-acquisition", "from": "CELG"},
{"date": "2020-04-01", "type": "removal-via-acquisition", "from": "S"},
{"date": "2022-06-09", "type": "rename", "from": "FB", "to": "META"},
```

Records inserted in chronological position; sort_keys+sort_values invariants preserved.

### 3. `_HISTORICAL_TICKER_CHECKS` extension — same file

Add 12 spot-checks (one above + one below each event date, plus a couple of "current" anchors):
```python
# DWDP → DOW rename (2019-04-02)
("2018-06-01", "DWDP", True),    # pre-rename: DWDP present
("2018-06-01", "DOW",  False),   # pre-rename: DOW absent
("2024-06-01", "DOW",  True),    # post-rename: DOW present (still SP100 today)
# CELG removal-via-acquisition (2019-11-20)
("2018-06-01", "CELG", True),    # pre-removal: CELG present
("2024-06-01", "CELG", False),   # post-removal: CELG absent
# S removal-via-acquisition (2020-04-01)
("2018-06-01", "S",    True),    # pre-removal: S present
("2024-06-01", "S",    False),   # post-removal: S absent
# FB → META rename (2022-06-09)
("2020-06-01", "FB",   True),    # pre-rename: FB present
("2020-06-01", "META", False),   # pre-rename: META absent
("2024-06-01", "META", True),    # post-rename: META present (still SP100 today)
("2024-06-01", "FB",   False),   # post-rename: FB absent
```

### 4. Regenerate `data/reference/sp100_history.json`

Run `python scripts/build_sp100_history.py`. Verify:
- Idempotent (re-run = byte-identical)
- All validator spot-checks (Tier A from 1.A.x + new Tier B) pass
- Snapshot count may grow (new event dates add new snapshot keys)
- `pit.get_all_historical_tickers()` should now include FB, CELG, S (+DWDP if Decision 4 ≠ skip) on top of Tier A's PCLN/KRFT/UTX/RTN/EMC/YHOO

### 5. Smoke backtest extension — `scripts/smoke_backtest_pit.py`

Add 11 Tier B entries to the `SPOT_CHECKS` list:
```python
# DWDP → DOW rename (2019-04-02)
("2018-06-01", "DWDP", True,  "DowDuPont was DWDP until 2019-04-02"),
("2018-06-01", "DOW",  False, "DOW didn't exist as SP100 ticker pre-rename"),
("2024-06-01", "DOW",  True,  "Post-rename, DOW should be present"),
# CELG removal (2019-11-20)
("2018-06-01", "CELG", True,  "Celgene was SP100 until BMS acquisition"),
("2024-06-01", "CELG", False, "Post-acquisition, CELG should be gone"),
# S removal (2020-04-01)
("2018-06-01", "S",    True,  "Sprint Corp was SP100 until T-Mobile merger"),
("2024-06-01", "S",    False, "Post-merger, S should be gone"),
# FB → META rename (2022-06-09)
("2020-06-01", "FB",   True,  "Facebook was FB until 2022-06-09"),
("2020-06-01", "META", False, "META didn't exist as ticker pre-rename"),
("2024-06-01", "META", True,  "Post-rename, META should be present"),
("2024-06-01", "FB",   False, "Post-rename, FB should be gone"),
```

### 6. Tests — `tests/scripts/test_build_sp100_history.py`

Add per-event reverse-application tests if any introduce a NEW pattern not already covered by 1.A.x tests. Most events are already covered by existing rename / merger / removal-via-acquisition tests, so likely 0-2 new tests needed.

### 7. Docs

- Update `scripts/build_sp100_history.py` module docstring to list Tier B coverage
- Update CLAUDE.md `pit.py` Wired entry to mention Tier B
- Update PR #802's "ticker-rename caveat" note (if any survived 1.A.x's T5 cleanup)

## Acceptance gates

1. **Operator-confirmed event dates** — each Tier B event has a verified S&P press release URL or equivalent in pre-flight.md
2. **Validator spot-checks PASS** on regenerated JSON (Tier A + Tier B)
3. **Smoke backtest passes** with Tier B SPOT_CHECKS added
4. **Cross-check sample backtest dates**:
   - `pit.get_sp100_at("2020-06-01")` includes FB (not META)
   - `pit.get_sp100_at("2018-01-01")` includes CELG, S
5. **Text-masking superset** (`pit.get_all_historical_tickers()`) includes FB, CELG, S in addition to Tier A historical names

## Reference docs

- **#803** — originating tracker (HIGH, this sprint resolves the Tier B sub-bucket)
- **#60** — task tracking (this sprint)
- PR #802 + #813 reviews — operator's verification of which events are real
- Sprint 1.A.x (`docs/audits/2026-04-27-sprint-1.A.x-corp-actions/`) — schema design + Tier A coverage (must be merged before this sprint dispatches)

## Strict-rigor receipts (per PR #749 + #806 + #817)

- Spec committed as deliverable 0 to `sprint/1.A.x.1-tier-b/base` (PR #806 rule)
- Pre-flight committed as deliverable 1
- **Stale-base check before PR-create** (PR #817 rule) — PM verifies merge-base = origin/main HEAD, rebases if not, verifies post-rebase diff matches expected scope, then `git push --force-with-lease`
- Worktree-isolated agents (SD-06)
- Per-deliverable commits (DR-05)
- PR body regenerated from final git log (DR-06)
- Pre-existing failures from canon doc (CQ-07)
- `test_repo_structure.py` output disclosed (#731)
- No skip / xfail / weakening
- Branch_pushed verification per PR #806 — Developer agents MUST push before reporting DONE

## Out of scope

- **Pre-2015 backfill** (#799) — separate sprint
- **Real-time corporate-action ingestion** (Sprint 1.X if needed)
- **Tier C events** — T→WBD, GE→GEHC, GOOG/GOOGL (each requires separate research; file as #803 sub-trackers if confirmed real)
- **Methodology wiring** (Sprint 1.B — gated on this merging)

## Coding-team skill notes

This is a small feature wave. PM-direct pre-flight (small enumeration), single Developer for code+tests+docs (or 2-3 in parallel if scope grows). QA Reviewer always; Performance Reviewer NOT required (one-shot script); Security Reviewer NOT required (no auth, no user input). Integrator runs final regression sweep + canon doc update + smoke verification.

Estimated total wall-clock: ~30-45 min from operator dispatch (vs ~2-3 hours for 1.A.x because schema/logic/validator already exist).

## Operator action gates (during execution)

1. **Pre-flight verification** — pre-flight.md must commit S&P press release URLs (or equivalent authoritative sources) for all 4 events. If any URL can't be confirmed at execution time, STOP and await operator decision.
2. **Re-pin protocol** — if regenerated JSON's spot-checks pass but any test under `tests/` has pinned numerics that shift because of the new tickers, re-pin per the protocol from Sprint 1.A.1 spec (≤5% comment-update with `# T10/Tier-B re-pin: was X; now Y`; >5% BLOCK).
3. **Stale-base gate** — when integration is opened, the new gate from PR #817 fires automatically. PM rebases onto current main, verifies post-rebase diff matches expected scope (5 files: 2 docs, 2 scripts, 1 data + 0-1 test if anything new), force-pushes-with-lease.

---

**Status when this spec is committed:** READY — all operator decisions resolved (4 events confirmed, DWDP=rename(a), T→WBD/GE→GEHC=skip). Awaiting Sprint 1.A.x merge before /code dispatch.
