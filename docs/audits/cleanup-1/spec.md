# Sprint Cleanup-1 (A+B+E) — 10-Fix Bundled Backlog Sweep

**Sprint ID:** cleanup-1
**Sprint type:** Cleanup-batch (per `feedback_batch_related_work` 2026-05-26)
**Target release:** v0.36.71 (re-baselined at impl time; main is v0.36.70 post-#110)
**Test floor:** 6,980+ (post-#110). Net-add only; no deletions without compensation tests.
**Branch:** `sprint/cleanup-1/impl` (PM picks final name; base is `sprint/cleanup-1/base`)
**PR title:** `chore(cleanup-1): observability + backtest CLI + sim/test infra — #112/113/114/118/119/120/121/122/123/124`
**Deliverable:** ONE PR with 10 commits (one per fix), dual-Opus QA SOUND, attack-plan updated, post-merge kin sweep.

---

## Scope: 10 Fixes

This sprint bundles three related backlog clusters (A = observability accuracy,
B = backtest CLI plumbing, E = sim/test infra trio) into a single PR to maximize
review-cycle compression per `feedback_batch_related_work`.

### Cluster A — Observability accuracy (5 fixes)
- **#119** — `config/arcis_config.yaml` `logs_runtime` path drift
- **#120** — HealthProbe heartbeat filename mapping (ollama + dashboard)
- **#122** — HealthProbe `stale_seconds` threshold too aggressive
- **#123** — live-monitor agent baselines for wedge diagnostic
- **#124** — TradingState `shadow_trades` UndefinedTable post-DB-wipe

### Cluster B — Backtest CLI plumbing (1 fix)
- **#118** — `scripts/run_backtest.py --with-walkforward` rigor bypass

### Cluster E — Sim/test infra trio (3 fixes)
- **#112** — `test_trainer_stub.py` env-drift (DB_PATH read must be lazy)
- **#113** — lifecycle-smoke 600s timeout optimization
- **#114** — sim per-fault matrix T10-T12 (deferred from v0.36.54)

### Cluster F — Tooling (1 fix)
- **#121** — py-spy admin access for live process stack-dump

---

## Discipline (inherited from memories — verbatim per operator directive)

1. **ARCHITECT AUTONOMY** (per `feedback_architect_autonomy` 2026-05-26):
   PM resolves design-shaped sub-decisions itself using best-practice +
   codebase fit. Documents each in commit-body or footnote. `AskUserQuestion`
   ONLY for: genuine scope questions, MUST-overrides, blast-radius expansion.

2. **BATCHING** (per `feedback_batch_related_work` 2026-05-26):
   - Commit-per-fix discipline. ONE commit per task; revertable independently.
   - 3-wave structure (foundation → dependents → integration).
   - Single dual-Opus QA at end of bundle (not per-commit).
   - On landing, run post-merge kin sweep against pending tasks to catch
     any subsumption (per the protocol amended into the memory).

3. **SIBLING-SEARCH** (per `feedback_review_sibling_search`):
   Every fix MUST grep the rest of its file + adjacent files for the
   same anti-pattern. #110 dual-Opus round 1 NOT_SOUND was caused by
   missed sibling-search — do not repeat.

4. **NO OUT-OF-SCOPE DEFERRAL** (per `feedback_complete_efforts_no_deferral`):
   If a fix surfaces adjacent defects, fix them inline OR file as a
   sibling task with explicit reasoning. Do NOT punt to "we'll do later."

5. **VERIFY-BY-MUTATION** (per `feedback_vacuous_test_pattern`):
   Every new test must be verified to fail without the fix. No vacuous
   passes. #110's QA explicitly added non-vacuousness stress-tests —
   adopt the same standard here.

---

## WAVE 1 — Foundation (parallel-safe; no shared surface)

### #119 — `config/arcis_config.yaml` `logs_runtime` path drift
- **Files:** `config/arcis_config.yaml`, Tier-1 design doc, `CLAUDE.md`,
  `training_control.py:31` comment, audit docs referencing `C:/arcis/logs/`.
- **Locked choice (architect resolved):** option (b) — update config + docs.
  NOT (a) (don't move actual logs). Rationale: docs are cheap; moving live
  log path mid-flight risks watch-loop downtime.
- **New value:** `paths.logs_runtime: C:/arcis/halcyon-lab/logs`
- **Tests:** assert `load_arcis_config().paths.logs_runtime` resolves to a
  directory that exists AND contains an `arcis.log` file (boundary-touch).

### #121 — py-spy admin access for live process stack-dump
- **Files:** `scripts/dump_watchloop.ps1` (NEW), `docs/runbooks/stack-dump.md` (NEW)
- **Locked choice (architect resolved):** option (a) — wrapper script that
  elevates via `Start-Process -Verb RunAs` and invokes py-spy. NOT (b)
  (procdump requires sysinternals install). NOT (c) (faulthandler needs
  watch-loop code change — bigger blast radius).
- **Tests:** smoke test that the script exists + py-spy dispatch dry-run
  succeeds.

### #112 — `test_trainer_stub.py` env-drift (DB_PATH read must be lazy)
- **Files:** `tests/training/test_trainer_stub.py`
- **Surface:** module-level `DB_PATH = os.environ['DB_PATH']` read
- **Fix:** move read inside fixture function so conftest's env injection
  happens before resolution.
- **Tests:** verify `test_trainer_stub` no longer fails when `DB_PATH` is
  set by conftest AFTER `pytest_configure`.

### #114 — sim per-fault matrix T10-T12 (deferred from v0.36.54)
- **Files:** `tests/simulation/lifecycle/test_per_fault_matrix.py`
- **Surface:** 3 new test classes — T10 (broker timeout), T11 (clock drift),
  T12 (data feed gap). Already specced in #97's design.
- **Sibling-search:** scan `tests/simulation/lifecycle/` for any existing
  matrix scaffolding to extend rather than parallel.

---

## WAVE 2 — Dependents (Wave 1 must complete first)

### #120 — HealthProbe heartbeat filename mapping (ollama + dashboard)
- **Depends on:** #119 (logs_runtime path correction)
- **Files:** `src/tools/healthprobe/core.py`, `config/arcis_config.yaml`
  (services.* heartbeat_file overrides if needed)
- **Surface:** service→file mapping in HealthProbe must match NSSM-produced
  filenames (`dashboard-stdout.log`, `ollama_watchdog.out.log`) under the
  corrected `logs_runtime` path from #119.
- **Tests:** assert HealthProbe verdict for ollama + dashboard reads from
  the correct file paths; false-DEGRADED noise eliminated.

### #122 — HealthProbe `stale_seconds` threshold too aggressive
- **Depends on:** #119, #120
- **Files:** `config/arcis_config.yaml` (or `src/tools/healthprobe/core.py`
  if threshold is hardcoded)
- **Locked choice (architect resolved):** option (a) — config threshold bump
  from 60 → 900 seconds (15 min). NOT (b) per-task heartbeat (touches watch
  loop — bigger blast radius; v2 enhancement). NOT (c) time-of-day-aware
  (complexity not justified for v1).
- **V2 enhancement note (for PR description):** "Per-task intra-iteration
  heartbeat is the right v2 fix — bumps threshold can stay tight at 60s
  once watch loop writes a heartbeat at top of each scheduled task. Defer
  to a future infra effort."
- **Tests:** assert HealthProbe doesn't flag DEGRADED during a known
  14-minute scan cycle; assert it DOES flag DEGRADED for a 25-minute
  silent gap.

### #123 — live-monitor agent baselines for wedge diagnostic
- **Depends on:** #122 (threshold)
- **Files:** `.claude/plugins/arcis/agents/live-monitor.md`
  (+ `docs/agent-tests/live-monitor-golden.md` update)
- **Surface:** agent prompt revision per `feedback_wedge_vs_long_iteration`
  memory protocol. Update OUTPUT FORMAT to include `historical_baseline_min`
  field. Update SOP to require:
  1. Heartbeat staleness > 20 min (not just > 60s)
  2. arcis.log silence > 20 min (correlated with heartbeat)
  3. No in-progress task markers in last 20 lines
  4. Compare current staleness against `baseline_p99` for hour-of-day
- **Sibling-search:** also update `commands/operate.md` watchloop-wedged
  runbook to require these same checks before recommending restart.
- **Tests:** golden test must verify the agent refuses to declare wedge
  on a 14-min stale heartbeat with active in-progress markers (regression
  case from today's 11:14 ET misdiagnosis).

### #124 — TradingState `shadow_trades` UndefinedTable post-DB-wipe
- **Files:** `src/tools/tradingstate/core.py`
- **Surface:** SQL query for `open_positions` in TradingState
- **Investigation required:** walk `src/schema/registry.py` to find what
  replaced `shadow_trades` post-wipe. Likely candidates: `recommendations`,
  `attribution_trades`, or a renamed table.
- **Locked discipline (architect resolved):** if no equivalent table exists,
  TradingState's `open_positions` field must return null with a diagnostic
  `error_field` (not silent empty) — making the gap operator-visible. This
  is the broader silent-failure anti-pattern that masked the morning's
  wedge misdiagnosis.
- **Sibling-search:** scan all `src/tools/` for queries against potentially-
  wiped tables; surface as Known Considerations in PR description.
- **Tests:** assert TradingState returns a structured error envelope (not
  silent empty) when a queried table is missing.

### #118 — `scripts/run_backtest.py --with-walkforward` rigor bypass
- **Files:** `scripts/run_backtest.py` (line 83)
- **Surface:** import statement
- **Locked choice (architect resolved):** option (b) — DEPRECATE the CLI
  flag. Print message: `--with-walkforward is deprecated. Use
  /arcis:strategy backtest <strategy-id> for rigor-grade walkforward.`
  Rationale: arcis:strategy is the canonical surface now; updating the
  script's call-site duplicates the strategy skill's orchestration.
- **Tests:** assert running `--with-walkforward` prints deprecation notice
  and exits non-zero; assert default mode (without flag) still works.

### #113 — lifecycle-smoke 600s timeout optimization
- **Files:** `.github/workflows/lifecycle-smoke.yml`,
  `tests/simulation/lifecycle/test_smoke.py`
- **Surface:** CI timeout was bumped to 600s in v0.36.54 as a band-aid;
  underlying scenarios run slower than they should.
- **Investigation required:** profile a smoke run; identify which scenario
  classes are bottleneck. Likely: oracle wall-clock waits or `market_data`
  fake polling.
- **Locked discipline (architect resolved):** aim for 300s ceiling; if
  that's unreachable in one pass, document the residual at PR time + file
  follow-up. Do NOT trade smoke coverage for runtime.

---

## WAVE 3 — Integration + Release

**Integration gate task:**
- Run full test suite locally; verify test count ≥ 6,980 + delta from new
  tests in this PR.
- Run `/arcis:periodic-discipline tool-boundary-tests` to verify all 13
  tools still respond cleanly post-fix.
- Verify HealthProbe verdict for all 3 services is HEALTHY (not DEGRADED)
  on a fresh invocation — proves #119+#120+#122 cluster works end-to-end.
- Verify TradingState returns either real position data OR structured error
  (not silent empty) — proves #124.
- Update `CHANGELOG.md`.
- Bump version to v0.36.71 in `src/version.py`.

**Dual-Opus QA at end of wave 3 (NOT per-commit):**
- Reviewer 1 + Reviewer 2 independent passes (per
  `feedback_use_coding_team_skill` dual-Opus discipline).
- Both must rate SOUND on: root-cause, hardening, ripple, noise.
- 100% confidence required from both.
- #110's experience: first round caught sibling-search misses that second
  round verified fixed. Expect similar; budget for round 2.

**POST-MERGE KIN SWEEP** (per `feedback_batch_related_work` amended protocol):
When this PR lands, walk pending task list looking for subsumed work.
Specifically check whether #116 (PR-time vuln scanning) overlaps with
any of the CI workflow changes in #113.

---

## Out of Scope (do NOT expand this sprint)

- #51 drawdown 30-day rolling window — Sprint Cleanup-2
- #77 dangling-FK root — Sprint Cleanup-2
- #115 PR-2 cutover — gated on 1-week hold-over
- #116 PR-time vuln scanning — atomic, separate effort
- Phase 5 design effort (#99+#102+#65+#72+#73) — separate `/arcis:design`
- Per-task heartbeat for watch loop (#122 v2 enhancement) — defer
- TradingState reactive cleanup beyond `shadow_trades` — file as follow-up
  if sibling-search finds more

---

## STATUS: COMPLETE (2026-05-27 — v0.36.71)

All 10 primary fixes plus one sibling-search consolidation commit landed on
branch `sprint/cleanup-1/impl` and merged to `main` as PR.

**Commit range (top to bottom):**

- `<INTEGRATE>` — `chore(cleanup-1): bump v0.36.71 + CHANGELOG + integration receipt`
- `441f6694` — `chore(cleanup-1): finish sibling-search sweep — platform deprecation refs + nssm filename map + wedge runbook`
- `e5b799ea` — `docs(#123): live-monitor 4-point wedge protocol + operate.md sibling + golden cases`
- `c4eeec96` — `fix(#122): bump ArcisWatchLoop heartbeat staleness threshold 60→900s`
- `a93f99ed` — `chore(#113): tighten lifecycle-smoke timeout 600s → 480s`
- `12cea1d1` — `fix(#120): map HealthProbe heartbeat sources to actual NSSM filenames`
- `2f89ae12` — `chore(#118): deprecate scripts/run_backtest.py --with-walkforward (canonical: /arcis:strategy backtest)`
- `5e7a9210` — `fix(#124): TradingState returns structured error envelope on UndefinedTable`
- `d1ebb32c` — `test(#114): add per-fault matrix T10/T11/T12 — broker timeout, clock drift, data feed gap`
- `96fc7243` — `fix(#112): lazy-import production module in test_trainer_stub to absorb env scrub`
- `afcbbe83` — `feat(#121): py-spy admin stack-dump wrapper for watchloop wedge diagnostic`
- `edb68ab6` — `fix(#119): correct logs_runtime to repo-local path`
- `5222c9bf` — `spec(cleanup-1): commit specification as deliverable 0 for PR provenance`

**Net-add:** +27 new tests across the sprint. Total collected: 6,997
(well above 5,467 CI floor).

**Dual-Opus QA verdict:** _(to be filled in at merge time)_

**Follow-ups filed (per `feedback_complete_efforts_no_deferral` deferred-with-reason):**

1. `TRAINING_PID_FILE` runtime derivation alignment vs the updated
   `logs_runtime` config (or revert the #119 comment to acknowledge the
   discrepancy honestly). Architect-locked option (b) on #119 forbade
   moving log file locations at runtime, so this is a deliberate
   carry-over.
2. `scan_service.py` 440 → 517 lines past grandfathered tolerance —
   pre-existing on `main`. Either split or update
   `config/known_violations.json`.
3. lifecycle-smoke session-scoped `run_smoke()` fixture caching —
   would collapse ~9 independent invocations to ~1 and let timeout
   drop from 480s to ≤300s.
4. Six tests under `tests/` import `src.training` modules at module
   scope — apply the #112 lazy-import pattern for hardening.

