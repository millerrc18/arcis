# Sprint 5 Closeout — Implementation Plan (v3 — C7 added)

**Generated:** 2026-05-12 from `docs/audits/2026-05-12-sprint-5-closeout-plan/specs/2026-05-12-sprint-5-closeout-plan-design.md`

**Tasks:** 26  |  **Execution batches:** 19

## Sequencing notes

v3 revision adds 10 C7 tasks (17-26) between Wave D close (Task 14) and Sprint Close (Task 16). Sprint Close (Task 16) now depends on all 1-15 + 17-26. Sequencing rationale: Batch 10 starts C7a serial chain (Task 17 = first packet_writer.py edit; Task 25 = independent analyst_collector change runs alongside). Tasks 18, 19, 20 are sequential rebases on packet_writer.py + enricher.py (single-batch each — same pattern as the C4→D2→D5 watch.py serial chain in v2). Task 20 has hard dependency on Task 2 (strategy_id FK). Tasks 21-24 are the C7b serial chain — all share packet_writer.py + enricher.py rebases. Task 26 is the matrix scanner — runs last after C7b chain merged so it asserts coverage against the actual state. PM enforces serial dispatch for the packet_writer.py + enricher.py chain via §6.5.1 detection mechanism (same as watch.py: git fetch + gh pr list + worktree-glob check). All other tasks within a batch can run worktree-parallel. Task 16 (Sprint Close) updates depends_on to [1-15, 17-26] (Task 25 independent but still needs Sprint Close to aggregate). Projected final test floor moves 5350→5400 (v2 was 5350; +40 C7 tests pushes projected median to 5450-5500; 5400 keeps 50-test conservative buffer). Sprint Close updates pg-tests.yml floor + CLAUDE.md to 5400 (not 5350).

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
- **Batch 10**: tasks [17, 25]
- **Batch 11**: tasks [18]
- **Batch 12**: tasks [19]
- **Batch 13**: tasks [20]
- **Batch 14**: tasks [21]
- **Batch 15**: tasks [22]
- **Batch 16**: tasks [23]
- **Batch 17**: tasks [24]
- **Batch 18**: tasks [26]
- **Batch 19**: tasks [16]

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

### Task 17 — Wave C7a.1 — COUNCIL CONSENSUS packet section

- **Complexity:** ?
- **Depends on:** []
- **Scope fence:** Do NOT modify _build_feature_prompt sections 1-12. Do NOT touch C7b plan-gating logic (this is Tier-1, plan-independent). Do NOT call safe_send. Do NOT modify council_votes or council_sessions schema. Do NOT add a Finnhub call. FIRST of the C7a serial chain — subsequent tasks 18-20 rebase on this.
- **Files in scope:** ['src/llm/packet_writer.py', 'src/data_enrichment/enricher.py', 'tests/llm/test_packet_council_consensus.py']
- **Files read-only:** ['src/schema/registry.py']
- **Test strategy:** +4 tests in test_packet_council_consensus.py: (1) per-pillar read populates 5 vote fields, (2) prompt rendering produces COUNCIL CONSENSUS section with 5 rows + confidence, (3) missing-session fallback renders empty-state message, (4) stale-session (>3d) appends [STALE] marker. Read-only joins on council_votes + council_sessions; tests fixture an in-memory DB with sample rows.
- **Reviewer dispatch:** []

Add `=== COUNCIL CONSENSUS ===` section to `_build_feature_prompt` in `src/llm/packet_writer.py` at index 13 (after CROSS-ASSET CONTEXT). Read latest non-stale `council_sessions` row via `src/data_enrichment/enricher.py`; join `council_votes` per-pillar (macro/strategic/tactical/innovation/risk). Populate new enricher feature-dict fields per spec §4.9: `council_macro_vote`, `council_strategic_vote`, `council_tactical_vote`, `council_innovation_vote`, `council_risk_vote`, `council_session_id`, `council_consensus_score`, `council_session_age_days`. Render section as 5-row compact table per spec §X.1.1. Missing-session fallback: section renders `(No recent council session)`. Stale (>3d) fallback: append `[STALE]`. THIS TASK IS THE FIRST OF FOUR SEQUENTIAL EDITS to packet_writer.py + enricher.py (Tasks 17→18→19→20). Per §6.5.1 detection mechanism, PM enforces serial dispatch via Glob over worktree branches.

### Task 18 — Wave C7a.2 — HISTORICAL CREDIBILITY packet section

- **Complexity:** ?
- **Depends on:** [17]
- **Scope fence:** Do NOT modify walkforward_results schema. Do NOT modify promotion_gate.py logic. Do NOT add Finnhub calls. Rebase on Task 17.
- **Files in scope:** ['src/llm/packet_writer.py', 'src/data_enrichment/enricher.py', 'tests/llm/test_packet_historical_credibility.py']
- **Files read-only:** ['src/schema/registry.py', 'src/methods/promotion_gate.py']
- **Test strategy:** +3 tests: walkforward read with setup_class match, PSR/CPCV vote-count rendering, no-data fallback. Fixture walkforward_results rows in test DB.
- **Reviewer dispatch:** []

Add `=== HISTORICAL CREDIBILITY ===` section to `_build_feature_prompt` at index 14. Enricher reads `walkforward_results` for matching `setup_class` (and ticker+strategy if FK lands). Populate `setup_walkforward_credibility` (PSR/CPCV vote-count), `setup_psr_pass`, `setup_cpcv_pass`, `setup_walkforward_n_votes`. Render as numeric credibility prior + per-method pass/fail per spec §X.1.2. No-match fallback: `(No walk-forward history for this setup class)`. REBASES on Task 17's packet_writer.py + enricher.py edits.

### Task 19 — Wave C7a.3 — RECENT ATTRIBUTION packet section

- **Complexity:** ?
- **Depends on:** [18]
- **Scope fence:** Do NOT modify attribution_trades schema. Do NOT add Finnhub calls. Do NOT compute against unrealized PnL — closed trades only. Rebase on Task 18.
- **Files in scope:** ['src/llm/packet_writer.py', 'src/data_enrichment/enricher.py', 'tests/llm/test_packet_recent_attribution.py']
- **Files read-only:** ['src/schema/registry.py']
- **Test strategy:** +3 tests: 30d window read, similar-ticker sector join, no-recent-trades fallback. Fixture attribution_trades rows with mix of inside/outside window.
- **Reviewer dispatch:** []

Add `=== RECENT ATTRIBUTION ===` section at index 15. Enricher reads `attribution_trades` last 30 days (default; configurable via `data_enrichment.attribution_window_days`). Computes setup-class W/L rate + ticker-specific PnL + similar-ticker (sector-match) PnL. Populates `recent_setup_win_rate`, `recent_ticker_pnl`, `recent_similar_pnl_30d`. Renders per spec §X.1.3. No-recent-trades fallback message. REBASES on Task 18.

### Task 20 — Wave C7a.4 — STRATEGY CONTEXT header section

- **Complexity:** ?
- **Depends on:** [2, 19]
- **Scope fence:** Do NOT modify strategy_registry schema. Do NOT modify shadow_trades schema (Task 2 already did). Do NOT add a Finnhub call. Rebase on Task 19. If Task 2 scoped-reduced FK, document degradation in PR body.
- **Files in scope:** ['src/llm/packet_writer.py', 'src/data_enrichment/enricher.py', 'tests/llm/test_packet_strategy_context.py']
- **Files read-only:** ['src/schema/registry.py']
- **Test strategy:** +3 tests: strategy_id FK join populates header, demoted/abstain rendering, NULL-strategy_id fallback (legacy trade). Fixture strategy_registry + shadow_trades rows.
- **Reviewer dispatch:** []

Add `=== STRATEGY CONTEXT ===` as a header preamble (between DATA CONTEXT and TECHNICAL DATA) in `_build_feature_prompt`. Enricher reads `strategy_registry` via newly-added `strategy_id` FK on `shadow_trades` from Task 2 (#56). Populates `strategy_id`, `strategy_status` (active|shadow|abstain|demoted), `strategy_parent_name`. Renders per spec §X.1.4. NULL-strategy_id fallback (legacy trades): `Strategy: (unassigned — legacy trade)`. REBASES on Task 19. **HARD DEPENDENCY on Task 2** — if Task 2 scope-reduced to ColumnDef-only (no FK), C7a.4 must use best-effort lookup + fallback; PR body must disclose the degradation.

### Task 21 — Wave C7b.1 — INSTITUTIONAL FLOW collector + section (plan-gated)

- **Complexity:** ?
- **Depends on:** [20]
- **Scope fence:** Do NOT bypass finnhub_plan_supports gate. Do NOT add packet section that renders even partially when plan does not support — section must be ABSENT (Decision 30). Do NOT modify enricher.py beyond institutional_* feature fields (Task 22 picks up next). Do NOT add the DATA CONTEXT header trigger here (composite Tasks 22-24 collectively close the trigger). FIRST of C7b serial chain.
- **Files in scope:** ['src/data_collection/institutional_ownership_collector.py', 'src/schema/registry.py', 'src/llm/packet_writer.py', 'tests/data_collection/test_institutional_ownership_collector.py']
- **Files read-only:** ['src/data_enrichment/finnhub_plan.py', 'src/data_collection/insider_collector.py', 'src/scheduler/watch.py']
- **Test strategy:** +5 tests: (1) plan=fundamental-1 → API call made + row written + UPSERT idempotent, (2) plan=free → NO API call (mock-the-finnhub-client + assert_not_called) + collector returns None, (3) schema discipline (institutional_holdings table + columns + index), (4) packet section renders when plan supports + data present, (5) packet section completely absent when plan=free. Run validate-schema --fix + render_migrate.py; include outputs in PR body.
- **Reviewer dispatch:** []

Create `src/data_collection/institutional_ownership_collector.py` with `collect_institutional_ownership(ticker, config)` per spec §4.10. Gate at function entry on `finnhub_plan_supports('institutional_ownership', config)` — return None + INFO log when plan does not support. Add `institutional_holdings` TableDef per spec §3.1c. Add INSTITUTIONAL FLOW packet section at index 4.5 (between SECTOR RELATIVE and FUNDAMENTAL SNAPSHOT) with three render states: plan supports + data → render with age-days; plan supports + no data → `(No data yet — collector pending)`; plan does not support → section absent. Populate enricher feature-dict fields per spec §4.9. Wire 1-line nightly collector tick in `src/scheduler/watch.py` (plan-gated; no-op when plan=free). FIRST of C7b serial chain — subsequent tasks 22-24 rebase on packet_writer.py + enricher.py edits.

### Task 22 — Wave C7b.2 — filings_sentiment collector + MATERIAL EVENTS section (plan-gated)

- **Complexity:** ?
- **Depends on:** [21]
- **Scope fence:** Do NOT touch edgar_filings or edgar_collector.py — filings_sentiment is a distinct retrieval cadence and table (Decision 27). Do NOT inline-call the collector from runtime — collector is overnight/nightly only. Rebase on Task 21.
- **Files in scope:** ['src/data_collection/filings_sentiment_collector.py', 'src/schema/registry.py', 'src/llm/packet_writer.py', 'src/data_enrichment/enricher.py']
- **Files read-only:** ['src/data_enrichment/finnhub_plan.py', 'src/data_collection/institutional_ownership_collector.py']
- **Test strategy:** +5 tests: plan=fundamental-1 API call + row, plan=free no-API + None, schema discipline (filings_sentiment table), packet sub-block render when plan supports, sub-block omits when plan does not. Test file `tests/data_collection/test_filings_sentiment_collector.py`.
- **Reviewer dispatch:** []

Create `src/data_collection/filings_sentiment_collector.py` per spec §4.11. Plan-gated on `'filings_sentiment'`. Add `filings_sentiment` TableDef per spec §3.1c. Add `=== MATERIAL EVENTS ===` packet section at index 7.5 (between RECENT NEWS and MACRO CONTEXT) — this task seeds the section with filings_sentiment sub-block; Task 23 (press_releases) adds the second sub-block. Composition rule: if neither sub-block has plan-support, section omits entirely; if only one, section renders with only that sub-block. Populate `filing_sentiment_score`, `filing_sentiment_label`, `latest_filing_type`, `latest_filing_age_days` in enricher. Wire nightly tick in watch.py. REBASES on Task 21.

### Task 23 — Wave C7b.3 — press_releases collector + MATERIAL EVENTS section (plan-gated)

- **Complexity:** ?
- **Depends on:** [22]
- **Scope fence:** Do NOT route press releases through the existing RECENT NEWS pipeline — they belong in MATERIAL EVENTS (distinct catalyst category, Decision 27). Do NOT modify news collectors. Rebase on Task 22.
- **Files in scope:** ['src/data_collection/press_releases_collector.py', 'src/schema/registry.py', 'src/llm/packet_writer.py', 'src/data_enrichment/enricher.py']
- **Files read-only:** ['src/data_enrichment/finnhub_plan.py']
- **Test strategy:** +5 tests: plan=fundamental-1 + plan=free pair, schema, packet sub-block render + omit. Test file `tests/data_collection/test_press_releases_collector.py`. MATERIAL EVENTS section integration test: when only press_releases supported (filings_sentiment NOT supported) → section renders with only press-releases sub-block.
- **Reviewer dispatch:** []

Create `src/data_collection/press_releases_collector.py` per spec §4.12. Plan-gated on `'press_releases'`. Add `press_releases` TableDef per spec §3.1c. Extend MATERIAL EVENTS section with press-releases sub-block (per spec §X.2.2). Populate `press_release_count_7d`, `latest_press_release_headline`, `latest_press_release_age_days` in enricher. Wire nightly tick in watch.py. REBASES on Task 22.

### Task 24 — Wave C7b.4 — stock_financials runtime promotion (plan-gated) + DATA CONTEXT header

- **Complexity:** ?
- **Depends on:** [23]
- **Scope fence:** Do NOT call Finnhub API at runtime — read existing JSON sink only. Do NOT modify scripts/finnhub_fundamental_export.py. Do NOT add a new TableDef — JSON sink is the storage. Do NOT trigger DATA CONTEXT header on Tier-1 section absence — Tier-1 is plan-independent (Decision 32). Rebase on Task 23.
- **Files in scope:** ['src/data_enrichment/financials.py', 'src/llm/packet_writer.py', 'src/data_enrichment/enricher.py', 'tests/data_enrichment/test_financials.py']
- **Files read-only:** ['scripts/finnhub_fundamental_export.py', 'src/data_enrichment/finnhub_plan.py']
- **Test strategy:** +4 tests for financials.py: plan=fundamental-1 reads JSON + enriches, plan=free returns None (last-known fallback preserved), FUNDAMENTAL SNAPSHOT in-place enrichment with live fields, snapshot age-days computed. +3 tests in NEW `tests/llm/test_data_context_header_trigger.py`: header omitted when all Tier-2 sections present, header present when ≥1 omits, header content lists exact omitted section names.
- **Reviewer dispatch:** []

Create `src/data_enrichment/financials.py` per spec §4.13 — promotes `scripts/finnhub_fundamental_export.py` from export-only to runtime read-only enricher. Plan-gated on `'stock_financials'`. Reads `data/finnhub_fundamentals/<ticker>.json` (existing nightly-export sink). Enriches the existing FUNDAMENTAL SNAPSHOT packet section IN-PLACE with live P/E, debt/equity, gross margin, ROIC, quality flag. Populates `fundamental_*` feature fields per spec §4.9. When plan=free: section's existing fallback (last-known cached or empty) preserved — no regression. **THIS TASK ALSO ADDS THE DATA CONTEXT HEADER** (spec §4.8.1) — prepends DATA CONTEXT block at top of prompt when ≥1 of {INSTITUTIONAL FLOW, MATERIAL EVENTS, FUNDAMENTAL SNAPSHOT enrichment} omits. Implements §4.8.2 stale-data ageing (default 7d threshold via `data_enrichment.stale_data_threshold_days`). REBASES on Task 23.

### Task 25 — Wave C7b.5 — analyst_collector nightly cap update (plan-conditional)

- **Complexity:** ?
- **Depends on:** []
- **Scope fence:** Do NOT bump cap above the documented rate-limit. Do NOT touch other collectors. Do NOT add new endpoints — rate-limit-only change.
- **Files in scope:** ['src/data_collection/analyst_collector.py', 'tests/data_collection/test_analyst_collector_rate_limit.py']
- **Files read-only:** ['src/data_enrichment/finnhub_plan.py']
- **Test strategy:** +2 tests: plan=fundamental-1 cap=100, plan=free cap=20 (preserved). PR body must include rate-limit citation (Finnhub doc URL + retrieved-date).
- **Reviewer dispatch:** []

Update `src/data_collection/analyst_collector.py:14` comment + add `_get_nightly_cap(config)` helper per spec §4.14. Plan=fundamental-1 → 100/night; plan=free → 20/night (preserved). **C7b.5 developer MUST verify current Finnhub fundamental-1 rate-limit from Finnhub docs** (via Context7 or direct doc fetch) before bumping; cite source in PR body. Independent of Tasks 17-24 — only touches analyst_collector.py.

### Task 26 — Wave C7b.6 — finnhub_plan feature-matrix runtime-coverage AST scanner

- **Complexity:** ?
- **Depends on:** [21, 22, 23, 24, 25]
- **Scope fence:** Do NOT modify _FEATURE_MATRIX. Do NOT modify any src/ files — pure test addition. Do NOT add scanner-level allowlists — fail loud on coverage gap. Depends on full C7b chain (21-25) being merged first so scanner runs against complete state.
- **Files in scope:** ['tests/test_finnhub_plan_runtime_coverage.py', 'tests/data_enrichment/test_no_collector_without_plan_gate.py', 'tests/llm/test_packet_section_plan_omission.py']
- **Files read-only:** ['src/data_enrichment/finnhub_plan.py', 'src/llm/packet_writer.py', 'src/data_collection/institutional_ownership_collector.py', 'src/data_collection/filings_sentiment_collector.py']
- **Test strategy:** +3 tests in test_finnhub_plan_runtime_coverage.py (forward-coverage, reverse-omission-path, self-test on synthetic source-tree fixture) + the test_packet_section_plan_omission.py parametrized cases (counted under their parent C7b tasks) + AST guardrail in test_no_collector_without_plan_gate.py. Total new tests: +3 from this task's own file. Test file additions in tests/llm/ are referenced by Tasks 21-24's plan-on/off coverage; this task ensures the file exists with the parametrize harness.
- **Reviewer dispatch:** []

Create `tests/test_finnhub_plan_runtime_coverage.py` per spec §4.15. Two-way AST scanner: (1) FORWARD — for every feature in `_FEATURE_MATRIX['fundamental-1']`, assert ≥1 `finnhub_plan_supports('<feature>',...)` call site exists in `src/`; (2) REVERSE — for every paid-tier-only feature, assert a packet-section omission test exists in `tests/llm/test_packet_section_plan_omission.py`. Self-test on synthetic fixture (feature defined + caller present → PASS; feature defined + caller absent → FAIL). ALSO create `tests/data_enrichment/test_no_collector_without_plan_gate.py` (collector-gate AST guardrail per spec §6.2c). ALSO create `tests/llm/test_packet_section_plan_omission.py` with parametrized cases for INSTITUTIONAL FLOW, MATERIAL EVENTS, FUNDAMENTAL SNAPSHOT enrichment. **Depends on Tasks 21-25** — runtime coverage is asserted against what exists at merge time.

