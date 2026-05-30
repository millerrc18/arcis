# Sprint 4 — Cockpit Followups + Notification Subsystem — Design Spec

**Generated**: 2026-05-07
**Source artifacts**:
- `docs/audits/2026-05-06-cockpit-coherence-sprint/sp4-followups.md` (11 issues, ~380 lines)
- `docs/audits/2026-05-07-telegram-email-sweep/{summary.md,cross-cutting.md,recommendations.md}` (50 findings, 6-group split)
- `docs/audits/2026-05-06-cockpit-coherence-sprint/spec.md` (Sprint 3 reference structure)

**Reviewer**: design-feasibility + design-roast (post-architect; revision pass 1 applied 2026-05-07)
**Consumable by**: `arcis:code` PM orchestrator
**Sprint base branch**: `sprint/cockpit-followups-2026-05-07/base`
**Test floor**: 4702 → `>= 4798` (without T22) or `>= 4804` (with T22) — semantic `>=` enforced at T23. Per-task accounting in plan.md §"Test-floor accounting".
**Integration target**: `main`

> **Wave ↔ Batch cross-reference**: spec narrates 4 logical Waves (W0/W1/W2/W3); plan dispatches 9 numbered Batches (Batch 0 → Batch 8). Both labels appear throughout this document; the plan.md cross-reference table is the single source of truth. **W1 (blocker) = Batches 1+2+3a (T2-T8 + T14)**.

---

## 1. Executive Summary

Sprint 3 closed the dashboard surface to a high quality bar. Sprint 4 closes (a) the 10 follow-up issues that Sprint 3 deferred (`#SP4-*` tracker) and (b) brings the notification subsystem to the same bar (`#47` triage of the 50-finding telegram + email sweep). One issue (`#SP4-settings-backend-float32-storage`) is closed as **WON'T FIX** with operator-guide note.

**Net scope:**
- 10 cockpit followups consolidated into 8 functional groupings (one is WON'T FIX).
- 1 cross-domain notification cluster split into 6 groups (A-F per audit recommendations).
- 24 named tasks (1 split: T11 → T11 + T11.5; 1 split into sub-PRs T4a-T4d) across 4 logical waves / 9 plan batches.
- ~+96 tests (test floor 4702 → `>= 4798` without T22 / `>= 4804` with T22). Per-task accounting in plan.md §"Test-floor accounting".
- Critical highlight: **W1 (blocker = plan-Batches 1+2+3a) must close Group A (Notifications NameError + safe_send) before any Sprint 4 deploy**. CUSUM, leakage, model-regression alerts are silently broken in production right now (`overnight.py:134, 149, 304, 311` call `send_telegram_message` which does NOT exist; the NameError is swallowed by `except Exception`).

**Sprint 4 wave structure (logical) — see plan.md for 9-batch dispatch graph:**

| Wave | Plan Batches | Tasks | Theme | Why this order |
|------|--------------|-------|-------|----------------|
| **W0** | Batch 0 | T1 | Sprint base — branch + per-task CHANGELOG line pre-allocation + before/ screenshots | Per-task placeholder lines avoid CHANGELOG cascade merge conflicts |
| **W1** | Batches 1+2+3a | T2-T8 + T14 (~9 tasks; T4 = 4 sub-PRs) | Group A (notifications NameError + safe_send) + cloud-req CI guardrail + Group E.A schema registration | Blocker. Production alerts silently broken; cloud-req drift caused #1006/#1007 in Sprint 3 |
| **W2** | Batches 3b+4+5 | T9, T10, T11, T11.5, T12, T13, T15, T16, T17, T18, T19, T20 (~12 tasks) | Group B (email) + Group C (telegram template) + Group E.B (observability) + cohort + KPI + frontend signs + queryFn fix + reconciliation + visual-verify checkpoint | Parallel-safe medium-effort blocks. No file overlap |
| **W3** | Batches 7a+7b+8 | T21, T22, T23 (~3 tasks) | Group F (operator-guide + coverage) + Group D operator-discretion + closeout | Closeout. Group D operator-discretion at dispatch — may slip to Sprint 5 |

**Carry-over commitments:**
- All Wave 1 tasks must land before any Wave 2 dispatch.
- Visual-verify gate at integration (Chrome DevTools MCP, mirrors `docs/audits/2026-05-06-cockpit-coherence-sprint/visual-verify/`).
- Per-deliverable commit-and-push for ≥3-sub-deliverable tasks (Group A, B, C, F).
- Pre-commit scope-check (`#699`) + pre-push stale-base (`#59`) hooks active for ALL dispatches.
- Worktree isolation per parallel agent dispatch (CLAUDE.md mandate).
- Sibling-search rule for any per-line bug fix (per memory `feedback_review_sibling_search`).

---

## 2. Audit Findings (consolidated, severity-organized)

### 2.1 CRITICAL — production-broken (must close in Wave 1)

| ID | Where | Effect | Wave | Closes via |
|----|-------|--------|------|-----------|
| `notif-C1` | `src/scheduler/overnight.py:134, 149, 304, 311` | `send_telegram_message` doesn't exist; NameError swallowed by `except Exception`. CUSUM, leakage, model-regression alerts silently fail. | W1 | T2 (Group A) |
| `notif-CC1` | 25+ caller sites | Structural anti-pattern: `try/except Exception` around notify_* hides import-time NameErrors as if they were network failures. | W1 | T3, T4 (Group A safe_send + migration) |
| `cloud-req-import` | `requirements-cloud.txt` drift | 4th recurrence (jsonschema → numpy → requests → scipy). #1007 hot-fix in Sprint 3. | W1 | T7, T8 (cloud-req guardrail dual-lane) |
| `notif-C2` | `src/email/notifier.py` (full file, 0 tests) | SMTP, TLS, CC, ConnectionRefusedError all unasserted; 6 production paths depend on this | W2 | T11 (Group B) |
| `notif-C5` | `src/email/notifier.py:51` | `[recipient] + cc_addresses` raises TypeError if cc_addresses is None | W2 | T11 (Group B) |
| `notif-C4` | `src/email/notifier.py:34` | Email password fallback to YAML; `your-app-password-here` literal in `settings.example.yaml` | W2 | T11 (Group B) |
| `notif-C15` | `src/notifications/telegram.py` `send_telegram` function body (locate by name; approximate `:125-160`) | No 4096-char chunked-send path exists today (verified by GREP — no `4096`/`truncate` reference). Long bodies (`notify_weekly_digest` 28 fields) are silently dropped by Telegram API. | W2 | T13 (Group C — adds chunked send) |
| `notif-C11` | `src/notifications/platform_events.py:26` | `_DEDUP_CACHE = {}` is process-local; NSSM restart re-fires same alerts | W2 | T15 (Group E persistence) |
| `notif-C17` | `src/email/notifier.py:70-72` + 6 callers | `except Exception: return False`; SMTP down all day → silent fails | W2 | T11+T15 (Group B/E fallback) |

### 2.2 IMPORTANT — quality bar (Sprint 4 if scope permits)

| ID | Where | Closes via |
|----|-------|-----------|
| `cockpit-#1` shadow_metrics live cohort | `src/api/cloud_routes/trades.py:301-343` (NOT analytics.py — drift alert) | T9 (helper extension at trades.py:42) |
| `cockpit-#2` /api/status open_positions cohort | `src/api/cloud_routes/core.py:147-150` (no source filter; cohort label says `trades.live_only`) | T10 |
| `cockpit-#3` Calmar 4 sites migrate | `src/evaluation/cto_report.py:738`, `src/simulation/engine.py:439`, `src/evaluation/backtester.py:343`, `src/platform/metrics.py:75` | T17 |
| `cockpit-#4` stop_loss sign (REFRAMED) | 5 frontend sites: `LiveLedger.jsx:40`, `ShadowLedger.jsx:64,568,592`, `TradeHistory.jsx:31-36` | T18 |
| `cockpit-#5` PG reconciliation parametrize | `tests/test_dashboard_reconciliation.py` + new `tests/conftest.py` postgres fixture | T19 |
| `cockpit-#6` /api/kpis _meta envelope test | `tests/test_dashboard_reconciliation.py` (extension) | T19 |
| `cockpit-#7` bare queryFn 2 sites + ESLint rule extension | `frontend/src/pages/StrategyResearch.jsx:41` + `frontend/src/components/PlatformStatusWidget.jsx:13` + `frontend/eslint-rules/no-bare-queryfn-with-args.js` | T16 |
| `cockpit-#8a` backend total_pnl_dollars emit | `src/api/cloud_routes/kpis_compute.py` + `src/api/cloud_routes/kpis.py` | T11 (depends on Group B parallel-safe; T12 frontend) |
| `cockpit-#8b` KPIStrip P&L card | `frontend/src/components/dashboard/KPIStrip.jsx` (replace PromotionGateCard, tooltip vote count under Stage TL) | T12 (depends on T11) |
| `notif-Group-D` mute/digest/routing | (operator-discretion at W3 dispatch) | T22 (optional) |
| `notif-Group-F` operator-guide + coverage | `docs/operator-guide.md`, `tests/notifications/test_telegram_send_path.py` | T21 |

### 2.3 WON'T FIX (operator-confirmed)

| ID | Where | Reason | Closeout |
|----|-------|--------|----------|
| `cockpit-#9` settings backend float32 storage | `src/api/cloud_routes/settings.py` write path | Drift alert from analyst: storage is already exact JSON-text (`registry.py:1568` ColumnDef('setting_value', 'TEXT', nullable=False)). No `numpy.float32` cast in Python write path. Float32 noise is **Chrome a11y tree behavior** — browser casts JS Number to float32 for screen-reader output. No Python-side fix possible. | T23 closeout adds 1-paragraph note to `docs/operator-guide.md` |

---

## 3. Architecture Decisions

See `design_decisions[]` for the canonical record. Top-level decisions called out in spec:

### 3.1 Cohort taxonomy unchanged (8 cohort_ids)

`src/api/cohort_meta.py:22` defines 8 cohorts: `kpi.canonical`, `trades.all_closed`, `trades.strategy`, `trades.model`, `trades.live_only`, `stress.scenario`, `attribution.pairs`, `none`. Sprint 4 adds NO new cohort labels. Area 1 (`#SP4-shadow-metrics-live-cohort`) uses existing `trades.live_only`.

### 3.2 `_desk_clause` extension at `trades.py:42` (NOT analytics.py)

Drift alert from deep analysis: helper lives at `src/api/cloud_routes/trades.py:42-57`, NOT `analytics.py` as the brief implied. The helper is shared by 5 endpoints (shadow_open, shadow_closed, sharpe_attribution, shadow_metrics, shadow_account).

**Current signature** (architect-verified): `_desk_clause(desk: str | None) -> tuple[str, list]` — takes a `desk` string IN, returns `(sql_fragment, params)` tuple OUT.

**T9 extension**: `_desk_clause(desk: str | None) -> tuple[str, list, str]` — same `desk` IN; output gains a third element `cohort_id`. For `desk='live'`, helper returns `('source = %s', ['live'], 'trades.live_only')`. Other desks return `cohort_id='trades.all_closed'`. This is a 5-endpoint blast radius accepted in one task to keep the helper-shape change atomic. (Reviewer pass-1 corrected an inverted INPUT/OUTPUT description from the prior revision.)

### 3.3 calmar_ratio canonical migration — allowlist becomes empty

All 4 hand-rolled Calmar sites (`cto_report.py:738`, `engine.py:439`, `backtester.py:343`, `platform/metrics.py:75`) migrate to `src/evaluation/statistics.py:131` `calmar_ratio()`. Allowlist in `tests/test_calmar_canonical_only.py` becomes empty after T17. Test retains `test_no_new_calmar_formulas` + `test_no_calmar_named_functions` for ongoing protection. Operator confirmed full scope.

**Compatibility verification per site (from deep analysis):**
- `cto_report.py:738`: `(mean_r * 150) / max_dd_pct` — pass `calmar_ratio(mean_r * 150, max_dd_pct)`.
- `engine.py:439`: `annualized_return / max_dd` — direct compatible.
- `backtester.py:343`: `round(ann_return / abs(max_dd_pct), 2)` — apply round at call site.
- `platform/metrics.py:75` (`compute_calmar`): `total_return / max_drawdown` returns `inf` if `max_dd==0`. **Divergence with canonical** which returns `0.0`. T17 verifies no consumer depends on `inf` sentinel; if any does, route via wrapper that maps 0.0 → caller-expected sentinel.

### 3.4 Notification subsystem — `safe_send` central wrapper

`safe_send(event, **kwargs)` in `src/notifications/__init__.py` becomes the single ingress for all 25+ caller sites. Behavior:

1. Imports target notify_X explicitly. ImportError raises immediately (NOT swallowed).
2. Checks `is_telegram_enabled()` once internally.
3. Calls notify_X.
4. Catches ONLY network failures: `urllib3.exceptions.HTTPError`, `requests.exceptions.RequestException`, `socket.timeout`, `OSError`. **NOT `Exception`** — NameError, KeyError, TypeError propagate.
5. Logs at appropriate severity (warning transient, error repeat).
6. Increments `notifications_sent_failed` counter (feeds Group E observability table).
7. Persists outcome to `notifications_sent` table with status `ok`/`failed`/`dropped`.

Group A migration mechanically replaces 25+ `try/except Exception { import + check + call }` with one-line `safe_send('event_name', **kwargs)`.

### 3.5 KPIStrip 6th card — replace PromotionGateCard (recommended)

The vote count duplicates Stage Traffic Light gate context. Architect recommendation per CODEBASE_REPORT analyst hint:
- Replace `PromotionGateCard` (5th card) with new **`TotalPnlDollarsCard`** sourcing `safeKpis.total_pnl_dollars`.
- Surface vote count as tooltip badge under Stage Traffic Light card (where it belongs contextually).
- Wire `meta={safeKpis._meta?.total_pnl_dollars}` to new card.
- New card uses canonical KPICard meta-prop API from Sprint 3 T5.

Operator may override at Wave 2 dispatch (alternative: add 6th card and keep both — grid changes from `repeat(5,1fr)` to `repeat(6,1fr)`). Architect tracks both options in T12 description.

### 3.6 Cloud-req CI guardrail in Wave 1 (dual-lane)

Operator-confirmed Wave 1. Two complementary tests:
- **Fast lane**: AST-walker enumerates imports reachable from `src/api/cloud_app.py`, asserts each top-level package is stdlib OR in `requirements-cloud.txt`. Runs in seconds.
- **Slow lane (CI only)**: pytest with subprocess creates temp venv, installs ONLY `requirements-cloud.txt`, runs `python -c 'from src.api.cloud_app import app'`, asserts exit 0. Marked `@pytest.mark.slow`.

Fast lane catches 95% of cases at PR-time without venv overhead. Slow lane catches cross-package transitive imports the AST walker misses.

### 3.7 ESLint rule extension bundled with Area 7 fix

Drift alert: bare queryFn at `StrategyResearch.jsx:41` and `PlatformStatusWidget.jsx:13` is **`Identifier`** (named import: `queryFn: getPlatformStrategies`), NOT `MemberExpression` (`queryFn: api.foo`). The Sprint 3 ESLint rule at `frontend/eslint-rules/no-bare-queryfn-with-args.js:60` only flags `MemberExpression`. T16 extends the rule to flag any `prop.value` where `type !== 'ArrowFunctionExpression' && type !== 'FunctionExpression'`. Bundles call-site fix + rule extension in same PR.

### 3.8 stop_loss task reframed (NOT stop_loss-specific)

Drift alert from analyst: bug pattern is `Math.abs(pnl).toFixed(2)` with conditional `+` prefix only for positive — strips negative sign for ALL losing trades, not just stop_loss exits. Reframe T18 as **"fix dollar P&L sign formatting at 5 frontend sites"**.

Affected sites (all in scope of T18):
- `frontend/src/pages/LiveLedger.jsx:40` (`PnlValue` function)
- `frontend/src/pages/ShadowLedger.jsx:64` (`PnlValue` function)
- `frontend/src/pages/ShadowLedger.jsx:568` (open-cols inline)
- `frontend/src/pages/ShadowLedger.jsx:592` (closed-cols inline)
- `frontend/src/pages/TradeHistory.jsx:31-36` (`formatDollars` — verify)

Non-buggy site (do NOT touch): `frontend/src/components/ActivityFeed.jsx:57` passes raw signed value; JS formats negative with `-` natively.

### 3.9 #SP4-settings-backend-float32-storage closed as WON'T FIX

Drift alert from analyst: storage is already exact JSON-text (`registry.py:1568` ColumnDef stores TEXT; `apply_override` calls `json.dumps(value)` preserving IEEE-754 double). No `numpy.float32`, `.astype`, or `float32` cast anywhere in write path. Float32 noise (`aria-valuenow="0.004999999888241291"`) is **Chrome a11y tree behavior** — browser casts JS Number to float32 for screen-reader output. NO Python-side fix possible. T23 closeout adds 1-paragraph note to `docs/operator-guide.md`.

### 3.10 Notification observability table (CC4)

New schema-registry tables:

**`notifications_sent`** — append-only audit log:
- `id` INTEGER PRIMARY KEY
- `event_type` TEXT NOT NULL (e.g. `cusum_alarm`, `eod_recap`, `trade_opened`)
- `channel` TEXT NOT NULL (`telegram`, `email`)
- `recipient` TEXT (chat_id or email address; nullable for broadcast)
- `sent_at` TEXT NOT NULL (ISO timestamp)
- `status` TEXT NOT NULL (`ok`, `failed`, `dropped`, `heartbeat`)
- `retry_count` INTEGER NOT NULL DEFAULT 0
- `error_msg` TEXT (nullable)

Index: `(event_type, sent_at DESC)` for cockpit health widget queries. **Retention/cleanup**: `notifications_sent` is append-only and will grow unbounded. Sprint 5 follow-up `#SP5-notifications-retention` should add a daily cleanup task (delete rows where `sent_at < NOW() - 90 days`, except `status='heartbeat'` which retains for ops monitoring). For Sprint 4, table is allowed to grow — operator can `DELETE FROM notifications_sent WHERE sent_at < ...` manually if needed.

**`notifications_dedup`** — replaces process-local `_DEDUP_CACHE`:
- `id` INTEGER PRIMARY KEY (matches codebase convention; reviewer item-MINOR)
- `event_type` TEXT NOT NULL
- `dedup_key` TEXT NOT NULL
- `sent_at` TEXT NOT NULL
- UNIQUE constraint: `(event_type, dedup_key)` — enforces deduplication

Lookup: `SELECT 1 FROM notifications_dedup WHERE event_type=? AND dedup_key=? AND sent_at > <cutoff>`.

Both tables registered via `src/schema/registry.py:TABLES`. CLAUDE.md schema rules apply — NO `CREATE TABLE` outside registry.

### 3.11 Group D (mute/digest/routing) operator-discretion

Group D is the largest sub-cluster (~3-5 days, multiple files). Fix-now-vs-fix-later judgment per memory `feedback_fix_before_trade`: it's IMPORTANT (not CRITICAL), so operator may slip to Sprint 5. Architect schedules T22 as plan-Batch-7b (separated from T21 = plan-Batch-7a) with explicit operator-discretion gate.

**Workflow (per reviewer item #14):**
1. After T20 visual-verify checkpoint completes, PM dispatches T21 (Batch 7a).
2. Once T21 returns green, PM **surfaces T22 dispatch question to operator** via Telegram or AskUserQuestion: "Sprint 4 Group D (mute/digest/routing) — Y/N? Skipping opens follow-up `#SP5-notifications-routing-policy`."
3. If approved → dispatch T22 (Batch 7b) in parallel with sprint-closeout prep. T22 deliverables fold into T23.
4. If declined → skip T22 entirely; open `#SP5-notifications-routing-policy`; T23 proceeds without T22 in dependency graph.

This separation prevents PM from auto-dispatching T22 alongside T21; the operator gate is enforced by batch boundary, not just task description.

---

## 4. Implementation Plan (per-task spec)

See `plan` field for the full task graph in PM-orchestrator schema. Below is the human-readable view organized by wave.

### Wave 0 — Sprint base (1 task, sequential)

**T1 — Sprint base setup + per-task CHANGELOG line pre-allocation**
- Create branch `sprint/cockpit-followups-2026-05-07/base` off `main`.
- **Pre-allocate ONE LINE PER TASK in `CHANGELOG.md` `[Unreleased]` with explicit task-id markers** — each task PR replaces ONLY its placeholder line, no adjacent edits permitted. Allocate `<!-- T2 -->` through `<!-- T23 -->` plus all sub-PR markers (`<!-- T4a-d -->`, `<!-- T11a-b -->`, `<!-- T13a-c -->`, `<!-- T15a-c -->`, `<!-- T17a-b -->`, `<!-- T18a-c -->`, `<!-- T21a-c -->`). See plan.md T1 for the canonical placeholder list. Per reviewer item #9 — pre-writing a single shared block does NOT prevent merge conflicts unless each PR appends to a UNIQUE pre-allocated line.
- Create `docs/audits/2026-05-07-sprint-4-cockpit-followups/visual-verify/{before,after}/` directory skeleton.
- Capture `before/` Chrome DevTools MCP screenshots of **the 11 priority pages enumerated below** (verbatim from Sprint 3's `docs/audits/2026-05-06-cockpit-coherence-sprint/visual-verify/before/`):
  1. `01-dashboard.png`, 2. `03-shadow-ledger.png`, 3. `05-trade-history.png`, 4. `06-strategy.png`, 5. `09-cto-report.png`, 6. `10-attribution.png`, 7. `11-model-perf.png`, 8. `15-stress-test.png`, 9. `21-monitoring.png`, 10. `23-settings.png`, 11. `24-roadmap.png`.
- **Acceptance criteria for NEW components** (no `before/` baseline can exist):
  - **P&L card** (T12; new `25-kpi-pnl-card.png`): renders with `$X,XXX.XX` format, meta badge visible, no console errors, value matches `/api/kpis._meta.total_pnl_dollars.value`.
  - **NotificationsHealthPanel** (T15; new `26-notifications-health-panel.png`): shows `success_rate / fail_count / dedup_hits / oldest_unack_alert` fields (all numeric); no `--` placeholders; meta badge cohort = `notifications.health` (or whatever cohort_id is selected during T15b implementation).

### Wave 1 — Blocker (Plan-Batches 1+2+3a; ~9 tasks counting T4 sub-PRs, fully serialized through T1, then parallel where safe)

**T2 — Group A.1 — Rename `send_telegram_message` → `send_telegram` at 4 overnight.py sites**
- `src/scheduler/overnight.py:134, 149, 304, 311` — rename. 4-line mechanical fix.
- Sibling-search rule (EXPANDED scope per reviewer): GREP `src/ scripts/ tests/` for `send_telegram_message`. Pre-fix expect ONLY the 4 sites in `src/scheduler/overnight.py`. Post-fix expect 0 across all paths. **If pre-fix GREP shows >4 matches anywhere, treat as drift alert and surface to PM before proceeding** — do NOT auto-fix unexpected sites without explicit confirmation.
- New regression test: `tests/notifications/test_overnight_alarm_paths.py` (NEW) asserts each of the 4 alarm sites successfully invokes the real `send_telegram`. Mock the underlying transport. (Glob-verified: `tests/notifications/` directory exists with `__init__.py` + 2 existing test files.)

**T3 — Group A.2 — Build `notifications.safe_send()` central wrapper**
- `src/notifications/__init__.py` re-export `safe_send`.
- `src/notifications/telegram.py` add `safe_send(event_type, **kwargs)` per §3.4.
- New `tests/notifications/test_safe_send.py`: assert ImportError propagates, network errors caught, `notifications_sent_failed` incremented on failure.
- Depends on T2 (so rename is in place before migration).

**T4 — Group A.3 — Migrate 25+ caller sites to `safe_send()`**
- 16 caller files (per recommendations.md): `src/scheduler/{watch,reports,watch_handlers}.py`, `src/scheduler/overnight.py`, `src/shadow_trading/executor.py`, `src/services/{scan_service,recap_service,watchlist_service}.py`, `src/training/{canary,ingestion_gate,trainer}.py`, `src/risk/governor.py`, `src/evaluation/auditor.py`, `src/data_collection/research_synthesizer.py`, `src/cli/commands.py`, `src/api/cloud_routes/platform.py`.
- **Split into 4 sub-tasks** to honor `max 4 files_in_scope` per task: T4a, T4b, T4c, T4d. Sub-task batching is parallel-safe (zero file overlap among sub-tasks).
- Mechanical: replace `try/except Exception { import + check + call }` with one-line `safe_send('event_name', **kwargs)`.
- Per-deliverable commit-and-push: each sub-task is one PR.

**T5 — Group A.4 — Fix I10 (cli/commands.py lazy imports)**
- `src/cli/commands.py`: replace lazy in-function imports with module-level imports. Let `ImportError` happen at process startup, not at first runtime hit.
- Sibling-search GREP: `^\s*from src\.notifications` inside function bodies; expect zero post-fix.

**T6 — Group A.5 — Fix I12 + CC2 (function-wide bare except + duplicated config loaders)**
- I12: `src/notifications/telegram_commands.py:236-237` `check_action_reminders` — break function-wide `except` into per-check `except`. Each of 5 reminders independently fails.
- CC2: consolidate `_get_telegram_config` (architect-verified line numbers: `src/notifications/telegram.py:104` + `src/notifications/telegram_commands.py:32`; revised from prior `:114` + `:43`) into shared helper at `src/notifications/_config.py` (NEW file). Both modules import from the new shared module.

**T7 — Cloud-req CI guardrail (fast-lane AST walker)**
- New `tests/test_cloud_requirements_imports.py`: AST walks imports reachable from `src/api/cloud_app.py`, asserts each top-level package is stdlib OR in `requirements-cloud.txt`. Sub-second runtime. Runs on every PR.
- New `scripts/check_cloud_deploy_imports.py` shareable invocation (used by T8 slow-lane and CI).

**T8 — Cloud-req CI guardrail (slow-lane venv subprocess)**
- Extend `tests/test_cloud_requirements_imports.py` with `@pytest.mark.slow` test that creates a temp venv, installs `requirements-cloud.txt` only, runs `python -c 'from src.api.cloud_app import app'`. Asserts exit 0 + no `ModuleNotFoundError`.
- CI matrix: gated behind `--run-slow` flag locally; opt-in via env in CI.
- Worktree env-drift caveat (memory `feedback_worktree_env_drift`): venv setup is hermetic, doesn't carry `.env`.

### Wave 2 — Parallel medium-effort blocks (~12 tasks, parallel-safe)

**T9 — Cockpit-#1 — Shadow metrics live cohort (helper extension)**
- DRIFT-CORRECTED files: `src/api/cloud_routes/trades.py:42-57` (`_desk_clause`), `trades.py:301-343` (shadow_metrics endpoint).
- Extend helper signature: `(frag, params)` → `(frag, params, cohort_id)`. For `desk='live'`: emit `source = %s` with param `'live'` + `cohort_id='trades.live_only'`. Other desks: `cohort_id='trades.all_closed'`.
- 5-endpoint blast radius: shadow_open, shadow_closed, sharpe_attribution, shadow_metrics, shadow_account. All update to consume new tuple shape.
- Test extensions: per-desk cohort assertion (replace `test_shadow_metrics_all_desks_emit_all_closed`).

**T10 — Cockpit-#2 — /api/status open_positions cohort align**
- `src/api/cloud_routes/core.py:147-150`: add `WHERE source='live'` to SQL.
- Cohort label `'trades.live_only'` (already at `core.py:189`) now matches SQL.
- Reconciliation: `/api/status.open_positions == /api/live/summary.open_positions` (T16 already asserts equality; T19 extension verifies cohort match).
- Sibling-search GREP `core.py` for any other `WHERE status='open'` that lacks source filter.

**T11 — Cockpit-#8a — Backend `total_pnl_dollars` emit (8a backend ONLY; Group B email split into T11.5)**
- `src/api/cloud_routes/kpis_compute.py`: add `compute_total_pnl_dollars(instrumented)` returning sum of `pnl_dollars` rounded.
- `src/api/cloud_routes/kpis.py`: at the `@router.get("/kpis", ...)` decorator (architect-verified line `:104`; the `get_kpis()` function body return-dict spans `:116-136`, REVISED from prior `:115-135`) — emit `total_pnl_dollars` field + `_meta.total_pnl_dollars` (cohort `'kpi.canonical'`, n=n_trades).
- New tests in `tests/api/test_kpis.py`: assert field present, asset _meta cohort/label/n shape.
- Parallel-safe with T13/T15 (different files).
- T11.5 (Group B email subsystem hardening) split per reviewer item-MINOR — different files, parallel-safe with T11.

**T11.5 — Group B — Email subsystem hardening + tests**
- `src/email/notifier.py`: fix C5 (`cc_addresses or []`), drop YAML password fallback C4 (require `EMAIL_PASSWORD` env, startup warn if YAML key non-empty), I17 (`config['training']['target_examples']` for digest_builder), C17 telegram-fallback path (uses `safe_send` from T3).
- `src/email/__init__.py`: re-export digest_builder per N1.
- New `tests/email/test_notifier.py` (NEW; `tests/email/` directory does NOT yet exist — create it): mock `smtplib.SMTP`; assert envelope (To/Cc/Subject), TLS path, auth path, `from_address` fallback, `ConnectionRefusedError` handling, telegram-fallback fires when SMTP returns False.
- Per-deliverable commit-and-push: T11.5 ships as one PR (4 files; under cap).
- Depends on T3 (safe_send for C17 telegram-fallback). Does NOT depend on T11 — parallel-safe.

**T12 — Cockpit-#8b — KPIStrip P&L card (replace PromotionGateCard)**
- `frontend/src/components/dashboard/KPIStrip.jsx:285-303`: replace `<PromotionGateCard>` with new `<TotalPnlDollarsCard>`. Surface vote count as tooltip badge under `<TrafficLightCard>` (lift `kpi={safeKpis.promotion_gate}` into TL card's tooltip slot).
- New `TotalPnlDollarsCard` follows existing card API; reads `safeKpis.total_pnl_dollars` + `safeKpis._meta?.total_pnl_dollars`.
- Extend `KPIStrip.test.jsx`: assert P&L card renders, vote count visible in TL tooltip, no PromotionGateCard.
- **Visual-verify rule**: render in browser before push (memory `feedback_visual_verify_ui`).
- Depends on T11.
- Operator may override architecture decision at Wave 2 dispatch (alternative: 6th card; grid `repeat(6,1fr)`). Both options documented in description.

**T13 — Group C — Telegram template hygiene + chunked send + HTML escape**
- `src/notifications/telegram.py`: add `_html_escape(text)` helper (I6); use on all interpolated string fields. Add chunked send for `>4000 chars` with `[chunk N/M]` markers (C15). Apply to all `send_telegram` callers automatically.
- C16: `notify_research_digest` truncates summary, append `[truncated; see email digest]`.
- C7: mirror `notify_overnight_training_complete` `dict-with-success` pattern in `notify_overnight_complete`.
- I11: `notify_action_required` icons map raises on unknown urgency.
- I16: drop manual `&amp;` escapes in `notify_premarket_brief` and `notify_weekly_digest`; use `_html_escape`.
- I15: normalize earnings time labels in `src/data_ingestion/finnhub.py` adapter (upstream).
- New tests: `tests/notifications/test_telegram_chunked_send.py`, `tests/notifications/test_html_escape.py`.
- Per-deliverable commit-and-push: split into T13a (chunked + escape helper + tests) + T13b (notify_* updates) + T13c (finnhub I15 + I11 urgency).

**T14 — Group E.A — `notifications_sent` + `notifications_dedup` schema registration (W1 task; moved from W2)**
- Per reviewer revision pass 1: schema registration moved to W1 (Batch 3a) so T15 (W2) can wire write hooks against an already-registered schema.
- Register two new tables in `src/schema/registry.py` per CLAUDE.md schema rules (NO `CREATE TABLE` outside registry).
- See §3.10 for column specs (notifications_sent has `id INTEGER PK` + indexed; notifications_dedup has `id INTEGER PK` + UNIQUE `(event_type, dedup_key)` per reviewer item-MINOR).
- Tests in `tests/test_schema.py` extension: assert both tables registered; column types match spec.

**T15 — Group E.B — Notifications observability + dedup persistence + health widget**
- Depends on T3, T11.5, T14.
- `src/notifications/platform_events.py`: refactor `_DEDUP_CACHE` to use `notifications_dedup` table. Restart-safe.
- Wire `safe_send` (T3) and email notifier (T11.5) to write to `notifications_sent` after every dispatch.
- C12: add `force_send=True` kwarg to bypass silent-on-pass for `notify_validation_summary`. Heartbeat sentinel writes to `notifications_sent` with `status='heartbeat'` every N hours.
- New endpoint `src/api/cloud_routes/notifications.py:/api/notifications/health` (NEW) — last 24h success/fail rate, dedup hits, oldest unack alert.
- New `frontend/src/components/dashboard/NotificationsHealthPanel.jsx` (NEW; Glob-verified does NOT exist) — bottom-of-page widget reads `/api/notifications/health`.
- New `frontend/src/api.js:getNotificationsHealth` (with arrow-form queryFn — pre-meets T16 ESLint rule).
- T15c also appends a paragraph to `docs/operator-guide.md` warning operator about expected one-shot duplicate alerts on first NSSM restart post-merge (per reviewer item #13).
- Per-deliverable commit-and-push: T15a (schema + dedup migration), T15b (write hooks + endpoint), T15c (frontend widget + tests).
- Depends on T3 (safe_send write hook), T14 (email write hook).
- **Visual-verify rule**: NotificationsHealthPanel rendered in browser before push.

**T16 — Cockpit-#7 — Bare queryFn 2 sites + ESLint rule extension**
- `frontend/src/pages/StrategyResearch.jsx:41`: wrap `queryFn: getPlatformStrategies` → `queryFn: () => getPlatformStrategies()`.
- `frontend/src/components/PlatformStatusWidget.jsx:13`: same.
- `frontend/eslint-rules/no-bare-queryfn-with-args.js:60`: extend rule. Currently checks `prop.value.type === 'MemberExpression'`. Extend to flag any `prop.value` where `type !== 'ArrowFunctionExpression' && type !== 'FunctionExpression'`. Catches Identifier (named imports), CallExpression (.bind), other non-function shapes.
- Sibling-search rule: GREP frontend `src/` for `queryFn: \w+` (Identifier shape); expect zero new sites.
- Run `npm --prefix frontend run lint:queryfn` — must exit 0 post-fix.
- Existing test `tests/test_eslint_queryfn_guardrail.py` continues to pass (no Sprint 3 regression).

**T17 — Cockpit-#3 — Calmar 4 sites migrate (allowlist becomes empty)**
- `src/evaluation/cto_report.py:738`: `(mean_r * 150) / max_dd_pct` → `calmar_ratio(mean_r * 150, max_dd_pct)`.
- `src/simulation/engine.py:439`: `annualized_return / max_dd` → `calmar_ratio(annualized_return, max_dd)`.
- `src/evaluation/backtester.py:343`: `round(ann_return / abs(max_dd_pct), 2)` → `round(calmar_ratio(ann_return, abs(max_dd_pct)), 2)`.
- `src/platform/metrics.py:75` (`compute_calmar`): replace body with `calmar_ratio(total_return, max_drawdown)`. **Verify no consumer depends on `inf` sentinel** — GREP across **ALL `src/`** (not just direct compute_calmar callers) using EXPANDED pattern: `(== inf|== math\.inf|== float\(['\"]inf['\"]\)|isinf\(|isfinite\(.*not|sys\.float_info\.max|Infinity)`. If any match found, route via local wrapper that maps `0.0` → caller-expected sentinel.
- `tests/test_calmar_canonical_only.py`: remove all 4 allowlist entries; allowlist becomes empty. Retain `test_no_new_calmar_formulas` + `test_no_calmar_named_functions`.
- Per-deliverable commit-and-push: T17a (cto_report + engine), T17b (backtester + platform/metrics + allowlist empty).

**T18 — Cockpit-#4 — stop_loss sign formatting at 5 frontend sites (REFRAMED)**
- `frontend/src/pages/LiveLedger.jsx:40` (`PnlValue`): replace `${Math.abs(value).toFixed(2)}` + conditional `+` prefix with native sign-preserving format.
- `frontend/src/pages/ShadowLedger.jsx:64` (`PnlValue`): same.
- `frontend/src/pages/ShadowLedger.jsx:568` (open-cols inline): same.
- `frontend/src/pages/ShadowLedger.jsx:592` (closed-cols inline): same.
- `frontend/src/pages/TradeHistory.jsx:31-36` (`formatDollars` — verify): same.
- Sibling-search rule: GREP `frontend/src/` for `Math\.abs.*toFixed` AND `pnl|profit|loss|dollar` proximity; expect zero new sites.
- New tests: render fixture with `pnl=-150.50`; assert DOM text contains `-$150.50` (NOT `+$150.50`).
- **Visual-verify rule**: render LiveLedger + ShadowLedger + TradeHistory in browser; confirm losing trades show negative.
- Per-deliverable commit-and-push: T18a (LiveLedger + tests), T18b (ShadowLedger 3 sites + tests), T18c (TradeHistory + tests).

**T19 — Cockpit-#5 + #6 — T16 reconciliation test extensions**
- EXTEND existing `tests/conftest.py` (Glob-verified: ALREADY EXISTS — adds yfinance mock + `init_test_db()` helper) with new postgres fixture. Use `@pytest.fixture(scope='function')` (NOT session — per reviewer item #12, isolate state per test). Use `pytest.mark.skipif(not os.environ.get('DATABASE_URL'), reason=...)` decorator (NOT `pytest.skip()` inside fixture) — keeps pass-counts CONSISTENT across local (with DATABASE_URL set) and CI (without). Operator should ideally `unset DATABASE_URL` before running test count assertions at sprint closeout, OR T23 strict `>=` accommodates either.
- Parametrize `tests/test_dashboard_reconciliation.py` to run against both SQLite (existing) and Postgres (new) fixtures.
- Add `test_kpis_meta_envelope_reconciliation` per cockpit-#6: assert `_meta.rf_adjusted_excess_sharpe.cohort == 'kpi.canonical'`, `_meta.win_rate.cohort == 'kpi.canonical'`, `_meta.total_pnl_dollars.cohort == 'kpi.canonical'` (T11 lands first), `n` non-negative integers.
- KPIs needs `_fetch_closed_trades` + `_fetch_spy_returns_for_trades` + `filter_fully_instrumented` patches per deep analysis. New mock fixture `_kpis_runtime_mock`.
- Add `test_status_open_positions_cohort_aligned` per cockpit-#2: assert `core.py:147-150` SQL matches cohort label.
- Worktree env-drift caveat: postgres fixture uses test DB URL via env; CI matrix gates by `DATABASE_URL` presence.

**T20 — KPI strip + Notifications widget visual-verify (interim)**
- Mid-Wave-2 visual-verify checkpoint. Captures screenshots after T12 (P&L card) + T15 (NotificationsHealthPanel) land.
- Compares against `before/` baseline; documents diff in `docs/audits/2026-05-07-sprint-4-cockpit-followups/visual-verify/interim-w2.md`.
- Catches frontend regressions early (memory `feedback_visual_verify_ui`).

### Wave 3 — Closeout (~3 tasks, sequential)

**T21 — Group F — Coverage + operator-guide**
- `tests/notifications/test_telegram_commands.py`: extend with 17 happy-path + 17 error-path tests for the 17 command handlers (C13).
- `tests/notifications/test_telegram_send_path.py` (new): foundation send-path tests per CC5.
- `src/notifications/telegram_commands.py:574-645` `_cmd_council`: typed exceptions → categorized return strings (cost_cap_exceeded, agent_timeout, llm_unavailable, no_quorum, invalid_question) per C14.
- CC3: convert top-4 high-traffic notify_* (`notify_trade_opened`, `notify_trade_closed`, `notify_eod_report`, `notify_weekly_digest`) to typed dataclass payloads.
- `docs/operator-guide.md`: add §X.x "Notification troubleshooting" tree (I13). Cover: bot is silent, bot token rotated, email digest stopped arriving, how to verify subsystem health (use `/api/notifications/health`).
- `docs/telegram-commands.md`: document `send-test-email` CLI (I14).
- Per-deliverable commit-and-push: T21a (test extensions), T21b (typed council + dataclass payloads), T21c (operator-guide + telegram-commands docs).

**T22 — Group D — Mute / digest / routing policy (OPERATOR-DISCRETION)**
- **GATE**: PM verifies operator approval at Wave 3 dispatch. If skipped, opens follow-up `#SP5-notifications-routing-policy` and continues to T23.
- If approved:
  - New `src/notifications/policy.py` (~80 LOC): quiet_hours (start/end UTC), weekend_suppression, per-event severity → channel map.
  - New `src/notifications/router.py` (~200 LOC): declarative `event_type → {channels, severity, prefix}` table. Refactor 25+ callers (already migrated to `safe_send` in T4) to call `route_event(event_type, **kwargs)` once.
  - I5: drop redundant `is_telegram_enabled()` wrapping at all call sites; router checks once.
  - I2: add digest scheduler — events flagged `digest-eligible` buffer for N minutes, flush as single message.
  - `config/settings.example.yaml`: new keys.
  - New tests: `tests/notifications/test_router.py`, `tests/notifications/test_policy.py`.

**T23 — Sprint closeout — visual-verify gate + CHANGELOG + operator-guide + strict test count**
- `docs/audits/2026-05-07-sprint-4-cockpit-followups/visual-verify/post-merge-commitment.md`: per-finding commitment table mirroring Sprint 3 pattern at `docs/audits/2026-05-06-cockpit-coherence-sprint/visual-verify/post-merge-commitment.md`.
- Capture `after/` screenshots of 11 priority pages + new NotificationsHealthPanel + new P&L card.
- Walk each CLOSE-class row; document PASS/FAIL/N-A in `visual-verify/results.md`.
- If any CLOSE row FAILs → dispatch hot-fix agent BEFORE marking Sprint 4 complete.
- `CHANGELOG.md`: finalize sprint-base [Unreleased] block with all delivered work (groups A-F + cockpit-#1 through #11). Single shared entry; per-PR sub-bullets pre-populated by individual tasks.
- `docs/operator-guide.md`: ADD 1-paragraph note for `#SP4-settings-backend-float32-storage` WON'T FIX explanation (per §3.9).
- Run `python -m pytest tests/ -q --timeout=60`. Assert pass count `>= 4798` (without T22) or `>= 4804` (with T22) — semantic `>=` per reviewer item #7. See plan.md §"Test-floor accounting" for per-task contribution table. Operator approves any deviation; floor was 4702 from Sprint 3 closeout.
- Run `python -m pytest tests/test_repo_structure.py -v`; document new violations in `config/known_violations.json`.
- Open Sprint 5 follow-up issues for any DEFER classes:
  - `#SP5-notifications-routing-policy` if T22 skipped
  - `#SP5-notifications-CC6-prefixing` (deferred from sweep cross-cutting)
  - `#SP5-stop-loss-test-fixture-pollution` (if T18 surfaces)

---

## 5. Out of Scope / Deferred

| Item | Reason | Tracker |
|------|--------|---------|
| **Settings backend float32 storage** | WON'T FIX — analyst confirmed JSON-text storage is exact; float32 noise is Chrome a11y tree behavior (browser cast). 1-paragraph note added to operator-guide in T23. | Closed in T23 |
| **TradeHistory.jsx:114 √150 diagnostic Sharpe** | Operator-approved non-canonical UX in Sprint 3 O11. | None |
| **Group D mute/digest/routing** | Operator-discretion at W3 dispatch (T22). May slip to Sprint 5. | `#SP5-notifications-routing-policy` |
| **CC6 message prefixing** | Bundled with Group D; deferred if D skipped. | `#SP5-notifications-CC6-prefixing` |
| **Postgres CI matrix DATABASE_URL secret** | T19 adds parametrize fixture, but CI matrix configuration is operator-side. | Operator-task to wire `DATABASE_URL` secret into CI workflow |
| **CC3 dataclass migration of 26 lower-traffic notify_***  | T21 covers top-4 only; the long-tail migrations are mechanical follow-ups. | `#SP5-notifications-dataclass-payloads-tail` |

---

## 6. Migration Notes

### 6.1 Database schema changes (T14 schema + T15 write hooks)

- New tables `notifications_sent` + `notifications_dedup` registered in `src/schema/registry.py` (T14, plan-Batch-3a) per §3.10.
- Run `python -m src.main validate-schema --fix` post-merge to materialize tables locally.
- Run `python scripts/render_migrate.py` post-merge to sync Render Postgres.
- T15 migrates `_DEDUP_CACHE = {}` (process-local; currently at `src/notifications/platform_events.py:26`) to `notifications_dedup` query path. **First post-merge restart** may re-fire alerts that were in the in-memory cache pre-restart — expected, one-shot.
- **Operator-guide note** (added by T15c per reviewer item #13): T15c appends a paragraph to `docs/operator-guide.md` warning operator about expected one-shot duplicate alerts on first NSSM restart post-merge. Optional post-deploy script seeds `notifications_dedup` from `notifications_sent` rows where `sent_at > NOW() - 24h` (script optional, doc paragraph mandatory).
- **Retention**: `notifications_sent` is append-only and grows unbounded. Sprint 5 follow-up `#SP5-notifications-retention` will add a daily cleanup task. For Sprint 4, table is allowed to grow.

### 6.2 `safe_send` migration (T2-T6)

- T2 renames 4 sites in `overnight.py` (Wave 1 blocker — production currently broken).
- T3 introduces `safe_send` wrapper; existing call sites continue working unchanged.
- T4 mechanically migrates 25+ caller sites; semantics improve (NameError now propagates) but external behavior identical for happy-path.
- T5 module-level imports in `cli/commands.py` may surface ImportError at process startup that was previously deferred. Test floor enforces no new test failures.

### 6.3 KPI strip 6th card (T11+T12)

- T11 backend lands first; payload backward-compat (additive `total_pnl_dollars` field).
- T12 frontend replaces PromotionGateCard with TotalPnlDollarsCard. Vote count surfaces under TrafficLightCard tooltip — operators familiar with Sprint 3 layout will see one less card. Operator may override at dispatch (alternative: 6-card layout).

### 6.4 ESLint rule extension (T16)

- Existing rule fires on `MemberExpression` only. Extension fires on any non-function-shape value. Run `npm --prefix frontend run lint:queryfn` post-merge — must exit 0. T16 fixes the 2 known sites pre-emptively.

### 6.5 Calmar allowlist empty (T17)

- Allowlist in `tests/test_calmar_canonical_only.py` shrinks from 3-4 entries (post-Sprint 3) to 0. Retained tests `test_no_new_calmar_formulas` + `test_no_calmar_named_functions` continue protection. Optional: delete the test entirely if guardrail-only path is preferred (architect leaves both in place; future Sprint 5 may consolidate).

### 6.6 CHANGELOG per-task line pre-allocation

Per reviewer item #9: pre-writing a single shared block does NOT prevent merge conflicts unless each PR appends to a UNIQUE pre-allocated line. T1 pre-allocates **ONE LINE PER TASK in `CHANGELOG.md` `[Unreleased]` with explicit task-id markers** — `<!-- T2 -->`, `<!-- T3 -->`, `<!-- T4a -->` through `<!-- T4d -->`, `<!-- T5 -->` through `<!-- T23 -->`, plus all sub-PR markers (`<!-- T11a -->`, `<!-- T11b -->`, `<!-- T13a-c -->`, `<!-- T15a-c -->`, `<!-- T17a-b -->`, `<!-- T18a-c -->`, `<!-- T21a-c -->`). Each task PR replaces ONLY its own placeholder line; no adjacent edits permitted. T23 verifies + removes any unused placeholders (e.g., `<!-- T22 -->` if T22 skipped). **Closes the cascade-conflict hazard at 30+ parallel PRs.**

---

## 7. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **Group A T4 25-site migration introduces regression** | Medium | High | Per-deliverable commit-and-push (T4a-T4d sub-tasks). Each PR independently testable. Reviewer dispatch = QA + Performance. |
| **T9 5-endpoint `_desk_clause` blast radius breaks one consumer** | Low | High | Helper change atomic in one task. Test extension covers per-desk cohort assertion. Sibling-search rule applies. |
| **T11 backend → T12 frontend race** | Low | Medium | T12 explicit depends_on=[T11]. Pre-push stale-base hook (#59) will refuse if T12 branch is behind T11 merge. |
| **T15 schema migration on Render Postgres** | Medium | Medium | `render_migrate.py` runs post-merge; if it fails, hot-fix follow-up. Tested locally first via `validate-schema --fix`. |
| **T16 ESLint rule extension flags new false-positives** | Low | Medium | Rule fires on non-function-shape; verified against current frontend pre-merge. T16 includes corrective wraps. |
| **T19 Postgres fixture skip behavior in CI** | Medium | Low | `pytest.skip` when `DATABASE_URL` not set. SQLite path always runs. CI gates by env presence. |
| **T22 Group D operator skips at dispatch** | Medium | Low | Operator-discretion gate. Follow-up issue `#SP5-notifications-routing-policy` opens. |
| **T23 visual-verify catches regression post-merge** | Low | High | Mirror Sprint 3 pattern; T20 mid-wave checkpoint catches early. Hot-fix agent dispatch protocol documented. |
| **Cloud-req drift recurrence post-T7/T8** | Low | High | Dual-lane test runs on every PR. AST walker catches 95% at PR-time; venv subprocess catches transitive. |
| **Worktree env-drift on T8 venv test** | Medium | Low | Hermetic venv setup; doesn't carry `.env`. Fixture explicitly clears env vars. |
| **CHANGELOG cascade conflicts in W2** | Low | Low | T1 pre-writes single shared [Unreleased] entry. Per-task sub-bullet adds are isolated within group sections. |
| **T18 stop_loss fix breaks ActivityFeed parity** | Low | Medium | Sibling-search rule applies. ActivityFeed:57 explicitly NOT in scope (passes raw signed value already). |

---

## 8. Reviewer Dispatch (per CLAUDE.md table)

| Task touches… | QA | Security | Performance |
|---------------|----|----------|-------------|
| Notifications safe_send + migration (T2-T6) | ✓ | ✓ (token redaction) | — |
| Cloud-req CI guardrail (T7, T8) | ✓ | — | ✓ (slow-lane runtime) |
| API routes + cohort (T9, T10, T11) | ✓ | — | ✓ |
| Frontend KPIStrip (T12) | ✓ | — | — |
| Telegram template (T13) | ✓ | ✓ (HTML escape XSS) | — |
| Email subsystem (T14) | ✓ | ✓ (password env vs YAML) | — |
| Schema + observability (T15) | ✓ | — | ✓ (notifications_sent index) |
| ESLint rule extension (T16) | ✓ | — | — |
| Calmar canonical migration (T17) | ✓ | — | ✓ (no new perf regression) |
| Frontend stop_loss formatting (T18) | ✓ | — | — |
| Reconciliation test (T19) | ✓ | — | — |
| Coverage + operator-guide (T21) | ✓ | — | — |
| Group D router/policy (T22) | ✓ | — | — |
| Sprint closeout (T23) | — | — | — |

---

## 9. Visual-verify gate (mirror Sprint 3)

**Pre-sprint** (T1): Capture `before/` screenshots of 11 priority pages via Chrome DevTools MCP.

**Mid-Wave-2** (T20): Capture interim screenshots after T12 + T15 land. Diff against baseline. Catches frontend regressions early.

**Post-integration-merge** (T23):
1. Wait for Render redeploy (~5-10 min).
2. Re-capture 11 priority pages → `visual-verify/after/`.
3. Walk each CLOSE-class row in `post-merge-commitment.md`; confirm "Expected" matches reality.
4. Document PASS/FAIL/N-A per row in `visual-verify/results.md`.
5. If any CLOSE row FAILs → dispatch hot-fix agent BEFORE marking Sprint 4 complete.

**Verification mandate from memory `feedback_visual_verify_ui`**: frontend Dashboard / KPIStrip / Layout / NotificationsHealthPanel edits MUST be browser-rendered before push. Static checks insufficient.

---

## Design Decisions

| Decision | Rationale | Trade-off (alternatives considered) |
|----------|-----------|--------------------------------------|
| Cohort taxonomy unchanged — Sprint 4 adds NO new cohort labels. Area 1 (#SP4-shadow-metrics-live-cohort) uses existing 'trades.live_only'. | src/api/cohort_meta.py:22 defines a closed taxonomy of 8 cohort_ids. Sprint 3 T8/T9 closed the additive _meta envelope contract. test_invalid_cohort_id_rejected enforces KeyError on unknown cohorts. Adding new cohorts requires updating cohort_meta.py + downstream consumers; the live-only fix doesn't need a new label since 'trades.live_only' already exists. | Add 'trades.live_only.live' sub-cohort (rejected: unnecessary nesting; existing label conveys semantics); Add cohort 'trades.live_only.from_source' (rejected: redundant with the SQL filter rationale) |
| _desk_clause helper extension at src/api/cloud_routes/trades.py:42 (NOT analytics.py per drift alert), 5-endpoint blast radius accepted in one task. | Deep analyst confirmed helper lives at trades.py:42-57, NOT analytics.py as the brief implied. Helper is shared by 5 endpoints (shadow_open, shadow_closed, sharpe_attribution, shadow_metrics, shadow_account). Extending signature from (frag, params) → (frag, params, cohort_id) requires updating all 5 callers' tuple unpacking. Keeping the change atomic in one task avoids per-PR coordination overhead and preserves helper-shape invariant. | Add new helper _desk_clause_with_cohort and migrate one caller per task (rejected: 5x dispatch overhead, mid-state where 2 helpers coexist); Bake cohort_id into per-caller logic, keep helper unchanged (rejected: drift between cohort label and SQL filter is exactly the bug we're fixing) |
| Close #SP4-settings-backend-float32-storage as WON'T FIX with operator-guide paragraph. | Deep analyst confirmed: (1) registry.py:1568 stores setting_value as TEXT, (2) apply_override calls json.dumps(value) preserving IEEE-754 double, (3) NO numpy.float32, .astype, or float32 cast anywhere in Python write path. The float32 noise (aria-valuenow='0.004999999888241291') is Chrome a11y tree behavior — browser casts JS Number to float32 for screen-reader output. NO Python-side fix possible because storage is already exact. Operator-confirmed. | Add backend toFixed-style precision clamp before write (rejected: storage already exact; clamp would round-trip lossy data through Python float64 unnecessarily); Switch to NUMERIC SQLite column type with precision (rejected: SQLite NUMERIC is the same as REAL = double; no improvement); Set explicit aria-valuenow attribute in frontend HTML (rejected: HTML attributes get re-cast through Chrome a11y tree regardless; doesn't fix root cause) |
| 8a/8b parallel-safe split — backend total_pnl_dollars emit (T11) lands first; frontend KPIStrip card (T12) depends on T11. | Operator-confirmed parallel-safe. Backend payload is additive (existing consumers ignore new field). Frontend depends on backend field being live in production for visual-verify. T11 also bundles Group B email subsystem hardening — different files, no overlap, parallel-safe within T11 batch. | Bundle 8a + 8b in one task (rejected: max 4 files_in_scope honored per CLAUDE.md; backend + frontend split keeps each PR scoped); Frontend lands first with mock total_pnl_dollars (rejected: visual-verify wouldn't reflect production) |
| KPIStrip 6th card replaces PromotionGateCard (architect recommendation) — vote count surfaces under TrafficLightCard tooltip. Operator may override at Wave 2 dispatch. | Per analyst hint: vote count duplicates Stage Traffic Light gate context. Replacing PromotionGateCard with TotalPnlDollarsCard keeps KPIStrip at 5 cards (no grid-template-columns change), preserves visual rhythm, and surfaces vote count where it belongs contextually (under TL gate). Operator may override at dispatch for 6th-card alternative (grid: repeat(6,1fr)). | Add 6th card, keep PromotionGateCard (rejected: grid layout requires breakpoint-aware redesign; vote count is contextually subordinate to TL); Move vote count to a separate sub-section below KPIStrip (rejected: visual hierarchy weakens; tooltip-as-disclosure is canonical) |
| stop_loss task reframed — fix dollar P&L sign formatting at 5 frontend sites (NOT stop_loss-specific). | Drift alert from analyst: bug pattern Math.abs(pnl).toFixed(2) with conditional + prefix only for positive — strips negative sign for ALL losing trades, not just stop_loss exits. Affected sites span LiveLedger, ShadowLedger (3 places), TradeHistory. Reframing T18 captures the actual scope. ActivityFeed.jsx:57 already passes raw signed value — explicitly NOT in scope. | Limit fix to stop_loss exit_reason check in display layer (rejected: bug isn't stop_loss-specific; same render path produces wrong sign for all losses); Fix backend signed value (rejected: Sprint 3 T4 verified backend is correct; bug is display-layer) |
| ESLint rule extension bundled with Area 7 fix in same PR. | Drift alert: bare queryFn at 2 sites is Identifier (named import: queryFn: getPlatformStrategies), NOT MemberExpression. Sprint 3 rule at frontend/eslint-rules/no-bare-queryfn-with-args.js:60 only checks MemberExpression — silently passes for Identifier. Without rule extension, future regressions can recur. Bundling rule extension + call-site fix in one PR ensures lint passes for the new state and protects against regression. | Fix call-sites only, defer rule extension to Sprint 5 (rejected: rule deficiency is the regression vector; fixing without rule extension leaves the door open); Extend rule first, fix call-sites in next PR (rejected: rule extension would fail lint without call-sites being wrapped first; one-PR atomic is simpler) |
| Cloud-req CI guardrail in Wave 1 (operator-confirmed) with dual-lane: AST walker (fast) + venv subprocess (slow CI). | 4th recurrence of cloud-deploy import drift (jsonschema, numpy, requests, scipy). #1007 Sprint 3 hot-fix. Fast lane (AST walker) catches 95% of cases at PR-time without venv overhead. Slow lane catches transitive imports the AST walker misses. Both run in CI; fast on every PR, slow gated by --run-slow flag locally and env in CI. | Slow lane only (rejected: minute-scale runtime per PR is friction); Fast lane only (rejected: misses transitive package detection — exact bug class that recurred); Defer to Sprint 5 (rejected: structural blind spot; operator confirmed Wave 1 priority) |
| Notification subsystem 6-group split (Groups A-F per audit recommendations.md). Group A is Wave 1 blocker. Group D operator-discretion may slip to Sprint 5. | Audit recommendations cluster 50 findings into 6 functional groups by file boundaries and effort. Group A NameError + safe_send is the critical-path blocker — production CUSUM/leakage/regression alerts are silently broken. Group D mute/digest/routing is the largest cluster (~3-5 days, multiple files) and is IMPORTANT (not CRITICAL). Per memory feedback_fix_before_trade, IMPORTANT-class can be fix-later if scope is tight; operator-discretion at W3 dispatch. | All 6 groups in Sprint 4 (rejected: 50-finding cluster is too large for one sprint after combining with 10 cockpit followups; Sprint 4 already at ~40-50 tasks); Defer Group A to Sprint 5 (rejected: production alerts silently broken — fix-now per memory feedback_fix_before_trade) |
| Wave structure — Wave 1 (~7 tasks) blocker, Wave 2 (~12 tasks) parallel medium-effort, Wave 3 (~3 tasks) closeout. | Wave 1 must serialize because Group A T2 (rename) → T3 (safe_send build) → T4 (migration) is a dependency chain. Cloud-req guardrail T7/T8 parallels with Group A (different files). Wave 2 is mostly parallel-safe medium-effort blocks with no file overlap. Wave 3 closes coverage + operator-guide + visual-verify gate. | Single sequential wave (rejected: 23 tasks at scale require parallel batching to fit timeline); More waves with finer-grained gates (rejected: visual-verify checkpoint at T20 already provides mid-wave checkpoint; more gates add coordination overhead) |
| Single shared CHANGELOG [Unreleased] entry pre-written at sprint base (T1); per-task sub-bullets; T23 finalizes. | Memory feedback_strict_rigor_no_handwave applies. With ~23 tasks across 9 batches, 12+ parallel Wave 2 PRs would each touch CHANGELOG.md and produce cascade conflicts. T1 pre-writes single shared block with all sub-headings; each task PR adds its sub-bullet to its section; T23 finalizes. Avoids merge-conflict death spiral. | Per-PR CHANGELOG entry (rejected: cascade conflicts at 12-parallel-PR scale); Defer all CHANGELOG to T23 (rejected: T23 must consolidate from per-task notes; pre-written placeholders make consolidation mechanical) |
| Visual-verify gate at integration with mid-Wave-2 interim checkpoint (T20). | Memory feedback_visual_verify_ui — frontend Dashboard/KPIStrip/Layout/NotificationsHealthPanel edits must be browser-rendered before push. Mirror Sprint 3 pattern. T20 mid-W2 checkpoint catches frontend regressions early (after T12 KPIStrip + T15 NotificationsHealthPanel + T18 sign formatting all land). T23 final post-merge gate before sprint complete. | Final gate only at T23 (rejected: regressions at sprint end require hot-fix dispatch and add timeline); Per-task visual-verify (rejected: 23x dispatch overhead; visual-verify is most useful when multiple frontend changes compose) |
| All 4 Calmar sites migrate in T17; allowlist becomes empty post-merge. | Operator-confirmed full scope. Deep analysis verified all 4 sites are compatible with canonical calmar_ratio() signature. platform/metrics.py:75 compute_calmar has divergence (returns inf vs canonical 0.0) — T17 verifies no consumer depends on inf sentinel via GREP for `== inf` or `> 1e10`. Allowlist empty after T17; protective tests test_no_new_calmar_formulas + test_no_calmar_named_functions retained for ongoing protection. | Migrate 3 sites, leave platform/metrics due to inf-sentinel risk (rejected: operator confirmed full scope; GREP verification mitigates); Add wrapper that maps 0.0 → inf for backward compat (rejected: hides bug — 0.0 is the correct value when max_dd=0; wrapper prolongs the inconsistency) |
| Notifications schema (notifications_sent + notifications_dedup) registered in src/schema/registry.py per CLAUDE.md schema rules. | CLAUDE.md mandates: NEVER write CREATE TABLE outside src/schema/registry.py. New tables go through TableDef + run validate-schema --fix. notifications_sent enables observability; notifications_dedup migrates _DEDUP_CACHE from process-local to restart-safe (memory: NSSM restarts the watch loop regularly per reference_watch_loop_management). | JSON file persistence for dedup (rejected: file-locking complexity vs SQLite ACID; NOT idiomatic for the codebase); Process-local + Redis (rejected: Redis not in stack; SQLite is canonical persistence) |
| Worktree isolation mandatory for all parallel agent dispatches per CLAUDE.md. | Memory feedback_strict_rigor_no_handwave applies. PR #690 N3 incident (two agents in Wave 2 overwrote each other's tree during index race). Sprint 0 Waves 4+5 stash-pop class (4 of 5 agents in each wave hit failures). Worktree isolation is the documented fix. Worktree env-drift caveat (PR #711→#729): hermetic test fixtures avoid .env reliance — applied to T8 (venv test) and T19 (postgres fixture). | Single working tree with serialization (rejected: defeats parallel batching benefit); Branch-based isolation without worktrees (rejected: index-race vector remains) |
