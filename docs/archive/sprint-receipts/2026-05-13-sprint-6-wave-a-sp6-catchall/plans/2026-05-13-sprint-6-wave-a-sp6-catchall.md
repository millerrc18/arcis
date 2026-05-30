# Sprint 6 Wave A — SP6 Catch-All Sweep Implementation Plan

## Companion spec

[Wave A design spec](../specs/2026-05-13-sprint-6-wave-a-sp6-catchall-design.md)

## Sentinel decision

Wave A is **single-PR**. All 7 items land in one commit (post-squash). No feature flags; no opt-in toggles; no per-item rollback. If any item produces a regression, revert the whole PR (`git revert <wave-a-sha>` is a single command).

## Execution order

Single dev agent. Intra-PR commit sequence (the agent commits incrementally for traceability; the PR squash-merges them):

1. Item 2 — `_get_finnhub_key` extraction (foundation for Item 1's optional adoption)
2. Item 1 — `price_target` to matrix (depends on Item 2 if path-(a) refactors call site)
3. Item 3 — PE settings hook
4. Item 4 — env-pollution test fix
5. Item 5 — Decision 27 lock test
6. Items 6 + 7 — migration utils extraction (`_shared_migration_utils.py` written once with both helpers)

## Tasks

### Wave A — Single dev agent dispatch via `/arcis:code` with `--files` scope fence

```json
{
  "tasks": [
    {
      "id": "WA1",
      "description": "Extract _get_finnhub_key from 6 collectors into src/data_collection/_finnhub_shared.py. Module docstring follows codebase convention (Called by / Calls / Owns tables / Config keys / Tests). All 6 collectors import `get_finnhub_key` and drop the local definition.",
      "files_in_scope": [
        "src/data_collection/_finnhub_shared.py",
        "src/data_collection/institutional_ownership_collector.py",
        "src/data_collection/filings_sentiment_collector.py",
        "src/data_collection/press_releases_collector.py",
        "src/data_collection/insider_collector.py",
        "src/data_collection/short_interest_collector.py",
        "src/data_collection/analyst_collector.py",
        "tests/data_collection/test_finnhub_shared.py"
      ],
      "files_read_only": [],
      "scope_fence": "Extract ONLY the _get_finnhub_key helper. Do NOT refactor other parts of the collectors. Do NOT change the function signature or env-vs-YAML precedence semantics. Each collector loses its 12-line _get_finnhub_key definition and gains one `from src.data_collection._finnhub_shared import get_finnhub_key` import. Verify byte-identical behavior across all 6 collectors before commit.",
      "test_strategy": "+1 test in tests/data_collection/test_finnhub_shared.py covering: (a) env-key takes precedence over config-key, (b) YAML fallback when env unset, (c) None when neither set. Sibling check: `pytest tests/data_collection/ -q` must show all existing collector tests still pass.",
      "dependencies": []
    },
    {
      "id": "WA2",
      "description": "Add 'price_target' to _FEATURE_MATRIX['fundamental-1'] in src/data_enrichment/finnhub_plan.py. Remove 'price_target' from _REVERSE_INVARIANT_ALLOWLIST in tests/test_finnhub_plan_runtime_coverage.py.",
      "files_in_scope": [
        "src/data_enrichment/finnhub_plan.py",
        "tests/test_finnhub_plan_runtime_coverage.py"
      ],
      "files_read_only": [
        "src/data_collection/analyst_collector.py"
      ],
      "scope_fence": "ONLY touch _FEATURE_MATRIX['fundamental-1'] (add 'price_target') and the test allowlist (remove 'price_target'). Do NOT touch the analyst_collector call site at :146-165 — its behavior automatically activates once the matrix is populated. Verify the T26 AST scanner (test_reverse_every_plan_supports_call_references_matrix_feature) passes without the allowlist entry.",
      "test_strategy": "+1 unit test: assert `finnhub_plan_supports('price_target', {'data_enrichment': {'finnhub_plan': 'fundamental-1'}}) == True`. Existing T26 AST scanner test passes WITHOUT 'price_target' in allowlist.",
      "dependencies": ["WA1"]
    },
    {
      "id": "WA3",
      "description": "Add PE quality threshold settings hook. config/settings.example.yaml gains a `data_enrichment.fundamental_quality_thresholds: { pe_min: 2.0, pe_max: 200.0 }` block. src/data_enrichment/financials.py::_derive_quality_flag() reads from config (with hardcoded fallback for backward-compat).",
      "files_in_scope": [
        "src/data_enrichment/financials.py",
        "config/settings.example.yaml",
        "tests/data_enrichment/test_financials.py"
      ],
      "files_read_only": [
        "src/config/__init__.py"
      ],
      "scope_fence": "ONLY change _derive_quality_flag's threshold source from module constants to config-with-fallback. Do NOT change the quality-flag semantics ('ok' / 'low' / None). Do NOT remove the module-level _PE_REASONABLE_LO/HI constants — they remain as fallback defaults.",
      "test_strategy": "+2 tests: (a) test_quality_flag_respects_custom_thresholds — set settings to pe_min=5.0, pe_max=50.0; verify a stock with PE=3.0 returns 'low'. (b) test_quality_flag_falls_back_when_config_missing — pass config=None; verify default 2.0/200.0 bounds apply.",
      "dependencies": []
    },
    {
      "id": "WA4",
      "description": "Fix env-pollution failure in tests/test_enrichment.py::TestFinnhubPlan::test_feature_matrix_distinguishes_free_and_premium by adding `monkeypatch.delenv('FINNHUB_PLAN', raising=False)` at test entry. Move the entry in docs/audits/known-pre-existing-failures.md from 'Currently failing' to 'Recently cleared'.",
      "files_in_scope": [
        "tests/test_enrichment.py",
        "docs/audits/known-pre-existing-failures.md"
      ],
      "files_read_only": [
        "src/data_enrichment/finnhub_plan.py"
      ],
      "scope_fence": "ONLY modify the single test function + the pre-existing-failures doc. Do NOT change get_finnhub_plan precedence semantics — the env-over-config behavior is documented intent.",
      "test_strategy": "Test passes WITH FINNHUB_PLAN=fundamental-1 set in env (operator's normal local state). Verify by running `FINNHUB_PLAN=fundamental-1 python -m pytest tests/test_enrichment.py::TestFinnhubPlan::test_feature_matrix_distinguishes_free_and_premium -v`.",
      "dependencies": []
    },
    {
      "id": "WA5",
      "description": "Add tests/data_collection/test_filings_sentiment_revision_semantics.py — structural lock test documenting that the current action='ignore' upsert silently drops Finnhub sentiment-model revisions. Test PASSES (lock the current behavior as intentional; flips when operator switches to action='replace').",
      "files_in_scope": [
        "tests/data_collection/test_filings_sentiment_revision_semantics.py"
      ],
      "files_read_only": [
        "src/data_collection/filings_sentiment_collector.py",
        "src/utils/db.py"
      ],
      "scope_fence": "ONLY add the new test file. Do NOT change collector behavior. Do NOT modify _REPLACE_SEMANTICS in src/utils/db.py — that's the future migration path, not Wave A scope.",
      "test_strategy": "+1 test: write a filings_sentiment row → attempt to upsert same (ticker, filing_type, filed_at) with different sentiment_score → fetch the row → verify ORIGINAL score persists (revision silently dropped). Test ASSERTS the silent-drop behavior so any future _REPLACE_SEMANTICS switch fails this test loudly, forcing operator review.",
      "dependencies": []
    },
    {
      "id": "WA6",
      "description": "Create scripts/_shared_migration_utils.py with topo_sort_tables, redact_password, confirm helpers. Both migration scripts (sqlite_to_pg_migrate.py + render_to_local_migrate.py) import from the shared module and drop local definitions. topo_sort_tables uses graphlib.TopologicalSorter (Python 3.9+ stdlib).",
      "files_in_scope": [
        "scripts/_shared_migration_utils.py",
        "scripts/sqlite_to_pg_migrate.py",
        "scripts/render_to_local_migrate.py",
        "tests/scripts/test_shared_migration_utils.py"
      ],
      "files_read_only": [
        "src/schema/registry.py"
      ],
      "scope_fence": "(a) Extract _redact_password, _confirm, AND topo_sort_tables into the new shared module. (b) Both migration scripts import the shared helpers. (c) topo_sort_tables consumes (table_names, fk_pairs) where fk_pairs is [(child_table, parent_table), ...]; uses graphlib.TopologicalSorter; raises graphlib.CycleError on cycles. (d) BOTH migration scripts replace their hardcoded table order with `topo_sort_tables(...)` output. Do NOT change migration safety semantics (dry-run, YES-prompt, connect_timeout). Do NOT modify the schema registry.",
      "test_strategy": "+2 tests in tests/scripts/test_shared_migration_utils.py: (a) test_topo_sort_returns_fk_respecting_order — synthetic 3-table FK graph; assert child appears after parent. (b) test_topo_sort_raises_on_cycle — synthetic cyclic FK; assert CycleError. +2 tests for redact_password + confirm covering empty input + YES vs YES-typed-as-no.",
      "dependencies": []
    },
    {
      "id": "WA7",
      "description": "Update CHANGELOG.md under [Unreleased] with a single 'Sprint 6 Wave A — SP6 catch-all sweep' entry listing all 7 items as sub-bullets. Each sub-bullet references the originating Sprint 5 PR review (#1067, #1082, #1083, #1084, #1085) for traceability.",
      "files_in_scope": [
        "CHANGELOG.md"
      ],
      "files_read_only": [
        "docs/audits/2026-05-13-sprint-6-wave-a-sp6-catchall/specs/2026-05-13-sprint-6-wave-a-sp6-catchall-design.md"
      ],
      "scope_fence": "ONLY append to [Unreleased] section. Format follows existing CHANGELOG conventions. Do NOT bump src/version.py (v0.36.0 bumps at Wave B Sprint 6 close PR — Wave A is intermediate).",
      "test_strategy": "No new tests for CHANGELOG. Spot-check formatting via `grep -A 20 '## \\[Unreleased\\]' CHANGELOG.md`. Verify sub-bullets cite source PRs.",
      "dependencies": ["WA1", "WA2", "WA3", "WA4", "WA5", "WA6"]
    }
  ],
  "execution_order": [
    {"batch": 1, "tasks": ["WA1", "WA3", "WA4", "WA5", "WA6"], "parallel": true, "rationale": "WA1/WA3/WA4/WA5/WA6 touch disjoint files. Parallel-safe. WA2 depends on WA1 — runs in batch 2."},
    {"batch": 2, "tasks": ["WA2"], "parallel": false, "rationale": "Depends on WA1 (Item 1 path-(a) verifies matrix is populated without breaking T26 AST scanner)."},
    {"batch": 3, "tasks": ["WA7"], "parallel": false, "rationale": "CHANGELOG aggregates after all code changes land. Runs last in the dev agent's commit sequence."}
  ],
  "notes": [
    "Wave A is a single dev agent dispatch via /arcis:code. The execution_order batches are intra-task commit sequencing for the agent, NOT separate PRs.",
    "Total file count: 21 (3 NEW + 18 MODIFIED).",
    "Total test count delta: +9 (1 from WA1, 1 from WA2, 2 from WA3, 0 from WA4 (test fix), 1 from WA5, 4 from WA6 — 2 topo + 1 redact + 1 confirm).",
    "Test floor post-merge target: >= 5309.",
    "LOC budget total: net approximately -50 lines (refactoring reduces duplication).",
    "Wave A lands BEFORE Wave B walk-forward (per operator decision 2026-05-13). After Wave A merges, dispatch Wave B via /arcis:code with the 2026-05-13-sprint-6-walkforward-impl spec + plan."
  ]
}
```

## Acceptance criteria (Wave A)

- Single PR opened against `main` titled `Sprint 6 Wave A — SP6 catch-all sweep (closes 7 PR-review follow-ups)`.
- All 7 items captured in the PR description with source-PR provenance.
- All 6 dev agent tasks (WA1-WA6) committed in 1 commit each (squash-merge consolidates).
- WA7 CHANGELOG update is the final commit.
- Tests: `python -m pytest tests/ -q --timeout=60` returns `>= 5309 passed`.
- AST scanner: `pytest tests/test_finnhub_plan_runtime_coverage.py -v` returns 6 passed (forward + reverse invariants + 4 self-tests).
- Operator-machine sanity check: `FINNHUB_PLAN=fundamental-1 python -m pytest tests/test_enrichment.py::TestFinnhubPlan::test_feature_matrix_distinguishes_free_and_premium -v` passes (Item 4 verification).
- No regressions in `tests/data_collection/` (Item 2 extraction safety check).

## Out of scope (Wave A)

Per the design spec. Highlights:

- Walk-forward framework wiring → Wave B (`2026-05-13-sprint-6-walkforward-impl`).
- `alpaca_adapter.py` split (#97) — separate post-Sprint-5 refactor.
- KPI caching (#105), strategy_id filter pushdown (#106), `initially_deferred=True` honor (#107), row-count drift (#112), PG content-dedup (#114) — all roadmap-deferred.
- Any new collector or new gate. Wave A is cleanup, not feature addition.
