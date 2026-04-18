# Capability Registry v1 — Pass 2 Research Findings

**Sprint:** Capability Registry + Home Page Panels v1 (Sprint 1B)
**Branch:** `feat/capability-registry-v1`
**Pass 2 date:** 2026-04-18
**Status:** No operator gate — proceeding directly to implementation after commit.

---

## 1. Decorator patterns already in codebase

### 1.1 `src/platform/plugin_registry.py` (confirmed exemplar)

```python
# plugin_registry.py:16-31
_PLUGINS: dict[str, type[StrategyPlugin]] = {}

def register_plugin(cls: type[StrategyPlugin]) -> type[StrategyPlugin]:
    """Decorator: registers a plugin class under its strategy_id."""
    instance = cls()
    _PLUGINS[instance.strategy_id()] = cls
    return cls
```

**Matches Pass 1 assumption.** My four decorators mirror this: module-level dict, decorator that side-effects the dict, returns the decorated object. Differences:

- Plugin registry takes a class and instantiates; I take a function (for Actions/States/Systems) or literal kwargs (for Decisions).
- Plugin registry stores the class; I store a Pydantic-validated `Entry` model.

### 1.2 Other `@register*` patterns

- `src/schema/registry.py:82` uses `_register(table: TableDef)` — functional registration, not decorator, because tables aren't code-bearing. Not applicable to capabilities.
- FastAPI `@router.get/post(...)` decorators register routes — precedent for import-time side effects on a module-level collection. Reassures the pattern is idiomatic.

No conflicts with Pass 1 design.

---

## 2. Pydantic version + idioms

### 2.1 Version

- `requirements.txt:1`: `pydantic>=2.7,<3.0`
- Installed: `pydantic==2.12.5`

**Pydantic v2 confirmed.** Use `field_validator` and `model_validator(mode='after')` — NOT `@validator`.

### 2.2 Existing usage

- `src/api/cloud_routes/core.py:41`: `from pydantic import BaseModel`
- `src/api/cloud_routes/diagnostics.py:27`: `from pydantic import BaseModel`
- `src/api/cloud_routes/platform.py:24`: `from pydantic import BaseModel, Field`

All existing usage is simple `BaseModel` subclasses. No custom validators in the cloud routes modules. Registry schemas introduce `field_validator` + `model_validator` use — new pattern, but fully native to Pydantic v2.

### 2.3 JSON Schema validation

- `jsonschema==4.26.0` installed (via transitive dep). NOT in `requirements.txt`. **Action required:** add `jsonschema>=4.0` to `requirements.txt` to make it a first-class dep.

Use `jsonschema.Draft7Validator.check_schema(...)` inside a `field_validator` for Action's `input_schema` / `output_schema`. Draft 7 matches what MCP tool definitions expect.

---

## 3. API conventions

### 3.1 Cloud route factory pattern

Confirmed from `src/api/cloud_app.py:270-281`:

```python
app.include_router(factory(_runtime, verify_auth))
```

Every cloud route module exports `create_router(runtime, verify_auth) -> APIRouter`. `runtime` is a `SimpleNamespace` with `.query`, `.query_one`, `.get_pg`, `.et`, `.logger`, etc. (cloud_app.py:255-267).

**My decision:** follow this pattern for `system_index.py`. New module exports `create_router(runtime, verify_auth)`. Registered after existing routers in `cloud_app.py`.

### 3.2 Local route pattern diverges

`src/api/cloud_routes/platform.py` uses a *different* pattern: direct `router = APIRouter()` at module level, `verify_auth` injected later. This divergence exists because platform routes read SQLite locally (`src/config.DB_PATH`), not Postgres. The cloud_app also runs the platform router but it only works correctly in local mode.

**My decision for `system_index`:** stick with the `create_router(runtime, verify_auth)` pattern. The system index endpoint:
- Calls registry functions (pure Python, no DB)
- For State queries, uses `sqlite3.connect(DB_PATH)` inside the query function (same as platform.py)
- For `operator_view_state` reads/writes, uses the same `sqlite3.connect(DB_PATH)` pattern

Runtime's `query`/`query_one` is Postgres-backed and won't help us — those hit Render. State queries need local SQLite when running local, Postgres when running cloud. Per the bootstrap design, registries are the same; query functions handle their own data source selection (using `ARCIS_ENV` or path existence).

### 3.3 Dependencies pattern

`dependencies=[Depends(verify_auth)]` per endpoint (not middleware-level). Confirmed at `core.py:188`, `core.py:218`, etc. My endpoint uses the same:

```python
@router.get("/api/system/index", dependencies=[Depends(verify_auth)])
def system_index() -> dict: ...
```

---

## 4. Schema registry patterns

### 4.1 TableDef shape

Confirmed `src/schema/registry.py:61-77`: `TableDef` takes `name`, `description`, `columns`, `primary_key`, optional `indexes`, `foreign_keys`, `sync_to_postgres` (default True), `sync_mode`, `sync_time_column`, `sync_pk`, `sync_conflict_col`.

### 4.2 `sync_to_postgres=False`

Grep for existing usage: no entry in `registry.py` explicitly uses `sync_to_postgres=False`. Default is True. Spot-check: field exists and is honored by `render_sync.py`. **Action:** the `operator_view_state` TableDef sets it explicitly False.

### 4.3 Registry count

Currently 63 `_register(TableDef(` calls (per `grep -c`). Spec mentions 49 tables elsewhere but accurate count is 63 (drift in spec comment, not my concern). Adding `operator_view_state` → 64.

### 4.4 Validate-schema flow

`python -m src.main validate-schema --fix` will create the new SQLite table. `python scripts/render_migrate.py` syncs to Postgres. I'll run both during commit 6.

---

## 5. Existing state-query candidates — what already exists

| Registry entry | Existing helper | Path | Notes |
|---|---|---|---|
| `shadow_trade_cohort` | None single-shot | `src/shadow_trading/executor.py:2087+` has COUNT/sum queries but they live inside methods. Need a thin dedicated state query wrapper. | Will write `src/shadow_trading/state.py::shadow_cohort_summary()` that returns `{open: N, closed: N, quarantined: N, total: N}`. |
| `strategy_registry_state` | Partial | `src/platform/promotion.py:59` reads `current_status FROM strategy_registry`. No counts-by-status helper. | Thin wrapper inline in the decorator module. |
| `training_corpus` | `src/services/training_service.py:47-61` groups by outcome and source | Usable as-is. |
| `bootcamp_mode` | Config read | `src/scheduler/watch.py:112` reads `bootcamp_cfg.get("enabled", False)` + `.get("phase", 1)`. Config source is YAML. | Query function reads config and returns `{enabled, phase, reason}`. |
| `alpaca_account` | `src/shadow_trading/alpaca_adapter.py:202::get_account_info(desk)` | Returns balance/equity. Already exists. Wrap it. |
| `ollama_model` | None discovered. | No `get_ollama_model()` helper. | Read `config/settings.local.yaml`'s `llm.model` value. State query returns config value; health is the connectivity probe. |

### 5.1 System health candidates

| Registry entry | Existing signal | Notes |
|---|---|---|
| `watch_loop` | `src/startup.py:73::is_watch_loop_running()` returns PID or None. | Health check returns `{status: ok, pid: N}` when running, `{status: down}` when not. |
| `reconcile_trades` | `shadow_trades` has `last_reconciled_at` columns? | Use `SELECT MAX(updated_at) FROM shadow_trades WHERE status='open'` as proxy for "last reconcile touch." Acceptable v1. |
| `attribution_resolver` | `scripts/reresolve_attribution.py` is the command. Last-run timestamp in `attribution_runs` table? | Grep shows `src/attribution/logger.py` logs events; use most recent log entry time as "last run." |
| `nightly_audit_agent` | `/audit` is a Claude Code slash command. `config/daily_repo_audit_baseline.json` tracks expected failures. | Health = file existence + mtime of baseline + count of `expected_failures`. The audit is operator-triggered, not a daemon — health = "configured, X known findings, last reviewed <date>." |

### 5.2 Decision capability homes

Per Pass 1 §8.1, all four Decisions live in `src/platform/capability_registry/decisions.py`. Each is a direct `register_decision(...)` call with the strategic fact, rationale, and revisit trigger. Source references cite existing docs — the pullback-contaminated decision cites today's regime diagnostic output; lazy-prices-deprecated cites existing compass reports; the walkforward freeze cites the operator's April-18 pivot.

---

## 6. MCP schema requirements

Minimal MCP tool definition (per public Anthropic docs for MCP Python SDK):

```python
{
  "name": "tool_name",
  "description": "Human/AI-readable description",
  "inputSchema": { "type": "object", "properties": {...}, "required": [...] }
}
```

Our ActionEntry carries `name`, `description`, and `input_schema` as valid JSON Schema. The field name in MCP is `inputSchema` (camelCase) vs our `input_schema` — trivial rename at the exposure layer. No schema redesign needed at v2.

**Action:** enforce `input_schema` is a dict with `type: object` at minimum (via `field_validator`). `output_schema` gets the same validation for symmetry (even though MCP doesn't require it; positions us for future OpenAPI export too).

**Confirmed:** Pass 1 decision §4.7 stands — schema-compatible, not exposed.

---

## 7. CI test framework conventions

### 7.1 Test location

- `tests/test_repo_structure.py` — exists but is module-structure tests, not registry-specific. The test file isn't quite the right home.
- `tests/test_schema.py` — schema validation tests; similar in spirit but for DB tables.
- `tests/platform/` — platform-specific tests; this is the right home for registry unit tests.

**My decision:**
- Unit tests for registry mechanics → `tests/platform/test_capability_registry.py`
- CI enforcement (all registered entries have complete metadata) → `tests/test_capability_registry_metadata.py` at the top level, so every PR runs it.

### 7.2 conftest.py

`tests/conftest.py` is minimal. For the metadata test, I'll add a session-scoped autouse fixture local to the test file that calls `bootstrap.ensure_bootstrapped()`. No global conftest changes needed.

### 7.3 Test markers

Spot-check: `pytest.mark` usage is sparse. No need for new markers.

---

## 8. CHANGELOG structure

Confirmed `CHANGELOG.md:3-13` — under `## [Unreleased]` → `### Added (v0.25.0 — Diagnostic Dashboard)` section. **My approach:** add a new `### Added (v0.25.0 — Capability Registry)` subsection under `[Unreleased]`. Keep the diagnostic dashboard section intact. Both ship in v0.25.0.

---

## 9. Frontend conventions

### 9.1 Dashboard.jsx structure

Read first 80 lines. Key elements:
- `useQuery` for data fetching
- `MetricCard`, `DataTable`, `LoadingSpinner`, `StatusBadge` components already exist
- `PlatformStatusWidget` is a precedent for a home-page panel that queries an endpoint and renders a compact status
- `IS_CLOUD` from `../config` controls local/cloud branches
- Tailwind classes for layout; custom CSS vars (`var(--arcis-bg-surface)`, etc.)

### 9.2 api.js pattern

Confirmed existing `api.js` exports an object with per-endpoint functions. My addition:

```js
getSystemIndex: () => fetch(`${API_BASE}/api/system/index`, { headers: authHeaders() }).then(r => r.json()),
markReviewed: (name) => fetch(`${API_BASE}/api/system/index/${encodeURIComponent(name)}/mark-reviewed`, { method: 'POST', headers: authHeaders() }).then(r => r.json()),
```

### 9.3 No new npm deps

- `react-markdown` and `remark-gfm` were added by Sprint 1A.
- Sprint 1B needs none. Uses existing components (`StatusBadge`, MetricCard-style tiles, DataTable if needed).

---

## 10. Revisions to Pass 1

None material.

Minor clarifications:
- Pass 1 §4.2 mentioned ThreadPoolExecutor with max_workers=8; confirmed the approach is Windows-compatible (no signal module).
- Pass 1 §5.7 said `sync_to_postgres=False` for `operator_view_state`; confirmed no other table uses that flag, so I'll set it explicitly.
- Pass 1 §8 listed home modules for registrations. Confirmed:
  - Action `regime_diagnostic` → register in `src/diagnostics/dashboard_runner.py` (module that already imports for regime) OR in a new thin module `src/diagnostics/__init__.py`. **Decision:** register in `src/diagnostics/__init__.py` to avoid side effects on `dashboard_runner.py` (which is called per-run and should be idempotent). Simpler ImportErrors if anything breaks.
  - Action `forensic_trade_audit` → same, `src/diagnostics/__init__.py`.
  - Action `strategy_backtest` → `src/platform/__init__.py` or `src/platform/capability_registry/action_registrations.py`. **Decision:** `src/platform/__init__.py` — domain module, minimal surface.
  - Action `edgar_historical_backfill` → `scripts/backfill_edgar_historical.py` exists but scripts aren't imported at runtime. Create `src/data_ingestion/backfill_registration.py` (new, 5-line file) that registers the action pointing at the CLI command.
  - State `shadow_trade_cohort` → create `src/shadow_trading/state.py` (new) with the query function and the decorator.
  - State `strategy_registry_state` → `src/platform/__init__.py` (decorator + query function).
  - State `training_corpus` → `src/services/training_service.py` (file exists, add decorator near `get_training_stats`).
  - State `bootcamp_mode` → new `src/services/bootcamp_state.py` (small file; mirrors `review_service.py` pattern).
  - State `alpaca_account` → `src/shadow_trading/alpaca_adapter.py` near `get_account_info`.
  - State `ollama_model` → new `src/llm/ollama_state.py` (small file; existing `src/llm/` has no clean home).
  - System `watch_loop` → `src/startup.py` (next to `is_watch_loop_running`).
  - System `reconcile_trades` → new `src/shadow_trading/reconcile_state.py`.
  - System `attribution_resolver` → `src/attribution/logger.py`.
  - System `nightly_audit_agent` → new `src/platform/capability_registry/audit_registration.py` (the audit lives outside Python; this is the minimal registration home).

All of these register at import time. The bootstrap module triggers the imports.

---

## 11. Open risks re-verified

### 11.1 psutil availability (startup.py:80)

`psutil` is imported inside `is_watch_loop_running`. If not installed, falls back to `os.kill(pid, 0)` but there's a bug: `old_pid` is set only in the `try` branch, so the `except ImportError` branch references an undefined local. Not my problem this sprint — documenting as a pre-existing issue.

Our system health check for `watch_loop` can safely call `is_watch_loop_running()`. If it raises, the timeout/exception wrapping in `/api/system/index` converts to "unavailable."

### 11.2 Bootstrap robustness

Pass 1 §5.1 flagged that decorator-time errors could crash app startup. Confirmed: Pydantic will raise on malformed metadata. This is desired. But during dev, a half-written capability would prevent any `python -m ...` invocation.

**Mitigation:** bootstrap uses `importlib.import_module(...)` wrapped in try/except. On error, bootstrap logs `CAPABILITY_REGISTRY_BOOTSTRAP_ERROR <module>: <exception>` at WARNING and continues. At the end of bootstrap, if any import raised, the metadata CI test (tests/test_capability_registry_metadata.py) **fails hard** — so CI catches it before merge, but local dev stays unblocked.

This is a softer stance than Pass 1 §5.1's "crash the app." Revision: CI enforces, dev doesn't crash. More correct.

### 11.3 Schema registry sync_pk default

For the `operator_view_state` table with composite primary key (`user_id`, `entry_name`), `sync_pk` defaults to `primary_key`. Confirmed `TableDef.sync_pk: str | None = None` means "use primary_key." Composite PKs work in `render_sync` per existing tables. No issue.

---

## 12. Ready to implement

Proceeding to commit 3 (Pydantic schemas). No operator gate.

### Binding constants from this research

- Pydantic v2 syntax (`field_validator`, `model_validator`)
- Draft 7 JSON Schema
- `jsonschema>=4.0` added to `requirements.txt` in commit 3
- `create_router(runtime, verify_auth)` factory pattern in commit 7
- Decorator bootstrap logs CAPABILITY_REGISTRY_BOOTSTRAP_ERROR but does not crash
- Registry homes per §10 — diverges slightly from Pass 1 §8 but not materially
