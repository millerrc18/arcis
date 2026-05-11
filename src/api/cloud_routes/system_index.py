"""Unified system index endpoint — all four capability registries + live state.

Serves GET /api/system/index (read) and POST /api/system/index/{name}/mark-reviewed
(write the operator_view_state override). The payload is intentionally
byte-identical to what dashboards, CC sessions, and future MCP clients
consume (per evaluation doc R10).

State queries and system health checks are invoked at request time with
a 2-second per-call timeout via ThreadPoolExecutor. Raised exceptions
become {'status': 'unavailable', 'error': ...}; timeouts become
{'status': 'timeout'} — one bad query cannot cascade-break the index.

Called by: api.cloud_app (via include_router)
Calls: src.platform.capability_registry (bootstrap + read)
Owns tables: operator_view_state (reads+writes)
Config keys: none
Tests: tests/api/test_system_index.py
"""
from __future__ import annotations

import json
import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from src.config import DB_PATH
from src.utils.db import connect_db, engine_aware_upsert
from src.platform.capability_registry import (
    BaseEntry,
    ensure_bootstrapped,
    get_action,
    get_decision,
    get_state,
    get_system,
    list_actions,
    list_decisions,
    list_states,
    list_systems,
)

logger = logging.getLogger(__name__)

QUERY_TIMEOUT_SECONDS = 2.0
OPERATOR_ID = "operator"  # single-operator system per v1 scope

_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="system-index-query")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _open_sqlite() -> sqlite3.Connection:
    conn = connect_db(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _call_with_timeout(fn, *, name: str) -> dict[str, Any]:
    """Invoke a state-query or health-check with a hard timeout.

    Exceptions become status=unavailable; timeouts become status=timeout.
    The raw dict the function returned is preserved under `result` for
    callers that want structured access.
    """
    try:
        future = _executor.submit(fn)
        result = future.result(timeout=QUERY_TIMEOUT_SECONDS)
        if not isinstance(result, dict):
            return {"status": "unavailable", "error": f"{name} returned non-dict: {type(result).__name__}"}
        return {"status": "ok", "result": result}
    except FuturesTimeout:
        logger.warning("[SYSTEM_INDEX] query '%s' exceeded %s s timeout", name, QUERY_TIMEOUT_SECONDS)
        return {"status": "timeout"}
    except Exception as exc:  # noqa: BLE001 — per R5, one bad query must not fail the endpoint
        logger.warning("[SYSTEM_INDEX] query '%s' raised: %r", name, exc)
        return {"status": "unavailable", "error": str(exc)}


def _read_view_state(conn: sqlite3.Connection, entry_name: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT last_viewed_at, last_viewed_value, last_reviewed_date_override "
        "FROM operator_view_state WHERE user_id = ? AND entry_name = ?",
        (OPERATOR_ID, entry_name),
    ).fetchone()
    return dict(row) if row else None


def _write_view_state(conn: sqlite3.Connection, entry_name: str, value: dict[str, Any]) -> None:
    now = _utc_now_iso()
    value_json = json.dumps(value, default=str)
    engine_aware_upsert(conn, 'operator_view_state', {
        'user_id': OPERATOR_ID,
        'entry_name': entry_name,
        'last_viewed_at': now,
        'last_viewed_value': value_json,
    }, action='replace')
    conn.commit()


def _write_reviewed_override(conn: sqlite3.Connection, entry_name: str) -> str:
    reviewed = date.today().isoformat()
    engine_aware_upsert(conn, 'operator_view_state', {
        'user_id': OPERATOR_ID,
        'entry_name': entry_name,
        'last_reviewed_date_override': reviewed,
    }, action='replace')
    conn.commit()
    return reviewed


def _compute_delta(prev_value: dict | None, new_value: dict | None) -> Any:
    """Compute delta_since_last_view between two state snapshots.

    Returns None when no previous value, when type changed, or when the
    comparison is unclear. Otherwise: numeric diff, or nested dict of diffs
    for dict-shaped values.
    """
    if prev_value is None or new_value is None:
        return None
    if type(prev_value) is not type(new_value):
        return None
    if isinstance(prev_value, dict) and isinstance(new_value, dict):
        out: dict[str, Any] = {}
        for key in new_value:
            if key in prev_value:
                pv, nv = prev_value[key], new_value[key]
                if isinstance(pv, (int, float)) and isinstance(nv, (int, float)):
                    out[key] = nv - pv
        return out or None
    return None


_CALLABLE_FIELDS = {"query_function", "health_check_function"}


def _base_payload(entry: BaseEntry) -> dict[str, Any]:
    """Common payload fields for every entry, independent of registry type.

    Callable fields (query_function, health_check_function) are excluded
    from the dump — Pydantic can't serialize them to JSON and they'd
    pollute the API response with repr strings anyway.
    """
    return entry.model_dump(mode="json", exclude=_CALLABLE_FIELDS)


def _enrich_action(entry) -> dict[str, Any]:
    return _base_payload(entry)


def _enrich_decision(entry) -> dict[str, Any]:
    return _base_payload(entry)


def _enrich_state(entry, conn: sqlite3.Connection) -> dict[str, Any]:
    payload = _base_payload(entry)
    prior = _read_view_state(conn, entry.name)
    called = _call_with_timeout(entry.query_function, name=entry.name)
    payload["live"] = called
    if called["status"] == "ok":
        value = called["result"]
        prev_value = None
        if prior and prior.get("last_viewed_value"):
            try:
                prev_value = json.loads(prior["last_viewed_value"])
            except (TypeError, json.JSONDecodeError):
                prev_value = None
        payload["delta_since_last_view"] = _compute_delta(prev_value, value)
        # Persist the new baseline — GET side-effect is accepted per
        # evaluation §R5.4. Only update if the call succeeded so we
        # preserve the last known-good baseline on transient failure.
        try:
            _write_view_state(conn, entry.name, value)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[SYSTEM_INDEX] failed to update view_state for %s: %r", entry.name, exc)
    else:
        payload["delta_since_last_view"] = None
    payload["last_reviewed_date_override"] = (
        prior.get("last_reviewed_date_override") if prior else None
    )
    payload["last_viewed_at"] = prior.get("last_viewed_at") if prior else None
    return payload


def _enrich_system(entry, conn: sqlite3.Connection) -> dict[str, Any]:
    payload = _base_payload(entry)
    called = _call_with_timeout(entry.health_check_function, name=entry.name)
    payload["health"] = called
    prior = _read_view_state(conn, entry.name)
    payload["last_reviewed_date_override"] = (
        prior.get("last_reviewed_date_override") if prior else None
    )
    return payload


def _cloud_shadow_trade_cohort(runtime) -> dict[str, Any]:
    from src.shadow_trading._status_sql import active_in_clause, terminal_in_clause

    active_frag, active_params = active_in_clause()
    terminal_frag, terminal_params = terminal_in_clause()
    row = runtime.query_one(
        "SELECT "
        f"SUM(CASE WHEN status IN ({active_frag}) THEN 1 ELSE 0 END) AS open_n, "
        f"SUM(CASE WHEN status IN ({terminal_frag}) THEN 1 ELSE 0 END) AS closed_n, "
        "SUM(CASE WHEN COALESCE(quarantined, 0) = 1 THEN 1 ELSE 0 END) AS quarantined_n, "
        "COUNT(*) AS total_n "
        "FROM shadow_trades",
        active_params + terminal_params,
    ) or {}
    return {
        "value": {
            "open": int(row.get("open_n") or 0),
            "closed": int(row.get("closed_n") or 0),
            "quarantined": int(row.get("quarantined_n") or 0),
            "total": int(row.get("total_n") or 0),
        },
    }


def _cloud_strategy_registry_state(runtime) -> dict[str, Any]:
    rows = runtime.query(
        "SELECT current_status, COUNT(*) AS n "
        "FROM strategy_registry GROUP BY current_status"
    )
    by_status = {
        (row.get("current_status") or "unknown"): int(row.get("n") or 0)
        for row in rows
    }
    return {"value": {"total": sum(by_status.values()), "by_status": by_status}}


def _cloud_training_corpus(runtime) -> dict[str, Any]:
    outcome_rows = runtime.query(
        "SELECT UPPER(COALESCE(outcome_type, 'UNKNOWN')) AS outcome, "
        "COUNT(*) AS n FROM training_examples "
        "GROUP BY UPPER(COALESCE(outcome_type, 'UNKNOWN'))"
    )
    source_rows = runtime.query(
        "SELECT COALESCE(source, 'unknown') AS source, COUNT(*) AS n "
        "FROM training_examples GROUP BY COALESCE(source, 'unknown')"
    )
    total_row = runtime.query_one("SELECT COUNT(*) AS c FROM training_examples") or {}
    return {
        "value": {
            "total": int(total_row.get("c") or 0),
            "by_outcome": {
                row.get("outcome") or "UNKNOWN": int(row.get("n") or 0)
                for row in outcome_rows
            },
            "by_source": {
                row.get("source") or "unknown": int(row.get("n") or 0)
                for row in source_rows
            },
        },
    }


def _cloud_bootcamp_mode() -> dict[str, Any]:
    try:
        from src.config import load_config

        cfg = load_config()
        bootcamp = (cfg.get("bootcamp") or {}) if cfg else {}
    except Exception:
        bootcamp = {}
    return {
        "value": {
            "enabled": bool(bootcamp.get("enabled", False)),
            "phase": int(bootcamp.get("phase", 0)) if bootcamp.get("enabled") else None,
            "qualification_threshold": int(bootcamp.get("qualification_threshold", 0) or 0),
            "email_mode": bootcamp.get("email_mode", "digest"),
        },
    }


_CLOUD_STATE_RESOLVERS = {
    "shadow_trade_cohort": _cloud_shadow_trade_cohort,
    "strategy_registry_state": _cloud_strategy_registry_state,
    "training_corpus": _cloud_training_corpus,
    "bootcamp_mode": lambda runtime: _cloud_bootcamp_mode(),
}


def _has_cloud_runtime(runtime) -> bool:
    return (
        hasattr(runtime, "query")
        and callable(getattr(runtime, "query"))
        and hasattr(runtime, "query_one")
        and callable(getattr(runtime, "query_one"))
    )


def _cloud_call_state(entry, runtime) -> dict[str, Any]:
    resolver = _CLOUD_STATE_RESOLVERS.get(entry.name)
    if resolver is None:
        return _call_with_timeout(entry.query_function, name=entry.name)
    try:
        return {"status": "ok", "result": resolver(runtime)}
    except Exception as exc:  # noqa: BLE001
        logger.warning("[SYSTEM_INDEX] cloud resolver '%s' raised: %r", entry.name, exc)
        return {"status": "unavailable", "error": str(exc)}


def _enrich_state_cloud(entry, runtime) -> dict[str, Any]:
    payload = _base_payload(entry)
    payload["live"] = _cloud_call_state(entry, runtime)
    payload["delta_since_last_view"] = None
    payload["last_reviewed_date_override"] = None
    payload["last_viewed_at"] = None
    return payload


def _enrich_system_cloud(entry) -> dict[str, Any]:
    payload = _base_payload(entry)
    payload["health"] = _call_with_timeout(entry.health_check_function, name=entry.name)
    payload["last_reviewed_date_override"] = None
    return payload


def _compute_counts(actions, states, systems, decisions) -> dict[str, Any]:
    from datetime import timedelta
    stale_threshold = date.today() - timedelta(days=180)
    by_category: dict[str, int] = {}
    deprecated = 0
    needs_review = 0
    for entry in list(actions) + list(states) + list(systems) + list(decisions):
        by_category[entry.category] = by_category.get(entry.category, 0) + 1
        if entry.deprecated:
            deprecated += 1
        if entry.last_reviewed_date < stale_threshold:
            needs_review += 1
    return {
        "total": len(actions) + len(states) + len(systems) + len(decisions),
        "by_category": by_category,
        "deprecated": deprecated,
        "needs_review": needs_review,
    }


def _build_offline_payload(actions, states, systems, decisions) -> dict[str, Any]:
    """Payload shape when local SQLite is unreachable — registries only."""
    return {
        "generated_at": _utc_now_iso(),
        "actions": [_enrich_action(a) for a in actions],
        "states": [
            {**_base_payload(s), "live": {"status": "unavailable", "error": "sqlite_unavailable"}, "delta_since_last_view": None}
            for s in states
        ],
        "systems": [
            {**_base_payload(s), "health": {"status": "unavailable", "error": "sqlite_unavailable"}}
            for s in systems
        ],
        "decisions": [_enrich_decision(d) for d in decisions],
        "counts": _compute_counts(actions, states, systems, decisions),
    }


def _build_live_payload(conn, actions, states, systems, decisions) -> dict[str, Any]:
    """Normal payload shape with live state/health enrichment."""
    return {
        "generated_at": _utc_now_iso(),
        "actions": [_enrich_action(a) for a in actions],
        "states": [_enrich_state(s, conn) for s in states],
        "systems": [_enrich_system(s, conn) for s in systems],
        "decisions": [_enrich_decision(d) for d in decisions],
        "counts": _compute_counts(actions, states, systems, decisions),
    }


def _build_cloud_payload(runtime, actions, states, systems, decisions) -> dict[str, Any]:
    """Cloud payload shape when local SQLite is unavailable."""
    return {
        "generated_at": _utc_now_iso(),
        "actions": [_enrich_action(a) for a in actions],
        "states": [_enrich_state_cloud(s, runtime) for s in states],
        "systems": [_enrich_system_cloud(s) for s in systems],
        "decisions": [_enrich_decision(d) for d in decisions],
        "counts": _compute_counts(actions, states, systems, decisions),
    }


def create_router(runtime, verify_auth) -> APIRouter:
    """Build the /api/system/index router.

    `runtime` is the cloud_app SimpleNamespace. Local mode uses SQLite for
    view-state persistence; cloud mode falls back to runtime/Postgres-backed
    resolvers when local SQLite is unavailable.
    """
    router = APIRouter()

    @router.get("/api/system/index", dependencies=[Depends(verify_auth)])
    def system_index() -> dict[str, Any]:
        ensure_bootstrapped()
        actions = list_actions()
        states = list_states()
        systems = list_systems()
        decisions = list_decisions()

        try:
            conn = _open_sqlite()
        except Exception as exc:
            logger.warning("[SYSTEM_INDEX] unable to open local SQLite (%s): %r", type(exc).__name__, exc)
            if _has_cloud_runtime(runtime):
                return _build_cloud_payload(runtime, actions, states, systems, decisions)
            return _build_offline_payload(actions, states, systems, decisions)

        try:
            return _build_live_payload(conn, actions, states, systems, decisions)
        except Exception as exc:
            logger.warning("[SYSTEM_INDEX] _build_live_payload raised (%s): %r", type(exc).__name__, exc)
            if _has_cloud_runtime(runtime):
                return _build_cloud_payload(runtime, actions, states, systems, decisions)
            return _build_offline_payload(actions, states, systems, decisions)
        finally:
            conn.close()

    @router.post(
        "/api/system/index/{entry_name}/mark-reviewed",
        dependencies=[Depends(verify_auth)],
    )
    def mark_reviewed(entry_name: str) -> dict[str, Any]:
        ensure_bootstrapped()
        found = (
            get_action(entry_name)
            or get_state(entry_name)
            or get_system(entry_name)
            or get_decision(entry_name)
        )
        if not found:
            raise HTTPException(status_code=404, detail=f"capability {entry_name!r} not found")
        try:
            conn = _open_sqlite()
            try:
                reviewed = _write_reviewed_override(conn, entry_name)
                return {
                    "entry_name": entry_name,
                    "last_reviewed_date_override": reviewed,
                }
            finally:
                conn.close()
        except Exception as exc:
            logger.error("[SYSTEM_INDEX] mark-reviewed local state unavailable for %s (%s): %r", entry_name, type(exc).__name__, exc)
            raise HTTPException(status_code=503, detail="local state unavailable") from exc

    return router
