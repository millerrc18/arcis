"""Provenance guard — anti-hollow-STABLE check (T8, #97).

assert_real_path_executed() proves that a simulation run drove the REAL
production code path, not a hollow shortcut that would let a broken prod
path produce a green STABLE verdict. Asserts three properties: patched
seam call-counts >= 1; every shadow_trade row carries an executor-only
order_type; runtime DSN identity (5434 sim, never prod) and inv9 columns.

Called by: src.simulation.lifecycle.scenario.ScenarioRunner.run (T9).
Calls: nothing (pure Python introspection).
Owns tables: none.
Config keys: none.
Tests: tests/simulation/lifecycle/test_provenance.py
"""
from __future__ import annotations

from collections import Counter
from typing import Any

# ── inv9 hashed column set (spec §3.4 / §4.6) ───────────────────────────────
INV9_HASHED_COLUMNS: tuple[str, ...] = (
    "recommendation_id",
    "ticker",
    "status",
    "actual_shares",
    "order_type",
    "exit_reason",
    "pnl_dollars",
)

# ── executor-only order_type values (executor.py:889/925) ────────────────────
_EXECUTOR_ONLY_ORDER_TYPES: frozenset[str] = frozenset(
    {"bracket", "simple_with_stop"}
)

# ── sim DSN signature (docker-compose.test.yml: user=test pass=test port=5434)
_SIM_PORT_FRAGMENT = ":5434/"
_SIM_CRED_FRAGMENT = "test:test"


class ProvenanceError(Exception):
    """Raised when a provenance property fails.

    The message names the specific property that failed and includes the
    offending values so the cause is immediately diagnosable.
    """


def _get_conn_dsn(oracle_conn: Any) -> str:
    """Extract the DSN string from a connection-like object or string."""
    if isinstance(oracle_conn, str):
        return oracle_conn
    dsn = getattr(oracle_conn, "dsn", None)
    if dsn is not None:
        return str(dsn)
    info = getattr(oracle_conn, "info", None)
    if info is not None:
        dsn = getattr(info, "dsn", None)
        if dsn is not None:
            return str(dsn)
    raise ProvenanceError(
        f"oracle_conn has no .dsn attribute; cannot verify DSN identity. "
        f"Got type: {type(oracle_conn).__name__}"
    )


def _check_seam_counts(fake_tc: Any, fake_md: Any, fake_llm: Any) -> None:
    """Assert all patched seam call-counts are >= 1 (Property 1)."""
    md_calls: Counter = getattr(fake_md, "calls", Counter())
    tc_calls: Counter = getattr(fake_tc, "calls", Counter())
    llm_calls: Counter = getattr(fake_llm, "calls", Counter())
    checks = [
        ("fetch_ohlcv", md_calls["fetch_ohlcv"]),
        ("fetch_spy",   md_calls["fetch_spy"]),
        ("generate",    llm_calls["generate"]),
        ("get_account", tc_calls["get_account"]),
        ("submit_order", tc_calls["submit_order"]),
    ]
    for seam_name, count in checks:
        if count < 1:
            raise ProvenanceError(
                f"seam '{seam_name}' was never invoked (count={count}). "
                f"The patched seam was not reached by the real code path — "
                f"a missed monkeypatch or early-return caused a hollow run."
            )


def _check_order_types(rows: list[dict]) -> None:
    """Assert every row carries an executor-only order_type (Property 2)."""
    for idx, row in enumerate(rows):
        ot = row.get("order_type")
        if ot not in _EXECUTOR_ONLY_ORDER_TYPES:
            raise ProvenanceError(
                f"row[{idx}] has order_type={ot!r} which is NOT in the "
                f"executor-only set {sorted(_EXECUTOR_ONLY_ORDER_TYPES)!r}. "
                f"Only executor.place_bracket_order writes 'bracket' or "
                f"'simple_with_stop'. This row was not written by the real "
                f"executor."
            )


def _check_inv9_columns(rows: list[dict]) -> None:
    """Assert every row covers the inv9-hashed columns (Property 3a)."""
    for idx, row in enumerate(rows):
        for col in INV9_HASHED_COLUMNS:
            if col not in row:
                raise ProvenanceError(
                    f"row[{idx}] is missing inv9-hashed column '{col}'. "
                    f"All of {INV9_HASHED_COLUMNS!r} are required. "
                    f"A missing column means the INSERT did not cover the "
                    f"expected schema."
                )


def _check_dsn_identity(oracle_conn: Any, primed_dsn: str) -> None:
    """Assert oracle_conn DSN == primed_dsn == 5434 sim signature (Property 3b)."""
    conn_dsn = _get_conn_dsn(oracle_conn)
    if conn_dsn != primed_dsn:
        raise ProvenanceError(
            f"DSN mismatch: oracle_conn.dsn={conn_dsn!r} does not equal "
            f"primed_dsn={primed_dsn!r}. The oracle connection must match "
            f"the DB load_config was primed with."
        )
    for dsn, label in ((conn_dsn, "oracle_conn.dsn"), (primed_dsn, "primed_dsn")):
        missing = []
        if _SIM_PORT_FRAGMENT not in dsn:
            missing.append(f"port fragment '{_SIM_PORT_FRAGMENT}'")
        if _SIM_CRED_FRAGMENT not in dsn:
            missing.append(f"credential fragment '{_SIM_CRED_FRAGMENT}'")
        if missing:
            raise ProvenanceError(
                f"DSN identity check failed for {label}: missing "
                f"{', '.join(missing)}. This DSN may point at prod — "
                f"NEVER run the sim gate against prod. DSN={dsn!r}"
            )


def assert_real_path_executed(
    fake_tc: Any,
    fake_md: Any,
    fake_llm: Any,
    oracle_conn: Any,
    primed_dsn: str,
    rows: list[dict],
) -> None:
    """Assert the REAL prod path was exercised. Raises ProvenanceError on miss.

    Parameters: fake_tc (FakeTradingClient), fake_md (FakeMarketData),
    fake_llm (FakeLLM), oracle_conn (psycopg2/asyncpg connection or stub
    with .dsn), primed_dsn (DSN primed into load_config), rows (open
    shadow_trade row dicts). Returns None on success.
    """
    _check_seam_counts(fake_tc, fake_md, fake_llm)
    _check_order_types(rows)
    _check_inv9_columns(rows)
    _check_dsn_identity(oracle_conn, primed_dsn)
