"""DB-derived invariant checks for the lifecycle Oracle (Task 9).

Called by: src.simulation.lifecycle.oracle.invariants
Calls: none (stdlib hashlib + psycopg connection passed in)
Owns tables: none (read-only SELECTs against the ephemeral 5434 sim Postgres)
Config keys: none
Tests: tests/simulation/lifecycle/test_oracle.py

These checks query the ephemeral 5434 Postgres the simulator wrote to and
return an ``InvariantResult`` each. Invariants 1, 2, 3, 7 and the determinism
snapshot (invariant 9) live here; the signal/observer-derived checks (4, 5, 6,
8) live in ``_checks_signal``.

Every SELECT carries an explicit ORDER BY on a stable BUSINESS key (spec §7.2
determinism): never a SERIAL / autoincrement PK and never a raw timestamp, so
two identical seeded runs produce an identical row order and hash.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import closing

from src.shadow_trading.reconcile import SYNTHETIC_EXIT_REASONS
from src.simulation.lifecycle.oracle._result import InvariantResult


def check_attribution(conn) -> InvariantResult:
    """Invariant 1 — 1:1 attribution: every non-reconciled trade links a rec.

    A non-reconciled shadow_trades row with a NULL recommendation_id has no
    recommendation behind it. (Reconciled rows are caught separately by
    invariant 2; here we only assert the attribution link for the rest.)
    """
    with closing(conn.cursor()) as cur:
        cur.execute(
            "SELECT trade_id FROM shadow_trades "
            "WHERE (order_type IS NULL OR order_type <> 'reconciled') "
            "  AND recommendation_id IS NULL "
            "ORDER BY trade_id"
        )
        unattributed = [r[0] for r in cur.fetchall()]
    passed = not unattributed
    detail = (
        "every non-reconciled trade links a recommendation"
        if passed
        else f"{len(unattributed)} unattributed trade(s): {unattributed}"
    )
    return InvariantResult(
        name="attribution_1to1", passed=passed, detail=detail,
        degraded_correctly=passed, error_swallowed=False,
    )


def check_zero_orphans(conn) -> InvariantResult:
    """Invariant 2 — zero orphans (also catches the reconcile tz-coercion effect).

    COUNT of rows where order_type='reconciled' OR recommendation_id IS NULL
    must be 0. This is also where the reconcile.py:128-131 tz-coercion
    fail-conservative branch is caught: that branch logs NOTHING (so it is NOT
    observable via the SwallowedErrorObserver), but its EFFECT is an orphan /
    reconciled row, which lands here.
    """
    with closing(conn.cursor()) as cur:
        cur.execute(
            "SELECT trade_id FROM shadow_trades "
            "WHERE order_type = 'reconciled' OR recommendation_id IS NULL "
            "ORDER BY trade_id"
        )
        orphans = [r[0] for r in cur.fetchall()]
    passed = not orphans
    detail = (
        "no orphan / reconciled rows"
        if passed
        else f"{len(orphans)} orphan / reconciled row(s): {orphans}"
    )
    return InvariantResult(
        name="zero_orphans", passed=passed, detail=detail,
        degraded_correctly=passed, error_swallowed=False,
    )


def check_zero_synthetic_closes(conn) -> InvariantResult:
    """Invariant 3 — zero reconciled_stale / synthetic _resolve_stuck_pnl closes.

    A close with any exit_reason in SYNTHETIC_EXIT_REASONS (sourced from
    src.shadow_trading.reconcile, the prod source-of-truth) is one the
    platform fabricated rather than executed. Count must be 0. Adding a new
    synthetic exit_reason in reconcile.py automatically extends this gate
    (no drift between prod and the oracle).
    """
    placeholders = ", ".join(["%s"] * len(SYNTHETIC_EXIT_REASONS))
    with closing(conn.cursor()) as cur:
        cur.execute(
            f"SELECT trade_id FROM shadow_trades "
            f"WHERE exit_reason IN ({placeholders}) "
            f"ORDER BY trade_id",
            tuple(sorted(SYNTHETIC_EXIT_REASONS)),
        )
        synthetic = [r[0] for r in cur.fetchall()]
    passed = not synthetic
    detail = (
        "no synthetic / reconciled_stale closes"
        if passed
        else f"{len(synthetic)} synthetic close(s): {synthetic}"
    )
    return InvariantResult(
        name="zero_synthetic_closes", passed=passed, detail=detail,
        degraded_correctly=passed, error_swallowed=False,
    )


def check_corpus_integrity(conn) -> InvariantResult:
    """Invariant 7 — only clean measured trades become training_examples.

    The empty-holdout case must BLOCK promotion: when there are no measured
    (non-quarantined, non-synthetic) training examples, no model version may be
    registered. A registered model on an empty measured corpus is a violation.
    """
    with closing(conn.cursor()) as cur:
        cur.execute(
            "SELECT COUNT(*) FROM training_examples "
            "WHERE COALESCE(quarantined, 0) = 0 AND source <> 'synthetic'"
        )
        measured = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM model_versions")
        models = cur.fetchone()[0]
    promotion_on_empty = measured == 0 and models > 0
    passed = not promotion_on_empty
    detail = (
        f"measured_examples={measured}, model_versions={models}"
        if passed
        else f"promotion on empty holdout: measured=0 but {models} model(s) registered"
    )
    return InvariantResult(
        name="corpus_integrity", passed=passed, detail=detail,
        degraded_correctly=passed, error_swallowed=False,
    )


# ── invariant 9: deterministic reproducibility ─────────────────────────────────

# (table, business-key ORDER BY columns, value columns hashed). Surrogate /
# SERIAL PKs and raw timestamps are EXCLUDED from the hashed value set; ordering
# uses stable business keys only (spec §7.2).
_SNAPSHOT_QUERIES = (
    (
        "shadow_trades",
        ("recommendation_id", "ticker", "order_type"),
        ("recommendation_id", "ticker", "status", "actual_shares",
         "order_type", "exit_reason", "pnl_dollars"),
    ),
    (
        "training_examples",
        ("source", "ticker", "recommendation_id"),
        ("source", "ticker", "recommendation_id", "quarantined", "outcome"),
    ),
    (
        "model_versions",
        ("version_name", "status"),
        ("version_name", "status", "training_examples_count", "holdout_score"),
    ),
)


def canonical_snapshot_hash(conn) -> str:
    """Return a stable SHA-256 of the business-meaningful DB snapshot.

    EXCLUDES SERIAL/autoincrement surrogate keys and raw timestamps; ORDERs every
    query by stable business keys; assumes PYTHONHASHSEED=0 (pinned by bootstrap).
    Two identical seeded runs hash identically; any real data change differs.
    """
    hasher = hashlib.sha256()
    with closing(conn.cursor()) as cur:
        for table, order_cols, value_cols in _SNAPSHOT_QUERIES:
            cols = ", ".join(value_cols)
            order_by = ", ".join(order_cols)
            cur.execute(f"SELECT {cols} FROM {table} ORDER BY {order_by}")
            hasher.update(f"::{table}::".encode())
            for row in cur.fetchall():
                # json.dumps with sort_keys + default=str is a documented canonical
                # serializer — stable across CPython rebuilds and across container
                # images. repr() on Decimal/datetime/None is NOT a documented
                # canonical format, so use json for cross-environment determinism
                # (#98 review should-fix #6, 2026-05-23).
                hasher.update(
                    json.dumps(list(row), sort_keys=True, default=str).encode()
                )
    return hasher.hexdigest()


def check_deterministic_reproducibility(conn) -> InvariantResult:
    """Invariant 9 — emit the canonical snapshot hash as the result detail."""
    digest = canonical_snapshot_hash(conn)
    return InvariantResult(
        name="deterministic_reproducibility", passed=True, detail=digest,
        degraded_correctly=True, error_swallowed=False,
    )
