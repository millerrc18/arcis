# Capability Registry Refresh + Anti-Drift CI Guards — Design Spec (Rev 1)

**Target:** `C:/arcis/halcyon-lab` · `src/platform/capability_registry/`
**Goal:** Refresh the live ledger from **19 → exactly 80** entries reflecting platform reality, and replace the frozen `assert total >= 18` snapshot with **5 structural CI guards (A–E)** that derive the *expected* capability set from live code, making future drift a hard CI failure.
**Constraints honored:** Pydantic-valid metadata (fails at import), every new host module added to `CAPABILITY_MODULES`, follow existing patterns, do not break the 19 existing entries, avoid import cycles, do NOT register transport/route handlers, refresh `last_reviewed_date` on new entries, no DB schema change.

**Rev-1 changelog (what changed vs the reviewed draft and why):**
- **DA-1 (count):** Headline, dial-back prose, and per-family task keep-sets now all derive to ONE number — **80** (19 existing + 47 structural + 14 heterogeneous). The heterogeneous keep-set was trimmed from 25 → 14 (option (a)); the trimmed 11 move to an explicit deferred backlog. CI floor is `>= 80`.
- **DA-2 (coverage overclaim, most important):** §5 now states the guarded-vs-unguarded fraction explicitly, and adds **Convention E** — a per-capability-package presence guard that gives the ~33 previously-unguarded heterogeneous + existing entries a structural anti-drift check. The claim is calibrated: E closes module-granularity drift; the residual (a new function inside an already-registered module) is named honestly.
- **DA-3 (cosmetic ACTIONs):** Option (a) — a real `scripts/run_watch_handler.py` CLI dispatcher is added (with a smoke test), and every handler ACTION gets a real non-empty `input_schema` (`at`, `force`). This also resolves F-min-1.
- **DA-4 (Convention C fragility):** Convention C now enumerates gate **definitions** (the `GOVERNOR_GATES` tuple), never a `check_trade` dry-run (verified short-circuit at governor.py:613/680 makes a dry-run un-buildable). The companion test asserts `set(_GATE_META) == set(GOVERNOR_GATES)` (F-min-2) plus a static source-scan that the tuple matches the literal gate names present in `governor.py`.
- **Minors:** A-oracle collision + plain-`maybe_`-fn assertions; engine-SYSTEM degrade-not-raise (bare-env health test); Convention B EXEMPT docstring; Convention D regex broadened to catch the functional `register_x(...)` call form used by the new en-bloc loop modules.

---

## 1. Overview

The capability registry is four import-time decorator dicts (`ACTIONS`, `STATES`, `SYSTEMS`, `DECISIONS`) in `src/platform/capability_registry/registry.py`, validated by Pydantic models in `schemas.py` (`BaseEntry` requires `name`/`description`/`category`/`version`/`maintainer`/`introduced_in`/`last_reviewed_date`; `kind` is auto-injected per decorator, NOT a caller field), populated by importing the modules listed in `bootstrap.py:CAPABILITY_MODULES` (currently 14). The endpoint `GET /api/system/index` renders them.

The ledger froze in mid-April (every entry carries `last_reviewed_date = date(2026,4,18)`) while the platform grew. The frozen guard `test_18_capabilities_registered` (`assert total >= 18`, at integration test lines 88 AND 128 — two assertions) can never detect a new undecorated feature.

This design does two things:
1. **Refresh** — register the three firm structural sets (16 watch handlers → ACTIONS; 18 `*_collector.py` modules → SYSTEMS; 11 governor gates + governor SYSTEM + drawdown DECISION → 13 DECISION/SYSTEM) plus a trimmed, highest-value heterogeneous keep-set across execution, scan→LLM→council, training, eval/audit, notifications — landing **exactly 80** entries.
2. **Anti-drift** — implement 5 structural guards (A–E) as **hard** (merge-blocking) tests whose oracles live next to the code they watch. The operator's purpose is *"so I don't lose sight of platform features"*; §5 is explicit about which fraction is structurally guarded and what residual surface remains.

### Ground-truth corrections (verified by reading the code; supersede inventory §5 drafts)

| Item | Inventory §5 said | **Actual (verified this pass)** | Design consequence |
|---|---|---|---|
| Collector count | "24 collectors" | **18** modules match `src/data_collection/*_collector.py` (glob enumerated) | Convention B targets exactly 18; `short_volume_finra.py`/`options_metrics.py`/`retention.py`/`research_synthesizer.py` are NOT in the glob set |
| Convention B `EXEMPT` | `{_finnhub_shared, errors, retention, research_synthesizer}` | None of those end in `_collector`, so they were never glob candidates | `EXEMPT` starts **empty** (documented future hook) |
| Governor gate names | `volatility`, `duplicate_position` | emitted `"name"` strings are **`volatility_halt`** (governor.py:805), **`duplicate`** (:820) | `GOVERNOR_GATES` + DECISION names use the *emitted* names → `gate_volatility_halt`, `gate_duplicate` |
| Convention A naming | §3b proposed prettier names (`model_stress_test`, `intraday_bar_collection`) | guard does pure `maybe_`-strip → `stress_test`, `1min_bar_collection` | **Registered ACTION name MUST equal the stripped handler name** or A fails; §3b cosmetic names dropped |
| `check_trade` emission | implied a dry-run could harvest all gate names | **short-circuits**: governor.py:613 `governor_disabled` early-return (1 check only); :680 `emergency_halt` rejects before later gates append; `traffic_light` only appends when multiplier<1.0; `event_risk`/`position_size` have conditional branches | **No single fixture emits all 11** → Convention C MUST enumerate definitions, not dry-run output (DA-4) |
| `scripts/run_watch_handler.py` | referenced as the kickoff endpoint | **does not exist** | Must be created as a real CLI dispatcher (DA-3) |

These are load-bearing: getting any wrong makes the corresponding guard fail against its own registrations.

---

## 2. Architecture

### 2.1 New modules (registration anchors + helpers + guards + dispatcher)

| New file | Purpose | In `CAPABILITY_MODULES`? |
|---|---|---|
| `src/data_collection/_capability_health.py` | Shared `table_freshness_health(table, ts_col, stale_after_minutes, cadence_label)` helper used by all 18 collector SYSTEMs | No (helper, not a host) |
| `src/data_collection/capability_registration.py` | Registers the 18 collector SYSTEMs en-bloc via a metadata table (collectors stay logic-only) | **Yes** |
| `src/scheduler/handler_registration.py` | Imports `ALL_HANDLERS`, registers each as an ACTION via a per-handler metadata table; name = `maybe_`-stripped handler name (Convention A oracle) | **Yes** |
| `src/risk/gate_decisions.py` | Registers the 11 governor-gate DECISIONs en-bloc, driven by `src.risk.governor.GOVERNOR_GATES`; also `risk_governor` SYSTEM + `decision_drawdown_adjusted_risk` (Convention C oracle) | **Yes** |
| `src/platform/capability_registry/_io_schemas.py` | `simple_io_schema(properties, required)` builder returning MCP-valid Draft-7 `{type:object,...}` for ACTION input/output | No (helper) |
| `scripts/run_watch_handler.py` | **(DA-3)** Real CLI dispatcher: `--list` enumerates `ALL_HANDLERS`; `--handler <name> [--at ISO] [--force]` imports + invokes the named handler against a constructed `WatchLoop`. This is the genuine `kickoff_endpoint` for the 16 handler ACTIONs | No (CLI entry, not a registration host) |
| `src/{shadow_trading,llm,council,training,evaluation,notifications}/capability_registration.py` | Thin per-package hosts for the heterogeneous keep-set (used when the logic module's top-level import graph is heavy/cyclic) | **Yes** (each) |
| `tests/test_capability_registry_coverage.py` | The 5 structural guards (A–E) + health/query-executes test + C-companion completeness | n/a (test) |

### 2.2 The two homogeneous families use metadata-table-driven loops

For the 18 collectors and the 11 gates, hand-authoring 18+11 decorator blocks is high-burden and error-prone. A single module per family declares a metadata table and loops. **These loops call the registrar in its FUNCTIONAL form** (`register_system(...)(fn)`, `register_decision(...)`), NOT the `@`-decorator form — which is why Convention D's regex must catch both forms (see §5/D).

```python
# src/data_collection/capability_registration.py  (shape)
from datetime import date
from src.platform.capability_registry import register_system
from src.data_collection._capability_health import table_freshness_health

_TODAY = date(2026, 5, 21)
# (system_name == module stem, table, ts_col, stale_after_min, cadence_label, description)
_COLLECTORS = (
    ("vix_collector", "vix_term_structure", "collected_at", 1500, "daily overnight",
     "VIX/VIX9D/VIX3M term-structure snapshot for regime + governor volatility gate."),
    ("insider_collector", "insider_transactions", "collected_at", 2880, "daily overnight",
     "Form 4 insider buys/sells for the universe."),
    # ... 16 more, one row per *_collector.py module ...
)
for _name, _table, _ts, _stale, _cadence, _desc in _COLLECTORS:
    def _health(table=_table, ts=_ts, stale=_stale, cadence=_cadence):  # default-arg closure capture
        return table_freshness_health(table, ts, stale, cadence)
    register_system(
        name=_name, description=_desc, category="data-collection",
        version="1.0", maintainer="ai_session", introduced_in="v0.36.0",
        last_reviewed_date=_TODAY, expected_runtime=_cadence,
    )(_health)
```

**Critical correctness rule:** the SYSTEM `name` MUST equal the collector module stem (`vix_collector` module → SYSTEM `vix_collector`), because Convention B maps module-stem → expected-SYSTEM-name directly. The table's first column is the authoritative module↔system binding.

```python
# src/risk/gate_decisions.py  (shape)
from datetime import date
from src.platform.capability_registry import register_decision
from src.risk.governor import GOVERNOR_GATES   # the oracle tuple (definition list)

_TODAY = date(2026, 5, 21)
# gate_name -> (decision_text, rationale, revisit_trigger)
_GATE_META = {
    "traffic_light": (...), "event_risk": (...), "deterministic_audit": (...),
    "emergency_halt": (...), "daily_loss": (...), "position_size": (...),
    "max_positions": (...), "sector_concentration": (...), "correlation": (...),
    "volatility_halt": (...), "duplicate": (...),
}
# F-min-2: completeness check — a missing key fails with a precise message, not a bare KeyError
assert set(_GATE_META) == set(GOVERNOR_GATES), (
    f"_GATE_META keys must exactly match GOVERNOR_GATES. "
    f"missing={set(GOVERNOR_GATES) - set(_GATE_META)} extra={set(_GATE_META) - set(GOVERNOR_GATES)}"
)
for _gate in GOVERNOR_GATES:
    _text, _why, _revisit = _GATE_META[_gate]
    register_decision(
        name=f"gate_{_gate}", description=f"Risk-governor check '{_gate}' in check_trade.",
        category="risk-governor", version="1.0", maintainer="operator",
        introduced_in="v0.14.0", last_reviewed_date=_TODAY,
        decision_text=_text, rationale=_why, revisit_trigger=_revisit,
    )
```

`GOVERNOR_GATES` is a new module-level tuple added to `src/risk/governor.py` beside `check_trade`, equal to the emitted `"name"` strings in declaration order (verified governor.py:628–820):
```python
GOVERNOR_GATES = (
    "traffic_light", "event_risk", "deterministic_audit", "emergency_halt",
    "daily_loss", "position_size", "max_positions", "sector_concentration",
    "correlation", "volatility_halt", "duplicate",
)
```

### 2.3 The watch-handler CLI dispatcher (DA-3, real wiring)

`scripts/run_watch_handler.py` is the genuine `kickoff_endpoint` target. It is import-light (imports `ALL_HANDLERS` from `watch_handlers`, and `WatchLoop` only inside `main()` so `--list` works without constructing the heavy loop). Shape:
```python
# scripts/run_watch_handler.py
"""CLI dispatcher: invoke a single watch-loop handler by name.
Usage:
  python scripts/run_watch_handler.py --list
  python scripts/run_watch_handler.py --handler maybe_stress_test [--at 2026-05-21T19:00:00] [--force]
"""
import argparse, datetime as _dt
from src.scheduler.watch_handlers import ALL_HANDLERS
_BY_NAME = {h.__name__: h for h in ALL_HANDLERS}

def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--list", action="store_true")
    p.add_argument("--handler")
    p.add_argument("--at")            # ISO timestamp override (defaults to now, ET)
    p.add_argument("--force", action="store_true")  # bypass the schedule-window gate
    args = p.parse_args(argv)
    if args.list:
        for name in _BY_NAME: print(name)
        return 0
    fn = _BY_NAME.get(args.handler)
    if fn is None:
        raise SystemExit(f"unknown handler {args.handler!r}; known: {sorted(_BY_NAME)}")
    from src.scheduler.watch import WatchLoop          # heavy import deferred
    now = _dt.datetime.fromisoformat(args.at) if args.at else _dt.datetime.now()
    watch = WatchLoop(...)                              # constructed per existing entrypoint convention
    if args.force: watch.overnight = True               # let the window predicate pass
    fn(watch, now)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```
The handler ACTIONs therefore carry a **real, non-empty** `input_schema`:
```python
simple_io_schema(
    properties={
        "at": {"type": "string", "format": "date-time", "description": "ISO timestamp override; default now (ET)"},
        "force": {"type": "boolean", "description": "bypass the schedule-window gate"},
    },
    required=[],
)
```
`kickoff_endpoint` = `"python scripts/run_watch_handler.py --handler <handler_name>"`. The script is smoke-tested (Task 3): `--list` prints exactly the 16 names, and dispatching one handler with `--force --at <fixed>` returns 0 without raising in a bare env (handlers are written to no-op when their preconditions are absent).

### 2.4 Import-cycle avoidance (the chief risk)

Every registration anchor stays **import-light**: at module top it imports only `date`, the `register_*` callable, and (for collectors) the freshness helper. **All heavy dependencies are deferred into the callable bodies** — exactly as the existing exemplars do (`reconcile_state._most_recent_reconcile_touch` catches `DBOperationalError` and lazy-imports `connect_db`/`DB_PATH`; `training_service` imports `sqlite3`/config inside the function). Concretely:
- Collector health fns import nothing heavy — `table_freshness_health` does its own lazy `connect_db`/`DB_PATH` import inside.
- Handler ACTION registrations import `ALL_HANDLERS` (a leaf list in `watch_handlers.py`) but NOT `watch.py` (the heavy `WatchLoop`).
- `gate_decisions.py` imports only `GOVERNOR_GATES` (a literal tuple) from `governor.py`.
- Heterogeneous families use thin `*/capability_registration.py` hosts that import only `register_*` + the freshness helper at top; the engine probes lazy-import their targets inside the health fn.

**Verification:** the bootstrap-clean test (`test_bootstrap_is_clean_in_final_state`) asserts zero `CAPABILITY_REGISTRY_BOOTSTRAP_ERROR`; any cycle surfaces there as a hard failure in the capstone batch.

---

## 3. The Refresh — what gets registered (deterministic count → exactly 80)

Starting ledger: **19**. (Per operator directive, finest sub-steps are grouped.)

### 3a. Collectors → 18 SYSTEMS  (category `data-collection`)  **[firm structural set]**
`analyst_collector, cboe_collector, company_executive_collector, docs_collector, edgar_collector, fed_collector, filings_sentiment_collector, insider_collector, institutional_ownership_collector, macro_collector, options_collector, press_releases_collector, price_target_collector, research_collector, short_interest_collector, stock_financials_collector, trends_collector, vix_collector`. Each health = table-freshness via `MAX(ts_col)` on the collector's owned table. **+18**

### 3b. Watch handlers → 16 ACTIONS  (category `scheduler`)  **[firm structural set]**
Name = `maybe_`-stripped handler name (authoritative for Convention A): `morning_vram_handoff, post_close_capture, overnight_training_collection, evening_vram_handoff, stress_test, data_collection, news_ingestion, enrichment_precache, 1min_bar_collection, pre_market_refresh, premarket_rolling_features, premarket_training, premarket_news_scoring, premarket_candidates, stats_pulse, walkforward_reconciler`. `kickoff_endpoint` = `python scripts/run_watch_handler.py --handler <handler_name>` (real, §2.3); `input_schema` = `{at, force}` (real, §2.3); `output_schema` = `simple_io_schema()`; `estimated_duration` per handler. **+16**

### 3c. Governor gates → 11 DECISIONS + 1 SYSTEM + 1 DECISION  (category `risk-governor`)  **[firm structural set]**
11 `gate_<emitted_name>` DECISIONs (§2.2). Plus `risk_governor` SYSTEM (health = enabled + config sane, degrade-not-raise) and `decision_drawdown_adjusted_risk` DECISION (Thorp proportional bet reduction, `governor.py:338`). **+13**

> **Firm structural total: 18 + 16 + 13 = 47.** These are the A/B/C guard targets and are non-negotiable.

### Heterogeneous keep-set (trimmed to exactly 14 — DA-1)

To land at the operator's ceiling ("~75–85", aiming ~80) the heterogeneous families register only their **highest-value major** entry. Each family lists its exact keep set; everything else moves to the deferred backlog (§3-defer).

| Family (task) | **Kept (count)** | Kinds |
|---|---|---|
| 3d Execution / exits (T5) | `submit_shadow_trade`, `position_exit_manager`, `trade_reconciler` (**3**) | ACTION, SYSTEM, SYSTEM |
| 3e Scan→LLM→council (T6) | `llm_scorer`, `council_engine`, `build_decision_packet` (**3**) | SYSTEM, SYSTEM, ACTION |
| 3f Training (T7) | `run_finetune`, `model_promotion_gate`, `training_quality_filter` (**3**) | ACTION, DECISION, DECISION |
| 3g Eval / audit (T8) | `system_auditor`, `model_monitor`, `run_backtest` (**3**) | SYSTEM, SYSTEM, ACTION |
| 3h Notifications (T9) | `telegram_notifier`, `spy_benchmark_state` (**2**) | SYSTEM, STATE |
| **Heterogeneous total** | **14** | |

Grouping is applied where multiple sub-steps share one decision surface: `model_promotion_gate` folds 50-trade + canary + promotion criteria; `training_quality_filter` folds quality + drift + leakage + ingestion gate.

### 3-defer. Deferred to documented backlog (NOT registered this pass; recorded in capstone)
`exit_reason_classifier`, `decision_trade_alerts`, `bracket_monitor` (execution); `candidate_ranking`, `build_watchlist`, `trade_postmortem`, `council_aggregation`, `eod_recap` (scan/LLM/council); `evaluate_holdout`, `rollback_model`, `build_training_corpus`, `run_dpo` (training); `system_validator`, `walkforward_validation`, `build_scorecard`, `change_detector`, `monte_carlo_sim` (eval); `telegram_command_handler`, `notification_policy`, `platform_event_bus`, `attribution_backtest` (notifications). These are second-tier engines/decisions; the backlog note (`docs/audits/2026-05-21-capability-registry/deferred_backlog.md`) preserves them with one-line metadata so nothing is lost.

### Deterministic total
**19 (existing) + 47 (firm structural) + 14 (heterogeneous keep) = 80.** This is the single derivable number used by the headline, the CI floor (`>= 80`), and the sum of the per-family task keep-sets. No other count appears anywhere.

---

## 4. Per-family wiring patterns (the contract developers apply)

### 4.1 SYSTEM health-check pattern — **degrade, never raise** (collectors + engines)
**Shape:** `() -> {"status": "ok"|"degraded"|"down", "detail": str, ...}`.
**Collector freshness helper** (`_capability_health.py`) — catches `DBOperationalError`, returns a status dict, never propagates:
```python
def table_freshness_health(table, ts_col, stale_after_minutes, cadence_label):
    from datetime import datetime, timezone
    from src.config import DB_PATH
    from src.utils.db import DBOperationalError, connect_db
    try:
        conn = connect_db(DB_PATH)
    except Exception as exc:                       # bare-env: DB path missing
        return {"status": "down", "detail": f"db unavailable: {exc}"}
    try:
        row = conn.execute(f"SELECT MAX({ts_col}) FROM {table}").fetchone()
    except DBOperationalError as exc:               # table missing / not migrated
        return {"status": "down", "detail": f"{table} unavailable: {exc}"}
    finally:
        conn.close()
    last = (row or (None,))[0]
    if last is None:
        return {"status": "degraded", "detail": f"{table} empty — collector has not run"}
    # parse last (ISO) -> age; degraded if older than stale_after_minutes
    return {"status": "ok", "detail": f"last row at {last} ({cadence_label})", "last_updated_at": last}
```
`table`/`ts_col` are code-controlled constants — no SQL-injection surface.

**Engine SYSTEM health fns MUST degrade-not-raise in a fully-unconfigured/env-stripped worktree** (no Ollama, no `.env`) — the health-executes test (§7) runs in a bare env. Each engine fn wraps its probe in `try/except` and returns the status dict:
- `llm_scorer` (`src/llm/...`): probe Ollama reachability lazily; `except (ConnectionError, OSError, Exception) -> {status:"down", detail:"Ollama unreachable"}`; if reachable but no recent score → `degraded`.
- `council_engine` (`src/council/...`): read last council-run timestamp lazily; any read failure → `{status:"degraded", detail:"no council run recorded"}`.
- `telegram_notifier` (`src/notifications/...`): `{status:"ok" if token-configured else "degraded", detail:last-send-or-"not configured"}`; never raise on missing token.
- `risk_governor` (`src/risk/...`): construct/read governor config lazily; `except -> {status:"degraded", detail:"governor config unavailable"}`; `{status:"ok" if enabled else "degraded"}`.
- `system_auditor` (`src/evaluation/...`): last `audit_reports` freshness via `table_freshness_health` (already degrade-safe); note the two-layer-staleness gotcha in the description.
- `model_monitor` (`src/evaluation/...`): last drift-check freshness via the helper; degrade on missing table.

### 4.2 ACTION kickoff pattern (handlers + engine kickoffs)
**Required fields:** `kickoff_endpoint` (URL path OR CLI string — metadata test accepts both), `input_schema`, `output_schema` (both MCP-valid Draft-7 via `simple_io_schema`), `estimated_duration`. Anchor fn returns a static `{registered_at, entry_module}` dict (matching `regime_diagnostic_capability`). Scheduler handlers use the §2.3 CLI form + real `{at, force}` schema; execution/training engines with real HTTP routes use the route path.
```python
def simple_io_schema(properties=None, required=None):
    return {"type": "object", "properties": properties or {}, "required": required or [], "additionalProperties": False}
```

### 4.3 STATE query pattern (`spy_benchmark_state`)
`() -> {"value": <scalar-or-dict>}`; `refresh_hint` per cadence; lazy-imports its data source inside the fn and degrades to `{"value": None}` on a missing source rather than raising.

### 4.4 DECISION pattern (gates + strategic facts)
Plain/functional `register_decision(...)` call with `decision_text`/`rationale`/`revisit_trigger`. Gates are loop-registered from `GOVERNOR_GATES`; other DECISIONs are hand-authored in their family host.

---

## 5. The 5 CI Guards (hard / merge-blocking) — with an honest coverage statement

All live in `tests/test_capability_registry_coverage.py`, each calling `ensure_bootstrapped()` first. The frozen `assert total >= 18` (integration test lines 88 AND 128) is **raised to a structural floor (`>= 80`)** AND superseded by A–E.

### 5.0 Coverage accounting (DA-2 — calibrated claim, stated up front)

| Set | Count | Guarded by | Drift caught |
|---|---|---|---|
| Watch handlers | 16 | **A** (derive from `ALL_HANDLERS`) | a new handler with no ACTION |
| Collectors | 18 | **B** (derive from `*_collector.py` glob) | a new collector file with no SYSTEM |
| Governor gates | 11 | **C** (derive from `GOVERNOR_GATES`) | a new gate not in the tuple+registered |
| **Structural subtotal** | **47** | A/B/C (filename/list/tuple oracles) | structural — fully automatic |
| Heterogeneous keep + existing 19 + governor SYSTEM/drawdown | 33 | **E** (per-package presence + manifest) | a new business-logic **module** under a capability package that registers nothing and isn't EXEMPT |
| **Everything in `CAPABILITY_MODULES`** | 80 | **D** (every registering module is bootstrapped) | a registered module forgotten from the bootstrap list |

**What is structurally guaranteed:** A/B/C make the 47-entry firm core self-updating from code (a new handler/collector/gate that skips its registration → CI red). D guarantees no registered module is silently dropped from bootstrap. E (new this rev) guarantees that a **new module** added under any enumerated capability package either registers ≥1 entry or is explicitly EXEMPT — closing the exact failure that motivated this work ("a new undecorated subsystem in execution/training/eval silently drifts").

**Honest residual surface (NOT claimed as guarded):** E operates at *module* granularity. A new business-logic *function* added inside an already-registered module (e.g. a second public entrypoint in `executor.py`) is NOT forced onto the ledger by any guard — that remains a review-time judgment. We do **not** claim "CI prevents all drift"; we claim "CI prevents (a) any new handler/collector/gate from skipping registration, and (b) any new module under a capability package from registering nothing without an explicit exemption." The operator should read E's `EXEMPT` set as the on-the-record list of "modules we deliberately chose not to surface."

### Convention A — every `ALL_HANDLERS` handler is a registered ACTION
```python
from src.scheduler.watch_handlers import ALL_HANDLERS
from src.platform.capability_registry import ensure_bootstrapped, list_actions
def _expected(h): n = h.__name__; return n[6:] if n.startswith("maybe_") else n
def test_every_watch_handler_is_a_registered_action():
    ensure_bootstrapped()
    # (minor) every handler is a plain maybe_-prefixed function — no partials/lambdas
    for h in ALL_HANDLERS:
        assert callable(h) and hasattr(h, "__name__") and h.__name__.startswith("maybe_"), \
            f"ALL_HANDLERS entry {h!r} is not a plain maybe_-prefixed function"
    expected = {_expected(h) for h in ALL_HANDLERS}
    # (minor) no name collisions after stripping
    assert len(expected) == len(ALL_HANDLERS), \
        f"maybe_-strip produced colliding ACTION names: {len(ALL_HANDLERS)} handlers -> {len(expected)} names"
    missing = expected - {a.name for a in list_actions()}
    assert not missing, f"Watch handlers without a registered ACTION: {sorted(missing)}"
```

### Convention B — every `src/data_collection/*_collector.py` registers a SYSTEM named for its stem
```python
import pkgutil, src.data_collection as dc
from src.platform.capability_registry import ensure_bootstrapped, list_systems
# EXEMPT contract (documented): add a *_collector module stem here ONLY if it is a shared
# helper that hosts no real collector (none today). Each entry MUST carry a one-line reason.
EXEMPT: set[str] = set()
def test_every_collector_module_registers_a_system():
    ensure_bootstrapped()
    expected = {n for _, n, _ in pkgutil.iter_modules(dc.__path__) if n.endswith("_collector") and n not in EXEMPT}
    registered = {s.name for s in list_systems() if s.category == "data-collection"}
    missing = expected - registered
    assert not missing, f"Collector modules with no SYSTEM (name must == module stem): {sorted(missing)}"
```
*(Name-convention form chosen over inventory §5's import-delta form: no per-module import side-effects, precise stable failure message.)*

### Convention C — every `GOVERNOR_GATES` entry is a registered DECISION `gate_<g>` (DA-4: definition enumeration, NO dry-run)
```python
import pathlib, re
from src.risk.governor import GOVERNOR_GATES
from src.platform.capability_registry import ensure_bootstrapped, list_decisions
def test_every_governor_gate_is_a_registered_decision():
    ensure_bootstrapped()
    missing = {f"gate_{g}" for g in GOVERNOR_GATES} - {d.name for d in list_decisions()}
    assert not missing, f"Governor gates missing register_decision: {sorted(missing)}"

# C-companion (DA-4): the tuple cannot silently drift from the code, but we do NOT run check_trade
# (it short-circuits at governor.py:613/680, so no fixture emits all 11 names). Instead:
#  (1) F-min-2 completeness lives in gate_decisions.py: assert set(_GATE_META)==set(GOVERNOR_GATES).
#  (2) Static source-scan: every literal gate name in check_trade is present in GOVERNOR_GATES.
_GATE_NAME_LITERAL = re.compile(r'"name":\s*"([a-z_]+)"')
_NON_GATE = {"input_surface", "governor_disabled"}  # framework checks, not strategy gates
def test_governor_gates_tuple_matches_source():
    src = (pathlib.Path(__file__).resolve().parents[1] / "src" / "risk" / "governor.py").read_text(encoding="utf-8")
    emitted = {m.group(1) for m in _GATE_NAME_LITERAL.finditer(src)} - _NON_GATE
    assert emitted == set(GOVERNOR_GATES), (
        f"GOVERNOR_GATES drifted from check_trade literals. "
        f"in_source_not_tuple={emitted - set(GOVERNOR_GATES)} in_tuple_not_source={set(GOVERNOR_GATES) - emitted}"
    )
```
*(Robust to short-circuit: a static scan sees every `"name": "..."` literal regardless of which branch fires at runtime. `_NON_GATE` excludes the two framework checks `input_surface`/`governor_disabled` that are not strategy gates.)*

### Convention D (meta-guard) — every module containing a registration call is in `CAPABILITY_MODULES`  (DA-minor: catch BOTH decorator AND functional forms)
```python
import pathlib, re
from src.platform.capability_registry.bootstrap import CAPABILITY_MODULES
# Catch BOTH @register_x decorators AND functional register_x(...) calls (the en-bloc loop
# modules use the functional form: register_system(...)(fn), register_decision(...)).
# Exclude the `def register_x(` definitions in registry.py via the (?<!def ) lookbehind.
_PAT = re.compile(r"@register_(?:action|state|system|decision)\b|(?<!def )register_(?:action|state|system|decision)\(")
SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
SELF_PKG = "src.platform.capability_registry"
def test_every_registering_module_is_in_bootstrap():
    listed = set(CAPABILITY_MODULES)
    offenders = []
    for p in SRC.rglob("*.py"):
        text = p.read_text(encoding="utf-8")
        if not _PAT.search(text):
            continue
        mod = ".".join(p.relative_to(SRC.parent).with_suffix("").parts)
        # registry.py/schemas.py/__init__.py DEFINE the API; decisions.py is a real host.
        if mod.startswith(SELF_PKG) and mod not in {f"{SELF_PKG}.decisions", f"{SELF_PKG}.audit_registration"}:
            continue
        if mod not in listed:
            offenders.append(mod)
    assert not offenders, f"Modules register capabilities but are absent from CAPABILITY_MODULES: {sorted(offenders)}"

# D self-test (DA-minor): prove the broadened regex catches the functional form used by the new hosts.
def test_convention_d_pattern_catches_functional_form():
    assert _PAT.search("register_system(name='x')(fn)")     # functional system
    assert _PAT.search("    register_decision(name='y')")    # functional decision
    assert _PAT.search("@register_action(name='z')")        # decorator action
    assert not _PAT.search("def register_system(**meta):")  # definition excluded
```

### Convention E (presence/coverage guard) — every business-logic module under a capability package registers ≥1 entry OR is EXEMPT  (DA-2)
```python
import pathlib, re
from src.platform.capability_registry.bootstrap import CAPABILITY_MODULES
from src.platform.capability_registry import (
    ensure_bootstrapped, list_actions, list_states, list_systems, list_decisions,
)
SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
_REG = re.compile(r"@register_(?:action|state|system|decision)\b|(?<!def )register_(?:action|state|system|decision)\(")
# The enumerated capability packages whose modules must surface a capability or be EXEMPT.
# (Derived from §3's heterogeneous families; the homogeneous families are covered by A/B/C.)
CAPABILITY_PACKAGES = (
    "src/shadow_trading", "src/llm", "src/council", "src/training",
    "src/evaluation", "src/notifications", "src/ranking", "src/analytics",
)
# EXEMPT: modules deliberately NOT surfaced this pass — the on-the-record "we chose not to"
# list. Each entry has a one-line reason. Deferred-backlog items live here until registered.
EXEMPT_MODULES: dict[str, str] = {
    "src.shadow_trading.bracket_monitor": "deferred to backlog (covered operationally by position_exit_manager)",
    "src.shadow_trading.exit_reason": "deferred: exit_reason_classifier DECISION",
    # ... every deferred-backlog module + every pure helper/leaf (no business logic) ...
}
_HELPER_HINT = re.compile(r"^_|_helpers?$|^errors?$|^constants?$|^types?$|^_status_sql$|^_capability_health$")
def _has_business_logic(text: str) -> bool:
    # heuristic: a module with at least one public def/class that isn't a pure dataclass/const
    return bool(re.search(r"^(?:async def |def |class )[A-Za-z]", text, re.M))
def test_every_capability_package_module_surfaces_or_is_exempt():
    ensure_bootstrapped()
    listed_hosts = set(CAPABILITY_MODULES)
    # modules that DID register (their dotted name appears in a host that registered something)
    offenders = []
    for pkg in CAPABILITY_PACKAGES:
        pkg_dir = SRC.parent / pkg
        if not pkg_dir.exists():
            continue
        for p in pkg_dir.rglob("*.py"):
            if p.name in {"__init__.py", "capability_registration.py"}:
                continue
            stem = p.stem
            if _HELPER_HINT.search(stem):
                continue
            mod = ".".join(p.relative_to(SRC.parent).with_suffix("").parts)
            if mod in EXEMPT_MODULES:
                continue
            text = p.read_text(encoding="utf-8")
            if not _has_business_logic(text):
                continue
            registers_here = bool(_REG.search(text))
            covered_by_host = mod in listed_hosts or any(
                h.startswith(mod.rsplit(".", 1)[0]) for h in listed_hosts
            )
            # a module is OK if it registers directly OR a sibling capability_registration.py
            # in the same package registers on its behalf (thin-host pattern).
            sibling_host = f"{mod.rsplit('.', 1)[0]}.capability_registration"
            if not (registers_here or sibling_host in listed_hosts):
                offenders.append(mod)
    assert not offenders, (
        "Modules under a capability package register no capability and are not EXEMPT — "
        f"a new subsystem may have drifted in: {sorted(offenders)}. "
        "Either register a capability for it, or add it to EXEMPT_MODULES with a reason."
    )
```
*(E is intentionally module-granular and uses an explicit `EXEMPT_MODULES` manifest so the failure is a precise, actionable list. The thin-host pattern means a module covered by a sibling `capability_registration.py` passes. The deferred-backlog set is seeded into `EXEMPT_MODULES` so the capstone leaves E green while keeping the deferred items on-the-record.)*

**Why these beat `>= 18`:** each derives the *expected* set from a live oracle (handler list, filename glob, gate tuple, source-scan, package walk) so a new feature that skips its registration changes only the expected side → CI red. Each oracle is co-located with the feature, so it self-updates.

---

## 6. Error Handling

- **Malformed metadata:** Pydantic raises at decoration → bootstrap logs `CAPABILITY_REGISTRY_BOOTSTRAP_ERROR` and the metadata test's `decorator_failures` assertion fails hard. Fix: correct the kwargs.
- **Health/query fn raises at request time:** endpoint isolates per-entry (existing behavior, preserved). Health fns must ALSO **execute without raising in a bare env** — enforced by the §7 health-executes test (runs with no Ollama, no `.env`). Engine fns achieve this via the try/except→status-dict pattern in §4.1.
- **Import cycle from a new bootstrap import:** surfaces as a bootstrap error → `test_bootstrap_is_clean_in_final_state` fails. Mitigation: §2.4 import-light anchors + defer-into-callable + thin per-package hosts.
- **Duplicate name:** `_check_duplicate` raises `CapabilityRegistryError` unless metadata is identical. New names are namespaced to avoid collision with the 19 (engine `trade_reconciler` vs proxy `reconcile_trades`; engine `run_backtest` vs wrapper `strategy_backtest`).
- **`_GATE_META` incompleteness:** the `assert set(_GATE_META) == set(GOVERNOR_GATES)` in `gate_decisions.py` (F-min-2) fails at import with a precise missing/extra-key message — never a bare `KeyError` in the loop.
- **`GOVERNOR_GATES` tuple drift:** the C-companion static source-scan (`test_governor_gates_tuple_matches_source`) fails if the tuple diverges from the literal gate names in `check_trade` — robust to short-circuit because it scans source text, not runtime output.
- **Missing `scripts/run_watch_handler.py`:** the Task-3 smoke test (`--list` → 16 names; one dispatch returns 0) fails if the dispatcher is absent or broken.

---

## 7. Testing Strategy

| Test | Location | Type | Asserts |
|---|---|---|---|
| Convention A | `tests/test_capability_registry_coverage.py` (new) | hard | every `ALL_HANDLERS` → ACTION; no strip collisions; all plain `maybe_` fns |
| Convention B | same | hard | every `*_collector.py` stem → `data-collection` SYSTEM; EXEMPT empty |
| Convention C + companion | same | hard | `{gate_<g>}` ⊆ DECISIONs; `set(_GATE_META)==set(GOVERNOR_GATES)` (in module); tuple == source literals (static scan, NO dry-run) |
| Convention D + self-test | same | hard | every registering module (decorator OR functional form) ∈ `CAPABILITY_MODULES`; regex self-test catches functional form |
| Convention E | same | hard | every business-logic module under a capability package registers or is EXEMPT |
| Health/query executes (bare env) | same | hard | every SYSTEM `health_check_function()` returns `{status in {ok,degraded,down}}` and every STATE `query_function()` returns a dict — run with no Ollama / no `.env` (engine fns must degrade-not-raise) |
| `run_watch_handler.py` smoke | `tests/test_run_watch_handler.py` (new, owned by Task 3) | hard | `--list` prints exactly 16 handler names; dispatching one handler `--force --at <fixed>` returns 0 without raising |
| Floor raised | `tests/test_capability_registry_integration.py` (edit) | hard | BOTH `>= 18` assertions (lines 88 + 128) → `>= 80`; zero bootstrap errors (existing, kept) |
| Per-entry metadata | `tests/test_capability_registry_metadata.py` (extend) | hard | existing checks now cover 80 entries; add: every collector SYSTEM `category=='data-collection'` |
| Endpoint round-trip | `tests/test_capability_registry_integration.py` (existing) | hard | `/api/system/index` still 200 with the larger payload |

**Test infra available:** tmp-SQLite via `src.schema.registry.TABLES` + `src.schema.sqlite.generate_create_sql`; `clear_registries_for_tests` + `reset_for_tests` + force-reload fixture pattern for test-order robustness. New tests reuse this fixture so they survive other tests clearing the registries. The health-executes test deliberately does NOT seed Ollama/.env — it asserts graceful degradation.

---

## 8. Batching / Sequencing Strategy

The one hard sequencing rule: **a guard must land in the SAME batch as (or after) its target registrations**, never before. Each structural guard travels with its registrations; the meta/coverage guards (D, E) + floor-raise land LAST (they depend on everything).

- **Batch 1 (foundations):** `_capability_health.py`, `_io_schemas.py`, `scripts/run_watch_handler.py` (+ its smoke test), and add the `GOVERNOR_GATES` tuple to `governor.py`. No registrations yet; no guard yet. Unblocks 2/3/4.
- **Batch 2 (collectors + B):** `capability_registration.py` (18 SYSTEMs) + `CAPABILITY_MODULES` edit + Convention B.
- **Batch 3 (handlers + A):** `handler_registration.py` (16 ACTIONs, real CLI kickoff + `{at,force}` schema) + bootstrap + Convention A.
- **Batch 4 (gates + C):** `gate_decisions.py` (11 DECISIONs + `_GATE_META` completeness assert + `risk_governor` SYSTEM + `decision_drawdown_adjusted_risk`) + bootstrap + Convention C + companions.
- **Batches 5–9 (heterogeneous families, parallel):** each registers its trimmed keep-set (3/3/3/3/2), edits `CAPABILITY_MODULES`, adds its health-fn-executes coverage, and seeds its deferred modules into Convention E's `EXEMPT_MODULES`. No new structural guard.
- **Batch 10 (capstone, depends on all):** Convention D + Convention E (with the full `EXEMPT_MODULES` manifest assembled) + raise BOTH integration floors to `>= 80` + extend metadata test + verify all new entries carry `last_reviewed_date=date(2026,5,21)` + full bootstrap-clean verification + write `deferred_backlog.md`.

Batches 2/3/4 are independently reviewable. 5–9 are independent families. 10 gates the merge.

---

## 9. Risks

- **Import cycles (primary):** new bootstrap imports of `council`, `llm`, `training`, `evaluation` may pull heavy graphs. Mitigation: §2.4 import-light anchors + defer-into-callable + thin `*/capability_registration.py` hosts. The bootstrap-clean test is the backstop.
- **Engine health in bare env:** an engine probe that raises when Ollama/.env is absent would red the health-executes test. Mitigation: §4.1 mandates try/except→status-dict per engine fn (mirrors the verified `reconcile_state` degrade pattern).
- **Convention E false positives/negatives:** the `_has_business_logic` + `_HELPER_HINT` heuristic plus the explicit `EXEMPT_MODULES` manifest keep E actionable; a misfire is fixed by adding an EXEMPT entry (with reason) or registering. E is module-granular by design — the residual (new function in an existing module) is documented in §5.0, not silently claimed away.
- **Convention D functional-form miss:** resolved by broadening the regex to catch `register_x(` and proving it with the D self-test.
- **Windows UTF-8:** all source reads use `encoding='utf-8'` (cp1252 memory note); all new files ASCII-only.
- **Out of scope (correctly):** the halcyon/halcyon_app DB-ownership split (no schema change). Transport/route handlers under `src/api/` are deliberately NOT registered (and `src/api` is excluded from Convention E's `CAPABILITY_PACKAGES`).

---

## 10. Known Considerations

- **Convention E is module-granular.** It cannot force a *second* capability out of an already-registered module. New top-level subsystems are caught; new entrypoints inside an existing module are a review-time call. This is stated plainly so the operator is not told "CI prevents all drift."
- **The deferred backlog (§3-defer) is on-the-record twice:** in `deferred_backlog.md` and as `EXEMPT_MODULES` entries with reasons. Promoting a deferred item later = remove its EXEMPT entry + register it (E will then require it).
- **Existing 19 entries keep `last_reviewed_date=2026-04-18`** (constraint: do not break them). Only the 61 new entries get `2026-05-21`. Bumping the old 19 is a separate dashboard "Mark Reviewed" action.
- **`run_watch_handler.py` constructs a real `WatchLoop`.** If the loop's constructor requires config the bare CI env lacks, the smoke test dispatches with `--force` against a handler whose body no-ops without preconditions; the dispatcher itself is the wired artifact, satisfying the operator's "real kickoff endpoint" requirement.

## Design Decisions

| Decision | Rationale |
|---|---|
| Land at EXACTLY 80 entries (19 existing + 47 firm structural + 14 heterogeneous keep), with the heterogeneous keep-set trimmed per-family to T5=3, T6=3, T7=3, T8=3, T9=2; the CI floor is raised to >= 80; the trimmed 11 second-tier entries move to a documented deferred backlog. | DA-major-1: the reviewed draft was internally inconsistent — headline said ~80, dial-back prose implied ~80, but the task keep-sets summed to 25 -> 91. The operator's target was ~75-85 and option (a) (trim to land ~80) was mildly preferred. One derivable number now flows everywhere: headline (80), §3 sum (19+47+14), per-family keep-sets (sum 14), and the floor (>= 80). The 47 firm structural entries (18 collectors + 16 handlers + 13 governor) are non-negotiable A/B/C targets; the heterogeneous keep is the adjustable lever, set to 14 to hit 80 exactly. Nothing is lost — the 11 trimmed entries are recorded in deferred_backlog.md AND seeded into Convention E's EXEMPT_MODULES with reasons. |
| Add Convention E — a per-capability-package presence/coverage guard with an explicit CAPABILITY_PACKAGES walk and an EXEMPT_MODULES manifest — and state the guarded-vs-unguarded fraction explicitly in §5.0; calibrate the claim to 'CI prevents new handler/collector/gate skips (A/B/C) AND new capability-package modules registering nothing (E)', NOT 'CI prevents all drift'. | DA-major-2 (most important): Conventions A/B/C structurally cover only the 47-entry firm core (handlers/collectors/gates). The ~33 heterogeneous + existing entries had NO structural anti-drift guard, so a NEW undecorated subsystem in execution/training/eval/council/notifications would silently drift — the exact failure that motivated this work and contradicts the operator's purpose ('so I don't lose sight of platform features'). Convention E derives an expected set from code structure: every business-logic module under an enumerated capability package must register >=1 entry (directly or via a sibling capability_registration.py) or be in EXEMPT_MODULES with a reason. A new module that registers nothing and isn't EXEMPT -> CI red. The EXEMPT_MODULES manifest doubles as the on-the-record 'modules we deliberately chose not to surface' list. The honest residual (a new FUNCTION inside an already-registered module) is named in §5.0/§10 rather than papered over. |
| Implement option (a) for the 16 scheduler-fired handler ACTIONs: add a REAL scripts/run_watch_handler.py CLI dispatcher (imports + invokes the named handler against a constructed WatchLoop, with --list/--handler/--at/--force), smoke-test it, and give each handler ACTION a real non-empty input_schema ({at: date-time, force: bool}) instead of an empty {type:object} placeholder. | DA-major-3 + F-min-1: the operator explicitly chose FULLY-WIRED ('real kickoff endpoints + real I/O schemas'). The reviewed draft pointed kickoff_endpoint at a non-existent scripts/run_watch_handler.py and used empty placeholder schemas — cosmetic, not wired, and dishonest given the operator's 'real' requirement. Option (a) was preferred. The dispatcher is a genuine artifact (import-light: ALL_HANDLERS at top, WatchLoop deferred into main() so --list works bare); its smoke test (--list -> 16 names; one dispatch returns 0 without raising) proves it dispatches. The {at, force} input_schema reflects the dispatcher's actual trigger params, satisfying 'real I/O schemas'. |
| Convention C derives the expected DECISION set from gate DEFINITIONS — the GOVERNOR_GATES tuple — never from a check_trade dry-run. The companion test asserts set(_GATE_META)==set(GOVERNOR_GATES) (in gate_decisions.py, fails before the loop with a precise message) AND statically scans governor.py for the "name":"..." gate literals to prove the tuple matches the source (minus the two framework checks input_surface/governor_disabled). | DA-major-4 + F-min-2: verified that check_trade short-circuits — governor.py:613 returns early with ONLY governor_disabled when disabled; :680 emergency_halt rejects before daily_loss/position_size/etc. append; traffic_light only appends when multiplier<1.0; event_risk/position_size have conditional branches. Therefore NO single passing fixture emits all 11 gate names, making the reviewed draft's dry-run harvest either spuriously failing or requiring an un-buildable fixture. Definition-enumeration (the operator's preferred approach) is robust to short-circuit because GOVERNOR_GATES is a static declaration list. To still prevent the tuple silently drifting from the code, the C-companion does a STATIC source-scan (regex the literal "name" strings in governor.py) rather than running the function — this sees every gate literal regardless of which runtime branch fires. F-min-2's set(_GATE_META)==set(GOVERNOR_GATES) assert makes a missing gate fail at import with 'missing={...} extra={...}', not a bare KeyError deep in the loop. |
| Broaden Convention D's detection regex to catch BOTH the @register_x decorator form AND the functional register_x(...) call form, and add a D self-test proving it detects the functional form; add audit_registration to the required-host set alongside decisions.py. | DA-minor (Convention D fragility): verified that the new en-bloc loop modules (capability_registration.py for collectors, gate_decisions.py for gates) and the existing decisions.py use the FUNCTIONAL form — register_system(name=...)(fn), register_decision(name=...) — not the @-decorator. The reviewed draft's pattern (@register_(action|state|system)\b | (?<!def )register_decision\() would MISS functional register_system(/register_action(/register_state( calls, so a new collector/gate host that registers functionally could slip past D into a state where it's not in CAPABILITY_MODULES and silently fails to load. The broadened pattern @register_(?:action|state|system|decision)\b | (?<!def )register_(?:action|state|system|decision)\( catches both; the (?<!def ) lookbehind still excludes the def register_x( definitions in registry.py. The self-test asserts detection of register_system(...)(fn), register_decision(...), @register_action(...), and exclusion of def register_system(. |
| All SYSTEM health functions and STATE query functions must degrade-not-raise in a fully-unconfigured/env-stripped worktree (no Ollama, no .env, missing tables); the health-executes test runs in a bare env and asserts each returns a valid {status}/{value} dict. Each engine fn (llm_scorer, council_engine, telegram_notifier, risk_governor, system_auditor, model_monitor) wraps its probe in try/except returning {status: degraded|down}. | DA-minor (engine health in bare env): the existing reconcile_state exemplar already degrades (catches DBOperationalError -> None -> {status: degraded}). New engine probes that reach for Ollama, a Telegram token, or governor config would RAISE in a bare CI worktree (worktrees don't carry the operator's .env — per the worktree-env-drift memory), reddening the health-executes test and potentially the bootstrap if a probe runs at import. Mandating the catch->status-dict branch per engine fn (Ollama unreachable -> down; no token -> degraded 'not configured'; config unavailable -> degraded) makes the registry observable rather than fragile, and lets the health-executes test run honestly with nothing configured. |
| Two homogeneous families (18 collectors, 11 gates) register en-bloc via metadata-table-driven loops in dedicated modules (capability_registration.py, gate_decisions.py); heterogeneous families co-locate registrations next to their logic or in a thin per-package capability_registration.py, with all heavy imports deferred into callable bodies. | Preserved strength: 18+11 hand-authored decorator blocks are high-burden and a metadata-typo surface. A table+loop with a shared health helper (table_freshness_health) and schema builder (simple_io_schema) cuts per-entry authoring to data rows and keeps the module<->capability binding explicit (collector table's first column == module stem, satisfying Convention B). Heterogeneous families have distinct health/IO logic per entry, so co-location (matching the existing diagnostics/training_service/reconcile_state exemplars) reads better; thin per-package hosts isolate heavy/cyclic import graphs (council/engine.py, llm/client.py, training/*) so bootstrap stays clean. |
| Registered watch-handler ACTION names are the mechanical maybe_-stripped handler names (stress_test, 1min_bar_collection, data_collection, ...), overriding inventory §3b's cosmetic proposals; GOVERNOR_GATES and the registered DECISION names use the gate names actually emitted by check_trade (volatility_halt, duplicate, deterministic_audit), named gate_<emitted_name>. | Preserved ground-truth corrections. Convention A's value is zero maintenance: its oracle is a pure maybe_-strip of ALL_HANDLERS.__name__ (verified all 16 are plain def maybe_* functions). If registered names diverged from the strip, the guard would fail against its own registrations and require a hand-maintained mapping. Likewise, verified at governor.py:805/820 the emitted check['name'] values are volatility_halt and duplicate (NOT §5's draft volatility/duplicate_position); Convention C derives expected DECISIONs from GOVERNOR_GATES and the static source-scan asserts the tuple matches those literals, so using the wrong names would make both incoherent. '1min_bar_collection' is valid (BaseEntry._name_is_snake_or_hyphen allows leading digits — verified schemas.py:45). |
| Sequence guards to land WITH or AFTER their target registrations (B with collectors=batch 2, A with handlers=batch 3, C with gates=batch 4); the Convention D meta-guard, the new Convention E coverage guard, and BOTH floor-raises (>= 80) land LAST in the capstone (depends_on all family tasks). | Preserved strength + extended for E. A guard merged before its registrations fails CI on the very PR that introduces the registrations. Pairing each structural guard with its registration set makes each batch green-on-merge and independently reviewable. Convention D ('every registering module is in CAPABILITY_MODULES') AND Convention E ('every capability-package module registers or is EXEMPT') are only satisfiable once ALL registrations exist and ALL deferred modules are seeded into EXEMPT_MODULES, so they must be the final gate. The integration test has TWO floor assertions (lines ~88 and ~128, verified) — both must be raised in the capstone or the second silently keeps the >= 18 snapshot. |
| Keep the existing 19 entries untouched (including last_reviewed_date=2026-04-18); refresh applies last_reviewed_date=date(2026,5,21) only to the 61 newly-added entries. | Preserved. The constraint 'do NOT break the 19 existing entries' plus the duplicate-guard's identical-rerun allowance means re-touching existing entries risks metadata churn for no functional gain. New entries get the current date so the 180-day staleness warning starts fresh for them. The operator's 'refresh last_reviewed_date' is satisfied by stamping the 61 new entries; bumping the old 19 is a separate dashboard 'Mark Reviewed' action. |
