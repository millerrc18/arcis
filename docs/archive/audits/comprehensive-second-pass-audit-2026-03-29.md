# Comprehensive Second-Pass Audit

Date: 2026-03-29
Repo snapshot: `13d61e3`
Audit mode: Read-only code audit plus targeted validation
Code changes made by auditor: None
New artifact created: This markdown report only

## Executive Summary

This is a second-pass audit performed after the latest fixes were pushed. The goal was not just to repeat the first pass, but to validate whether prior issues were truly resolved, search for additional failure modes, and pressure-test the repo against its stated operating posture.

My conclusion is that the codebase is stronger in several important areas than it was in the first audit, but it is still not "production ready" from an external auditor's viewpoint.

The biggest remaining risks are not cosmetic and not limited to tests. They cluster in four areas:

1. Trade lifecycle truth is still not fully trustworthy.
2. Training-data governance is materially weaker than the repo's stated moat thesis implies.
3. Schema ownership is fragmented, creating silent breakage across monitoring and cloud surfaces.
4. UI, tests, docs, and backend contracts have drifted enough that several surfaces now look healthier than they actually are.

If I had to summarize the repo in one sentence: it has fund-like ambition and feature breadth, but not yet fund-grade control discipline.

## Scope And Methodology

This audit included:

- Review of `AGENTS.md`
- Review of core docs, including `docs/architecture.md`, `docs/deployment.md`, prior audit artifacts, and dashboard-facing docs
- Inspection of trade execution, API, cloud sync, council, training, logging, scheduler, and service layers
- Validation against the current SQLite schema and live repo state
- Targeted test execution and build verification

This audit did not modify source code. The only file added is this report.

## Severity Summary

| Severity | Count | Notes |
| --- | ---: | --- |
| Critical | 4 | Directly affects execution integrity or core data-governance trust |
| High | 9 | Major correctness, security, or control-plane drift |
| Medium | 6 | Important cleanup, reporting, or operational-hardening items |

## First-Pass Validation Status

| Prior Theme | Status Now | Notes |
| --- | --- | --- |
| Paper bracket exit handling | Unresolved | Still misinterprets parent fill and still lacks child leg state |
| Live close ordering / hidden exposure | Unresolved | Journal can still close before broker truth |
| Live broker-side stop/target protection | Unresolved | Live flow still uses simple market entry only |
| Local dashboard secret exposure | Unresolved | Authless config surface still too broad |
| Local/cloud/frontend route drift | Unresolved | Still substantial |
| Council contract drift | Unresolved | Still severe; tests and UI remain stale |
| Bootcamp downgrade of critical audit flags | Unresolved | Still present |
| Conservative drawdown fallback in governor | Resolved | Now returns conservative drawdown on error |
| Trade open should reject on validator / governor exceptions | Resolved | Now rejects instead of proceeding |
| Watcher logging / unbounded process output risk | Partially resolved | Rotating logs are in place |
| Render sync first-fetch blowup risk | Partially resolved | Initial incremental fetch is capped, but full-mode sync is still broken |

## Remediation Matrix

### Must Fix Before Capital At Risk

| Priority | Item | Why |
| --- | --- | --- |
| P0 | Fix bracket-exit truth in paper execution | Current paper results and labels can be wrong |
| P0 | Make broker confirmation authoritative for live closes | Prevent hidden live exposure |
| P0 | Remove or harden `/shadow/close/{ticker}` | It can desynchronize ledger from broker immediately |
| P0 | Split blinded vs outcome-bearing training corpora | Current training export undermines the stated data moat |
| P0 | Establish one canonical schema owner and migrate conflicting tables | Current split causes silent breakage |
| P0 | Make the repo clean-shell green, including council | Current test posture is not release-grade |

### Must Fix Before Wider Operator Use

| Priority | Item | Why |
| --- | --- | --- |
| P1 | Add auth and safe-field filtering to local admin surfaces | Current local dashboard is overexposed |
| P1 | Add broker-native live protection or keep live disabled | Current local watcher is a single point of failure |
| P1 | Align frontend, local API, cloud API, docs, and tests around one contract | Current UI truth is inconsistent by environment |
| P1 | Unify activity logging schema and readers | Current observability is split-brain |
| P1 | Fix cloud SQL to use canonical schemas | Current cloud telemetry can fail or mislead |

### Cleanup / Refactor

| Priority | Item | Why |
| --- | --- | --- |
| P2 | Normalize P&L field semantics | Avoid per-share vs position-level confusion |
| P2 | Remove duplicate drawdown logic from executor | Reduce risk-policy divergence |
| P2 | Make CLI help ASCII-safe on Windows | Improve operator ergonomics |
| P2 | Update stale docs and stale internal audit claims | Current written posture overstates system health |
| P2 | Revisit bootcamp critical-flag downgrade semantics | Preserve governance truth |

## Detailed Findings

## Critical Findings

### C1. Paper bracket-exit handling is still incorrect

- Status: Unresolved from first pass
- Confidence: High
- Evidence:
  - `src/shadow_trading/executor.py:395-417` checks bracket state and treats the parent order status `filled` / `partially_filled` as if that can represent an exit.
  - `src/shadow_trading/alpaca_adapter.py:283-294` returns no `legs` payload from `get_order_status()`.
  - `src/shadow_trading/executor.py:440-450` still calls `place_paper_exit()` after the bracket check.
- Why this matters:
  - A bracket parent fill is the entry, not the stop or target child fill.
  - Current logic can either miss a real bracket exit or submit a second paper sell after a child leg already closed the position.
  - That corrupts both operational truth and downstream training labels.
- Recommendation:
  - Return nested child-leg data from the adapter.
  - Treat parent fill as entry-only.
  - Suppress any synthetic/local paper exit if a child leg already closed the position.
- Trade-offs:
  - More adapter complexity and more branch coverage needed in tests.
  - Strongly worth it; without this, paper execution cannot be treated as ground truth.

### C2. Live trade closure still allows the journal to get ahead of the broker

- Status: Unresolved from first pass
- Confidence: High
- Evidence:
  - `src/shadow_trading/executor.py:452-527` closes the local trade record before attempting the live broker exit at `src/shadow_trading/executor.py:535-540`.
  - `src/main.py:299-307` still says "Closing journal record anyway" if the live sell fails.
- Why this matters:
  - A failed live exit can leave a real position open while the internal ledger says it is closed.
  - That is one of the worst possible failure modes in a trading system because it breaks the operator's mental model.
- Recommendation:
  - Do not mark a live trade closed until broker confirmation is received.
  - Introduce an intermediate reconciliation state if needed.
  - Build a dedicated reconciliation job and make it visible in the dashboard.
- Trade-offs:
  - More state transitions and more ops plumbing.
  - Essential for live-capital safety.

### C3. The local close endpoint can desynchronize the system immediately

- Status: New
- Confidence: High
- Evidence:
  - `src/api/routes/shadow.py:34-92` closes the trade directly via `close_shadow_trade(...)`.
  - It never calls any broker exit function.
  - It does not branch by `source`.
- Why this matters:
  - If this route is triggered, the system can mark a paper or live trade closed without actually closing it at the broker.
  - Combined with the authless local dashboard, this is a serious operational hazard even if the route is not currently prominent in the UI.
- Recommendation:
  - Remove the endpoint, or make it call broker-specific exits first and only close the journal on success.
  - Add explicit source restrictions.
- Trade-offs:
  - Slightly less manual convenience.
  - Much lower chance of an operator-induced reconciliation failure.

### C4. Training-data governance does not currently support the stated moat thesis

- Status: New
- Confidence: High
- Evidence:
  - `src/training/trainer.py:292-295` exports `instruction`, `input_text`, and `output_text` for all rows in `training_examples`.
  - `src/training/bootstrap.py:105-129` explicitly writes `=== ACTUAL OUTCOME ===` into `input_text` for `synthetic_claude`.
  - `src/training/leakage_detector.py:49-50` only checks a narrow subset of sources.
  - Current DB observations:
    - `972` total examples
    - `703` rows with `=== ACTUAL OUTCOME ===` in `input_text`
    - Of those, `700` are `historical_backfill`, `3` are `synthetic_claude`
- Why this matters:
  - The repo says training-data quality is the number one competitive advantage.
  - A dataset dominated by outcome-bearing prompt text, combined with leakage checks that exclude the dominant legacy source, weakens that claim materially.
  - It also creates a false sense of safety if validation focuses only on blinded subsets while export still includes legacy outcome-bearing rows.
- Recommendation:
  - Split the corpus into explicit families: blinded production SFT, outcome-bearing review/postmortem, and synthetic experimentation.
  - Refuse outcome-bearing rows in training export unless the training objective explicitly requires them.
  - Expand leakage detection to every source that can reach training.
  - Track provenance more strictly than `source` alone.
- Trade-offs:
  - Slower training-data accumulation and more migration work.
  - Much stronger moat integrity and audit defensibility.

## High Findings

### H1. Live trading still depends on the watcher for stops and targets

- Status: Unresolved
- Confidence: High
- Evidence:
  - `src/shadow_trading/executor.py:762-767` stores live trades as `order_type = "simple"`.
  - `src/shadow_trading/alpaca_adapter.py:358-390` submits market buy orders only.
- Impact:
  - A host crash, process crash, or network failure removes automated exit protection.
- Recommendation:
  - Use broker-native bracket or OCO orders for live trades, or keep live trading disabled until that exists.

### H2. Local admin surfaces are still too exposed

- Status: Unresolved
- Confidence: High
- Evidence:
  - `src/main.py:874` binds to `0.0.0.0`.
  - `src/api/routes/system.py:21-41` masks only `email.password`, `alpaca.api_secret`, and `training.anthropic_api_key`.
  - `src/api/routes/system.py:339-362` allows config writes directly to `settings.local.yaml`.
- Impact:
  - Secrets and mutable configuration are too easy to expose or mutate.
- Recommendation:
  - Default to localhost only.
  - Require auth for all admin/config routes.
  - Use an allowlist for fields that can ever be returned or changed.

### H3. Local, cloud, frontend, docs, and tests still do not describe the same product

- Status: Unresolved
- Confidence: High
- Evidence:
  - Frontend routes: `frontend/src/App.jsx:71-82`
  - Frontend API calls: `frontend/src/api.js:78-103`
  - Local app mounted routers: `src/api/app.py:20-27`
  - Cloud-only routes still exist in `src/api/cloud_app.py`
- Impact:
  - Different environments present different truths.
  - Operators and developers can mistake missing features for broken features or vice versa.
- Recommendation:
  - Define a single API surface contract and make both local and cloud variants conform to it or explicitly feature-gate non-parity views.

### H4. The council subsystem is still deeply drifted

- Status: Unresolved
- Confidence: High
- Evidence:
  - New agent model: `src/council/agents.py`
  - New vote/direction model: `src/council/protocol.py`
  - Old UI assumptions: `frontend/src/pages/Council.jsx`
  - Old tests: `tests/test_council.py`, `tests/test_council_agents.py`
  - Old docs: `docs/architecture.md:264-292`
- Impact:
  - The subsystem is hard to trust because behavior, docs, tests, and presentation disagree.
  - This is exactly the kind of drift that produces false confidence in reviews and demos.
- Recommendation:
  - Freeze council feature work.
  - Publish a canonical council contract.
  - Update code, tests, docs, and UI in one sweep.

### H5. Schema ownership is fragmented, and the current DB reflects the wrong owner

- Status: New
- Confidence: High
- Evidence:
  - Watcher-created simplified tables:
    - `src/scheduler/watch.py:669-687`
    - `src/scheduler/watch.py:676-682`
  - Canonical table definitions:
    - `src/training/versioning.py:25-35`
    - `src/training/canary.py:34-45`
    - `src/training/quality_drift.py:22-33`
    - `src/logging/activity.py:26-33`
  - Current DB observations:
    - `activity_log` is `event_type/detail/created_at`
    - `canary_evaluations` is simplified
    - `quality_drift_metrics` is simplified
- Impact:
  - Which module touches a table first can determine the schema.
  - That creates silent breakage in monitoring and data-quality safeguards.
- Recommendation:
  - Establish one migration path and one owner for every table.
  - Remove table creation from secondary modules that should only read/write established schemas.

### H6. Cloud API SQL does not match the canonical training schema

- Status: New
- Confidence: High
- Evidence:
  - `src/api/cloud_app.py:345-346` queries `outcome`
  - `src/api/cloud_app.py:661-663` queries `estimated_cost`
  - `src/api/cloud_app.py:705` queries `regime_label`
  - `src/api/cloud_app.py:1348-1349` groups by `outcome`
  - Canonical training schema in `src/training/versioning.py` uses `trade_outcome` and `cost_dollars`
  - Running those exact queries against the current DB produced `no such column` failures
- Impact:
  - Cloud dashboard metrics can silently fail or degrade into misleading approximations.
- Recommendation:
  - Stop writing raw schema-dependent SQL in presentation routes.
  - Route all training/cost summaries through schema-aware service functions.

### H7. Activity logging is split-brain

- Status: New
- Confidence: High
- Evidence:
  - `src/logging/activity.py:79-81` writes `timestamp/category/event/detail/source`
  - `src/utils/activity_logger.py:42-44` writes `event_type/detail/created_at`
  - `src/api/routes/system.py:318-326` reads through `src.logging.activity.get_recent_activity`
  - Current runtime behavior: category-filtered reads fail against the current DB schema
- Impact:
  - The activity feed is not authoritative.
  - This weakens operator trust in dashboard telemetry and postmortem reconstruction.
- Recommendation:
  - Pick one event schema, migrate the table, and remove the other implementation.

### H8. Render sync still has a silent `full` mode bug

- Status: New
- Confidence: High
- Evidence:
  - `src/sync/render_sync.py:35-38` defines `model_versions` as `mode: "full"`
  - `src/sync/render_sync.py:403-425` handles only `incremental` and `latest_only`
  - `src/sync/render_sync.py:427` falls through to `return 0`
- Impact:
  - `model_versions` can silently fail to sync, degrading cloud truth around training state and version visibility.
- Recommendation:
  - Implement `full` mode explicitly, or remove it and use a supported mode.

### H9. The test posture still does not support a release-quality claim

- Status: Unresolved
- Confidence: High
- Evidence:
  - `pytest -q` fails collection in a clean shell
  - `PYTHONPATH=. python -m pytest -q` still fails collection because `tests/test_council_agents.py` imports removed symbols
  - `python -m pytest tests/test_council.py -q` currently reports `24 failed, 5 passed`
- Impact:
  - A repo that is not clean-shell green cannot support high-confidence release claims.
- Recommendation:
  - Make a clean-shell green test run mandatory before any production-readiness declaration.

## Medium Findings

### M1. Training status reporting is outdated relative to current source taxonomy

- Status: New
- Confidence: High
- Evidence:
  - `src/services/training_service.py:35-45`
  - `src/training/versioning.py:441-445`
  - Current DB includes `blinded_win` and `blinded_loss`, but status still reports `dataset_wins=0` and `dataset_losses=0`
- Impact:
  - The dashboard understates the composition of the training set.
- Recommendation:
  - Update source counting and dashboard labels to reflect the current taxonomy.

### M2. Unrealized P&L semantics are inconsistent

- Status: Unresolved
- Confidence: High
- Evidence:
  - `src/services/shadow_service.py:43`
  - `src/services/shadow_service.py:67`
  - `tests/test_services.py:139-141`
- Impact:
  - Some fields are per-share while others are position-level, which invites wrong UI and operator interpretation.
- Recommendation:
  - Normalize all dollar-denominated P&L to position-level dollars.

### M3. Drawdown policy is still duplicated

- Status: Partially resolved
- Confidence: Medium
- Evidence:
  - Conservative error fallback in `src/risk/governor.py:72`
  - Permissive duplicate path in `src/shadow_trading/executor.py:186`
- Impact:
  - Risk policy can diverge depending on call path.
- Recommendation:
  - Remove local sizing fallback logic from executor and route through the governor only.

### M4. Cloud telemetry mixes approximate placeholders with real metrics

- Status: Unresolved
- Confidence: Medium
- Evidence:
  - `src/api/cloud_app.py` contains a mix of real DB reads and approximation-heavy endpoints
- Impact:
  - The dashboard can look more authoritative than it really is.
- Recommendation:
  - Label estimated metrics clearly and reduce placeholder surfaces over time.

### M5. Documentation currently overstates system health

- Status: Unresolved
- Confidence: High
- Evidence:
  - `docs/audit_comprehensive_2026-03-28.md:3-10` claims all critical and high issues were fixed
  - `docs/deployment.md:106-107` still describes `sessionStorage` and 24-hour sessions
  - Frontend currently uses 7-day `localStorage`
- Impact:
  - Internal governance artifacts can mislead decision-making.
- Recommendation:
  - Treat ops docs and internal audits as versioned release artifacts that must be validated against code.

### M6. CLI help still breaks on a standard Windows console

- Status: Unresolved
- Confidence: High
- Evidence:
  - `python -m src.main --help` still raises `UnicodeEncodeError`
- Impact:
  - Day-to-day operator ergonomics are lower than they should be on the primary local platform.
- Recommendation:
  - Make help text ASCII-safe or explicitly require UTF-8 console output.

## Refactoring Recommendations

These are not just code-style preferences. They are leverage points that would reduce the number of latent failures in the system.

### 1. Create a canonical data-contract layer

Move schema-aware reads and writes out of routes and scattered helpers into service modules with typed return shapes.

Benefits:

- Fewer route-level SQL mismatches
- Easier cloud/local parity
- Better migration safety
- Better testability

### 2. Collapse trade lifecycle state into an explicit state machine

Current trade lifecycle transitions are spread across executor, CLI, API route handlers, and journal helpers.

Benefits:

- Fewer close-ordering bugs
- Cleaner reconciliation handling
- Easier distinction between paper and live semantics
- Better postmortem auditability

### 3. Separate "model training corpus" from "analysis and review corpus"

The current `training_examples` table is doing too many jobs.

Benefits:

- Cleaner provenance
- Cleaner leakage checks
- Easier holdout guarantees
- Better ability to reason about what the active model actually saw

### 4. Introduce a single event bus or event-write facade

Activity logging, notifications, and dashboard feed semantics are too fragmented.

Benefits:

- One schema
- One set of event categories
- Easier replay and postmortem support
- Better operator trust

### 5. Define environment capability flags explicitly

Instead of allowing local and cloud to drift informally, define capability flags such as:

- `supports_live_ledger`
- `supports_council_history`
- `supports_health_score`
- `supports_activity_feed`

Benefits:

- Cleaner UI behavior
- Less route drift
- Fewer "works in cloud only" surprises

## Strategic Commentary

This section is intentionally candid because the user asked for outside perspective, including critical perspective.

### 1. The repo is most vulnerable where it claims to be strongest

The stated moat is training-data quality. Right now, the training pipeline has enough legacy mixing, source drift, and outcome-bearing prompt text to make that moat less defensible than the repo narrative suggests.

That does not mean the strategy is wrong. It means the moat needs harder rails than the current implementation provides.

### 2. Operational integrity is likely to outrank alpha quality in the near term

There is enough sophistication here that the next major failure is more likely to come from control-plane mismatch than from inability to generate market insight.

Examples:

- paper exits not reflecting actual bracket behavior
- live journal state getting ahead of broker truth
- schema drift causing dashboards to misreport health

If that is right, then the best next sprint is probably not "more intelligence" but "more truth."

### 3. The system has crossed the threshold where "internal prototype" habits become dangerous

Broad local admin surfaces, stale docs, drifted tests, and multi-owner schemas are survivable in an early prototype.

They become genuinely hazardous once the system starts to describe itself as operationally ready, even in bootcamp mode.

### 4. There is a meaningful opportunity to simplify before expanding

The roadmap is ambitious and credible in vision, but the current best move is probably consolidation:

- one trade lifecycle model
- one training corpus model
- one activity/event model
- one council contract
- one source of schema truth

That kind of simplification usually increases speed later because it removes invisible drag and hidden fear.

## Verification Log

### Commands And Outcomes

- `pytest -q`
  - Fails collection in a clean shell
- `PYTHONPATH=. python -m pytest -q`
  - Still fails collection due to stale council imports
- `python -m pytest tests/test_council.py -q`
  - `24 failed, 5 passed`
- Targeted suites passing:
  - `tests/test_live_trading.py`
  - `tests/test_bracket_orders.py`
  - `tests/test_local_api_routes.py`
  - `tests/test_render_sync.py`
  - `tests/test_activity_log.py`
  - `tests/test_activity_logger.py`
- `npm run build`
  - Passes
  - Frontend bundle remains large
- `python -m src.main --help`
  - Still crashes on Windows with `UnicodeEncodeError`

### Current DB Observations

- `training_examples`: `972` rows
- Source distribution:
  - `historical_backfill`: `700`
  - `blinded_win`: `192`
  - `blinded_loss`: `77`
  - `synthetic_claude`: `3`
- Rows with `=== ACTUAL OUTCOME ===` in `input_text`: `703`
- Current `activity_log` schema:
  - `id`
  - `event_type`
  - `detail`
  - `created_at`
- Current `canary_evaluations` schema is the simplified watcher version
- Current `quality_drift_metrics` schema is the simplified watcher version

## Recommended Execution Order

If I were sequencing the next work from a risk perspective, I would do it in this order:

1. Fix trade close semantics and bracket exit truth.
2. Lock down admin surfaces and remove the unsafe local close path.
3. Establish one schema owner and migrate conflicting tables.
4. Split training corpora and tighten provenance/leakage controls.
5. Make tests green in a clean shell, especially council.
6. Align local/cloud/frontend/docs around one public contract.
7. Normalize reporting semantics and cleanup items.

## Bottom Line

This repo does not look like a weak project. It looks like a strong project that is hitting the normal wall where breadth starts to outpace control discipline.

That is fixable.

But the right response is not to declare victory early. The right response is to tighten truth, reconciliation, schema ownership, and data provenance until the system becomes boring in the places where today it is still clever.
