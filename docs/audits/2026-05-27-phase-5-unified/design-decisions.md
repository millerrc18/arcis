# Phase 5 - Design Decisions Log

**Total DDs:** 45
**Generated:** 2026-05-27 (r3 - post-Feasibility + Devil's Advocate revision)

---

## 1. DD-01: cloud_routes/ is LOAD-BEARING; KEEP the directory, DELETE only cloud_app.py + Render infra files; rename DEFERRED to Phase 6

**Rationale:** src/api/app.py:183-190 imports 6 router modules from cloud_routes/ — these mount the LOCAL FastAPI app. cloud_app.py is the dead second consumer.

**Alternatives considered:**
- Delete cloud_routes/ entirely (REJECTED: breaks live local dashboard)
- Rename cloud_routes/→routes_shared/ in PR-B (REJECTED: triples reviewer load on already-large PR)

---

## 2. DD-02: Sentinel-lock cloud_app.py deletion with 2 new sentinel tests at tests/ root

**Rationale:** Mirrors the existing tests/test_render_sync_removed.py 44L canonical pattern that locks the Sprint 5 §J5/§J6 sync deletions; prevents regression without enforcement gap.

**Alternatives considered:**
- Sentinel under tests/sync/ (REJECTED: tests/sync/ does not exist; canonical location is tests/ root)
- No sentinel (REJECTED: leaves the same enforcement gap that allowed cloud_app to drift this long)

---

## 3. DD-03: Add 2 sentinel tests in PR-B: test_cloud_app_removed.py + test_no_database_url_branch.py

**Rationale:** Locks both the file deletion AND the dual-runtime strip. Without the DATABASE_URL grep sentinel, a future developer could re-add the branch unaware it was deliberately stripped.

**Alternatives considered:**
- Single combined sentinel (REJECTED: violates single-responsibility for sentinels)

---

## 4. DD-04: scripts/render_architecture_doc.py is NOT Render-coupled; KEEP

**Rationale:** 'render' is a verb here (generates docs/architecture.md from AST). No Render API or DNS coupling. False-positive on the deletion sweep.

**Alternatives considered:**
- Delete then realize need (REJECTED: irreversible)
- Rename to generate_architecture_doc.py (DEFERRED to KC-3)

---

## 5. DD-05: scripts/render_migrate.py is NOT Render-coupled; KEEP (consumer doc surface at CLAUDE.md:98)

**Rationale:** Schema-sync CLI for the local PG; consumed by CLAUDE.md instructions. Rename would require doc updates.

**Alternatives considered:**
- Rename to local_pg_migrate.py in PR-B (REJECTED: scope creep)
- Delete (REJECTED: actively used)

---

## 6. DD-06: PR-A adds 2 new structure rules: test_no_underscore_scratch_at_repo_root + test_no_sqlite_at_repo_root

**Rationale:** Preventative enforcement closes CLAUDE.md:26 gap (SQLite-at-root) with a CI layer and prevents future _*.py scratch accumulation at repo root.

**Alternatives considered:**
- Single rule combining both (REJECTED: violates single-responsibility for structure rules)
- No new rules — manual discipline only (REJECTED: 17 scratch files prove discipline insufficient)

---

## 7. DD-07: Wave order is PR-A → PR-B → PR-C → PR-D → PR-E → PR-F → PR-G

**Rationale:** PR-A clears debris before PR-B's structure tests run. PR-B's auto-resolutions reduce PR-C scope. PR-D must precede PR-E. PR-F must come LAST. PR-G integrates.

**Alternatives considered:**
- PR-F first to document going in (REJECTED: docs lag the code state)
- PR-D before PR-C (REJECTED: PR-D's _safe_run touches watch.py which PR-C deliberately excludes per KC-4)

---

## 8. DD-08: PR-C in-scope subset is 8 files meeting (NOT auto-resolved by W1) AND (NOT architecturally locked) AND (clean refactor path) AND (NOT active-write surface) AND (tests in place)

**Rationale:** 51 grandfathered files exist; phase 5 cannot absorb all. The 5 criteria identify the safest subset.

**Alternatives considered:**
- Refactor all 51 (REJECTED: blast radius too high)
- Refactor only 3-4 highest (REJECTED: under-shoots phase 5 cleanup ambition)

---

## 9. DD-08a: The 8 PR-C files with verified-current line counts (Sprint #115 T17 ripple updated 2026-05-27)

**Rationale:** Stale LoC numbers would lead developers to plan splits that no longer match reality. Refreshed: executor 3093L, telegram 1822L, trainer 1530L, cli/commands 1531L, governor 970L, system 761L, scan_service 517L at src/services/, email_digest 1236L (NOT 520L), watch.py 2944L for KC-4.

**Alternatives considered:**
- Use deep-analysis baseline numbers (REJECTED: stale)

---

## 10. DD-08b: cloud_routes leftover files stay GRANDFATHERED for Phase 6

**Rationale:** Post-PR-B dual-runtime strip frees ~30L per file but all 6 remain >400L. Phase 5 PR-C scope-balloon avoided.

**Alternatives considered:**
- Include in PR-C (REJECTED: 6 additional refactors triples PR-C scope)

---

## 11. DD-08c (NEW r2): T16 email_digest 3-module split is MINIMUM acceptable outcome; optional 4th module defers to PR-C2 if task budget overruns

**Rationale:** Original spec assumed 520L → 320+200 split which is impossible (actual is 1236L). 3-module split handles the bulk; collectors module is stretch.

**Alternatives considered:**
- Force 4-module split in T16 (REJECTED: budget risk)
- Defer entire refactor to PR-C2 (REJECTED: under-delivers Phase 5)

---

## 12. DD-09: Test deletions require AND-conjoined Pass-A flag + Pass-B confirm + substitute test named in PR description

**Rationale:** Single-pass deletion is the root-cause of vacuous-test pattern in #94. AND-conjoined criteria prevent both false-deletes and lazy-deletes.

**Alternatives considered:**
- Pass-A only (REJECTED: heuristic produces false positives)
- Pass-B only (REJECTED: missing structural signal)

---

## 13. DD-10: 400L file-size limit STAYS at 400L

**Rationale:** Limit is a focus-discipline tool; raising it weakens the discipline. Grandfathered list shows it's already a soft fence.

**Alternatives considered:**
- Raise to 500L (REJECTED: invites further bloat)
- Raise per-category (REJECTED: complexity without benefit)

---

## 14. DD-11: watch.py refactor is NOT in Phase 5 PR-C (KC-4 deferral)

**Rationale:** 2944L file + active-write surface = risk profile too high for Phase-5 consolidation; deserves a dedicated sprint.

**Alternatives considered:**
- Include in PR-C (REJECTED: would dominate PR-C complexity)

---

## 15. DD-12: CollectorResult lives in NEW src/data_collection/result.py — NOT added to errors.py

**Rationale:** Result is data; errors.py is exceptions. Separation of concerns; mixing them invites future drift.

**Alternatives considered:**
- Add to errors.py (REJECTED: result is not an error)
- Add to a new src/data_collection/types.py (REJECTED: cohesion lower than dedicated result module)

---

## 16. DD-13: CollectorResult is a frozen @dataclass with 3 classmethod constructors (ok_from_count / partial / failed)

**Rationale:** Frozen prevents accidental mutation post-construction; classmethods encode the 3 valid construction paths and avoid bool-trap construction.

**Alternatives considered:**
- Mutable dataclass (REJECTED: invites bug-class)
- TypedDict (REJECTED: no methods or invariants)

---

## 17. DD-14: CollectorPartialFailureError continues to raise alongside CollectorResult (result-vs-exception split preserved)

**Rationale:** Exceptions are for halting paths; results are for completing paths. analyst/insider use the >50% error-rate threshold to escalate to exception.

**Alternatives considered:**
- Eliminate CollectorPartialFailureError; encode in result.status only (REJECTED: callers depending on exception-flow would silently change behavior)

---

## 18. DD-15 (REVISED r3 per DA1): Big Bang migration within PR-D — collectors migrate FIRST, _safe_run flips LAST (T19 is the FINAL commit of PR-D)

**Rationale:** 22 collectors read by exactly 1 consumer (_safe_run); bounded blast radius. Shim would add churn without reducing risk. Reorder (collectors-first / consumer-last) keeps intermediate HEAD green WITHOUT a transitional shim: _safe_run still treats return as bool (truthy) while collectors return CollectorResult. Big Bang completes when T19 flips _safe_run as the last commit. Considered OPTION B (transitional shim accepting both dict + CollectorResult, deleted in close-out) but rejected — adds shim-debt with no benefit when reordering achieves the same green-HEAD invariant.

**Alternatives considered:**
- Per-collector phased migration with from_legacy_dict shim across PRs (REJECTED: shim either lives forever or gets removed in a follow-up PR — wasted motion)
- OPTION B transitional dict/CollectorResult shim in _safe_run (REJECTED: shim debt; reorder achieves same green-HEAD without shim)
- Flip _safe_run first then migrate collectors (REJECTED: breaks intermediate HEAD — un-migrated collectors return dict but _safe_run expects CollectorResult)

---

## 19. DD-15a (NEW r2): PR-D close-out task T26 OWNS the CLAUDE.md §207 Data Collection Rules patch

**Rationale:** PR-D introduces the contract change; CLAUDE.md §207 documents it. Updating in T26 keeps contract change atomic with doc. PR-F's CLAUDE.md scan is then verification only, not source of truth.

**Alternatives considered:**
- Update CLAUDE.md §207 in PR-F (REJECTED: separates contract change from doc by 2 PRs — drift risk)
- Update in T19 when _safe_run changes (REJECTED: contract not finalized until all 22 collectors migrated — and T19 is now LAST per DD-15 revision)

---

## 20. DD-16: Every NEW or MODIFIED test in PR-D must satisfy the boundary-touch 6-item checklist + would-fail-if-impl-deleted gold-standard

**Rationale:** Per memory feedback_vacuous_test_pattern; the vacuous tests in #94 T1/T18 missed this check.

**Alternatives considered:**
- Spot-check only (REJECTED: too easy to miss)

---

## 21. DD-17: Test audit is two-pass hybrid (Pass A heuristic + Pass B empirical sample)

**Rationale:** Pass-A alone has false positives; Pass-B alone misses structural signal. Sampling top 50 keeps Pass-B tractable.

**Alternatives considered:**
- Full-empirical scan of all tests (REJECTED: prohibitive runtime)
- Heuristic-only (REJECTED: false-positive rate)

---

## 22. DD-18: Test deletion criteria are AND-conjoined

**Rationale:** Prevents lazy deletes (no substitute) and prevents one-signal false-positives. Mirrors how DD-09 frames the rationale discipline.

**Alternatives considered:**
- OR-conjoined (REJECTED: too permissive)

---

## 23. DD-19: Boundary-touch additions cover 6 seams: DB, Broker, LLM, ripgrep, NSSM, HTTP

**Rationale:** These are the 6 external-boundary classes in the codebase per the deep analysis; covering all 6 makes the test surface boundary-complete.

**Alternatives considered:**
- Add boundary tests opportunistically (REJECTED: incomplete coverage)

---

## 24. DD-20: Test floors HELD — pg-tests.yml EXPECTED=5267, CLAUDE.md SQLite-only 5,467

**Rationale:** Floors are PR-blocking; lowering them weakens the safety net. PR-D additions and PR-E deletions net positive.

**Alternatives considered:**
- Lower PG floor to absorb chronic-failure class (REJECTED: hides the chronic-failure)

---

## 25. DD-21: CI floor bump DEFERRED until post-#95 baseline stabilizes

**Rationale:** Phase 5 close + #95 clean-slate wipe will produce a new baseline; bumping prematurely creates a false-pass risk.

**Alternatives considered:**
- Bump at PR-G (REJECTED: pre-#95 baseline is not the final baseline)

---

## 26. DD-22: Docs taxonomy is 7-layered (evergreen / standards / runbooks / operations / audits-rolling / archive / visual-verify)

**Rationale:** Each layer has a distinct update cadence + audience. Mixing them in flat docs/ produces the current archive bloat.

**Alternatives considered:**
- Keep flat (REJECTED: produced 40+ audit subdirs)
- Merge runbooks + operations (REJECTED: distinct purposes)

---

## 27. DD-23: docs/audits archive sweep uses git mv (MOVES not deletes)

**Rationale:** Preserves history per file; reviewers can still git log --follow. Deletes lose forever.

**Alternatives considered:**
- Delete then rely on git history (REJECTED: degrades developer ergonomics for archived receipts)

---

## 28. DD-24: MASTER.md §2 uses rolling 3-sprint window inline + one-liners for older entries

**Rationale:** Keeps MASTER readable while preserving discoverability of older context via links to archive.

**Alternatives considered:**
- Keep all sprints inline (REJECTED: MASTER bloats indefinitely)
- Delete older entries (REJECTED: loses historical reasoning)

---

## 29. DD-25: CHANGELOG.md and RELEASES.md REMAIN separate; cross-link only

**Rationale:** CHANGELOG is per-change log (Keep-a-Changelog format); RELEASES is process narrative + path-to-v1 dashboard. Different artifacts for different audiences.

**Alternatives considered:**
- Merge into single CHANGELOG (REJECTED: loses process-narrative voice)
- Merge into RELEASES (REJECTED: loses standard log format)

---

## 30. DD-26: Floor-drift remediation closes via PR-F (README rewrite + MASTER §2 floor table)

**Rationale:** Single source of truth for floor numbers — README quotes it, MASTER explains the SQLite-vs-PG-aware delta.

**Alternatives considered:**
- Add a tests/CONTRIBUTING.md (REJECTED: more places to drift)

---

## 31. DD-27: CLAUDE.md updates are DELTA PATCHES ONLY (no full rewrite)

**Rationale:** Deep-analysis verified CLAUDE.md is fresh through #111; brief misread it as stale. Full rewrite risks losing operator-curated content.

**Alternatives considered:**
- Full rewrite (REJECTED: regression risk)

---

## 32. DD-28: DIRECTORY.md regenerated from scratch in PR-F via scripts/generate_directory.py

**Rationale:** Manual edits to DIRECTORY.md drift over time; regen ensures it reflects HEAD. Script reliability concern (memory ref) addressed by repair-as-part-of-PR-F if broken.

**Alternatives considered:**
- Manual edit (REJECTED: drift risk)
- Stop maintaining DIRECTORY.md (REJECTED: it's referenced by operator)

---

## 33. DD-29: PR-C waves dispatch in 3 sub-waves (C-i sequential / C-ii parallel / C-iii parallel)

**Rationale:** shadow_executor + telegram (C-i) are high-blast and serialized for review focus; remaining 6 refactors are independent imports — safe to parallel.

**Alternatives considered:**
- All sequential (REJECTED: wastes 3-4 days of wall-clock)
- All parallel (REJECTED: review load too high for high-blast files)

---

## 34. DD-30: PR-D waves dispatch in 3 sub-waves (D-i sequential foundation / D-ii 4-batch parallel / D-iii sequential close with T19 LAST)

**Rationale:** result.py + 3 canonical collectors set the pattern; remaining 19 collectors mirror in parallel batches; close-out (CLAUDE.md patch then T19 _safe_run flip) sequential. T19 is the FINAL commit per DD-15 revision.

**Alternatives considered:**
- All collectors in single mega-task (REJECTED: 22-file scope violates 4-file cap and review tractability)
- T19 flip first (REJECTED per DD-15 — breaks intermediate HEAD)

---

## 35. DD-31: Visual-verify .png hierarchies move WITH parent receipt subdir; binary identity preserved

**Rationale:** Visual-verify pngs are the regression-evidence anchor for UI PRs; transcoding or unbundling breaks the audit trail.

**Alternatives considered:**
- Strip .png files (REJECTED: destroys visual-verify evidence)
- Transcode to WebP (REJECTED: introduces image-format drift)

---

## 36. DD-32: PR-G includes 3 phase-close sentinels (known_violations freshness + audits archive policy + CollectorResult contract)

**Rationale:** Sentinels lock the post-phase-5 invariants so a future PR can't silently regress (e.g., adding a sub-400L file to known_violations or returning to bool from _safe_run).

**Alternatives considered:**
- Skip sentinels (REJECTED: regression risk in 6 months)

---

## 37. DD-33: Kin-task subsumption (#125, #126) is CONDITIONAL on OQ-1 operator confirmation

**Rationale:** Task IDs only — architect cannot verify thematic overlap without operator input. Architect-autonomy directive: surface only genuine scope questions.

**Alternatives considered:**
- Auto-subsume (REJECTED: scope assumption)
- Auto-leave-open (REJECTED: misses potential consolidation)

---

## 38. DD-34: Trading-embargo window (OQ-2) — architect recommends dead window (22:30-09:30 ET)

**Rationale:** Dead window means a failure can't impair live trading; matches memory feedback_no_restart_during_overnight_window guidance.

**Alternatives considered:**
- Active trading window (REJECTED: failure during live trading is catastrophic)

---

## 39. DD-35: README audience (OQ-3) — architect recommends operator-only + link to MASTER for contributor case

**Rationale:** Current de-facto audience is operator; pretending otherwise produces stale contributor onboarding flows.

**Alternatives considered:**
- Full contributor onboarding (REJECTED: maintenance burden without users)

---

## 40. DD-36: Per-PR NSSM smoke-test + visual-verify is MANDATORY for PRs touching watch.py or src/api/*.py

**Rationale:** Memory references: feedback_visual_verify_ui (B1/B2 regression), feedback_dashboard_visibility (operator's primary cockpit). Both classes were operator-caught post-merge previously — sentinels insufficient.

**Alternatives considered:**
- Trust automated tests (REJECTED: B1/B2 slipped through automated tests)

---

## 41. DD-37 (NEW r3 / DA3): CHANGELOG.md per-PR sentinel markers prevent merge conflicts across 7 PRs

**Rationale:** 7 PRs touch CHANGELOG [Unreleased] over 3-4 weeks. Naive concurrent edits textually overlap → conflicts. Each PR writes under its own `<!-- PR-X entries -->` marker block; hunks under different markers do NOT overlap. PR-F (T33) unifies markers into versioned `## [v0.36.78]` block + removes markers. Markers also serve as per-PR audit trail.

**Alternatives considered:**
- Single shared [Unreleased] section without markers (REJECTED: textual conflict on every PR merge)
- Each PR maintains its own CHANGELOG-PR-X.md file then concatenated by PR-F (REJECTED: 7 new files for a problem markers solve in-place)
- Sequential PR-merge only (REJECTED: kills parallelism within phase)

---

## 42. DD-38 (NEW r3 / DA4): Pass-B methodology defined for unit / integration / fully-shimmed test cases

**Rationale:** §6.1 said 'delete the impl function the test mocks' which is unambiguous for unit tests but ambiguous for integration tests with multiple mocks. Methodology: unit (delete single impl), integration (delete each impl one-at-a-time; all must break the test, surface-level vacuous flag if any single-impl deletion doesn't break it), fully-shimmed (vacuous by definition).

**Alternatives considered:**
- Skip integration tests in Pass B (REJECTED: integration tests are where vacuousness most accumulates)
- Delete all mocked impls together (REJECTED: doesn't isolate WHICH surface is vacuous)

---

## 43. DD-39 (NEW r3 / DA5): Boundary-touch 6-item checklist embedded verbatim in spec §6.5 + verified/added to docs/standards/boundary-touch-tests.md + PR template in T0a (PR-A)

**Rationale:** DD-16/17/19/§10 reference 'the 6-item checklist' but checklist text was not in spec, no task created/updated the source doc, no PR template integration. T0a (new task id=100) closes this — spec embeds checklist, T0a ensures the standards doc + PR template match.

**Alternatives considered:**
- Link to standards doc without embedding in spec (REJECTED: spec becomes dependent on external doc state)
- Embed in CLAUDE.md instead (REJECTED: CLAUDE.md delta-only per DD-27)

---

## 44. DD-40 (NEW r3 / DA7): T13 CLI split uses decorator-preservation pattern (b) — sub-modules export DECORATED functions; commands.py is pure re-export. Subprocess sentinel test verifies audit-log emission per command, MUST exist and pass in PR-C.

**Rationale:** Per memory feedback_cli_decorated_public_api: CLI __main__.py MUST import decorated public API (not _impl helpers). Two patterns considered — (a) undecorated sub-modules + commands.py applies decorators at dispatch boundary; (b) sub-modules export decorated, commands.py is pure re-export. Pattern (b) RECOMMENDED — keeps decorator close to function, avoids dispatcher double-application. Subprocess sentinel verifies the decorator chain works end-to-end (audit-log entry per command via `python -m src.cli <cmd> --help`).

**Alternatives considered:**
- Pattern (a) undecorated sub-modules + dispatcher-decorates (REJECTED: double-application risk + decorators detached from definition)
- Defer sentinel to PR-G (REJECTED: T13 is where the regression risk lives — sentinel must ship with the split)

---

## 45. DD-41 (NEW r3 / DA2): T20-T25 per-task file cap raised from 4 to 6-8 for paired collector+test updates

**Rationale:** Each collector migration requires updating both the collector .py AND its test file (mechanical search-replace). With 4-file cap, 4 collectors + 4 tests = 8 files exceeds scope. Splitting into 2 tasks (collectors-only + tests-only) doubles task count from 6 to 12 in PR-D — no benefit. Raising cap to 6-8 per task (4 collectors + 4 tests) keeps related changes atomic. Documented as DD per architect-autonomy directive on cap deviations.

**Alternatives considered:**
- Keep 4-file cap + double the task count (REJECTED: 12 tasks in PR-D is operator-cognitive-load heavy)
- Tests in separate trailing task per batch (REJECTED: introduces a window where collector returns CollectorResult but tests still assert dict shape)

## 46. DD-42 (NEW / OPERATOR SCOPE INJECTION 2026-05-28): PR-E2 suite green-gate uses a JUSTIFIED-SKIP policy

**Decision:** PR-E2 (a second sub-PR in the PR-E wave) enforces a suite green-gate. Every test must PASS, OR carry a documented skip reason in an ALLOWLISTED category. Zero failures; zero xpass (xfail_strict=true). No test may remain skipped merely because "it broke and wasn't the current scope."

**Allowlisted skip categories (exhaustive):**
1. `platform` — OS/arch-specific (e.g. Windows-only / POSIX-only).
2. `optional-dep` — requires an uninstalled optional dependency (gated import).
3. `engine-aware` — PG-vs-SQLite behavioral divergence the test legitimately gates on.
4. `tracked-upstream-bug (#N)` — a real defect tracked by issue #N (NOT a silent punt).

Every surviving skip carries an allowlisted reason string + (for category 4) a tracking task #N. A CI sentinel (T43, tests/test_suite_integrity.py) FAILS if any test failed, any skip lacks an allowlisted reason, or any xfail xpassed; xfail_strict=true is set globally. The sentinel is proven non-vacuous (verify-by-mutation: RED on injected skip-without-reason / failure / xpass).

**Rationale:** the campaign repeatedly surfaced tests skipped/red "out of scope" (pre-existing api failures kin #20, date-sensitive flakes kin #18, notifications_digest_queue kin #8). The green-gate converts the suite from "mostly green with a tolerated tail" to "provably green or provably justified" — making future regressions detectable rather than buried in a skip/fail backdrop.

**Alternatives considered:**
- Leave the tail as-is (REJECTED: the tolerated-failure backdrop is exactly what let the PR-B T7 docstring regression reach main misclassified as "pre-existing" — kin #16).
- Hard zero-skip (REJECTED: platform/optional-dep/engine-aware skips are legitimate; an allowlist preserves them while banning the "broke, deferred" anti-pattern).

---
