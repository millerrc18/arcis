# Sprint 5 Closeout Plan — Design Spec (v2)

**Document ID:** `docs/audits/2026-05-12-sprint-5-closeout-plan/spec.md`
**Status:** Draft v2 — revised post devil's-advocate CONCERNS verdict
**Audience:** `arcis:code` PM orchestrator + per-wave developer/reviewer agents
**Scope:** Waves C/D/F (implementation) + Wave E (design-only) + mini-tracker dispositions + Sprint Close PR contract

---

## 0. Revision History

| Version | Date | Author | Notes |
|---|---|---|---|
| v1 | 2026-05-12 | design-team | Initial spec. |
| v2 | 2026-05-12 | design-team | Devil's-advocate revision. Resolved C1 (platform_events disposition → Task 2 owns TableDef; #96 retired), M1 (severity required kwarg + AST guardrail), M2 (`bypass_severity` removed — rule #1 IS the bypass), M3 (alert_silence reads UNION with digest_queue), M4 (retry counter persisted to JSON), M5 (digest flush-then-fail resets `flushed_at`), MIN1-7 + NIT1 fixed inline, FEAS1 (28 not 30+), FEAS2 (new `src/monitoring/` package). Decisions table grown 17→24. |

---

## 1. Overview

### 1.1 Goal

Land Sprint 5 — the final Arcis sprint before walk-forward framework becomes the active post-Sprint-5 track — via 5 wave PRs (Waves C, D, E-disposition, F) plus a Sprint Close PR. After Close, `src/version.py = v0.35.0`, a `v0.35.0` git tag exists, `docs/roadmap.md` exists, the CHANGELOG has a consolidated Sprint 5 section, and the operator-guide describes the new notifications routing config. Three new operator-visible behaviors ship: notifications routing policy (Wave D), manual-intervention drift detection (Wave C #45), and a server-side stale-base CI check (Wave F #15).

### 1.2 In Scope

- **Wave C** (5 tasks + folded #100 scanner extension + folded #96 platform_events TableDef): data integrity + cross-engine future-prevention
- **Wave D** (1 task #69 + folded #93/#94 + new #101 source tagging + new severity-audit sub-step): notifications routing policy, digest mode, retry/escalation with persistent state, alert-silence detector
- **Wave E** (1 task #91): keep existing spec at `docs/audits/2026-05-12-dual-gpu-ideation/specs/` as canonical artifact; defer implementation; disposition.md APPLIES the 4 identified stale-text fixes inline in the same PR
- **Wave F** (3 tasks): server-side stale-base check, test suite speedup, local PG provisioning
- **Sprint Close PR**: aggregated CHANGELOG, version bump to 0.35.0, git tag, new `docs/roadmap.md`, operator-guide append, test floor canon refresh, known-pre-existing-failures.md refresh, `_scalar` cosmetic removal, #97 sentinel grandfather

### 1.3 Out of Scope (explicit)

- Walk-forward framework implementation (separate post-Sprint-5 track). **NOTE:** the `shadow_trades.strategy_id` FK added in Task 2 targets the current `strategy_registry` schema. The walk-forward framework MUST treat this FK as a deprecation candidate when its replacement strategy-attribution model lands; explicit migration step required in the walk-forward design (insurance against post-sprint schema lock-in).
- New ML model architectures or training code beyond the deferred Wave E impl
- Frontend redesign (Sprint 5 may render new widgets, no arch changes)
- Render infrastructure (PG cutover complete)
- #97 actual file split of `alpaca_adapter.py` (grandfathered via `known_violations.json`; tracked as post-Sprint-5)
- Engine.py + value_tracker.py `except Exception` refactor (#68 sibling work, post-Sprint-5)

### 1.4 Success Criteria

- All 5 wave PRs merged plus Sprint Close PR merged with green CI
- Final test floor between 5350-5450 (sustained, with zero new failures)
- All operator-visible decisions resolved without mid-sprint additional AskUserQuestion batches (decisions already approved in 2026-05-12 CHECKPOINT)
- Devil's-advocate gates pass: Wave D config attack surface bounded (no dynamic event_type resolution); digest mode cannot delay severity≥medium events; backward-compat default config preserves current behavior; retry counter survives watch-loop restart; alert_silence does not false-fire during digest-only quiet periods

---

## 2. Architecture

### 2.1 Wave C — Data Integrity Hardening

Sequencing bottleneck per glidepath ("C must complete before D"): typed exceptions (#68) and schema additions (#56 strategy_id, severity column for notifications_sent, **platform_events TableDef**) are dependencies of Wave D.

**Tasks:**
- **C1 (#54)** — wire `dates` + `directions` arrays at `src/api/cloud_routes/kpis.py:128` (corrected from brief's `:91`). 2-LOC change that flips MC permutation vote from ABSTAIN to real PASS/FAIL.
- **C2 (#56 + #96 RESOLVED)** — add `strategy_id TEXT` ColumnDef + ForeignKeyDef to `shadow_trades` in `src/schema/registry.py`; extend `_fetch_closed_trades` in `src/api/cloud_routes/kpis_compute.py` with optional `strategy_id` filter param. **ALSO add `platform_events` TableDef** (TEXT id, TEXT event_type, TEXT severity, TEXT payload_json, TIMESTAMP created_at) — D5 alert_silence detector AND C4 drift detector are both write-sites (see §4.5 + §4.4). FK creation strategy: PostgreSQL `ADD CONSTRAINT ... NOT VALID` + background `VALIDATE CONSTRAINT` to avoid VALIDATE-time table lock on shadow_trades. SQLite ignores NOT VALID; constraint applies on next insert.
- **C3 (#68 REFRAMED)** — create typed exception hierarchy in `src/council/errors.py` (`CouncilError` base → `CouncilParseError`, `CouncilTimeoutError`, `CouncilAgentDataError`, `CouncilProviderError`); replace **28** bare `except Exception` blocks in `src/council/agent_data.py` with typed catches (corrected from v1 '30+' per actual grep count). **Engine.py + value_tracker.py except-blocks DEFERRED to post-sprint** (per deep-report scope guard).
- **C4 (#45)** — new module `src/monitoring/manual_intervention_drift.py` (see §2.2.1 for package rationale) that compares `get_all_positions()` (alpaca_adapter) vs `shadow_trades WHERE status='open'`; emits `notify_manual_intervention_drift` event when divergence persists > 30 min (configurable). New event_type in `src/notifications/telegram.py` event_map. Writes `platform_events` row for forensic trail.
- **C5 (#47)** — verification doc only: `docs/audits/2026-05-07-telegram-email-sweep/triage-disposition.md` catalogs all 50 findings as `closed-by-PR-X | scoped-into-Wave-D | follow-up-issue-N | accepted-risk`. Zero source changes.
- **C6 (#100)** — extend AST scanner at `tests/test_no_fetchone_int_index_in_pg_unsafe_files.py` with new test function `test_no_fetchall_list_comp_int_index_in_pg_unsafe_files` matching `ListComp(elt=Subscript(value=Name, slice=Constant(int)), generators=[comprehension(iter=Call(func=Attribute(attr='fetchall')))])` plus a sibling scanner over `scripts/`. Self-test included.

### 2.2 Wave D — Notifications Routing Policy (LARGEST PIECE)

Single architectural insertion: a **policy gate** between `safe_send`'s `is_telegram_enabled()` check and the `event_map[event_type]` lookup. Three layered concerns compose:

1. **Dedup** (existing) — 24h content-identity dedup via `notifications_dedup` table
2. **Policy** (NEW) — mute rules (quiet hours, severity, event_type), routing (telegram/email/both/none)
3. **Digest queue** (NEW) — bundles severity=low events into cadence-flushed batches

**Composition order:** dedup → policy → digest queue → dispatch.

**Hard invariants (preserve from Sprint 4 T2 and security review):**
- `event_map[event_type]` lookup REMAINS in `safe_send`. YAML config REFERENCES event_type keys; never resolves them dynamically. KeyError-on-unknown-event_type security boundary preserved.
- `safe_send`'s `except (urllib3.HTTPError, requests.RequestException, socket.timeout, OSError)` block at `src/notifications/telegram.py:1299-1311` is the ONLY broad catch. New retry logic mounts INSIDE this except block; does NOT widen the catch.
- Severity ≥ `medium` BYPASSES digest queue (digest is opt-in for severity=low only). Critical alerts cannot be delayed by digest cadence.
- **`severity` is a REQUIRED kwarg of `safe_send`** (no default value). Every existing call site is audited + updated in Task 12; AST guardrail asserts `safe_send` is never called without a literal `severity=...` kwarg.

**event_map mutation discipline:**
- All event_map additions (`manual_intervention_drift`, `alert_silence`) land at **module-import time** in `src/notifications/telegram.py` (top-level assignments to the `event_map` dict literal — NOT runtime mutations).
- `_load_notifications_config()` is invoked from `src/main.py:startup` AFTER all `src.monitoring.*` and `src.notifications.*` modules have been imported (import-graph guarantees event_map is fully populated before config validates against its keys).
- Integration test `tests/notifications/test_event_map_load_order.py` imports `src.main` then loads a sample config that references the new event types and asserts validation passes.

### 2.2.1 Extend existing `src/monitoring/` package (operational alerting)

**Rationale (FEAS2 resolution, corrected per PR #1061 review):** `src/diagnostics/` is dedicated to statistical methodology per its `__init__.py` docstring (canonical_sharpe, instrumentation_filter, MinTRL power assessment, etc.). Operational alerting modules (drift detection, alert silence) are a different category. Mixing them dilutes the diagnostics namespace. **The `src/monitoring/` package already exists** (currently holds `system_metrics.py` for GPU/CPU/RAM/disk/Ollama health tracking) — it is the natural home for additional operational health detectors. Sprint 5 EXTENDS this existing package; it does not create a new one.

**Package contents AFTER Sprint 5** (additions in **bold**):
- `src/monitoring/__init__.py` — docstring updated from "System monitoring — GPU, CPU, RAM, disk, Ollama health tracking." to "System monitoring + operational alerting — health metrics and divergence detectors."
- `src/monitoring/system_metrics.py` — EXISTING (no change)
- **`src/monitoring/errors.py`** — `MonitoringDataError` (mirrors the #68 typed-error pattern)
- **`src/monitoring/manual_intervention_drift.py`** (Wave C #45)
- **`src/monitoring/alert_silence.py`** (Wave D D5)

**Modified surfaces:**
- `src/notifications/telegram.py:1234` — insert policy gate between line 1232 (`is_telegram_enabled` check) and line 1287 (`event_map[event_type]`).
- `src/notifications/telegram.py:1299` — replace single-attempt send with exponential-backoff retry (1s, 5s, 30s = 3 attempts). After 5 consecutive failures in a 10-min window, mark `policy_decision='escalated'` and call email-channel notifier as fallback. **Counter persisted to `data/notification_retry_state.json` (see §4.3) so escalation survives NSSM watch-loop restart.**
- `src/notifications/telegram.py:780` — apply `_html_escape()` to `regime_old`/`regime_new` in `notify_regime_alert` (#93).
- `src/notifications/telegram.py:805` — apply `_html_escape()` to `risk_governor_status` + each ticker in `recent_str` before join in `notify_streak_alert` (#94).
- `src/scheduler/watch.py` — add digest flush hook (every 5 min) + alert-silence detector hook (every 5 min during market hours).

**New surface — alert silence detector:**
`src/monitoring/alert_silence.py` — runs on watch loop cadence. If `(notifications_sent WHERE status='ok') UNION (notifications_digest_queue WHERE flushed_at IS NULL)` has no row within `config.alert_silence_threshold_minutes` (default 60) during market hours, writes `platform_events` row with severity=high AND surfaces dashboard widget data. UNION read closes the M3 false-positive (digest-only quiet periods). Closes F2 "18-hour live_prices gap with no notification" blind spot.

**Source tagging (#101 — operator clarification 2026-05-12):**
- New `source_tag TEXT DEFAULT 'unknown' NOT NULL` column on `notifications_sent` (default changed from `'watch-loop'` to `'unknown'` to fail loud when env var absent — see Decision 19).
- `safe_send` reads `os.environ.get('ARCIS_NOTIFICATION_SOURCE', 'unknown')` and writes to `source_tag` column AND prepends a `[<source>]` prefix to outgoing Telegram messages when source ≠ `'watch-loop'`
- NSSM service config MUST set `AppEnvironmentExtra=ARCIS_NOTIFICATION_SOURCE=watch-loop` (operator-guide documents the registry path: `HKLM\SYSTEM\CurrentControlSet\Services\<svc>\Parameters\AppEnvironmentExtra`). Sprint Close PR adds this to the operator-guide "Watch loop" section.
- `tests/conftest.py` session fixture sets `ARCIS_NOTIFICATION_SOURCE='pytest:<worktree-basename>'` AND monkeypatches `_send_telegram` to a null-router (no actual network call from pytest under any condition)
- arcis:code agents that invoke `python -m src.main` outside NSSM inherit `'unknown'` → alerts visibly tagged `[unknown]` so operator can identify untagged callers post-hoc.

### 2.3 Wave E — Dual-GPU Disposition

DESIGN-ONLY per operator decision. Deliverable: a one-pager `docs/audits/2026-05-12-dual-gpu-ideation/disposition.md` that:
- Confirms spec at `docs/audits/2026-05-12-dual-gpu-ideation/specs/2026-05-12-dual-gpu-workload-separation-design.md` is the canonical artifact
- States "Implementation deferred to first post-Sprint-5 maintenance window"
- **APPLIES the 4 stale-text fixes inline to the canonical spec in the same PR** (per MIN5): (1) test floor 3682→5350, (2) all 'Sprint 6' references → 'post-Sprint-5' or 'next-sprint', (3) any references to deprecated training pipelines (Unsloth) → Transformers+PEFT+TRL per memory `project_gpu_upgrade`, (4) NUM_PARALLEL update (1→4 viable on RTX 3090).
- Links from `docs/roadmap.md` (Sprint Close PR creates that file)

Pure-docs scope. Zero source changes. Zero new tests.

### 2.4 Wave F — Dev Tooling / Test Infrastructure

- **F1 (#15)** — new GitHub Actions workflow `.github/workflows/stale-base-check.yml` triggers on `pull_request.synchronize`, computes `git merge-base origin/main HEAD` vs `origin/main`'s HEAD, sets a status-check that blocks merge when stale. Complements client-side `scripts/hooks/pre-push`.
- **F2 (#86)** — restructure `tests/test_cloud_requirements_imports.py` from per-test fresh-venv pattern to session-scoped shared-venv: ONE pip install of `requirements-cloud.txt`, then per-test imports via subprocess against the shared venv. Target: drop full-sweep runtime by ~3x.
- **F3 (#87)** — new `docker-compose.test.yml` (postgres:16-alpine on `localhost:5433`); `tests/conftest.py` `pytest_sessionstart`/`pytest_sessionfinish` hooks provision + teardown. Three hardcoded `TEST_DATABASE_URL` fixtures (`tests/api/test_status.py:18`, `tests/test_cloud_app.py:15`, `tests/test_shadow_desk_filter.py:25`) refactored to use the provisioned URL. Graceful SKIP fallback when Docker not installed. Drops `Create test/test PG role` step from `.github/workflows/pg-tests.yml`.

### 2.5 Sprint Close PR

Final aggregation PR. See §9 (File Inventory) and §10 Sprint Close subsection for exact artifacts.

---

## 3. Data Model

### 3.1 Schema additions (all via `src/schema/registry.py`)

**Wave C #56 — shadow_trades.strategy_id**
```python
# In TABLES['shadow_trades'].columns, after existing columns ~line 318:
ColumnDef('strategy_id', 'TEXT', nullable=True, default=None,
          description='FK to strategy_registry.strategy_id; NULL for legacy rows pending backfill. Walk-forward framework will deprecate this FK target — see spec §1.3'),
# In TABLES['shadow_trades'].foreign_keys:
ForeignKeyDef('strategy_id', 'strategy_registry', 'strategy_id', initially_deferred=True),
```
*Backfill policy:* legacy rows remain NULL (no in-spec backfill task; tracked as post-sprint follow-up).

*FK creation strategy (PG locking — MIN3 resolution):* `render_migrate.py` emits `ALTER TABLE shadow_trades ADD CONSTRAINT shadow_trades_strategy_id_fkey FOREIGN KEY (strategy_id) REFERENCES strategy_registry(strategy_id) NOT VALID;` followed by an asynchronous `ALTER TABLE shadow_trades VALIDATE CONSTRAINT shadow_trades_strategy_id_fkey;`. `NOT VALID` skips the upfront table scan (no AccessExclusiveLock on shadow_trades during VALIDATE — only a lighter ShareUpdateExclusiveLock). SQLite path: NOT VALID semantics N/A; FK enforced on next insert. Task 2's PR body must document the validation timing.

*Precondition:* Wave C #56 developer must confirm `strategy_registry` TableDef + PK column name via Grep before adding the FK. If absent, scope-out to ColumnDef-only (no FK) with rationale in PR body.

**Wave C — platform_events TableDef (C1 resolution — folded into Task 2)**
```python
TableDef(
    name='platform_events',
    columns=[
        ColumnDef('id', 'INTEGER', primary_key=True, autoincrement=True),
        ColumnDef('event_type', 'TEXT', nullable=False),
        ColumnDef('severity', 'TEXT', nullable=False),  # low|medium|high|critical
        ColumnDef('payload_json', 'TEXT', nullable=True),
        ColumnDef('source', 'TEXT', nullable=False),  # 'alert_silence'|'drift_detector'|...
        ColumnDef('created_at', 'TIMESTAMP', nullable=False, default='CURRENT_TIMESTAMP'),
    ],
    indexes=[
        IndexDef('idx_platform_events_created_at', ['created_at']),
        IndexDef('idx_platform_events_event_type', ['event_type']),
    ],
)
```
*Rationale:* both `src/monitoring/alert_silence.py` (D5) AND `src/monitoring/manual_intervention_drift.py` (C4) write forensic-trail rows. TableDef creation lives in Task 2 because it's already touching `src/schema/registry.py`. Decision 7 updated: #96 is RESOLVED-BY-C2 (not scope-out).

**Wave D — notifications_sent column additions**
```python
# In TABLES['notifications_sent'].columns:
ColumnDef('severity', 'TEXT', nullable=False, default="'medium'",
          description='low|medium|high|critical — populated by safe_send from required severity kwarg'),
ColumnDef('policy_decision', 'TEXT', nullable=True, default=None,
          description='sent|muted|digested|escalated|failed|abandoned — forensic trail of policy gate decision'),
ColumnDef('source_tag', 'TEXT', nullable=False, default="'unknown'",
          description='watch-loop|pytest:<worktree>|operator-cli|unknown — distinguishes notification origin. Fails loud (default=unknown) when ARCIS_NOTIFICATION_SOURCE env var absent.'),
```

**Wave D — new notifications_digest_queue table**
```python
TableDef(
    name='notifications_digest_queue',
    columns=[
        ColumnDef('id', 'INTEGER', primary_key=True, autoincrement=True),
        ColumnDef('event_type', 'TEXT', nullable=False),
        ColumnDef('severity', 'TEXT', nullable=False),
        ColumnDef('payload_json', 'TEXT', nullable=False),
        ColumnDef('channel', 'TEXT', nullable=False),  # telegram|email|both
        ColumnDef('enqueued_at', 'TIMESTAMP', nullable=False, default='CURRENT_TIMESTAMP'),
        ColumnDef('flushed_at', 'TIMESTAMP', nullable=True, default=None),
        ColumnDef('flush_attempts', 'INTEGER', nullable=False, default='0',
                  description='Counter for retry-then-fail recovery; cap at 3 then mark policy_decision=abandoned'),
    ],
    indexes=[
        IndexDef('idx_digest_queue_pending', ['flushed_at', 'enqueued_at']),
    ],
)
```

### 3.2 Schema changes NOT in scope

- Engine.py + value_tracker.py except-block refactor — out of #68 scope per deep-report.
- Backfill of legacy `shadow_trades.strategy_id` NULL rows — post-sprint.

### 3.3 Migration timing & locking

All new schema additions go through:
1. Edit `src/schema/registry.py`
2. Run `python -m src.main validate-schema --fix` locally (SQLite)
3. Run `python scripts/render_migrate.py` against PG (PR body must include output per CLAUDE.md)

**Locking notes for Task 2:**
- `shadow_trades` is a hot table (read by KPIs, written by executor). `ADD COLUMN strategy_id TEXT` is metadata-only in PG ≥ 11 with no default; no rewrite. **The default value is NULL — no `DEFAULT` clause in DDL.**
- FK constraint creation uses `NOT VALID` to avoid AccessExclusiveLock during validation. Validation deferred to off-hours (operator-triggered: `python scripts/render_migrate.py --validate-deferred-constraints`).
- `platform_events` is a NEW table — no locking concern.
- `notifications_sent` column adds use `DEFAULT 'unknown'` (constant) for `source_tag` — PG ≥ 11 makes this metadata-only too.

---

## 4. API & Module Surface

### 4.1 `src/notifications/policy.py` (NEW)

```python
from dataclasses import dataclass
from datetime import datetime, time
from typing import Literal

Severity = Literal['low', 'medium', 'high', 'critical']
Action = Literal['send', 'mute', 'digest', 'escalate']
Channel = Literal['telegram', 'email', 'both', 'none']

@dataclass(frozen=True)
class PolicyDecision:
    action: Action
    channels: list[Channel]
    reason: str  # human-readable for logs + dashboard

def should_dispatch(
    event_type: str,
    severity: Severity,
    now_et: datetime,
    config: dict,  # parsed from settings.local.yaml notifications: section
) -> PolicyDecision:
    """
    Pure function. No I/O. Returns the dispatch decision.
    
    Rule precedence (first match wins):
      1. severity in {'high', 'critical'} → always send (immediate, no other gates apply)
      2. event_type in config['mute_event_types'] → mute
      3. now_et within config['quiet_hours'] → mute (or digest if config['quiet_digest']=True)
      4. severity == 'low' AND config['digest_low']=True → digest
      5. default → send via config['default_routing'].get(event_type, ['telegram'])
    
    NOTE: there is no `bypass_severity` config — rule #1 IS the bypass. High/critical
    is unconditionally immediate. Removed in v2 per M2 (unreachable code path).
    """
```

### 4.2 `src/notifications/digest_queue.py` (NEW)

```python
def enqueue(event_type: str, severity: str, payload: dict, channel: str, conn=None) -> int:
    """Write to notifications_digest_queue. Returns row id."""

def flush_due(now_et: datetime, config: dict, conn=None) -> list[FlushItem]:
    """
    Return events whose cadence bucket has elapsed since enqueued_at.
    
    Atomicity: SELECT rows WHERE flushed_at IS NULL AND enqueued_at < (now_et - cadence)
               THEN UPDATE flushed_at=now_et per row in a single transaction.
    
    Cadence: config['digest_cadence_minutes'] (default 60).
    
    Returns: [FlushItem(row_id, event_type, severity, payload, channel, enqueued_at), ...]
    Caller (watch.py flush hook) iterates and dispatches each via _send_with_retry.
    """

def mark_flush_failed(row_id: int, conn=None) -> None:
    """
    Called by watch.py flush hook when _send_with_retry fails ALL 3 attempts for a flushed row.
    
    Behavior (M5 resolution):
      1. SET flushed_at=NULL, flush_attempts=flush_attempts+1
      2. If flush_attempts >= 3 after increment: SET policy_decision='abandoned',
         keep flushed_at=NULL but exclude from future flush_due reads via
         `AND flush_attempts < 3` predicate in flush_due query.
      3. Else: row re-enters the flush eligibility pool on next tick.
    
    Closes the v1 "flush-then-fail loses events" data-loss path.
    """
```

`flush_due` query (revised):
```sql
SELECT id, event_type, severity, payload_json, channel, enqueued_at
FROM notifications_digest_queue
WHERE flushed_at IS NULL
  AND flush_attempts < 3
  AND enqueued_at < datetime(:now_et, '-' || :cadence_min || ' minutes')
ORDER BY enqueued_at ASC
FOR UPDATE SKIP LOCKED;  -- PG only; SQLite ignores (single-writer)
```

### 4.3 `src/notifications/telegram.py` — `safe_send` modification

**Before (line 1232-1290):**
```python
def safe_send(event_type: str, severity: str = 'medium', **kwargs):
    if not is_telegram_enabled():
        return
    # ... dedup check ...
    handler = event_map[event_type]  # KeyError-on-unknown — SECURITY BOUNDARY
    handler(**kwargs)
```

**After (M1 — severity is REQUIRED, no default):**
```python
def safe_send(event_type: str, *, severity: Severity, **kwargs):
    """
    severity is REQUIRED keyword-only — no default value.
    Existing call sites updated in Task 12 (D3). AST guardrail
    test_safe_send_severity_required.py asserts every safe_send(
    call passes a literal severity= kwarg.
    """
    if not is_telegram_enabled():
        return
    # ... dedup check (unchanged) ...
    
    # NEW: policy gate (composes after dedup, before dispatch)
    config = _load_notifications_config()  # cached after first call
    now_et = _now_et()
    decision = policy.should_dispatch(event_type, severity, now_et, config)
    
    if decision.action == 'mute':
        _record_policy_decision(event_type, severity, 'muted', decision.reason)
        return
    if decision.action == 'digest':
        digest_queue.enqueue(event_type, severity, kwargs, decision.channels[0])
        _record_policy_decision(event_type, severity, 'digested', decision.reason)
        return
    
    handler = event_map[event_type]  # KeyError-on-unknown PRESERVED
    _send_with_retry(handler, event_type, severity, decision, **kwargs)
```

**`_send_with_retry` (NEW helper inside telegram.py):**
- Wraps the existing send + the existing network-except block at lines 1299-1311
- 3 attempts with sleeps `[1, 5, 30]` seconds between
- After all 3 fail: writes `status='failed'`, `policy_decision='failed'`
- **Persistent counter (M4 resolution):** consecutive failure count + window_start_ts loaded from `data/notification_retry_state.json` on safe_send module import. After each failure: write updated counter back to JSON atomically (write tmp + os.replace). After 5 failures within 10-min window → escalation. State survives watch-loop restart.
- After escalation fires → email_notifier.send(...) as fallback. Records `policy_decision='escalated'`. Counter resets on next success (write state with counter=0).
- **Catch list UNCHANGED**: still only `(urllib3.HTTPError, requests.RequestException, socket.timeout, OSError)`. Bare `except Exception` is FORBIDDEN per Sprint 4 T2 discipline.

**`data/notification_retry_state.json` shape:**
```json
{
  "consecutive_failures": 0,
  "window_start_ts": "2026-05-12T14:30:00-04:00",
  "last_escalation_ts": null,
  "updated_at": "2026-05-12T14:35:12-04:00"
}
```
Loaded on safe_send first call (lazy import); written after each attempt outcome. File path follows the **new** `data/drift_detector_state.json` pattern introduced in Task 4 (`src/monitoring/manual_intervention_drift.py`); both files use atomic-write-via-tmp+os.replace and JSON-serializable singleton state. Mirrors memory `feedback_backfill_patterns` for atomic state files.

### 4.4 `src/monitoring/manual_intervention_drift.py` (NEW — Wave C #45)

```python
def detect_drift(
    broker_positions: dict[str, float],  # ticker -> qty from alpaca_adapter.get_all_positions()
    db_positions: dict[str, float],      # ticker -> sum(actual_shares) from shadow_trades WHERE status='open'
    threshold_minutes: int = 30,
    state_path: str = 'data/drift_detector_state.json',
    conn=None,
) -> list[DriftFinding]:
    """
    Compares broker vs db per-ticker. If diff != 0, persists first-seen-at timestamp
    to state_path. If diff has persisted unchanged > threshold_minutes:
      - emits a finding
      - writes a platform_events row (source='drift_detector', severity='high')
        for forensic trail
    Returns list of DriftFinding(ticker, broker_qty, db_qty, first_seen_at, severity).
    """
```

### 4.5 `src/monitoring/alert_silence.py` (NEW — Wave D add-on)

```python
def check_alert_silence(
    now_et: datetime,
    threshold_minutes: int = 60,
    conn=None,
) -> AlertSilenceFinding | None:
    """
    Reads the UNION of:
      - notifications_sent WHERE status='ok' ORDER BY sent_at DESC LIMIT 1
      - notifications_digest_queue WHERE flushed_at IS NOT NULL ORDER BY flushed_at DESC LIMIT 1
      - notifications_digest_queue WHERE enqueued_at IS NOT NULL ORDER BY enqueued_at DESC LIMIT 1
    The 3rd UNION term (enqueued_at) closes M3: during digest-only quiet periods,
    severity=low events accumulate in the queue without firing. Reading enqueued_at
    confirms the watch loop IS receiving + processing events even when nothing flushed.
    
    During market hours (per src/scheduler/holidays.is_market_open — NEW in
    Task 14 scope; extracted from WatchLoop._is_market_open at watch.py:405):
      - if MAX(union dates) is older than now_et - threshold_minutes → return AlertSilenceFinding
      - emits via safe_send(event_type='alert_silence', severity='high', ...)
      - writes platform_events row (source='alert_silence', severity='high') for forensic trail
    Returns None outside market hours.
    """
```

**Truth-table test (M3 anchor):**
- `digest_cadence_minutes=60` + `alert_silence_threshold_minutes=60` + only severity='low' events enqueued for 90 min during market hours → check_alert_silence returns None (queue activity proves watch loop is alive).

### 4.6 `src/council/errors.py` (extended — Wave C #68)

```python
class CouncilError(Exception):
    """Base for all council subsystem errors."""

class CouncilUnavailableError(RuntimeError, CouncilError):
    """Existing — kept for back-compat. Raised by aggregation.py."""

class CouncilParseError(CouncilError):
    """JSON / response-shape failures."""

class CouncilTimeoutError(CouncilError):
    """Ollama / network timeouts."""

class CouncilAgentDataError(CouncilError):
    """agent_data.py SQLite / DB-shape failures."""

class CouncilProviderError(CouncilError):
    """Ollama / LLM provider HTTP errors."""
```

### 4.7 YAML Config Schema (Wave D — `config/settings.example.yaml` extension)

```yaml
notifications:
  # All keys OPTIONAL — defaults preserve current behavior (everything → telegram, no mute, no digest)
  quiet_hours:
    enabled: false              # default: false (no quiet hours)
    start: '22:00'              # ET, 24h format
    end: '06:00'
    # NOTE: no `bypass_severity` — severity high/critical ALWAYS sends per
    # policy rule #1 (rule precedence in src/notifications/policy.py).
    # quiet_hours only gates severity in {low, medium}.
  mute_event_types: []          # list of event_type strings to silently drop; default: []
  digest_low: false             # default: false; if true, severity=low events buffer to digest queue
  digest_cadence_minutes: 60    # default 60; how often digest flushes; clamped to [1, 1440]
  default_routing:              # default: all events → ['telegram']
    # event_type: [channels]
    trade_opened: ['telegram']
    eod_report: ['email']
  retry:
    attempts: 3                 # default 3; clamped to [1, 10]
    backoff_seconds: [1, 5, 30] # default [1, 5, 30]; one sleep BEFORE each retry attempt after the first; len(backoff_seconds) must equal attempts (last value unused on success path)
    escalation_threshold: 5     # consecutive failures before email-fallback
    escalation_window_minutes: 10
    state_path: 'data/notification_retry_state.json'  # persistent counter
  alert_silence:
    enabled: true               # default: true
    threshold_minutes: 60       # alert if no successful send (or queued event) in this many min during market hours
```

**Validation rules (enforced by `_load_notifications_config`):**
- All event_type strings in `mute_event_types` + `default_routing` MUST be keys of the existing `event_map` dict. Unknown event_type in config raises `NotificationsConfigError` at startup — fail fast, not at dispatch time.
- `quiet_hours.start` / `end` MUST parse as `HH:MM` 24h time. Crossing midnight (22→06) is supported.
- `retry.backoff_seconds` length MUST equal `retry.attempts` (one sleep per attempt; the sleep at index `attempts-1` is unused on success but kept for symmetry and config simplicity).
- Channels MUST be in `{'telegram', 'email', 'both', 'none'}`.

---

## 5. Error Handling

### 5.1 safe_send retry + escalation policy (Wave D)

| Scenario | Behavior | Records |
|---|---|---|
| Attempt 1 succeeds | Status='ok', policy_decision='sent'; reset persistent counter | `notifications_sent` row + retry_state.json reset |
| Attempt 1 fails (network), attempt 2 succeeds | Same as above; log warning; reset counter | `notifications_sent` (status='ok') + retry_state.json reset |
| All 3 attempts fail (network) | status='failed', policy_decision='failed'; increment persistent counter | `notifications_sent` (status='failed') + retry_state.json incremented |
| 5+ failures in 10-min window | policy_decision='escalated'; call `email_notifier.send(subject=f'[ESCALATION] {event_type}', body=...)`. Window resets on next success. Counter survives watch-loop restart. | `notifications_sent` (status='escalated') + email + retry_state.json updated |
| Watch-loop restart mid-outage | retry_state.json loaded on safe_send first call; counter restored; escalation still fires at threshold | retry_state.json read at module init |
| Digest flush-then-fail (M5) | mark_flush_failed: reset flushed_at=NULL, flush_attempts++; on 3rd fail → policy_decision='abandoned', row stays in queue but excluded from future flush_due | notifications_digest_queue update |
| `event_type` not in `event_map` | KeyError raised (SECURITY — unchanged) | None (fail-fast at startup-config-load OR at dispatch) |
| `safe_send` called without `severity=` kwarg | TypeError at call time (severity is required) — caught at test time by AST guardrail | N/A (compile-time-ish) |
| `NotificationsConfigError` at startup | Watch loop fails to start; operator must fix YAML | stderr + sys.exit(1) |

### 5.2 Wave C #68 typed errors

- `agent_data.py` except blocks: classify per error source
  - SQLite errors (`sqlite3.OperationalError`, `psycopg.Error`) → re-raise as `CouncilAgentDataError`
  - `json.JSONDecodeError` / shape mismatches → re-raise as `CouncilParseError`
  - `requests.RequestException` (to Ollama) → re-raise as `CouncilProviderError`
  - Truly unexpected → keep `except Exception` ONLY at the top-level orchestration entry point in engine.py (out of #68 scope per deferral)
- Tests verify that callers can `except CouncilError` and reliably catch all council failures

### 5.3 Wave C #45 drift detection error handling

- If `get_all_positions()` raises (broker network), drift detector LOGS and returns empty list. No drift alert on its own outage (don't alert on alert path).
- If DB read fails, raise `MonitoringDataError` (from `src/monitoring/errors.py`, mirrors the #68 pattern in src/monitoring rather than src/diagnostics).

### 5.4 Wave F #87 fixture error handling

- Docker not installed / not running → `pytest_sessionstart` logs warning, leaves `TEST_DATABASE_URL` unset, parametrized PG variants SKIP (current behavior preserved).
- Container start fails (port conflict, image pull error) → SKIP gracefully, write reason to `pytest_warnings`.
- Container start succeeds but schema bootstrap fails → fail the session with explicit error (developer must fix migration, not silently SKIP).

---

## 6. Testing Strategy

### 6.1 Per-task test additions (projected)

| Wave | Task | New tests | Notes |
|---|---|---|---|
| C | C1 (#54) | +3 | wired call, MC-vote-no-abstain, response shape regression |
| C | C2 (#56 + platform_events) | +6 | schema discipline (strategy_id + platform_events), FK enforcement, filter behavior, FK NOT VALID semantics, platform_events write surface test |
| C | C3 (#68) | +8 | hierarchy structure, each typed exception raises/catches, agent_data error path coverage |
| C | C4 (#45) | +6 | detector with mocked broker/db, threshold boundary, alert dedup, widget data shape, watch-loop hook idempotence, state persistence |
| C | C5 (#47) | +0 | verification doc only |
| C | C6 (#100) | +3 | new scanner self-test, scripts/ scanner self-test, integration on synthetic violation file |
| D | D1 policy | +14 | truth table: severity × quiet-hours × mute-list × digest-low; config validation; cross-midnight quiet hours; severity-high-always-sends short-circuit (4 explicit cases); event_map import-time integration test |
| D | D2 digest_queue | +9 | enqueue, flush_due, cadence boundary, no-double-flush, schema discipline, mark_flush_failed reset, flush_attempts cap-at-3 abandon, digest UNION read in alert_silence |
| D | D3 retry+severity-audit | +9 | 1-attempt success, retry-then-success, 3-fail-then-fail, escalation threshold, persistent-counter survives simulated restart, counter reset on success, narrow-catch invariant, AST guardrail severity-required, audit-receipt: every safe_send call site has literal severity= kwarg |
| D | D4 html-escape + source-tag | +5 | regime_alert escape, streak_alert escape, source_tag column write, pytest source-tag prefix, conftest null-router |
| D | D5 alert_silence | +5 | silence detection, market-hours gate, platform_events forensic write, dashboard widget shape, M3 truth-table digest-only-quiet-period no false fire |
| F | F1 (#15) | +2 | workflow YAML lint, step structure assertion |
| F | F2 (#86) | +0 | restructure existing; verify test count unchanged |
| F | F3 (#87) | net +30-50 | un-SKIPs previously-skipped postgres parametrized variants |

**Total projected:** +95-115 new tests minus the un-SKIPs offset.
**Projected final floor:** 5400-5450. Sprint Close bumps `pg-tests.yml` floor 5050→5350 (50-test conservative margin) AND CLAUDE.md 3682→5350.

### 6.2 AST structural guardrails (per CLAUDE.md PR #1058/#1059/#1060 discipline)

For every NEW module, add a structural test that asserts the bug-class is unrepeatable:

- **policy.py** — `tests/notifications/test_policy_purity.py` asserts `policy.should_dispatch` does NOT import `requests`, `sqlite3`, or `psycopg` (pure function invariant via AST scan of imports)
- **digest_queue.py** — `tests/notifications/test_digest_queue_atomicity.py` asserts `flush_due` filters by `flushed_at IS NULL AND flush_attempts < 3` AND `mark_flush_failed` resets `flushed_at=NULL` (idempotence + recovery invariant)
- **safe_send retry** — `tests/notifications/test_safe_send_catch_discipline.py` AST-scans the file and asserts the network-except clause's exception tuple equals exactly `(urllib3.HTTPError, requests.RequestException, socket.timeout, OSError)`. Prevents future widening to `except Exception`.
- **safe_send severity** — `tests/notifications/test_safe_send_severity_required.py` AST-scans ALL `safe_send(` call sites across `src/` AND asserts each one passes a literal `severity=...` kwarg. Closes the M1 silent-downgrade gap.
- **manual_intervention_drift.py** — `tests/monitoring/test_drift_detector_no_recursion.py` asserts the detector does NOT call `safe_send('manual_intervention_drift', ...)` from within its own alert path (prevents alert-on-alert recursion)
- **event_map** — `tests/notifications/test_event_map_load_order.py` imports `src.main` then loads a sample config that references `manual_intervention_drift` + `alert_silence` event types and asserts validation passes (MIN7 anchor)

### 6.3 Existing-test sibling-search (per memory `feedback_review_sibling_search`)

Each developer MUST grep for the pattern they're fixing across the file AND across `src/` before claiming task done:
- C1 dev: grep `_compute_promotion_gate_kpi(` across `src/api/` for any other callers passing only `(n_trades, returns)`
- D3 dev: grep `safe_send(` across `src/` AND `tests/` — receipt of every call site's intrinsic severity classification (M1 audit)
- D4 dev: grep for `f'...{<var>}'` style HTML interpolation across all `notify_*` functions, not just regime + streak
- C6 dev: grep for `[r[N] for r in` across `src/` AND `scripts/` to confirm the scanner extension catches all live sites

### 6.4 Visual-verify gate (per memory `feedback_visual_verify_ui`)

New dashboard widgets that ship in this sprint:
- **D5 alert silence widget** — browser-render via `cd frontend && npm run dev`, screenshot included in PR body
- **C4 drift detection widget** — same discipline
- **Notifications routing config preview** (D1 add-on — optional, but recommended): a `GET /api/notifications/policy-preview` endpoint that returns the current effective config + a sample dispatch decision for every event_type. Surface via dashboard so operator can answer "what would fire right now?"

### 6.5 Worktree isolation (per CLAUDE.md)

ALL parallel agent dispatches use `isolation: "worktree"`. Sequencing constraint: when two tasks edit the same file (e.g., C4 + D2 + D5 all edit `src/scheduler/watch.py`), they MUST run sequentially OR the PM coordinates rebasing via per-wave PR sequencing (deep-report's preferred path: C4 lands first, then D2 rebases, then D5 rebases).

### 6.5.1 PM serial-dispatch detection mechanism (MIN1 anchor)

For the three tasks that edit `src/scheduler/watch.py` (C4=Task 4, D2=Task 11, D5=Task 14), PM enforces serial dispatch as follows:

1. **Pre-dispatch check (Glob-based):** Before dispatching task N+1, PM runs:
   ```bash
   git fetch origin
   gh pr list --base main --head <task-N-branch> --state merged --json mergedAt
   ```
   If task N's branch has NOT been merged to origin/main, PM does NOT dispatch task N+1. PM emits a status update "Waiting for Task N merge before Task N+1 dispatch" and re-checks every 5 min.

2. **Falsifiability trigger:** if PM dispatches task N+1 while task N's branch is unmerged (e.g., agent timeout race), task N+1 agent's first verification step is to run `git log origin/main --grep '<task-N-marker>' --oneline | wc -l` and refuse to start work if zero matches. Logs the violation to `.claude/serial-dispatch-violations.json` for operator post-mortem.

3. **Watch.py declared-scope grep:** Before dispatching ANY task with `src/scheduler/watch.py` in `files_in_scope`, PM globs:
   ```bash
   git -C <each-worktree> diff --name-only origin/main -- src/scheduler/watch.py
   ```
   across all currently-active worktrees. If more than one worktree has modified watch.py vs main, PM blocks dispatch.

---

## 7. Operational Notes

### 7.1 Operator-guide additions (per CLAUDE.md same-PR mandate)

**Wave D PR adds `docs/operator-guide.md` section "Notifications routing":**
- YAML config location: `config/settings.local.yaml` under `notifications:` key
- Schema reference: link to `config/settings.example.yaml` for live keys
- "How to inspect what would fire": `GET /api/notifications/policy-preview` URL
- Escalation expectation: "After 5 consecutive failures in 10 min, alerts route to email — check inbox if Telegram quiet during market hours. Counter persists across watch-loop restarts via `data/notification_retry_state.json`."
- Source-tag explanation: "`[unknown]` prefix on a Telegram message means the watch loop's `ARCIS_NOTIFICATION_SOURCE` env var was not set. If you see `[unknown]` in production, the NSSM AppEnvironmentExtra is missing — set it via `nssm edit <svc>` and restart. `[pytest:<worktree>]` prefix means a worktree-isolated pytest run leaked through env vars — should not happen post-Sprint-5 conftest fix; report if seen."
- NSSM env config: explicit registry path `HKLM\SYSTEM\CurrentControlSet\Services\<svc>\Parameters\AppEnvironmentExtra` add line `ARCIS_NOTIFICATION_SOURCE=watch-loop`

**Wave C PR adds section "Drift detection":**
- Alert format: "`Manual intervention drift detected: AAPL broker=100, db=150, persisted 35min`"
- How to silence: edit `config/settings.local.yaml` `diagnostics.drift_detection.enabled: false`
- Recovery procedure: reconcile via `python -m src.main reconcile-positions`
- Module location: `src/monitoring/manual_intervention_drift.py` (distinct from `src/diagnostics/` statistical methodology package)

**Wave F PR adds section "CI checks":**
- Stale-base check: "PR will fail merge if its branch is behind `origin/main`. Rebase locally + force-push to refresh."
- Bypass: documented but discouraged ("`git push --no-verify` only for emergency hotfix; expect operator review")

**Sprint Close PR adds section "Sprint 5 closeout state":**
- Version: v0.35.0
- New behaviors: notifications routing, drift detection, alert silence, stale-base CI
- Deferred: dual-GPU implementation, council engine.py/value_tracker.py except refactor, alpaca_adapter.py split
- Active track: walk-forward framework (separate roadmap entry — MUST treat `shadow_trades.strategy_id` FK as deprecation candidate per §1.3)

### 7.2 Roadmap (`docs/roadmap.md` — NEW)

Structure (created in Sprint Close PR):
```markdown
# Arcis Roadmap

## Sprint history
| Sprint | Date closed | Headline |
|---|---|---|
| Sprint 0 | 2026-04-25 | Repo structure + scope checks |
| Sprint 1 | 2026-04-27 | PIT discipline + universe T10 migration |
| Sprint 2 | (date) | Promotion gate methodology |
| Sprint 3 | (date) | Cost model wiring (#79) |
| Sprint 4 | 2026-05-08 | safe_send dispatcher + email hardening |
| Sprint 5 | 2026-05-XX | Notifications routing + cross-engine hardening + data integrity |

## Active track
- **Walk-forward framework** (post-Sprint-5) — see `docs/audits/<future-spec>.md`. Schema obligation: design migration to replace the `shadow_trades.strategy_id → strategy_registry.strategy_id` FK introduced in Sprint 5 Task 2.

## Deferred
- Dual-GPU workload separation (`docs/audits/2026-05-12-dual-gpu-ideation/`)
- Council engine.py + value_tracker.py except-block refactor (post-Sprint-5; #68 sibling)
- alpaca_adapter.py file split (post-Sprint-5; #97)
```

### 7.3 Test floor canon refresh

Sprint Close PR updates THREE locations:
- `CLAUDE.md` test floor line (currently 3682) → 5350 + lineage paragraph noting the projection. **Lineage entry must read: "3682 (Sprint 1.A.1) → 5050 (Sprint 4 close, pg-tests.yml floor) → 5350 (Sprint 5 close: +95-115 new tests from Waves C+D+F, conservative 50-test buffer below projected median)."**
- `.github/workflows/pg-tests.yml` floor (currently 5050) → 5350
- `CHANGELOG.md` v0.35.0 section documents the floor lineage explicitly so future agents can audit drift

### 7.4 Per-wave CHANGELOG entries (vs Sprint Close aggregation)

Each wave PR adds entries to `[Unreleased]` (per CLAUDE.md). Sprint Close PR aggregates all of these into a single `## [v0.35.0] - 2026-05-XX — Sprint 5 close` section, organized by subsection (Wave C / Wave D / Wave E / Wave F).

### 7.4.1 CHANGELOG aggregation rule (MIN4 anchor)

Sprint Close aggregation procedure:

(a) **Verbatim copy-paste preserves audit trail.** Each `[Unreleased]` entry written by a wave PR is moved verbatim (same wording, same bullet structure) into the `[v0.35.0]` section. No rewording, no "polishing." The audit trail must show that the closeout aggregation is mechanical.

(b) **Deduplicate meta-entries.** Repeated bullets like "Updated operator-guide" or "Bumped test floor" that appear in multiple wave PRs are consolidated into ONE bullet in the Close section. Wave-specific bullets stay distinct.

(c) **Within-wave order = task-id order.** Inside each wave subsection (C / D / E / F), bullets are ordered by ascending task id (C1, C2, C3, ... ; D1, D2, ...). This makes diff-review predictable across closeouts.

(d) **`[Unreleased]` header retained, body emptied.** After move, `## [Unreleased]` heading remains at the top of CHANGELOG.md with an empty body, ready for the next sprint's entries. Do NOT delete the heading.

---

## 8. File Inventory

### 8.1 New files

| Path | Created by | Purpose |
|---|---|---|
| `src/notifications/policy.py` | D1 | Pure-function policy gate |
| `src/notifications/digest_queue.py` | D2 | DB-backed digest buffer |
| `src/monitoring/__init__.py` | C4 | New operational alerting package |
| `src/monitoring/errors.py` | C4 | MonitoringDataError |
| `src/monitoring/manual_intervention_drift.py` | C4 | Drift detector |
| `src/monitoring/alert_silence.py` | D5 | Alert silence detector |
| `data/notification_retry_state.json` | D3 (runtime-created) | Persistent retry counter |
| `tests/notifications/test_policy.py` | D1 | Policy truth table |
| `tests/notifications/test_policy_purity.py` | D1 | AST guardrail |
| `tests/notifications/test_event_map_load_order.py` | D1 | MIN7 integration test |
| `tests/notifications/test_digest_queue.py` | D2 | State machine tests |
| `tests/notifications/test_digest_queue_atomicity.py` | D2 | AST/SQL guardrail + flush_failed recovery |
| `tests/notifications/test_safe_send_retry.py` | D3 | Retry + escalation + persistent counter |
| `tests/notifications/test_safe_send_catch_discipline.py` | D3 | AST guardrail on except tuple |
| `tests/notifications/test_safe_send_severity_required.py` | D3 | AST guardrail: every call site has literal severity= |
| `tests/notifications/test_html_escape_siblings.py` | D4 | regime + streak escape tests |
| `tests/monitoring/__init__.py` | C4 | Test package init |
| `tests/monitoring/test_manual_intervention_drift.py` | C4 | Drift detector unit tests |
| `tests/monitoring/test_drift_detector_no_recursion.py` | C4 | AST guardrail |
| `tests/monitoring/test_alert_silence.py` | D5 | Silence detector tests + M3 digest-UNION truth-table |
| `tests/council/test_typed_errors.py` | C3 | Council error hierarchy |
| `docker-compose.test.yml` | F3 | PG test container |
| `.github/workflows/stale-base-check.yml` | F1 | Server-side stale-base gate |
| `tests/workflows/test_stale_base_check.py` | F1 | YAML lint + structure |
| `docs/audits/2026-05-07-telegram-email-sweep/triage-disposition.md` | C5 | 50-finding disposition |
| `docs/audits/2026-05-12-dual-gpu-ideation/disposition.md` | E1 | Wave E deferral note + 4 stale-text fix anchors |
| `docs/roadmap.md` | Sprint Close | Sprint history + active track |

### 8.2 Modified files

| Path | Modified by | Change |
|---|---|---|
| `src/api/cloud_routes/kpis.py` | C1 | Line 128: pass `dates` + `directions` |
| `src/api/cloud_routes/kpis_compute.py` | C2 | `_fetch_closed_trades` adds optional `strategy_id` filter |
| `src/schema/registry.py` | C2, D2, D3 | strategy_id ColumnDef+FK (NOT VALID); platform_events TableDef; notifications_digest_queue TableDef (+ flush_attempts col); severity/policy_decision/source_tag columns on notifications_sent |
| `src/council/errors.py` | C3 | Add 4 typed exception classes |
| `src/council/agent_data.py` | C3 | Replace 28 `except Exception` blocks with typed catches |
| `src/notifications/telegram.py` | D1, D3, D4, C4, D5 | Insert policy gate at line 1234; replace single-attempt send with retry+escalate (persistent counter) at 1299; apply `_html_escape` at lines 780+805; severity made required kwarg; read `ARCIS_NOTIFICATION_SOURCE` env (default 'unknown'); add `manual_intervention_drift` + `alert_silence` to event_map at module-import time |
| `src/scheduler/watch.py` | C4, D2, D5 | Drift detector tick (every 30 min); digest flush tick (every 5 min); alert silence tick (every 5 min during market hours). SEQUENCE: C4 first, D2 rebases, D5 rebases. |
| `tests/conftest.py` | D4, F3 | `ARCIS_NOTIFICATION_SOURCE='pytest:<worktree>'`; `_send_telegram` null-router monkeypatch; `pytest_sessionstart`/`finish` docker-compose hooks |
| `tests/test_no_fetchone_int_index_in_pg_unsafe_files.py` | C6 | Add `test_no_fetchall_list_comp_int_index_in_pg_unsafe_files`; add scripts/ scanner |
| `tests/api/test_status.py`, `tests/test_cloud_app.py`, `tests/test_shadow_desk_filter.py` | F3 | Un-hardcode `TEST_DATABASE_URL` |
| `.github/workflows/pg-tests.yml` | F3, Sprint Close | Drop test/test role creation step; bump test floor 5050→5350 |
| `tests/test_cloud_requirements_imports.py` | F2 | Session-scoped shared-venv restructure |
| `config/settings.example.yaml` | D1 | Add `notifications:` section schema example (no `bypass_severity`) |
| `docs/operator-guide.md` | Wave D, C, F, Close | Sections: Notifications routing (incl. NSSM env), Drift detection, CI checks, Sprint 5 closeout state |
| `CLAUDE.md` | Sprint Close | Test floor 3682→5350; lineage note |
| `CHANGELOG.md` | Every wave + Close | Per-wave entries in `[Unreleased]`; Close aggregates per §7.4.1 |
| `src/version.py` | Sprint Close | `'v0.34.0'` → `'v0.35.0'` |
| `config/known_violations.json` | Sprint Close | Add `tests/shadow_trading/test_alpaca_adapter_split.py` entry (#97 grandfather) |
| `tests/shadow_trading/test_alpaca_adapter_split.py` | Sprint Close | Delete (sentinel obsolete after grandfather) |
| `docs/audits/known-pre-existing-failures.md` | Sprint Close | Refresh stale 34-failure canon to current state |
| `docs/audits/2026-05-12-dual-gpu-ideation/specs/2026-05-12-dual-gpu-workload-separation-design.md` | E1 | Apply 4 stale-text fixes inline (test floor, Sprint 6 refs, Unsloth refs, NUM_PARALLEL) — MIN5 |
| `scripts/render_migrate.py` | C2, D2, D3 | Emits NOT VALID FK syntax for shadow_trades_strategy_id_fkey; outputs included in PR bodies |

### 8.3 Cosmetic `_scalar` removal (Sprint Close)

Mechanical revert of `_scalar` helper usage across 82 call sites (now redundant post-PR-1060). Touched files limited to:
- `src/utils/db.py` (helper definition)
- Per-call-site files (~30 estimated; PM dispatch as a single-developer mechanical sweep with sibling-search confirmation)

If scope balloons (>40 files), PM defers to post-Sprint-5 and notes in Close PR body. Reversal cost: trivial.

---

## 9. Known Considerations (Devil's-Advocate-anticipated risks)

### 9.1 Wave D config attack surface

**Risk:** YAML parsing of operator config introduces injection or DoS surface.
**Mitigation:**
- All event_type values in config MUST be validated against the existing `event_map` keys at startup (`NotificationsConfigError` on unknown key). Closes the dynamic-dispatch risk preserved from Sprint 4 T2.
- All time strings parsed via `datetime.strptime(s, '%H:%M')` — raises ValueError on malformed input → fail-fast at startup
- `digest_cadence_minutes` clamped to [1, 1440] range; reject silently-huge values that would queue events indefinitely
- `retry.attempts` clamped to [1, 10]; `backoff_seconds` clamped per-element to [0, 300]
- No YAML `!include` or other tag interpolation — uses `yaml.safe_load` (existing project convention)

### 9.2 Digest-mode-delays-critical regression

**Risk:** A severity=critical event gets buffered to digest and an outage goes unnoticed for 60 min.
**Mitigation:**
- `policy.should_dispatch` rule #1: severity ∈ {high, critical} → always action='send', UNCONDITIONAL. No bypass_severity config knob (removed in v2 per M2 — rule #1 IS the bypass).
- AST guardrail `test_policy_severity_high_always_sends` asserts the function returns `action='send'` for severity='critical' regardless of any other config flag combination.
- Code review checklist: any future PR that changes `should_dispatch` MUST not modify the rule-1 short-circuit. Reviewer dispatch matrix includes Security.

### 9.3 Retry storms on sustained outage

**Risk:** If Telegram is down for hours, every alert spends 1+5+30=36s in retry before failing. Watch loop blocks.
**Mitigation:**
- After 5 consecutive failures in 10-min window, `_send_with_retry` SKIPS attempts 2+3 and goes straight to email-escalation. Closes the "every alert burns 36s" failure mode.
- Counter persisted to `data/notification_retry_state.json` so escalation behavior survives NSSM watch-loop restart (M4 resolution). Without persistence, restarts during sustained outages would reset counter and the very F2 scenario this mitigates would never reliably trigger.
- Retry sleeps wrapped in `time.sleep` — acceptable for watch loop's notification path (not in critical signal computation path).
- Telemetry: consecutive failure count surfaced via dashboard widget so operator sees the outage signal without waiting for the alert-silence detector.

### 9.4 Source tag confusion

**Risk:** Operator confuses `[pytest:<worktree>]` prefixed messages with real alerts, OR misses `[unknown]` tags signaling NSSM env misconfig.
**Mitigation:**
- `tests/conftest.py` ALSO monkeypatches `_send_telegram` to a null-router — pytest cannot actually call Telegram API even if env var leaks. Defense in depth.
- Default `source_tag='unknown'` (not `'watch-loop'`) fails LOUD when env var absent. NSSM service config MUST set `AppEnvironmentExtra=ARCIS_NOTIFICATION_SOURCE=watch-loop`. Operator-guide documents the registry path.
- AST guardrail in `tests/notifications/test_safe_send_pytest_isolation.py` confirms that under pytest, `_send_telegram` is monkeypatched (asserts `_send_telegram.__name__ == '_null_router'`).

### 9.5 Wave C #68 typed-except may surface previously-swallowed bugs

**Risk:** Tightening exception handling in agent_data.py exposes latent bugs that were previously silent.
**Mitigation:**
- PR body discloses expected behavior change
- Canary deploy: operator restarts watch loop via NSSM after merge, eyes-on for 1h with dashboard open
- Each typed exception class has a `safe_send`-able representation so surfacing bugs become real alerts, not silent regressions

### 9.6 #54 directions-wiring flips promotion_gate decisions

**Risk:** Strategies that were 'defer' due to MC ABSTAIN flip to 'reject' or 'promote' — a SEMANTIC change.
**Mitigation:**
- Pre-merge: C1 developer runs `promotion_gate` against current closed trades, includes the votes_passed-delta table in PR body
- CHANGELOG entry explicitly documents the shift; operator can choose to roll back via 1-LOC revert if delta is unacceptable
- Reviewer dispatch includes Performance reviewer (math correctness verification)

### 9.7 #100 scanner extension may produce noisy violations across `scripts/`

**Risk:** Adding `scripts/` to scanner coverage uncovers dozens of pre-existing violations.
**Mitigation:**
- C6 developer first runs the scanner with allowlist=[] against scripts/ and reports the count
- If count > 5, the spec'd fix is to land scanner extension with a populated allowlist matching current violations + a TODO entry in `docs/audits/known-pre-existing-failures.md`. The PR's MERIT is preventing FUTURE violations; existing ones are documented as pre-existing.
- If count ≤ 5, fix in same PR (preferred)

### 9.8 Worktree env drift (per memory `feedback_worktree_env_drift`)

**Risk:** Wave D tests pass in agent worktree but fail post-merge because worktree doesn't carry operator's .env values.
**Mitigation:**
- All Wave D tests use `monkeypatch.setenv` to set required env vars hermetically
- D4 explicitly tests the `ARCIS_NOTIFICATION_SOURCE` env var path with both set and unset cases (unset → 'unknown' fail-loud)
- `tests/conftest.py` already clears `ARCIS_LOCAL_API_TOKEN` per-test (per #729 pattern); extend to ALSO clear `ARCIS_TELEGRAM_TOKEN` to prevent worktree env leakage

### 9.9 Concurrent edits to src/scheduler/watch.py (C4 + D2 + D5)

**Risk:** Three tasks all add new hooks to the watch loop; parallel agent dispatches collide.
**Mitigation:** PM enforces sequential dispatch for these three tasks per §6.5.1 detection mechanism. Wave C #45 (C4) lands first; Wave D digest flush (D2) rebases on C4; Wave D alert silence (D5) rebases on D2. Each task's PR diff cleanly adds an isolated hook.

### 9.10 #87 docker-compose port 5433 conflict

**Risk:** Operator may have other PG instances or test containers on 5433.
**Mitigation:**
- F3 developer confirms `localhost:5433` is free via `netstat` before committing
- `docker-compose.test.yml` documents port as configurable via `TEST_PG_PORT` env var (default 5433)
- Fallback to 5434, 5435 documented in operator-guide

### 9.11 Alert silence false-fire during digest-only periods (M3)

**Risk:** During market-hour periods with ONLY severity=low events buffered to digest queue (no immediate sends), the silence detector reads only `notifications_sent` and false-fires after 60 min.
**Mitigation:** alert_silence detector reads UNION of `notifications_sent.sent_at`, `notifications_digest_queue.flushed_at`, AND `notifications_digest_queue.enqueued_at`. The 3rd term proves the watch loop IS receiving events even when nothing has fired. Explicit truth-table test: `digest_cadence=60 + alert_threshold=60 + low-only events for 90 min → returns None (no false silence)`.

### 9.12 Coverage gaps from deep-report

The deep-codebase-report `coverage_gaps[]` flags these areas as NOT-fully-read; spec calls them out so per-task developers re-read as their first step:
- `src/email/digest_builder.py` past line 80 (Wave D digest cadence may need to mirror; D2 developer reads full file as first step)
- `src/shadow_trading/reconcile.py` past line 60 (Wave C #45 detector should align with reconcile patterns; C4 developer reads first)
- `src/council/engine.py` + `value_tracker.py` (C3 task confirms scope-out by re-reading except patterns)
- `tests/test_cloud_requirements_imports.py` past line 100 (F2 developer reads first)
- `src/api/cloud_routes/kpis_compute.py` past line 400 (C2 developer reads `_fetch_closed_trades` signature)
- `config/settings.local.yaml` (operator file; D1 developer references `config/settings.example.yaml` as schema source)
- `tests/email/test_notifier.py` (C5 verifies via Glob)

---

## 10. Design Decisions Table

| # | Decision | Rationale | Alternatives considered | Reversal cost | Source |
|---|---|---|---|---|---|
| 1 | Wave E: DESIGN-ONLY, defer impl post-Sprint-5 | Spec says "deferred to SP6" — but no SP6. No current bottleneck demands impl. Reversible: spec is the deliverable. | Implement in SP5 (~1.5 days; low blast-radius); skip entirely (lose spec discipline) | Low — operator can opt-in impl in any post-sprint maintenance window | Operator CHECKPOINT 2026-05-12 |
| 2 | Version bump: MINOR (0.35.0) | Wave D ships new YAML config surface; Wave C #56 ships new schema column; Wave C #45 ships new event_type. All backward-compat additions per versioning policy. | Patch (0.34.1 — but additions aren't pure fixes); major (0.35→1.0 — premature) | Trivial (1-line string change) | Operator CHECKPOINT 2026-05-12 |
| 3 | Wave D defaults: BACKWARD-COMPAT | Zero-config users see no change; operator opts in. Minimizes blast radius. | Opt-out (quiet hours on by default — risk of suppressing real alerts before operator notices) | Zero (operator deletes config keys to restore) | Operator CHECKPOINT 2026-05-12 |
| 4 | PR boundary: PER-WAVE PRs (6 total) | Matches recent successful #1058/#1059/#1060 cadence. Smaller review surface; smaller blast radius per merge. | Monolithic Sprint Close PR (worse review surface, harder rollback) | Low (PM can batch-merge with single CHANGELOG section) | Operator CHECKPOINT 2026-05-12 |
| 5 | `docs/roadmap.md`: CREATE NEW | Sprint history + active-track pointer is distinct from operator-runnable runbook content. Cleaner separation. | Fold into `docs/operator-guide.md` Sprint history section (mixed concerns) | Low (file move + redirect-pointer) | Operator CHECKPOINT 2026-05-12 |
| 6 | #97 alpaca_adapter: GRANDFATHER + delete sentinel test | File split is high-blast-radius. Sentinel test currently incongruent. Cleanest fix: known_violations.json entry + delete sentinel. | Actually split file in SP5 (>4 hrs work, touches every alpaca call site); accept failing test (governance violation) | Low (operator can split in any post-sprint PR) | Operator CHECKPOINT 2026-05-12 |
| 7 | **#96 platform_events: RESOLVED-BY-C2** (revised v2) | C2 adds the `platform_events` TableDef unconditionally because both D5 alert_silence AND C4 drift detector are canonical write-sites for forensic trail. Decoupling: single schema change shared by 2 consumers, no fallback file-path complication, retires #96 outright. | (a) D5 unconditionally adds TableDef (rejected: schema change in D wave's surface, harder review); (b) Replace platform_events with JSONL file (rejected: forensic trail loses queryability + bifurcates audit surface); (c — CHOSEN) C2 owns TableDef, both D5 + C4 write to it | Low (TableDef + 2 write-sites; revert if needed) | Architect (C1 resolution) |
| 8 | #68 reframe: typed hierarchy + agent_data.py only (28 except blocks) | Brief premise WRONG — only 1 raise site exists; real opportunity is 28 bare except Exception in agent_data.py (corrected from v1 '30+' per actual grep count). Engine.py + value_tracker.py deferred. | Refactor all of council/ (>2x scope; risks Sprint 5 close slip); skip entirely (misses safety improvement) | Low (post-sprint sibling work can extend) | Architect (deep-report) |
| 9 | safe_send policy gate inserted IN-PLACE (no separate router module) | Duplicating event_map in a parallel router.py would weaken the KeyError-on-unknown-event_type security boundary. | New `src/notifications/router.py` module (parallel surface; harder to reason about composition) | Low (in-place insert is easily revertable) | Architect (Sprint 4 T2 security carry-forward) |
| 10 | Digest queue: DB-backed not in-memory | Watch loop restarts must not lose buffered events. SQLite/PG durability is the existing pattern. | In-memory deque (data loss on restart); Redis (new infrastructure dependency) | Low (table drop + module remove) | Architect |
| 11 | Source tag column added to notifications_sent (not separate audit table) | Notifications_sent already tracks every dispatch; source_tag is per-row metadata, not a separate event stream. | New `notification_audit` table (duplication; two-way join overhead) | Low (column drop) | Architect (#101 design) |
| 12 | Retry policy: 3 attempts with [1, 5, 30]s backoff | Tuned to Telegram's intermittent failure rate (F2: 2-3 failures/hour). Total wait per failed event = 36s, acceptable for non-hot-path. | Single attempt (current — too brittle); 5+ attempts (DoS risk) | Trivial (config tunable) | Architect (F2 mitigation) |
| 13 | Escalation: 5 failures in 10 min → email fallback | Captures sustained outages while tolerating transient blips. Email is the operator's secondary channel. | No escalation (F2 blind spot persists); SMS (new dep) | Trivial (config tunable) | Architect (F2 mitigation) |
| 14 | Sequence C4 → D2 → D5 for `src/scheduler/watch.py` edits | Three tasks edit the same file. Sequential PRs avoid worktree race. C4 lands first because Wave C precedes Wave D per glidepath. PM enforcement detection per §6.5.1. | Parallel + manual merge resolution (race risk per memory `feedback_review_sibling_search`) | Low (each PR is independent rebase) | Architect |
| 15 | Wave F #87 PG port 5433 (not 5432) | Avoid clash with operator's local PG (memory `reference_local_ports`: 8080 EnterpriseDB; PG on 5432 is operator's). | 5432 (collision risk); random port (test fixture complexity) | Trivial (port reassignment) | Architect (memory-grounded) |
| 16 | Test floor canon: 5350 (50-test conservative buffer below projected 5400-5450 median) | Projection has +/- range; 50-test conservative margin prevents flaky-test-day floor failures. | 5400 (tighter, risk transient drops); 5050 (no progress) | Trivial (CLAUDE.md + pg-tests.yml number) | Architect |
| 17 | `_scalar` cosmetic removal: SAME PR as Sprint Close, with scope-cap | Sprint Close is the natural home; ~30 file mechanical sweep is cosmetic, not architectural. Scope-cap: if >40 files, defer to post-sprint. | Standalone PR (PR count inflation); never remove (helper rots) | Trivial (already a mechanical revert) | Architect (post-PR-1060 cleanup) |
| 18 | **`safe_send` severity is REQUIRED kwarg (no default)** (NEW v2 — M1) | Default 'medium' would silently downgrade unclassified events; existing call sites would never be audited. Required kwarg forces every call site to explicitly classify severity at build time. AST guardrail enforces. | Default to 'medium' (rejected: silent downgrade, no audit trigger); default to 'low' (rejected: silently buffers to digest); detect+warn at runtime (rejected: warnings get ignored) | Low (D3 developer audits + updates every call site; AST guardrail prevents regression) | Architect (devil's-advocate M1) |
| 19 | **`ARCIS_NOTIFICATION_SOURCE` default = 'unknown' (fail-loud), NOT 'watch-loop'** (NEW v2 — MIN2) | arcis:code agents that run `python -m src.main` without NSSM inherit no env var. v1 default 'watch-loop' would silently mislabel them. 'unknown' makes the misconfig visible in Telegram messages (`[unknown]` prefix). NSSM AppEnvironmentExtra entry required and documented. | Default 'watch-loop' (v1 — fail-silent on misconfig); error-on-missing-env (rejected: would prevent any non-NSSM startup) | Trivial (default string change + NSSM env entry) | Architect (devil's-advocate MIN2) |
| 20 | **`quiet_hours.bypass_severity` config knob REMOVED — rule #1 IS the bypass** (NEW v2 — M2) | v1 spec declared `bypass_severity: critical` but rule precedence already had severity ≥ high → always send. The config knob was unreachable code (high/critical sent at rule #1 before quiet_hours ever evaluated). Removing the knob makes the truth table honest. | Restructure rules to put quiet_hours first + bypass_severity threshold (rejected: makes "critical during quiet hours" rule-dependent + harder to reason about); keep both (rejected: dead config knob lies to operator) | Trivial (YAML schema removal; truth-table tests updated) | Architect (devil's-advocate M2) |
| 21 | **Retry counter persisted to `data/notification_retry_state.json`** (NEW v2 — M4) | In-memory counter resets on every NSSM watch-loop restart. During the very F2 scenario this mitigates (sustained Telegram outages spanning restarts), escalation would never fire. JSON file follows the **new** `data/drift_detector_state.json` pattern introduced in Task 4 (atomic write via tmp+os.replace, JSON-serializable singleton state, module-init load). Both state files share the same shape so memory `feedback_backfill_patterns` applies uniformly. Loaded on safe_send module init, written after each attempt outcome. | DB table (rejected: schema bloat for 1-row state); ignore restart durability (rejected: defeats M4 mitigation); in-memory only with restart-immune singleton lock (rejected: complexity vs JSON file) | Trivial (file path change; module-init read; per-write atomic replace) | Architect (devil's-advocate M4; pattern corrected per PR #1061 review) |
| 22 | **Digest flush-then-fail: reset `flushed_at=NULL` + `flush_attempts++`, cap at 3 → `abandoned`** (NEW v2 — M5) | v1 marked flushed_at=now_et BEFORE dispatching; on retry-fail the row was permanently lost. Revised: `mark_flush_failed(row_id)` resets flushed_at + increments flush_attempts; flush_due filters `flush_attempts < 3`; 3rd fail marks `policy_decision='abandoned'` (visible forensically, never retried). Preserves no-data-loss invariant. | Mark flushed_at AFTER dispatch succeeds (rejected: SELECT … FOR UPDATE SKIP LOCKED gets complex for SQLite path); drop event silently on 1st fail (rejected: data loss); infinite retry (rejected: zombie queue rows) | Low (schema adds `flush_attempts` col + mark_flush_failed function; tests cover) | Architect (devil's-advocate M5) |
| 23 | **EXTEND existing `src/monitoring/` package with operational alerting modules** (NEW v2 — FEAS2; corrected per PR #1061 review) | `src/diagnostics/` is dedicated to statistical methodology per its `__init__.py` docstring. Operational alerting (drift detection, alert silence) is a distinct category. **`src/monitoring/` already exists** (currently `system_metrics.py` — GPU/CPU/RAM/disk/Ollama health) and is the natural home for additional operational health detectors. Sprint 5 ADDS modules to this existing package; the original "create new package" framing in v1 was a grounding error. Update `__init__.py` docstring from "System monitoring — GPU, CPU, RAM, disk, Ollama health tracking" to "System monitoring + operational alerting — health metrics and divergence detectors". | (a) `src/diagnostics/operations/` subpackage (rejected: still nested under statistical-methodology root); (c) Accept mixing with doc note (rejected: docstring becomes a lie); (b — CHOSEN) extend existing `src/monitoring/` package | Low (file additions; no API breakage; preserves `system_metrics.py`; import paths in watch.py + tests added) | Architect (devil's-advocate FEAS2 + PR #1061 grounding fix) |
| 24 | **FK creation uses `NOT VALID` + deferred `VALIDATE CONSTRAINT`** (NEW v2 — MIN3) | PostgreSQL `ADD CONSTRAINT ... FOREIGN KEY` without NOT VALID locks the table during the validation scan (AccessExclusiveLock). shadow_trades is hot. NOT VALID adds constraint metadata-only (no lock); `VALIDATE CONSTRAINT` later takes only ShareUpdateExclusiveLock (concurrent reads + writes allowed). Operator triggers validation off-hours. SQLite ignores NOT VALID — constraint enforced on next insert. | Block insert during VALIDATE (rejected: shadow_trades is read by KPIs during market hours); skip FK entirely (rejected: loses referential integrity); inline VALIDATE during business hours (rejected: lock risk) | Trivial (DDL syntax change in render_migrate.py; deferred-validate flag) | Architect (devil's-advocate MIN3) |

---

## 11. Do-Not-Do (explicit anti-requirements)

- DO NOT create a parallel `src/notifications/router.py` module. Modify `safe_send` in-place.
- DO NOT widen `safe_send`'s narrow network-except tuple. AST guardrail enforces.
- DO NOT add YAML `!include` or other tag-interpolation parsing. Use `yaml.safe_load` only.
- DO NOT make `event_map` mutable / dynamically extensible via config. Config REFERENCES existing keys. event_map additions land at module-import time only.
- DO NOT refactor `engine.py` or `value_tracker.py` `except Exception` blocks in #68. Scope-defer per deep-report.
- DO NOT actually split `alpaca_adapter.py` in this sprint. Grandfather per Decision 6.
- DO NOT add the `quiet_hours.bypass_severity` config knob — rule #1 IS the bypass (Decision 20). Severity ≥ high unconditionally sends.
- DO NOT call `safe_send(event_type, ...)` without a literal `severity=` kwarg. AST guardrail enforces; severity is keyword-only required (Decision 18).
- DO NOT default `ARCIS_NOTIFICATION_SOURCE` to `'watch-loop'` — fail-loud default is `'unknown'` (Decision 19).
- DO NOT keep the retry counter in-memory only — it MUST persist to `data/notification_retry_state.json` (Decision 21).
- DO NOT mark `flushed_at=now_et` before dispatch succeeds without the `mark_flush_failed` recovery path (Decision 22).
- DO NOT put operational alerting modules in `src/diagnostics/` — use the new `src/monitoring/` package (Decision 23).
- DO NOT issue PG `ADD CONSTRAINT … FOREIGN KEY` for shadow_trades without `NOT VALID` (Decision 24).
- DO NOT implement Wave E in this sprint. Disposition doc only (but APPLY 4 stale-text fixes inline).
- DO NOT bump test floor without verifying actual sweep count first (avoid 3682→5350 → ghost-floor failure).
- DO NOT skip the operator-guide update per CLAUDE.md rule.
- DO NOT defer CHANGELOG entries — each wave PR updates `[Unreleased]`, Sprint Close aggregates per §7.4.1.
- DO NOT use `git push --no-verify` on any of these PRs (no emergency hotfix justification).
- DO NOT introduce a new bare `except Exception` anywhere. Use typed catches.
- DO NOT call real Telegram API from pytest. Conftest null-router is mandatory.

---

## 12. Falsifiability Triggers

The spec is INVALIDATED (and must be revised) if any of the following surface during execution:

- **Wave C #56**: `strategy_registry` TableDef does NOT exist or its PK column name is unknown — spec must revise FK target before PR
- **Wave C #45**: `alpaca_adapter.get_all_positions()` does NOT return a usable `{ticker: qty}` shape — spec must revise drift comparison surface
- **Wave C platform_events**: a write-site for `platform_events` is discovered in src/ OUTSIDE the new C4 + D5 paths — spec must reconcile new TableDef shape with discovered write-site's column expectations
- **Wave D D1**: existing `event_map` dict at `telegram.py:1287` is private/internal and cannot be enumerated for config validation — spec must revise validation strategy (likely: export a public `EVENT_TYPES` set)
- **Wave D D2**: `notifications_digest_queue` cannot atomically mark `flushed_at` (no `SELECT ... FOR UPDATE` on SQLite) — spec must revise to use `WHERE flushed_at IS NULL` guarded by retry-on-conflict
- **Wave D D3**: AST guardrail `test_safe_send_severity_required.py` finds a `safe_send(` call site that cannot reasonably be classified with a severity (e.g., severity depends on runtime data not available at call site) — spec must add a `Severity.classify_runtime(event_type, **kwargs)` helper
- **Wave D D3**: `data/notification_retry_state.json` write fails on disk-full or permission error — spec must add graceful degradation (in-memory fallback + log warning) OR escalate to operator notification
- **Wave D D5**: alert_silence UNION query incompatibility between SQLite and PG (different date-arithmetic functions) — spec must add per-engine query variants in `digest_queue.py` and `alert_silence.py`
- **Wave F F3**: docker-compose v2 not installed on operator machine OR on CI runner — spec must revise to use `docker compose` CLI feature detection + clearer SKIP message
- **Sprint Close**: actual test sweep count is < 5350 after all waves merged — investigate dropped tests before bumping floor; possible that an early wave un-skipped fewer than projected
- **Sprint Close**: PM serial-dispatch detection (§6.5.1) fires false-positive — investigate watch.py worktree-glob logic before assuming serial discipline is broken
- **Cross-cutting**: any wave PR's diff includes whitespace-only lines from CRLF/LF drift > 5% of total diff lines — operator opts in `.gitattributes` LF normalization as a Sprint Close addendum

---

*End of spec v2. PM consumes the accompanying task graph for execution.*


## Design Decisions

| # | Decision | Choice | Rationale | Reversal cost |
|---|---|---|---|---|
| 1 | Wave E: design-only; defer implementation to post-Sprint-5; APPLY 4 stale-text f | ? | Spec itself says 'deferred to SP6' but Sprint 5 is final. No current bottleneck demands impl. Implementation = ~15 file  | ? |
| 2 | Version bump: MINOR (0.34.0 → 0.35.0) | ? | Wave D ships NEW notifications routing YAML config; Wave C #56 ships NEW shadow_trades.strategy_id column; Wave C #45 sh | ? |
| 3 | Wave D defaults: BACKWARD-COMPAT (zero-config = current behavior) | ? | Zero-config users see no change; operator opts in by editing config/settings.local.yaml. Minimizes blast radius; reversi | ? |
| 4 | PR boundary: PER-WAVE PRs (6 total) | ? | Matches recent successful #1058/#1059/#1060 cadence. Smaller review surface; smaller blast radius per merge; easier roll | ? |
| 5 | docs/roadmap.md: CREATE NEW | ? | Sprint history table + active-track pointer is a distinct artifact from operator-runnable runbook content in operator-gu | ? |
| 6 | #97 alpaca_adapter.py: GRANDFATHER via known_violations.json + delete sentinel t | ? | Actual file split is high blast-radius (touches every alpaca call site). Sentinel test is currently failing OR grandfath | ? |
| 7 | #96 platform_events: RESOLVED-BY-C2 (Task 2 unconditionally adds TableDef; both  | ? | v1 scoped #96 out pending Wave C developer grep — but D5 IS the write-site and grep runs BEFORE D5 lands → production cr | ? |
| 8 | #68 reframe: typed hierarchy + agent_data.py only (28 except blocks — corrected  | ? | Brief premise WRONG — only 1 raise site in entire src/council/; real opportunity is 28 bare except Exception in agent_da | ? |
| 9 | safe_send policy gate inserted IN-PLACE (no parallel router.py) | ? | Duplicating event_map in a parallel router.py would weaken the KeyError-on-unknown-event_type security boundary from Spr | ? |
| 10 | Digest queue: DB-backed table (not in-memory) | ? | Watch loop restarts must not lose buffered events. SQLite/PG durability is the existing pattern. | ? |
| 11 | Source tag (#101) added as column on notifications_sent (not separate audit tabl | ? | notifications_sent already tracks every dispatch; source_tag is per-row metadata. Defense-in-depth via conftest.py null- | ? |
| 12 | Retry policy: 3 attempts with [1, 5, 30]s backoff | ? | Tuned to F2 observed Telegram failure rate (~2-3/hour). Total wait per failed event = 36s, acceptable for non-hot-path. | ? |
| 13 | Escalation: 5 failures in 10 min → email fallback | ? | Captures sustained outages while tolerating transient blips. Email is the operator's secondary channel. | ? |
| 14 | Sequence C4 → D2 → D5 for src/scheduler/watch.py edits (PM-enforced via §6.5.1 d | ? | Three tasks edit the same file. Sequential PRs avoid worktree race. PM detection mechanism: git fetch + gh pr list pre-d | ? |
| 15 | PG test port 5433 (not 5432) | ? | Avoid clash with operator's local PG on 5432 per memory `reference_local_ports`. Configurable via TEST_PG_PORT env var. | ? |
| 16 | Test floor canon: 5350 (50-test conservative buffer below projected 5400-5450 me | ? | Projection has +/- range from un-SKIP variance; 50-test conservative margin prevents flaky-test-day floor failures. | ? |
| 17 | _scalar cosmetic removal: SAME PR as Sprint Close with scope-cap (≤40 files) | ? | Sprint Close is natural home; mechanical revert is cosmetic. Scope-cap protects PR review surface. | ? |
| 18 | All Wave D tests use monkeypatch.setenv hermetically + conftest clears ARCIS_TEL | ? | Per memory `feedback_worktree_env_drift`, worktree agents inherit operator's env; tests must NOT depend on env-var prese | ? |
| 19 | [NEW v2 — M1] safe_send severity is a REQUIRED keyword-only kwarg (no default va | ? | v1 spec had `severity: str = 'medium'` default. Devil's advocate M1: existing call sites would never be audited; events  | ? |
| 20 | [NEW v2 — MIN2] ARCIS_NOTIFICATION_SOURCE default value is 'unknown' (fail-loud) | ? | v1 default 'watch-loop' silently mislabels arcis:code agents that invoke `python -m src.main` outside NSSM (they inherit | ? |
| 21 | [NEW v2 — M2] quiet_hours.bypass_severity config knob REMOVED — rule #1 IS the b | ? | v1 spec declared `bypass_severity: critical` in YAML schema but rule precedence in policy.should_dispatch already had se | ? |
| 22 | [NEW v2 — M4] Retry counter persisted to data/notification_retry_state.json (not | ? | v1 in-memory counter reset on every NSSM watch-loop restart. During the F2 scenario this mitigates (sustained Telegram o | ? |
| 23 | [NEW v2 — M5] Digest flush-then-fail: reset flushed_at=NULL + flush_attempts++,  | ? | v1 marked flushed_at=now_et BEFORE dispatching. If _send_with_retry failed all 3 attempts, the row was already flushed → | ? |
| 24 | [NEW v2 — FEAS2] New `src/monitoring/` top-level package for operational alertin | ? | src/diagnostics/ __init__.py docstring dedicates the package to statistical methodology (canonical_sharpe, instrumentati | ? |
| 25 | [NEW v2 — MIN3] FK creation uses `ADD CONSTRAINT … NOT VALID` + deferred `VALIDA | ? | PostgreSQL `ADD CONSTRAINT … FOREIGN KEY` without NOT VALID takes an AccessExclusiveLock on shadow_trades during the val | ? |
