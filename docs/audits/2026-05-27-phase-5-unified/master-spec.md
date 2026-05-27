# Phase 5 — Codebase + Docs Consolidation Master Spec

**Status:** READY FOR REVIEW (architect-locked 2026-05-27, surgical revision r3)
**Scope:** Closes #102 + #72 + #65 + #73 + #99. Sequenced before #95 capstone (clean-slate wipe).
**Shape:** Hybrid (c) — Master plan with inline sub-specs for all 5 efforts; #73 and #99 carry the heaviest sub-spec weight as the highest-blast-radius efforts.
**Target:** v0.36.72 → v0.36.78 across 5-7 PRs over 3-4 weeks. Dual-Opus QA per PR.
**Trading impact:** ZERO-IMPAIRMENT requirement — no PR may merge while a watch-loop cycle is mid-flight on the wakeup window (21:30-22:30 ET embargo per memory).

**Revision r3 (2026-05-27) — addresses post-r2 Feasibility (2 fixes) + Devil's Advocate (8 major + 3 minor):**
- F1: Corrected 4 collector filenames missing `_collector` suffix vs reality in §5.2, DD-13 shape map, T21, T24 (`edgar_historical.py`, `options_metrics.py`, `retention.py`, `short_volume_finra.py`).
- F2: §12 DD count corrected to 42.
- DA1: T19 (`_safe_run` flip) reordered to LAST step of PR-D — collectors migrate first; consumer flips after all 22 return CollectorResult. DD-15 rationale updated.
- DA2: T20-T25 file cap raised from 4 to 10 (paired collector+test updates); new DD-41 documents the per-task cap raise.
- DA3: New §8.4 CHANGELOG per-PR sentinel-marker discipline; new DD-37.
- DA4: §6.1 Pass-B methodology extended for multi-mock integration tests; new DD-38.
- DA5: 6-item boundary-touch checklist embedded verbatim in §6.5; new T0a in PR-A creates/refreshes `docs/standards/boundary-touch-tests.md` + adds to PR template; new DD-39.
- DA6: §3.4 two-step rollback protocol for PR-B (revert + sentinel-delete in same commit).
- DA7: T13 CLI split now mandates decorator-preservation pattern (b) + subprocess sentinel test; new DD-40.
- DA8: T29 scoped to Pass-B-receipt-line citations + math-check pre-merge; T28 emits receipt with DELETION_LIST section.
- Minor DA9/DA10/DA11/DA12 noted in §13.

---

## 1. Executive Summary

Phase 5 is consolidation — not a feature sprint. Five long-tail efforts are joined because their blast radii overlap on the same files (cloud_routes/, watch.py, the 22 collectors, the docs tree). Sequencing them as one phase eliminates 3-5 redundant QA cycles and lets each wave shrink the surface for the next.

**The five efforts in dependency order:**

| Effort | Wave | What it does | Why this order |
|---|---|---|---|
| **#99-debris** (partial) | W0 / PR-A | Delete 17 `_*.py` REPL scratch + repo-root SQLite violation + typo artifact + add 2 new structure-rules + refresh boundary-touch standards doc + PR template | Fast, safe, unblocks `_*.py` collisions with scan tools; one PR's worth of cleanup |
| **#73** Render code sweep | W1 / PR-B | Delete `cloud_app.py`, `render.yaml`, `requirements-cloud.txt`, 2 of 4 `scripts/render_*.py`; remove `DATABASE_URL` dual-runtime branches from 7 cloud_routes files; preserve `cloud_routes/` (load-bearing, see DD-01) | Auto-resolves ~6 structure-debt entries; removes a maintenance tax from every subsequent PR |
| **#65** Structure-debt | W2 / PR-C | Targeted refactor of 8 grandfathered files; prune `config/known_violations.json` post-W1+W2 | Free wins from W1 already booked; remaining 8 are clean splits |
| **#72** CollectorResult | W3 / PR-D | New `CollectorResult` dataclass; migrate 22 collectors FIRST, then flip `_safe_run` consumer LAST; tests batch-updated; CLAUDE.md §207 contract delta | Independent of W1-W2 surfaces; sized for one big PR |
| **#102** Test audit | W4 / PR-E | Vacuous-test detection + scoped deletion + boundary-touch additions; floor held at 5,267 / 5,467 | Must come AFTER #72 so test deletions reflect the final collector contract |
| **#99** Docs consolidation | W5 / PR-F | MASTER refresh; README rewrite; `docs/archive/` policy; DIRECTORY regen; CHANGELOG / RELEASES de-overlap; CLAUDE.md delta patches | Must come LAST — needs to document all preceding waves |
| **Phase-5 close** | W6 / PR-G | Sentinel tests for deletions; `known_violations.json` final prune; kin-task subsumption commits (#125, #126) | Final integration; gates handoff to #95 |

**The architectural fork (DD-01) is RESOLVED:** `cloud_routes/` is load-bearing for the LOCAL app via `app.py:183-190`. The Render decommission removes the second consumer (`cloud_app.py`), not the directory. The directory name is now a lie but renaming it is deliberately deferred to a follow-up to keep PR-B focused on deletion.

**Total expected line-count delta:** ~ -3,500 LoC code (deletions dominate) + ~ +800 LoC tests + ~ -8,000 LoC docs (archive moves) + ~ +1,500 LoC docs (rewrites). Net repo shrinks.

---

## 2. Architecture / Topology Overview

No new architecture. Phase 5 simplifies the EXISTING architecture by:

1. **Killing the cloud bifurcation.** Pre-Phase-5: two FastAPI entrypoints (`app.py` + `cloud_app.py`) sharing the same `cloud_routes/` router library. Post-Phase-5: one entrypoint (`app.py`). The `cloud_routes/` library survives as a router-module collection (rename deferred).
2. **Normalizing collector outputs.** Pre-Phase-5: 8 distinct dict shapes returned by 22 collectors, all discarded by `_safe_run` at `watch.py:2442`. Post-Phase-5: one `CollectorResult` dataclass; `_safe_run` inspects status + reports to `_capability_health`.
3. **Documenting what's real.** Pre-Phase-5: README claims `3,500 tests`; CLAUDE.md says `5,467`; pg-tests.yml enforces `5,267`. Post-Phase-5: one authoritative floor table in MASTER §2 with rationale for the SQLite-vs-PG-aware delta.
4. **Reducing the audit-receipt tree.** Pre-Phase-5: 40+ `docs/audits/YYYY-MM-DD-*` subdirs at top-level. Post-Phase-5: rolling 3-sprint window at `docs/audits/`; older receipts moved to `docs/archive/sprint-receipts/`.

**What does NOT change:**
- The schema registry (architecturally locked, 2902L).
- The `_capability_health` contract (Shape G — separate from CollectorResult).
- The CI test-floor enforcement mechanism (only the numbers update).
- The Cloudflare Tunnel + ArcisDashboard NSSM service topology.
- The 16 `test_repo_structure` rules (TWO rules ADDED in PR-A; otherwise untouched).

---

## 3. Sub-Spec — #73 Render Code Sweep (W1 / PR-B)

The heaviest single PR in Phase 5. Resolves the doc-vs-code drift where `docs/operations/render-decommission.md` declares Render dead but live code imports a cloud-coupled router library.

### 3.1 The fork resolution (DD-01, evidence-traced)

**Question:** Is `src/api/cloud_routes/` delete-clean or load-bearing?

**Evidence collected:**
- `src/api/app.py:183-190` imports SIX router modules FROM `cloud_routes/`: `kpis`, `broker_exceptions`, `preflight`, `notifications`, `platform`, `walkforward`. These mount under `/api/*` on the LOCAL app served by Cloudflare Tunnel.
- `src/api/cloud_app.py:312-342` imports the SAME modules. This entrypoint is dead (no DNS, no traffic, no `DATABASE_URL` set in env per `docs/operations/render-decommission.md` Phase 2 receipt).
- 7 cloud_routes files have a `DATABASE_URL` dual-runtime gate (`cloud_routes/platform.py:55-63` is the canonical example). Since `DATABASE_URL` is unset post-cutover, the PG branch is dead but the SQLite branch is the active local read path.
- `src/sync/render_sync.py` and `src/sync/reconcile.py` were deleted in Sprint 5 §J5/§J6 with sentinel tests blocking re-introduction. No equivalent sentinel for `cloud_app.py` / `cloud_routes/`.

**Architect decision (DD-01):** `cloud_routes/` is **LOAD-BEARING** for the local app. KEEP the directory. DELETE only `cloud_app.py` and Render infrastructure files. Rename of `cloud_routes/` → `routes_shared/` is DEFERRED to a Phase-6 follow-up (not Phase 5 scope; documented as Known Consideration §13).

### 3.2 The deletion manifest

**Delete (irreversible — sentinel-locked):**
- `src/api/cloud_app.py` (~342L) — dead FastAPI entrypoint, no longer served.
- `render.yaml` (repo root) — Render service definition.
- `requirements-cloud.txt` (repo root) — cloud-only deps (psycopg2-binary, etc.).
- `scripts/render_init_db.py` — one-shot bootstrap, long-past.
- `scripts/render_to_local_migrate.py` — one-shot data-copy, already executed.

**Keep (verified non-Render despite name):**
- `scripts/render_architecture_doc.py` — "render" is a verb here; generates `docs/architecture.md` from AST. No Render coupling. Filed for rename consideration in §13.
- `scripts/render_migrate.py` — still the canonical schema-sync CLI per `CLAUDE.md:98`. Rename to `local_pg_migrate.py` DEFERRED (consumer doc surface) — added to §13.

**Modify (strip dual-runtime branches):**
- `src/api/cloud_routes/platform.py` — remove lines 55-63 (`if database_url:` PG branch); keep only the SQLite path. Update docstring `Reason:` block to remove Render rationale.
- `src/api/cloud_routes/broker_exceptions.py` — same pattern.
- `src/api/cloud_routes/commands.py` — same pattern.
- `src/api/cloud_routes/kpis_compute.py` — same pattern.
- `src/api/cloud_routes/notifications.py` — same pattern.
- `src/api/cloud_routes/preflight.py` — same pattern.
- `src/api/cloud_routes/walkforward.py` — same pattern.
- `src/api/cloud_routes/__init__.py` — update docstring ("Cloud dashboard route modules" → "Shared FastAPI router modules; historically named after the cloud_app entrypoint which was decommissioned in Phase 5").

**Add (regression locks):**
- `tests/test_cloud_app_removed.py` (repo-root location, mirrors the existing `tests/test_render_sync_removed.py` 44L canonical pattern) — sentinel asserting `src/api/cloud_app.py` does not exist and `render.yaml` / `requirements-cloud.txt` do not exist at repo root.
- `tests/test_no_database_url_branch.py` (repo-root location) — sentinel grepping the 7 modified files for `DATABASE_URL` references (zero hits required). Locks the strip in place.

**Documentation deltas (in PR-B, not deferred to PR-F):**
- `docs/operations/render-decommission.md` — add a closing receipt section noting code-side removal completed under PR-B.
- `CHANGELOG.md` `[Unreleased]` → `### Removed`: enumerate the 5 deleted files + the 7 stripped files. Written under the `<!-- PR-B entries -->` sentinel marker per §8.4.
- `MASTER.md` §2 (volatile state) — remove any Render-flavored bullets.

### 3.3 Test impact

Expected test count delta: **+2 sentinels**, **0 deletions** (no test currently exercises `cloud_app.py` exclusively — verified via `grep` step in PR-B verification).

If the test inventory step uncovers cloud_app-only tests, those tests are MIGRATED to cover `app.py` paths or DELETED with explicit rationale in the PR description (per DD-09 deletion-rationale discipline).

### 3.4 Risk + rollback

**Blast radius:** medium-high. Touches the LIVE FastAPI app serving the dashboard.

**Mitigations:**
- Cloudflare Tunnel + ArcisDashboard NSSM smoke-tests run pre-merge AND post-merge per `docs/operations/render-decommission.md` Phase 1 receipt.
- Visual-verify the Dashboard in browser per `feedback_visual_verify_ui` before push.
- PR-B does NOT touch `app.py` router include lines — only `cloud_app.py` (which is unmounted). Reduces surface.

**Two-step rollback protocol (DA6):**

A naive `git revert <pr-b-sha>` produces RED CI because the revert restores `cloud_app.py` AND the sentinel tests. With `cloud_app.py` back, the sentinels FAIL. Protocol:

1. `git revert --no-commit <pr-b-merge-sha>` — restores `cloud_app.py` + `render.yaml` + `requirements-cloud.txt` + 2 `render_*.py` scripts + DATABASE_URL branches.
2. In the SAME revert commit, ALSO delete the 2 sentinel tests:
   ```
   git rm tests/test_cloud_app_removed.py tests/test_no_database_url_branch.py
   git commit -m "Revert PR-B (#73 render sweep) + remove paired sentinels"
   ```
3. Push the combined revert + sentinel-delete as one commit.

**Rationale:** sentinels are PAIRED with the deletion. Forward direction adds both; revert direction must remove both. PR-G T37's contract-sentinel note cites this protocol.

---

## 4. Sub-Spec — #99 Docs Consolidation + Repo Restructure (W0 partial + W5 / PR-A debris + PR-F docs)

The widest-surface effort. Split into two PRs to keep blast radius manageable.

### 4.1 PR-A scope (W0 — repo-root debris + standards refresh)

**Delete (no kin in src/tests/scripts/docs verified via grep):**
- 17 `_*.py` files at repo root (REPL scratch): `_a.py`, `_audit.py`, `_ck.py`, `_f.py`, `_p.py`, `_q.py`, `_t1.py` through `_t1i2.py`, `_v.py`.
- `_582_operator_action.sql` — historical one-shot, #582 long-closed.
- `--db-path` — CLI typo artifact (filename literally `--db-path`).
- `ai_research_desk.sqlite3` at repo root — ACTIVE VIOLATION of CLAUDE.md:26. Verify size first; if non-zero, MOVE out of repo.
- `check_trades.py` at OUTER repo root — out of git scope; left alone.

**Add (preventative, DD-06):**
- New `test_repo_structure` rule: `test_no_underscore_scratch_at_repo_root` — fails if any `_*.py` or `__*.py` (excluding `__init__.py`, `__main__.py`) appears at repo root.
- Companion rule: `test_no_sqlite_at_repo_root` — fails if any `*.sqlite*` or `*.db` appears at repo root.

**Standards-doc refresh (DA5, owned by T0a):**
- Verify `docs/standards/boundary-touch-tests.md` exists; if missing the 6-item checklist text from §6.5, ADD it.
- Add a `## Boundary-Touch Compliance` block (referencing the 6-item checklist) to `.github/PULL_REQUEST_TEMPLATE.md`.

**Estimated PR-A line delta:** -2,500 LoC (scratch files) + +60 LoC (new rules) + ~+150 LoC (standards doc + PR template).

### 4.2 PR-F scope (W5 — docs)

**Doc taxonomy (DD-22):** 7-layered (evergreen / standards / runbooks / operations / audits-rolling / archive / visual-verify).

**Concrete actions:**

1. **README.md full rewrite** (~120 → ~200 lines): SQLite-only floor 5,467; remove Phase-1-Honest-Baseline; add Quick Start + Repo Layout; link to MASTER/CLAUDE/RELEASES.

2. **MASTER.md §2 rolling-window (DD-24):** 3-sprint inline + one-liners for older.

3. **CLAUDE.md delta patches only (DD-27):** test-floor at :15 + 1-line for new structure rules. NOTE: CLAUDE.md §207 patch is OWNED BY PR-D T26 (DD-15a) — PR-F only verifies.

4. **CHANGELOG.md vs RELEASES.md de-overlap (DD-25):** keep separate; cross-link headers. PR-F T33 unifies per-PR sentinel markers from §8.4 into a versioned `## [v0.36.78]` block + removes the markers.

5. **DIRECTORY.md regen (DD-28):** verify `scripts/generate_directory.py`; fix if broken; regen.

6. **`docs/audits/` archive sweep (DD-23, DD-31):** subdirs older than 2026-05-21 → `git mv` to `docs/archive/sprint-receipts/`. ~30 of ~40 move.

7. **`docs/operations/render-decommission.md` close-out:** Phase-4 receipt.

**Estimated PR-F line delta:** +1,500 LoC (rewrites) -8,000 LoC apparent (move-not-delete).

### 4.3 Test impact (PR-F)

- +1 sentinel: DIRECTORY.md staleness.
- +1 sentinel: standards + runbooks header check.
- 0 deletions.

---

## 5. Sub-Spec — #72 CollectorResult Contract (W3 / PR-D)

The deepest-contract effort. Touches 22 collectors + 1 consumer + ~21 test files.

### 5.1 The contract (DD-13)

**New file: `src/data_collection/result.py`** (NOT added to `errors.py` per DD-12).

```python
from dataclasses import dataclass, field
from typing import Literal

Status = Literal["ok", "partial", "failed"]

@dataclass(frozen=True)
class CollectorResult:
    collector_name: str
    status: Status
    primary_count: int
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, int] = field(default_factory=dict)

    @property
    def is_healthy(self) -> bool: ...
    @classmethod
    def ok_from_count(cls, name: str, count: int, **metadata: int) -> "CollectorResult": ...
    @classmethod
    def partial(cls, name: str, count: int, errors: list[str], **metadata: int) -> "CollectorResult": ...
    @classmethod
    def failed(cls, name: str, errors: list[str]) -> "CollectorResult": ...
```

### 5.2 Migration mapping (the 22 collectors)

**In-scope (22 collectors — actual file names verified 2026-05-27):**
`macro_collector.py`, `edgar_collector.py`, `edgar_historical.py`, `filings_sentiment_collector.py`, `options_collector.py`, `options_metrics.py`, `analyst_collector.py`, `insider_collector.py`, `fed_collector.py`, `press_releases_collector.py`, `cboe_collector.py`, `company_executive_collector.py`, `docs_collector.py`, `institutional_ownership_collector.py`, `price_target_collector.py`, `research_collector.py`, `retention.py`, `short_interest_collector.py`, `short_volume_finra.py`, `stock_financials_collector.py`, `trends_collector.py`, `vix_collector.py`.

NOTE: Four files use a BARE name (no `_collector` suffix): `edgar_historical.py`, `options_metrics.py`, `retention.py`, `short_volume_finra.py`.

**Explicitly OUT of scope:** `_capability_health.py`, `capability_registration.py`, `_finnhub_shared.py`, `research_sources.py`, `research_synthesizer.py`, `errors.py`, `__init__.py`.

| Current shape | Collectors | New CollectorResult mapping |
|---|---|---|
| Shape A (macro) | macro_collector | `primary_count=series_collected`, `metadata={"notable_changes": ...}` |
| Shape B (edgar) | edgar_collector, edgar_historical (bare), filings_sentiment_collector | `primary_count=tickers_processed`, `metadata={"filings_stored": ...}` |
| Shape C (options) | options_collector, options_metrics (bare) | `primary_count=tickers_collected`, `metadata={"contracts_stored": ...}`, `errors=[...]`, `status="partial" if errors else "ok"` |
| Shape D (analyst) | analyst_collector, insider_collector | `CollectorResult.partial()` when errors>50%; raise `CollectorPartialFailureError` REMAINS (DD-14) |
| Shape E (fed) | fed_collector | `primary_count=sum(buckets)`, `metadata={"statements":..., "minutes":..., ...}` |
| Shape F (press_releases) | press_releases_collector | `aggregate_results()` helper; `primary_count=len(non_null_items)` |
| Shape G (`_capability_health`) | _capability_health.py | OUT OF SCOPE |

**Other unmapped collectors:** cboe_collector, company_executive_collector, docs_collector, institutional_ownership_collector, price_target_collector, research_collector, retention (bare), short_interest_collector, short_volume_finra (bare), stock_financials_collector, trends_collector, vix_collector — each gets a CollectorResult with `primary_count` reflecting their natural unit (rows_stored).

### 5.3 Consumer-side: `_safe_run` at `watch.py:2442`

**Current:** returns `bool`, DISCARDS dict.

**New:** returns `CollectorResult`. On Exception → `CollectorResult.failed`. Routes status to `_capability_health.set_status` (ok/degraded/down). `if result.is_healthy:` is the bool-compat shim.

**CLAUDE.md §207 patch:** Owned by T26 (DD-15a).

### 5.4 Backward compat strategy (DD-15, REVISED in r3 per DA1)

**Decision:** Big Bang within ONE PR (PR-D). All 22 collectors + `_safe_run` migrate together. No multi-PR shim layer.

**Sequencing within PR-D (revised r3):** Collectors migrate FIRST; `_safe_run` flips LAST. During the intermediate state, collectors return CollectorResult but `_safe_run` still treats the return value as bool — the new dataclass is truthy and the old dict-discarding behavior simply becomes object-discarding behavior. Nothing breaks at intermediate HEAD because `_safe_run` never inspected the return shape beyond truthiness. T19 (flip `_safe_run`) is the FINAL commit of PR-D's wave D-iii.

**Rationale:**
- Shim layer (per-collector phased migration across PRs) was REJECTED: requires a `from_legacy_dict` helper that lives forever or gets deleted in a second PR — adds churn.
- The 22 collectors are read by exactly one consumer (`_safe_run`). Bounded blast radius.
- Reorder (collectors-first / consumer-last) keeps intermediate HEAD green without a transitional shim.

### 5.5 Test impact

- 21 collector test files update assertions: `result["x"]` → `result.primary_count` etc.
- 1 NEW: `tests/data_collection/test_collector_result.py` (~+15 tests).
- 1 NEW: `tests/scheduler/test_safe_run_routes_to_capability_health.py` (~+6 tests).
- Vacuous-test guard (DD-16): every updated test must satisfy the 6-item checklist (§6.5).
- Expected delta: +20 (may net to +15 after PR-E).

---

## 6. Sub-Spec — #102 Test Audit (W4 / PR-E) — INLINE

### 6.1 Audit methodology (DD-17 + DD-38)

**Two-pass hybrid:**

**Pass A — automated heuristic detection:**
1. Find tests where ONLY assertion is `assert_not_called()` or `assert_called_once()` on a mock.
2. Files with `@patch:assert_called` ratio > 3:1.
3. Tests that `patch('module_under_test')` (gold-standard violations).
4. Tests with `assert True` or no assertion.

**Pass B — empirical sample verification (DD-38, refined r3):**

For UNIT TESTS (test mocks exactly one impl):
- Run; confirm passes. Delete the impl in a SCRATCH worktree. Re-run.
- If still passes → VACUOUS. If fails → KEEP.

For INTEGRATION TESTS (test mocks 2+ impls):
- Delete each mocked impl ONE AT A TIME (scratch worktree).
- Test MUST fail on EACH single-impl deletion.
- If any single-impl deletion fails to break the test → VACUOUS ON THAT SURFACE.
  - (a) add a sibling boundary-touch test covering the un-broken surface, OR
  - (b) flag for deletion if ALL surfaces are vacuous.

For FULLY-SHIMMED SUT (every impl in the call chain is mocked):
- VACUOUS BY DEFINITION.

Sample prioritizes `tests/scheduler/`, `tests/data_collection/`, `tests/tools/`, `tests/safety/`.

**Deletion criteria (DD-18, AND-conjoined):** (a) Pass A flag AND (b) Pass B vacuous AND (c) PR description names a covering substitute.

**Pass-B receipt output (DA8):** T28 produces `docs/audits/2026-XX-XX-test-audit/pass-b-empirical.md` with a `## DELETION_LIST` section. Each row: `file:line: rationale` — T29 cites these in its diff.

### 6.2 Boundary-touch additions (DD-19)

6-seam matrix: DB / Broker / LLM / ripgrep / NSSM / HTTP. Net +15 boundary-touch tests.

### 6.3 Floor handling (DD-20)

**Decision:** Floors HELD — `pg-tests.yml` 5267, CLAUDE.md 5,467. DD-21 defers floor bump post-#95.

**PR-E deletion budget (DA10):** May delete UP TO (PR-D net additions - 5) tests; overflow defers to a Phase-6 PR. Concretely if PR-D nets +20, PR-E may delete up to 15.

### 6.4 Floor-drift remediation (DD-26)

Three-doc drift (README:3,500 / CLAUDE:5,467 / pg-tests:5,267) closed by PR-F. MASTER §2 documents the SQLite-vs-PG-aware delta.

### 6.5 Boundary-Touch 6-Item Checklist (canonical: `docs/standards/boundary-touch-tests.md`)

Every test added or modified in Phase 5 must satisfy:

1. **Mock target resolution** — grep the codebase for the patch path; confirm it resolves to a real callable.
2. **Method/attribute name resolution** — confirm asserted method/attr exists on the real type.
3. **Vacuous-test detection** — answer "would this test fail if impl were deleted?" Yes → keep; No → flag.
4. **Boundary-touch coverage** — for any composed contract (decorators, multi-callee), ≥1 test touches the REAL boundary (not all mocked).
5. **Sibling-search disclosure** — PR description names sibling files searched for the same anti-pattern; "none found" OK if searched.
6. **Standards citation** — module docstring or test docstring cites `docs/standards/boundary-touch-tests.md` for new tests.

T0a in PR-A verifies the standards doc + adds the list to that doc + the PR template if missing.

---

## 7. Sub-Spec — #65 Structure-Debt Sweep (W2 / PR-C) — INLINE

### 7.1 Selection criteria (DD-08)

In-scope subset meets: NOT auto-resolved by W1 + NOT architecturally locked + CLEAN refactor path + NOT active-write surface + tests in place.

**The 8 targeted files (DD-08a, verified 2026-05-27):**

| File | Lines | Refactor approach |
|---|---|---|
| `src/shadow_trading/executor.py` | 3093 | Extract `OrderLifecycle` (~800L), `ReconciliationEngine` (~600L); core ~1,200L |
| `src/notifications/telegram.py` | 1822 | Extract DELIVERY helpers → NEW `telegram_delivery.py` (~500L). Existing `telegram_commands.py` (854L) UNTOUCHED. Core post-split ~1,322L |
| `src/training/trainer.py` | 1530 | Extract `TrainerCheckpoint` → `trainer_checkpoint.py` (~400L); trainer ~1,130L |
| `src/cli/commands.py` | 1531 | Split: `commands_data.py`, `commands_training.py`, `commands_ops.py` (~510L each). Decorator pattern (b) per DD-40 — sub-modules export DECORATED functions; `commands.py` thin re-export |
| `src/risk/governor.py` | 970 | Extract `GovernorAudit` → `governor_audit.py` (~350L); governor ~620L |
| `src/api/routes/system.py` | 761 | Extract status set → `routes/system_status.py` (~370L); system ~390L |
| `src/services/scan_service.py` | 517 (run_scan 401L) | Extract phases to sibling `src/services/_scan_service_impl.py` (per DA9); scan_service ~280-340L, impl ~360L |
| `src/notifications/email_digest.py` | 1236 | 3-module split (MIN per DD-08c): orchestrator ~380L + render ~480L + handover ~250L. Optional 4th collect ~280L. Public API preserved |

**Auto-resolved by W1 (Phase-6 follow-ups per DD-08b):** analytics.py (996L), trades.py (630L), training.py (603L), system_index.py (449L), core.py (533L), kpis_compute.py (401L).

### 7.2 The 400L limit decision (DD-10)

**Keep at 400L.** Limit is focus-discipline, not hard rule. Grandfathered list = soft fence.

### 7.3 `known_violations.json` final prune (rolls into PR-G; DA11)

**Explicit PRUNE enumeration (PR-C T17 removes these 6):** `scan_service.py`, `src/api/routes/system.py`, `governor.py`, `trainer.py`, `cli/commands.py`, `email_digest.py`.

**Explicit GRANDFATHERED-KEPT enumeration:** `shadow_trading/executor.py` (post-split core ~1,200L), `notifications/telegram.py` (post-split ~1,322L). REMAIN in file with Phase-6 sub-target notes.

PR-G adds a sentinel that `known_violations.json` does not contain any file currently under 400L.

### 7.4 Test impact

Refactors are ZERO behavior-change. PR-C verification: `pytest tests/ -q` baseline-equal. Exception: T13 adds `tests/cli/test_cli_decorators_preserved.py` subprocess sentinel (~+6 tests) per DD-40.

### 7.5 Budget overrun fallback (DD-08c, new in r2)

If T16 overruns — defer optional 4th module split (`email_digest_collect.py`) to PR-C2. 3-module shape is MINIMUM acceptable.

---

## 8. Wave Structure + Parallelism

### 8.1 Wave map

```
W0 PR-A (debris + standards) → W1 PR-B (#73) → W2 PR-C (#65) → W3 PR-D (#72) → W4 PR-E (#102) → W5 PR-F (#99 docs) → W6 PR-G (close) → HANDOFF #95
```

### 8.2 Parallelism (DD-29, DD-30)

**Sequential:** PR-A → PR-B → PR-C → PR-D → PR-E → PR-F → PR-G.

**Within-wave parallelism:**
- **PR-C** (3 sub-waves): C-i T10+T11 (high-blast, sequential); C-ii T12+T13 (parallel); C-iii T14+T15+T16 (parallel).
- **PR-D** (3 sub-waves, REVISED r3 per DA1):
  - D-i: T18 (result.py) → T20 (3 canonical collectors macro/edgar/options) — sequential.
  - D-ii: T21 + T22 + T23 + T24 in 4-parallel batches; T25 sequential close.
  - D-iii: T26 (CLAUDE.md §207 + CHANGELOG) sequential; THEN T19 (`_safe_run` flip) as the FINAL commit of PR-D.
- **PR-F:** README + MASTER + DIRECTORY regen + CHANGELOG/RELEASES de-overlap independent.

### 8.3 PR-by-PR scope-fences

Per-PR scope-fences appear in the task graph below.

### 8.4 CHANGELOG Discipline (DA3, new in r3)

7 PRs touch `CHANGELOG.md` `[Unreleased]` over 3-4 weeks. Naive concurrent edits → merge conflicts. Discipline:

- Each PR writes its CHANGELOG entries under a per-PR sentinel marker:
  ```markdown
  ## [Unreleased]
  
  <!-- PR-A entries -->
  ### Added
  - Two new structure rules: test_no_underscore_scratch_at_repo_root + test_no_sqlite_at_repo_root.
  ### Removed
  - 17 _*.py REPL scratch files at repo root.
  <!-- /PR-A entries -->
  
  <!-- PR-B entries -->
  ### Removed
  - src/api/cloud_app.py (#73 render sweep).
  <!-- /PR-B entries -->
  ```
- Hunks under different markers do NOT textually overlap → 0 conflicts across the 7-PR sequence.
- PR-F (T33) unifies the per-PR markers into a versioned `## [v0.36.78]` block + REMOVES the markers as part of the de-overlap step.
- Markers also serve as a per-PR audit trail.

**Merge-calendar capacity (DA12):** 21:30-22:30 ET embargo → ~5 weekday + 2 weekend dead-windows over 3 weeks = ~21 slots; 7 PRs = ~30% utilization. Adequate.

---

## 9. Error Handling Strategy

No new error classes EXCEPT `CollectorResult` (NOT an exception — DD-14). `CollectorPartialFailureError` + `CollectorConfigError` remain. DATABASE_URL strip removes `psycopg2.OperationalError` path; SQLite path covers all post-strip. Sentinels use `pytest.fail()`.

---

## 10. Testing Strategy

**Per-PR test requirements:**

1. `pytest tests/ -q` PASS, count ≥ 5,467 (SQLite-only).
2. `pytest tests/ --pg` PASS, count ≥ 5,267.
3. `pytest tests/test_repo_structure.py -v` PASS.
4. Boundary-touch checklist (per §6.5 and `docs/standards/boundary-touch-tests.md`) for EVERY new test. PR template includes the checklist (added in PR-A T0a).
5. Gold-standard: "would this test fail if impl were deleted?" documented in PR description for PR-D/PR-E adds.
6. Visual-verify for PRs touching frontend paths (PR-B).
7. NSSM smoke-test pre+post for PRs touching `watch.py` or `src/api/*.py` (PR-B, PR-C C-i).

**Cross-cutting test additions:**
- +2 sentinels PR-A (no_underscore_scratch + no_sqlite_at_repo_root)
- +2 sentinels PR-B (test_cloud_app_removed + test_no_database_url_branch at tests/ root)
- +1 sentinel PR-C T13 (tests/cli/test_cli_decorators_preserved.py per DD-40)
- ~+21 tests PR-D (CollectorResult + safe_run routing)
- ~+15 boundary-touch additions PR-E
- net in PR-E may be -10 to 0 (vacuous deletions, capped at +20-5=15 per DA10)
- +1 sentinel PR-F (DIRECTORY.md staleness)
- +1 sentinel PR-G (known_violations.json freshness)

**Total Phase 5 net test additions:** ~+30 to +42 (target SQLite-only 5,497-5,510 post-Phase-5).

---

## 11. Implementation Plan (Task Graph)

See the `plan` JSON below. Summary:

| PR | Wave | Tasks | Est. files | Est. LoC delta |
|---|---|---|---|---|
| PR-A | W0 | T0a, T01–T03 | ~12 | -2,500 code, +210 docs/rules |
| PR-B | W1 | T04–T09 | ~15 | -700 code, +60 tests |
| PR-C | W2 | T10–T17 | ~26 | -200 (splits) + ~6 tests (T13 sentinel) |
| PR-D | W3 | T18, T20–T26, T19 (LAST) | ~52 | +800 (contract + tests) |
| PR-E | W4 | T27–T30 | ~20 | -300 (vacuous, capped) +400 (boundary) |
| PR-F | W5 | T31–T36 | ~12 | -8,000 (archive moves) +1,500 (rewrites) |
| PR-G | W6 | T37–T39 | ~6 | +200 (sentinels) |

---

## 12. Design Decisions Log

See the `design_decisions` JSON array — **42 entries** (36 original + DD-08c (email_digest budget fallback) + DD-15a (CLAUDE.md §207 ownership) added in r2; + DD-37 (CHANGELOG sentinel markers) + DD-38 (Pass-B multi-mock methodology) + DD-39 (boundary-touch checklist embedded) + DD-40 (T13 decorator preservation) + DD-41 (T20-T25 per-task cap raise) added in r3).

---

## 13. Known Considerations + §14 Open Questions

### 13.1 Known Considerations (architect-decided)

- **KC-1..KC-11** preserved from r2 (cloud_routes/render_migrate/render_architecture_doc, watch.py defer, schema registry locked, cloud_routes leftovers, TRAINING_PID, visual-verify pngs, _capability_health out, telegram_commands collision, scan_service path fix).
- **KC-12 (r3, DA9):** T15 scan_service refactor uses sibling `src/services/_scan_service_impl.py` for underscore-private convention consistency. Helpers do NOT live inline in scan_service.py — architect decision.
- **KC-13 (r3, DA10):** PR-E deletion budget capped at (PR-D net additions - 5). Defer overflow vacuous deletions to a Phase-6 PR.
- **KC-14 (r3, DA11):** PR-C T17 prunes exactly 6 known_violations.json entries (§7.3). `shadow_trading/executor.py` and `notifications/telegram.py` REMAIN with Phase-6 sub-target notes.
- **KC-15 (r3, DA12):** Embargo capacity = ~21 slots over 3 weeks vs 7 PRs = ~30% utilization. Adequate.

### 13.2 §14 Open Questions (genuine operator-decisions)

- **OQ-1 (KIN SUBSUMPTION):** Operator-confirms thematic overlap with #125, #126 → PR-G subsumes; else leave open for Phase-6.
- **OQ-2 (TRADING-EMBARGO WINDOW):** Architect recommends dead window (22:30-09:30 ET) for PR-B + PR-D merges.
- **OQ-3 (README AUDIENCE):** Architect recommends operator-only + link to MASTER.md for contributor case.

No other operator-questions surface — all technical forks resolved via DDs.
