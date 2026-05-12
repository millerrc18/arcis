# Sprint 5 Wave A + Wave B — Combined Spec

**Sprint:** 5 (final). **Glidepath:** `docs/audits/2026-05-12-sprint-5-glidepath/glidepath.md`.
**Scope:** Wave A (cutover settlement) + Wave B (Sprint 4 close-outs). 8 tasks total.
**Goal:** Close 8 small backlog items in parallel, ~1 day total. Hold test count floor 3682.

## Wave A — Cutover settlement (4 tasks)

### T1 — Fix `_check_row_counts` cross-engine KeyError:0 at watch.py:1178 + AST sweep (task #92)

**Why:** Post-cutover, the watch loop's `_check_row_counts()` logs `[DB] Row count check failed: 0` because `conn.execute("SELECT COUNT(*) FROM shadow_trades").fetchone()[0]` does positional indexing. Against psycopg2's dict-like row_factory used by `connect_db()` on PG, `[0]` is a key lookup → `KeyError(0)`. The sanity-check that detects "shadow_trades unexpectedly empty" silently never fires. Same class as task #34 (KeyError:0 in Wave 5 orphan-guard) which was previously fixed but didn't sweep this site.

**Files in scope (write):**
- `src/scheduler/watch.py` (line 1178 — single-line fix)
- `tests/test_no_fetchone_int_index_in_pg_unsafe_files.py` (NEW) — AST sweep guarding against `.fetchone()[<int>]` patterns in files reachable from `connect_db()` on PG
- `tests/test_scheduler_watch.py` OR `tests/test_check_row_counts_cross_engine.py` (NEW or extend) — regression-lock test asserting the fix path

**Files in scope (read-only):**
- `src/utils/db.py` (verify row_factory configuration for PG path)

**Fix mechanism:** Replace `row[0]` with cross-engine-safe access. Two acceptable patterns:
1. `count = row[0] if not isinstance(row, dict) else row['count']` (defensive)
2. Use `cur.description` to find column index, OR alias the column: `SELECT COUNT(*) AS n FROM shadow_trades` and access `row[0] if tuple else row['n']`

Pick option 1 (matches the pattern used in task #34's fix; minimal change).

**Scope fence:**
- Do NOT modify `src/utils/db.py` row_factory behavior
- Do NOT touch other `_check_*` functions in watch.py
- Do NOT introduce a generic helper if a 1-line inline fix suffices
- AST sweep test must be SCOPED to files reachable from `connect_db()` on PG (use the connect_db discipline allowlist from T6 of cutover-rectification at `tests/test_connect_db_discipline.py` as the input set)

**AST sweep requirements:**
- Walk `src/` for `.py` files in the PG-reachable set (per `tests/test_no_sqlite_isms_in_pg_safe_files.py` allowlist)
- For each file, AST-parse and find `Call` nodes where:
  - The `.func` is an `Attribute` with `attr='fetchone'`, AND
  - The parent expression is a `Subscript` with an integer `value` (i.e., `.fetchone()[<int>]`)
- Collect violations → if any, fail the test with file:line list
- Add a self-test using `tmp_path` with a synthetic violation (matching T6's pattern)
- ALLOWLIST: files that are SQLite-only-by-design (per the existing allowlist used in `test_no_sqlite_isms_in_pg_safe_files.py`)

**Test strategy:** New test must pass on the fixed watch.py:1178. Self-test must catch a synthetic violation. Existing `tests/test_connect_db_discipline.py` 17/17 must stay green.

**Acceptance:**
- watch.py:1178 fix lands; the existing `[DB] Row count check failed: 0` warning no longer fires (verified by re-reading runtime arcis.log post-impl OR by an inline pytest that exercises the cross-engine path)
- New AST sweep test catches `.fetchone()[<int>]` patterns; current src/ produces a known-violation list OR is clean
- If new violations surface, the test should LOUDLY fail with file:line — DO NOT silently fix or grandfather them (operator decides per-violation)

---

### T2 — Document PYTHONUTF8=1 training-env requirement (task #77)

**Why:** PYTHONUTF8=1 is required for the TRL training pipeline (per inline note in `docs/operator-guide.md` near line 1671). Currently undocumented as an operator-runbook item; operators won't know to set it when bootstrapping a fresh machine. Surfaced as a gap during the cutover-rectification sprint when ArcisWatchLoop env was inspected and PYTHONUTF8 was absent — operator confirmed it's set system-wide.

**Files in scope:**
- `docs/operator-guide.md` (add section)

**Scope fence:**
- Do NOT modify code (this is docs-only)
- Do NOT add a startup-check for PYTHONUTF8 (out of scope for this small task; if needed, file as a follow-up)
- Do NOT add to other docs files (single source of truth in operator-guide.md)

**Content requirements (the new section must include):**
1. **What:** `PYTHONUTF8=1` Python env var
2. **Why:** TRL training pipeline encodes/decodes corpus JSONL in UTF-8; on Windows without this var, Python's default encoding (cp1252 / Windows-1252) corrupts non-ASCII chars and silently breaks training
3. **Where to set it (3 places):**
   - NSSM ArcisWatchLoop service env (AppEnvironmentExtra) — for watch-loop-spawned training subprocesses
   - User-scope env var (`[Environment]::SetEnvironmentVariable('PYTHONUTF8','1','User')`) — for operator shell invocations of `python -m src.main` etc.
   - System-scope env var if multi-user box (out of scope for single-operator box)
4. **How to verify:** `python -c "import sys; print(sys.flags.utf8_mode)"` should return `1` (truthy)
5. **Cross-link to existing env-var inventory at line 1671** to keep one canonical list

**Placement:** Insert as new subsection in the existing operator-guide environment-variable section, OR add an explicit "Training environment requirements" subsection if no current home matches. The dual-GPU spec just shipped (d19a782) has an analogous structure — copy that style.

**Acceptance:**
- New section reads cleanly to an operator bootstrapping a fresh Windows machine
- Cross-link to line 1671 env-var inventory works (anchor or relative reference)
- Operator can find this section via Cmd+F for `PYTHONUTF8`

---

### T3 — known_violations.json render_sync.py size update follow-up (task #26)

**Why:** Task #26 originally tracked: "separate PR for known_violations.json render_sync.py size update (1112 → 1359)". BUT — `render_sync.py` was DELETED in Phase 3-revised (SP5 §J / PR #1055). So the entry is now stale. The right move is to REMOVE the `src/sync/render_sync.py` entries from `known_violations.json` (whichever subsection has them: `oversized_files` and/or `oversized_functions`).

**Files in scope:**
- `config/known_violations.json` (remove render_sync.py entries)

**Scope fence:**
- Do NOT touch other entries in known_violations.json (those are separate task scopes — #27 handles its own)
- Do NOT re-introduce render_sync.py if the file is genuinely gone (verify with `ls src/sync/render_sync.py` — should not exist post-Phase-3-revised)

**Mechanism:**
1. Verify `src/sync/render_sync.py` is gone (`ls src/sync/`)
2. Grep known_violations.json for `render_sync` — capture every occurrence
3. Remove each line (preserving JSON validity)
4. Re-run `python -m pytest tests/test_repo_structure.py -v` to confirm no NEW violations surface (any pre-existing failures unrelated to render_sync are task #27's domain)

**Acceptance:**
- `grep -c render_sync config/known_violations.json` returns 0
- JSON file remains valid (`python -c "import json; json.load(open('config/known_violations.json'))"`)
- `tests/test_repo_structure.py` failures count matches the post-removal baseline (3 known failures from rectification sprint stay: backtester.py size, news.py:fetch_news_sentiment, orphan TODOs — those are #27's scope)

---

### T4 — Pre-existing test_repo_structure.py violations (task #27)

**Why:** Three pre-existing violations were documented during the cutover-rectification sprint (PR #1056) and have been showing up in every Wave 1 agent's stderr ever since:
1. `src/evaluation/backtester.py` is 408 lines (max 400) — test_no_file_over_400_lines
2. `src/data_enrichment/news.py:fetch_news_sentiment` is 77 lines (max 60) — test_no_function_over_60_lines
3. orphan TODOs in src/ — test_todos_have_issue_numbers

**Decision needed:** real-fix vs grandfather. Per operator strict-rigor preference (`feedback_strict_rigor_no_handwave`), real-fix is preferred when small. Per `feedback_fix_before_trade`, default fix-now.

**Recommendation per finding:**
- **Finding 1 (backtester.py 408 lines):** Small (8 lines over). Try a real refactor first — extract a small helper to a sibling file (e.g., `src/evaluation/backtester_helpers.py`). If the cleanest extraction would be cosmetic, grandfather with operator-visible rationale in known_violations.json.
- **Finding 2 (news.py:fetch_news_sentiment 77 lines):** 17 lines over. Extract a helper from inside the function (e.g., the article-text aggregation loop). Real refactor preferred.
- **Finding 3 (orphan TODOs):** Just need issue numbers. Grep TODOs in src/ that lack `(#NNN)` suffix, file each as a GitHub issue (or attach to an existing one), update the comment to include the issue number.

**Files in scope:**
- `src/evaluation/backtester.py` (refactor for #1) + sibling helper if extracted + tests (regression-lock)
- `src/data_enrichment/news.py` (refactor `fetch_news_sentiment` for #2) + tests
- ALL `src/**/*.py` files with orphan TODOs (just comment updates) — locate via grep then update
- `config/known_violations.json` ONLY IF a finding is grandfathered after real-fix attempt fails

**Scope fence:**
- Do NOT touch any other oversized file/function outside the 3 listed (other violations are out of scope; file as follow-ups if found)
- Do NOT silently grandfather without trying real-fix first (per strict-rigor)
- Do NOT modify CI thresholds (400 lines, 60 lines) — those are project-wide policy

**Test strategy:**
- After refactor, `python -m pytest tests/test_repo_structure.py -v --timeout=60` should pass all 3 of the named tests
- Run targeted tests for backtester.py + news.py modules to confirm no regressions

**Acceptance:**
- All 3 `test_repo_structure.py` named tests pass OR have an explicit grandfather entry in known_violations.json with `rationale` field explaining why
- No test failures introduced in `tests/test_backtester*.py` (if exist) or `tests/test_news*.py`
- Test count floor 3682 holds (new tests OK; net deletes prohibited)

---

## Wave B — Sprint 4 close-outs (4 tasks)

### T5 — Extend `_html_escape` to notify_risk_alert + notify_exposure_alert (task #65)

**Why:** Sprint 4 T13 added `_html_escape()` to the Telegram notification path but only wired it into `notify_account_alert` (and a couple others). The risk-alert and exposure-alert paths still concatenate raw strings into Telegram HTML-mode messages, vulnerable to:
- Display corruption if a ticker or message contains `<`, `>`, `&`
- Telegram message rejection (HTTP 400) on malformed HTML
- Potential operator-side confusion if user-controlled text gets injected (e.g., a position-detail string from broker API)

**Files in scope:**
- `src/notifications/telegram.py` (extend escape coverage in `notify_risk_alert` + `notify_exposure_alert`)
- `tests/test_notifications_telegram.py` OR equivalent (extend with 2 new tests per function: clean-input round-trip + HTML-injection-attempt is escaped)

**Scope fence:**
- Do NOT change `_html_escape()` implementation itself (already correct from Sprint 4 T13)
- Do NOT extend to other notification functions outside the 2 named — that's a future sweep if needed
- Do NOT change the public signatures of `notify_risk_alert` / `notify_exposure_alert`

**Mechanism:** For each of the 2 functions, identify every f-string or string-concat that interpolates external-source text (ticker, broker message, user-input) into the Telegram-HTML-mode payload. Wrap each interpolated value with `_html_escape()`. Static-string content (headers, separators, fixed labels) doesn't need escaping.

**Test strategy (4 new tests minimum):**
- `test_notify_risk_alert_escapes_ticker_with_special_chars` — ticker like `<RISKY>` renders as `&lt;RISKY&gt;`
- `test_notify_risk_alert_clean_input_round_trips` — normal `AAPL` renders as `AAPL` (no double-escape)
- `test_notify_exposure_alert_escapes_position_detail_with_html` — broker-supplied detail with `<` `>` `&` is escaped
- `test_notify_exposure_alert_clean_input_round_trips` — normal detail unchanged

**Acceptance:**
- 4 new tests pass
- Test floor stays ≥3682
- `_html_escape` import in telegram.py is the same one used by `notify_account_alert` (no duplicated helper)

---

### T6 — Negative total_pnl_dollars test fixture in KPIStrip (task #66)

**Why:** Sprint 4 T12 introduced `total_pnl_dollars` rendering in the KPIStrip component (positive values rendered with green color, sign-prefix `+`). Negative case was implemented (red color, sign-prefix `−` per Unicode minus or `-`) but NOT covered by a test fixture. Edge cases that could silently regress:
- Negative zero (`-0.00`) — should render as `0.00` (no sign), not `−0.00`
- Large negative (`-12345.67`) — should render with comma separator + red color
- Exact zero (`0.00`) — should render neutral (no color, no sign)

**Files in scope:**
- `frontend/src/components/dashboard/KPIStrip.test.jsx` (add new test cases; existing file has positive-case coverage)

**Files read-only:**
- `frontend/src/components/dashboard/KPIStrip.jsx` (verify the current render logic to know what to assert)

**Scope fence:**
- Do NOT modify KPIStrip.jsx (the implementation is presumed correct per T12; we're adding test coverage only)
- IF a test reveals a bug, FILE IT as a follow-up — don't silently fix
- Do NOT add tests for other KPIs in the strip (focus is total_pnl_dollars only)

**Test cases (minimum 3 new):**
1. `KPIStrip renders negative total_pnl_dollars with red color and minus sign` — input `-1234.56`, assert color class is the red variant + text matches `-$1,234.56` (or equivalent based on actual format)
2. `KPIStrip renders zero total_pnl_dollars as neutral` — input `0`, assert no color class beyond neutral + text matches `$0.00`
3. `KPIStrip renders large negative total_pnl_dollars with thousands separator` — input `-12345.67`, assert text matches `-$12,345.67`

**Test framework:** Vitest + @testing-library/react (per existing KPIStrip.test.jsx pattern). Confirm before writing.

**Acceptance:**
- 3 new test cases pass via `cd frontend && npm test KPIStrip`
- No regressions in existing positive-case tests
- ESLint clean (`cd frontend && npm run lint`)

---

### T7 — Wire `write_heartbeat()` into watch-loop scheduler (task #67)

**Why:** Sprint 4 T15 added `write_heartbeat()` in `src/notifications/platform_events.py` as a notifications-side liveness signal (writes a row to `platform_events` table or similar). The function was implemented but never wired into the watch loop's periodic cycle. Currently the watch loop has a `watchdog.txt` file-based heartbeat (per `src/scheduler/watch.py:1407` "Write heartbeat every iteration (~60s)") but no DB-side heartbeat for the dashboard to read.

**Files in scope:**
- `src/scheduler/watch.py` (add `write_heartbeat()` call in the existing heartbeat path or scheduler cadence)

**Files read-only:**
- `src/notifications/platform_events.py` (verify `write_heartbeat()` signature + side effects)

**Scope fence:**
- Do NOT change `write_heartbeat()` itself (Sprint 4 T15 implementation is presumed correct)
- Do NOT introduce a NEW heartbeat cadence — wire into existing `~60s` iteration or the periodic-status-heartbeat-60min path (operator preference: every iteration vs every 60min)
- Do NOT remove the file-based `watchdog.txt` write (both signals coexist)

**Wire-in mechanism:**
1. Read `watch.py` around lines 1399-1407 (initial heartbeat) and 1407 (per-iteration heartbeat) — identify the right call site
2. Add `from src.notifications.platform_events import write_heartbeat` (lazy import inside the function preferred to keep module load light)
3. Call `write_heartbeat()` inside a `try/except` block — failures must NOT crash the watch loop (notifications side is best-effort)
4. Log at DEBUG level on success, WARNING on failure

**Cadence decision:** Default to every iteration (matches existing `watchdog.txt` cadence — ~60s). If platform_events table has high write cost, fall back to every 60min (matches `_print_status_heartbeat` cadence at watch.py:1814).

**Test strategy:**
- `tests/test_scheduler_watch.py` extend: 1 new test that mocks `write_heartbeat` and asserts it's called within the watch-loop iteration loop
- `tests/test_platform_events.py` (if exists) — verify the existing tests still pass

**Acceptance:**
- 1 new test passes (mock + assert called)
- Existing `tests/test_scheduler_watch*.py` pass
- Test floor ≥3682
- Live verification (operator-side, post-merge): query `platform_events` table; should see heartbeat row count growing on the cadence chosen

---

### T8 — Mirror #44 kwarg assertions to test_bracket_safety.py (task #48)

**Why:** Task #44 (completed) added kwarg-pattern assertions to `tests/test_bracket_orders.py` — 12 occurrences confirming bracket-order submission uses correct `take_profit=` / `stop_loss=` kwargs (not positional or wrong-named kwargs). `tests/test_bracket_safety.py` covers safety-net behavior (cancel-before-close, fail-soft) but only has 6 kwarg-related assertions. There's a gap: safety-net paths that re-submit a bracket order could silently use wrong kwargs and the test wouldn't catch it.

**Files in scope:**
- `tests/test_bracket_safety.py` (extend with mirrored kwarg assertions)

**Files read-only:**
- `tests/test_bracket_orders.py` (template — copy the assertion pattern)
- `src/shadow_trading/executor.py` OR `src/trading/alpaca_broker.py` (verify which bracket-submission paths exist in safety-net code)

**Scope fence:**
- Do NOT modify production code in `src/shadow_trading/` or `src/trading/` (if a real bug surfaces from the new tests, file as follow-up — don't silently fix)
- Do NOT change `test_bracket_orders.py` (already has its kwarg coverage)
- Match the existing `test_bracket_safety.py` style (don't introduce a new pytest pattern)

**Mechanism:**
1. Identify the bracket-submission call sites in safety-net paths (cancel-before-close, broker-exception recovery, OCO sibling-cancel — referenced by test_bracket_safety.py)
2. For each: confirm a test exists that mocks the submission and exercises the path
3. For each existing test where the mock is asserted with `assert_called_with(...)`: extend the assertion to check the kwargs explicitly (`take_profit=`, `stop_loss=`, `time_in_force=`, etc.)
4. Add NEW tests if a safety-net path has no kwarg-coverage today

**Test strategy:** Net add — at least 6 new kwarg-level assertions (matching the gap from `test_bracket_orders.py`'s 12). Could be net 3-6 new test functions OR extending existing assertions.

**Acceptance:**
- `grep -c "kwargs\|kwarg\|call_args\|assert_called_with" tests/test_bracket_safety.py` increases by ≥6
- All new tests pass; no regressions in existing test_bracket_safety.py
- Test floor ≥3682

---

## Cross-wave acceptance

- **All 8 tasks closed** (real-fix or grandfathered with operator-visible rationale per T4)
- **Test count floor ≥3682** held; net adds expected (~10-20 new tests across the 8 tasks)
- **No new test_repo_structure violations** introduced
- **AST scanner (T1 new test) + connect_db_discipline (existing)** both stay green
- **CHANGELOG.md `[Unreleased]`** entries appended per task (or one consolidated wave entry)
- **One sprint PR** (or two — one per wave — operator preference; PM defaults to one consolidated PR per Sprint 4 / Sprint 3 precedent)
- **Visual-verify required for T6 (KPIStrip)** — operator preference per `feedback_visual_verify_ui`: frontend Dashboard/KPIStrip edits must be browser-rendered before push. PM dispatches frontend developer with visual-verify discipline.

## Out of scope

- **Wave C+ tasks** — data integrity / notifications routing / dev tooling (separate waves per glidepath)
- **Real refactor of any task #27 finding that requires more than ~30 min of work** — grandfather instead with operator notification
- **Changes to `_html_escape()` implementation itself** (Sprint 4 T13 already shipped)
- **Schema changes** (none of the 8 tasks touch tables)
- **Walk-forward framework anything** — post-Sprint-5 separate track

## Operator memory pointers

- `feedback_strict_rigor_no_handwave` — worktree isolation, sibling-search, no-skip/weaken/bypass
- `feedback_review_sibling_search` — when reviewer/fix agent finds bug at file:line, GREP file for same anti-pattern at other lines (load-bearing for T1 AST sweep)
- `feedback_visual_verify_ui` — T6 KPIStrip browser-render required
- `feedback_fix_before_trade` — defaults to fix-now (relevant for T4 decisions)
- `feedback_use_coding_team_skill` — invoke `arcis:code` PM orchestrator (this dispatch)
- `feedback_pm_dispatch_path_verification` — Glob-verify file paths before writing dispatch briefs (PM did this pre-spec)
- `feedback_worktree_env_drift` — worktrees don't carry .env; tests must be hermetic
- `reference_worktree_base_default` — worktrees branch from origin/main; PM cherry-picks if needed

## Expected sprint output

- **PR(s) opened against `main`** with all 8 tasks closed
- **Per-task scorecard** in PR body (T1 through T8)
- **Wave A+B closeout entry** in CHANGELOG.md `[Unreleased]`
- **Test count delta** disclosed in PR body
- **Visual-verify screenshot** attached to PR (T6 KPIStrip negative-pnl rendering)
