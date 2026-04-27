# Known Pre-Existing Test Failures

Canonical list of test failures that exist on `main` and are not regressions from current work. Updated atomically when failures land or clear. Agents reference this list in PR bodies rather than independently rediscovering.

**How to use:** Before flagging a "pre-existing failure" in a PR review, check this list. If the failure is here, just state "no NEW failures introduced; documented list unchanged." If a failure is NOT here, it's either a regression (must be fixed) or a newly-discovered pre-existing (must be added to this list with a tracker).

---

## Currently failing on main (last verified: 2026-04-27 post-Sprint-0.D.2 full sweep — 34 failures)

Full sweep: `34 failed, 4034 passed, 11 skipped` — run `python -m pytest tests/ -q --timeout=60` to reproduce.

### SPRINT-0.C-INTRODUCED REGRESSION (27 tests)

| Test | Category | Tracker | One-line reason |
|------|----------|---------|-----------------|
| `tests/audits/test_training_audit_cli.py::test_cli_end_to_end_dry_run_prints_summary_json` | SPRINT-0.C-INTRODUCED | #767 | `connect_db` NameError in `src/training/audit/core.py:56` — C.1 migration missed import |
| `tests/audits/test_training_audit_cli.py::test_cli_write_mode_updates_db` | SPRINT-0.C-INTRODUCED | #767 | Same root cause as above |
| `tests/audits/test_training_audit_cli.py::test_cli_reruns_produce_identical_summaries` | SPRINT-0.C-INTRODUCED | #767 | Same root cause as above |
| `tests/training/test_audit_integration.py::test_dry_run_does_not_mutate_db` | SPRINT-0.C-INTRODUCED | #767 | Same root cause: `connect_db` NameError in `src/training/audit/core.py:56` |
| `tests/training/test_audit_integration.py::test_write_mode_flags_quarantined_rows` | SPRINT-0.C-INTRODUCED | #767 | Same root cause as above |
| `tests/training/test_audit_integration.py::test_dry_run_is_reproducible_rerun_identical_summary` | SPRINT-0.C-INTRODUCED | #767 | Same root cause as above |
| `tests/training/test_audit_integration.py::test_single_pass_runs_in_isolation` | SPRINT-0.C-INTRODUCED | #767 | Same root cause as above |
| `tests/training/test_audit_integration.py::test_summary_has_taxonomy_conformant_reason_codes` | SPRINT-0.C-INTRODUCED | #767 | Same root cause as above |
| `tests/platform/test_backtest_engine.py::test_backtest_matches_hand_computed_example_event_driven` | SPRINT-0.C-INTRODUCED | #783 | `connect_db` NameError in `src/platform/signal_eval.py` — C.1 missed import |
| `tests/platform/test_find_candidates.py::test_find_candidates_returns_nonempty_on_signal_match` | SPRINT-0.C-INTRODUCED | #783 | Same root cause: `signal_eval.py` missing `connect_db` import |
| `tests/platform/test_sector_filter.py::test_sector_filter_keeps_only_defensive` | SPRINT-0.C-INTRODUCED | #783 | Same root cause as above |
| `tests/platform/test_sector_filter.py::test_no_sector_filter_returns_all` | SPRINT-0.C-INTRODUCED | #783 | Same root cause as above |
| `tests/platform/test_sector_filter.py::test_sector_filter_multiple_sectors` | SPRINT-0.C-INTRODUCED | #783 | Same root cause as above |
| `tests/platform/test_signal_eval_python_plugin.py::test_python_plugin_dedupes_open_positions` | SPRINT-0.C-INTRODUCED | #783 | Same root cause as above |
| `tests/platform/test_signal_eval_scheduled.py::test_scheduled_dedupes_open_positions` | SPRINT-0.C-INTRODUCED | #783 | Same root cause as above |
| `tests/test_connect_db_complete_coverage.py::test_no_raw_sqlite3_connect_outside_allowlist` | SPRINT-0.C-INTRODUCED | #784 | `render_sync.py` has 6 raw sqlite3.connect sites not in allowlist after C.1 |
| `tests/test_log_levels.py::test_log_call_uses_expected_level[shadow_trading/alpaca_adapter.py-[CANCEL] Could not cancel order-debug]` | SPRINT-0.C-INTRODUCED | #785 | C.2 alpaca split moved [CANCEL] log emitter; test still scans old file path |
| `tests/test_log_levels.py::test_log_call_uses_expected_level[shadow_trading/alpaca_adapter.py-[CANCEL] Failed to cancel order-debug]` | SPRINT-0.C-INTRODUCED | #785 | Same root cause as above |
| `tests/test_log_levels.py::test_log_call_uses_expected_level[shadow_trading/alpaca_adapter.py-[CANCEL] Could not cancel all orders-debug]` | SPRINT-0.C-INTRODUCED | #785 | Same root cause as above |
| `tests/test_log_levels.py::test_log_call_uses_expected_level[shadow_trading/alpaca_adapter.py-[CANCEL] Could not list orders-debug]` | SPRINT-0.C-INTRODUCED | #785 | Same root cause as above |
| `tests/test_repo_structure.py::test_no_file_over_400_lines` | SPRINT-0.C-INTRODUCED | #786 | `scan_service.py` is 421 lines; not grandfathered — C.1/continuation grew it past 400 |
| `tests/test_repo_structure.py::test_no_function_over_60_lines` | SPRINT-0.C-INTRODUCED | #787 | `scan_service.py:run_scan` grew from grandfathered 330 to 385 lines (>380 tolerance) |
| `tests/test_live_trading.py::TestLiveAdapter::test_get_live_config_requires_credentials` | SPRINT-0.C-INTRODUCED | #788 | C.2 alpaca split — `LiveTradingError` moved to new module, test import stale |
| `tests/test_live_trading.py::TestLiveAdapter::test_live_trading_client_uses_paper_false` | SPRINT-0.C-INTRODUCED | #788 | C.2 alpaca split — config mock patches wrong path, falls back to example config |
| `tests/test_services.py::test_scan_with_packet_worthy_dry_run` | SPRINT-0.C-INTRODUCED | #789 | `data_integrity.py` rejects test mock universe ("Empty universe after validation!") — C.1/C.5 |
| `tests/test_services.py::test_scan_strategy_wires_strategy_and_attribution_hooks` | SPRINT-0.C-INTRODUCED | #789 | Same root cause as above |
| `tests/test_services.py::test_scan_strategy_without_attribution_hooks_skips_logging` | SPRINT-0.C-INTRODUCED | #789 | Same root cause as above |
| `tests/shadow_trading/test_reconcile_dispatch_db_path.py::test_get_strategies_by_status_resolves_none_to_config` | SPRINT-0.C-INTRODUCED | #790 | C.1 added `timeout=` kwarg to `connect_db()`; test mock lambda doesn't accept it |
| `tests/shadow_trading/test_reconcile_dispatch_db_path.py::test_get_strategies_by_status_preserves_explicit_path` | SPRINT-0.C-INTRODUCED | #790 | Same root cause as above |
| `tests/shadow_trading/test_broker_partial_swallow_upgrades.py::test_site7_stop_loss_failure_persists` | SPRINT-0.C-INTRODUCED | #791 | C.5 executor audit changed stop-order error path; `log_and_persist(operation='place_stop_order')` no longer called |

### TRUE PRE-EXISTING (4 tests)

| Test | Category | Tracker | One-line reason |
|------|----------|---------|-----------------|
| `tests/test_broker_interface.py::TestAlpacaLiveBracket651::test_place_live_bracket_submits_alpaca_bracket_request` | TRUE PRE-EXISTING | #760 / #792 | Live Alpaca bracket API — requires live broker infra, pre-Sprint-0 |
| `tests/test_broker_interface.py::TestAlpacaLiveBracket651::test_place_live_bracket_with_limit_uses_limit_request` | TRUE PRE-EXISTING | #760 / #792 | Same root cause as above |
| `tests/test_broker_interface.py::TestAlpacaLiveBracket651::test_paper_and_live_bracket_use_same_alpaca_api` | TRUE PRE-EXISTING | #760 / #792 | Same root cause as above |
| `tests/test_ib_production.py::TestErrorCodes::test_handle_ib_error_classifies_codes` | TRUE PRE-EXISTING | #760 / #792 | IB error codes — requires IB Gateway infra, pre-Sprint-0 |

---

## Recently cleared

| Test | Cleared by | Notes |
|------|-----------|-------|
| `tests/test_ib_production.py::TestErrorCodes::test_handle_ib_error_classifies_codes` | Sprint 0.D PR #764 (D.2 test triage) | `ib_broker_helpers.py` post-PR-#739 split emitted logs under `src.trading.ib_broker_helpers`; added `_ib_logger = logging.getLogger("src.trading.ib_broker")` (PR #735 pattern) |
| `tests/test_broker_interface.py::TestAlpacaLiveBracket651` (3 tests) | Sprint 0.D PR #764 (D.2 test triage) | Tests patched `alpaca_adapter.*` but `place_live_bracket` resolves `_get_live_config`/`_get_live_trading_client` from `alpaca_adapter_live` module scope; `test_paper_and_live_bracket_use_same_alpaca_api` inspected `place_live_bracket` but `OrderClass.BRACKET` lives in `_build_live_bracket_request`. Fixed patch targets and source inspection. |
| `tests/integration/test_track_1_5_full_pipeline.py::test_full_pipeline_when_broker_exception_during_exit` | Sprint 0.B PR #743 (B2.6 test triage) | Stale `'unknown'` assertion; Wave 2b promoted `'broker_exception'` to first-class CONTROLLED_VOCAB |
| `tests/shadow_trading/test_broker_partial_swallow_upgrades.py::test_site6_emergency_close_sdk_missing_persists` | Sprint 0.B PR #743 (B2.6 test triage) | Added missing `place_paper_entry` + `_verify_and_update` mocks so execution reaches the SDK-missing branch |
| `tests/test_repo_structure.py::test_no_file_over_400_lines` (`promotion_gate.py` 573 lines) | Sprint 0.B PR #735 | Real refactor, no grandfather entry |
| `tests/test_repo_structure.py::test_no_file_over_400_lines` (`ib_broker.py` 507 lines) | Sprint 0.B PR #739 | Same pattern, mirrored #735 split |
| `tests/test_repo_structure.py::test_no_function_over_60_lines` (`_run_cpcv` 87 lines) | Sprint 0.B PR #735 | Function-level extraction |
| `tests/test_repo_structure.py::test_no_function_over_60_lines` (`verify_live_order_accepted` 114 lines) | Sprint 0.B PR #739 | Sub-helpers extracted |
| `tests/test_local_routes.py::TestSettings::test_post_settings` and 17 sibling auth-fallout tests | Sprint 0.B PR #729 | Hermetic env fixture for `ARCIS_LOCAL_API_TOKEN` |
| `tests/trading/test_alpaca_live_verification.py` (9 tests) | Sprint 0.C PR #750 (C.2 alpaca split + patch-compat fix) | `_poll_order_status` switched to call-time orchestrator-namespace resolve (PR #735 pattern) |
| `tests/shadow_trading/test_ib_broker_helpers.py` (log namespace failures) | Sprint 0.D PR #764 (#763) | `ib_broker_helpers` log namespace fixed post-C.2 split |

---

## How to update this file

When a new failure lands on main:
1. Add a row to "Currently failing on main"
2. Include the tracker number (or file one if needed)
3. Note the first PR where it was disclosed

When a failure clears:
1. Move from "Currently failing on main" to "Recently cleared"
2. Note the PR that cleared it
3. After ~30 days or 10 PRs, remove the entry from "Recently cleared" (history is in git log)

When a PR introduces a NEW failure that's documented as deferred:
1. Add to "Currently failing on main" with explicit deferral rationale
2. Reference the tracker that owns the fix
3. The PR introducing the failure must explicitly disclose the deferral in its strict-rigor receipts

---

## Sprint 0 / 0.B / 0.C / 0.D lineage

This file was created as part of Sprint 0.C C.4 (process work) per the `arcis:coding-team` skill's Delivery Discipline §4 — specifically the "Pre-existing failure canon" pattern. Replaces the prior pattern of every PR review body independently rediscovering and re-flagging the same 4 failures.

**Sprint 0.D.2 reset (2026-04-27):** Full sweep run on post-Sprint-0.C main revealed 34 failures (not 2 as previously documented). All 34 have been categorized, assigned trackers, and enumerated above. The prior 2-row table was a partial snapshot; this table is the authoritative full picture.

See: `.claude/plugins/arcis/skills/coding-team/SKILL.md` — Delivery Discipline §4
See: `.claude/plugins/arcis/skills/coding-team/references/anti-fallacy-playbook.md` — CQ-07 Pre-existing failure rediscovery
