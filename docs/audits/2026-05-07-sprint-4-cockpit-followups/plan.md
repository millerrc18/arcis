# Sprint 4 — Cockpit Followups + Notification Subsystem — Implementation Plan

**Generated**: 2026-05-07 (revised after reviewer pass 1)
**Spec**: `spec.md` (canonical)
**Source artifacts**:
- `docs/audits/2026-05-06-cockpit-coherence-sprint/sp4-followups.md` (11 issues)
- `docs/audits/2026-05-07-telegram-email-sweep/{summary.md,cross-cutting.md,recommendations.md}` (50 findings, 6-group split)
**Sprint base branch**: `sprint/cockpit-followups-2026-05-07/base`
**Test floor target**: 4702 → 4742+ (`>=` enforced at sprint-closeout task — see Test-floor accounting below)
**Integration target**: visual-verify gate at integration mirroring Sprint 3 pattern
**Consumable by**: `arcis:code` PM orchestrator

---

## Wave ↔ Batch cross-reference

The spec narrates **4 logical Waves (W0/W1/W2/W3)**. The PM orchestrator dispatches **9 numbered Batches (Batch 0 → Batch 8)**. Both labels appear throughout this plan; this table is the single source of truth.

| Logical Wave (spec) | Plan Batches | Tasks | Theme |
|---|---|---|---|
| **W0** Sprint base | Batch 0 | T1 | Branch + CHANGELOG pre-allocation + before/ screenshots |
| **W1** Blocker | Batch 1 + Batch 2 + Batch 3a | T2, T7 → T3, T8 → T4, T5, T6, T14 | Group A NameError + safe_send + Group A migration + cloud-req CI guardrail + schema registration |
| **W2** Parallel medium-effort | Batch 3b + Batch 4 + Batch 5 + Batch 6 | T9, T10, T11, T13, T16, T17, T18 → T12, T15, T19 → T20 | Backend cohort + Group B email + Group C telegram template + Group E observability + ESLint + Calmar + frontend signs + reconciliation + visual-verify checkpoint |
| **W3** Closeout | Batch 7a + Batch 7b + Batch 8 | T21 → T22 (operator-confirm) → T23 | Coverage + operator-guide + Group D operator-discretion + sprint closeout |

The PM dispatches strictly in **Batch order** (0 → 1 → 2 → 3a → 3b → 4 → 5 → 6 → 7a → 7b → 8). Tasks within a batch are parallel-safe; batches run sequentially.

## Execution order

```
Batch 0:  [1]                                     (W0)
Batch 1:  [2, 7]                                  (W1 starts — Group A rename + cloud-req fast-lane)
Batch 2:  [3, 8]                                  (W1 — safe_send build + cloud-req slow-lane)
Batch 3a: [4, 5, 6, 14]                           (W1 ends — Group A migration + I10 + I12+CC2 + schema registration)
Batch 3b: [9, 10, 11, 13, 16, 17, 18]             (W2 starts — backend cohort + KPIs + telegram template + ESLint + Calmar + frontend signs)
Batch 4:  [12, 15, 19]                            (W2 — frontend KPIStrip + observability widget + reconciliation extensions)
Batch 5:  [20]                                    (W2 — mid-W2 visual-verify checkpoint)
Batch 6:  (reserved — empty post-revision; see notes)
Batch 7a: [21]                                    (W3 — coverage + operator-guide)
Batch 7b: [22]                                    (W3 — Group D operator-discretion gate; PM asks operator)
Batch 8:  [23]                                    (W3 — sprint closeout)
```

> **Rationale for splitting plan-Batch-7 into 7a + 7b**: T22 is operator-discretion at dispatch (spec §3.11). Splitting lets the PM dispatch T21 immediately and pause for operator confirmation before T22. If operator declines, T22 is skipped and `#SP5-notifications-routing-policy` opens. T23's `depends_on` includes T21 (mandatory) and T22 (only if dispatched).

## Plan notes

- **9-batch execution graph** (renamed from prior "9 waves"). Tasks within a batch are parallel-safe; batches run sequentially.
- **Worktree isolation MANDATORY** for all parallel batches per CLAUDE.md.
- **Reviewer dispatch**:
  - T2-T6 Group A → QA + Security (token redaction).
  - T7-T8 cloud-req → QA + Performance.
  - T9-T10 API routes → QA + Performance.
  - T11-T12 KPI strip → QA.
  - T13 Group C → QA + Security (HTML XSS).
  - T14-T15 Group E → QA + Performance (notifications_sent index).
  - T16 ESLint → QA.
  - T17 Calmar → QA + Performance (no perf regression).
  - T18 frontend signs → QA.
  - T19 reconciliation → QA.
  - T20 visual-verify checkpoint → no reviewer dispatch (reporting only).
  - T21 Group F coverage → QA.
  - T22 Group D operator-discretion → QA (if executed).
  - T23 closeout → no reviewer.
- **Visual-verify rule**: T12 (KPIStrip), T15 (NotificationsHealthPanel), T18 (LiveLedger/ShadowLedger/TradeHistory), T20 (mid-W2 checkpoint), T23 (closeout gate).
- **Sibling-search rule**: T2 (overnight.py + scripts/ + tests/), T4 (16 caller files), T9 (5-endpoint blast radius), T10 (core.py SQL filter), T16 (frontend GREP), T17 (Calmar GREP — extended pattern), T18 (Math.abs+toFixed GREP).
- **Per-deliverable commit-and-push**: T4 (4 sub-PRs), T11 (2 sub-PRs after split), T13 (3 sub-PRs), T15 (3 sub-PRs), T17 (2 sub-PRs), T18 (3 sub-PRs), T21 (3 sub-PRs).
- **CHANGELOG one-line-per-task pre-allocation** by T1; per-PR replaces only its placeholder line; T23 finalizes.
- Cohort taxonomy unchanged (8 cohort_ids).
- Calmar allowlist becomes empty post-T17.
- `#SP4-settings-backend-float32-storage` WON'T FIX (T23 operator-guide note).
- Notification dedup migration NSSM restart re-fire warning added to operator-guide (T15c or T23 — see T15c spec).
- Group D (T22) operator-discretion at W3 dispatch — PM asks operator before dispatching Batch 7b. If declined, opens follow-up `#SP5-notifications-routing-policy`.
- Test floor `>=` 4742 in T23 — operator must approve any deviation. Per-task contributions documented in **Test-floor accounting** §.

## 11 priority pages (from Sprint 3 visual-verify)

T1 captures `before/`, T20 captures `interim-w2/`, T23 captures `after/` — for the canonical 11 pages enumerated by Sprint 3 at `docs/audits/2026-05-06-cockpit-coherence-sprint/visual-verify/before/`:

1. `01-dashboard.png`
2. `03-shadow-ledger.png`
3. `05-trade-history.png`
4. `06-strategy.png`
5. `09-cto-report.png`
6. `10-attribution.png`
7. `11-model-perf.png`
8. `15-stress-test.png`
9. `21-monitoring.png`
10. `23-settings.png`
11. `24-roadmap.png`

Plus 2 net-new components in T20 + T23:

12. `25-kpi-pnl-card.png` (NEW — from T12)
13. `26-notifications-health-panel.png` (NEW — from T15)

For NEW components there is no `before/` baseline. Acceptance criteria are defined in T1 description and re-asserted in T20 / T23.

## Test-floor accounting

Target: `>= 4742` at T23 sprint closeout (operator may override). Per-task contributions:

| Task | Net new tests | Cumulative target |
|---|---|---|
| T2 | +4 (4 alarm sites — overnight `test_overnight_alarm_paths.py`) | 4706 |
| T3 | +6 (`test_safe_send.py`: ImportError, NameError, network-only catch, counter, is_telegram_enabled short-circuit, success path) | 4712 |
| T4 | 0 (mechanical migration; no new tests; existing scheduler tests cover happy-path) | 4712 |
| T5 | +2 (`tests/cli/test_commands_imports.py`: AST walk + module-import succeeds) | 4714 |
| T6 | +2 (`test_check_action_reminders_isolation.py`: per-check failure isolation + `_get_telegram_config` shared) | 4716 |
| T7 | +4 (`test_cloud_requirements_imports.py` AST: clean state + synthetic missing-pkg + transitive walk + stdlib-accept) | 4720 |
| T8 | +2 (`@pytest.mark.slow`: temp venv import + synthetic missing scipy regression) | 4722 |
| T9 | +5 (per-desk cohort: live, swing, all + sharpe_attribution tuple-unpack + shadow_open/closed/account smoke) | 4727 |
| T10 | +2 (`test_status_open_positions_cohort_aligned` + regression-lock without source filter) | 4729 |
| T11 | +6 (`test_kpis.py`: total_pnl_dollars present + correct sum + meta cohort/label/n + email mocks: cc_addresses=None + EMAIL_PASSWORD env required + telegram-fallback) | 4735 |
| T12 | +2 (KPIStrip.test.jsx: P&L card renders + vote in TL tooltip) | 4737 |
| T13 | +6 (chunked send 5000-char + html_escape & < > + dict-with-success + ValueError-on-unknown-urgency + premarket escape + finnhub time normalize) | 4743 |
| T14 | +2 (test_schema.py: notifications_sent registered + notifications_dedup registered) | 4745 |
| T15 | +5 (dedup persistence restart-safe + 2 write-hooks + /api/notifications/health endpoint + frontend NotificationsHealthPanel render) | 4750 |
| T16 | +4 (rule fires Identifier + does-not-fire arrow + does-not-fire function + fires CallExpression .bind) | 4754 |
| T17 | 0 (`_ALLOWLIST` is a static set, not parametrize — emptying it does NOT remove tests; protective tests `test_no_new_calmar_formulas` + `test_no_calmar_named_functions` retained, both already exist) | 4754 |
| T18 | +6 (LiveLedger neg + pos + zero; ShadowLedger 3 sites; TradeHistory; ActivityFeed regression-lock) | 4760 |
| T19 | +3 (kpis _meta envelope reconciliation + status open_positions cohort aligned + postgres-skip-when-no-DATABASE_URL) | 4763 |
| T20 | 0 (visual-verify reporting only) | 4763 |
| T21 | +35 (17 happy + 17 error path + 1 send_path foundation) | 4798 |
| T22 | +6 if dispatched (router + policy + quiet hours + weekend + digest scheduler + is_telegram_enabled drop) | 4804 (if T22) / 4798 (if not) |
| T23 | 0 (closeout reporting) | 4798 / 4804 |

**Computed test-floor target after sprint**: `>= 4798` (without T22) or `>= 4804` (with T22).

> **Reviewer flagged the spec target as "4742+" — this revision uses `>=` semantics throughout and computes 4798/4804 as the realistic post-sprint floor.** Spec §1 is updated to match. T23's strict-equality assertion is replaced with `>=`. If T22 is skipped at dispatch, T23 asserts `>= 4798`. Otherwise `>= 4804`. Operator must approve at T23 if delivered count differs.

> **Postgres fixture caveat**: T19 introduces `tests/conftest.py` postgres fixture using `pytest.mark.skipif(not DATABASE_URL, reason="...")` — keeps pass-counts CONSISTENT across local (with DATABASE_URL set) and CI (without). Operator should `unset DATABASE_URL` before running test count assertions at sprint closeout, OR T23 strict `>=` accommodates either.

---

## Tasks

### Task 1 — Sprint base setup + per-task CHANGELOG line pre-allocation + visual-verify before/

- **Wave**: W0 (Batch 0)
- **Depends on**: none (root)
- **Complexity**: low
- **Files in scope**:
  - `CHANGELOG.md`
  - `docs/audits/2026-05-07-sprint-4-cockpit-followups/visual-verify/before/README.md` (NEW)
- **Files read-only**:
  - `docs/audits/2026-05-06-cockpit-coherence-sprint/spec.md`
  - `docs/audits/2026-05-06-cockpit-coherence-sprint/visual-verify/post-merge-commitment.md`
  - `docs/audits/2026-05-06-cockpit-coherence-sprint/visual-verify/before/` (11 reference screenshots)

**Description:**

Create branch `sprint/cockpit-followups-2026-05-07/base` off main. **Pre-allocate ONE LINE PER TASK in CHANGELOG.md `[Unreleased]`** with explicit task-id markers — each task PR replaces ONLY its placeholder line; no adjacent edits permitted. Allocate placeholders for ALL tasks and sub-PRs:

```
<!-- T2  --> *placeholder Group-A.1 send_telegram rename*
<!-- T3  --> *placeholder Group-A.2 safe_send wrapper*
<!-- T4a --> *placeholder Group-A.3 scheduler migration*
<!-- T4b --> *placeholder Group-A.3 services migration*
<!-- T4c --> *placeholder Group-A.3 training+risk migration*
<!-- T4d --> *placeholder Group-A.3 misc migration*
<!-- T5  --> *placeholder Group-A.4 cli lazy imports*
<!-- T6  --> *placeholder Group-A.5 per-check except + _get_telegram_config consolidation*
<!-- T7  --> *placeholder cloud-req fast-lane AST*
<!-- T8  --> *placeholder cloud-req slow-lane venv*
<!-- T9  --> *placeholder cockpit-#1 shadow_metrics live cohort*
<!-- T10 --> *placeholder cockpit-#2 /api/status open_positions cohort*
<!-- T11a --> *placeholder cockpit-#8a backend total_pnl_dollars*
<!-- T11b --> *placeholder Group-B email subsystem hardening*
<!-- T12 --> *placeholder cockpit-#8b KPIStrip P&L card*
<!-- T13a --> *placeholder Group-C chunked send + html_escape*
<!-- T13b --> *placeholder Group-C notify_* updates*
<!-- T13c --> *placeholder Group-C finnhub I15 + I11 urgency*
<!-- T14 --> *placeholder Group-E.A schema registration*
<!-- T15a --> *placeholder Group-E.B dedup migration*
<!-- T15b --> *placeholder Group-E.B write hooks + /api/notifications/health*
<!-- T15c --> *placeholder Group-E.B NotificationsHealthPanel + operator-guide NSSM warning*
<!-- T16 --> *placeholder cockpit-#7 bare queryFn + ESLint extension*
<!-- T17a --> *placeholder cockpit-#3 calmar cto_report+engine*
<!-- T17b --> *placeholder cockpit-#3 calmar backtester+platform/metrics+allowlist empty*
<!-- T18a --> *placeholder cockpit-#4 LiveLedger sign*
<!-- T18b --> *placeholder cockpit-#4 ShadowLedger 3 sites*
<!-- T18c --> *placeholder cockpit-#4 TradeHistory sign*
<!-- T19 --> *placeholder cockpit-#5+#6 reconciliation extensions*
<!-- T20 --> *placeholder mid-W2 visual-verify checkpoint*
<!-- T21a --> *placeholder Group-F coverage extensions*
<!-- T21b --> *placeholder Group-F typed council + dataclass payloads*
<!-- T21c --> *placeholder Group-F operator-guide + telegram-commands docs*
<!-- T22  --> *placeholder Group-D router/policy/digest (if dispatched)*
<!-- T23 --> *placeholder sprint closeout — visual-verify gate + WON'T-FIX note + test count*
```

Create `docs/audits/2026-05-07-sprint-4-cockpit-followups/visual-verify/{before,after}/` directory skeleton. Capture `before/` Chrome DevTools MCP screenshots of **the 11 priority pages enumerated in plan-§ "11 priority pages"** mirroring Sprint 3 pattern. NO functional code changes.

**Acceptance criteria for NEW components (T12 P&L card + T15 NotificationsHealthPanel) — to be re-asserted at T20 and T23:**

- **P&L card** (`25-kpi-pnl-card.png`): renders with `$X,XXX.XX` format, meta badge visible, no console errors, value matches `/api/kpis._meta.total_pnl_dollars.value`.
- **NotificationsHealthPanel** (`26-notifications-health-panel.png`): shows `success_rate / fail_count / dedup_hits / oldest_unack_alert` fields (all numeric); no `--` placeholders without sentinel reason; meta badge cohort = `notifications.health` (or whatever cohort_id is selected during T15b implementation).

**Scope fence:**

Do NOT touch any source code, tests, or non-CHANGELOG/docs files. Do NOT begin implementation work — this is sprint-base setup only. Each placeholder line MUST have a unique task-id marker so per-task PRs replace exactly one line.

**Test strategy:**

No unit tests — sprint-base setup. Manual verification: branch exists on origin; CHANGELOG.md has `[Unreleased]` block with all 33 placeholder lines (one per task/sub-PR); `before/` directory contains 11 screenshots matching enumerated pages.

---

### Task 2 — Group A.1 — Rename send_telegram_message at 4 overnight.py sites

- **Wave**: W1 (Batch 1)
- **Depends on**: [1]
- **Complexity**: low
- **Files in scope**:
  - `src/scheduler/overnight.py`
  - `tests/notifications/test_overnight_alarm_paths.py` (NEW)
- **Files read-only**:
  - `src/notifications/telegram.py`

**Description:**

WAVE 1 BLOCKER. CUSUM/leakage/regression alerts are silently broken in production right now. Rename `send_telegram_message` → `send_telegram` at `src/scheduler/overnight.py:134, 149, 304, 311`. New regression test `tests/notifications/test_overnight_alarm_paths.py` (NEW file) asserts each of the 4 alarm sites successfully invokes the real `send_telegram` (mock the underlying transport).

**SIBLING-SEARCH RULE (expanded scope per reviewer):** GREP `src/ scripts/ tests/` for `send_telegram_message`:
- **Pre-fix expectation**: ONLY 4 matches at `src/scheduler/overnight.py:134, 149, 304, 311`.
- **Post-fix expectation**: 0 matches across all paths.
- If pre-fix GREP shows >4 matches anywhere, **treat as drift alert and surface to PM before proceeding** (do NOT auto-fix the unexpected sites without explicit confirmation — they may be in scope for a different task).

Verify `tests/notifications/` directory exists pre-T2 (Glob-verified by architect: present, contains `__init__.py` + 2 existing test files).

**Scope fence:**

Do NOT add safe_send wrapper here (Task 3). Do NOT migrate other caller sites (Task 4). Do NOT modify `src/notifications/telegram.py` beyond imports. CHANGELOG.md: replace ONLY the `<!-- T2 -->` placeholder line — no other CHANGELOG edits.

**Test strategy:**

1) `test_overnight_alarm_paths.py` (4 tests): 4 alarm sites (CUSUM, leakage, model-regression critical, model-regression warning) successfully invoke `send_telegram` with proper message string. 2) Mock `src.notifications.telegram.send_telegram`; assert called once per site with expected substrings. 3) Sibling-search assertion: assert no remaining `send_telegram_message` references in `src/`, `scripts/`, or `tests/`. **Net new tests: +4**.

**Sibling-search reminder:** when fixing a bug or anti-pattern at a specific file:line, GREP the file (and adjacent files) for the same anti-pattern at other lines before declaring the fix complete (CLAUDE.md `feedback_review_sibling_search` memory).

---

### Task 3 — Group A.2 — Build notifications.safe_send central wrapper

- **Wave**: W1 (Batch 2)
- **Depends on**: [2]
- **Complexity**: medium
- **Files in scope**:
  - `src/notifications/telegram.py`
  - `src/notifications/__init__.py` (currently empty — will gain re-exports)
  - `tests/notifications/test_safe_send.py` (NEW)
- **Files read-only**:
  - `src/scheduler/overnight.py`

**Description:**

Create `safe_send(event_type, **kwargs)` in `src/notifications/telegram.py` per spec §3.4. Re-export from `src/notifications/__init__.py` (Glob-verified: file is currently 0 bytes — no existing re-exports to preserve). Behavior: imports target `notify_X` explicitly (ImportError raises immediately, NOT swallowed); checks `is_telegram_enabled()` once; calls `notify_X`; catches ONLY network failures (`urllib3.exceptions.HTTPError`, `requests.exceptions.RequestException`, `socket.timeout`, `OSError`) — NOT bare Exception; logs at appropriate severity; increments `notifications_sent_failed` counter; persists outcome to `notifications_sent` table (Group E hook lands later in T15 — for T3, stub the table write behind a feature flag).

**Reviewer drift-correction (item #16):** Reviewer flagged a "self-import at `src/notifications/telegram.py:26`". **Verified by architect: line 26 is a function-list comment (`send_telegram, is_telegram_enabled, _get_telegram_config`), NOT an import. The only `from src.notifications.*` import inside `telegram.py` is at line 1028 (`from src.notifications.telegram_commands import (...)`) — that is a SIBLING-module import, not self-import.** No remediation needed; the spec already prescribes consolidating `_get_telegram_config` via `src/notifications/_config.py` (T6) which will eliminate the cross-module dependency at line 1028 over time.

Tests in `tests/notifications/test_safe_send.py` (NEW file): assert ImportError propagates, network errors caught, NameError propagates, counter incremented on failure, `is_telegram_enabled()` returning False short-circuits, success path.

**Scope fence:**

Do NOT migrate caller sites here (Task 4). Do NOT add `notifications_sent` table here (Task 14 owns schema, Task 15 owns write hooks) — stub the persistence call behind a feature flag. Do NOT modify other notify_* functions. Do NOT touch `src/notifications/platform_events.py` (Task 15). CHANGELOG.md: replace ONLY `<!-- T3 -->` placeholder.

**Test strategy:**

1) `safe_send` invokes target `notify_X` correctly. 2) Network error (`RequestException`) caught and logged as warning. 3) NameError NOT caught — propagates. 4) ImportError NOT caught — propagates. 5) `is_telegram_enabled()` returning False short-circuits without invoking `notify_X`. 6) Failed dispatch increments counter (will hook to `notifications_sent` table in T15). **Net new tests: +6**.

**Sibling-search reminder:** see CLAUDE.md `feedback_review_sibling_search` memory.

---

### Task 4 — Group A.3 — Migrate 16 caller sites to safe_send (4 sub-PRs T4a/T4b/T4c/T4d)

> Per reviewer item #10, T4 is restructured as 4 separate plan entries below (T4a–T4d). Each has its own `files_in_scope` (4-file cap honored). All 16 files Glob-verified by architect.

#### Task 4a — Group A.3.a — Scheduler caller migration

- **Wave**: W1 (Batch 3a)
- **Depends on**: [3]
- **Complexity**: low
- **Files in scope**:
  - `src/scheduler/watch.py`
  - `src/scheduler/reports.py`
  - `src/scheduler/watch_handlers.py`
  - `src/scheduler/overnight.py`
- **Files read-only**:
  - `src/notifications/telegram.py`
  - `src/notifications/__init__.py`

**Description:**

Mechanical migration: replace `try/except Exception { import + check + call }` with one-line `safe_send('event_name', **kwargs)` at the 4 scheduler files. SIBLING-SEARCH per file: GREP `try:\s*\n\s*from src\.notifications` blocks; verify zero post-migration. CHANGELOG.md: replace ONLY `<!-- T4a -->` placeholder.

**Scope fence:**

Sub-PR T4a covers ONLY 4 scheduler files. Other 12 files in T4b/T4c/T4d. Do NOT touch `src/notifications/telegram.py` beyond imports. Do NOT change `notify_*` function signatures. Do NOT modify message content/formatting.

**Test strategy:** GREP-driven; existing scheduler tests cover happy path. Net new tests: 0. Test floor unaffected.

#### Task 4b — Group A.3.b — Services + executor caller migration

- **Wave**: W1 (Batch 3a)
- **Depends on**: [3]
- **Complexity**: low
- **Files in scope**:
  - `src/services/scan_service.py`
  - `src/services/recap_service.py`
  - `src/services/watchlist_service.py`
  - `src/shadow_trading/executor.py`
- **Files read-only**:
  - `src/notifications/telegram.py`
  - `src/notifications/__init__.py`

**Description:**

Same mechanical migration pattern as T4a. CHANGELOG.md: replace ONLY `<!-- T4b -->` placeholder.

**Scope fence:** Sub-PR T4b covers ONLY 4 service+executor files. Same do-nots as T4a.

**Test strategy:** Same as T4a. Net new tests: 0.

#### Task 4c — Group A.3.c — Training + risk caller migration

- **Wave**: W1 (Batch 3a)
- **Depends on**: [3]
- **Complexity**: low
- **Files in scope**:
  - `src/training/canary.py`
  - `src/training/ingestion_gate.py`
  - `src/training/trainer.py`
  - `src/risk/governor.py`
- **Files read-only**:
  - `src/notifications/telegram.py`
  - `src/notifications/__init__.py`

**Description:**

Same mechanical migration. CHANGELOG.md: replace ONLY `<!-- T4c -->` placeholder.

**Scope fence:** Sub-PR T4c covers ONLY 4 training+risk files. Same do-nots as T4a.

**Test strategy:** Same as T4a. Net new tests: 0.

#### Task 4d — Group A.3.d — Misc caller migration

- **Wave**: W1 (Batch 3a)
- **Depends on**: [3]
- **Complexity**: low
- **Files in scope**:
  - `src/evaluation/auditor.py`
  - `src/data_collection/research_synthesizer.py`
  - `src/cli/commands.py`
  - `src/api/cloud_routes/platform.py`
- **Files read-only**:
  - `src/notifications/telegram.py`
  - `src/notifications/__init__.py`

**Description:**

Same mechanical migration. NOTE: `src/cli/commands.py` is also touched by T5 (lazy-imports → module-level). T4d migrates the call sites; T5 relocates the imports. They touch the same file but in different ways. T5 depends on T4d to avoid merge conflicts. CHANGELOG.md: replace ONLY `<!-- T4d -->` placeholder.

**Scope fence:** Sub-PR T4d covers ONLY 4 misc files. Coordinate with T5 — T4d migrates call sites (try/except → safe_send), T5 relocates imports (function-body → module-level).

**Test strategy:** Same as T4a. Net new tests: 0.

---

### Task 5 — Group A.4 — Fix I10 cli/commands.py lazy imports

- **Wave**: W1 (Batch 3a — same batch as T4d, but sequential within batch)
- **Depends on**: [3, 4d]
- **Complexity**: low
- **Files in scope**:
  - `src/cli/commands.py`
  - `tests/cli/test_commands_imports.py` (NEW — `tests/cli/` directory does NOT yet exist, create it)
- **Files read-only**:
  - `src/notifications/telegram.py`

**Description:**

Replace lazy in-function imports of `src.notifications.*` with module-level imports in `src/cli/commands.py`. Let ImportError happen at process startup, not at first runtime hit. SIBLING-SEARCH RULE: GREP `^\s*from src\.notifications` inside function bodies (use multiline regex); expect zero post-fix. Add `tests/cli/test_commands_imports.py` (NEW) asserting no lazy imports remain (AST walk).

**Scope fence:**

Do NOT modify command logic — only import site relocation. Do NOT add new CLI commands. Do NOT touch `src/notifications/*` (Task 3). T5 must rebase on T4d's merge (`feedback_pm_dispatch_path_verification`). CHANGELOG.md: replace ONLY `<!-- T5 -->` placeholder.

**Test strategy:**

1) AST walk of `src/cli/commands.py`: no `from src.notifications.*` imports inside `FunctionDef` nodes. 2) Module-level import of `src.notifications.*` succeeds at module load. 3) Existing CLI command tests still pass. **Net new tests: +2**.

---

### Task 6 — Group A.5 — Fix I12 + CC2 (per-check except + consolidate config loaders)

- **Wave**: W1 (Batch 3a)
- **Depends on**: [3]
- **Complexity**: low
- **Files in scope**:
  - `src/notifications/telegram_commands.py`
  - `src/notifications/telegram.py`
  - `src/notifications/_config.py` (NEW)
  - `tests/notifications/test_check_action_reminders_isolation.py` (NEW)
- **Files read-only**: (none — all 4 in scope)

**Description:**

I12: `src/notifications/telegram_commands.py:236-237` `check_action_reminders` — break function-wide bare `except` into per-check `except`. Each of 5 reminders independently fails.

CC2: consolidate `_get_telegram_config` (currently duplicated at `src/notifications/telegram.py:104` AND `src/notifications/telegram_commands.py:32` — line numbers verified by architect, REVISED from prior `:114` and `:43`) into shared helper at `src/notifications/_config.py` (NEW file). Both modules import from the new shared module.

Add `tests/notifications/test_check_action_reminders_isolation.py` (NEW): simulate one reminder raising; assert other 4 still execute.

**Scope fence:**

Do NOT change reminder logic — only error-handling granularity. Do NOT migrate callers of `_get_telegram_config` beyond the 2 modules. Both `src/notifications/_config.py` and `tests/notifications/test_check_action_reminders_isolation.py` are NEW files. CHANGELOG.md: replace ONLY `<!-- T6 -->` placeholder.

**Test strategy:**

1) Mock 5 reminders; raise exception in reminder 2 only; assert reminders 1, 3, 4, 5 all execute and reminder 2 logged at error. 2) `_get_telegram_config` single source of truth — both `telegram.py` and `telegram_commands.py` import from `src/notifications/_config.py`. 3) Existing tests for both files continue to pass. **Net new tests: +2**.

**Sibling-search reminder:** see CLAUDE.md `feedback_review_sibling_search` memory.

---

### Task 7 — Cloud-req CI guardrail (fast-lane AST walker)

- **Wave**: W1 (Batch 1)
- **Depends on**: [1]
- **Complexity**: medium
- **Files in scope**:
  - `tests/test_cloud_requirements_imports.py` (NEW)
  - `scripts/check_cloud_deploy_imports.py` (NEW)
  - `requirements-cloud.txt`
- **Files read-only**:
  - `src/api/cloud_app.py`
  - `requirements.txt`

**Description:**

WAVE 1 BLOCKER (alongside Group A). 4th recurrence (jsonschema → numpy → requests → scipy) of cloud-deploy import drift; #1007 was Sprint 3 hot-fix. Create `tests/test_cloud_requirements_imports.py` (NEW): AST walks imports reachable from `src/api/cloud_app.py`; asserts each top-level package is stdlib OR in `requirements-cloud.txt`. Sub-second runtime, runs on every PR.

**Stop-list (per reviewer item-MINOR):** AST walker walks ONLY imports reachable from `cloud_app.py`'s import graph. **Stop traversal at `src/api/cloud_routes/*` boundary at the package level — only walk imports reachable from `cloud_app`'s import graph, NOT test fixtures, NOT `tests/*`, NOT `scripts/*`.** Document the stop-list as constants at the top of the test file.

Helper at `scripts/check_cloud_deploy_imports.py` (NEW; shareable invocation; used by T8 slow-lane and CI). Test asserts: (a) cloud_app imports parse, (b) all imports resolvable to stdlib or `requirements-cloud.txt` entry, (c) helpful error message lists missing packages.

**T7 = ALL Wave 5 PR gate; T8 = informational/CI-only.** Per reviewer item #4: **T7 (fast-lane AST walker) gates ALL Wave-2/W2 PRs on every commit (PR-time CI). T8 (slow-lane venv) is informational/CI-only — does NOT block PR merge or downstream tasks.** Documented in spec §6 risk table also.

**Scope fence:**

Fast-lane only. Do NOT create temp venv (Task 8). Do NOT modify `requirements-cloud.txt` unless to add packages currently used (verify GREP first). Do NOT add new dependencies. CHANGELOG.md: replace ONLY `<!-- T7 -->` placeholder.

**Test strategy:**

1) Synthetic test: cloud_app.py imports `numpy` (not in requirements-cloud.txt) → test fails with helpful error. 2) Current state: cloud_app.py imports clean → test passes. 3) Standard library imports (datetime, json) accepted without registration. 4) Transitively-reachable imports walked (e.g. cloud_app → cloud_routes/kpis → cohort_meta — all packages checked); test fixtures NOT walked. **Net new tests: +4**.

---

### Task 8 — Cloud-req CI guardrail (slow-lane venv subprocess)

- **Wave**: W1 (Batch 2)
- **Depends on**: [7]
- **Complexity**: medium
- **Files in scope**:
  - `tests/test_cloud_requirements_imports.py` (EXTEND)
- **Files read-only**:
  - `src/api/cloud_app.py`
  - `requirements-cloud.txt`
  - `scripts/check_cloud_deploy_imports.py`

**Description:**

Extend `tests/test_cloud_requirements_imports.py` with `@pytest.mark.slow` test that creates a temp venv via `venv` module, installs ONLY `requirements-cloud.txt`, runs `python -c 'from src.api.cloud_app import app'`, asserts exit 0 + no `ModuleNotFoundError`. Marked slow; gated behind `--run-slow` flag locally; opt-in via env in CI. **NOT a PR merge gate — informational only** (per reviewer item #4 + spec §6 risk table).

WORKTREE CAVEAT (memory `feedback_worktree_env_drift`): venv setup is hermetic, doesn't carry `.env`. Fixture explicitly clears `ARCIS_LOCAL_API_TOKEN` and other env that cloud_app reads.

**Scope fence:**

Do NOT modify `requirements-cloud.txt` (Task 7 owns). Do NOT change `scripts/check_cloud_deploy_imports.py`. Do NOT add new test files. CHANGELOG.md: replace ONLY `<!-- T8 -->` placeholder.

**Test strategy:**

1) `@pytest.mark.slow` test creates temp venv, installs `requirements-cloud.txt`, imports `cloud_app`. Exit 0. 2) Synthetic regression: temp venv missing scipy → test fails with explicit ModuleNotFoundError on scipy. 3) Worktree-isolated run: env vars cleared in fixture; cloud_app loads without `.env`. **Net new tests: +2**.

---

### Task 9 — Cockpit-#1 — Shadow metrics live cohort (helper extension)

- **Wave**: W2 (Batch 3b)
- **Depends on**: [1]
- **Complexity**: medium
- **Files in scope**:
  - `src/api/cloud_routes/trades.py`
  - `tests/api/test_shadow_metrics.py`
  - `tests/api/test_sharpe_attribution.py` (NEW — Glob-verified: does NOT exist; create it)
- **Files read-only**:
  - `src/api/cohort_meta.py`

**Description:**

DRIFT-CORRECTED: helper at `src/api/cloud_routes/trades.py:42-57` (NOT `analytics.py` per brief). **Helper signature today: `_desk_clause(desk: str | None) -> tuple[str, list]`** — verified by architect; reviewer's prior `(frag, params) → (frag, params, cohort_id)` description had INPUT/OUTPUT inverted.

Extend the helper signature to **`_desk_clause(desk: str | None) -> tuple[str, list, str]`** — same `desk` input; new output adds `cohort_id`. For `desk='live'`: emit SQL fragment `source = %s` with param `'live'` AND `cohort_id='trades.live_only'`. Other desks: `cohort_id='trades.all_closed'`.

5-endpoint blast radius — all 5 callers update tuple unpacking: `shadow_open`, `shadow_closed`, `sharpe_attribution`, `shadow_metrics`, `shadow_account` (all live in `src/api/cloud_routes/trades.py`). Update `shadow_metrics` endpoint at `trades.py:301-343` to consume `cohort_id` from helper instead of hardcoding.

**Glob-verified test files (item #6):**
- `tests/api/test_shadow_metrics.py` — EXISTS.
- `tests/api/test_sharpe_attribution.py` — does NOT exist (NEW file in scope).
- `tests/api/test_shadow_open.py` / `test_shadow_closed.py` / `test_shadow_account.py` — do NOT exist. **Coverage for these endpoints lives inside `tests/api/test_shadow_metrics.py`** (verified by architect via Glob; the existing file covers the helper's downstream consumers in one place). T9 extends `test_shadow_metrics.py` to add per-desk cohort assertions for all 5 endpoints. **No T9 file split needed** — `files_in_scope` stays at 3 entries; max-4 honored.

SIBLING-SEARCH RULE: GREP `src/api/cloud_routes/trades.py` for `_desk_clause(` — verify all 5 call sites updated to consume new 3-tuple shape.

**Scope fence:**

Do NOT add new cohort labels to `src/api/cohort_meta.py` — use existing `'trades.live_only'`. Do NOT modify `cohort_meta.py` at all. Do NOT touch `analytics.py`. Do NOT extend to other endpoints beyond the 5 in `trades.py`. CHANGELOG.md: replace ONLY `<!-- T9 -->` placeholder.

**Test strategy:**

1) `shadow_metrics?desk=live` → response `_meta.cohort='trades.live_only'`; SQL filter contains `source='live'`. 2) `shadow_metrics?desk=swing` → cohort=`'trades.all_closed'`. 3) `shadow_metrics?desk=all` → cohort=`'trades.all_closed'`, no desk filter. 4) `sharpe_attribution` (new test file): tuple unpacking compiles, behavior unchanged for non-live desks. 5) GREP confirms all 5 call sites updated. **Net new tests: +5**.

---

### Task 10 — Cockpit-#2 — /api/status open_positions cohort align (SQL source filter)

- **Wave**: W2 (Batch 3b)
- **Depends on**: [1]
- **Complexity**: low
- **Files in scope**:
  - `src/api/cloud_routes/core.py`
  - `tests/api/test_status.py` (EXTEND — Glob-verified: exists)
- **Files read-only**:
  - `src/api/cloud_routes/trades.py`
  - `src/api/cohort_meta.py`

**Description:**

`src/api/cloud_routes/core.py:147-150`: add `WHERE source='live'` to SQL. Cohort label `'trades.live_only'` (already at `core.py:189`) now matches SQL. Reconciliation: `/api/status.open_positions == /api/live/summary.open_positions` (T16 already asserts equality; T19 extension verifies cohort match).

SIBLING-SEARCH RULE: GREP `src/api/cloud_routes/core.py` for `WHERE status='open'` — expect ONLY this site after fix; document in PR body. Add `test_status_open_positions_cohort_aligned` in `tests/api/test_status.py`.

**Scope fence:**

Do NOT touch `trades.py` (Task 9 owns `_desk_clause` helper; T10 is at `/api/status` only). Do NOT modify `cohort_meta.py`. Do NOT add new endpoints. CHANGELOG.md: replace ONLY `<!-- T10 -->` placeholder.

**Test strategy:**

1) `/api/status.open_positions == /api/live/summary.open_positions` (live=2 in fixture). 2) Mock shadow_trades has 5 rows: 2 source=live status=open + 3 source=swing status=open → open_positions=2. 3) Cohort label `'trades.live_only'` aligns with SQL. 4) Pre-fix data (no source filter): open_positions=5 → test fails (regression-lock). **Net new tests: +2**.

---

### Task 11 — Cockpit-#8a — Backend total_pnl_dollars emit (8a backend ONLY; Group B email is T11.5)

> Per reviewer item-MINOR: split T11 into T11 (backend only, 2 files: `kpis_compute.py` + `kpis.py`) and T11.5 (Group B email + tests, 2 files: `email/notifier.py` + `tests/email/test_notifier.py`). Each parallel-safe. T11 retains `depends_on: [3]` (per reviewer item #4 — drop T8 dependency); T11.5 retains `depends_on: [3]` (Group B C17 telegram-fallback uses safe_send from T3). T11.5 does NOT depend on T11 (different files).

- **Wave**: W2 (Batch 3b)
- **Depends on**: [3]
- **Complexity**: low
- **Files in scope**:
  - `src/api/cloud_routes/kpis_compute.py`
  - `src/api/cloud_routes/kpis.py`
  - `tests/api/test_kpis.py` (EXTEND — Glob-verified: exists)
- **Files read-only**:
  - `src/api/cohort_meta.py`

**Description:**

8a: Add `compute_total_pnl_dollars(instrumented)` returning sum of `pnl_dollars` rounded, to `src/api/cloud_routes/kpis_compute.py`. Wire into `src/api/cloud_routes/kpis.py:104` (line of `@router.get("/kpis", ...)` decorator — LINE NUMBER REVISED from prior `:115-135`; actual return-dict spans `:116-136`) — emit `total_pnl_dollars` field plus `_meta.total_pnl_dollars` (cohort=`'kpi.canonical'`, n=`n_trades`).

CHANGELOG.md: replace ONLY `<!-- T11a -->` placeholder.

**Scope fence:**

Do NOT touch frontend KPIStrip (Task 12). Do NOT modify `src/email/*` (Task 11.5). Do NOT modify cohort_meta.py.

**Test strategy:**

1) `/api/kpis.total_pnl_dollars` present + correctly summed from instrumented trades. 2) `/api/kpis._meta.total_pnl_dollars.cohort='kpi.canonical'`, `.n=n_trades`. 3) total_pnl_dollars=0.0 when no instrumented trades. **Net new tests in `tests/api/test_kpis.py`: +3** (covered by T11 — T11 contributes 3 tests, T11.5 contributes 3 — combined +6 in test-floor accounting).

---

### Task 11.5 — Group B — Email subsystem hardening + tests

- **Wave**: W2 (Batch 3b — parallel with T11)
- **Depends on**: [3]
- **Complexity**: medium
- **Files in scope**:
  - `src/email/notifier.py`
  - `src/email/__init__.py`
  - `tests/email/test_notifier.py` (NEW — Glob-verified: does NOT exist; create `tests/email/` directory)
- **Files read-only**:
  - `src/notifications/__init__.py`
  - `src/notifications/telegram.py`

**Description:**

Group B: `src/email/notifier.py` — fix C5 (`cc_addresses or []`), drop YAML password fallback C4 (require `EMAIL_PASSWORD` env, startup warn if YAML key non-empty), I17 (`config['training']['target_examples']` for digest_builder), C17 telegram-fallback path (uses `safe_send` from T3). N1: re-export `digest_builder` from `src/email/__init__.py`.

New `tests/email/test_notifier.py` (NEW; `tests/email/` directory does NOT yet exist — create it): mock `smtplib.SMTP`; assert envelope (To/Cc/Subject), TLS path, auth path, `from_address` fallback, `ConnectionRefusedError` handling, telegram-fallback fires when SMTP returns False.

CHANGELOG.md: replace ONLY `<!-- T11b -->` placeholder.

**Scope fence:**

Do NOT touch frontend KPIStrip (Task 12). Do NOT modify `src/notifications/*` (Group A tasks). Do NOT add new email digests — only fix existing 6 paths. Do NOT modify SMTP server config — env vars only.

**Test strategy:**

1) cc_addresses=None → no TypeError. 2) EMAIL_PASSWORD env required; YAML fallback removed; startup warn if YAML key non-empty. 3) SMTP returns False → safe_send telegram-fallback fires with subject + truncated body. 4) ConnectionRefusedError caught + persisted to `notifications_sent` (stub OK pre-T15). 5) TLS path: `starttls()` called when port 587. 6) Envelope: To/Cc/Subject correctly populated. **Net new tests: +3 (test_notifier.py)** (combined with T11's +3 = 6 in test-floor accounting).

---

### Task 12 — Cockpit-#8b — KPIStrip P&L card (replace PromotionGateCard)

- **Wave**: W2 (Batch 4)
- **Depends on**: [11]
- **Complexity**: medium
- **Files in scope**:
  - `frontend/src/components/dashboard/KPIStrip.jsx`
  - `frontend/src/components/dashboard/KPIStrip.test.jsx`
- **Files read-only**:
  - `src/api/cloud_routes/kpis.py`

**Description:**

Replace `PromotionGateCard` (5th card) at `frontend/src/components/dashboard/KPIStrip.jsx:285-303` with new `TotalPnlDollarsCard`. Surface vote count as tooltip badge under `TrafficLightCard` (lift `kpi={safeKpis.promotion_gate}` into TL card's tooltip slot). New `TotalPnlDollarsCard` follows existing card API; reads `safeKpis.total_pnl_dollars` + `safeKpis._meta?.total_pnl_dollars` (uses Sprint 3 T5 KPICard meta-prop API). Extend `KPIStrip.test.jsx`: P&L card renders, vote count visible in TL tooltip, no `PromotionGateCard`.

VISUAL-VERIFY RULE: render in browser before push (memory `feedback_visual_verify_ui`). Acceptance criteria for new P&L card defined in T1 description: `$X,XXX.XX` format, meta badge visible, no console errors, value matches `/api/kpis._meta.total_pnl_dollars.value`.

OPERATOR-OVERRIDE OPTION: alternative is 6th card with grid `'repeat(6,1fr)'`; both options documented.

**Scope fence:**

Do NOT modify `KPICard` component (Sprint 3 T5 owns). Do NOT touch other Dashboard.jsx widgets. Do NOT change `/api/kpis` backend (Task 11). Do NOT remove `PromotionGateCard` component file — only its usage in `KPIStrip`. CHANGELOG.md: replace ONLY `<!-- T12 -->` placeholder.

**Test strategy:**

1) Mock `safeKpis.total_pnl_dollars=$1234.56` + `_meta.total_pnl_dollars` cohort/label/n → P&L card renders with value + meta badge. 2) `PromotionGateCard` absent from DOM. 3) `TrafficLightCard` tooltip contains vote count text. 4) Visual-verify screenshot in PR (Chrome DevTools MCP). **Net new tests: +2**.

---

### Task 13 — Group C — Telegram template hygiene + chunked send + HTML escape

- **Wave**: W2 (Batch 3b)
- **Depends on**: [3]
- **Complexity**: medium
- **Files in scope**:
  - `src/notifications/telegram.py`
  - `src/data_ingestion/finnhub.py`
  - `tests/notifications/test_telegram_chunked_send.py` (NEW)
  - `tests/notifications/test_html_escape.py` (NEW)
- **Files read-only**:
  - `src/notifications/__init__.py`

**Description:**

`src/notifications/telegram.py`: add `_html_escape(text)` helper (I6); use on all interpolated string fields. Add chunked send for `>4000 chars` with `[chunk N/M]` markers (C15).

**Reviewer drift-correction (item #2):** Spec previously cited `telegram.py:125-160` for the chunked-send range. **Architect verified: the range refers to the `send_telegram` function body which currently spans `:125-160` (def at line 125, ends ~160) — but there is NO existing 4096-char truncate logic in that function** (verified via GREP for `4096` / `truncate` — zero matches). T13 ADDS chunked-send to `send_telegram` (currently a single-shot post). Implementation: GREP-locate `send_telegram` function body (lines 125-160 is approximate — task author should re-locate by function name, not line), insert chunking logic before the `requests.post` call.

C16: `notify_research_digest` truncates summary, append `[truncated; see email digest]`.
C7: mirror `notify_overnight_training_complete` `dict-with-success` pattern in `notify_overnight_complete`.
I11: `notify_action_required` icons map raises on unknown urgency.
I16: drop manual `&amp;` escapes in `notify_premarket_brief` and `notify_weekly_digest`; use `_html_escape`.
I15: normalize earnings time labels in `src/data_ingestion/finnhub.py` adapter.

New tests: `tests/notifications/test_telegram_chunked_send.py` (NEW) + `tests/notifications/test_html_escape.py` (NEW).

PER-DELIVERABLE COMMIT-AND-PUSH: T13a (chunked + escape helper + tests, 2 files), T13b (notify_* updates, 1 file), T13c (finnhub I15 + I11, 1 file). Each replaces ONLY its CHANGELOG placeholder line (`<!-- T13a -->`, `<!-- T13b -->`, `<!-- T13c -->`).

**Scope fence:**

Do NOT migrate caller sites (Task 4). Do NOT add new notify_* functions. Do NOT modify message body content beyond escape/chunk mechanism. Do NOT touch `src/email/*` (Task 11.5).

**Test strategy:**

1) `_html_escape`: `'&'`→`'&amp;'`, `'<'`→`'&lt;'`, `'>'`→`'&gt;'`. 2) Chunked send: 5000-char body → 2 messages with `[chunk 1/2]`, `[chunk 2/2]` markers. 3) <4000-char body → single message, no chunking. 4) `notify_overnight_complete` with non-string error → does not falsely render success. 5) `notify_action_required` with unknown urgency → ValueError raised (not silent default). 6) `notify_premarket_brief`: `'&amp;'` replaced by `_html_escape`; output identical to pre-fix manual escape. 7) finnhub `earnings_time` normalized upstream — fixture trade with raw time → `notify_position_earnings_warning` consumes normalized string. **Net new tests: +6**.

---

### Task 14 — Group E.A — notifications_sent + notifications_dedup schema registration

- **Wave**: W1 (Batch 3a)
- **Depends on**: [1]
- **Complexity**: low
- **Files in scope**:
  - `src/schema/registry.py`
  - `tests/test_schema.py`
- **Files read-only**:
  - `src/api/cohort_meta.py`

**Description:**

Register two new tables in `src/schema/registry.py` per CLAUDE.md schema rules (NO `CREATE TABLE` outside registry).

`notifications_sent`: `id INTEGER PRIMARY KEY` + `event_type TEXT NOT NULL` + `channel TEXT NOT NULL ('telegram'|'email')` + `recipient TEXT` (nullable for broadcast) + `sent_at TEXT NOT NULL` (ISO timestamp) + `status TEXT NOT NULL ('ok'|'failed'|'dropped'|'heartbeat')` + `retry_count INTEGER NOT NULL DEFAULT 0` + `error_msg TEXT` (nullable). Index `(event_type, sent_at DESC)`.

`notifications_dedup`: `id INTEGER PRIMARY KEY` (ADDED per reviewer item-MINOR for codebase-pattern consistency with `notifications_sent`) + `event_type TEXT NOT NULL` + `dedup_key TEXT NOT NULL` + `sent_at TEXT NOT NULL` + UNIQUE constraint `(event_type, dedup_key)`. The unique constraint enforces deduplication while keeping the integer-PK convention.

Run `python -m src.main validate-schema --fix` post-merge.

Add `tests/test_schema.py` extension asserting both tables registered + columns match spec.

**Scope fence:**

Do NOT add `CREATE TABLE` statements anywhere. Do NOT migrate `_DEDUP_CACHE` here (Task 15). Do NOT add write-path code (Task 15). Schema-only. CHANGELOG.md: replace ONLY `<!-- T14 -->` placeholder.

**Test strategy:**

1) `TABLES` dict contains `'notifications_sent'` + `'notifications_dedup'`. 2) Schema validation runs clean — no drift. 3) `test_schema.py` asserts column types match spec (`id INTEGER PRIMARY KEY`; `event_type TEXT NOT NULL`; etc.). 4) Index `(event_type, sent_at DESC)` registered. 5) UNIQUE constraint `(event_type, dedup_key)` registered on `notifications_dedup`. **Net new tests: +2**.

---

### Task 15 — Group E.B — Notifications observability + dedup persistence + health widget

- **Wave**: W2 (Batch 4)
- **Depends on**: [3, 11.5, 14]
- **Complexity**: high
- **Files in scope**:
  - `src/notifications/platform_events.py`
  - `src/api/cloud_routes/notifications.py` (NEW — Glob-verified: does NOT exist)
  - `frontend/src/components/dashboard/NotificationsHealthPanel.jsx` (NEW — Glob-verified: does NOT exist)
  - `frontend/src/api.js`
- **Files read-only**:
  - `src/schema/registry.py`
  - `src/notifications/telegram.py`
  - `src/email/notifier.py`

**Description:**

`src/notifications/platform_events.py`: refactor `_DEDUP_CACHE` (currently at `:26` per architect Grep) to use `notifications_dedup` table. Restart-safe (memory `feedback_watch_loop_management` — NSSM restarts the watch loop).

Wire `safe_send` (Task 3) and email notifier (Task 11.5) write hooks into `notifications_sent` table after every dispatch. C12: add `force_send=True` kwarg to bypass silent-on-pass for `notify_validation_summary`. Heartbeat sentinel writes `notifications_sent` with `status='heartbeat'` every N hours.

New endpoint `src/api/cloud_routes/notifications.py:/api/notifications/health` (last 24h success/fail rate, dedup hits, oldest unack alert).

New `frontend/src/components/dashboard/NotificationsHealthPanel.jsx` — bottom-of-page widget reads `/api/notifications/health` (uses arrow-form queryFn pre-meeting T16 ESLint rule).

New entry in `frontend/src/api.js`: `getNotificationsHealth`.

PER-DELIVERABLE COMMIT-AND-PUSH:
- **T15a**: `platform_events.py` dedup migration + heartbeat (replaces `<!-- T15a -->`).
- **T15b**: write hooks + `/api/notifications/health` endpoint (`src/api/cloud_routes/notifications.py` NEW + part of `src/notifications/platform_events.py`) (replaces `<!-- T15b -->`).
- **T15c**: frontend widget (`NotificationsHealthPanel.jsx` NEW + `frontend/src/api.js` extension) + **operator-guide NSSM-restart re-fire warning paragraph** (per reviewer item #13) — append to `docs/operator-guide.md` §"Notification dedup migration": warn operator about expected one-shot duplicate alerts on first NSSM restart post-merge. Optional post-deploy script seeds `notifications_dedup` from `notifications_sent` rows where `sent_at > NOW() - 24h` (script optional, doc paragraph mandatory). T15c also replaces `<!-- T15c -->`.

VISUAL-VERIFY RULE: NotificationsHealthPanel rendered in browser before push.

**Scope fence:**

Do NOT add new tables (Task 14 owns schema). Do NOT modify safe_send wrapper internals (Task 3). Do NOT migrate caller sites (Task 4). Do NOT add new notify_* functions. T15c includes one operator-guide paragraph; do NOT modify other operator-guide sections.

**Test strategy:**

1) `_DEDUP_CACHE` migrated: dedup query reads `notifications_dedup` table. NSSM restart preserves dedup state (test via fresh process + same `dedup_key` — no re-fire). 2) safe_send write hook: failure event → `notifications_sent` row with `status='failed'`, `error_msg` populated. Success → `status='ok'`. 3) Email notifier write hook: SMTP success → row with `channel='email'`, `status='ok'`. SMTP fail + telegram-fallback → 2 rows (email failed + telegram ok). 4) `/api/notifications/health`: returns last-24h aggregates `{success_rate, fail_count, dedup_hits, oldest_unack_alert}`. 5) Frontend `NotificationsHealthPanel` renders panel; visual-verify screenshot in PR. **Net new tests: +5**.

---

### Task 16 — Cockpit-#7 — Bare queryFn 2 sites + ESLint rule extension

- **Wave**: W2 (Batch 3b)
- **Depends on**: [1]
- **Complexity**: low
- **Files in scope**:
  - `frontend/src/pages/StrategyResearch.jsx`
  - `frontend/src/components/PlatformStatusWidget.jsx`
  - `frontend/eslint-rules/no-bare-queryfn-with-args.js`
  - `frontend/eslint-rules/no-bare-queryfn-with-args.test.js` (NEW — Glob-verified: only `.js` exists, `.test.js` does NOT; create it)
- **Files read-only**:
  - `frontend/src/api.js`

**Description:**

DRIFT-CORRECTED: Sprint 3 ESLint rule at `frontend/eslint-rules/no-bare-queryfn-with-args.js:60` only flags `MemberExpression`. Bare queryFn at `StrategyResearch.jsx:41` + `PlatformStatusWidget.jsx:13` is `Identifier` (named import: `queryFn: getPlatformStrategies`). Extend rule: flag any `prop.value` where `type !== 'ArrowFunctionExpression' && type !== 'FunctionExpression'`. Wrap `StrategyResearch.jsx:41` → `queryFn: () => getPlatformStrategies()`. Wrap `PlatformStatusWidget.jsx:13` same.

SIBLING-SEARCH RULE: GREP `frontend/src/` for `queryFn: \w+$` (Identifier shape, end-of-line); expect zero post-fix. Run `npm --prefix frontend run lint:queryfn` — must exit 0.

**Scope fence:**

Do NOT modify other useQuery sites (Sprint 3 already wrapped them). Do NOT touch `api.js`. Do NOT add new ESLint rules — extend existing only. CHANGELOG.md: replace ONLY `<!-- T16 -->` placeholder.

**Test strategy:**

1) ESLint rule fires on synthetic `useQuery({queryFn: foo})` (Identifier). 2) Rule does NOT fire on `useQuery({queryFn: () => foo()})`. 3) Rule does NOT fire on `useQuery({queryFn: function() {}})`. 4) Rule fires on `useQuery({queryFn: foo.bind(this)})` (CallExpression). 5) `StrategyResearch.jsx` + `PlatformStatusWidget.jsx` wrapped; lint exits 0. 6) Existing `tests/test_eslint_queryfn_guardrail.py` continues to pass (no Sprint 3 regression). **Net new tests: +4**.

---

### Task 17 — Cockpit-#3 — Calmar 4 sites migrate (allowlist becomes empty)

- **Wave**: W2 (Batch 3b)
- **Depends on**: [1]
- **Complexity**: medium
- **Files in scope**:
  - `src/evaluation/cto_report.py`
  - `src/simulation/engine.py`
  - `src/evaluation/backtester.py`
  - `src/platform/metrics.py`
- **Files read-only**:
  - `src/evaluation/statistics.py`
  - `tests/test_calmar_canonical_only.py`

**Description:**

Migrate 4 hand-rolled Calmar sites to canonical `src/evaluation/statistics.py:131` `calmar_ratio()`:

(1) `src/evaluation/cto_report.py:738`: `(mean_r * 150) / max_dd_pct` → `calmar_ratio(mean_r * 150, max_dd_pct)`.
(2) `src/simulation/engine.py:439`: `annualized_return / max_dd` → `calmar_ratio(annualized_return, max_dd)`.
(3) `src/evaluation/backtester.py:343`: `round(ann_return / abs(max_dd_pct), 2)` → `round(calmar_ratio(ann_return, abs(max_dd_pct)), 2)`.
(4) `src/platform/metrics.py:75` (`compute_calmar`): replace body with `calmar_ratio(total_return, max_drawdown)`.

**Inf-sentinel sibling-search (per reviewer item #8 — EXPANDED PATTERN):** GREP across **ALL** `src/` (not just direct `compute_calmar` callers) for the expanded pattern set:

```
(== inf|== math\.inf|== float\(['\"]inf['\"]\)|isinf\(|isfinite\(.*not|sys\.float_info\.max|Infinity)
```

Catches `math.isinf(x)`, `np.isinf(x)`, `not math.isfinite(x)`, `sys.float_info.max`, `Infinity` (JS-style), and the originally-listed `== inf` / `> 1e10`. **Remediation if any match found**: route via local wrapper that maps `0.0` → caller-expected sentinel (preserves caller assumption while keeping canonical helper unchanged). Document each match and remediation in PR body.

`tests/test_calmar_canonical_only.py`: remove all entries from `_ALLOWLIST` and `_CALMAR_FUNC_ALLOWLIST` — both become empty sets after T17. **Important: `_ALLOWLIST` is a static set, NOT pytest.parametrize — emptying it does NOT remove test cases. Test count unaffected by allowlist emptying.** Retain `test_no_new_calmar_formulas_outside_allowlist` + `test_no_calmar_named_functions_outside_allowlist` + `test_allowlisted_sites_still_exist` (last one passes vacuously when allowlist is empty) + `test_calmar_func_guardrail_regression_synthetic`.

PER-DELIVERABLE COMMIT-AND-PUSH: T17a (cto_report + engine, replaces `<!-- T17a -->`), T17b (backtester + platform/metrics + allowlist empty, replaces `<!-- T17b -->`).

**Scope fence:**

Do NOT modify `src/evaluation/statistics.py` (canonical helper). Do NOT modify `analytics.py:568` (Sprint 3 T1 already migrated). Do NOT add new Calmar functions anywhere. Per-deliverable commits (T17a, T17b).

**Test strategy:**

1) `cto_report` Calmar: pre-fix value matches canonical to 3 decimals. 2) `engine` Calmar: same. 3) `backtester` Calmar: same (post-round). 4) `platform/metrics.compute_calmar`: `max_dd=0` → returns `0.0` (canonical), NOT `inf` (verify expanded GREP shows no consumer depends on inf). 5) `_ALLOWLIST` and `_CALMAR_FUNC_ALLOWLIST` are empty post-T17. 6) `test_no_new_calmar_formulas_outside_allowlist` + `test_no_calmar_named_functions_outside_allowlist` + `test_allowlisted_sites_still_exist` + `test_calmar_func_guardrail_regression_synthetic` all pass. **Net new tests: 0** (allowlist is static set, not parametrize — emptying it does not change test count).

---

### Task 18 — Cockpit-#4 — Stop_loss sign formatting at 5 frontend sites (REFRAMED)

- **Wave**: W2 (Batch 3b)
- **Depends on**: [1]
- **Complexity**: medium
- **Files in scope**:
  - `frontend/src/pages/LiveLedger.jsx`
  - `frontend/src/pages/ShadowLedger.jsx`
  - `frontend/src/pages/TradeHistory.jsx`
  - `frontend/src/pages/__tests__/PnlSignFormatting.test.jsx` (NEW)
- **Files read-only**:
  - `frontend/src/components/ActivityFeed.jsx`

**Description:**

REFRAMED per drift alert: bug pattern `Math.abs(pnl).toFixed(2)` with conditional `+` prefix only for positive — strips negative sign for ALL losing trades, not just stop_loss. Fix at 5 sites:

(1) `frontend/src/pages/LiveLedger.jsx:40` (PnlValue), (2) `frontend/src/pages/ShadowLedger.jsx:64` (PnlValue), (3) `ShadowLedger.jsx:568` (open-cols inline), (4) `ShadowLedger.jsx:592` (closed-cols inline), (5) `frontend/src/pages/TradeHistory.jsx:31-36` (formatDollars — verify).

Replace `${Math.abs(value).toFixed(2)}` + conditional `+` with native sign-preserving format. SIBLING-SEARCH RULE: GREP `frontend/src/` for `Math\.abs.*toFixed` AND `pnl|profit|loss|dollar` proximity; expect zero new sites post-fix. ActivityFeed.jsx:57 explicitly NOT in scope (already correct — passes raw signed value).

New tests assert DOM text contains `-$150.50` for `pnl=-150.50`. VISUAL-VERIFY RULE: render LiveLedger + ShadowLedger + TradeHistory in browser. PER-DELIVERABLE COMMIT-AND-PUSH: T18a (LiveLedger + tests, replaces `<!-- T18a -->`), T18b (ShadowLedger 3 sites + tests, replaces `<!-- T18b -->`), T18c (TradeHistory + tests, replaces `<!-- T18c -->`).

**Scope fence:**

Do NOT touch `ActivityFeed.jsx` — it passes raw signed value already. Do NOT modify backend (already signs correctly). Do NOT change DOM color logic (red/green) — only the textual sign. Do NOT add new components. Per-deliverable commits.

**Test strategy:**

1) PnlValue with `value=-150.50` → DOM text `-$150.50` (NOT `+$150.50` or `$150.50`). 2) PnlValue with `value=+200.00` → `+$200.00`. 3) PnlValue with `value=0` → `$0.00` (no prefix). 4) ShadowLedger inline 568+592: same pattern. 5) TradeHistory `formatDollars`: same pattern. 6) ActivityFeed.jsx unchanged (regression-lock test). 7) Sibling-search GREP expect zero matches outside the 5 fixed sites. **Net new tests: +6**.

---

### Task 19 — Cockpit-#5 + #6 — T16 reconciliation test extensions (postgres + kpis _meta)

- **Wave**: W2 (Batch 4)
- **Depends on**: [10, 11]
- **Complexity**: medium
- **Files in scope**:
  - `tests/test_dashboard_reconciliation.py`
  - `tests/conftest.py` (EXTEND — Glob-verified: file ALREADY EXISTS; T19 EXTENDS, does NOT create)
  - `tests/api/test_status.py` (EXTEND)
- **Files read-only**:
  - `src/api/cloud_routes/kpis.py`
  - `src/api/cloud_routes/core.py`
  - `src/api/cohort_meta.py`

**Description:**

EXTEND `tests/conftest.py` with postgres fixture (file already exists; mocks yfinance + `init_test_db()`). Add new fixture `_postgres_session` using:

```python
@pytest.fixture(scope='function')   # NOT session — per reviewer item #12 — isolate state per test
def postgres_session(...):
    if not os.environ.get('DATABASE_URL'):
        pytest.skip("DATABASE_URL not set; skipping postgres parametrize")
    ...
```

**`pytest.skip` (NOT `skipif` decorator)** is reviewer-flagged-MAJOR (item #12c-clarification): use `pytest.mark.skipif(condition, reason=...)` at decorator level to keep pass-counts CONSISTENT across local (with `DATABASE_URL`) and CI (without). When no `DATABASE_URL`, the postgres parametrization is SKIPPED at collection, NOT FAILED — total test count is identical regardless of env. Operator should ideally `unset DATABASE_URL` before running test count assertions at sprint closeout, OR T23 strict `>=` accommodates either.

Parametrize `tests/test_dashboard_reconciliation.py` to run against both SQLite (existing) and Postgres (new) fixtures.

Add `test_kpis_meta_envelope_reconciliation` per cockpit-#6: assert `_meta.rf_adjusted_excess_sharpe.cohort='kpi.canonical'`, `_meta.win_rate.cohort='kpi.canonical'`, `_meta.total_pnl_dollars.cohort='kpi.canonical'` (T11 lands first), `n` non-negative integers. KPIs needs `_fetch_closed_trades` + `_fetch_spy_returns_for_trades` + `filter_fully_instrumented` patches (per deep analysis). New mock fixture `_kpis_runtime_mock`.

Add `test_status_open_positions_cohort_aligned` per cockpit-#2: assert `core.py:147-150` SQL matches cohort label.

WORKTREE ENV-DRIFT CAVEAT: postgres fixture uses test DB URL via env; CI matrix gates by `DATABASE_URL` presence.

**Scope fence:**

Do NOT modify backend response shape. Do NOT add new endpoints. Do NOT use real network — fixtures only. Do NOT modify CI workflow (operator-task to wire `DATABASE_URL` secret). Do NOT change postgres-fixture scope to `session` — must be `function` or `module` to isolate state. CHANGELOG.md: replace ONLY `<!-- T19 -->` placeholder.

**Test strategy:**

1) `test_kpis_meta_envelope_reconciliation`: mock kpis runtime → `_meta.rf_adjusted_excess_sharpe.cohort='kpi.canonical'`. 2) Same for `win_rate`, `total_pnl_dollars`. All `n` fields non-negative integers. 3) `test_status_open_positions_cohort_aligned`: SQL filter has `source='live'` AND cohort=`'trades.live_only'`. 4) Postgres fixture: `pytest.mark.skipif` SKIPS (not fails) when `DATABASE_URL` not set; otherwise reconciliation runs against PG. 5) SQLite path continues to pass (no regression). **Net new tests: +3**.

---

### Task 20 — Mid-W2 visual-verify checkpoint

- **Wave**: W2 (Batch 5)
- **Depends on**: [12, 15, 18]
- **Complexity**: low
- **Files in scope**:
  - `docs/audits/2026-05-07-sprint-4-cockpit-followups/visual-verify/interim-w2.md` (NEW)
  - `docs/audits/2026-05-07-sprint-4-cockpit-followups/visual-verify/after/README.md` (NEW)
- **Files read-only**:
  - `docs/audits/2026-05-07-sprint-4-cockpit-followups/visual-verify/before/README.md`

**Description:**

Mid-Wave-2 visual-verify checkpoint after T12 (P&L card) + T15 (NotificationsHealthPanel) + T18 (sign formatting at 5 sites) land. Capture screenshots via Chrome DevTools MCP for **the 11 priority pages enumerated in plan-§ "11 priority pages" plus 2 NEW components (P&L card, NotificationsHealthPanel)**. Compare against `before/` baseline (Task 1) where applicable. **For NEW components, assert ACCEPTANCE CRITERIA from T1 instead** (no baseline diff possible):

- P&L card: `$X,XXX.XX` format, meta badge visible, no console errors, value matches `/api/kpis._meta.total_pnl_dollars.value`.
- NotificationsHealthPanel: success_rate / fail_count / dedup_hits / oldest_unack_alert all numeric; no `--` placeholders; meta badge cohort = configured value.

Document diff + acceptance-criteria check in `docs/audits/2026-05-07-sprint-4-cockpit-followups/visual-verify/interim-w2.md`. Catches frontend regressions early per memory `feedback_visual_verify_ui`. If any regression detected, dispatch hot-fix BEFORE T21+ Wave 3 starts. CHANGELOG.md: replace ONLY `<!-- T20 -->` placeholder.

**Scope fence:**

Do NOT modify code. Do NOT add new tasks. Reporting and screenshots only. If regression found, OPEN hot-fix issue and notify operator — do NOT silently fix.

**Test strategy:**

1) `interim-w2.md` table walks Dashboard, KPIStrip, NotificationsHealthPanel, LiveLedger, ShadowLedger, TradeHistory — 11 baseline pages + 2 new components. PASS/FAIL/N-A per row. 2) Any FAIL row blocks Wave 3 dispatch — operator notified. 3) Visual diff screenshots embedded in PR. **Net new tests: 0** (reporting-only).

---

### Task 21 — Group F — Coverage + operator-guide + typed council exceptions

- **Wave**: W3 (Batch 7a)
- **Depends on**: [3, 6, 13, 15]
- **Complexity**: medium
- **Files in scope**:
  - `tests/notifications/test_telegram_commands.py`
  - `tests/notifications/test_telegram_send_path.py` (NEW)
  - `src/notifications/telegram_commands.py`
  - `docs/operator-guide.md`
- **Files read-only**:
  - `src/notifications/telegram.py`
  - `docs/telegram-commands.md`

**Description:**

`tests/notifications/test_telegram_commands.py` (EXTEND): add 17 happy-path + 17 error-path tests for the 17 command handlers (C13). New `tests/notifications/test_telegram_send_path.py` (NEW): foundation send-path tests per CC5.

`src/notifications/telegram_commands.py:574-645` `_cmd_council`: typed exceptions → categorized return strings (`cost_cap_exceeded`, `agent_timeout`, `llm_unavailable`, `no_quorum`, `invalid_question`) per C14.

CC3: convert top-4 high-traffic notify_* (`notify_trade_opened`, `notify_trade_closed`, `notify_eod_report`, `notify_weekly_digest`) to typed dataclass payloads.

`docs/operator-guide.md`: add §X.x 'Notification troubleshooting' tree (I13). Cover: bot is silent, bot token rotated, email digest stopped arriving, how to verify subsystem health (use `/api/notifications/health`).

`docs/telegram-commands.md`: document `send-test-email` CLI (I14).

PER-DELIVERABLE COMMIT-AND-PUSH:
- T21a (test extensions, replaces `<!-- T21a -->`).
- T21b (typed council + dataclass payloads, replaces `<!-- T21b -->`).
- T21c (operator-guide + telegram-commands docs, replaces `<!-- T21c -->`).

**Scope fence:**

Do NOT migrate non-top-4 notify_* (deferred to Sprint 5 `#SP5-notifications-dataclass-payloads-tail`). Do NOT touch policy/router (Task 22). Do NOT modify telegram.py beyond top-4 dataclass shape. Per-deliverable commits.

**Test strategy:**

1) 17 happy-path + 17 error-path tests for command handlers (34 new tests). 2) `test_telegram_send_path.py`: end-to-end send → API mock → assertion (1 foundation test). 3) `_cmd_council`: simulate `cost_cap_exceeded` → return 'cost cap exceeded; raise via /admin or wait for next window'. 4) Typed dataclass for `notify_trade_opened`: missing required field → TypeError at construction (NOT silent). 5) operator-guide §X.x renders cleanly; troubleshooting tree includes `/api/notifications/health` URL. **Net new tests: +35**.

---

### Task 22 — Group D — Mute / digest / routing policy (OPERATOR-DISCRETION GATE)

- **Wave**: W3 (Batch 7b — gated on operator confirmation)
- **Depends on**: [4d, 21]
- **Complexity**: high
- **Files in scope** (only if dispatched):
  - `src/notifications/router.py` (NEW)
  - `src/notifications/policy.py` (NEW)
  - `tests/notifications/test_router.py` (NEW)
  - `tests/notifications/test_policy.py` (NEW)
- **Files read-only**:
  - `src/notifications/__init__.py`
  - `src/notifications/telegram.py`
  - `config/settings.example.yaml`

**Description:**

**OPERATOR-DISCRETION GATE — Batch 7b dispatch.** PM must explicitly request operator approval BEFORE dispatching T22. Workflow (per reviewer item #14):

1. After T20 visual-verify checkpoint completes successfully, PM finalizes T21 dispatch (Batch 7a).
2. After T21 returns green, PM **surfaces T22 dispatch question to operator** via Telegram or AskUserQuestion: "Sprint 4 Group D (mute/digest/routing) — Y/N? Skipping opens follow-up `#SP5-notifications-routing-policy`."
3. **If approved** → dispatch T22 in parallel with sprint-closeout prep. T22's deliverables fold into T23.
4. **If declined** → skip T22 entirely; open `#SP5-notifications-routing-policy`; T23 proceeds without T22 in dependency graph.

**If approved**:

- New `src/notifications/policy.py` (~80 LOC): `quiet_hours` (start/end UTC), `weekend_suppression`, per-event severity → channel map.
- New `src/notifications/router.py` (~200 LOC): declarative `event_type → {channels, severity, prefix}` table. Refactor 25+ callers (already migrated to safe_send in T4) to call `route_event(event_type, **kwargs)` once.
- I5: drop redundant `is_telegram_enabled()` wrapping at all call sites; router checks once.
- I2: add digest scheduler — events flagged `digest-eligible` buffer for N minutes, flush as single message.
- `config/settings.example.yaml`: new keys.
- New tests: `tests/notifications/test_router.py`, `tests/notifications/test_policy.py`.

CHANGELOG.md: replace ONLY `<!-- T22 -->` placeholder (or leave placeholder unreplaced if T22 skipped — T23 will remove the placeholder during finalization).

**Scope fence:**

OPERATOR-GATE: do NOT proceed without explicit operator confirmation at dispatch. Do NOT modify safe_send wrapper internals (Task 3). Do NOT add new notify_* functions. Do NOT change `notifications_sent` table schema (Task 14).

**Test strategy:**

1) Quiet hours: 02:00-06:00 UTC, fire event at 03:00 → buffered; flushed at 06:01. 2) Weekend suppression: Saturday → all events except CRITICAL deferred to Monday digest. 3) Routing table: `event_type='cusum_alarm'` → `channels=['telegram','email']`. 4) Digest scheduler: 5 events in 30s window with `digest-eligible` flag → single combined message after flush interval. 5) `is_telegram_enabled()` removed from caller sites (sibling-search GREP). **Net new tests: +6** (only contributes to floor if dispatched).

**Sibling-search reminder:** see CLAUDE.md `feedback_review_sibling_search` memory.

**Per-deliverable commit-and-push:** this task ships ≥3 sub-deliverables (Group A/B/C/F-tied). Commit + push after each sub-deliverable lands green; do NOT bundle into a single mega-commit. Pre-push stale-base hook will refuse if base has advanced — rebase before each push.

---

### Task 23 — Sprint closeout — visual-verify gate + CHANGELOG + WON'T-FIX note + test count

- **Wave**: W3 (Batch 8)
- **Depends on**: [16, 17, 18, 19, 20, 21] + (T22 if dispatched)
- **Complexity**: medium
- **Files in scope**:
  - `CHANGELOG.md`
  - `docs/operator-guide.md`
  - `docs/audits/2026-05-07-sprint-4-cockpit-followups/visual-verify/post-merge-commitment.md` (NEW)
  - `docs/audits/2026-05-07-sprint-4-cockpit-followups/visual-verify/results.md` (NEW)
- **Files read-only**:
  - `config/known_violations.json`

**Description:**

Create `docs/audits/2026-05-07-sprint-4-cockpit-followups/visual-verify/post-merge-commitment.md` (NEW): per-finding commitment table mirroring Sprint 3 pattern. Capture `after/` screenshots of **the 11 priority pages enumerated in plan-§ "11 priority pages" plus the 2 NEW components (`25-kpi-pnl-card.png`, `26-notifications-health-panel.png`)**. Walk each CLOSE-class row; document PASS/FAIL/N-A in `visual-verify/results.md` (NEW). If any CLOSE row FAILs → dispatch hot-fix agent BEFORE marking Sprint 4 complete.

Finalize `CHANGELOG.md` sprint-base `[Unreleased]` block — verify EVERY task placeholder line has been replaced by a real bullet (or removed if T22 was skipped). T1's pre-allocation made each task PR a one-line replacement; T23 is mostly a verification + "remove unused T22 placeholder if skipped" step.

`docs/operator-guide.md`: ADD 1-paragraph note for `#SP4-settings-backend-float32-storage` WON'T FIX explanation per spec §3.9. (T15c separately added the NSSM-restart re-fire warning paragraph — T23 does NOT duplicate.)

Run `python -m pytest tests/ -q --timeout=60`. Assert pass count `>= 4798` (without T22) or `>= 4804` (with T22) — semantic `>=` per reviewer item #7. If delivered count differs, root-cause via per-task accounting in plan-§ "Test-floor accounting"; operator approves any deviation BEFORE merge.

Run `python -m pytest tests/test_repo_structure.py -v`; document new violations in `config/known_violations.json`.

Open Sprint 5 follow-up issues for any DEFER classes:
- `#SP5-notifications-routing-policy` (if T22 skipped)
- `#SP5-notifications-CC6-prefixing`
- `#SP5-notifications-dataclass-payloads-tail`

**Scope fence:**

Do NOT touch `src/version.py` (no version bump in Sprint 4). Do NOT modify governance docs (MASTER.md, CLAUDE.md). Do NOT bypass `test_repo_structure.py` via fix-not-acknowledge. Do NOT silently update test count target — operator must approve any deviation. CHANGELOG.md: replace ONLY `<!-- T23 -->` placeholder + remove unused placeholders.

**Test strategy:**

1) Run `python -m pytest tests/ -q --timeout=60` — assert pass count `>= 4798` (or `>= 4804` if T22 dispatched). If different, root-cause and adjust spec OR adjust test count BEFORE merge. 2) Run `python -m pytest tests/test_repo_structure.py -v` — document any new violations. 3) Visual-verify gallery linked from PR — 11 baseline pages + 2 new components covered. 4) `CHANGELOG.md` has all delivered groups + cockpit-#1-#11. 5) `operator-guide.md` has 2 paragraphs added: WON'T-FIX for `#SP4-settings-backend-float32-storage` (T23) + NSSM-restart re-fire warning for notification dedup migration (T15c). 6) `post-merge-commitment.md` PASS/FAIL/N-A walk completed. **Net new tests: 0** (closeout reporting).

**Per-deliverable commit-and-push:** this task ships ≥3 sub-deliverables (visual-verify after-screenshots + CHANGELOG finalization + WON'T-FIX paragraph). Commit + push after each lands green.

---

## Sprint workflow

- Worktree-isolated dispatch per task is **MANDATORY** (CLAUDE.md mandate; closes index-race + stash-pop hazard classes documented in PR #690 / Sprint 0 Wave 4-5 incidents).
- PM writes `.claude/agent-scope.json` per dispatch with `files_in_scope` exactly mirroring this plan's entries — pre-commit scope-check hook enforces (`scripts/hooks/pre-commit`).
- Pre-push stale-base hook refuses pushes from branches behind `origin/main`. Sequenced tasks must rebase before push.
- Each PR updates `CHANGELOG.md` under `[Unreleased]` by replacing **its own pre-allocated `<!-- TN -->` placeholder line**; no adjacent edits permitted. Sprint-closeout task verifies + removes unused placeholders.
- **Visual-verify rule** applies to any frontend Dashboard / KPIStrip / Layout / NotificationsHealthPanel edit (per CLAUDE.md `feedback_visual_verify_ui` memory). Static checks insufficient — render in browser before push.
- `test_repo_structure.py` disclosure: any new file/function size violation must be added to `config/known_violations.json` with rationale (CLAUDE.md disclosure requirement).
- Operator origin check before dispatch: `git fetch origin && gh pr list` to avoid racing operator on parallel work (CLAUDE.md `feedback_autopilot_origin_check` memory).
- **Operator-discretion gate (T22)**: PM dispatches Batch 7a (T21) first; pauses for operator confirmation BEFORE dispatching Batch 7b (T22). If declined, opens `#SP5-notifications-routing-policy` and proceeds to Batch 8.

## Reviewer dispatch (per CLAUDE.md table)

| Task touches… | QA | Security | Performance |
|---------------|----|----------|-------------|
| Notification subsystem (Group A: NameError, safe_send, alert plumbing — T2-T6) | ✓ | ✓ | — |
| API routes / cohort/_meta backend (T9, T10, T11, _desk_clause helper) | ✓ | — | ✓ |
| Frontend pages / KPIStrip / Layout edits (T12, T18) | ✓ | — | — |
| ESLint custom rule extension + lint guardrails (T16) | ✓ | — | — |
| CI / cloud-req guardrail (T7, T8) | ✓ | ✓ | — |
| Group B email subsystem (T11.5) | ✓ | ✓ (password env vs YAML) | — |
| Group C telegram template (T13) | ✓ | ✓ (HTML XSS) | — |
| Group E notifications observability + dedup (T14, T15) | ✓ | — | ✓ (notifications_sent index) |
| Calmar canonical migration (T17) | ✓ | — | ✓ (no perf regression) |
| Reconciliation (T19) | ✓ | — | — |
| Group F coverage + operator-guide (T21) | ✓ | — | — |
| Group D operator-discretion (T22) | ✓ (if executed) | — | — |
| Sprint closeout (T23) | — | — | — |

## Integration & closeout

- **Visual-verify gate at integration** — assemble screenshot gallery covering 11 baseline pages + 2 NEW components before sprint can be marked complete. Failed CLOSE rows trigger hot-fix dispatch BEFORE merge (mirrors Sprint 3 pattern in T23).
- **Test-floor enforcement (`>=`, not strict equality)**: pass count must be `>= 4798` (without T22) or `>= 4804` (with T22) at sprint closeout. Any deviation requires operator approval BEFORE merge.
- **CHANGELOG entry pre-allocation**: at sprint base, T1 pre-allocates one line per task with `<!-- TN -->` markers. Per-task PRs replace ONLY their own line. T23 finalizes + removes unused placeholders (e.g., `<!-- T22 -->` if T22 skipped).
- **Operator-guide post-merge follow-ups**: roll into the Sprint 4 closeout task (T23) or queue against TaskList #28. T15c also contributes operator-guide content (NSSM-restart re-fire warning).
