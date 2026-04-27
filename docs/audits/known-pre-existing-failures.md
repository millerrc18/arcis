# Known Pre-Existing Test Failures

Canonical list of test failures that exist on `main` and are not regressions from current work. Updated atomically when failures land or clear. Agents reference this list in PR bodies rather than independently rediscovering.

**How to use:** Before flagging a "pre-existing failure" in a PR review, check this list. If the failure is here, just state "no NEW failures introduced; documented list unchanged." If a failure is NOT here, it's either a regression (must be fixed) or a newly-discovered pre-existing (must be added to this list with a tracker).

---

## Currently failing on main (last verified: 2026-04-27 post-Sprint-0.C merge)

_(none — all previously tracked failures cleared in Sprint 0.D)_

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

## Sprint 0 / 0.B / 0.C lineage

This file was created as part of Sprint 0.C C.4 (process work) per the `arcis:coding-team` skill's Delivery Discipline §4 — specifically the "Pre-existing failure canon" pattern. Replaces the prior pattern of every PR review body independently rediscovering and re-flagging the same 4 failures.

See: `.claude/plugins/arcis/skills/coding-team/SKILL.md` — Delivery Discipline §4
See: `.claude/plugins/arcis/skills/coding-team/references/anti-fallacy-playbook.md` — CQ-07 Pre-existing failure rediscovery
