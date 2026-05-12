# Sprint 5 Closeout Plan — design-team brief

**Goal:** Produce a comprehensive design spec + implementation plan that lets the PM agent autonomously and rigorously drive Sprint 5 to its closeout PR, without requiring operator input mid-flight on design choices.

**Sprint context:** Sprint 5 is the **final sprint** before walk-forward framework implementation becomes the active post-Sprint-5 track. No "Sprint 6" exists by design — all remaining backlog lands in Sprint 5 or is explicitly scoped-out.

**Glidepath authoritative source:** `docs/audits/2026-05-12-sprint-5-glidepath/glidepath.md`. Wave A + Wave B are CLOSED (PR #1058 merged at `25e9e58`). Two follow-up PRs from operator review of #1058 also merged: #1059 `_scalar` helper consolidation (`198bc1f`) + #1060 `PostgresConnectionWrapper.execute()` cursor wrapping (`6a2fcbb`). Origin/main is at `6a2fcbb` at brief time.

---

## Scope of the design spec

### 1. Wave D — Notifications routing policy (task #69) — REQUIRES DESIGN

The largest single remaining piece. Currently a sketch in the glidepath (§Wave D); needs full spec.

**Requirements to specify:**

- **Current notifications inventory** — 38 `notify_*` functions per Sprint 4 T3 baseline at `src/notifications/telegram.py`. All flow through `safe_send(event_type, **kwargs)` central dispatcher (Sprint 4 T3) with bot-token redaction + per-event-type dedup via `notifications_dedup` table. Email path lives at `src/email/digest_builder.py` + `src/email/notifier.py`.
- **Mute rules per channel** — by time-of-day (e.g., quiet hours 22:00–06:00 ET), by severity (low/medium/high/critical), by event_type (e.g., mute `regime_alert` during pre-market).
- **Digest mode** — bundle low-severity events into 5-min / 15-min / hourly summaries instead of per-event firing. Operator currently has `--email-mode digest` flag in `src/main.py:startup` — design should align with that prior art.
- **Routing layer** — operator-defined "event_type X goes to channel Y" config. Channels: telegram, email, both, none-silent. Config format: YAML extension under `config/settings.local.yaml` ideally, or a new dedicated file.
- **Sibling integration** — tasks #93 (`notify_regime_alert` HTML-escape) + #94 (`notify_streak_alert` HTML-escape) are natural Wave D scope (touch `src/notifications/telegram.py`). Fold them in.

**Spec must cover:**
- Config schema (with validation rules + default values)
- Migration path for existing `safe_send` callers (likely backward-compat: defaults preserve current behavior)
- Test strategy: config validation, mute-rule arithmetic, digest-batching state machine, routing-table interpretation
- Data model: any new tables needed (e.g., a `notifications_digest_queue` for pending-bundle events)?
- Security: config-loading attack surface (already covered by `safe_send`'s SECURITY docstring per Sprint 4 T3-fix)
- Observability: how does operator inspect "what would fire if I set this config?"

**Default value recommendations** (design team decides; operator overrides if they want):
- Quiet hours: 22:00–06:00 ET
- Digest cadence: hourly for severity=low, immediate for severity≥medium
- Default routing: telegram for all (current behavior — backward-compat)

### 2. Wave C — Data integrity hardening (5 tasks) — task-level decomposition

Per glidepath: "C must complete before D (typed exceptions + FK groundwork)." So Wave C is the sequencing bottleneck.

For each task, the design spec must include:
- **Files-in-scope** (paths)
- **Files-read-only** (caller context the developer reads but doesn't modify)
- **Scope fence** (one-line "this task is done when X")
- **Test strategy** (existing tests touched + new tests added)
- **Reviewer dispatch** (QA always; Security if config/auth touched; Performance if hot-path)

**Tasks:**
- **#54** — Wire `src/api/cloud_routes/kpis.py:91` to pass `dates` + `directions` arrays to `_compute_promotion_gate_kpi(returns, dates, directions)`. Currently passes only `returns`. Sprint 2 T3 follow-up.
- **#56** — Add `strategy_id` FK column to `shadow_trades` table + wire into methodology gate filter at `src/methods/promotion_gate.py`. Schema change in `src/schema/registry.py` + migration via `render_migrate.py`. Forward-compat for multi-strategy attribution.
- **#68** — Consolidate council typed exceptions into new `src/council/errors.py` module. Currently scattered as ad-hoc `RuntimeError`s across `src/council/{engine,agent_data,context,parsing,protocol}.py`. Mid-size refactor; create typed hierarchy `CouncilError(Exception)` → `CouncilParseError`, `CouncilTimeoutError`, etc.
- **#45** — Operator-manual-intervention drift detection. New detector in `src/diagnostics/` that flags when broker positions diverge from local DB state for > N minutes (configurable). Surfaces via Telegram alert + dashboard widget.
- **#47** — Triage findings from task #46 Telegram + email sweep audit. Read `docs/audits/2026-05-07-telegram-email-sweep-audit/` artifacts; file 1 sub-task per finding OR fold all into Wave D scope if findings are routing-related.

### 3. Wave E — Dual-GPU utilization (task #91) — implementation decision

Design spec already landed at `docs/audits/2026-05-12-dual-gpu-strategy-a-spec/` (committed as `docs(sp5-91): dual-GPU workload separation design spec` at `d19a782`). RTX 3060 (inference) + RTX 3090 (training+council).

**Open decision (recommend default + alternative):**
- Default: **design-only, defer implementation to post-sprint** (per glidepath §Wave E "Spec stays 'ideation deliverable'"). Rationale: no current bottleneck demands it; reverse-able decision.
- Alternative: implement in Sprint 5 if low-blast-radius. Risk: 3060 driver/CUDA/VRAM-detection surprises.

### 4. Wave F — Dev tooling / test infrastructure (3 tasks) — approach specs

- **#15** — Pre-merge stale-base hook (server-side). Complements client-side `pre-push` hook (per `scripts/hooks/pre-push`). Implementation: GitHub Actions workflow on `pull_request.synchronize` that checks `merge-base(HEAD, main) == origin/main HEAD`; sets a status-check that blocks merge when stale.
- **#86** — Speed up full test suite (chronic agent timeout root cause). Hypothesis: `tests/test_cloud_requirements_imports.py` is the slowest test (uses fresh-env pip install per case). Investigate + restructure: parameterize within one env install, OR cache the venv across cases.
- **#87** — Provision local test PG for agents. Currently 3 fixtures hardcode `DATABASE_URL=postgresql://test:test@localhost/halcyon`. Refactor to use `docker-compose.test.yml` ephemeral container in `conftest.py` session scope.

### 4b. NEW findings (surfaced 2026-05-12 mid-flight, after surface scan)

**Finding F1 — 2 more T1ext-missed cross-engine sites** (10:09–10:13 ET log inspection)
- `src/scheduler/watch.py:1006` in `_refresh_live_prices`: `tickers = [r[0] for r in rows if r[0]]` — raised `KeyError(0)` on PG dict rows, broke live-prices refresh
- `src/shadow_trading/executor.py` (line TBD in `open_shadow_trade_with_reason`): same pattern, broke MR-WRAPPER trade-opening (`GOOG rejected: internal error: KeyError: 0`)
- Root cause: T1ext's AST scanner at `tests/test_no_fetchone_int_index_in_pg_unsafe_files.py` matches `.fetchone()[N]` only. The `[r[N] for r in fetchall()]` pattern (list comprehension over fetchall results) is invisible to the existing scanner.
- Already fixed structurally by PR #1060 (CompatRow wrapping) but the running watch loop was on pre-#1060 code until ~10:41 ET restart.
- **Design requirement**: Wave C+ task #100's scanner extension MUST cover the `[r[N] for r in fetchall()]` pattern in addition to extending coverage to `scripts/`. Specifically: detect any `Subscript(value=Name, slice=Constant(int))` inside a `comprehension.iter` chain that resolves to a `fetch*()` call.

**Finding F2 — 95 `system_event` notifications with `error_msg='telegram down'` since 2026-05-11**
- All have identical error_msg "telegram down" — captured by `safe_send`'s `except (urllib3.HTTPError, requests.RequestException, socket.timeout, OSError)` block at `src/notifications/telegram.py:1300-1310`
- Spread across ~36 hours of uptime; ~2–3/hour rate suggesting transient network blips rather than sustained outage
- Other Telegram traffic (294 system_event ok + 168 exposure_alert ok + ...) continues to succeed concurrently, confirming these are intermittent
- **Design requirement** (Wave D add-on): retry policy with exponential backoff for safe_send network failures (currently no retry — single attempt then write status='failed'); escalation-on-N-consecutive-failures (e.g., 5 in 10 min) to email channel so operator sees the actual outage signal, not just per-failure noise
- **Design requirement** (Wave D add-on): "alert silence" detector — if the watch loop hasn't successfully sent a Telegram notification in X min during market hours, surface via dashboard widget + write to platform_events for forensic trail. The 18-hour live_prices gap this morning didn't trigger any operator notification — that's a structural blind spot

### 5. Mini-tracker triage decisions

Filed during Sprint 5 work; need disposition in this design spec:
- **#93, #94** — Already scoped into Wave D above. Note in spec.
- **#96** — `platform_events` table-vs-code drift. 4 files reference, registry has only a comment, neither SQLite nor PG has the table. Recommend: **fix in Wave C alongside #56 schema work** (add TableDef to registry, migrate). OR scope-out if the dead-code branch can be removed instead. Design team picks.
- **#97** — `alpaca_adapter.py` split (425L). Pre-existing sentinel test `test_known_violations_no_alpaca_adapter_entry` asserts file MUST NOT appear in known_violations.json; T4 added it anyway to satisfy `test_no_file_over_400_lines`. Recommend: **scope-out the file split as post-sprint refactor; this sprint's PR-1058 already deleted the stale sentinel test**. Or did it? Design team verifies + decides.
- **`_scalar` reversal post-#1060** — Now possible since `PostgresConnectionWrapper.execute()` returns CompatRow. Recommend: **include in Sprint Close PR as cosmetic cleanup** (mechanical revert of 82 sites). Cost: ~30 min. Benefit: removes a now-redundant helper from the codebase.

### 6. Sprint Close PR contract

Define exactly what goes in the closeout PR:
- **Aggregated CHANGELOG** — collapse all Wave A–F entries into a single `## [vX.Y.Z] — 2026-05-XX — Sprint 5 close` section. Move from `[Unreleased]` to versioned section.
- **`src/version.py` bump + git tag** — decision: minor (0.X.0) or patch (0.X.Y). Recommend **minor** because Sprint 5 ships new behavior (notifications routing, drift detection, FK schema additions).
- **Roadmap update** — Sprint 5 marked complete; walk-forward becomes active post-Sprint-5 track. NOTE: surface scan confirmed `docs/roadmap.md` does NOT currently exist — decide: create new file with established structure, OR fold roadmap update into `docs/operator-guide.md` "Sprint history" section. Design team picks.
- **Operator-guide append** — post-Sprint-5 state summary: notifications routing config location, drift-detection alert format, dual-GPU status (deferred), known follow-ups.
- **Test floor target** — current 3682; project final after Waves C+D+F additions (~+50–100 new tests).
- **Visual-verify gate scope** — which dashboard surfaces affected? Notifications widget (Wave D), platform-events panel (#96 if fixed), drift-detection widget (Wave C #45).
- **Stale-canon refresh** — `docs/audits/known-pre-existing-failures.md` (34 documented vs ~89 real on main). Refresh or document the drift?

### 7. PR boundary decision

Glidepath §Success criteria: "One operator-visible PR per Wave (6 total + Close) for clean review surface." Design team confirms or proposes alternative (one giant PR vs per-wave).

Recommend default: **per-wave PRs** (better review surface, smaller blast radius per merge, matches recent successful #1058/#1059/#1060 cadence).

### 8. Risk register update

Original glidepath listed 4 landmines:
1. Test suite chronic timeout (#86) — STILL APPLIES, intentionally not fixed first
2. Cross-engine row-factory bugs (#92) — RESOLVED via T1 + T1ext (PR #1058)
3. Wave D scope creep — STILL APPLIES, this spec is the mitigation
4. Wave E hardware drift — STILL APPLIES if impl decision is "implement"

Add any new landmines that surfaced during Waves A+B work:
- PG schema completeness gap (P0 incident this session, resolved by render_migrate + sqlite_to_pg_migrate)
- CRLF/LF normalization noise in mechanical sweeps (CLAUDE.md §7) — affects PR review readability
- platform_events orphan reference (now tracked as #96)

---

## Constraints

- **Sprint 5 is final** — no SP6 catch-all. Each task must close in Sprint 5 OR be explicitly scoped-out with rationale in the spec.
- **Walk-forward framework** is out of scope (post-Sprint-5 separate track).
- **Test floor** — minimum 3682 tests, zero failures at baseline (per CLAUDE.md).
- **PG schema completeness** — Sprint 5 §J5/§J6 one-DB invariant: `ARCIS_PG_CUTOVER_ENABLED=1` routes ALL `connect_db()` to PG. Schema-vs-code drift now equals runtime exceptions. Any new tables must be declared in `src/schema/registry.py` AND migrated via `render_migrate.py`.
- **CHANGELOG discipline** — every PR updates `[Unreleased]` (CLAUDE.md).
- **Worktree isolation** — parallel agent dispatches use `isolation: "worktree"` (CLAUDE.md §Parallel Agent Dispatch).
- **Sibling-search rule** — when fixing file:line, GREP for same pattern at other lines (memory `feedback_review_sibling_search`).

## Out of scope (explicit)

- Walk-forward framework implementation
- New ML model architectures (Sprint 5 doesn't ship model changes)
- Frontend redesign (Sprint 5 may touch components but not architecture)
- Render infrastructure (cutover to local PG already complete)

## Success criteria for this design spec

- [ ] Wave D notifications-routing-policy has a config-schema-level spec + state-machine diagrams for digest batching
- [ ] Each of Wave C's 5 tasks has paragraph-level decomposition (files, scope, test, reviewer)
- [ ] Wave F's 3 tasks have approach-level specs
- [ ] Mini-tracker triage decisions are documented per-tracker with rationale
- [ ] Sprint Close PR contract enumerates EVERY artifact that lands (CHANGELOG section, version bump, tag, roadmap, operator-guide)
- [ ] Operator decision matrix is structured for one AskUserQuestion batch (max 4 questions)
- [ ] Risk register is updated with new landmines from this session

## Files to ground the spec against

- `docs/audits/2026-05-12-sprint-5-glidepath/glidepath.md` — authoritative wave plan
- `docs/audits/2026-05-12-sprint-5-wave-ab/spec.md` — Sprint 5 Wave A+B spec (already executed)
- `src/notifications/telegram.py` — 38 notify_* functions + safe_send central dispatcher
- `src/email/digest_builder.py` + `src/email/notifier.py` — email path
- `config/settings.local.yaml` — existing operator config shape
- `src/methods/promotion_gate.py` — #56 + #54 destination
- `src/schema/registry.py` — schema additions for #56, #96 (if not scoped out)
- `src/diagnostics/` — #45 home
- `src/council/{engine,agent_data,context,parsing,protocol}.py` — #68 refactor scope
- `scripts/hooks/pre-push` — #15 server-side complement reference
- `tests/test_cloud_requirements_imports.py` — #86 likely root cause
- `tests/conftest.py` — #87 docker-compose integration point
- `CLAUDE.md` — governance + test floor + worktree discipline
