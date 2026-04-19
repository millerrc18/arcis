# Capability Registry v1 — Pass 1 Evaluation

**Sprint:** Capability Registry + Home Page Panels v1 (Sprint 1B)
**Branch:** `feat/capability-registry-v1` (off `feat/diagnostic-dashboard-v1@7ca5175`)
**Target tag:** v0.25.0 (bundled with Sprint 1A diagnostic dashboard)
**Pass 1 author:** Claude Code (Opus 4.7, 1M context)
**Pass 1 date:** 2026-04-18
**Status:** No operator gate — proceeding directly to Pass 2 after commit.

---

## 1. Why this design, briefly

The operator has committed that all future code changes flow through AI assistants. Two risks follow:

- **Operator forgetting.** In 3–6 months, what capabilities exist? What's deprecated? What's configured-but-off?
- **AI context fragmentation.** Each session starts with partial context. Critical facts hide in 872-line docs that get skimmed.

The registry is designed to make Halcyon Lab **self-introspecting** — any human or AI querying it gets a canonical, structured, current answer to "what does this system do, and what is its state right now?"

Schema is MCP-compatible so future sessions could expose it as a tool source. That exposure is explicitly not in v1 scope.

---

## 2. R1–R10 satisfaction map

| # | Requirement | Feasibility | Notes / decisions |
|---|---|---|---|
| **R1** | In-process registry populated at import time | ✅ Clean | Mirror `src/platform/plugin_registry.py`: module-level dict, decorator side-effects. `register_plugin` at `plugin_registry.py:19` is the exemplar — same shape, different payload. |
| **R2** | Four specialized registries, one unified index endpoint | ✅ Clean | Four `dict[str, Entry]` stores in `registry.py`, one `/api/system/index` endpoint concatenating them with counts. Bootstrap module (§4.1) triggers imports so registries are populated before the endpoint is called. |
| **R3** | Mandatory metadata schema | ✅ Clean | Pydantic BaseModel per entry type; no optional required fields. Decorator passes kwargs directly into the model constructor — Pydantic validation fires at import time, so a malformed entry crashes app startup. That's the desired behavior per spec. |
| **R4** | CI enforcement | ✅ Clean | Test module iterates over all four registries after forcing the bootstrap import. Fails on incomplete metadata / duplicate names / deprecated-without-replacement. Emits warnings (via `pytest.warns`-equivalent module-level WARNINGS list the dashboard can surface) for stale entries. |
| **R5** | State queries lazy + isolated | ✅ Clean | Registry stores function refs, not values. The endpoint wraps each call in a try/except + 2s timeout (threaded executor with `concurrent.futures.ThreadPoolExecutor.submit(...).result(timeout=2)`). Exceptions become `{"status": "unavailable", "error": msg}`; timeouts become `{"status": "timeout"}`. Other entries unaffected. |
| **R6** | MCP-compatible schema | ✅ Clean | ActionEntry's `input_schema` / `output_schema` validated as JSON Schema at Pydantic-model level using `jsonschema.Draft7Validator.check_schema(...)` inside a field_validator. No full MCP client machinery; just schema-validity checking. |
| **R7** | Delta tracking for "What's New" | ✅ Clean | Sidecar table `operator_view_state(user_id, entry_name, last_viewed_at, last_viewed_value)` — single-operator design means `user_id='operator'` for now. Endpoint computes `delta_since_last_view` in Python after the state query returns; writes the new `last_viewed_value` on GET so subsequent views compute from the latest baseline. Writes are bounded (one row per entry). |
| **R8** | Mark Reviewed ritual | ✅ Clean (v1 scope) | Frontend POST `/api/system/index/{name}/mark-reviewed` updates `last_reviewed_date_override` in `operator_view_state`. v1 reads `max(registry.last_reviewed_date, operator_view_state.last_reviewed_date_override)` when computing stale-ness. Source-file edit automation deferred to v1.1 per spec §5. |
| **R9** | Deprecation requires replacement | ✅ Clean | Pydantic `model_validator(mode='after')` on every entry: `if deprecated and not deprecated_replacement: raise ValueError`. Negative test in CI. |
| **R10** | One endpoint, byte-identical for dashboard + API | ✅ Clean | Dashboard `fetch('/api/system/index')` — no server-side reshaping on the dashboard side. Response is whatever the endpoint returns. CLI and future MCP client hit the same URL. |

**Bottom line:** all ten requirements satisfy cleanly on top of existing patterns. No architectural surprises.

---

## 3. Design alternatives considered and rejected

### 3.1 Why in-code registries, not DB-backed

**Alternative:** Store each capability as a row in `capability_registry` table. Updates via PR-triggered INSERT/UPDATE.

**Why rejected:** DB registries drift. The row says "regime_diagnostic exists and lives at X"; meanwhile someone deletes the function and forgets the DB row. The row-vs-code divergence is undetectable without a reconciler, and the reconciler becomes the new source of drift. Code-colocated decorators cannot drift because the code IS the row — if the function is gone, the decorator is gone, the registry entry is gone.

**Trade-off accepted:** Dashboard loads a bit slower (imports happen at process start, not on request). Mitigated by the bootstrap module deliberately importing everything once, then caching the registry.

### 3.2 Why four specialized registries, not one god-registry

**Alternative:** One `CapabilityEntry` with discriminated union on `kind: Action | State | System | Decision`.

**Why rejected:** Action has `kickoff_endpoint` + `input_schema` + `output_schema` + `estimated_duration`. State has `query_function` + `refresh_hint`. System has `health_check_function` + `expected_runtime`. Decision has `decision_text` + `rationale` + `revisit_trigger`. These are different shapes. A union would force `Optional[...]` on 11 of 15 type-specific fields. Loss of type safety and self-documenting schemas outweighs the "unified iteration" benefit — the endpoint iterates all four registries in a loop anyway.

**Trade-off accepted:** 4× decorator code and 4× model code. Acceptable — the model code is ≈30 lines per type.

### 3.3 Why Pydantic, not dataclasses

**Alternative:** `@dataclass`, hand-rolled validators.

**Why rejected:** Pydantic is already a dependency (`src/api/cloud_routes/platform.py:24`, `src/api/cloud_routes/core.py:41`, `src/api/cloud_routes/diagnostics.py:27`). Field-level and model-level validators are first-class. JSON Schema validation can be plugged in via `field_validator`. The rejection of invalid metadata happens at decorator time with a legible error message instead of a hand-crafted `AssertionError`. Zero new deps.

### 3.4 Why MCP-compatible schema without MCP exposure in v1

**Alternative (a):** No MCP consideration — design whatever shape fits best now, reshape later.
**Alternative (b):** Full MCP server exposure now.

**Why rejected:**

- (a) would force a breaking-change sprint to re-align the schema if/when MCP matters. Cheap insurance against that future cost: write JSON Schema objects that are already valid MCP tool definitions.
- (b) adds a second runtime surface (MCP server over stdio or HTTP), auth, session lifecycle, and documentation that would double the sprint. MCP exposure is genuinely a standalone sprint.

**Trade-off accepted:** A bit of extra discipline around `input_schema` / `output_schema` fields (they must be real JSON Schema, not hand-waves). Validated in CI so the discipline is automatic.

### 3.5 Why bootstrap module, not `from src import *`

**Alternative:** Have `src/__init__.py` import every capability-hosting module.

**Why rejected:** `src/__init__.py` runs on every `from src.foo import bar` anywhere in the codebase. Side-effecting it this way risks circular imports (the capability registry module imports X, X imports Y, Y imports some code that imports from src). A dedicated `src/platform/capability_registry/bootstrap.py` is called explicitly by `app.startup` or `cloud_app` import, and by the metadata-CI test fixture. Explicit > implicit.

---

## 4. Architectural decisions

### 4.1 Bootstrap pattern

Registries populate only when their host module is imported. Two callers need full-registry state:

- FastAPI cloud_app at `/api/system/index` request time
- CI metadata test at test-collection time

Resolution: `src/platform/capability_registry/bootstrap.py::ensure_bootstrapped()` — idempotent function that imports each capability-hosting module once. Side-effects the registries. Returns nothing.

Called from:
- `src/api/cloud_app.py` app-startup event handler (new)
- `src/api/app.py` app-startup event handler (new — local API)
- CI test fixture `conftest.py` at session scope for `tests/test_capability_registry_metadata.py`

Rationale: pytest test collection doesn't import your app. If the bootstrap runs inside a fixture with scope=session and autouse=True in the platform tests directory, the registries populate before any test body runs.

### 4.2 Timeout implementation

Spec R5 requires 2s timeout on state queries. Options:

- **A. `concurrent.futures.ThreadPoolExecutor` with `.result(timeout=2)`.** Portable, stdlib, no signal-handling needed. Downside: a timed-out query keeps running in its thread until natural completion, then the future result is discarded.
- **B. `signal.alarm`.** Unix-only; broken on Windows. The operator runs Windows 11 per CLAUDE.md environment. **Rejected.**
- **C. `asyncio.wait_for`.** Requires all state queries to be `async def`. Most query candidates are synchronous SQLite reads. Forcing async would cascade into the query implementations. **Rejected.**

**Chosen:** A. One shared `ThreadPoolExecutor(max_workers=8)` at module level, 2s per-future timeout. Accept the "timed-out-but-still-running" cost — state queries should be quick reads; if one is pathologically slow, the operator learns via the dashboard timeout and fixes the query.

### 4.3 Delta tracking semantics

Three edge cases, decided per spec's explicit callouts plus one:

- **First view:** no prior state → delta is `null`. Dashboard hides the delta line.
- **Type change:** numeric → string or dict → scalar → delta is `null`. Avoid lying about comparability.
- **Large regression:** `value=20` previously `value=85` → display signed delta (`-65`) with neutral styling. Regression styling is v1.1.
- **New addition — `null` current:** if the query returned `"unavailable"` or `"timeout"`, do NOT update `last_viewed_value`. Preserve the last known-good baseline so the next successful view computes a correct delta.

### 4.4 Stale threshold: **180 days**

Decision made. Rationale:

- 90 days = fresher, but with 18 capabilities initially and growth to ~50 over 2+ years, a 90-day review cycle would mean ~1 review/week forever. That's friction.
- 180 days = 2 review cycles/year/capability. Matches natural sprint cadence. Operator does a "registry refresh afternoon" twice per year.
- Not user-tunable in v1. If the threshold turns out wrong, v1.1 can move it with one line change.

### 4.5 CI behavior for stale entries: **warning-only**

Decision made. Rationale:

- Failure would block unrelated PR merges because a single stale entry flips a checkmark. The operator would either disable the check (defeating it) or force-merge (defeating it).
- Warning surfaces in `pytest -W` output AND in the dashboard's "Needs Review" panel. Visibility without friction.
- Stale entry + no-review = red pill on dashboard. Operator sees it every day until resolved. That's pressure without blocking flow.
- Required-field violations remain hard failures — incomplete metadata is a bug, not a nudge.

### 4.6 18 capability migrations: **all 18**

Decision made. Rationale:

- The migration IS the validation of the abstraction. If one refuses to fit, that's a signal the schema is wrong.
- Per spec "If any refuse to fit the schema cleanly, STOP and report" — I commit to that. If during commits 6-9 one resists, I'll stop and surface rather than force-fit.
- I've pre-reviewed each against the schema:
  - **Actions 1-4:** all have kickoff endpoints (regime, forensic per Sprint 1A's new endpoints; strategy_backtest via `/api/platform/backtests`); `edgar_historical_backfill` is CLI-only so `kickoff_endpoint` is the CLI command string `"python scripts/backfill_edgar.py"` with `ui_kickoff_available=False`. Small schema addendum: `ui_kickoff_available: bool = True` on ActionEntry. Explicit.
  - **States 5-10:** all are SQLite queries or config reads. All fit cleanly.
  - **Systems 11-14:** all have discoverable health signals (PID lockfile, last successful run timestamp, last resolution timestamp, last agent invocation). All fit.
  - **Decisions 15-18:** all are operator-recorded facts. All fit.

### 4.7 MCP v2 exposure: **schema-compatible, not exposed**

Decision made. Rationale:

- ActionEntry's `input_schema` / `output_schema` are valid JSON Schema (Draft 7, the subset MCP expects). No MCP-server plumbing.
- If a future sprint needs MCP exposure, it wraps these schemas with an MCP server (stdio or SSE). No change to the registry data.
- Explicitly preserved future work:
  - MCP tool metadata (`title`, `description` already present; `parameters` → map from `input_schema`)
  - Tool invocation → call `kickoff_endpoint` (POST) or `query_function` (direct)

This note locked here so future sessions reading this doc don't rebuild the schema.

---

## 5. Identified risks

### R5.1 — Module-load ordering at import time [MEDIUM]

**Problem:** A decorator running at import time can raise (Pydantic rejects metadata). If the raising module is imported by `src/api/app.py` at startup, the entire app fails to boot.

**Mitigation:**
- `bootstrap.py` wraps each import in try/except, logs a clear `CAPABILITY_REGISTRY_BOOTSTRAP_ERROR` with the module name and exception, and re-raises at the end if any failed. Boot-time crash with a legible stack trace is the correct outcome — the whole point of R4 is "bad metadata = fail loudly."
- CI runs `bootstrap` under the CI metadata test fixture. If a PR breaks the registry, tests fail before merge.

### R5.2 — Circular imports [LOW]

**Problem:** Capability modules import from `src.platform.capability_registry`. If something in the registry package imports from a capability module, a cycle forms.

**Mitigation:** Registry package depends only on stdlib + pydantic + jsonschema. No imports from domain modules. Enforced by a CI test (tests/test_capability_registry.py::test_no_domain_imports_in_registry).

### R5.3 — Registry duplication via re-import [LOW]

**Problem:** If a decorator fires twice for the same name (e.g., a module is re-imported), the duplicate check would reject the second registration — breaking reload during development.

**Mitigation:** Decorator checks `if name in registry and registry[name] is not the new entry` to allow idempotent re-registration (same signature = no-op). Add a narrow test.

### R5.4 — State query writes during reads [MEDIUM]

**Problem:** The `/api/system/index` endpoint updates `operator_view_state.last_viewed_value` on GET. If two browsers open the dashboard concurrently, the second read uses the first's freshly-written value as baseline — delta = 0 even though state changed between opens.

**Mitigation:**
- Single-operator system (CLAUDE.md: Local API binds 127.0.0.1). The two-browser-concurrent case is already rare.
- Update is a single UPSERT per entry; a brief inconsistency window doesn't corrupt state.
- If it matters later: read-then-update at request time, or make last-viewed-update an explicit POST (`/mark-viewed`) rather than a GET side-effect. v1 accepts the read-with-side-effect; documented as known edge case.

### R5.5 — Timeout thread pool starvation [LOW]

**Problem:** `ThreadPoolExecutor(max_workers=8)` — if 8 state queries time out simultaneously, the 9th waits. With ≤10 state entries in v1 this is essentially impossible; noted for when registries grow.

**Mitigation:** Accept for v1. Monitor pool saturation in observability at v0.26 if registries pass 20 entries.

### R5.6 — Pydantic-v2 strictness [LOW]

**Problem:** Project may be on Pydantic v1 or v2. Syntax differs (`field_validator` vs `validator`).

**Mitigation:** Pass 2 will grep `pydantic` imports and version. If v1, adapt; if v2, native. Schemas will use v2-compatible idioms that degrade cleanly.

### R5.7 — `operator_view_state` sync to Postgres [LOW]

**Problem:** New SQLite table with `created_at` will auto-sync to Render per schema registry conventions. The sync isn't meaningful (operator reviews happen locally) and adds noise to cloud.

**Mitigation:** Set `sync_to_postgres=False` in the `operator_view_state` TableDef. Tested.

### R5.8 — JSON Schema validation cost at import [LOW]

**Problem:** `jsonschema.Draft7Validator.check_schema(...)` runs for each Action at import time.

**Mitigation:** Fast enough (microseconds per schema). Not measuring.

### R5.9 — Cloud app vs local app registry divergence [MEDIUM]

**Problem:** Cloud app and local app may import different capability modules. State queries that hit SQLite would fail in cloud mode (no local DB). System registrations might refer to processes only running locally (watch_loop).

**Mitigation:**
- `bootstrap.py` imports *all* capability modules. The registry is the same in both environments.
- Query functions that need SQLite check for `DB_PATH` availability and return `{"status": "unavailable", "reason": "not_local_environment"}` when running cloud-side.
- Health checks for purely-local systems (watch_loop) return the same `unavailable` status when run cloud-side — consistent with R5.

### R5.10 — `last_reviewed_date` drift vs source file [LOW]

**Problem:** Spec §R8 defers source-file update to v1.1. v1 stores overrides in `operator_view_state.last_reviewed_date_override`. A fresh checkout of the repo has no override — dashboard stale panel re-lights until override is re-clicked.

**Mitigation:** Accept for v1. Document that "Mark Reviewed is local state." The v1.1 source-file automation fixes this.

---

## 6. Explicit non-goals (v1)

Copied from spec and committed:

- **No MCP server exposure.** Schema compatibility is enough. (See 4.7.)
- **No source-file PR automation for Mark Reviewed.** Local state only. (v1.1.)
- **No search / filter UI on System Index.** Scrollable grouped list. (v1.1.)
- **No capability dependency graph.** (v3+.)
- **No auth on kickoff endpoints beyond what exists.** Operator-only API.
- **No regression styling on delta tracking.** Just signed numbers. (v1.1.)

---

## 7. Implementation sequence (binding)

1. This doc (Pass 1) — commit
2. `capability_registry_v1_research_findings.md` (Pass 2) — commit
3. Commit 3: `src/platform/capability_registry/schemas.py` + `tests/platform/test_capability_registry_schemas.py`
4. Commit 4: `src/platform/capability_registry/registry.py` + `bootstrap.py` + `tests/platform/test_capability_registry.py` (≥12 tests)
5. Commit 5: `tests/test_capability_registry_metadata.py` (baseline with 0 entries)
6. Commit 6: `operator_view_state` TableDef in `src/schema/registry.py` + `validate-schema --fix`
7. Commit 7: `src/api/cloud_routes/system_index.py` + `tests/api/test_system_index.py`
8. Commit 8: Register 4 Actions (regime_diagnostic, forensic_trade_audit, strategy_backtest, edgar_historical_backfill)
9. Commit 9: Register 6 States (shadow_trade_cohort, strategy_registry_state, training_corpus, bootcamp_mode, alpaca_account, ollama_model)
10. Commit 10: Register 4 Systems (watch_loop, reconcile_trades, attribution_resolver, nightly_audit_agent)
11. Commit 11: Register 4 Decisions (bootcamp_still_active, pullback_strategy_contaminated, lazy_prices_deprecated_on_sp100, no_new_strategy_specs_until_walkforward_ships)
12. Commit 12: Frontend — SystemIndexPanel + QuickStatsPanel + WhatsNewPanel + `api.js::getSystemIndex`
13. Commit 13: Frontend — CapabilityDetailModal + Mark Reviewed POST flow
14. Commit 14: Integration test + MASTER.md + `docs/capability_registry.md` + CHANGELOG v0.25.0 + PR

---

## 8. Files Pass 2 will verify / Pass 3 will touch

### Create
- `src/platform/capability_registry/__init__.py`
- `src/platform/capability_registry/schemas.py`
- `src/platform/capability_registry/registry.py`
- `src/platform/capability_registry/bootstrap.py`
- `src/api/cloud_routes/system_index.py`
- `tests/platform/test_capability_registry_schemas.py`
- `tests/platform/test_capability_registry.py`
- `tests/test_capability_registry_metadata.py`
- `tests/api/test_system_index.py`
- `frontend/src/components/system/SystemIndexPanel.jsx`
- `frontend/src/components/system/SystemIndexCard.jsx`
- `frontend/src/components/system/SystemIndexCategory.jsx`
- `frontend/src/components/system/WhatsNewPanel.jsx`
- `frontend/src/components/system/QuickStatsPanel.jsx`
- `frontend/src/components/system/CapabilityDetailModal.jsx`
- `docs/capability_registry.md`

### Modify
- `src/schema/registry.py` (+ `operator_view_state` TableDef)
- `src/api/cloud_app.py` (register `system_index` router + bootstrap on startup)
- `src/api/app.py` (bootstrap on startup — local)
- `src/diagnostics/regime_diagnostic.py` (`@register_action`)
- `src/diagnostics/forensic_trade_audit.py` (`@register_action`)
- `src/platform/backtest_persist.py` or similar (`@register_action` for backtest)
- EDGAR backfill home module (`@register_action`)
- `src/shadow_trading/models.py` or service (`@register_state`)
- `src/platform/promotion.py` or strategy registry query module (`@register_state`)
- `src/training/...` (`@register_state`)
- `src/services/review_service.py` or config (`@register_state` bootcamp)
- `src/shadow_trading/alpaca_adapter.py` (`@register_state` alpaca account)
- `src/llm/ollama.py` or similar (`@register_state` ollama model)
- `src/main.py` or watch loop module (`@register_system`)
- Reconcile module (`@register_system`)
- Attribution resolver module (`@register_system`)
- Nightly audit module (`@register_system`)
- Decision declarations live in `src/platform/capability_registry/decisions.py` (new — decisions aren't naturally attached to code, so one home file is acceptable; see 8.1)
- `frontend/src/pages/Dashboard.jsx`
- `frontend/src/api.js`
- `CHANGELOG.md` (v0.25.0 section)
- `docs/MASTER.md` (pointer to `/api/system/index`)

### 8.1 — Decision home

Unlike Actions/States/Systems, Decisions don't have a natural code home (they're strategic facts, not behaviors). Creating `src/platform/capability_registry/decisions.py` is acceptable — the module serves as the registration point and imports a `register_decision` call for each. Spec R1 is about registries living in-process at import time, which this satisfies. It does not mandate physical co-location with domain behavior for every entry type.

If future sessions disagree, alternative home is `docs/decisions/*.py` — but that pollutes `docs/` with Python. v1 uses `src/platform/capability_registry/decisions.py`.

---

## 9. Pass/fail criteria (self-check at Pass 3)

1. All four decorators exposed from `src/platform/capability_registry/__init__.py`.
2. Bootstrap module deterministically populates registries; calling twice is a no-op.
3. `/api/system/index` returns 18+ capabilities with counts by category.
4. CI test `tests/test_capability_registry_metadata.py` passes.
5. Delta computation works: synthetic test writes two sequential `last_viewed_value`s, asserts delta.
6. Deprecation negative test: creating an entry with `deprecated=True` and no `deprecated_replacement` raises at import time.
7. JSON Schema validity test for all ActionEntry entries.
8. Dashboard renders three panels and opens Detail Modal + Mark Reviewed round-trips.
9. Full pytest green. No new guardrail violations. `npm run build` clean.

---

## 10. Pass 2 commitments

Pass 2 will concretely verify (by reading code, not speculation):

1. `@register_plugin` decorator shape (`src/platform/plugin_registry.py:19`) — confirm my mirror is correct.
2. Pydantic version in use — affects `field_validator` syntax.
3. FastAPI route registration conventions for a new `cloud_routes/*.py` module — confirm my factory signature (`create_router(runtime, verify_auth)`) matches existing patterns.
4. `src/schema/registry.py` TableDef — confirm `sync_to_postgres=False` path and that adding a table with string primary key Just Works.
5. Existing state-query candidates — which already have queryable helpers, which need thin wrappers.
6. Watch loop PID lockfile read — confirm the health-check can stat the file safely.
7. CHANGELOG structure — confirm the v0.25.0 `[Unreleased]` section is the right insertion point.
8. CI test framework — confirm `tests/test_repo_structure.py` patterns for module-traversal-style tests.

Pass 2 will commit findings and note any required revisions to this evaluation.

---

## 11. Summary

Design is straightforward, leveraging existing decorator patterns. Four Pydantic models, four module-level dicts, one endpoint, one table. The 18-capability migration is the expensive part of the sprint and serves as the abstraction's acceptance test.

No operator-input dependencies were identified. Proceeding to Pass 2.
