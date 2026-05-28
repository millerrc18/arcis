# Phase 5 - Implementation Plan (Task Graph)

**Total tasks:** 40
**Generated:** 2026-05-27 (r3)
**Wave structure:** PR-A -> PR-B -> PR-C -> PR-D -> PR-E -> PR-F -> PR-G
**Total PRs:** 7 (target v0.36.72 -> v0.36.78)

## Execution Order

Each inner list is one wave; tasks within a wave dispatch in parallel.

```
  Wave  1: [100]
  Wave  2: [1]
  Wave  3: [2]
  Wave  4: [3]
  Wave  5: [4]
  Wave  6: [5]
  Wave  7: [6]
  Wave  8: [7]
  Wave  9: [8]
  Wave 10: [9]
  Wave 11: [10]
  Wave 12: [11]
  Wave 13: [12, 13]
  Wave 14: [14]
  Wave 15: [15, 16]
  Wave 16: [17]
  Wave 17: [18]
  Wave 18: [20]
  Wave 19: [21, 22, 23, 24]
  Wave 20: [25]
  Wave 21: [26]
  Wave 22: [19]
  Wave 23: [27]
  Wave 24: [28]
  Wave 25: [29]
  Wave 26: [30]
  Wave 27: [31]
  Wave 28: [32]
  Wave 29: [33, 34]
  Wave 30: [35]
  Wave 31: [36]
  Wave 32: [37]
  Wave 33: [38]
  Wave 34: [39]
```

## Plan Notes

40 tasks (added T0a as id=100 for PR-A standards refresh per DA5). Wave structure: PR-A (T100, T1-T3) → PR-B (T4-T9) → PR-C (T10-T17) → PR-D (T18, T20-T26, T19 LAST) → PR-E (T27-T30) → PR-F (T31-T36) → PR-G (T37-T39). KEY r3 CHANGES: (1) T19 _safe_run flip MOVED to LAST step of PR-D after T26 per DA1 — collectors migrate first (T18+T20+T21-T25) while _safe_run still treats return as bool (truthy); contract atomically completes when T19 lands as final commit. (2) T20-T25 file caps raised from 4 to 6-8 for paired collector+test updates per DD-41/DA2. (3) T13 mandates decorator-pattern (b) + tests/cli/test_cli_decorators_preserved.py subprocess sentinel per DD-40/DA7. (4) T28 emits DELETION_LIST receipt; T29 scope-fence requires receipt-line citations + pre-merge math check per DA8. (5) T17 prunes exactly 6 known_violations entries per DA11 (§7.3); shadow_executor + telegram REMAIN. (6) T100 (T0a) creates/refreshes docs/standards/boundary-touch-tests.md + PR template per DA5/DD-39. (7) All CHANGELOG edits use per-PR `<!-- PR-X entries -->` sentinel markers per DA3/DD-37; PR-F T33 unifies markers into `## [v0.36.78]` block. (8) PR-B revert is two-step per §3.4/DA6 — revert + sentinel-delete in same commit. (9) T15 scan_service uses sibling _scan_service_impl.py per DA9/KC-12. (10) PR-E deletion budget capped at (PR-D adds - 5) per DA10/KC-13. Parallelism: T12+T13 (PR-C C-ii), T15+T16 (PR-C C-iii), T21+T22+T23+T24 (PR-D D-ii 4-batch), T33+T34 (PR-F). All PR merges respect 21:30-22:30 ET embargo per memory; ~21 slots over 3 weeks vs 7 PRs = ~30% utilization adequate (DA12/KC-15).

---

## Tasks

### T100 - PR-A T0a standards doc + PR template refresh

**Complexity:** low

**Description:** Verify docs/standards/boundary-touch-tests.md exists and contains the §6.5 6-item checklist verbatim — if missing, ADD it. Add a Boundary-Touch Compliance block (referencing the 6-item checklist) to .github/PULL_REQUEST_TEMPLATE.md. This is the source-of-truth for DD-39 — all subsequent PRs (B/C/D/E/F/G) cite this checklist.

**Files in scope:**
- `docs/standards/boundary-touch-tests.md`
- `.github/PULL_REQUEST_TEMPLATE.md`

**Test strategy:** Grep `docs/standards/boundary-touch-tests.md` for the 6 numbered items — all must appear. Grep PR template for `Boundary-Touch` section header. Manual review of both files.

**Scope fence:** Do NOT modify any code files. Do NOT touch other standards docs. PR template additions are append-only — keep existing template content intact.

---

### T1 - PR-A debris purge + 2 new structure rules

**Complexity:** low
**Depends on:** T100

**Description:** Delete 17 `_*.py` REPL scratch files at repo root + `_582_operator_action.sql` + `--db-path` typo artifact + move `ai_research_desk.sqlite3` out of repo (operator-verifies size first). Add `test_no_underscore_scratch_at_repo_root` and `test_no_sqlite_at_repo_root` rules to tests/test_repo_structure.py. Update known_violations.json to remove these debris entries.

**Files in scope:**
- `tests/test_repo_structure.py`
- `config/known_violations.json`

**Files read-only:**
- `CLAUDE.md`

**Test strategy:** Run pytest tests/test_repo_structure.py -v; both new rules must PASS after debris removal. Run full pytest tests/ -q and verify count ≥ 5,467.

**Scope fence:** Do NOT touch src/ or scripts/. Do NOT touch docs/. Do NOT delete __init__.py or __main__.py. Do NOT delete check_trades.py at OUTER repo root. Do NOT skip operator-verify step on ai_research_desk.sqlite3 size.

---

### T2 - PR-A CHANGELOG.md entry (under <!-- PR-A entries --> marker)

**Complexity:** low
**Depends on:** T1

**Description:** Add CHANGELOG.md `[Unreleased]` entries under a new `<!-- PR-A entries -->` ... `<!-- /PR-A entries -->` marker block per §8.4. Inside: ### Removed enumeration of 19 debris artifacts; ### Added 2 new structure rules + boundary-touch standards-doc/PR-template refresh from T0a.

**Files in scope:**
- `CHANGELOG.md`

**Files read-only:**
- `tests/test_repo_structure.py`

**Test strategy:** Manual grep — CHANGELOG has `<!-- PR-A entries -->` and `<!-- /PR-A entries -->` markers wrapping the new Added/Removed subsections. No edits outside the marker block.

**Scope fence:** Do NOT add Changed or Fixed sections. Do NOT bump version. ALL new entries MUST be inside the `<!-- PR-A entries -->` marker block per DD-37.

---

### T3 - PR-A verification + structure-rule sentinel test

**Complexity:** low
**Depends on:** T1, T2

**Description:** Verify the 2 new structure rules behave correctly by re-introducing a temp `_test_scratch.py` (via test fixture using tmp_path) and confirming the rule FAILS. Then remove. Same fixture pattern for the sqlite rule.

**Files in scope:**
- `tests/test_repo_structure.py`

**Test strategy:** Test fixture creates+removes a scratch file inside the test; assertion uses tmp_path-anchored pattern, NOT a real repo write.

**Scope fence:** Do NOT actually write to the repo root in tests. Use tmp_path-style fixtures only.

---

### T4 - PR-B delete cloud_app.py + Render infra files

**Complexity:** medium
**Depends on:** T3

**Description:** Delete `src/api/cloud_app.py`, `render.yaml`, `requirements-cloud.txt`, `scripts/render_init_db.py`. Verify via grep that nothing imports cloud_app or references render.yaml.

**Files in scope:**
- `src/api/cloud_app.py`
- `render.yaml`
- `requirements-cloud.txt`
- `scripts/render_init_db.py`

**Files read-only:**
- `src/api/app.py`
- `docs/operations/render-decommission.md`

**Test strategy:** pytest tests/ -q baseline-equal. `grep -rn 'cloud_app' src/ tests/` → 0 hits. `nssm status ArcisDashboard` pre+post.

**Scope fence:** Do NOT delete cloud_routes/. Do NOT delete scripts/render_architecture_doc.py. Do NOT delete scripts/render_migrate.py. Do NOT touch src/api/app.py.

---

### T5 - PR-B delete scripts/render_to_local_migrate.py

**Complexity:** low
**Depends on:** T4

**Description:** Delete `scripts/render_to_local_migrate.py` (separated from T4 due to 4-file cap).

**Files in scope:**
- `scripts/render_to_local_migrate.py`

**Test strategy:** Grep `render_to_local_migrate` across repo — 0 hits expected.

**Scope fence:** Do NOT delete other render_*.py scripts. Do NOT touch render_migrate.py.

---

### T6 - PR-B strip DATABASE_URL branches from 4 cloud_routes files (batch 1)

**Complexity:** medium
**Depends on:** T5

**Description:** Remove `if database_url:` PG branches from platform.py (lines 55-63 per spec §3.1 reference), broker_exceptions.py, commands.py, kpis_compute.py. Update docstrings to remove Render rationale.

**Files in scope:**
- `src/api/cloud_routes/platform.py`
- `src/api/cloud_routes/broker_exceptions.py`
- `src/api/cloud_routes/commands.py`
- `src/api/cloud_routes/kpis_compute.py`

**Test strategy:** pytest tests/api/ -q baseline-equal. `grep -n 'DATABASE_URL' src/api/cloud_routes/{platform,broker_exceptions,commands,kpis_compute}.py` → 0 hits.

**Scope fence:** Do NOT touch notifications.py, preflight.py, walkforward.py, __init__.py — those are Task 7. Do NOT change function signatures or call sites.

---

### T7 - PR-B strip DATABASE_URL branches from 3 cloud_routes files (batch 2) + __init__ docstring

**Complexity:** medium
**Depends on:** T6

**Description:** Remove `if database_url:` PG branches from notifications.py, preflight.py, walkforward.py. Update __init__.py docstring.

**Files in scope:**
- `src/api/cloud_routes/notifications.py`
- `src/api/cloud_routes/preflight.py`
- `src/api/cloud_routes/walkforward.py`
- `src/api/cloud_routes/__init__.py`

**Test strategy:** pytest tests/api/ -q. Grep DATABASE_URL across all 7 modified cloud_routes files — 0 hits.

**Scope fence:** Do NOT delete __init__.py. Do NOT rename cloud_routes/ — that is deferred to Phase 6.

---

### T8 - PR-B add 2 sentinel tests at tests/ root

**Complexity:** low
**Depends on:** T7

**Description:** Create `tests/test_cloud_app_removed.py` (mirrors `tests/test_render_sync_removed.py` 44L canonical pattern) and `tests/test_no_database_url_branch.py`. Both at REPO-ROOT tests/ directory.

**Files in scope:**
- `tests/test_cloud_app_removed.py`
- `tests/test_no_database_url_branch.py`

**Files read-only:**
- `tests/test_render_sync_removed.py`
- `src/api/cloud_routes/platform.py`

**Test strategy:** Both sentinels MUST pass. Dry-run sabotage (`touch src/api/cloud_app.py` in scratch) → sentinel must fail. Remove. Same for DATABASE_URL sentinel.

**Scope fence:** Sentinels at tests/ root (NOT tests/sync/, NOT tests/api/). Use canonical tests/test_render_sync_removed.py 44L pattern. Do NOT add to known_violations.json.

---

### T9 - PR-B close-out: docs receipts + CHANGELOG (under <!-- PR-B entries --> marker)

**Complexity:** low
**Depends on:** T8

**Description:** Add Phase-4 receipt to docs/operations/render-decommission.md. Add CHANGELOG `[Unreleased]` entries under `<!-- PR-B entries -->` marker per §8.4: ### Removed enumeration of 5 deleted files + 7 stripped; ### Added 2 new sentinels. Document the two-step rollback protocol (§3.4) at end of render-decommission Phase-4 receipt.

**Files in scope:**
- `docs/operations/render-decommission.md`
- `CHANGELOG.md`

**Test strategy:** Manual review — Phase 4 receipt present + cites two-step rollback. CHANGELOG has `<!-- PR-B entries -->` block enumerating all 12 changed files.

**Scope fence:** Do NOT touch RELEASES.md (PR-F). Do NOT bump version. Do NOT rewrite render-decommission.md — append-only. All CHANGELOG additions MUST be inside the `<!-- PR-B entries -->` block.

---

### T10 - PR-C wave C-i: shadow_executor.py refactor

**Complexity:** high
**Depends on:** T9

**Description:** Split `src/shadow_trading/executor.py` (3093L) into `executor.py` (~1200L core) + `order_lifecycle.py` (~800L OrderLifecycle class) + `reconciliation_engine.py` (~600L ReconciliationEngine class). Zero behavior change. Public API preserved.

**Files in scope:**
- `src/shadow_trading/executor.py`
- `src/shadow_trading/order_lifecycle.py`
- `src/shadow_trading/reconciliation_engine.py`

**Files read-only:**
- `tests/shadow_trading/test_executor.py`

**Test strategy:** pytest tests/shadow_trading/ -q baseline-equal. NSSM smoke test ArcisWatchLoop + ArcisDashboard.

**Scope fence:** Do NOT change ANY public function signature. Do NOT touch tests/. Do NOT touch other shadow_trading files. Do NOT touch known_violations.json yet (wave C-iii cleanup).

---

### T11 - PR-C wave C-i: telegram.py refactor (delivery extraction)

**Complexity:** high
**Depends on:** T10

**Description:** Split `src/notifications/telegram.py` (1822L) by extracting DELIVERY helpers to NEW `src/notifications/telegram_delivery.py` (~500L). `src/notifications/telegram_commands.py` (854L) ALREADY EXISTS from a prior sprint — do NOT touch or recreate it.

**Files in scope:**
- `src/notifications/telegram.py`
- `src/notifications/telegram_delivery.py`

**Files read-only:**
- `src/notifications/telegram_commands.py`
- `tests/notifications/test_telegram.py`

**Test strategy:** pytest tests/notifications/ -q baseline-equal. `from src.notifications.telegram import send_telegram` still works. Confirm telegram_commands.py is unchanged via git diff.

**Scope fence:** Do NOT touch telegram_commands.py (already 854L). Do NOT rename any public function. Do NOT touch tests/.

---

### T12 - PR-C wave C-ii: trainer.py refactor

**Complexity:** medium
**Depends on:** T11

**Description:** Extract `TrainerCheckpoint` from `src/training/trainer.py` (1530L) to `src/training/trainer_checkpoint.py` (~400L). Trainer ~1130L.

**Files in scope:**
- `src/training/trainer.py`
- `src/training/trainer_checkpoint.py`

**Files read-only:**
- `tests/training/test_trainer.py`

**Test strategy:** pytest tests/training/ -q baseline-equal. TrainerCheckpoint import path consistent (re-exported from trainer.py for compat OR callers updated).

**Scope fence:** Do NOT touch trainer entrypoint signatures. Do NOT touch training_control.py. Do NOT update CLAUDE.md training references.

---

### T13 - PR-C wave C-ii: cli/commands.py split (decorator pattern (b) per DD-40)

**Complexity:** high
**Depends on:** T11

**Description:** Split `src/cli/commands.py` (1531L) by command category into `commands_data.py`, `commands_training.py`, `commands_ops.py` (~510L each). DECORATOR PRESERVATION PATTERN (b) per DD-40: sub-modules export DECORATED functions (with @prod_guard + @safety_window + audit-log applied); `commands.py` becomes a pure re-export module. ADD `tests/cli/test_cli_decorators_preserved.py` subprocess sentinel: for each command, `subprocess.run(['python', '-m', 'src.cli', '<cmd>', '--help'])`; assert audit_log table has a row for the invocation. This sentinel MUST EXIST and PASS in PR-C — not deferred.

**Files in scope:**
- `src/cli/commands.py`
- `src/cli/commands_data.py`
- `src/cli/commands_training.py`
- `src/cli/commands_ops.py`
- `tests/cli/test_cli_decorators_preserved.py`

**Files read-only:**
- `tests/cli/test_commands.py`

**Test strategy:** pytest tests/cli/ -q baseline-equal + new sentinel tests pass. `python -m src.cli --help` shows all commands. Sentinel verifies audit_log emission for each command via subprocess.

**Scope fence:** Do NOT add new CLI commands. Do NOT change argument-parser shape. Do NOT skip @prod_guard/@safety_window decorators. Do NOT use pattern (a) — pattern (b) ONLY per DD-40. Files cap raised to 5 for paired sentinel test (per DD-41 framework).

---

### T14 - PR-C wave C-iii: governor.py + system.py refactors (parallel-eligible pair)

**Complexity:** medium
**Depends on:** T12, T13

**Description:** (a) Extract `GovernorAudit` from `src/risk/governor.py` (970L) to `governor_audit.py` (~350L). (b) Extract status endpoints from `src/api/routes/system.py` (761L) to `routes/system_status.py` (~370L).

**Files in scope:**
- `src/risk/governor.py`
- `src/risk/governor_audit.py`
- `src/api/routes/system.py`
- `src/api/routes/system_status.py`

**Files read-only:**
- `tests/risk/test_governor.py`
- `tests/api/test_system_routes.py`

**Test strategy:** pytest tests/risk/ tests/api/ -q baseline-equal. Curl smoke /api/system/* endpoints still respond.

**Scope fence:** Do NOT touch unrelated risk/ or api/routes/ files. Do NOT change endpoint URLs.

---

### T15 - PR-C wave C-iii: scan_service.py refactor (sibling _impl per DA9)

**Complexity:** medium
**Depends on:** T14

**Description:** Extract run_scan's 401L inner function from `src/services/scan_service.py` (517L) into sibling `src/services/_scan_service_impl.py` with 3 phase helpers `_phase_collect`, `_phase_score`, `_phase_persist` (~120L each). Architect decision per KC-12/DA9: helpers live in sibling file (underscore-private convention), NOT inline. scan_service.py shrinks to ~280-340L.

**Files in scope:**
- `src/services/scan_service.py`
- `src/services/_scan_service_impl.py`

**Files read-only:**
- `tests/services/test_scan_service.py`

**Test strategy:** pytest tests/services/ -q baseline-equal. Smoke scan via CLI verifies 3 phases execute in order.

**Scope fence:** Do NOT touch scan-tools side (src/tools/scan_*.py). Do NOT change run_scan public signature. Helpers MUST go to _scan_service_impl.py — NOT inline (per DA9).

---

### T16 - PR-C wave C-iii: email_digest.py 3-module split

**Complexity:** high
**Depends on:** T14

**Description:** Split `src/notifications/email_digest.py` (1236L) into orchestrator `email_digest.py` (~380L) + NEW `email_digest_render.py` (~480L) + NEW `email_digest_handover.py` (~250L). Optional 4th: `email_digest_collect.py` (~280L) IF needed to keep orchestrator <400L. Public API preserved. If task budget overruns, defer 4th module to PR-C2 per DD-08c.

**Files in scope:**
- `src/notifications/email_digest.py`
- `src/notifications/email_digest_render.py`
- `src/notifications/email_digest_handover.py`
- `src/notifications/email_digest_collect.py`

**Files read-only:**
- `tests/notifications/test_email_digest.py`

**Test strategy:** pytest tests/notifications/ -q baseline-equal. `from src.notifications.email_digest import <public symbols>` unchanged.

**Scope fence:** Do NOT change any public function signature. Do NOT touch tests/. 4th module OPTIONAL — defer to PR-C2 if budget overruns. 3-module shape is MINIMUM.

---

### T17 - PR-C close-out: known_violations.json prune (exact 6) + CHANGELOG (<!-- PR-C entries -->)

**Complexity:** low
**Depends on:** T10, T11, T12, T13, T14, T15, T16

**Description:** Remove EXACTLY 6 entries from `config/known_violations.json` per §7.3/DA11: `scan_service.py`, `src/api/routes/system.py`, `governor.py`, `trainer.py`, `cli/commands.py`, `email_digest.py`. LEAVE `shadow_trading/executor.py` and `notifications/telegram.py` in the file (refactored but still >400L) with Phase-6 sub-target notes. Add CHANGELOG entries under `<!-- PR-C entries -->` marker.

**Files in scope:**
- `config/known_violations.json`
- `CHANGELOG.md`

**Test strategy:** pytest tests/test_repo_structure.py -v — no false-fails. known_violations.json contains exactly the kept-grandfathered entries + non-PR-C entries.

**Scope fence:** PRUNE EXACTLY 6 entries (enumerated above). LEAVE shadow_executor + telegram. Do NOT remove entries for KC-6 cloud_routes leftovers. Do NOT bump version. CHANGELOG entries MUST be inside `<!-- PR-C entries -->` marker.

---

### T18 - PR-D wave D-i: create CollectorResult dataclass

**Complexity:** medium
**Depends on:** T17

**Description:** Create NEW `src/data_collection/result.py` with frozen CollectorResult + classmethods (ok_from_count, partial, failed) + is_healthy property + aggregate_results helper (Shape F press_releases per-ticker lists).

**Files in scope:**
- `src/data_collection/result.py`
- `tests/data_collection/test_collector_result.py`

**Files read-only:**
- `src/data_collection/errors.py`

**Test strategy:** tests/data_collection/test_collector_result.py covers dataclass frozen-ness, 3 classmethods, is_healthy property, aggregate_results helper. ~+15 tests.

**Scope fence:** Do NOT add to errors.py — result.py is separate per DD-12. Do NOT modify collectors yet. Do NOT touch _safe_run.

---

### T20 - PR-D wave D-i: migrate 3 canonical collectors (macro/edgar/options)

**Complexity:** medium
**Depends on:** T18

**Description:** Migrate macro_collector, edgar_collector, options_collector to return CollectorResult. Update each collector's test file in same task. These 3 are the canonical examples for Wave D-ii agents to mirror. NOTE: _safe_run is NOT YET FLIPPED — it still treats return value as bool (truthy). The new CollectorResult is truthy so nothing breaks (DD-15 revised r3).

**Files in scope:**
- `src/data_collection/macro_collector.py`
- `src/data_collection/edgar_collector.py`
- `src/data_collection/options_collector.py`
- `tests/data_collection/test_macro_collector.py`
- `tests/data_collection/test_edgar_collector.py`
- `tests/data_collection/test_options_collector.py`

**Files read-only:**
- `src/data_collection/result.py`

**Test strategy:** Each migrated collector's tests update assertion shape (result['x'] → result.primary_count / result.metadata). Gold-standard: would test fail if collector body deleted? File cap raised to 6 for paired collector+test updates per DD-41.

**Scope fence:** Do NOT migrate other collectors here. Do NOT change collector public function names. Do NOT flip _safe_run yet (D-iii last step). File cap raised from 4 to 6 per DD-41.

---

### T21 - PR-D wave D-ii batch A: 4 collectors (edgar_historical, filings_sentiment, options_metrics, analyst) + tests

**Complexity:** medium
**Depends on:** T20

**Description:** Migrate these 4 collectors + their test files to CollectorResult. Note correct file names: `edgar_historical.py` (bare), `filings_sentiment_collector.py`, `options_metrics.py` (bare), `analyst_collector.py`. analyst preserves CollectorPartialFailureError raise (DD-14).

**Files in scope:**
- `src/data_collection/edgar_historical.py`
- `src/data_collection/filings_sentiment_collector.py`
- `src/data_collection/options_metrics.py`
- `src/data_collection/analyst_collector.py`
- `tests/data_collection/test_edgar_historical.py`
- `tests/data_collection/test_filings_sentiment_collector.py`
- `tests/data_collection/test_options_metrics.py`
- `tests/data_collection/test_analyst_collector.py`

**Files read-only:**
- `src/data_collection/result.py`
- `src/data_collection/macro_collector.py`

**Test strategy:** Per-collector pytest baseline-equal after test-assertion shape update. CollectorPartialFailureError still raised for analyst when err-rate >50%. File cap raised to 8 for paired collector+test updates per DD-41.

**Scope fence:** Do NOT delete CollectorPartialFailureError. Do NOT touch other collectors. Do NOT flip _safe_run. File cap raised from 4 to 8 per DD-41 — paired collector+test updates.

---

### T22 - PR-D wave D-ii batch B: 4 collectors (insider, fed, press_releases, cboe) + tests

**Complexity:** medium
**Depends on:** T20

**Description:** Migrate these 4 collectors + tests. press_releases uses aggregate_results helper for Shape F per-ticker lists. insider preserves CollectorPartialFailureError per DD-14.

**Files in scope:**
- `src/data_collection/insider_collector.py`
- `src/data_collection/fed_collector.py`
- `src/data_collection/press_releases_collector.py`
- `src/data_collection/cboe_collector.py`
- `tests/data_collection/test_insider_collector.py`
- `tests/data_collection/test_fed_collector.py`
- `tests/data_collection/test_press_releases_collector.py`
- `tests/data_collection/test_cboe_collector.py`

**Files read-only:**
- `src/data_collection/result.py`

**Test strategy:** Per-collector pytest baseline-equal. press_releases tests verify aggregate_results merges per-ticker lists correctly. File cap raised to 8 per DD-41.

**Scope fence:** Do NOT touch other collectors. Do NOT flip _safe_run. File cap raised from 4 to 8 per DD-41.

---

### T23 - PR-D wave D-ii batch C: 4 collectors (company_executive, docs, institutional_ownership, price_target) + tests

**Complexity:** medium
**Depends on:** T20

**Description:** Migrate these 4 collectors + tests. Each gets CollectorResult with primary_count reflecting natural unit (rows_stored or domain count).

**Files in scope:**
- `src/data_collection/company_executive_collector.py`
- `src/data_collection/docs_collector.py`
- `src/data_collection/institutional_ownership_collector.py`
- `src/data_collection/price_target_collector.py`
- `tests/data_collection/test_company_executive_collector.py`
- `tests/data_collection/test_docs_collector.py`
- `tests/data_collection/test_institutional_ownership_collector.py`
- `tests/data_collection/test_price_target_collector.py`

**Files read-only:**
- `src/data_collection/result.py`

**Test strategy:** Per-collector pytest baseline-equal. File cap raised to 8 per DD-41.

**Scope fence:** Do NOT touch research_synthesizer.py (consumer-side, out of scope). Do NOT flip _safe_run. File cap raised from 4 to 8 per DD-41.

---

### T24 - PR-D wave D-ii batch D: 4 collectors (research, retention, short_interest, short_volume_finra) + tests

**Complexity:** medium
**Depends on:** T20

**Description:** Migrate these 4 collectors + tests. Note bare-name files: `retention.py`, `short_volume_finra.py`. Other 2: `research_collector.py`, `short_interest_collector.py`.

**Files in scope:**
- `src/data_collection/research_collector.py`
- `src/data_collection/retention.py`
- `src/data_collection/short_interest_collector.py`
- `src/data_collection/short_volume_finra.py`
- `tests/data_collection/test_research_collector.py`
- `tests/data_collection/test_retention.py`
- `tests/data_collection/test_short_interest_collector.py`
- `tests/data_collection/test_short_volume_finra.py`

**Files read-only:**
- `src/data_collection/result.py`

**Test strategy:** Per-collector pytest baseline-equal. File cap raised to 8 per DD-41.

**Scope fence:** Do NOT touch research_synthesizer/research_sources/_finnhub_shared. Do NOT flip _safe_run. File cap raised from 4 to 8 per DD-41.

---

### T25 - PR-D wave D-ii batch E: 3 collectors (stock_financials, trends, vix) + tests

**Complexity:** medium
**Depends on:** T20

**Description:** Migrate the final 3 collectors + tests. After this task, all 22 collectors return CollectorResult — but _safe_run STILL returns bool (flip happens in T19 as final D-iii commit).

**Files in scope:**
- `src/data_collection/stock_financials_collector.py`
- `src/data_collection/trends_collector.py`
- `src/data_collection/vix_collector.py`
- `tests/data_collection/test_stock_financials_collector.py`
- `tests/data_collection/test_trends_collector.py`
- `tests/data_collection/test_vix_collector.py`

**Files read-only:**
- `src/data_collection/result.py`

**Test strategy:** Per-collector pytest baseline-equal. Full pytest tests/data_collection/ -q after task — equal to baseline + ~+21 net from new test files. File cap raised to 6 per DD-41.

**Scope fence:** Do NOT touch out-of-scope modules (_capability_health, capability_registration, _finnhub_shared, research_sources, research_synthesizer, errors, __init__). Do NOT flip _safe_run. File cap raised from 4 to 6 per DD-41.

---

### T26 - PR-D wave D-iii: CLAUDE.md §207 patch + CHANGELOG (<!-- PR-D entries -->)

**Complexity:** low
**Depends on:** T21, T22, T23, T24, T25

**Description:** Update CLAUDE.md Data Collection Rules §207 — change `_safe_run returns bool` to `_safe_run returns CollectorResult`; update done-flag example from `if self._safe_run(...): self._done = True` to `result = self._safe_run(...); if result.is_healthy: self._done = True`. Add CHANGELOG `<!-- PR-D entries -->` block enumerating contract change + 22-collector migration. Read MASTER.md §2; if it references `_safe_run returns bool` or specific collector dict shapes, update those lines. NOTE: This task runs BEFORE T19 (the _safe_run flip) — documenting the post-flip contract.

**Files in scope:**
- `CLAUDE.md`
- `CHANGELOG.md`
- `MASTER.md`

**Files read-only:**
- `src/scheduler/watch.py`
- `src/data_collection/result.py`

**Test strategy:** Manual review — CLAUDE.md §207 reflects new return type + example. CHANGELOG `<!-- PR-D entries -->` block enumerates contract change. MASTER.md §2 confirmed clean OR updated.

**Scope fence:** Do NOT rewrite CLAUDE.md beyond §207. Do NOT touch operator-guide.md or README.md (PR-F). Do NOT bump version. CHANGELOG inside `<!-- PR-D entries -->` marker.

---

### T19 - PR-D wave D-iii FINAL: flip _safe_run to return CollectorResult (LAST commit of PR-D per DA1)

**Complexity:** medium
**Depends on:** T26

**Description:** Modify `_safe_run` in `src/scheduler/watch.py:2442` to: (a) return CollectorResult instead of bool, (b) on Exception build CollectorResult.failed, (c) route status to _capability_health.set_status (ok → ok, partial → degraded, failed → down). Backward-compat: callers using `if result:` still work via is_healthy truthiness. THIS IS THE LAST COMMIT OF PR-D — by this point all 22 collectors already return CollectorResult (silently, since previous tasks did not flip _safe_run). This task completes the contract atomically and is the final piece per DD-15 (revised r3 / DA1).

**Files in scope:**
- `src/scheduler/watch.py`
- `tests/scheduler/test_safe_run_routes_to_capability_health.py`

**Files read-only:**
- `src/data_collection/result.py`
- `src/data_collection/_capability_health.py`

**Test strategy:** New tests/scheduler/test_safe_run_routes_to_capability_health.py with ~+6 tests covering ok/partial/failed routing. Existing watch.py tests baseline-equal. Full pytest tests/ -q passes with new contract.

**Scope fence:** Do NOT refactor watch.py beyond _safe_run. Do NOT touch other scheduler files. ALL 22 collectors MUST already return CollectorResult before this task runs (depends_on chain enforces). T19 is the LAST commit of PR-D per DA1.

---

### T27 - PR-E Pass A heuristic vacuous-test detection

**Complexity:** medium
**Depends on:** T19

**Description:** Run 4 architect-defined heuristic queries (mock-only assertions, @patch:assert_called ratio >3:1, full-SUT mocking, no-assertion tests) across tests/. Produce ranked candidate list. Sample top 50.

**Files in scope:**
- `docs/audits/2026-XX-XX-test-audit/pass-a-candidates.md`

**Files read-only:**
- `tests/`

**Test strategy:** Deterministic candidate list; ~50-100 candidates expected with highest-risk areas (scheduler/, data_collection/, tools/, safety/) ranked first.

**Scope fence:** Do NOT delete any tests in Pass A. Pass A produces a LIST only.

---

### T28 - PR-E Pass B empirical verification + DELETION_LIST receipt (per DD-38 / DA8)

**Complexity:** high
**Depends on:** T27

**Description:** For each top-50 Pass A candidate: apply Pass B methodology per DD-38 (unit / integration / fully-shimmed cases). Use SCRATCH worktree for impl deletions. OUTPUT: `docs/audits/2026-XX-XX-test-audit/pass-b-empirical.md` containing a `## DELETION_LIST` section. Each row carries `file:line: rationale` — T29 cites these. For integration tests where some surfaces are vacuous, document the surface in receipt with either (a) sibling boundary-touch test plan or (b) delete-flag.

**Files in scope:**
- `docs/audits/2026-XX-XX-test-audit/pass-b-empirical.md`

**Files read-only:**
- `tests/`

**Test strategy:** Per-candidate empirical receipt with rerun output. Confirmed-vacuous count expected: ~15-25 of 50. DELETION_LIST section is parseable: `file:line: rationale` format.

**Scope fence:** Use SCRATCH worktree for impl-deletion experiments. Do NOT push impl-deletion to main. Pass B is investigative only — no test deletions yet. Receipt MUST contain DELETION_LIST section in canonical format (per DA8).

---

### T29 - PR-E execute deletions + boundary-touch additions (Pass-B-receipt-cited per DA8)

**Complexity:** high
**Depends on:** T28

**Description:** For each test confirmed vacuous via DD-18 AND-conjoined criteria: delete with PR-description rationale CITING the Pass-B receipt line. Add ~15 boundary-touch tests covering 6-seam matrix per §6.2. PR-E deletion budget capped at (PR-D additions - 5) = ~15 per DA10.

**Files in scope:**
- `tests/llm/test_ollama_shutdown_boundary.py`
- `tests/scheduler/test_healthprobe_nssm_filenames.py`
- `tests/api/test_cloud_routes_db_seam.py`
- `tests/safety/test_safe_op_http_boundary.py`

**Files read-only:**
- `docs/audits/2026-XX-XX-test-audit/pass-b-empirical.md`

**Test strategy:** pytest tests/ -q count remains ≥ 5,467 (floor held). Per-deletion: PR description cites Pass-B-receipt line (file:line). Per-addition: 6-item checklist + would-fail-if-impl-deleted. PRE-MERGE MATH CHECK: `pytest tests/ --collect-only | wc -l` must equal baseline + (additions - declared_deletions) exactly. If math fails, PR is rejected (per DA8).

**Scope fence:** Do NOT delete tests outside the Pass-B receipt DELETION_LIST. Each deletion in the PR diff MUST be traceable to a Pass-B-receipt line — reviewer rejects untraceable deletions. Do NOT exceed PR-E deletion budget (PR-D additions - 5; per DA10). Do NOT lower floors in pg-tests.yml or CLAUDE.md (DD-20).

---

### T30 - PR-E close-out: audit receipt + CHANGELOG (<!-- PR-E entries -->)

**Complexity:** low
**Depends on:** T29

**Description:** Finalize `docs/audits/2026-XX-XX-test-audit/` receipt (overview + Pass-A + Pass-B DELETION_LIST + deletion-rationale matrix + additions matrix). Add CHANGELOG entries under `<!-- PR-E entries -->` marker.

**Files in scope:**
- `docs/audits/2026-XX-XX-test-audit/README.md`
- `CHANGELOG.md`

**Test strategy:** Manual review of receipt completeness. CHANGELOG inside `<!-- PR-E entries -->` marker.

**Scope fence:** Do NOT move receipt to docs/archive/ yet (current sprint; PR-F archive sweep handles). Do NOT bump version. CHANGELOG inside `<!-- PR-E entries -->` marker.

---

### T31 - PR-F README.md full rewrite

**Complexity:** medium
**Depends on:** T30

**Description:** Rewrite README.md from ~120 to ~200 lines: authoritative SQLite-only floor (5,467); remove Phase-1-Honest-Baseline; add Quick Start (operator) + Repo Layout; link to MASTER/CLAUDE/RELEASES/operator-guide.

**Files in scope:**
- `README.md`

**Files read-only:**
- `MASTER.md`
- `CLAUDE.md`
- `RELEASES.md`

**Test strategy:** Manual review. Test-count claim matches pg-tests.yml (PG) + CLAUDE.md (SQLite).

**Scope fence:** Do NOT duplicate CLAUDE.md content (local dev there). Do NOT add contributor onboarding (operator-only per OQ-3 recommendation).

---

### T32 - PR-F MASTER.md §2 rolling-window + DIRECTORY regen

**Complexity:** medium
**Depends on:** T31

**Description:** Implement DD-24 rolling 3-sprint window in MASTER.md §2. Run `scripts/generate_directory.py` — fix if broken. Regen DIRECTORY.md from scratch.

**Files in scope:**
- `MASTER.md`
- `DIRECTORY.md`
- `scripts/generate_directory.py`

**Test strategy:** Manual review of MASTER §2. DIRECTORY.md regen succeeds.

**Scope fence:** Do NOT touch MASTER §1 (immutable). Do NOT delete archived sprint receipts — T34 handles.

---

### T33 - PR-F CLAUDE.md delta sweep + CHANGELOG/RELEASES de-overlap + marker unification

**Complexity:** low
**Depends on:** T32

**Description:** CLAUDE.md delta patches only (DD-27): test-floor line at :15, 1-line entry for 2 new structure rules from PR-A, T0a standards-doc note. Re-verify §207 contract (set in T26). Add cross-link header to CHANGELOG.md and RELEASES.md (DD-25). UNIFY per-PR sentinel markers in CHANGELOG.md into a versioned `## [v0.36.78]` block + REMOVE the `<!-- PR-X entries -->` markers (per §8.4 / DD-37 cleanup step).

**Files in scope:**
- `CLAUDE.md`
- `CHANGELOG.md`
- `RELEASES.md`

**Test strategy:** Manual review. Cross-link headers at top of both CHANGELOG and RELEASES. CHANGELOG `<!-- PR-X entries -->` markers all removed; content unified under `## [v0.36.78]`.

**Scope fence:** Do NOT rewrite CLAUDE.md beyond delta patches (fresh through #111 per deep-analysis). Do NOT merge CHANGELOG + RELEASES — keep separate per DD-25.

---

### T34 - PR-F docs/audits archive sweep (git mv preserves history)

**Complexity:** medium
**Depends on:** T32

**Description:** Move audit subdirs older than 2026-05-21 from `docs/audits/` to `docs/archive/sprint-receipts/` via `git mv`. Visual-verify .png hierarchies (11-13 per before/after) move WITH parent receipt — binary identity (DD-31). ~30 of ~40 move.

**Files in scope:**
- `docs/archive/sprint-receipts/`
- `docs/audits/`

**Test strategy:** `git log --follow` on moved file shows full history. .png binaries unchanged via sha256.

**Scope fence:** MOVES ONLY — do not delete (DD-23). Do not transcode .png. Do not flatten subdir structure.

---

### T35 - PR-F operations + standards header sweep

**Complexity:** low
**Depends on:** T34

**Description:** Close out `docs/operations/render-decommission.md` Phase-4 receipt (additive to T9). Verify every doc in `docs/standards/` and `docs/runbooks/` has a header section.

**Files in scope:**
- `docs/operations/render-decommission.md`
- `docs/standards/`
- `docs/runbooks/`

**Test strategy:** Header-section sentinel (T36) checks each .md in standards/ + runbooks/ has H1 + immediate description paragraph.

**Scope fence:** Do NOT rewrite existing standards docs. Append-only.

---

### T36 - PR-F sentinels (DIRECTORY staleness + docs headers)

**Complexity:** low
**Depends on:** T35

**Description:** Add 2 new sentinel tests in tests/test_repo_structure.py: (a) DIRECTORY.md mtime within N sprints of HEAD commit date (sprint-staleness alert); (b) every doc in docs/standards/ and docs/runbooks/ has a header section.

**Files in scope:**
- `tests/test_repo_structure.py`

**Files read-only:**
- `DIRECTORY.md`
- `docs/standards/`
- `docs/runbooks/`

**Test strategy:** Both sentinels MUST pass. Dry-run sabotage in fixture MUST trigger failure.

**Scope fence:** Sentinels non-grandfathered — do NOT add to known_violations.json. Use tmp_path-style fixtures for negative checks.

---

### T37 - PR-G phase-5 final sentinel tests

**Complexity:** low
**Depends on:** T36

**Description:** Add 3 sentinel tests for phase-5 close-out: (a) known_violations.json freshness — no entry refers to a file currently <400L; (b) docs/audits/ archive policy — no subdir older than 3 sprints remains at top level; (c) CollectorResult contract — _safe_run signature returns CollectorResult.

**Files in scope:**
- `tests/test_repo_structure.py`
- `tests/scheduler/test_safe_run_contract.py`

**Files read-only:**
- `config/known_violations.json`
- `src/scheduler/watch.py`

**Test strategy:** All 3 sentinels MUST pass. Negative dry-runs verify each fails when its constraint is violated in tmp_path.

**Scope fence:** Sentinels non-grandfathered. Do NOT add to known_violations.json.

---

### T38 - PR-G known_violations.json final prune + CHANGELOG (<!-- PR-G entries -->)

**Complexity:** low
**Depends on:** T37

**Description:** Final prune: remove entries for files that fell under 400L through any phase-5 PR. Add CHANGELOG `<!-- PR-G entries -->` block summarizing total phase-5 reductions.

**Files in scope:**
- `config/known_violations.json`
- `CHANGELOG.md`

**Test strategy:** pytest tests/test_repo_structure.py -v — T37 sentinel must PASS post-prune.

**Scope fence:** Do NOT remove entries for KC-6 cloud_routes leftovers (Phase-6). Do NOT bump version. CHANGELOG inside `<!-- PR-G entries -->` marker.

---

### T39 - PR-G kin-task subsumption + RELEASES finalize

**Complexity:** low
**Depends on:** T38

**Description:** Conditional on OQ-1 operator-confirmation: add 2 close-out commits subsuming #125 and #126. Update RELEASES.md with phase-5 receipt. Tag v0.36.78 with phase-5 close-out summary.

**Files in scope:**
- `RELEASES.md`
- `CHANGELOG.md`

**Files read-only:**
- `MASTER.md`

**Test strategy:** Manual review of RELEASES entry. git tag v0.36.78 references phase-5 close-out.

**Scope fence:** Subsumption commits ONLY if OQ-1 operator-confirmed; else tag without subsumption and leave #125/#126 open for Phase-6.

---

## PR-E2 — suite green-gate (OPERATOR SCOPE INJECTION 2026-05-28)

Second sub-PR in the PR-E wave. Ships AFTER PR-E (audit + boundary-touch + targeted deletion) lands. POLICY = JUSTIFIED-SKIP GATE (per DD-42): every test PASSES, or carries a documented skip reason in an ALLOWLISTED category {platform, optional-dep, engine-aware (PG-vs-SQLite), tracked-upstream-bug (#N)}. Zero failures, zero xpass (xfail_strict=true). No test stays skipped because "it broke and wasn't the current scope." Measured landscape (2026-05-28, pr-d branch): 63 unconditional/in-body skips across 43 files (suspect pool); 24 conditional skipif across 13 files (mostly legit gates); 4 xfails (all tests/simulation/lifecycle). PR-E2 gets standard dual-Opus QA at 100% confidence.

### T40 - PR-E2 green-gate AUDIT
**Complexity:** medium
**Depends on:** PR-E merged
**Description:** Run the FULL suite on GREEN main (ONLY after PR-E lands — never against an incomplete working tree). Capture the true failing/skip/xfail inventory. Classify the 63 unconditional skips into {fix-and-unskip | delete-as-dead-code | justify}, confidence-tier each.
**Files in scope:** docs/audits/2026-05-28-test-audit/green-gate-audit.md
**Scope fence:** Audit/list only — no test changes in T40. Run against merged main, not a WIP tree.

### T41 - PR-E2 drive failures green + fix-and-unskip
**Complexity:** high
**Depends on:** T40
**Description:** Drive ALL failing tests green; fix-and-unskip resolvable skips; delete genuinely-dead skipped tests ONLY where the surface is covered elsewhere. Includes the 2 walkforward stale-row failures (#126).
**Scope fence:** Each deletion traceable to a T40-audit line + a covered-elsewhere proof. Each fix-and-unskip proven non-vacuous.

### T42 - PR-E2 justify + normalize skips/xfails
**Complexity:** medium
**Depends on:** T40
**Description:** Every surviving skip gets an allowlisted reason string + a tracking task #N. Validate each of the 24 skipif conditions is a real gate. Adjudicate the 4 xfails: fix→remove the marker, OR mark strict + attach a tracking task.
**Scope fence:** Allowlist categories ONLY {platform, optional-dep, engine-aware, tracked-upstream-bug(#N)}; no free-text "broke, out of scope".

### T43 - PR-E2 CI SENTINEL
**Complexity:** high
**Depends on:** T41, T42
**Description:** Add tests/test_suite_integrity.py that FAILS if (a) any test failed, (b) any skip lacks an allowlisted reason, (c) any xfail xpassed. Set xfail_strict=true in pyproject/pytest.ini. Wire into .github/workflows/pg-tests.yml. Sentinel MUST be proven non-vacuous: verify it goes RED when a skip-without-reason, a failure, and an xpass are each introduced in a tmp fixture.
**Scope fence:** pg-tests.yml edits = sentinel wiring only (no floor lowering per DD-20). Sentinel verify-by-mutation mandatory.

### T44 - PR-E2 CHANGELOG + floor reconciliation
**Complexity:** low
**Depends on:** T43
**Description:** CHANGELOG under <!-- PR-E2 entries --> marker. CLOSE #126 (absorbed here, NOT in PR-G) — coordinate with PR-G's #125/#126 OQ-1 subsumption so #126 isn't double-handled. Note whether #125 lazy-import is needed to unskip tests/training/test_pass_c.py (carries 4 skipif).
**Scope fence:** Do NOT bump version. CHANGELOG inside <!-- PR-E2 entries --> marker. Reconcile #126 ownership with PR-G T39.

---


## Implementation receipts

- **PR-A LANDED 2026-05-27** commit `a8bf5ff9` (PR #1186) — T100 + T1 + T2 + T3 shipped as 6 commits in suggested order; dual-Opus QA both SOUND; +4 tests / -19 debris files; +.github/PULL_REQUEST_TEMPLATE.md + archive/sqlite-debris-2026-05-27/. Procedural skips: T1e known_violations.json prune (no debris entries existed; verified empty). Pre-existing failure surfaced: test_no_file_over_400_lines on scan_service.py — out of scope, owned by PR-C T15.
- **PR-B LANDED 2026-05-27** commit `75334f27` (PR #1188) — T4 + T4b + T4c + T4d + T6 + T7 + T8 + T9 shipped as 10 commits (8 original + 2 QA-revisions); dual-Opus QA Attempt 3 BOTH SOUND (Attempt 1 caught convergent ripple finding on tests/test_schema.py:822+872 parametrize against deleted `_fetch_closed_trades_from_postgres` symbol — revision `cd694efd`; Attempt 2 caught CHANGELOG enumeration of 9 nonexistent test functions + 7 files — revision `f6d584b4`). PR-B scope EXPANDED with T4b/T4c/T4d cloud_app cleanup remediation (kin #9 for plan-gap). T5 SKIPPED per kin #13 (`scripts/render_to_local_migrate.py` houses load-bearing `apply_ownership_reconciliation` function; deferred to dedicated migration PR). Net test delta: -137 (6870 final from 7007 baseline; floor 5,467 safe with 1,403 margin). 6 kins filed: #9 (plan-gap T4), #10 (rewrite test_status.py), #11 (rewrite test_shadow_desk_filter.py), #12 (hardcoded-timestamp flake, unrelated), #13 (plan-gap T5), #14 (stale cloud_app docstring prose in ~17 src/ files). Coordinator merged at 21:30 EDT on operator override of dead-window wait.
- **Mid-campaign hotfix to main** commit `c3fd74c2` (2026-05-28) — restored `Config keys:` docstring line in 3 cloud_routes (notifications/preflight/walkforward); PR-B T7 dropped it when stripping DATABASE_URL, turning `test_all_modules_have_standard_docstring` RED on main; both PR-B reviewers misclassified it as pre-existing. kin #16. Surfaced during PR-C T10 verification.
- **PR-C LANDED 2026-05-28** commit `6e5dbaf4` (PR #1189) — T10-T16 + T11 (all 7 refactors) shipped as 11 commits; dual-Opus QA Attempt 1 BOTH SOUND. Operator authorized Option-A (tests/-edit) on 2026-05-28 after T11/T12 hit systemic module-attribute-@patch pinning — each refactor re-targets patches to new modules + proves non-vacuity (memory feedback_refactor_patch_retarget). Splits: executor.py 3093→1231L, trainer.py 1463→1339L, cli/commands.py 1531→90L, governor.py 949→931L + system.py 723→370L, scan_service.py 517→220L, email_digest.py 1236→354L, telegram.py 1662→821L. test_repo_structure now FULLY GREEN (T15 fixed the last size failure). Test count 6870→6934. DD-40 false-premise corrected (kin #19: src/cli has no decorators/audit_log — conflated with src/tools). GovernorAudit class didn't exist (only 46L fn). ORCHESTRATION INCIDENT (kin #21): an agent over-ran scope — ran T17 close-out (`d6169189`+`2bc6acdf`) before T11 landed, recording T11 as deferred; coordinator reconciled CHANGELOG directly (`a4016f14`). Kins #15/#17/#18/#19/#20/#21 filed; #22 closed (T11 landed not deferred). Non-mutating — merged immediately post-QA.
- **PR-E LANDED 2026-05-28** commit `55d488e4` (PR #1191) — test audit (#102): deleted 2 empirically-confirmed-vacuous tests (`test_notify_gate_proposal_does_not_raise`, `test_handle_ib_error_does_not_raise` — both H4 does-not-raise over log-only-stub SUTs, cited to Pass-B EXP-1/EXP-2) + added 23 boundary-touch tests across all 6 DD-19 seams (DB/Broker/LLM/ripgrep/NSSM/HTTP), each driving real artifacts (no mocks at the seam) + proven would-fail-if-impl-deleted. Two-pass receipt at `docs/audits/2026-05-28-test-audit/` (T27 Pass A 194 candidates `c295c004` → T28 Pass B `9f7b5fc2` → T29 execute `303d6e40` → T30 close-out `fdd83aaa`). **T29 agent TIMED OUT pre-commit (truncated report); coordinator did PM-side close-out**: CAUGHT + removed 1 vacuous addition (broker fractional-quantity — proved vacuous by mutation: `quantity: float→int` left it passing; plain dataclass has no coercion SUT) + HARDENED 1 (ripgrep use-test empty-results blind spot). PRE-MERGE MATH CHECK exact: 6989→7010 == 6989+23−2; floor 5,467 held. dual-Opus QA Attempt 1 BOTH SOUND 100% (QA-2 independently ran 6 break-the-SUT experiments, one per seam — all FAILED-while-broken = non-vacuous; zero mocks at seams; src/ left clean). pg-tests PASS (path-filtered; the pre-existing #1055-cutover api-route red cluster — `test_route_parity`/`test_system_index` — did NOT gate this PR; filed kin #26 as PR-E2 T40 input). Non-mutating (zero src/) — no dead-window/NSSM-smoke needed; merged on operator authorization (3-branch CI logic, memory feedback_ci_red_disambiguation; CI green = branch A). OPERATOR SCOPE INJECTION during this wave: PR-E2 suite green-gate (T40-T44, DD-42) appended to plan, ships AFTER PR-E.
- **PR-D LANDED 2026-05-28** commit `0702ef0a` (PR #1190) — CollectorResult Big Bang (#72): all 21 collectors migrated dict→CollectorResult + `_safe_run` flipped to return it. 12 commits, T19 (the flip) LAST per DA1: T18 (dataclass) → T20-pre (consumer-aware foundation) → T20-T25 (21 collectors in batches) → T21b/T24-fix (consumer-seams) → T26 (docs) → T19 (flip). 53 files, +1940/-353. dual-Opus QA Attempt 1 BOTH SOUND (100% confidence; silent-failure axis empirically verified closed). Operator-chosen CONSUMER-AWARE migration (kin #23): DD-15 r3's truthiness-bridge premise was false — collectors have DIRECT dict-consumers (overnight._is_collector_error would have silently reversed the #623 fix); migrated 5 consumer sites to dual-mode. 2 spec defects corrected: capability_health routing DROPPED (non-existent set_status API; not in §207) + the no-__bool__ truthiness trap (37 gating callers → .is_healthy; watch_handlers.py pulled into scope). edgar_historical NOT migrated (doc-resolution helper, not a collector — kin #24). Pre-existing 21 tests/api/ failures unrelated (kin #20 cloud_app→app auth). Coordinator merged ~10:55 EDT on operator override of dead-window wait; NSSM smoke-test (import-level) clean, watch loop undisturbed. Kins #23 (resolved)/#24 filed.
