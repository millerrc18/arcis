# Sprint 5 Closeout — Implementation Plan

**Generated:** 2026-05-12 from `docs/audits/2026-05-12-sprint-5-closeout-plan/specs/2026-05-12-sprint-5-closeout-plan-design.md`

**Tasks:** 16  |  **Execution batches:** 10

## Sequencing notes

v2 revision. Wave C precedes Wave D per glidepath. Batches: (1) Independent small tasks — #54 wire, #47 audit doc, #100 scanner, #15 stale-base CI, Wave E disposition + inline stale-text fixes (all zero-or-low-risk independent edits). (2) Council errors (#68 — independent of #56 schema), test speedup (#86), PG provisioning (#87). (3) #56+#96 schema task (must precede #45 because the platform_events TableDef is C4's write target). (4) #45 drift detector (depends on schema in Task 2 + typed-error pattern in Task 3; first watch.py hook). (5) D1 policy.py (depends on #68 + on #45 having added the manual_intervention_drift event_map entry so config validation works). (6) D2 digest_queue.py + watch.py rebases on #45's watch.py edit. (7) D3 safe_send retry + severity audit + schema column adds (depends on D1 policy + D2 digest_queue). (8) D4 html-escape siblings + conftest isolation (depends on D3 safe_send wiring). (9) D5 alert silence (depends on D2's watch.py hook landing + D3 safe_send semantics + Task 11's notifications_digest_queue table for UNION read). (10) Sprint Close aggregates everything. Sequential constraint on src/scheduler/watch.py: tasks 4, 11, 14 edit the same file — each rebases on prior. PM enforces serial dispatch via §6.5.1 detection mechanism (git fetch + gh pr list before dispatch + worktree-glob check). All other tasks within a batch can run worktree-parallel.

## Execution batches

- **Batch 1**: tasks [1, 5, 6, 7, 15]
- **Batch 2**: tasks [3, 8, 9]
- **Batch 3**: tasks [2]
- **Batch 4**: tasks [4]
- **Batch 5**: tasks [10]
- **Batch 6**: tasks [11]
- **Batch 7**: tasks [12]
- **Batch 8**: tasks [13]
- **Batch 9**: tasks [14]
- **Batch 10**: tasks [16]

## Task details

### Task 1 — Wave C #54 — Wire dates+directions to promotion_gate KPI

- **Complexity:** ?
- **Depends on:** []
- **Scope fence:** Do NOT modify kpis_compute.py — its signature is already correct. Do NOT modify promotion_gate.py. Do NOT change schema. Do NOT add a strategy_id filter (that's Task 2).
- **Files in scope:** ['src/api/cloud_routes/kpis.py', 'tests/api/test_kpis.py']
- **Files read-only:** ['src/api/cloud_routes/kpis_compute.py', 'src/methods/promotion_gate.py', 'src/schema/registry.py']
- **Test strategy:** +3 tests in tests/api/test_kpis.py: (1) wired_call_passes_dates_and_directions, (2) mc_vote_no_longer_abstains_with_directions, (3) response_shape_regression. Pre-merge sanity: print votes_passed delta to PR body.
- **Reviewer dispatch:** ['QA']

Modify src/api/cloud_routes/kpis.py:128 to extract `dates` and `directions` arrays from the `instrumented` trade list and pass them to `_compute_promotion_gate_kpi(n_trades, returns, dates=dates, directions=directions)`. The kpis_compute.py signature at line 364 already accepts both as optional kwargs (Sprint 2 T3 forward-compat). Pre-merge: run promotion_gate against current closed trades and include the votes_passed delta in PR body — wiring directions will flip MC permutation vote from ABSTAIN to real PASS/FAIL, a SEMANTIC change. Add 3 tests: wired-call passes correct shape, MC vote no longer abstains given real directions, snapshot/regression on response shape.

### Task 2 — Wave C #56 + #96 — shadow_trades.strategy_id + platform_events TableDef

- **Complexity:** ?
- **Depends on:** [1]
- **Scope fence:** Do NOT backfill existing rows. Do NOT modify promotion_gate.py. Do NOT write to platform_events from this task — only declare the TableDef. Do NOT issue inline `VALIDATE CONSTRAINT` — that's operator-deferred.
- **Files in scope:** ['src/schema/registry.py', 'src/api/cloud_routes/kpis_compute.py', 'scripts/render_migrate.py', 'tests/test_schema.py']
- **Files read-only:** ['src/shadow_trading/executor.py', 'src/shadow_trading/models.py', 'src/monitoring/alert_silence.py']
- **Test strategy:** +6 tests: schema discipline (strategy_id column present), schema discipline (platform_events table present with all 6 columns), FK enforcement at DB layer, kpis_compute filter behavior with strategy_id, kpis_compute backward-compat with strategy_id=None, NOT VALID FK syntax verification in render_migrate output. Include `validate-schema` + `render_migrate.py` outputs in PR body.
- **Reviewer dispatch:** ['QA', 'Security']

Step 1: Grep src/ to confirm `strategy_registry` TableDef exists and its PK column name. If absent, fall back to ColumnDef-only for strategy_id (no FK) and note in PR body. Step 2: Add `ColumnDef('strategy_id', 'TEXT', nullable=True)` and `ForeignKeyDef('strategy_id', 'strategy_registry', 'strategy_id', initially_deferred=True)` to TABLES['shadow_trades'] in src/schema/registry.py. Step 3: Add `platform_events` TableDef per spec §3.1 (id, event_type, severity, payload_json, source, created_at + indexes) — used as forensic-trail write target by D5 alert_silence AND C4 drift detector. Step 4: Extend `_fetch_closed_trades` in src/api/cloud_routes/kpis_compute.py with optional `strategy_id` filter param. Step 5: Update scripts/render_migrate.py to emit FK constraint as `ADD CONSTRAINT ... NOT VALID` (avoids AccessExclusiveLock on shadow_trades during validation). Step 6: Run `python -m src.main validate-schema --fix` and `python scripts/render_migrate.py`; include BOTH outputs in PR body per CLAUDE.md. Document FK validation-timing in PR body (operator runs deferred VALIDATE off-hours).

### Task 3 — Wave C #68 — Council typed exception hierarchy + agent_data.py refactor (28 except blocks)

- **Complexity:** ?
- **Depends on:** []
- **Scope fence:** Do NOT refactor engine.py except-blocks. Do NOT refactor value_tracker.py except-blocks. Do NOT modify aggregation.py raise site. Do NOT change the public surface of agent_data.py functions.
- **Files in scope:** ['src/council/errors.py', 'src/council/agent_data.py', 'tests/council/test_typed_errors.py']
- **Files read-only:** ['src/council/aggregation.py', 'src/council/engine.py', 'src/council/value_tracker.py']
- **Test strategy:** +8 tests in tests/council/test_typed_errors.py: hierarchy structure, each typed exception raises/catches correctly, agent_data.py SQLite path surfaces CouncilAgentDataError, JSON parse path surfaces CouncilParseError, Ollama HTTP path surfaces CouncilProviderError, `except CouncilError` catches all subclasses, back-compat CouncilUnavailableError still IS-A RuntimeError, no bare `except Exception` left in agent_data.py (AST scan asserts 0 occurrences).
- **Reviewer dispatch:** ['QA']

Extend src/council/errors.py with CouncilParseError, CouncilTimeoutError, CouncilAgentDataError, CouncilProviderError (each inheriting CouncilError). Keep existing CouncilUnavailableError(RuntimeError, CouncilError) for back-compat. Refactor the 28 `except Exception as exc` blocks in src/council/agent_data.py (corrected from v1 '30+' — actual grep count is 28): triage each block by error source (SQLite/psycopg → CouncilAgentDataError, json.JSONDecodeError → CouncilParseError, requests.RequestException → CouncilProviderError). PR body must disclose: 'This may surface previously-swallowed bugs; canary deploy via watch-loop restart with eyes-on for 1h.' Engine.py + value_tracker.py except-blocks are EXPLICITLY DEFERRED to post-sprint.

### Task 4 — Wave C #45 — Manual intervention drift detector + new src/monitoring/ package + watch loop hook

- **Complexity:** ?
- **Depends on:** [2, 3]
- **Scope fence:** Do NOT modify alpaca_adapter.py or reconcile.py. Do NOT add the drift alert to the policy.py or digest_queue.py paths (Wave D handles those). Do NOT add a dashboard widget yet (operator-guide reference only). Do NOT place modules in src/diagnostics/ — operational alerting goes in src/monitoring/ per Decision 23.
- **Files in scope:** ['src/monitoring/manual_intervention_drift.py', 'src/notifications/telegram.py', 'src/scheduler/watch.py', 'tests/monitoring/test_manual_intervention_drift.py']
- **Files read-only:** ['src/shadow_trading/reconcile.py', 'src/shadow_trading/alpaca_adapter.py', 'src/schema/registry.py', 'docs/operator-guide.md']
- **Test strategy:** +6 tests in tests/monitoring/test_manual_intervention_drift.py: detector with mocked broker/db, threshold boundary (29 min no-alert, 31 min alert), state persistence across calls, alert dedup within 24h, no-alert-on-broker-outage (don't alert on alert path), platform_events row written on finding. +1 AST guardrail in tests/monitoring/test_drift_detector_no_recursion.py (no safe_send call from inside the detector's own alert path). Also create src/monitoring/__init__.py + src/monitoring/errors.py + tests/monitoring/__init__.py — minimal package scaffolding.
- **Reviewer dispatch:** ['QA', 'Security']

Create the new `src/monitoring/` package: src/monitoring/__init__.py (with docstring 'Operational health detectors. Distinct from src/diagnostics/ statistical methodology.'), src/monitoring/errors.py (MonitoringDataError). Create src/monitoring/manual_intervention_drift.py with `detect_drift(broker_positions, db_positions, threshold_minutes=30, state_path, conn) -> list[DriftFinding]`. Detector writes a `platform_events` row (source='drift_detector', severity='high') for forensic trail when emitting a finding. Add `notify_manual_intervention_drift` to src/notifications/telegram.py event_map at module-import-time (top-level dict literal). Wire a 30-minute periodic tick in src/scheduler/watch.py that calls the detector and emits via safe_send (with literal severity='high' kwarg). Add operator-guide section 'Drift detection'. THIS TASK IS THE FIRST OF THREE SEQUENTIAL EDITS to src/scheduler/watch.py (followed by tasks 11 and 14). Per §6.5.1, PM enforces serial dispatch via Glob over worktree branches.

### Task 5 — Wave C #47 — Telegram-email-sweep audit triage disposition doc

- **Complexity:** ?
- **Depends on:** []
- **Scope fence:** Do NOT modify any source. Do NOT modify existing audit files. Disposition doc only.
- **Files in scope:** ['docs/audits/2026-05-07-telegram-email-sweep/triage-disposition.md']
- **Files read-only:** ['docs/audits/2026-05-07-telegram-email-sweep/summary.md', 'docs/audits/2026-05-07-telegram-email-sweep/recommendations.md', 'docs/audits/2026-05-07-telegram-email-sweep/cross-cutting.md', 'tests/email/test_notifier.py', 'tests/notifications/test_telegram_send_path.py', 'docs/operator-guide.md']
- **Test strategy:** No new tests. Reviewer verifies disposition doc enumerates ALL 50 findings with explicit status.
- **Reviewer dispatch:** ['QA']

Create docs/audits/2026-05-07-telegram-email-sweep/triage-disposition.md cataloging all 50 findings (C1-C17 critical + I-series important + CC1-CC6 cross-cutting + Nit) with status per finding: `closed-by-PR-X | scoped-into-Wave-D | follow-up-issue-N | accepted-risk`. Verify Group B (test_notifier.py coverage) via Glob; if gap remains, log as follow-up. Verify Group F (operator-guide §X troubleshooting) via Grep; if absent, log as follow-up. Zero source changes. Pure documentation task.

### Task 6 — Wave C #100 — AST scanner extension for [r[N] for r in fetchall()] pattern + scripts/ coverage

- **Complexity:** ?
- **Depends on:** []
- **Scope fence:** Do NOT fix individual src/ violations in this task — scanner only flags. If pre-existing violations found, allowlist them with rationale.
- **Files in scope:** ['tests/test_no_fetchone_int_index_in_pg_unsafe_files.py']
- **Files read-only:** ['src/scheduler/watch.py', 'src/shadow_trading/executor.py', 'scripts/']
- **Test strategy:** +3 tests: new scanner self-test on synthetic ListComp violation, scripts/ scanner self-test, integration scanning over src/ + scripts/ confirms zero violations (or populated allowlist).
- **Reviewer dispatch:** ['QA']

Extend tests/test_no_fetchone_int_index_in_pg_unsafe_files.py with a new test function `test_no_fetchall_list_comp_int_index_in_pg_unsafe_files` matching `ListComp(elt=Subscript(value=Name, slice=Constant(int)), generators=[comprehension(iter=Call(func=Attribute(attr='fetchall')))])`. Add a sibling scanner that walks scripts/ root. Include self-test that catches synthetic violation. Pre-merge: run scanner against scripts/ with allowlist=[] and report violation count; if >5, populate allowlist + document in known-pre-existing-failures.md; if ≤5, fix in-PR.

### Task 7 — Wave F #15 — Server-side stale-base CI check

- **Complexity:** ?
- **Depends on:** []
- **Scope fence:** Do NOT modify pg-tests.yml. Do NOT modify the client-side pre-push hook. Do NOT add bypass mechanisms beyond `git push --no-verify` (which is git's standard).
- **Files in scope:** ['.github/workflows/stale-base-check.yml', 'tests/workflows/test_stale_base_check.py', 'docs/operator-guide.md']
- **Files read-only:** ['scripts/hooks/pre-push', '.github/workflows/pg-tests.yml']
- **Test strategy:** +2 tests in tests/workflows/test_stale_base_check.py: YAML parses + lints, step structure includes (checkout fetch-depth 0, merge-base computation, conditional failure step).
- **Reviewer dispatch:** ['QA']

Create .github/workflows/stale-base-check.yml triggered on pull_request.synchronize. Job: actions/checkout@v4 with fetch-depth: 0; compute `git merge-base origin/main HEAD`; compare to `origin/main`'s HEAD SHA; set check status to failure if behind. Add operator-guide section 'CI checks' explaining the workflow and the `git push --no-verify` emergency bypass. Add tests/workflows/test_stale_base_check.py: YAML lints, step structure assertion.

### Task 8 — Wave F #86 — Test suite speedup via session-scoped shared venv

- **Complexity:** ?
- **Depends on:** []
- **Scope fence:** Do NOT remove any existing test cases. Do NOT change what each case asserts. Do NOT modify requirements-cloud.txt. Do NOT add session-scope fixtures unrelated to this restructure.
- **Files in scope:** ['tests/test_cloud_requirements_imports.py', 'tests/conftest.py']
- **Files read-only:** ['scripts/check_cloud_deploy_imports.py', 'requirements-cloud.txt']
- **Test strategy:** +0 new tests. Verify pre-vs-post test count unchanged. Verify runtime via `python -m pytest tests/test_cloud_requirements_imports.py -v --durations=20` before + after; report delta in PR body.
- **Reviewer dispatch:** ['QA', 'Performance']

Read tests/test_cloud_requirements_imports.py fully (line 1 to end) as first step. Restructure from per-test fresh-venv pattern to session-scoped shared-venv: ONE pip install of requirements-cloud.txt at session start, then per-test imports via subprocess against the shared venv path. Use pytest.fixture(scope='session') for venv creation. Target: drop full-sweep runtime by ~3x. Preserve test count. Add docstring noting the restructure rationale.

### Task 9 — Wave F #87 — Local PG provisioning via docker-compose

- **Complexity:** ?
- **Depends on:** []
- **Scope fence:** Do NOT un-hardcode TEST_DATABASE_URL in files beyond the 3 listed. Do NOT change conftest.py beyond docker hooks + the 3 fixture references. Do NOT change PG version from 16-alpine without operator approval.
- **Files in scope:** ['docker-compose.test.yml', 'tests/conftest.py', '.github/workflows/pg-tests.yml', 'docs/operator-guide.md']
- **Files read-only:** ['tests/api/test_status.py', 'tests/test_cloud_app.py', 'tests/test_shadow_desk_filter.py']
- **Test strategy:** +0 new tests directly. Expect +30-50 tests by un-SKIPping previously-skipped postgres parametrized variants. Verify local `pytest tests/` provisions PG, the 3 un-hardcoded fixtures use the provisioned URL, and CI green after pg-tests.yml step removal.
- **Reviewer dispatch:** ['QA', 'Security']

Create docker-compose.test.yml at repo root (postgres:16-alpine on localhost:5433, configurable via TEST_PG_PORT env var, default user/pass test/test, db halcyon). Add pytest_sessionstart/pytest_sessionfinish hooks in tests/conftest.py that run `docker compose -f docker-compose.test.yml up -d` and `docker compose down -v` respectively. Graceful SKIP if docker not installed. Un-hardcode TEST_DATABASE_URL in tests/api/test_status.py:18, tests/test_cloud_app.py:15, tests/test_shadow_desk_filter.py:25. Drop 'Create test/test PG role' step from .github/workflows/pg-tests.yml.

### Task 10 — Wave D D1 — policy.py + YAML config schema + truth table tests + event_map import-order test

- **Complexity:** ?
- **Depends on:** [3, 4]
- **Scope fence:** Do NOT modify safe_send yet (Task 12). Do NOT create a parallel router.py — policy is pure-function gate. Do NOT add YAML !include or other tag interpolation. Do NOT make event_map dynamically extensible. Do NOT add bypass_severity config knob (removed per Decision 20).
- **Files in scope:** ['src/notifications/policy.py', 'tests/notifications/test_policy.py', 'tests/notifications/test_policy_purity.py', 'tests/notifications/test_event_map_load_order.py', 'config/settings.example.yaml']
- **Files read-only:** ['src/notifications/telegram.py', 'src/main.py']
- **Test strategy:** +14 tests in tests/notifications/test_policy.py: severity high/critical always sends (4 explicit cases — regardless of quiet hours/mute list/digest_low/quiet_digest), mute_event_types muting, quiet hours window (start<end and start>end cross-midnight), digest_low buffering for severity=low only, default routing fallback, channel resolution (telegram/email/both/none), config validation rejects unknown event_type, config validation rejects bypass_severity key (removed in v2), time string parse error, cadence out-of-range, backoff_seconds length mismatch. +1 AST guardrail in test_policy_purity.py asserts policy.py imports no I/O modules. +1 integration test in test_event_map_load_order.py that imports src.main then validates sample config (MIN7).
- **Reviewer dispatch:** ['QA', 'Security']

Create src/notifications/policy.py with pure-function `should_dispatch(event_type, severity, now_et, config) -> PolicyDecision` per spec §4.1. Decision rule precedence (FIRST MATCH WINS): (1) severity in {high, critical} → always send (rule #1 IS the bypass; no `bypass_severity` config knob per Decision 20); (2) event_type in mute_event_types → mute; (3) within quiet_hours → mute (or digest if quiet_digest=True); (4) severity=low AND digest_low=True → digest; (5) default routing. Extend config/settings.example.yaml with `notifications:` section per spec §4.7 (NO bypass_severity key). Implement `_load_notifications_config` in src/notifications/telegram.py with validation: unknown event_type raises NotificationsConfigError at startup; time strings parse as HH:MM; cadence clamped to [1,1440]; retry attempts clamped to [1,10]; backoff_seconds len equals attempts. Add operator-guide section 'Notifications routing' (incl. NSSM AppEnvironmentExtra registry path). Create tests/notifications/test_event_map_load_order.py (MIN7) that imports src.main then loads a sample config referencing manual_intervention_drift + alert_silence event types and asserts validation passes.

### Task 11 — Wave D D2 — digest_queue.py + schema + flush-then-fail recovery + watch loop flush hook (rebases on Task 4)

- **Complexity:** ?
- **Depends on:** [4, 10]
- **Scope fence:** Do NOT enqueue from anywhere other than safe_send (Task 12 wires that). Do NOT modify policy.py. Do NOT add cron-style scheduling — use the existing watch loop tick cadence. Do NOT skip the mark_flush_failed path — the abandoned-row state is the M5 contract.
- **Files in scope:** ['src/notifications/digest_queue.py', 'tests/notifications/test_digest_queue.py', 'tests/notifications/test_digest_queue_atomicity.py', 'src/schema/registry.py']
- **Files read-only:** ['src/email/digest_builder.py', 'src/notifications/telegram.py', 'src/scheduler/watch.py']
- **Test strategy:** +9 tests in tests/notifications/test_digest_queue.py: enqueue writes row with NULL flushed_at, flush_due returns only rows past cadence bucket AND flush_attempts<3, flush_due marks flushed_at atomically (no double-flush via concurrent call simulation), schema discipline (table + flush_attempts col), cadence boundary precision, idempotence on re-flush, mark_flush_failed resets flushed_at + increments flush_attempts, flush_attempts cap at 3 sets policy_decision='abandoned', abandoned rows excluded from future flush_due. +1 AST/SQL guardrail in test_digest_queue_atomicity.py asserts flush_due uses WHERE clause `flushed_at IS NULL AND flush_attempts < 3` and mark_flush_failed sets flushed_at=NULL. NOTE: watch.py flush hook landing is deferred to align with sequential C4→D2→D5 dispatch (§6.5.1) — flush hook lands in this task's PR after Task 4 merges.
- **Reviewer dispatch:** ['QA', 'Security']

Create src/notifications/digest_queue.py with `enqueue(event_type, severity, payload, channel, conn=None) -> int`, `flush_due(now_et, config, conn=None) -> list[FlushItem]`, and `mark_flush_failed(row_id, conn=None) -> None`. flush_due query filters `WHERE flushed_at IS NULL AND flush_attempts < 3`. mark_flush_failed resets flushed_at=NULL + increments flush_attempts; on 3rd fail sets policy_decision='abandoned' (M5 resolution). Add notifications_digest_queue TableDef to src/schema/registry.py per spec §3.1 (INCLUDES flush_attempts INTEGER NOT NULL DEFAULT 0). Run validate-schema --fix + render_migrate.py; include outputs in PR body. Wire flush hook in src/scheduler/watch.py (every 5 min) — REBASES on Task 4's watch.py edits. The flush hook iterates flush_due items, calls _send_with_retry (Task 12 helper) for each, and invokes mark_flush_failed(row_id) on retry-exhaustion. Read src/email/digest_builder.py fully (line 1 to end) before designing cadence to align with existing email-side 4-digest-per-day pattern.

### Task 12 — Wave D D3 — safe_send retry (persistent counter) + severity-required audit + escalation + schema column adds

- **Complexity:** ?
- **Depends on:** [10, 11]
- **Scope fence:** Do NOT widen the network-except catch. Do NOT remove the KeyError-on-unknown-event_type security boundary. Do NOT add severity normalization — accept the canonical 4 strings only. Do NOT default ARCIS_NOTIFICATION_SOURCE to 'watch-loop' — must be 'unknown' (Decision 19). Do NOT keep the retry counter in-memory only — must persist to data/notification_retry_state.json (Decision 21).
- **Files in scope:** ['src/notifications/telegram.py', 'src/schema/registry.py', 'tests/notifications/test_safe_send_retry.py', 'tests/notifications/test_safe_send_catch_discipline.py']
- **Files read-only:** ['src/notifications/policy.py', 'src/notifications/digest_queue.py', 'src/email/notifier.py']
- **Test strategy:** +9 tests in test_safe_send_retry.py: 1-attempt success, retry-then-success, 3-fail-then-fail records status='failed', escalation after 5 consecutive failures in 10-min window writes status='escalated' + calls email_notifier, persistent counter SURVIVES simulated watch-loop restart (escalation fires correctly across restart — M4 anchor), counter resets to 0 on next success, retry sleeps don't exceed config bound, source_tag defaults to 'unknown' when ARCIS_NOTIFICATION_SOURCE env unset, severity-required raises TypeError when caller omits severity= kwarg. +1 AST guardrail in test_safe_send_catch_discipline.py asserts the network-except clause exception tuple equals exactly `(urllib3.HTTPError, requests.RequestException, socket.timeout, OSError)`. +1 separate file tests/notifications/test_safe_send_severity_required.py AST-scans every `safe_send(` call site in src/ and asserts each one passes a literal severity= kwarg (M1 anchor). Severity-audit receipt MUST appear in PR body.
- **Reviewer dispatch:** ['QA', 'Security']

Step 1: AUDIT every existing `safe_send(` call site across src/ and assign an intrinsic severity. Include the receipt table in PR body (call site → severity classification → rationale). Step 2: Make `severity` a REQUIRED keyword-only kwarg of safe_send (no default value). Update every audited call site to pass a literal severity= kwarg. Step 3: Add `severity TEXT NOT NULL DEFAULT 'medium'` + `policy_decision TEXT` + `source_tag TEXT DEFAULT 'unknown' NOT NULL` columns to notifications_sent TableDef in src/schema/registry.py (source_tag default is 'unknown' — fail-loud per Decision 19). Run validate-schema --fix + render_migrate.py. Step 4: Modify src/notifications/telegram.py: (a) insert policy gate at line 1234 between is_telegram_enabled and event_map lookup; (b) replace single-attempt send at line 1299 with `_send_with_retry` helper implementing 3 attempts with [1,5,30]s backoff; (c) implement consecutive-failure tracking PERSISTED to data/notification_retry_state.json (atomic write via tmp+os.replace) — counter survives NSSM watch-loop restart (M4); (d) 5-failures-in-10min escalation to email_notifier. Catch tuple at line 1299 MUST remain exactly `(urllib3.HTTPError, requests.RequestException, socket.timeout, OSError)`. Read source_tag from `os.environ.get('ARCIS_NOTIFICATION_SOURCE', 'unknown')` (default changed from 'watch-loop' to 'unknown' — fail-loud).

### Task 13 — Wave D D4 — HTML escape #93+#94 + #101 source-tag conftest isolation

- **Complexity:** ?
- **Depends on:** [12]
- **Scope fence:** Do NOT apply _html_escape to non-HTML send paths. Do NOT change the _html_escape implementation. Do NOT modify other notify_* functions beyond the 2 listed + any siblings discovered by grep (document each).
- **Files in scope:** ['src/notifications/telegram.py', 'tests/notifications/test_html_escape_siblings.py', 'tests/conftest.py']
- **Files read-only:** ['src/notifications/policy.py', 'tests/notifications/test_html_escape.py']
- **Test strategy:** +5 tests in test_html_escape_siblings.py: notify_regime_alert escapes regime_old/regime_new (with and without malicious `<script>` input), notify_streak_alert escapes status + ticker, sibling-search finding completeness (no remaining f-string interpolation in notify_* without escape — AST guardrail), source_tag column written correctly under pytest env (value matches 'pytest:<basename>'), _send_telegram monkeypatched under pytest (`__name__ == '_null_router'`).
- **Reviewer dispatch:** ['QA', 'Security']

Apply `_html_escape()` to regime_old/regime_new interpolation at src/notifications/telegram.py:780-796 (notify_regime_alert) per T5 pattern. Apply `_html_escape()` to risk_governor_status + each ticker in recent_str before join at src/notifications/telegram.py:805-818 (notify_streak_alert). Sibling-search: grep all `notify_*` functions for `f'...{<var>}'` style HTML interpolation; flag any uncovered sites in PR body. In tests/conftest.py: (1) set `ARCIS_NOTIFICATION_SOURCE='pytest:<worktree-basename>'` via session fixture, (2) monkeypatch `_send_telegram` to a null-router so pytest CANNOT call Telegram API, (3) clear `ARCIS_TELEGRAM_TOKEN` per-test (per #729 pattern).

### Task 14 — Wave D D5 — Alert silence detector (UNION-with-digest-queue read) + watch loop hook (rebases on Task 11)

- **Complexity:** ?
- **Depends on:** [11, 13]
- **Scope fence:** Do NOT call safe_send from within the alert_silence event's own dispatch path (no recursion). Do NOT modify is_market_open. Do NOT add the silence detector to non-market-hours paths. Do NOT place the module in src/diagnostics/ — operational alerting goes in src/monitoring/ per Decision 23.
- **Files in scope:** ['src/monitoring/alert_silence.py', 'tests/monitoring/test_alert_silence.py', 'src/notifications/telegram.py', 'src/scheduler/watch.py']
- **Files read-only:** ['src/scheduler/holidays.py', 'src/notifications/digest_queue.py', 'src/schema/registry.py']
- **Test strategy:** +5 tests in test_alert_silence.py: silence detected during market hours when no recent ok send AND no recent digest activity, no-alert outside market hours, platform_events row written on detection (source='alert_silence'), dashboard widget data shape, M3 anchor truth-table (digest_cadence=60 + alert_threshold=60 + low-only events for 90 min during market hours → returns None — no false silence because digest_queue.enqueued_at MAX is recent). Visual-verify gate: render the widget in browser before PR push.
- **Reviewer dispatch:** ['QA']

Create src/monitoring/alert_silence.py with `check_alert_silence(now_et, threshold_minutes=60, conn=None) -> AlertSilenceFinding | None`. Logic (M3 resolution): read UNION of (notifications_sent WHERE status='ok' MAX sent_at), (notifications_digest_queue WHERE flushed_at IS NOT NULL MAX flushed_at), (notifications_digest_queue WHERE enqueued_at IS NOT NULL MAX enqueued_at). During market hours (via src/scheduler/holidays.is_market_open), if MAX(union) is older than now_et - threshold, return finding + emit via safe_send(event_type='alert_silence', severity='high', ...) + write platform_events row (source='alert_silence', severity='high') for forensic trail. The enqueued_at UNION term proves watch loop is alive during digest-only quiet periods (no false-fire). Add `alert_silence` to telegram.py event_map at module-import time. Wire 5-min hook in src/scheduler/watch.py — REBASES on Task 11's watch.py edits. Add dashboard widget data endpoint (operator visibility).

### Task 15 — Wave E — Dual-GPU disposition doc + inline stale-text fixes to canonical spec

- **Complexity:** ?
- **Depends on:** []
- **Scope fence:** Do NOT touch any source files. Do NOT touch any test files. Pure-docs scope. Do NOT introduce new design concepts in the disposition doc — it's a deferral notice + canonical pointer + stale-text fix anchor.
- **Files in scope:** ['docs/audits/2026-05-12-dual-gpu-ideation/disposition.md', 'docs/audits/2026-05-12-dual-gpu-ideation/specs/2026-05-12-dual-gpu-workload-separation-design.md']
- **Files read-only:** []
- **Test strategy:** No new tests. Reviewer verifies (a) disposition doc exists + correctly states deferral rationale + links to canonical spec, (b) the 4 stale-text fixes have been applied inline to the canonical spec (grep for 'Sprint 6', '3682', 'Unsloth' returns zero in the canonical spec post-PR).
- **Reviewer dispatch:** ['QA']

Create docs/audits/2026-05-12-dual-gpu-ideation/disposition.md stating: 'Implementation deferred to first post-Sprint-5 maintenance window per operator decision 2026-05-12. Spec at docs/audits/2026-05-12-dual-gpu-ideation/specs/2026-05-12-dual-gpu-workload-separation-design.md is the canonical artifact.' APPLY the 4 stale-text fixes inline to the canonical spec in the SAME PR (per MIN5 — pure-docs scope, cheap): (1) any 'test floor 3682' references → 5350, (2) any 'Sprint 6' references → 'post-Sprint-5' or 'next-sprint', (3) any references to Unsloth training pipeline → 'Transformers + PEFT + TRL' per memory project_gpu_upgrade, (4) NUM_PARALLEL update (1→4 viable on RTX 3090). Link the disposition from docs/roadmap.md (created in Sprint Close).

### Task 16 — Sprint Close PR — CHANGELOG aggregation + version bump + tag + roadmap + canon refresh

- **Complexity:** ?
- **Depends on:** [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]
- **Scope fence:** Do NOT bump test floor without verifying actual sweep count first. Do NOT push tag before PR merges. Do NOT delete _scalar helper if scope cap exceeded — defer. Do NOT skip the §7.4.1 aggregation rules (verbatim copy, dedupe metas, task-id order, retain empty [Unreleased]).
- **Files in scope:** ['src/version.py', 'CHANGELOG.md', 'docs/roadmap.md', 'docs/operator-guide.md', 'CLAUDE.md', '.github/workflows/pg-tests.yml', 'docs/audits/known-pre-existing-failures.md', 'config/known_violations.json', 'tests/shadow_trading/test_alpaca_adapter_split.py', 'src/utils/db.py']
- **Files read-only:** ['src/api/cloud_routes/kpis.py', 'src/schema/registry.py', 'src/notifications/telegram.py']
- **Test strategy:** Verify full pytest sweep count ≥ 5350 BEFORE bumping floor. Run `git diff --check` to surface any CRLF/LF drift. Visual-verify dashboard renders cleanly. Run `python -c 'from src.version import VERSION; print(VERSION)'` to confirm new version. Tag creation post-merge: `git tag -a v0.35.0 -m 'Sprint 5 close: notifications routing + data integrity + cross-engine hardening + dev tooling'`.
- **Reviewer dispatch:** ['QA', 'Documentarian']

Final closeout PR. Steps: (1) Bump src/version.py from 'v0.34.0' to 'v0.35.0'. (2) In CHANGELOG.md, move ALL [Unreleased] entries into a new `## [v0.35.0] - 2026-05-XX — Sprint 5 close` section per §7.4.1 aggregation rule (verbatim copy-paste; deduplicate meta-entries; within-wave ordering by task-id; [Unreleased] header retained with empty body). (3) Create docs/roadmap.md per spec §7.2 template with sprint-history table + active-track pointer (incl. walk-forward FK deprecation note from §1.3) + deferred-track section. (4) Append docs/operator-guide.md section 'Sprint 5 closeout state' + 'NSSM env config' subsection. (5) Update CLAUDE.md test floor 3682→5350 with lineage paragraph per §7.3. (6) Update .github/workflows/pg-tests.yml floor 5050→5350. (7) Refresh docs/audits/known-pre-existing-failures.md by re-running full sweep and regenerating the failure table. (8) Add tests/shadow_trading/test_alpaca_adapter_split.py to config/known_violations.json with rationale 'pending post-sprint refactor (#97)'; delete the sentinel test file. (9) Cosmetic _scalar helper removal across ~30 call sites — SCOPE CAP: if >40 files would change, defer to post-sprint and note in PR body. (10) Create git tag `v0.35.0` after PR merge.

