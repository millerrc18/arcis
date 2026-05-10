# Sprint 5 — Scope Inventory (Final / Terminal Sprint)

**Created:** 2026-05-08 (post-Sprint-4 close, main HEAD `56fd7fb`, tag `v0.34.0`)
**Operator policy (per memory `feedback_sprint_5_is_final`):** Sprint 5 is the **last** sprint. No SP6+ tags. Anything that does not ship in SP5 must be explicitly closed-without-fix with operator acknowledgement, or formally scoped out (separate post-S5 effort).

---

## Strategic constraints (operator-decided 2026-05-08)

1. **Terminal sprint.** Queue must hit zero by SP5 close. Tag `#SP6-*` is forbidden.
2. **Post-Sprint-5 posture: feature-freeze / bug-fix only.** No live-trading promotion gate as a S5 deliverable. Paper trading continues post-S5; live-trading promotion is a separate decision later. SP5 must NOT include live-trading-readiness tasks.
3. **#37 unified DB consolidation is OUT OF SCOPE.** PR #940 design investigation already merged; further work parked as a separate post-S5 effort. Do not pull #37 prerequisites back into SP5.
4. **Scope of "maintainable state":** post-S5, no new functionality. Bug fixes, security patches, dependency bumps only.

---

## A. Notifications subsystem (4 canonical GH issues)

| # | Issue | Title | Implementation surface |
|---|-------|-------|------------------------|
| A1 | #1040 | T22 deferred — routing/policy/digest | `src/notifications/telegram.py`, `src/services/email_*.py`, new routing module |
| A2 | #1041 | CC6: `[ARCIS]` prefix on Telegram | `safe_send` / `_send_single` in `src/notifications/telegram.py` |
| A3 | #1044 | Convert remaining 28 `notify_*` to typed dataclass payloads | `src/notifications/telegram.py` (extend pattern from T21-REV) |
| A4 | #1045 | Move 5 typed council exceptions to `src/council/errors.py` | `src/notifications/telegram_commands.py:33-50` → `src/council/errors.py` |

**Dependency note:** A1 should land **before or with** A3 since safe_send routing entries need to know the event types A3 introduces. A2 is mechanically independent. A4 is independent.

**Implicit follow-ups discovered during SP4:**
- `_PAYLOAD_EVENTS` set should be hoisted out of inline definition to a top-level constant for readability (cosmetic, ~5 lines).
- `notify_risk_alert` + `notify_exposure_alert` need `_html_escape` wiring (tracker #65 — SP4 T13 follow-up).

---

## B. Code-quality canon (test_repo_structure.py)

These have been "pre-existing" across 4 sprints. SP5 closes the pattern.

### B1. `test_no_file_over_400_lines` — 1 NEW + 6 grandfathered

| Status | File | Lines | Disposition candidate |
|--------|------|-------|------------------------|
| **NEW** | `src/evaluation/backtester.py` | 408 | Trim or split (added during SP4 — Calmar migration likely pushed over) |
| GF | `src/startup_checks.py` | 482 | Split into per-check modules |
| GF | `src/cli/commands.py` | 1456 | Major refactor — split by command group |
| GF | `src/council/agent_data.py` | 450 | Split per-agent gather_*_data fns |
| GF | `src/council/engine.py` | 703 | Split engine vs phase orchestration |
| GF | `src/data_enrichment/news.py` | 490 | Split fetch / enrich / cache |
| GF | `src/email/digest_builder.py` | 409 | Trim or split section builders |

### B2. `test_no_function_over_60_lines` — 1 NEW + ~13 grandfathered

| Status | Function | Lines |
|--------|----------|-------|
| **NEW** | `src/data_enrichment/news.py:fetch_news_sentiment` | 77 |
| GF | `src/main.py:build_parser` | 214 |
| GF | `src/cli/commands.py:cmd_config_fix` | 85 |
| GF | `src/cli/commands.py:cmd_collect_data` | 71 |
| GF | `src/cli/commands.py:cmd_live_close` | 70 |
| GF | `src/council/agent_data.py:gather_innovation_data` | 87 |
| GF | `src/council/agent_data.py:gather_tactical_data` | 87 |
| GF | `src/council/agent_data.py:gather_macro_data` | 82 |
| GF | `src/council/agent_data.py:gather_risk_data` | 79 |
| GF | `src/council/agent_data.py:gather_strategic_data` | 72 |
| GF | `src/council/aggregation.py:aggregate_votes` | 96 |
| GF | `src/council/aggregation.py:compute_dynamic_weights` | 89 |
| GF | `src/council/context.py:build_shared_context` | 70 |
| GF | `src/startup_checks.py:_check_render_postgres` | 65 |

### B3. `test_todos_have_issue_numbers` — 1 violation
- `src/scheduler/watch.py:793` — `# TODO: wire real per-packet conviction list from result when` — needs issue number or removal.

### B4. `test_all_modules_have_standard_docstring` — 7 grandfathered (warning, not failure)
- `src/services/mr_scan_service.py`
- `src/simulation/engine.py`
- `src/simulation/monte_carlo.py`
- `src/trading/alpaca_broker.py`
- `src/trading/broker_factory.py`
- `src/utils/type_safety.py`
- (one more — confirm via fresh run during design)

**SP5 canon disposition: HYBRID (operator-decided 2026-05-08).**

Scope (operator-confirmed, ~8–10 tasks):
- Fix the **1 NEW file violation:** `src/evaluation/backtester.py` (408 → ≤400)
- Fix the **1 NEW function violation:** `src/data_enrichment/news.py:fetch_news_sentiment` (77 → ≤60)
- Fix the **1 TODO violation:** `src/scheduler/watch.py:793` (add issue number or remove)
- Refactor the **4 worst-offender files** (split or trim):
  - `src/cli/commands.py` (1456 lines) — split by command group
  - `src/council/engine.py` (703 lines) — split engine vs phase orchestration
  - `src/data_enrichment/news.py` (490 lines) — split fetch / enrich / cache
  - `src/council/agent_data.py` (450 lines) — split per-agent gather_*_data fns
- Refactor the **2 worst-offender functions:**
  - `src/main.py:build_parser` (214 lines) — split into per-command parser builders
  - `src/council/aggregation.py:aggregate_votes` (96 lines) — extract sub-helpers
- **Accept all other grandfathered items as permanent.** Rename `known_violations.json` → `accepted_legacy_violations.json` (or comparable) so the test framing changes from "future fix" to "explicitly accepted". Tests must still PASS.

NOT in scope under Hybrid:
- `src/startup_checks.py` (482), `src/email/digest_builder.py` (409) — accept as permanent
- All other grandfathered functions in `cli/commands.py`, `council/agent_data.py`, `council/aggregation.py:compute_dynamic_weights`, `council/context.py:build_shared_context`, `startup_checks.py:_check_render_postgres` — accept as permanent
- All grandfathered docstring warnings (§B4) — accept as permanent unless a refactor incidentally adds the docstring

---

## C. Pending tracker tail (prior-sprint follow-ups)

| Tracker # | Title | Cluster |
|-----------|-------|---------|
| #15 | Pre-merge stale-base hook (server-side / merge-time) | Tooling |
| #26 | Separate PR for known_violations.json render_sync.py size update | Code-quality |
| #27 | (=B1+B2+B3 above) | Code-quality |
| #45 | Operator-manual-intervention drift detection | Observability |
| #47 | Triage findings from #46 Telegram + email sweep audit | Notifications (overlaps A1) |
| #48 | Mirror #44 kwarg assertions to test_bracket_safety.py | Testing |
| #54 | Wire `kpis.py:91` to pass dates+directions to `_compute_promotion_gate_kpi` | Dashboard / API |
| #56 | Add `strategy_id` FK to `shadow_trades` + wire into methodology gate filter | Schema |
| #65 | Extend `_html_escape` to `notify_risk_alert` + `notify_exposure_alert` | Notifications (sub-task of A1) |
| #66 | Add negative `total_pnl_dollars` test fixture in KPIStrip | Frontend testing |
| #67 | Wire `write_heartbeat()` into watch-loop scheduler | Observability |

**Cluster summary:** Notifications cluster (#47, #65 + GH A1) consolidates with §A. Code-quality cluster (#26, #27) consolidates with §B. Observability cluster (#45, #67) is a small new section §D below.

---

## D. Observability / drift detection (new section)

| Item | Source | Justification |
|------|--------|---------------|
| Operator-manual-intervention drift detection | #45 | Operator manual halt/override leaves no audit trail; needed for post-S5 maintenance posture |
| Watch-loop heartbeat metric (`write_heartbeat()` wiring) | #67 (SP4 T15 follow-up) | T15 added the function; never wired into scheduler. Needed for "is the loop healthy?" check |
| Pre-merge stale-base hook (server-side) | #15 | Complements client-side #59; prevents stale-base PRs from merging |

---

## E. Testing tail

| Item | Source |
|------|--------|
| Mirror #44 kwarg assertions to `test_bracket_safety.py` | #48 |
| Add negative `total_pnl_dollars` test fixture in KPIStrip | #66 |
| env-drift test fixtures (test_live_trading) — implicit | per memory `feedback_worktree_env_drift` |
| `_PAYLOAD_EVENTS` regression-lock test | implicit (SP4 hardening) |

---

## F. Dashboard / API tail

| Item | Source |
|------|--------|
| Wire `kpis.py:91` to pass dates+directions to `_compute_promotion_gate_kpi` | #54 (SP2 T3 follow-up) |
| Add `strategy_id` FK to `shadow_trades` + methodology-gate filter | #56 (SP2 T2 forward-compat) |

---

## G. Out of scope (operator-decided 2026-05-08)

| Item | Reason |
|------|--------|
| Unified DB consolidation (#37 / PR #940) | Multi-week effort; separate post-S5 project |
| Live-trading promotion gate | Post-S5 decision; not part of terminal-sprint cleanup |
| Live-broker validation tasks | Implies live-trading commitment; out of scope per posture |

---

## H. Open design questions for the Architect

1. **Canon disposition mode** — Aggressive vs Conservative vs Hybrid (see §B disposition options). Operator may prefer a specific stance to bound scope.
2. **Routing-policy abstraction layer** — Where does the routing engine live? Options: `src/notifications/routing.py` new module; or expand `safe_send` to include routing logic; or per-channel adapters. (Affects A1 + A3 sequencing.)
3. **Quiet-hours config** — Hardcode (e.g., 22:00–07:00 ET) vs config-driven. Per-event-type quiet-hours overrides allowed?
4. **Weekend-digest scheduler** — New scheduler or piggyback on existing `scheduler/watch.py`? Where does the digest accumulator persist (SQLite table vs in-memory + crash-recovery)?
5. **Backtester 408-line trim approach** — natural split point or just remove dead code? (A SP4 commit pushed it over the line; the diff history will show the cleanest fix.)

---

## I. Sprint 5 success criteria

- All 4 SP5 GH issues closed (#1040, #1041, #1044, #1045).
- 11 pending tracker tail items closed (each either fixed or explicitly closed-not-planned with operator ack).
- `test_no_file_over_400_lines`, `test_no_function_over_60_lines`, `test_todos_have_issue_numbers` either PASS or explicitly accepted as permanent (whitelist renamed/restructured to reflect that).
- Test floor: SP4 ended at 4995. SP5 should add ≥30 tests (canon fixes + notifications regression locks + env-drift fixtures + kwarg mirror).
- Versioning: SP5 ships as `v0.35.0` per established cadence.
- Documentation: operator-guide + CHANGELOG + MASTER.md updated to reflect "system in maintainable state" closing chapter.
- Visual-verify gate on Render after merge — same protocol as SP3/SP4 closeouts.

---

## J. Full repo scrub (operator-added 2026-05-10 after cutover review)

Operator directive added during PR #1047 review cycle: after the Modified-A cutover lands and the DB is unified, Sprint 5 must include a **comprehensive repo scrub** that closes accumulated debt the cutover surfaced + categories not yet inventoried. The PR #1047 review caught a partial-PG-password leak in a committed log (`migration-dry-run.log`), which suggested broader risk: if one secret slipped in, others may have. SP5's scrub closes that gap exhaustively before the system enters its post-S5 feature-freeze maintenance posture.

**Why now:** SP5 is the terminal sprint. Anything not scrubbed here becomes permanent debt the operator carries forward without further sprint capacity to address it.

### J1. Secrets audit across full git history

- Run `gitleaks detect --source . --no-banner --no-git --redact` against the current working tree
- Run `gitleaks detect --source . --log-opts="--all" --no-banner --redact` against ALL refs/all-history (catches leaks scrubbed from main but still reachable via reflog/branch tips)
- Cross-check with `trufflehog git file://.` for high-entropy strings (catches secrets gitleaks's rule patterns miss)
- For each finding: (a) verify it's still active OR already rotated; (b) if active → rotate immediately + add to known-rotated-secrets audit; (c) scrub from history via `git filter-repo` (the modern replacement for filter-branch); (d) document scrub in CHANGELOG so reviewers can verify the fix
- Establish a pre-commit hook that runs gitleaks on staged content — prevents future leaks at commit time. ARCIS already has `scripts/hooks/pre-commit` for scope-check; extend it.

### J2. Eradicate the 87 pre-existing test failures observed during PR #1047 dispatches

From multiple agents' broad-sweep reports during PR #1047 (T2-rev, T3, T1):
- ~6 `test_projections_live_*` auth-fixture failures (auth not configured in test env / worktree-env-drift class per memory `feedback_worktree_env_drift`)
- ~3 `test_repo_structure.py` failures (pre-existing canon; addressed by §B Hybrid disposition — confirm here)
- `tests/evaluation/test_walkforward.py::test_all_folds_produce_trades` makes a live FRED API call without mock — pre-existing CLAUDE.md "mock all external APIs" violation
- `tests/test_cloud_requirements_imports.py` makes live PyPI network calls — should use `@pytest.mark.network` and be excludable from fast runs
- ~75 remaining unaccounted — categorize each into: real-bug / fixture-env-mismatch / network-bound / flake; fix or document acceptance per category

Goal: full sweep `python -m pytest tests/ -q --timeout=60` returns 0 failures on operator's machine post-SP5.

### J3. Dependabot vulnerabilities

GitHub flagged **4 high + 1 moderate** vulnerabilities on `main` at the time of PR #1047 push. Review at https://github.com/millerrc18/arcis/security/dependabot; for each:
- Upgrade dependency to a non-vulnerable version (Dependabot PRs already filed for `jsonschema`, `uvicorn`, `bitsandbytes`, `matplotlib` per the 2026-05-08 PR list)
- If upgrade not possible: document why; add to an accepted-vulnerabilities allowlist (security risk acknowledgement + mitigation)

### J4. Gitignore audit

- Catch any `.env` / `.local` / `.log` / `*.pkl` / `*.gguf` files accidentally tracked (the `migration-dry-run.log` slipped past via `git add -f`; verify NO similar force-adds linger in tree)
- Run `git ls-files | xargs -I{} sh -c 'git check-ignore -q "{}" && echo "TRACKED-BUT-IGNORED: {}"'`
- Audit `training_data/` allowlist — currently `train.py` + `README.md` re-included; verify no other files should be tracked or that the pattern is correct
- Test gate: add `test_no_gitignored_files_tracked` to repo_structure

### J5. Dead code + stale-file sweep

- Schema audit: any tables in `src/schema/registry.py` not referenced by any code (post-cutover, with `render_sync.py` retired)? Drop them.
- Code audit: `vulture` or `deadcode` to find unused functions / classes (post-cutover the dual-mode `if database_url:` branches in cloud_routes become dead)
- Frontend dead-code: which components in `frontend/src/` aren't referenced from `App.jsx` or its tree?
- Documentation cruft: `docs/audits/` accumulates per-sprint specs; consider an archival convention (move closed sprints to `docs/audits/archive/`)

### J6. Post-cutover code retirement (folds in §6 tail items from spec)

These are also the spec's "out of scope today" §6.5-6.9 items — Sprint 5 absorbs them:
- `src/sync/render_sync.py` — 1359 LOC, fully obsolete once watch loop is on PG. **Delete the entire file.**
- `src/api/cloud_app.py` — 341 LOC, fully obsolete once local FastAPI is the only entry point. **Delete the entire file.**
- `src/schema/postgres.py` vs `src/schema/sqlite.py` — keep only one engine's generator. Post-Modified-A this is PG; `sqlite.py` deletes.
- 6 `cloud_routes/*.py` files with `if database_url:` runtime branches — collapse to single-engine PG logic. ~70 LOC removable.
- Stale CNAME records in Cloudflare DNS (`api → halcyon-api.onrender.com`, `www → halcyon-frontend-3ioh.onrender.com`) — cleanup per Wave 3 runbook
- Pre-cutover SQLite snapshot at `C:/arcis/data/ai_research_desk-2026-05-10-precutover.sqlite3` — retain 30 days post-cutover for emergency rollback; document disposal date in operator-guide §11 Maintenance Tasks

### J7. NSSM + system services audit

- List all NSSM services on operator's machine. Expected: `ArcisWatchLoop`, `ArcisDashboard`, `Cloudflared`. Anything else is stale (from prior experiments / one-shots).
- Verify each service's `AppEnvironmentExtra`, `AppDirectory`, `AppParameters` are correct + documented in `docs/operator-guide.md`
- Verify NSSM service ARGUMENTS / env vars don't contain secrets that should be in `.env` instead (NSSM env is persisted in registry; same scrub discipline applies)

### J8. Docker artifacts cleanup

- `docker image prune -a` to remove dangling images
- `docker volume prune` (after confirming no current containers need them — Docker PG's `pg-data` volume must be preserved)
- Document expected images / volumes in `docs/operator-guide.md` under "Modified-A — Local Postgres"

### J9. CHANGELOG.md cleanup + final v0.35.0 cut

- All `[Unreleased]` entries (Wave 1-5 cutover work + SP5 closeout) get bundled under `[v0.35.0] - 2026-05-XX` header
- New empty `[Unreleased]` block at top for post-SP5 maintenance changes
- Tag `v0.35.0` in git
- `src/version.py` VERSION → `v0.35.0`
- Validate per `docs/versioning-policy.md` (no drift between CHANGELOG header / VERSION / git tag)

### J10. Memory cleanup (operator-side `~/.claude/projects/C--arcis/memory/`)

Not a repo change but operator-side. Audit memories for:
- Outdated facts (e.g., references to RTX 3060 that survived the 3090 upgrade — keep the historical reference but note it's superseded)
- Memories about sprints that completed (e.g., Sprint 3 audit specifics — close out or archive)
- Duplicate / overlapping memories (sometimes happens when multiple agents save similar memories)

### J11. File organization / "files in correct homes" — spring cleaning

Per operator note 2026-05-10: §J also means classic structural hygiene — making sure each file lives where future-Ryan and future-agents would expect to find it.

- **Stray top-level files**: scan repo root for files that should be in subdirs. (`C:Temppr997_full.diff` and `.clone/` were cleaned during Wave 1 pre-flight; verify no similar artifacts linger.) Top-level should be: README, LICENSE, CHANGELOG, CLAUDE.md, MASTER.md, pyproject.toml, requirements.txt, docker-compose.yml, .env.example, .gitignore. Anything else is suspect.
- **`docs/audits/` archival**: closed sprints (Sprint 1-4 work) should move to `docs/audits/archive/<sprint-id>/` so the active-audits dir is just current-sprint + post-sprint-followups. Reduces git diff noise + improves dir-listing comprehension. SP1.A, SP1.B, SP1.C, SP2, SP3 (`2026-05-06-cockpit-coherence-sprint`), SP4 (`2026-05-07-sprint-4-cockpit-followups`) all candidates.
- **`scripts/` organization**: currently flat. Consider grouping by purpose: `scripts/one_shots/` (migrations, scrubs — like `sqlite_to_pg_migrate.py`), `scripts/maintenance/` (regularly-runnable — like `render_migrate.py`, `verify_training_readiness.py`), `scripts/build/` (build_sp100_history.py-style data builders). Either via dirs or a docstring convention.
- **`tests/` symmetry with `src/`**: any test file that doesn't have a clear `src/` counterpart? Any source module without tests? Add coverage gap doc OR backfill. Note: `tests/test_db_util.py` mirrors `src/utils/db.py`, `tests/api/test_app_ws_auth.py` mirrors `src/api/app.py` ws endpoint — that's the pattern.
- **`docs/` organization**: `docs/operator-guide.md` is 1700+ lines. Consider splitting into per-topic files OR adding a clear ToC + section markers. Same for MASTER.md. Reduce gigantic single-file documents.
- **Frontend file organization**: `frontend/src/components/` is flat with 30+ components. Consider grouping by domain (dashboard/, council/, trades/, etc. — partial pattern already exists for `dashboard/`).
- **Naming consistency**: file naming conventions — `snake_case.py` for Python (confirmed), `PascalCase.jsx` for React components (verify; some may have drifted to camelCase). Add a `docs/style-guide.md` or extend CLAUDE.md.
- **Data dir hygiene**: `C:/arcis/data/` accumulates snapshots (e.g., `ai_research_desk-2026-05-10-precutover.sqlite3` from cutover, `render-pg-snapshot-2026-05-10.sql`). Document a retention policy in operator-guide §7 Maintenance Tasks — e.g., "snapshots older than 90 days auto-purge unless explicitly preserved".
- **Logs dir hygiene**: `C:/arcis/logs/` similarly accumulates. Confirm log rotation is in place; if not, add it.

### Acceptance criteria for §J11

- Top-level repo dir is canonical (no stray .diff / .clone / temp files)
- `docs/audits/` shows only active or recent sprints; older sprints in `docs/audits/archive/`
- `scripts/` organized OR documented per a clear scheme
- `tests/` ↔ `src/` symmetry audit committed at `docs/audits/2026-05-XX-sprint-5-closeout/coverage-gap.md` (where gaps are intentional and accepted)
- `frontend/src/components/` grouped where natural
- `docs/style-guide.md` (NEW) or CLAUDE.md addendum documents naming + organization conventions
- Snapshots / logs retention policies documented in `operator-guide.md` §7

### Acceptance criteria for §J

- `gitleaks detect --source . --log-opts="--all"` returns 0 findings
- `python -m pytest tests/ -q --timeout=60` shows 0 failures on operator's machine
- Dependabot dashboard shows 0 high-severity vulnerabilities (moderates documented if any retained)
- `git ls-files | xargs git check-ignore -q` (negated) returns 0 paths
- `vulture src/` and `vulture frontend/src/` return <10 false-positive-rate findings
- `render_sync.py`, `cloud_app.py`, `sqlite.py` schema generator all deleted
- 6 cloud_routes dual-mode branches collapsed
- All NSSM services documented in operator-guide
- v0.35.0 cut + tagged
- Operator-guide post-S5 reflects "maintainable state" — no open follow-ups, no SP6 escape hatch references

§J is the heaviest single section of SP5 by volume but most of the work is auditing + deletion, not new feature development. Estimated 2–3 days of focused work if dispatched as a coding-team sprint batch.
