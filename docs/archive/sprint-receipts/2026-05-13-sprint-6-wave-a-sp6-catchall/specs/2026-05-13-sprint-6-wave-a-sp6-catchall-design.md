# Sprint 6 Wave A — SP6 Catch-All Sweep (Design Spec)

## Revision History

| Version | Date | Author | Notes |
|---------|------|--------|-------|
| v1.0 | 2026-05-13 | Design Director | Single-PR sweep covering 7 SP6 catch-all items aggregated from Sprint 5 PR reviews. Lands as Sprint 6 Wave A — BEFORE Wave B (walk-forward framework wiring). Items are independently scoped and small (~5-30 LOC each); bundle reduces coordination overhead. |

## Overview

The 7 SP6 catch-all items in `docs/roadmap.md` were each surfaced during Sprint 5 PR review cycles but explicitly deferred to a post-Sprint-5 sweep. The operator's 2026-05-13 design decision puts them into Sprint 6 as Wave A, landing as a clean foundation BEFORE the walk-forward framework wiring (Wave B = `2026-05-13-sprint-6-walkforward-impl`).

This spec captures the 7 items as a single bundled PR. Each item has a concrete resolution path already documented; the spec's job is sequencing within the PR + cross-item dependency callouts + acceptance criteria.

**Sprint 6 Wave structure:**

| Wave | Deliverable | Order | Companion design |
|------|-------------|-------|------------------|
| **Wave A** | SP6 catch-all sweep (this spec, 7 items, 1 PR) | First | this file |
| **Wave B** | Walk-forward framework wiring (T1-T15, multi-PR) | After Wave A merges | `2026-05-13-sprint-6-walkforward-impl-design.md` |

**Why Wave A first.** Two of the 7 catch-all items (`_get_finnhub_key` extraction + `_shared_migration_utils` extraction) touch files the walk-forward implementation will also touch (`scripts/run_backtest.py`, `src/data_enrichment/`). Landing the refactors first prevents Wave B from racing against in-flight cleanup.

## Operator Decisions

1. **Packaging:** Single bundled PR. All 7 items in one diff.
2. **Sprint placement:** Sprint 6 Wave A. Lands BEFORE Wave B walk-forward implementation.
3. **Target release:** v0.36.0 (Sprint 6 close, same as Wave B).
4. **CHANGELOG framing:** Single `### Changed` entry under v0.36.0 (Sprint 6 close) listing all 7 items as sub-bullets. No separate `[Unreleased]` accumulation needed since both Waves land within Sprint 6.

## The 7 Items (full inventory)

### Item 1 — `price_target` matrix resolution

**Source:** PR #1085 review (T26 finnhub_plan AST scanner). The reverse-invariant allowlist contains `price_target` because `src/data_collection/analyst_collector.py:146` calls `finnhub_plan_supports("price_target")` but `price_target` is NOT in `_FEATURE_MATRIX`. The gate always returns False; price-target collection is permanently dead code.

**Two paths:**
- (a) **Add to matrix** — `price_target` joins `_FEATURE_MATRIX['fundamental-1']`. The Finnhub `/stock/price-target` endpoint becomes active for paid plans.
- (b) **Remove dead code** — drop the entire `if finnhub_plan_supports("price_target"):` block + the `pt = {}` initialization at `analyst_collector.py:146-165` (~20 LOC).

**Spec decision (operator confirmation required at /arcis:code dispatch time):** Default to path (a) — Finnhub fundamental-1 plan DOES provide `/stock/price-target` per the Sprint 5 T25 rate-limit citation (operator already pays for the tier). Adding to matrix unlocks the endpoint with zero new code paths needed. If the price-target endpoint is operationally undesirable for some reason (e.g., excessive cost, non-deterministic responses), fall back to path (b).

**Implementation (path a):**
- `src/data_enrichment/finnhub_plan.py:42` — add `"price_target",` to `_FEATURE_MATRIX['fundamental-1']` set.
- `tests/test_finnhub_plan_runtime_coverage.py` — remove `"price_target"` from `_REVERSE_INVARIANT_ALLOWLIST` (the AST scanner will now pass because the feature is in matrix).
- Add 1 unit test verifying `finnhub_plan_supports("price_target", {"data_enrichment": {"finnhub_plan": "fundamental-1"}}) == True`.

**LOC budget:** ~5 LOC.

### Item 2 — `_get_finnhub_key` 3× duplication extraction

**Source:** PRs #1082/#1083/#1084 reviews. Three collectors duplicate the same 12-line `_get_finnhub_key()` helper byte-identically: `institutional_ownership_collector.py:38-49`, `filings_sentiment_collector.py:38-49`, `press_releases_collector.py:38-49`. Plus a fourth in `insider_collector.py` and `short_interest_collector.py` and `analyst_collector.py` (~6 sites total when including pre-Wave-C7b collectors).

**Implementation:**
- Create `src/data_collection/_finnhub_shared.py` (NEW file, ~30 LOC) exposing `get_finnhub_key() -> str | None`. Module docstring follows the codebase convention (Called by / Calls / Owns tables / Config keys / Tests).
- Replace all 6 collector-local `_get_finnhub_key` definitions with `from src.data_collection._finnhub_shared import get_finnhub_key`.
- Tests: 1 new test in `tests/data_collection/test_finnhub_shared.py` covering env-takes-precedence + YAML fallback + None on neither.

**Note: scope-creep risk.** Initially flagged as 3× duplication; sibling-search reveals it's 6×. Spec ships the broader scope to close the class completely.

**LOC budget:** ~30 LOC new + ~60 LOC removed (net -30 LOC).

### Item 3 — `_PE_REASONABLE_LO/HI` settings.yaml hook

**Source:** PR #1084 review (T24 stock_financials runtime). Hardcoded constants `_PE_REASONABLE_LO = 2.0` and `_PE_REASONABLE_HI = 200.0` in `src/data_enrichment/financials.py` should be operator-tunable.

**Implementation:**
- `config/settings.example.yaml` — add `data_enrichment.fundamental_quality_thresholds.pe_min: 2.0` and `pe_max: 200.0` entries.
- `src/data_enrichment/financials.py` — `_derive_quality_flag()` reads from config (with fallback to current hardcoded defaults for backward-compat). Use `src.config.load_config()` pattern.
- Tests: 2 new tests — quality-flag respects custom thresholds + falls back when config missing.
- Update operator-guide (T15 footprint) with the new tunable.

**LOC budget:** ~15 LOC across 3 files.

### Item 4 — `test_feature_matrix_distinguishes_free_and_premium` env-pollution

**Source:** PR #1085 review (T26 disclosure). Test at `tests/test_enrichment.py::TestFinnhubPlan::test_feature_matrix_distinguishes_free_and_premium` fails on operator's local machine because `.env` sets `FINNHUB_PLAN` which `get_finnhub_plan()` prefers over the test's explicit config-dict arg per documented precedence. Pre-existing failure listed in `docs/audits/known-pre-existing-failures.md`.

**Implementation:**
- Add `monkeypatch.delenv("FINNHUB_PLAN", raising=False)` to the test setup (1-line fix at function entry).
- Update `docs/audits/known-pre-existing-failures.md` — move the entry from "Currently failing" to "Recently cleared" with this PR's reference.

**LOC budget:** ~2 LOC.

### Item 5 — Decision 27 footnote follow-up (filings_sentiment `action='ignore'`)

**Source:** PR #1083 review. The `filings_sentiment_collector.py` upsert uses `action='ignore'` which silently drops Finnhub sentiment-model revisions for existing `(ticker, filing_type, filed_at)` rows. The Decision 27 footnote was added inline in the collector docstring, but no operational mechanism for revision detection exists.

**Implementation:**
- Add a structural test `tests/data_collection/test_filings_sentiment_revision_semantics.py` that documents the current behavior: write row, attempt to upsert with different score → second row silently dropped. Test PASSES (locks the current behavior as intentional).
- If/when operator decides to switch to `action='replace'`, the test inverts and the migration is `_REPLACE_SEMANTICS` registration in `src/utils/db.py`.

**LOC budget:** ~30 LOC (mostly test).

### Item 6 — Topological FK ordering for migration scripts

**Source:** PR #1067 review. `scripts/sqlite_to_pg_migrate.py` and `scripts/render_to_local_migrate.py` fire `INSERT`s in arbitrary table order. Works today because schema is FK-acyclic, but breaks under future FK cycles.

**Implementation:**
- Create `scripts/_shared_migration_utils.py::topo_sort_tables(tables, fks) -> list[str]` returning FK-respecting insert order. Uses `graphlib.TopologicalSorter` (Python 3.9+ stdlib).
- Both migration scripts replace their hardcoded table list with `topo_sort_tables(TABLES, fks_from_registry)`.
- Tests: 2 new tests — topo sort returns valid order + raises CycleError on FK cycles.

**LOC budget:** ~50 LOC.

### Item 7 — Extract `_redact_password` + `_confirm` to `_shared_migration_utils.py`

**Source:** PR #1067 review. Both `sqlite_to_pg_migrate.py` and `render_to_local_migrate.py` duplicate `_redact_password()` and `_confirm()` helpers.

**Implementation:**
- Same file as Item 6 (`scripts/_shared_migration_utils.py`) gains `redact_password()` and `confirm()` public helpers.
- Both migration scripts replace local definitions with imports.
- Tests: 2 new tests covering edge cases (empty password, YES vs YES-typed-as-no input).

**LOC budget:** ~25 LOC new + ~40 LOC removed (net -15 LOC).

**Item 6 + 7 share the same new file** (`scripts/_shared_migration_utils.py`). They land together in a single dev agent dispatch for coherence.

## Cross-Item Dependencies

| From → To | Reason |
|-----------|--------|
| Item 2 → Item 1 | If Item 1 (path a) wants to use the shared `get_finnhub_key` helper, Item 2 must land first. Order them within the PR: 2 → 1. |
| Item 6 + 7 → standalone | Items 6 + 7 share `_shared_migration_utils.py`. Land together. |
| All 7 items → Wave B (walk-forward) | Per operator decision, Wave A lands FIRST so Wave B inherits clean foundations. |

**Within the bundled PR**, commit order: 2 (Finnhub helper extraction) → 1 (price_target matrix) → 3 (PE threshold settings) → 4 (env-pollution test fix) → 5 (Decision 27 lock test) → 6+7 (migration utils extraction). The PR squash-merges as a single commit; intra-PR ordering matters only for the dev agent's mental model.

## Acceptance Criteria

- All 7 items land in a single PR.
- Test count net delta: +9 tests minimum (1 from Item 1, 1 from Item 2, 2 from Item 3, 0 from Item 4, 1 from Item 5, 2 from Item 6, 2 from Item 7).
- Test floor post-merge: ≥ 5309 (5300 + 9 net adds).
- `test_finnhub_plan_runtime_coverage.py::test_reverse_every_plan_supports_call_references_matrix_feature` passes WITHOUT `price_target` in `_REVERSE_INVARIANT_ALLOWLIST` (Item 1).
- `tests/data_collection/test_finnhub_shared.py` passes (Item 2).
- `tests/data_enrichment/test_financials.py::test_quality_flag_respects_custom_thresholds` passes (Item 3).
- `tests/test_enrichment.py::TestFinnhubPlan::test_feature_matrix_distinguishes_free_and_premium` passes on operator's local machine (Item 4).
- `known-pre-existing-failures.md` moves the Item 4 entry to "Recently cleared".
- `scripts/_shared_migration_utils.py` exists with `topo_sort_tables`, `redact_password`, `confirm` exports (Items 6+7).
- Both migration scripts import from `_shared_migration_utils.py` (no local duplicates remain).

## Out of Scope (Wave A)

Per operator decision and v0.36.0 framing:

- Walk-forward framework wiring (lives in Wave B — see `2026-05-13-sprint-6-walkforward-impl-design.md`).
- Other roadmap-deferred items: #97 (`alpaca_adapter.py` split), #105 (KPI caching), #106 (strategy_id filter pushdown), #107 (`initially_deferred=True` honor), #112 (row-count drift investigation), #114 (PG dedup).
- Any change to `_FEATURE_MATRIX['free']` (Item 1 only touches `'fundamental-1'`).
- Migration script behavior beyond ordering + helper extraction (no new safety gates, no new dry-run modes).

## Falsifiability Triggers

If Wave A wires correctly:

1. **Item 1 verification:** `python -c "from src.data_enrichment.finnhub_plan import _FEATURE_MATRIX; assert 'price_target' in _FEATURE_MATRIX['fundamental-1']"` exits 0.
2. **Item 2 verification:** `grep -c "def _get_finnhub_key" src/data_collection/*.py` returns 0 post-merge (all collectors import from `_finnhub_shared`).
3. **Item 6 verification:** running `python scripts/sqlite_to_pg_migrate.py --dry-run` emits the topologically-sorted table order to stdout (verify the order respects FK dependencies — e.g., `shadow_trades` comes after `strategy_registry`).
4. **Item 7 verification:** `grep -c "def _confirm\|def _redact_password" scripts/sqlite_to_pg_migrate.py scripts/render_to_local_migrate.py` returns 0 (both scripts import from shared utils).

If any of these fail post-merge: open `#SP6-wave-a-incomplete` tracker + revert PR.

## File Inventory (Wave A)

| File | Status | Reason |
|------|--------|--------|
| `src/data_collection/_finnhub_shared.py` | NEW | Item 2 — shared `get_finnhub_key` helper |
| `src/data_enrichment/finnhub_plan.py` | MODIFIED | Item 1 — add `price_target` to matrix |
| `src/data_collection/institutional_ownership_collector.py` | MODIFIED | Item 2 — drop local helper, import shared |
| `src/data_collection/filings_sentiment_collector.py` | MODIFIED | Item 2 |
| `src/data_collection/press_releases_collector.py` | MODIFIED | Item 2 |
| `src/data_collection/insider_collector.py` | MODIFIED | Item 2 |
| `src/data_collection/short_interest_collector.py` | MODIFIED | Item 2 |
| `src/data_collection/analyst_collector.py` | MODIFIED | Item 2 |
| `src/data_enrichment/financials.py` | MODIFIED | Item 3 — PE thresholds from settings |
| `config/settings.example.yaml` | MODIFIED | Item 3 — new `fundamental_quality_thresholds` block |
| `tests/test_enrichment.py` | MODIFIED | Item 4 — monkeypatch.delenv fix |
| `tests/test_finnhub_plan_runtime_coverage.py` | MODIFIED | Item 1 — remove price_target from allowlist |
| `tests/data_collection/test_finnhub_shared.py` | NEW | Item 2 tests |
| `tests/data_collection/test_filings_sentiment_revision_semantics.py` | NEW | Item 5 lock test |
| `tests/data_enrichment/test_financials.py` | MODIFIED | Item 3 — threshold tests |
| `scripts/_shared_migration_utils.py` | NEW | Items 6+7 — topo_sort + redact_password + confirm |
| `scripts/sqlite_to_pg_migrate.py` | MODIFIED | Items 6+7 — import shared utils |
| `scripts/render_to_local_migrate.py` | MODIFIED | Items 6+7 — import shared utils |
| `tests/scripts/test_shared_migration_utils.py` | NEW | Items 6+7 tests |
| `docs/audits/known-pre-existing-failures.md` | MODIFIED | Item 4 — move to cleared section |
| `CHANGELOG.md` | MODIFIED | Wave A entry under `## [Unreleased]` |

**Total: 21 files touched (3 NEW + 18 MODIFIED).** Net LOC delta estimated -5 (additions roughly balance removals — refactoring).

## Testing Strategy

- All new tests run hermetically (no live DB, no external APIs).
- Item 4's test must run cleanly with FINNHUB_PLAN set in env (operator's normal local state).
- Item 6's topo-sort tests use a synthetic 3-table FK graph (not the real 70-table registry — too slow).
- Item 7's tests cover edge cases (empty password handling, multi-character YES variants).
- Sibling tests for existing collectors after Item 2 extraction: verify they still pass via `pytest tests/data_collection/ -q`.
- AST scanner test from T26 (`test_finnhub_plan_runtime_coverage`) must pass post-Item-1 with the allowlist trimmed.

## Operational Notes

**Operator override paths (post-Wave A):**

- Item 1 — set `FINNHUB_PLAN=free` in env to disable price-target collection (gate now returns False on free tier).
- Item 3 — set `data_enrichment.fundamental_quality_thresholds.pe_max: <value>` in `config/settings.local.yaml` to tune.

**Provenance:** Wave A PR description references each of the 7 items by source PR (#1067, #1082, #1083, #1084, #1085) so future maintainers can trace each line of the diff back to its originating review.

## Design Decisions

| ID | Decision | Rationale | Source |
|----|----------|-----------|--------|
| SP6-CA-001 | Bundle 7 items into 1 PR | Operator decision (packaging Q1). Each item is independently small (~5-30 LOC); coordination overhead of 7 separate PRs exceeds the diff-coherence cost of bundling. | operator-interview |
| SP6-CA-002 | Wave A lands BEFORE Wave B | Items 2 + 6 + 7 introduce new shared modules that Wave B walk-forward implementation will reference. Landing the refactors first prevents race conditions. | operator-interview |
| SP6-CA-003 | Item 1 defaults to "add to matrix" | Operator already pays for Finnhub fundamental-1 tier which provides `/stock/price-target`. Adding to matrix unlocks the endpoint with zero new code; the alternative (remove dead code) discards capability the operator already paid for. | technical-default |
| SP6-CA-004 | Item 2 scope expanded from 3× to 6× | Sibling-search per `feedback_review_sibling_search` rule revealed 6 sites with byte-identical `_get_finnhub_key`. Ship the broader scope to close the class completely. | sibling-search-rule |
| SP6-CA-005 | Item 5 ships a LOCK test, not a behavior change | The Decision 27 footnote was added in PR #1083 documentation only. Until operator confirms a real production case of sentiment-revision drift, lock the current behavior with a structural test. Behavior change is post-Sprint-6. | conservative-default |

## Known Considerations (non-blocking)

- **Item 5's value is documentary, not corrective.** If operator never sees Finnhub model revisions in production, Item 5 is dead code. Worth tracking via the test's run-history — if it never fires (post-merge), it can be deleted in a future cleanup.
- **Item 2 may surface latent bugs in collectors.** Replacing 6 identical helpers with a shared import could surface a bug if any of them had a subtle non-byte-identical difference. Sibling-search confirmed byte-identical, but verify with a sweep test post-extraction.
- **Item 6's topo sort uses stdlib.** No new dependency. `graphlib.TopologicalSorter` is Python 3.9+ stdlib (codebase is on 3.12).
- **Wave A does not bump version.** v0.36.0 bumps at Wave B Sprint 6 close PR (mirrors Sprint 5's T16 pattern). Wave A's CHANGELOG entries accumulate in `[Unreleased]` and Wave B's close PR aggregates them.
