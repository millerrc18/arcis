# Pass A — Heuristic Vacuous-Test Candidate List

**Audit:** #102 (PR-E, T27)
**Date:** 2026-05-28
**Branch:** sprint/phase-5/pr-e
**Methodology:** DD-38 Pass A heuristic detection; DA8 test quality
**Status:** CANDIDATE LIST ONLY — no tests deleted (Pass B / T28 verifies empirically)

---

## 1. Scan Overview

| Metric | Value |
|--------|-------|
| Test files scanned | 674 |
| Total candidates flagged | **194** |
| H1 mock-only assertions | 111 |
| H2 high @patch:assert ratio | 26 |
| H3 SUT self-patch | 8 |
| H4 no assertions | 51 |

**Area breakdown (priority order):**

| Area | Candidates | Priority |
|------|-----------|----------|
| scheduler | 38 | P1 (live trading schedule) |
| data_collection | 0 | P2 (data pipeline) |
| tools | 0 | P3 (CLI tooling) |
| safety | 21 | P4 (safety/risk) |
| simulation | 4 | P5 (sim engine) |
| other | 131 | P6 |

---

## 2. Methodology

### Tool

`tmp/vacuous_scanner.py` — Python AST scanner (no imports executed, no tests run).
Scans 674 `test_*.py` files in `tests/` recursively via `ast.iter_child_nodes` to avoid
double-counting class methods. Produces `tmp/scan_results.json`.

### 4 Heuristic Queries

**H1 — Mock-only assertions**

A test function where `total_assert_like > 0` AND `len(real_asserts) == 0`.
`real_asserts` = `ast.Assert` nodes whose `.test` does NOT reference known mock-state attributes
(`called`, `call_count`, `call_args`, `call_args_list`, `return_value`, `mock_calls`)
plus `pytest.raises` context managers, plus `unittest.TestCase.assert*` method calls.
`mock_method_calls` = calls to `assert_called*`, `assert_any_call`, `assert_has_calls`, `assert_not_called`, etc.
Test is flagged when its only assertions are on mock objects — it cannot detect missing SUT logic.

**H2 — @patch:assert ratio > 3:1**

Count of `@patch` / `@mock.patch` / `patch(...)` decorators on the function plus any enclosing
class, divided by total assertion-like count. Flagged when `patch_count > 3` AND `ratio > 3.0`.
Heavy mocking with sparse assertions means most of the SUT is shimmed away.

**H3 — Full-SUT mocking (self-patch)**

Test function name is `test_<subject>` where `<subject>` appears in a `@patch` target's terminal
symbol. E.g. `test_backtest_model_called_per_fold` with `@patch('src.evaluation.walkforward.backtest_model')`.
Guard: terminal symbol > 3 chars, not a keyword (`mock`, `patch`, `side`, `true`, etc.).
When the SUT itself is patched, the test exercises the mock stub, not the production code path.

**H4 — No assertions**

Test function has `total_assert_like == 0` AND >= 2 substantive body statements (excluding
docstring and `pass` nodes). `with pytest.raises` and `with self.assertRaises` context managers
are detected and count as real assertions. H4 candidates are often "does-not-raise" smoke tests —
legitimate but produce no failure if the SUT silently regresses.

### Ranking Key

1. Area priority: scheduler (P1) > safety (P4) > simulation (P5) > other (P6)
2. Severity: H3 (-3 pts) > H4 (-2) = H1 (-2) > H2 (-1)
3. Multi-heuristic (H1+H3 ranks higher than either alone)
4. Alphabetical filepath + line number as tiebreaker

### False-Positive Suppression Applied

- `unittest.TestCase.assertEqual` / `.assertRaises` / `.assertLogs` / `.assertIn` etc. counted as real assertions
- `with self.assertRaises(...)` context manager counted as real assertion
- Functions with only docstring + `pass` excluded from H4
- `ast.iter_child_nodes` (not `ast.walk`) prevents double-counting class methods

### Exact Queries for T28 Re-derivation

```bash
# Re-run the canonical scanner:
python tmp/vacuous_scanner.py > tmp/scan_results.json 2>tmp/scan_stderr.txt

# H1 proxy — tests with assert_called_* but no plain assert on SUT output:
grep -r 'assert_called' tests/ --include='*.py' -l

# H2 proxy — test files with many @patch lines (>3 per test):
grep -rc '@patch' tests/ --include='*.py' | sort -t: -k2 -rn | head -20

# H3 proxy — tests patching a symbol matching the test name:
grep -rn '@patch' tests/ --include='*.py' -B5 | grep -E 'def test_'

# H4 proxy — test functions with zero assert/raises keywords:
python -c "
import ast, pathlib
for f in pathlib.Path('tests').rglob('test_*.py'):
    src = f.read_text(errors='replace')
    try:
        tree = ast.parse(src)
    except SyntaxError:
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith('test_'):
            body = ast.unparse(node)
            if 'assert' not in body and 'raises' not in body:
                print(f'{f}:{node.lineno} {node.name}')
"
```

---

## 3. Top 50 Ranked Candidates

Ranked by risk. Pass B (T28) empirically verifies each entry: delete the SUT implementation,
run the test — if it still passes, the test is confirmed vacuous.

| # | Area | File:Line | Test Name | Heuristic(s) | Why Suspicious |
|---|------|-----------|-----------|-------------|----------------|
| 1 | scheduler | `scheduler/test_eod_report_format.py:112` | `test_send_eod_report_handles_none_best_worst` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| 2 | scheduler | `scheduler/test_overnight_email_routing.py:68` | `test_daily_audit_green_no_email` | H1 | all 2 assertion(s) are on mock objects (no SUT output checked) |
| 3 | scheduler | `scheduler/test_overnight_email_routing.py:87` | `test_daily_audit_yellow_no_email` | H1 | all 2 assertion(s) are on mock objects (no SUT output checked) |
| 4 | scheduler | `scheduler/test_overnight_email_routing.py:191` | `test_shadow_mode_saturday_also_fires_immediate_send` | H1 | all 2 assertion(s) are on mock objects (no SUT output checked) |
| 5 | scheduler | `scheduler/test_overnight_email_routing.py:226` | `test_off_mode_saturday_only_enqueues` | H1 | all 2 assertion(s) are on mock objects (no SUT output checked) |
| 6 | scheduler | `scheduler/test_reports_email_routing.py:98` | `test_morning_watchlist_with_via_cli_calls_send_directly` | H1 | all 2 assertion(s) are on mock objects (no SUT output checked) |
| 7 | scheduler | `scheduler/test_reports_email_routing.py:123` | `test_morning_watchlist_email_mode_full_stream_still_emails` | H1 | all 2 assertion(s) are on mock objects (no SUT output checked) |
| 8 | scheduler | `scheduler/test_walkforward_reconciler.py:146` | `test_reconciler_skips_paired_backtest` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| 9 | scheduler | `scheduler/test_watch_email_digest_schedule.py:316` | `test_holdover_time_aligned_mode_suppresses_midday_evening` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| 10 | scheduler | `scheduler/test_watch_platform_tick.py:50` | `test_platform_tick_respects_cadence` | H1 | all 3 assertion(s) are on mock objects (no SUT output checked) |
| 11 | scheduler | `scheduler/test_watch_platform_tick.py:82` | `test_platform_tick_runs_each_strategy_independently` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| 12 | scheduler | `scheduler/test_watch_platform_tick.py:128` | `test_platform_tick_zero_active_strategies_is_noop` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| 13 | scheduler | `test_scheduler_watch.py:32` | `test_write_heartbeat_called_in_iteration` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| 14 | scheduler | `test_watch_handler_registry.py:129` | `test_dispatch_unknown_event_is_noop` | H4 | zero assert statements and no pytest.raises (has 2 substantive statement(s)) |
| 15 | scheduler | `test_watch_handlers.py:130` | `test_maybe_morning_training_stop_respects_done_flag` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| 16 | scheduler | `test_watch_handlers.py:137` | `test_maybe_morning_training_stop_before_window` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| 17 | scheduler | `test_watch_handlers.py:158` | `test_maybe_evening_training_launch_fires_after_midnight` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| 18 | scheduler | `test_watch_handlers.py:165` | `test_maybe_evening_training_launch_before_window` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| 19 | scheduler | `test_watch_handlers.py:171` | `test_maybe_evening_training_launch_respects_done_flag` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| 20 | scheduler | `test_watch_handlers.py:185` | `test_maybe_market_open_training_stop_fires_after_925` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| 21 | scheduler | `test_watch_handlers.py:191` | `test_maybe_market_open_training_stop_before_925` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| 22 | scheduler | `test_watch_handlers.py:197` | `test_maybe_market_open_training_stop_respects_done_flag` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| 23 | scheduler | `test_watch_handlers.py:259` | `test_maybe_post_close_capture_before_window` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| 24 | scheduler | `test_watch_handlers.py:265` | `test_maybe_overnight_training_collection_requires_training_enabled` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| 25 | scheduler | `test_watch_handlers.py:271` | `test_maybe_overnight_training_collection_fires_at_18` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| 26 | scheduler | `test_watch_handlers.py:277` | `test_maybe_stress_test_only_fires_when_model_version_changed` | H1 | all 2 assertion(s) are on mock objects (no SUT output checked) |
| 27 | scheduler | `test_watch_handlers.py:287` | `test_maybe_data_collection_fires_at_2130_daily_including_weekend` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| 28 | scheduler | `test_watch_handlers.py:295` | `test_maybe_news_ingestion_fires_at_22_daily` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| 29 | scheduler | `test_watch_handlers.py:302` | `test_maybe_enrichment_precache_fires_at_23_daily` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| 30 | scheduler | `test_watch_handlers.py:309` | `test_maybe_1min_bar_collection_fires_at_2330_daily` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| 31 | scheduler | `test_watch_handlers.py:326` | `test_maybe_pre_market_refresh_skips_weekend` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| 32 | scheduler | `test_watch_handlers.py:332` | `test_maybe_premarket_rolling_features_fires_at_602_weekday` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| 33 | scheduler | `test_watch_handlers.py:338` | `test_maybe_premarket_training_fires_at_7_weekday` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| 34 | scheduler | `test_watch_handlers.py:344` | `test_maybe_premarket_news_scoring_fires_at_802_weekday` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| 35 | scheduler | `test_watch_handlers.py:350` | `test_maybe_premarket_candidates_fires_before_925` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| 36 | scheduler | `test_watch_handlers.py:360` | `test_maybe_premarket_candidates_skips_after_925` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| 37 | scheduler | `test_watch_pragma_isolation.py:215` | `test_configure_database_on_postgres_path_is_no_op_for_pragmas` | H4 | zero assert statements and no pytest.raises (has 9 substantive statement(s)) |
| 38 | scheduler | `test_watch_strategy_gate.py:274` | `test_notify_gate_proposal_does_not_raise` | H4 | zero assert statements and no pytest.raises (has 3 substantive statement(s)) |
| 39 | safety | `platform/test_shadow_harness.py:107` | `test_harness_bracket_monitor_uses_research_client` | H1 | all 2 assertion(s) are on mock objects (no SUT output checked) |
| 40 | safety | `platform/test_shadow_harness.py:160` | `test_harness_verify_accounts_distinct_on_init` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| 41 | safety | `risk/test_governor_disabled_alert.py:44` | `test_warn_once_is_idempotent_within_process` | H1 | all 2 assertion(s) are on mock objects (no SUT output checked) |
| 42 | safety | `risk/test_governor_disabled_alert.py:59` | `test_warn_once_skips_telegram_when_disabled` | H1 | all 2 assertion(s) are on mock objects (no SUT output checked) |
| 43 | safety | `risk/test_governor_disabled_alert.py:72` | `test_warn_once_tolerates_telegram_error` | H1 | all 2 assertion(s) are on mock objects (no SUT output checked) |
| 44 | safety | `test_bracket_safety.py:62` | `test_retry_exit_called_for_exit_failed` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| 45 | safety | `test_bracket_safety.py:95` | `test_bad_timestamp_forces_timeout` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| 46 | safety | `test_ib_broker.py:631` | `test_disconnect_safe_when_not_connected` | H4 | zero assert statements and no pytest.raises (has 3 substantive statement(s)) |
| 47 | safety | `test_ib_production.py:60` | `test_no_reconnect_when_already_connected` | H1 | all 2 assertion(s) are on mock objects (no SUT output checked) |
| 48 | safety | `test_ib_shadow.py:131` | `test_never_calls_place_order` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| 49 | safety | `test_kill_switch_source_allowlist.py:83` | `test_resume_from_auditor_succeeds` | H4 | zero assert statements and no pytest.raises (has 2 substantive statement(s)) |
| 50 | safety | `test_kill_switch_source_allowlist.py:89` | `test_resume_from_scheduler_succeeds` | H4 | zero assert statements and no pytest.raises (has 2 substantive statement(s)) |

---

## 4. Full Candidate List by Area

### 4.1 Scheduler (P1 — live trading schedule) — 38 candidates

| File:Line | Test Name | Heuristic(s) | Why Suspicious |
|-----------|-----------|-------------|----------------|
| `scheduler/test_eod_report_format.py:112` | `test_send_eod_report_handles_none_best_worst` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| `scheduler/test_overnight_email_routing.py:68` | `test_daily_audit_green_no_email` | H1 | all 2 assertion(s) are on mock objects (no SUT output checked) |
| `scheduler/test_overnight_email_routing.py:87` | `test_daily_audit_yellow_no_email` | H1 | all 2 assertion(s) are on mock objects (no SUT output checked) |
| `scheduler/test_overnight_email_routing.py:191` | `test_shadow_mode_saturday_also_fires_immediate_send` | H1 | all 2 assertion(s) are on mock objects (no SUT output checked) |
| `scheduler/test_overnight_email_routing.py:226` | `test_off_mode_saturday_only_enqueues` | H1 | all 2 assertion(s) are on mock objects (no SUT output checked) |
| `scheduler/test_reports_email_routing.py:98` | `test_morning_watchlist_with_via_cli_calls_send_directly` | H1 | all 2 assertion(s) are on mock objects (no SUT output checked) |
| `scheduler/test_reports_email_routing.py:123` | `test_morning_watchlist_email_mode_full_stream_still_emails` | H1 | all 2 assertion(s) are on mock objects (no SUT output checked) |
| `scheduler/test_walkforward_reconciler.py:146` | `test_reconciler_skips_paired_backtest` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| `scheduler/test_watch_email_digest_schedule.py:316` | `test_holdover_time_aligned_mode_suppresses_midday_evening` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| `scheduler/test_watch_platform_tick.py:50` | `test_platform_tick_respects_cadence` | H1 | all 3 assertion(s) are on mock objects (no SUT output checked) |
| `scheduler/test_watch_platform_tick.py:82` | `test_platform_tick_runs_each_strategy_independently` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| `scheduler/test_watch_platform_tick.py:128` | `test_platform_tick_zero_active_strategies_is_noop` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| `test_scheduler_watch.py:32` | `test_write_heartbeat_called_in_iteration` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| `test_watch_handler_registry.py:129` | `test_dispatch_unknown_event_is_noop` | H4 | zero assert statements and no pytest.raises (has 2 substantive statement(s)) |
| `test_watch_handlers.py:130` | `test_maybe_morning_training_stop_respects_done_flag` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| `test_watch_handlers.py:137` | `test_maybe_morning_training_stop_before_window` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| `test_watch_handlers.py:158` | `test_maybe_evening_training_launch_fires_after_midnight` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| `test_watch_handlers.py:165` | `test_maybe_evening_training_launch_before_window` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| `test_watch_handlers.py:171` | `test_maybe_evening_training_launch_respects_done_flag` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| `test_watch_handlers.py:185` | `test_maybe_market_open_training_stop_fires_after_925` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| `test_watch_handlers.py:191` | `test_maybe_market_open_training_stop_before_925` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| `test_watch_handlers.py:197` | `test_maybe_market_open_training_stop_respects_done_flag` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| `test_watch_handlers.py:259` | `test_maybe_post_close_capture_before_window` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| `test_watch_handlers.py:265` | `test_maybe_overnight_training_collection_requires_training_enabled` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| `test_watch_handlers.py:271` | `test_maybe_overnight_training_collection_fires_at_18` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| `test_watch_handlers.py:277` | `test_maybe_stress_test_only_fires_when_model_version_changed` | H1 | all 2 assertion(s) are on mock objects (no SUT output checked) |
| `test_watch_handlers.py:287` | `test_maybe_data_collection_fires_at_2130_daily_including_weekend` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| `test_watch_handlers.py:295` | `test_maybe_news_ingestion_fires_at_22_daily` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| `test_watch_handlers.py:302` | `test_maybe_enrichment_precache_fires_at_23_daily` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| `test_watch_handlers.py:309` | `test_maybe_1min_bar_collection_fires_at_2330_daily` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| `test_watch_handlers.py:326` | `test_maybe_pre_market_refresh_skips_weekend` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| `test_watch_handlers.py:332` | `test_maybe_premarket_rolling_features_fires_at_602_weekday` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| `test_watch_handlers.py:338` | `test_maybe_premarket_training_fires_at_7_weekday` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| `test_watch_handlers.py:344` | `test_maybe_premarket_news_scoring_fires_at_802_weekday` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| `test_watch_handlers.py:350` | `test_maybe_premarket_candidates_fires_before_925` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| `test_watch_handlers.py:360` | `test_maybe_premarket_candidates_skips_after_925` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| `test_watch_pragma_isolation.py:215` | `test_configure_database_on_postgres_path_is_no_op_for_pragmas` | H4 | zero assert statements and no pytest.raises (has 9 substantive statement(s)) |
| `test_watch_strategy_gate.py:274` | `test_notify_gate_proposal_does_not_raise` | H4 | zero assert statements and no pytest.raises (has 3 substantive statement(s)) |

---

### 4.2 Data Collection (P2 — data pipeline) — 0 candidates

*No candidates flagged. The 22 data_collection test files consistently use real SUT assertions
(assertEqual, assertIn, pytest.raises). This is a positive signal confirming data-pipeline test
quality.*

---

### 4.3 Safety (P4 — risk governor, kill switch, bracket orders, IB broker) — 21 candidates

| File:Line | Test Name | Heuristic(s) | Why Suspicious |
|-----------|-----------|-------------|----------------|
| `platform/test_shadow_harness.py:107` | `test_harness_bracket_monitor_uses_research_client` | H1 | all 2 assertion(s) are on mock objects (no SUT output checked) |
| `platform/test_shadow_harness.py:160` | `test_harness_verify_accounts_distinct_on_init` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| `risk/test_governor_disabled_alert.py:44` | `test_warn_once_is_idempotent_within_process` | H1 | all 2 assertion(s) are on mock objects (no SUT output checked) |
| `risk/test_governor_disabled_alert.py:59` | `test_warn_once_skips_telegram_when_disabled` | H1 | all 2 assertion(s) are on mock objects (no SUT output checked) |
| `risk/test_governor_disabled_alert.py:72` | `test_warn_once_tolerates_telegram_error` | H1 | all 2 assertion(s) are on mock objects (no SUT output checked) |
| `test_bracket_safety.py:62` | `test_retry_exit_called_for_exit_failed` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| `test_bracket_safety.py:95` | `test_bad_timestamp_forces_timeout` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| `test_ib_broker.py:631` | `test_disconnect_safe_when_not_connected` | H4 | zero assert statements and no pytest.raises (has 3 substantive statement(s)) |
| `test_ib_production.py:60` | `test_no_reconnect_when_already_connected` | H1 | all 2 assertion(s) are on mock objects (no SUT output checked) |
| `test_ib_shadow.py:131` | `test_never_calls_place_order` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| `test_kill_switch_source_allowlist.py:83` | `test_resume_from_auditor_succeeds` | H4 | zero assert statements and no pytest.raises (has 2 substantive statement(s)) |
| `test_kill_switch_source_allowlist.py:89` | `test_resume_from_scheduler_succeeds` | H4 | zero assert statements and no pytest.raises (has 2 substantive statement(s)) |
| `test_kill_switch_source_allowlist.py:93` | `test_resume_from_unknown_source_succeeds` | H4 | zero assert statements and no pytest.raises (has 2 substantive statement(s)) |
| `test_live_trading.py:219` | `test_daily_loss_guard_halts_trading` | H2 | 4 @patch decorators vs 1 assertion(s) (ratio 4.0:1) |
| `test_reconcile.py:131` | `test_position_with_no_shadow_trade_sends_alert` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| `test_reconcile.py:175` | `test_orphan_position_sends_alert` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| `test_reconcile.py:185` | `test_orphan_position_auto_exits` | H1 | all 2 assertion(s) are on mock objects (no SUT output checked) |
| `test_shadow_service.py:219` | `test_close_position_without_shadow_trade_sends_alert` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| `test_shadow_service.py:230` | `test_submit_order_calls_broker` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |
| `trading/test_ib_broker_helpers.py:22` | `test_handle_ib_error_does_not_raise` | H4 | zero assert statements and no pytest.raises (has 4 substantive statement(s)) |
| `trading/test_ib_cancel_before_close.py:47` | `test_cancel_called_for_open_bracket` | H1 | all 1 assertion(s) are on mock objects (no SUT output checked) |

---

### 4.4 Simulation (P5 — sim engine lifecycle) — 4 candidates

| File:Line | Test Name | Heuristic(s) | Why Suspicious |
|-----------|-----------|-------------|----------------|
| `simulation/lifecycle/test_clock.py:49` | `test_advance_rejects_negative` | H4 | zero assert statements and no pytest.raises (has 2 substantive statement(s)) |
| `simulation/lifecycle/test_fake_market_llm.py:107` | `test_market_data_same_seed_identical_bars` | H4 | zero assert statements and no pytest.raises (has 5 substantive statement(s)) |
| `simulation/lifecycle/test_fake_market_llm.py:225` | `test_fetch_ohlcv_same_seed_frame_equal` | H4 | zero assert statements and no pytest.raises (has 6 substantive statement(s)) |
| `simulation/lifecycle/test_fake_market_llm.py:260` | `test_fetch_spy_benchmark_same_seed_frame_equal` | H4 | zero assert statements and no pytest.raises (has 3 substantive statement(s)) |

---

### 4.5 Tools (P3 — CLI tooling) — 0 candidates

*No candidates flagged. tools/ tests consistently exercise real assertion patterns.*

---

### 4.6 Other (remaining flat tests/ root + subdirectories) — 131 candidates

Selected high-risk entries from "other" (H1+H3, H2>5:1, or H4 in critical paths):

| File:Line | Test Name | Heuristic(s) | Why Suspicious |
|-----------|-----------|-------------|----------------|
| `evaluation/test_walkforward.py:324` | `test_backtest_model_called_per_fold` | H1+H3 | SUT self-patched; only checks mock call_count (no fold output validated) |
| `test_services.py:276` | `test_event_risk_hard_block_skips_llm` | H1+H2 | 13 @patch vs 1 mock assertion (13.0:1); SUT nearly fully shimmed |
| `evaluation/test_backtester_corpus.py:251` | `test_missing_corpus_entries_are_skipped_and_logged` | H2 | 11 @patch vs 1 assertion (11.0:1) |
| `evaluation/test_shadow.py:245` | `test_primary_corpus_path_filters_to_taken_only_regression_lock` | H2 | 11 @patch vs 1 assertion (11.0:1) |
| `evaluation/test_shadow.py:295` | `test_shadow_filters_parse_failed_for_fair_comparison` | H2 | 11 @patch vs 1 assertion (11.0:1) |
| `evaluation/test_shadow.py:351` | `test_shadow_trade_count_geq_primary_trade_count` | H2 | 11 @patch vs 1 assertion (11.0:1) |
| `test_backtester.py:212` | `test_backtest_model_unexpected_exception_propagates` | H2 | 6 @patch vs 1 assertion (6.0:1) |
| `test_backtester.py:325` | `test_backtest_with_calibration_has_lower_pnl` | H2 | 12 @patch vs 2 assertions (6.0:1) |
| `test_backtester.py:373` | `test_backtest_without_calibration_no_cost_applied` | H2 | 12 @patch vs 2 assertions (6.0:1) |
| `test_cto_report.py:154` | `test_all_wins` | H2 | 7 @patch vs 1 assertion (7.0:1) |
| `evaluation/test_walkforward.py:337` | `test_backtest_model_receives_date_kwargs` | H3 | patches backtest_model (the SUT); only validates call kwargs not outputs |
| `test_broker_interface.py:226` | `test_get_current_price_delegates` | H3 | test patches its own SUT method |
| `test_local_api_routes.py:231` | `test_submit_review` | H3 | test patches the route handler it claims to test |
| `test_local_api_routes.py:238` | `test_mark_executed` | H3 | test patches the route handler it claims to test |
| `test_services.py:627` | `test_run_fine_tune_service` | H3 | test patches the service function it claims to test |
| `test_services.py:635` | `test_rollback_model_service` | H3 | test patches the service function it claims to test |
| `notifications/test_email_digest_coverage_matrix.py:267` | `test_no_orphan_send_email_call_sites` | H4 | zero assertions; coverage probe only |
| `notifications/test_email_digest_coverage_matrix.py:303` | `test_event_types_emitted_match_registered` | H4 | zero assertions; consistency probe |
| `platform/test_walkforward_autofire.py:192` | `test_auto_fire_releases_lock_after_spawn` | H4 | 11 substantive stmts, no assertions (lock-release smoke test) |
| `test_dpo_pipeline.py:11` | `test_db` | H4 | 6 substantive stmts, no assertions (DB setup smoke) |
| `test_validation.py:11` | `test_db` | H4 | 6 substantive stmts, no assertions (DB setup smoke) |

Full other-area list (131 entries) available in `tmp/scan_results.json` field `candidates`
filtered by `area == "other"`.

---

## 5. Pass B Input Contract

T28 (Pass B) consumes this document. For each candidate in the table:

1. Navigate to `file:line` (the test function start line)
2. Identify the SUT being tested (from function name + `@patch` targets + docstring)
3. Delete or stub the SUT implementation to an unconditional `return None` / `return {}`
4. Run the specific test: `pytest <file>::<test_name> -x`
5. If it **still passes** after the SUT is disabled, the test is **CONFIRMED vacuous**
6. Restore the SUT; mark candidate as CONFIRMED or FALSE_POSITIVE

Only CONFIRMED vacuous tests are deleted in T29.

**Expected confirmation rates by heuristic (pre-empirical estimate):**

| Heuristic | Expected Confirm Rate | Reasoning |
|-----------|-----------------------|-----------|
| H1 (mock-only) | ~60-80% | Mock call-count tests may still catch missing calls; depends on test design |
| H2 (high ratio) | ~40-60% | Patches may cover multiple code paths; some real assertions remain |
| H3 (SUT self-patch) | ~80-90% | Patching the SUT itself means the test exercises the stub |
| H4 (no assertion) | ~30-50% | Many are "does-not-raise" — legitimate if the SUT crashes without the test |

---

## 6. Notes and Caveats

1. **data_collection clean (0 candidates):** The 22 data_collection test files use real
   SUT assertions throughout. A positive signal.

2. **tools clean (0 candidates):** tools/ test files consistently use real assertion patterns.

3. **H4 "does-not-raise" pattern:** Many H4 candidates test implicit no-raise semantics
   (e.g., `test_disconnect_safe_when_not_connected`, `test_kill_switch_source_allowlist.py:83-93`).
   These are architecturally weaker (a `return` stub would pass them) but may be intentional.
   Pass B must verify each one carefully.

4. **test_watch_handlers.py cluster (21 H1 entries):** The watch-handler timing tests check
   only that a downstream function was called — not what it was called with, nor what it returned.
   If the entire handler were deleted, `mock.assert_called_once()` would fail — so these may not
   be vacuous in the strictest sense. Pass B must test each one.

5. **evaluation/ backtester H2 cluster:** `test_backtester.py` and `test_shadow.py` have 11-13
   `@patch` decorators per test with 1-2 assertions each. These are functionally integration tests
   that heavily mock the data layer. The SUT logic itself runs, but coverage of that logic is thin.

6. **Overlap with kin tasks:** Tasks #10, #11, #20 (rewrite test_local_routes.py, test_status.py,
   and cloud_app tests) overlap with some H1/H3 findings here. Pass B should cross-reference.

7. **Scanner version:** `tmp/vacuous_scanner.py` commit SHA is recorded in the commit message.
   To reproduce: `git show <sha>:tmp/vacuous_scanner.py | python - > scan.json`.
