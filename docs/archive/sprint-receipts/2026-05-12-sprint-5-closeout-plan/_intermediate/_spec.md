# Sprint 5 Closeout Plan â€” Design Spec

**Document ID:** `docs/audits/2026-05-12-sprint-5-closeout-plan/spec.md`
**Status:** Draft v1 (for PM execution)
**Audience:** `arcis:code` PM orchestrator + per-wave developer/reviewer agents
**Scope:** Waves C/D/F (implementation) + Wave E (design-only) + mini-tracker dispositions + Sprint Close PR contract

---

## 0. Revision History

| Version | Date | Author | Notes |
|---|---|---|---|
| v1 | 2026-05-12 | design-team | Initial spec covering 6 waves + Sprint Close. Incorporates deep-codebase-report.json corrections (test floor reality, kpis.py:128 not :91, #68 reframe to agent_data.py except blocks, #96 scope-out pending grep). Operator-approved decisions from CHECKPOINT folded into Design Decisions table. |

---

## 1. Overview

### 1.1 Goal

Land Sprint 5 â€” the final Arcis sprint before the walk-forward framework becomes the active post-Sprint-5 track â€” via 5 wave PRs (Waves C, D, E-disposition, F) plus a Sprint Close PR. After Close, `src/version.py = v0.35.0`, a `v0.35.0` git tag exists, `docs/roadmap.md` exists, the CHANGELOG has a consolidated Sprint 5 section, and the operator-guide describes the new notifications routing config. Three new operator-visible behaviors ship: notifications routing policy (Wave D), manual-intervention drift detection (Wave C #45), and a server-side stale-base CI check (Wave F #15).

### 1.2 In Scope

- **Wave C** (5 tasks + folded #100 scanner extension): data integrity + cross-engine future-prevention
- **Wave D** (1 task #69 + folded #93/#94 + new #101 source tagging): notifications routing policy, digest mode, retry/escalation, alert-silence detector
- **Wave E** (1 task #91): keep existing spec at `docs/audits/2026-05-12-dual-gpu-ideation/specs/` as the deliverable; defer implementation
- **Wave F** (3 tasks): server-side stale-base check, test suite speedup, local PG provisioning
- **Sprint Close PR**: aggregated CHANGELOG, version bump to 0.35.0, git tag, new `docs/roadmap.md`, operator-guide append, test floor canon refresh, known-pre-existing-failures.md refresh, `_scalar` cosmetic removal, #97 sentinel grandfather

### 1.3 Out of Scope (explicit)

- Walk-forward framework implementation (separate post-Sprint-5 track)
- New ML model architectures or training code beyond the deferred Wave E impl
- Frontend redesign (Sprint 5 may render new widgets, no arch changes)
- Render infrastructure (PG cutover complete)
- #96 `platform_events` TableDef creation (scope-out pending Wave C developer grep confirmation; resolves to triage-disposition.md if no write-site found)
- #97 actual file split of `alpaca_adapter.py` (grandfathered via `known_violations.json`; tracked as post-Sprint-5)
- Engine.py + value_tracker.py `except Exception` refactor (#68 sibling work, post-Sprint-5)

### 1.4 Success Criteria

- All 5 wave PRs merged plus Sprint Close PR merged with green CI
- Final test floor between 5350-5450 (sustained, with zero new failures)
- All operator-visible decisions resolved without mid-sprint additional AskUserQuestion batches (decisions already approved in 2026-05-12 CHECKPOINT)
- Devil's-advocate gates pass: Wave D config attack surface bounded (no dynamic event_type resolution); digest mode cannot delay severityâ‰¥medium events; backward-compat default config preserves current behavior

---

## 2. Architecture

### 2.1 Wave C â€” Data Integrity Hardening

Sequencing bottleneck per glidepath ("C must complete before D"): typed exceptions (#68) and schema additions (#56 strategy_id, severity column for notifications_sent) are dependencies of Wave D.

**Tasks:**
- **C1 (#54)** â€” wire `dates` + `directions` arrays at `src/api/cloud_routes/kpis.py:128` (corrected from brief's `:91`). 2-LOC change that flips MC permutation vote from ABSTAIN to real PASS/FAIL.
- **C2 (#56)** â€” add `strategy_id TEXT` ColumnDef + ForeignKeyDef to `shadow_trades` in `src/schema/registry.py:198-318`; extend `_fetch_closed_trades` in `src/api/cloud_routes/kpis_compute.py` with optional `strategy_id` filter param.
- **C3 (#68 REFRAMED)** â€” create typed exception hierarchy in `src/council/errors.py` (`CouncilError` base â†’ `CouncilParseError`, `CouncilTimeoutError`, `CouncilAgentDataError`, `CouncilProviderError`); replace 30+ bare `except Exception` blocks in `src/council/agent_data.py` with typed catches. **Engine.py + value_tracker.py except-blocks DEFERRED to post-sprint** (per deep-report scope guard).
- **C4 (#45)** â€” new module `src/diagnostics/manual_intervention_drift.py` that compares `get_all_positions()` (alpaca_adapter) vs `shadow_trades WHERE status='open'`; emits `notify_manual_intervention_drift` event when divergence persists > 30 min (configurable). New event_type in `src/notifications/telegram.py` event_map.
- **C5 (#47)** â€” verification doc only: `docs/audits/2026-05-07-telegram-email-sweep/triage-disposition.md` catalogs all 50 findings as `closed-by-PR-X | scoped-into-Wave-D | follow-up-issue-N | accepted-risk`. Zero source changes.
- **C6 (#100)** â€” extend AST scanner at `tests/test_no_fetchone_int_index_in_pg_unsafe_files.py` with new test function `test_no_fetchall_list_comp_int_index_in_pg_unsafe_files` matching `ListComp(elt=Subscript(value=Name, slice=Constant(int)), generators=[comprehension(iter=Call(func=Attribute(attr='fetchall')))])` plus a sibling scanner over `scripts/`. Self-test included.

### 2.2 Wave D â€” Notifications Routing Policy (LARGEST PIECE)

Single architectural insertion: a **policy gate** between `safe_send`'s `is_telegram_enabled()` check and the `event_map[event_type]` lookup. Three layered concerns compose:

1. **Dedup** (existing) â€” 24h content-identity dedup via `notifications_dedup` table
2. **Policy** (NEW) â€” mute rules (quiet hours, severity, event_type), routing (telegram/email/both/none)
3. **Digest queue** (NEW) â€” bundles severity=low events into cadence-flushed batches

**Composition order:** dedup â†’ policy â†’ digest queue â†’ dispatch.

**Hard invariants (preserve from Sprint 4 T2 and security review):**
- `event_map[event_type]` lookup REMAINS in `safe_send`. YAML config REFERENCES event_type keys; never resolves them dynamically. KeyError-on-unknown-event_type security boundary preserved.
- `safe_send`'s `except (urllib3.HTTPError, requests.RequestException, socket.timeout, OSError)` block at `src/notifications/telegram.py:1299-1311` is the ONLY broad catch. New retry logic mounts INSIDE this except block; does NOT widen the catch.
- Severity â‰¥ `medium` BYPASSES digest queue (digest is opt-in for severity=low only). Critical alerts cannot be delayed by digest cadence.

**New modules:**
- `src/notifications/policy.py` â€” pure-function `should_dispatch(event_type, severity, now_et, config) -> PolicyDecision`. PolicyDecision is a dataclass: `{action: 'send'|'mute'|'digest'|'escalate', channels: list[str], reason: str}`.
- `src/notifications/digest_queue.py` â€” DB-backed buffer. `enqueue(event_type, severity, payload, channel)` writes to `notifications_digest_queue` table; `flush_due(now_et, config) -> list[dict]` returns events whose cadence bucket has elapsed.

**Modified surfaces:**
- `src/notifications/telegram.py:1234` â€” insert policy gate between line 1232 (`is_telegram_enabled` check) and line 1287 (`event_map[event_type]`).
- `src/notifications/telegram.py:1299` â€” replace single-attempt send with exponential-backoff retry (1s, 5s, 30s = 3 attempts). After 5 consecutive failures in a 10-min window, mark `policy_decision='escalated'` and call email-channel notifier as fallback.
- `src/notifications/telegram.py:780` â€” apply `_html_escape()` to `regime_old`/`regime_new` in `notify_regime_alert` (#93).
- `src/notifications/telegram.py:805` â€” apply `_html_escape()` to `risk_governor_status` + each ticker in `recent_str` before join in `notify_streak_alert` (#94).
- `src/scheduler/watch.py` â€” add digest flush hook (every 5 min) + alert-silence detector hook (every 5 min during market hours).

**New surface â€” alert silence detector:**
`src/diagnostics/alert_silence.py` â€” runs on watch loop cadence. If `notifications_sent WHERE status='ok'` has no row within `config.alert_silence_threshold_minutes` (default 60) during market hours, writes `platform_events` row with severity=high AND surfaces dashboard widget data. Closes F2 "18-hour live_prices gap with no notification" blind spot.

**Source tagging (#101 â€” operator clarification 2026-05-12):**
- New `source_tag TEXT DEFAULT 'watch-loop'` column on `notifications_sent`
- `safe_send` reads `os.environ.get('ARCIS_NOTIFICATION_SOURCE', 'watch-loop')` and writes to `source_tag` column AND prepends a `[<source>]` prefix to outgoing Telegram messages when source â‰  `'watch-loop'`
- `tests/conftest.py` session fixture sets `ARCIS_NOTIFICATION_SOURCE='pytest:<worktree-basename>'` AND monkeypatches `_send_telegram` to a null-router (no actual network call from pytest under any condition)

### 2.3 Wave E â€” Dual-GPU Disposition

DESIGN-ONLY per operator decision. Deliverable: a one-pager `docs/audits/2026-05-12-dual-gpu-ideation/disposition.md` that:
- Confirms spec at `docs/audits/2026-05-12-dual-gpu-ideation/specs/2026-05-12-dual-gpu-workload-separation-design.md` is the canonical artifact
- States "Implementation deferred to first post-Sprint-5 maintenance window"
- Documents the 4 stale-text fixes in the spec that should land in any future impl PR (test floor 3682â†’5350, 'Sprint 6' references, etc.)
- Links from `docs/roadmap.md` (Sprint Close PR creates that file)

Zero source changes. Zero new tests.

### 2.4 Wave F â€” Dev Tooling / Test Infrastructure

- **F1 (#15)** â€” new GitHub Actions workflow `.github/workflows/stale-base-check.yml` triggers on `pull_request.synchronize`, computes `git merge-base origin/main HEAD` vs `origin/main`'s HEAD, sets check status to failure if behind. Complements client-side `scripts/hooks/pre-push`.
- **F2 (#86)** â€” restructure `tests/test_cloud_requirements_imports.py` from per-test fresh-venv pattern to session-scoped shared-venv: ONE pip install of `requirements-cloud.txt`, then per-test imports via subprocess against the shared venv. Target: drop full-sweep runtime by ~3x.
- **F3 (#87)** â€” new `docker-compose.test.yml` (postgres:16-alpine on `localhost:5433`); `tests/conftest.py` `pytest_sessionstart`/`pytest_sessionfinish` hooks provision + teardown. Three hardcoded `TEST_DATABASE_URL` fixtures (`tests/api/test_status.py:18`, `tests/test_cloud_app.py:15`, `tests/test_shadow_desk_filter.py:25`) refactored to use the provisioned URL. Graceful SKIP fallback when Docker not installed. Drops `Create test/test PG role` step from `.github/workflows/pg-tests.yml`.

### 2.5 Sprint Close PR

Final aggregation PR. See Â§9 (File Inventory) and Â§10 Sprint Close subsection for exact artifacts.

---

## 3. Data Model

### 3.1 Schema additions (all via `src/schema/registry.py`)

**Wave C #56 â€” shadow_trades.strategy_id**
```python
# In TABLES['shadow_trades'].columns, after existing columns ~line 318:
ColumnDef('strategy_id', 'TEXT', nullable=True, default=None,
          description='FK to strategy_registry.strategy_id; NULL for legacy rows pending backfill'),
# In TABLES['shadow_trades'].foreign_keys:
ForeignKeyDef('strategy_id', 'strategy_registry', 'strategy_id'),
```
*Backfill policy:* legacy rows remain NULL (no in-spec backfill task; tracked as post-sprint follow-up). The `desk` column at `registry.py:299` continues to carry legacy `research_<strategy_id>` attribution.

*Precondition:* Wave C #56 developer must confirm `strategy_registry` TableDef + PK column name via Grep before adding the FK. If absent, scope-out to ColumnDef-only (no FK) with rationale in PR body.

**Wave D â€” notifications_sent column additions**
```python
# In TABLES['notifications_sent'].columns:
ColumnDef('severity', 'TEXT', nullable=True, default=None,
          description='low|medium|high|critical â€” populated by safe_send from event metadata'),
ColumnDef('policy_decision', 'TEXT', nullable=True, default=None,
          description='sent|muted|digested|escalated â€” forensic trail of policy gate decision'),
ColumnDef('source_tag', 'TEXT', nullable=False, default="'watch-loop'",
          description='watch-loop|pytest:<worktree>|operator-cli â€” distinguishes notification origin'),
```

**Wave D â€” new notifications_digest_queue table**
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
    ],
    indexes=[
        IndexDef('idx_digest_queue_pending', ['flushed_at', 'enqueued_at']),
    ],
)
```

### 3.2 Schema changes NOT in scope

- **#96 `platform_events`** â€” TableDef creation deferred. Wave C developer runs `grep -rn 'platform_events' src/ scripts/` BEFORE Wave C close. If a write-site exists, file as Wave C addendum. If only the registry comment refers to it (deep-report's most likely finding), document in C5 triage-disposition.md as "comment-only drift; no write-site; close as documentation cleanup".
- **Engine.py + value_tracker.py except-block refactor** â€” out of #68 scope per deep-report.

### 3.3 Migration

All new schema additions go through:
1. Edit `src/schema/registry.py`
2. Run `python -m src.main validate-schema --fix` locally (SQLite)
3. Run `python scripts/render_migrate.py` against PG (PR body must include output per CLAUDE.md)

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
      1. severity in {'high', 'critical'} â†’ always send (immediate)
      2. event_type in config['mute_event_types'] â†’ mute
      3. now_et within config['quiet_hours'] AND severity != 'critical' â†’ mute (or digest if config['quiet_digest']=True)
      4. severity == 'low' AND config['digest_low']=True â†’ digest
      5. default â†’ send via config['default_routing'].get(event_type, ['telegram'])
    """
```

### 4.2 `src/notifications/digest_queue.py` (NEW)

```python
def enqueue(event_type: str, severity: str, payload: dict, channel: str, conn=None) -> int:
    """Write to notifications_digest_queue. Returns row id."""

def flush_due(now_et: datetime, config: dict, conn=None) -> list[dict]:
    """
    Return events whose cadence bucket has elapsed since enqueued_at.
    Marks returned rows with flushed_at=now_et atomically.
    Cadence: config['digest_cadence_minutes'] (default 60).
    Returns: [{'event_type', 'severity', 'payload', 'channel', 'enqueued_at'}, ...]
    """
```

### 4.3 `src/notifications/telegram.py` â€” `safe_send` modification

**Before (line 1232-1290):**
```python
def safe_send(event_type: str, severity: str = 'medium', **kwargs):
    if not is_telegram_enabled():
        return
    # ... dedup check ...
    handler = event_map[event_type]  # KeyError-on-unknown â€” SECURITY BOUNDARY
    handler(**kwargs)
```

**After:**
```python
def safe_send(event_type: str, severity: str = 'medium', **kwargs):
    if not is_telegram_enabled():
        return
    # ... dedup check (unchanged) ...
    
    # NEW: policy gate (composes after dedup, before dispatch)
    config = _load_notifications_config()
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
- Tracks consecutive failure count in-memory; after 5 failures within 10-min window, sets `decision.action='escalate'` and calls `email_notifier.send(...)` as fallback. Records `policy_decision='escalated'`.
- **Catch list UNCHANGED**: still only `(urllib3.HTTPError, requests.RequestException, socket.timeout, OSError)`. Bare `except Exception` is FORBIDDEN per Sprint 4 T2 discipline.

### 4.4 `src/diagnostics/manual_intervention_drift.py` (NEW â€” Wave C #45)

```python
def detect_drift(
    broker_positions: dict[str, float],  # ticker -> qty from alpaca_adapter.get_all_positions()
    db_positions: dict[str, float],      # ticker -> sum(actual_shares) from shadow_trades WHERE status='open'
    threshold_minutes: int = 30,
    state_path: str = 'data/drift_detector_state.json',
) -> list[DriftFinding]:
    """
    Compares broker vs db per-ticker. If diff != 0, persists first-seen-at timestamp
    to state_path. If diff has persisted unchanged > threshold_minutes, emits a finding.
    Returns list of DriftFinding(ticker, broker_qty, db_qty, first_seen_at, severity).
    """
```

### 4.5 `src/diagnostics/alert_silence.py` (NEW â€” Wave D add-on)

```python
def check_alert_silence(
    now_et: datetime,
    threshold_minutes: int = 60,
    conn=None,
) -> AlertSilenceFinding | None:
    """
    Reads notifications_sent WHERE status='ok' ORDER BY sent_at DESC LIMIT 1.
    During market hours (per src/scheduler/holidays.is_market_open):
      - if no successful send within threshold_minutes â†’ returns AlertSilenceFinding
      - emits via safe_send(event_type='alert_silence', severity='high', ...)
      - writes platform_events row (severity=high) for forensic trail
    Returns None outside market hours.
    """
```

### 4.6 `src/council/errors.py` (extended â€” Wave C #68)

```python
class CouncilError(Exception):
    """Base for all council subsystem errors."""

class CouncilUnavailableError(RuntimeError, CouncilError):
    """Existing â€” kept for back-compat. Raised by aggregation.py."""

class CouncilParseError(CouncilError):
    """JSON / response-shape failures."""

class CouncilTimeoutError(CouncilError):
    """Ollama / network timeouts."""

class CouncilAgentDataError(CouncilError):
    """agent_data.py SQLite / DB-shape failures."""

class CouncilProviderError(CouncilError):
    """Ollama / LLM provider HTTP errors."""
```

### 4.7 YAML Config Schema (Wave D â€” `config/settings.example.yaml` extension)

```yaml
notifications:
  # All keys OPTIONAL â€” defaults preserve current behavior (everything â†’ telegram, no mute, no digest)
  quiet_hours:
    enabled: false              # default: false (no quiet hours)
    start: '22:00'              # ET, 24h format
    end: '06:00'
    bypass_severity: critical   # 'medium'|'high'|'critical' â€” bypass quiet hours at this severity and above
  mute_event_types: []          # list of event_type strings to silently drop; default: []
  digest_low: false             # default: false; if true, severity=low events buffer to digest queue
  digest_cadence_minutes: 60    # default 60; how often digest flushes
  default_routing:              # default: all events â†’ ['telegram']
    # event_type: [channels]
    trade_opened: ['telegram']
    eod_report: ['email']
  retry:
    attempts: 3                 # default 3
    backoff_seconds: [1, 5, 30] # default [1, 5, 30]
    escalation_threshold: 5     # consecutive failures before email-fallback
    escalation_window_minutes: 10
  alert_silence:
    enabled: true               # default: true
    threshold_minutes: 60       # alert if no successful send in this many min during market hours
```

**Validation rules (enforced by `_load_notifications_config`):**
- All event_type strings in `mute_event_types` + `default_routing` MUST be keys of the existing `event_map` dict. Unknown event_type in config raises `NotificationsConfigError` at startup â€” fail fast, not at dispatch time.
- `quiet_hours.start` / `end` MUST parse as `HH:MM` 24h time. Crossing midnight (22â†’06) is supported.
- `retry.backoff_seconds` MUST equal length `retry.attempts - 1` (3 attempts â†’ 2 inter-attempt sleeps). Wait â€” re-spec: 3 attempts â†’ 3 backoff values, last one ignored if attempt 3 succeeds. Use `attempts` as count, `backoff_seconds[i]` as sleep before attempt `i+1`.
- Channels MUST be in `{'telegram', 'email', 'both', 'none'}`.

---

## 5. Error Handling

### 5.1 safe_send retry + escalation policy (Wave D)

| Scenario | Behavior | Records |
|---|---|---|
| Attempt 1 succeeds | Status='ok', policy_decision='sent' | `notifications_sent` row |
| Attempt 1 fails (network), attempt 2 succeeds | Same as above (success masks transient failure); log warning | `notifications_sent` (status='ok') |
| All 3 attempts fail (network) | status='failed', policy_decision='failed'; increment in-memory consecutive_failures | `notifications_sent` (status='failed') |
| 5+ failures in 10-min window | policy_decision='escalated'; call `email_notifier.send(subject=f'[ESCALATION] {event_type}', body=...)`. Reset counter on next success. | `notifications_sent` (status='escalated') + email |
| `event_type` not in `event_map` | KeyError raised (SECURITY â€” unchanged) | None (fail-fast at startup-config-load OR at dispatch) |
| `NotificationsConfigError` at startup | Watch loop fails to start; operator must fix YAML | stderr + sys.exit(1) |

### 5.2 Wave C #68 typed errors

- `agent_data.py` except blocks: classify per error source
  - SQLite errors (`sqlite3.OperationalError`, `psycopg.Error`) â†’ re-raise as `CouncilAgentDataError`
  - `json.JSONDecodeError` / shape mismatches â†’ re-raise as `CouncilParseError`
  - `requests.RequestException` (to Ollama) â†’ re-raise as `CouncilProviderError`
  - Truly unexpected â†’ keep `except Exception` ONLY at the top-level orchestration entry point in engine.py (out of #68 scope per deferral)
- Tests verify that callers can `except CouncilError` and reliably catch all council failures

### 5.3 Wave C #45 drift detection error handling

- If `get_all_positions()` raises (broker network), drift detector LOGS and returns empty list. No drift alert on its own outage (don't alert on alert path).
- If DB read fails, raise `CouncilAgentDataError`-equivalent here is `DiagnosticsDataError` (new, mirrors pattern from #68 in `src/diagnostics/errors.py`).

### 5.4 Wave F #87 fixture error handling

- Docker not installed / not running â†’ `pytest_sessionstart` logs warning, leaves `TEST_DATABASE_URL` unset, parametrized PG variants SKIP (current behavior preserved).
- Container start fails (port conflict, image pull error) â†’ SKIP gracefully, write reason to `pytest_warnings`.
- Container start succeeds but schema bootstrap fails â†’ fail the session with explicit error (developer must fix migration, not silently SKIP).

---

## 6. Testing Strategy

### 6.1 Per-task test additions (projected)

| Wave | Task | New tests | Notes |
|---|---|---|---|
| C | C1 (#54) | +3 | wired call, MC-vote-no-abstain, response shape regression |
| C | C2 (#56) | +5 | schema discipline, FK enforcement, filter behavior |
| C | C3 (#68) | +8 | hierarchy structure, each typed exception raises/catches, agent_data error path coverage |
| C | C4 (#45) | +6 | detector with mocked broker/db, threshold boundary, alert dedup, widget data shape, watch-loop hook idempotence, state persistence |
| C | C5 (#47) | +0 | verification doc only |
| C | C6 (#100) | +3 | new scanner self-test, scripts/ scanner self-test, integration on synthetic violation file |
| D | D1 policy | +12 | truth table: severity Ã— quiet-hours Ã— mute-list Ã— digest-low; config validation; cross-midnight quiet hours |
| D | D2 digest_queue | +8 | enqueue, flush_due, cadence boundary, no-double-flush, schema discipline |
| D | D3 retry | +6 | 1-attempt success, retry-then-success, 3-fail-then-fail, escalation threshold, consecutive-counter reset on success, narrow-catch invariant |
| D | D4 html-escape + source-tag | +5 | regime_alert escape, streak_alert escape, source_tag column write, pytest source-tag prefix, conftest null-router |
| D | D5 alert_silence | +4 | silence detection, market-hours gate, platform_events forensic write, dashboard widget shape |
| F | F1 (#15) | +2 | workflow YAML lint, step structure assertion |
| F | F2 (#86) | +0 | restructure existing; verify test count unchanged |
| F | F3 (#87) | net +30-50 | un-SKIPs previously-skipped postgres parametrized variants |

**Total projected:** +90-110 new tests minus the un-SKIPs offset.
**Projected final floor:** 5400-5450. Sprint Close bumps `pg-tests.yml` floor 5050â†’5350 (10-test conservative margin) AND CLAUDE.md 3682â†’5350.

### 6.2 AST structural guardrails (per CLAUDE.md PR #1058/#1059/#1060 discipline)

For every NEW module, add a structural test that asserts the bug-class is unrepeatable:

- **policy.py** â€” `tests/notifications/test_policy_purity.py` asserts `policy.should_dispatch` does NOT import `requests`, `sqlite3`, or `psycopg` (pure function invariant via AST scan of imports)
- **digest_queue.py** â€” `tests/notifications/test_digest_queue_atomicity.py` asserts `flush_due` does NOT modify rows whose `flushed_at` is non-NULL (idempotence invariant via SQL trace)
- **safe_send retry** â€” `tests/notifications/test_safe_send_catch_discipline.py` AST-scans the file and asserts the network-except clause's exception tuple equals exactly `(urllib3.HTTPError, requests.RequestException, socket.timeout, OSError)`. Prevents future widening to `except Exception`.
- **manual_intervention_drift.py** â€” `tests/diagnostics/test_drift_detector_no_recursion.py` asserts the detector does NOT call `safe_send('manual_intervention_drift', ...)` from within its own alert path (prevents alert-on-alert recursion)

### 6.3 Existing-test sibling-search (per memory `feedback_review_sibling_search`)

Each developer MUST grep for the pattern they're fixing across the file AND across `src/` before claiming task done:
- C1 dev: grep `_compute_promotion_gate_kpi(` across `src/api/` for any other callers passing only `(n_trades, returns)`
- D4 dev: grep for `f'...{<var>}'` style HTML interpolation across all `notify_*` functions, not just regime + streak
- C6 dev: grep for `[r[N] for r in` across `src/` AND `scripts/` to confirm the scanner extension catches all live sites

### 6.4 Visual-verify gate (per memory `feedback_visual_verify_ui`)

New dashboard widgets that ship in this sprint:
- **D5 alert silence widget** â€” browser-render via `cd frontend && npm run dev`, screenshot included in PR body
- **C4 drift detection widget** â€” same discipline
- **Notifications routing config preview** (D1 add-on â€” optional, but recommended): a `GET /api/notifications/policy-preview` endpoint that returns the current effective config + a sample dispatch decision for every event_type. Surface via dashboard so operator can answer "what would fire right now?"

### 6.5 Worktree isolation (per CLAUDE.md)

ALL parallel agent dispatches use `isolation: "worktree"`. Sequencing constraint: when two tasks edit the same file (e.g., C4 + D2 + D5 all edit `src/scheduler/watch.py`), they MUST run sequentially OR the PM coordinates rebasing via per-wave PR sequencing (deep-report's preferred path: C4 lands first, then D2 rebases, then D5 rebases).

---

## 7. Operational Notes

### 7.1 Operator-guide additions (per CLAUDE.md same-PR mandate)

**Wave D PR adds `docs/operator-guide.md` section "Notifications routing":**
- YAML config location: `config/settings.local.yaml` under `notifications:` key
- Schema reference: link to `config/settings.example.yaml` for live keys
- "How to inspect what would fire": `GET /api/notifications/policy-preview` URL
- Escalation expectation: "After 5 consecutive failures in 10 min, alerts route to email â€” check inbox if Telegram quiet during market hours"
- Source-tag explanation: "`[pytest:<worktree>]` prefix on a Telegram message means a worktree-isolated pytest run leaked through env vars. Should not happen post-Sprint-5 conftest fix; report if seen."

**Wave C PR adds section "Drift detection":**
- Alert format: "`Manual intervention drift detected: AAPL broker=100, db=150, persisted 35min`"
- How to silence: edit `config/settings.local.yaml` `diagnostics.drift_detection.enabled: false`
- Recovery procedure: reconcile via `python -m src.main reconcile-positions`

**Wave F PR adds section "CI checks":**
- Stale-base check: "PR will fail merge if its branch is behind `origin/main`. Rebase locally + force-push to refresh."
- Bypass: documented but discouraged ("`git push --no-verify` only for emergency hotfix; expect operator review")

**Sprint Close PR adds section "Sprint 5 closeout state":**
- Version: v0.35.0
- New behaviors: notifications routing, drift detection, alert silence, stale-base CI
- Deferred: dual-GPU implementation, council engine.py/value_tracker.py except refactor, alpaca_adapter.py split
- Active track: walk-forward framework (separate roadmap entry)

### 7.2 Roadmap (`docs/roadmap.md` â€” NEW)

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
- **Walk-forward framework** (post-Sprint-5) â€” see `docs/audits/<future-spec>.md`

## Deferred
- Dual-GPU workload separation (`docs/audits/2026-05-12-dual-gpu-ideation/`)
- Council engine.py + value_tracker.py except-block refactor (post-Sprint-5; #68 sibling)
- alpaca_adapter.py file split (post-Sprint-5; #97)
```

### 7.3 Test floor canon refresh

Sprint Close PR updates THREE locations:
- `CLAUDE.md` test floor line (currently 3682) â†’ 5350 + lineage paragraph noting the projection
- `.github/workflows/pg-tests.yml` floor (currently 5050) â†’ 5350
- `CHANGELOG.md` v0.35.0 section documents the floor lineage explicitly so future agents can audit drift

### 7.4 Per-wave CHANGELOG entries (vs Sprint Close aggregation)

Each wave PR adds entries to `[Unreleased]` (per CLAUDE.md). Sprint Close PR moves ALL of these into a single `## [v0.35.0] - 2026-05-XX â€” Sprint 5 close` section, organized by subsection (Wave C / Wave D / Wave E / Wave F).

---

## 8. File Inventory

### 8.1 New files

| Path | Created by | Purpose |
|---|---|---|
| `src/notifications/policy.py` | D1 | Pure-function policy gate |
| `src/notifications/digest_queue.py` | D2 | DB-backed digest buffer |
| `src/diagnostics/manual_intervention_drift.py` | C4 | Drift detector |
| `src/diagnostics/alert_silence.py` | D5 | Alert silence detector |
| `src/diagnostics/errors.py` | C4 | Diagnostics typed errors |
| `tests/notifications/test_policy.py` | D1 | Policy truth table |
| `tests/notifications/test_policy_purity.py` | D1 | AST guardrail |
| `tests/notifications/test_digest_queue.py` | D2 | State machine tests |
| `tests/notifications/test_digest_queue_atomicity.py` | D2 | AST/SQL guardrail |
| `tests/notifications/test_safe_send_retry.py` | D3 | Retry + escalation |
| `tests/notifications/test_safe_send_catch_discipline.py` | D3 | AST guardrail on except tuple |
| `tests/notifications/test_html_escape_siblings.py` | D4 | regime + streak escape tests |
| `tests/diagnostics/test_manual_intervention_drift.py` | C4 | Drift detector unit tests |
| `tests/diagnostics/test_drift_detector_no_recursion.py` | C4 | AST guardrail |
| `tests/diagnostics/test_alert_silence.py` | D5 | Silence detector tests |
| `tests/council/test_typed_errors.py` | C3 | Council error hierarchy |
| `docker-compose.test.yml` | F3 | PG test container |
| `.github/workflows/stale-base-check.yml` | F1 | Server-side stale-base gate |
| `tests/workflows/test_stale_base_check.py` | F1 | YAML lint + structure |
| `docs/audits/2026-05-07-telegram-email-sweep/triage-disposition.md` | C5 | 50-finding disposition |
| `docs/audits/2026-05-12-dual-gpu-ideation/disposition.md` | E1 | Wave E deferral note |
| `docs/roadmap.md` | Sprint Close | Sprint history + active track |

### 8.2 Modified files

| Path | Modified by | Change |
|---|---|---|
| `src/api/cloud_routes/kpis.py` | C1 | Line 128: pass `dates` + `directions` |
| `src/api/cloud_routes/kpis_compute.py` | C2 | `_fetch_closed_trades` adds optional `strategy_id` filter |
| `src/schema/registry.py` | C2, D2, D3 | strategy_id ColumnDef+FK; notifications_digest_queue TableDef; severity/policy_decision/source_tag columns on notifications_sent |
| `src/council/errors.py` | C3 | Add 4 typed exception classes |
| `src/council/agent_data.py` | C3 | Replace 30+ `except Exception` blocks with typed catches |
| `src/notifications/telegram.py` | D1, D3, D4 | Insert policy gate at line 1234; replace single-attempt send with retry+escalate at 1299; apply `_html_escape` at lines 780+805; read `ARCIS_NOTIFICATION_SOURCE` env |
| `src/scheduler/watch.py` | C4, D2, D5 | Drift detector tick (every 30 min); digest flush tick (every 5 min); alert silence tick (every 5 min during market hours). SEQUENCE: C4 first, D2 rebases, D5 rebases. |
| `tests/conftest.py` | D4, F3 | `ARCIS_NOTIFICATION_SOURCE='pytest:<worktree>'`; `_send_telegram` null-router monkeypatch; `pytest_sessionstart`/`finish` docker-compose hooks |
| `tests/test_no_fetchone_int_index_in_pg_unsafe_files.py` | C6 | Add `test_no_fetchall_list_comp_int_index_in_pg_unsafe_files`; add scripts/ scanner |
| `tests/api/test_status.py`, `tests/test_cloud_app.py`, `tests/test_shadow_desk_filter.py` | F3 | Un-hardcode `TEST_DATABASE_URL` |
| `.github/workflows/pg-tests.yml` | F3, Sprint Close | Drop test/test role creation step; bump test floor 5050â†’5350 |
| `tests/test_cloud_requirements_imports.py` | F2 | Session-scoped shared-venv restructure |
| `config/settings.example.yaml` | D1 | Add `notifications:` section schema example |
| `docs/operator-guide.md` | Wave D, C, F, Close | Sections: Notifications routing, Drift detection, CI checks, Sprint 5 closeout state |
| `CLAUDE.md` | Sprint Close | Test floor 3682â†’5350; lineage note |
| `CHANGELOG.md` | Every wave + Close | Per-wave entries in `[Unreleased]`; Close aggregates into `[v0.35.0]` |
| `src/version.py` | Sprint Close | `'v0.34.0'` â†’ `'v0.35.0'` |
| `config/known_violations.json` | Sprint Close | Add `tests/shadow_trading/test_alpaca_adapter_split.py` entry (#97 grandfather) |
| `tests/shadow_trading/test_alpaca_adapter_split.py` | Sprint Close | Delete (sentinel obsolete after grandfather) |
| `docs/audits/known-pre-existing-failures.md` | Sprint Close | Refresh stale 34-failure canon to current state |
| `scripts/render_migrate.py` | C2, D2, D3 | (no edits; outputs included in PR bodies) |

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
- All time strings parsed via `datetime.strptime(s, '%H:%M')` â€” raises ValueError on malformed input â†’ fail-fast at startup
- `digest_cadence_minutes` clamped to [1, 1440] range; reject silently-huge values that would queue events indefinitely
- `retry.attempts` clamped to [1, 10]; `backoff_seconds` clamped per-element to [0, 300]
- No YAML `!include` or other tag interpolation â€” uses `yaml.safe_load` (existing project convention)

### 9.2 Digest-mode-delays-critical regression

**Risk:** A severity=critical event gets buffered to digest and an outage goes unnoticed for 60 min.
**Mitigation:**
- `policy.should_dispatch` rule #1: severity âˆˆ {high, critical} â†’ always action='send', no quiet-hours bypass needed. Tested by 4 explicit truth-table cases.
- AST guardrail `test_policy_severity_high_always_sends` asserts the function returns `action='send'` for severity='critical' regardless of any other config flag combination.
- Code review checklist: any future PR that changes `should_dispatch` MUST not modify the rule-1 short-circuit. Reviewer dispatch matrix includes Security.

### 9.3 Retry storms on sustained outage

**Risk:** If Telegram is down for hours, every alert spends 1+5+30=36s in retry before failing. Watch loop blocks.
**Mitigation:**
- After 5 consecutive failures in 10-min window, `_send_with_retry` SKIPS attempts 2+3 and goes straight to email-escalation. Closes the "every alert burns 36s" failure mode.
- Retry sleeps wrapped in `time.sleep` â€” acceptable for watch loop's notification path (not in critical signal computation path).
- Telemetry: consecutive failure count surfaced via dashboard widget so operator sees the outage signal without waiting for the alert-silence detector.

### 9.4 Source tag confusion

**Risk:** Operator confuses `[pytest:<worktree>]` prefixed messages with real alerts.
**Mitigation:**
- `tests/conftest.py` ALSO monkeypatches `_send_telegram` to a null-router â€” pytest cannot actually call Telegram API even if env var leaks. Defense in depth.
- Operator-guide section explicitly documents the prefix semantics.
- AST guardrail in `tests/notifications/test_safe_send_pytest_isolation.py` confirms that under pytest, `_send_telegram` is monkeypatched (asserts `_send_telegram.__name__ == '_null_router'`).

### 9.5 Wave C #68 typed-except may surface previously-swallowed bugs

**Risk:** Tightening exception handling in agent_data.py exposes latent bugs that were previously silent.
**Mitigation:**
- PR body discloses expected behavior change
- Canary deploy: operator restarts watch loop via NSSM after merge, eyes-on for 1h with dashboard open
- Each typed exception class has a `safe_send`-able representation so surfacing bugs become real alerts, not silent regressions

### 9.6 #54 directions-wiring flips promotion_gate decisions

**Risk:** Strategies that were 'defer' due to MC ABSTAIN flip to 'reject' or 'promote' â€” a SEMANTIC change.
**Mitigation:**
- Pre-merge: C1 developer runs `promotion_gate` against current closed trades, includes the votes_passed-delta table in PR body
- CHANGELOG entry explicitly documents the shift; operator can choose to roll back via 1-LOC revert if delta is unacceptable
- Reviewer dispatch includes Performance reviewer (math correctness verification)

### 9.7 #100 scanner extension may produce noisy violations across `scripts/`

**Risk:** Adding `scripts/` to scanner coverage uncovers dozens of pre-existing violations.
**Mitigation:**
- C6 developer first runs the scanner with allowlist=[] against scripts/ and reports the count
- If count > 5, the spec'd fix is to land scanner extension with a populated allowlist matching current violations + a TODO entry in `docs/audits/known-pre-existing-failures.md`. The PR's MERIT is preventing FUTURE violations; existing ones are documented as pre-existing.
- If count â‰¤ 5, fix in same PR (preferred)

### 9.8 Worktree env drift (per memory `feedback_worktree_env_drift`)

**Risk:** Wave D tests pass in agent worktree but fail post-merge because worktree doesn't carry operator's .env values.
**Mitigation:**
- All Wave D tests use `monkeypatch.setenv` to set required env vars hermetically
- D4 explicitly tests the `ARCIS_NOTIFICATION_SOURCE` env var path with both set and unset cases
- `tests/conftest.py` already clears `ARCIS_LOCAL_API_TOKEN` per-test (per #729 pattern); extend to ALSO clear `ARCIS_TELEGRAM_TOKEN` to prevent worktree env leakage

### 9.9 Concurrent edits to src/scheduler/watch.py (C4 + D2 + D5)

**Risk:** Three tasks all add new hooks to the watch loop; parallel agent dispatches collide.
**Mitigation:** PM enforces sequential dispatch for these three tasks. Wave C #45 (C4) lands first; Wave D digest flush (D2) rebases on C4; Wave D alert silence (D5) rebases on D2. Each task's PR diff cleanly adds an isolated hook.

### 9.10 #87 docker-compose port 5433 conflict

**Risk:** Operator may have other PG instances or test containers on 5433.
**Mitigation:**
- F3 developer confirms `localhost:5433` is free via `netstat` before committing
- `docker-compose.test.yml` documents port as configurable via `TEST_PG_PORT` env var (default 5433)
- Fallback to 5434, 5435 documented in operator-guide

### 9.11 Coverage gaps from deep-report

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
| 1 | Wave E: DESIGN-ONLY, defer impl post-Sprint-5 | Spec says "deferred to SP6" â€” but no SP6. No current bottleneck demands impl. Reversible: spec is the deliverable. | Implement in SP5 (~1.5 days; low blast-radius); skip entirely (lose spec discipline) | Low â€” operator can opt-in impl in any post-sprint maintenance window | Operator CHECKPOINT 2026-05-12 |
| 2 | Version bump: MINOR (0.35.0) | Wave D ships new YAML config surface; Wave C #56 ships new schema column; Wave C #45 ships new event_type. All backward-compat additions per versioning policy. | Patch (0.34.1 â€” but additions aren't pure fixes); major (0.35â†’1.0 â€” premature) | Trivial (1-line string change) | Operator CHECKPOINT 2026-05-12 |
| 3 | Wave D defaults: BACKWARD-COMPAT | Zero-config users see no change; operator opts in. Minimizes blast radius. | Opt-out (quiet hours on by default â€” risk of suppressing real alerts before operator notices) | Zero (operator deletes config keys to restore) | Operator CHECKPOINT 2026-05-12 |
| 4 | PR boundary: PER-WAVE PRs (6 total) | Matches recent successful #1058/#1059/#1060 cadence. Smaller review surface; smaller blast radius per merge. | Monolithic Sprint Close PR (worse review surface, harder rollback) | Low (PM can batch-merge with single CHANGELOG section) | Operator CHECKPOINT 2026-05-12 |
| 5 | `docs/roadmap.md`: CREATE NEW | Sprint history + active-track pointer is distinct from operator-runnable runbook content. Cleaner separation. | Fold into `docs/operator-guide.md` Sprint history section (mixed concerns) | Low (file move + redirect-pointer) | Operator CHECKPOINT 2026-05-12 |
| 6 | #97 alpaca_adapter: GRANDFATHER + delete sentinel test | File split is high-blast-radius. Sentinel test currently incongruent. Cleanest fix: known_violations.json entry + delete sentinel. | Actually split file in SP5 (>4 hrs work, touches every alpaca call site); accept failing test (governance violation) | Low (operator can split in any post-sprint PR) | Operator CHECKPOINT 2026-05-12 |
| 7 | #96 platform_events: SCOPE-OUT pending write-site grep | Deep-report finds no clear write-site; comment-only drift. Add TableDef only if Wave C developer confirms write-site. | Add TableDef unconditionally (risks dead schema); ignore entirely (perpetuates drift) | Low (in-PR decision; doesn't block Sprint Close) | Operator CHECKPOINT 2026-05-12 |
| 8 | #68 reframe: typed hierarchy + agent_data.py only | Brief premise WRONG â€” only 1 raise site exists; real opportunity is 30+ bare except Exception. Engine.py + value_tracker.py deferred to keep scope tractable. | Refactor all of council/ (>2x scope; risks Sprint 5 close slip); skip entirely (misses the safety improvement) | Low (post-sprint sibling work can extend) | Architect (deep-report) |
| 9 | safe_send policy gate inserted IN-PLACE (no separate router module) | Duplicating event_map in a parallel router.py would weaken the KeyError-on-unknown-event_type security boundary. | New `src/notifications/router.py` module (parallel surface; harder to reason about composition) | Low (in-place insert is easily revertable) | Architect (Sprint 4 T2 security carry-forward) |
| 10 | Digest queue: DB-backed not in-memory | Watch loop restarts must not lose buffered events. SQLite/PG durability is the existing pattern. | In-memory deque (data loss on restart); Redis (new infrastructure dependency) | Low (table drop + module remove) | Architect |
| 11 | Source tag column added to notifications_sent (not separate audit table) | Notifications_sent already tracks every dispatch; source_tag is per-row metadata, not a separate event stream. | New `notification_audit` table (duplication; two-way join overhead) | Low (column drop) | Architect (#101 design) |
| 12 | Retry policy: 3 attempts with [1, 5, 30]s backoff | Tuned to Telegram's intermittent failure rate (F2: 2-3 failures/hour). Total wait per failed event = 36s, acceptable for non-hot-path. | Single attempt (current â€” too brittle); 5+ attempts (DoS risk) | Trivial (config tunable) | Architect (F2 mitigation) |
| 13 | Escalation: 5 failures in 10 min â†’ email fallback | Captures sustained outages while tolerating transient blips. Email is the operator's secondary channel. | No escalation (F2 blind spot persists); SMS (new dep) | Trivial (config tunable) | Architect (F2 mitigation) |
| 14 | Sequence C4 â†’ D2 â†’ D5 for `src/scheduler/watch.py` edits | Three tasks edit the same file. Sequential PRs avoid worktree race. C4 lands first because Wave C precedes Wave D per glidepath. | Parallel + manual merge resolution (race risk per memory `feedback_review_sibling_search`) | Low (each PR is independent rebase) | Architect |
| 15 | Wave F #87 PG port 5433 (not 5432) | Avoid clash with operator's local PG (memory `reference_local_ports`: 8080 EnterpriseDB; PG on 5432 is operator's). | 5432 (collision risk); random port (test fixture complexity) | Trivial (port reassignment) | Architect (memory-grounded) |
| 16 | Test floor canon: 5350 (10-test buffer below projected 5400-5450 median) | Projection has +/- range; 50-test conservative margin prevents flaky-test-day floor failures. | 5400 (tighter, risk transient drops); 5050 (no progress) | Trivial (CLAUDE.md + pg-tests.yml number) | Architect |
| 17 | `_scalar` cosmetic removal: SAME PR as Sprint Close, with scope-cap | Sprint Close is the natural home; ~30 file mechanical sweep is cosmetic, not architectural. Scope-cap: if >40 files, defer to post-sprint. | Standalone PR (PR count inflation); never remove (helper rots) | Trivial (already a mechanical revert) | Architect (post-PR-1060 cleanup) |

---

## 11. Do-Not-Do (explicit anti-requirements)

- DO NOT create a parallel `src/notifications/router.py` module. Modify `safe_send` in-place.
- DO NOT widen `safe_send`'s narrow network-except tuple. AST guardrail enforces.
- DO NOT add YAML `!include` or other tag-interpolation parsing. Use `yaml.safe_load` only.
- DO NOT make `event_map` mutable / dynamically extensible via config. Config REFERENCES existing keys.
- DO NOT refactor `engine.py` or `value_tracker.py` `except Exception` blocks in #68. Scope-defer per deep-report.
- DO NOT actually split `alpaca_adapter.py` in this sprint. Grandfather per Decision 6.
- DO NOT add `platform_events` TableDef unless Wave C developer's grep confirms write-site.
- DO NOT implement Wave E in this sprint. Disposition doc only.
- DO NOT bump test floor without verifying actual sweep count first (avoid 3682â†’5350 â†’ ghost-floor failure).
- DO NOT skip the operator-guide update per CLAUDE.md rule.
- DO NOT defer CHANGELOG entries â€” each wave PR updates `[Unreleased]`, Sprint Close aggregates.
- DO NOT use `git push --no-verify` on any of these PRs (no emergency hotfix justification).
- DO NOT introduce a new bare `except Exception` anywhere. Use typed catches.
- DO NOT call real Telegram API from pytest. Conftest null-router is mandatory.

---

## 12. Falsifiability Triggers

The spec is INVALIDATED (and must be revised) if any of the following surface during execution:

- **Wave C #56**: `strategy_registry` TableDef does NOT exist or its PK column name is unknown â€” spec must revise FK target before PR
- **Wave C #45**: `alpaca_adapter.get_all_positions()` does NOT return a usable `{ticker: qty}` shape â€” spec must revise drift comparison surface
- **Wave D D1**: existing `event_map` dict at `telegram.py:1287` is private/internal and cannot be enumerated for config validation â€” spec must revise validation strategy (likely: export a public `EVENT_TYPES` set)
- **Wave D D2**: `notifications_digest_queue` cannot atomically mark `flushed_at` (no `SELECT ... FOR UPDATE` on SQLite) â€” spec must revise to use `WHERE flushed_at IS NULL` guarded by retry-on-conflict
- **Wave F F3**: docker-compose v2 not installed on operator machine OR on CI runner â€” spec must revise to use `docker compose` CLI feature detection + clearer SKIP message
- **Sprint Close**: actual test sweep count is < 5350 after all waves merged â€” investigate dropped tests before bumping floor; possible that an early wave un-skipped fewer than projected
- **Cross-cutting**: any wave PR's diff includes whitespace-only lines from CRLF/LF drift > 5% of total diff lines â€” operator opts in `.gitattributes` LF normalization as a Sprint Close addendum

---

*End of spec. PM consumes the accompanying task graph for execution.*
