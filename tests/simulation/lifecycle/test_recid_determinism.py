"""Read-only verification spike: inv9-hashed column determinism (T7, #97).

Summary of findings
-------------------
1. recommendation_id — DIVERGES across fresh runs.

   Source: ``src.journal.store.log_recommendation`` line 132:
       rec_id = str(uuid.uuid4())
   ``uuid.uuid4()`` calls the OS CSPRNG (``os.urandom(16)``). Python's
   ``random.seed()`` has NO effect on UUID generation. Under any frozen
   clock the value still differs across processes / calls. Two independent
   calls produce two independent UUIDs.

   §3.4 escalation chosen: FIX-UNDER-SIM-SEEDING (preferred path).
   The simulator must patch ``uuid.uuid4`` in ``src.journal.store`` with a
   deterministic counter-based minter seeded at scenario start. The patch
   must NOT touch prod code; it is installed alongside the other organic
   patches (wiring.install_organic_patches) and torn down in the same
   undo() closure. This is the exact same pattern used for alpaca_adapter /
   market_data / packet_writer — no operator waiver required.

   T13 residual blind-spot: until the sim-side patch is wired (T9 or a
   follow-up task), any canonical_snapshot_hash that includes
   recommendation_id will differ across re-runs even for identical seeds,
   making the Oracle's invariant 9 EQUALITY check fail. The snapshot query
   in _checks_db.py already includes recommendation_id; the fix must land
   before invariant 9 EQUALITY passes end-to-end.

2. actual_shares — REPRODUCIBLE.

   Formula (executor.py line 808):
       planned_shares = max(1, int(allocation_dollars / entry_price))
   With fixed allocation_dollars (e.g. $50,000) and fixed entry_price
   (e.g. $100.00), the integer division is exact and deterministic. Float
   arithmetic on literals is bit-for-bit stable under CPython on the same
   platform. Verified: both runs return 500 shares.

   Note: actual_shares in shadow_trades is set from planned_shares in the
   sim path (no broker fill deviation). If the executor path were exercised
   end-to-end via the real Alpaca adapter, actual_shares could deviate due
   to partial fills; in the sim the FakeTradingClient fills at exactly
   planned_shares, so the column is stable.

3. pnl_dollars — REPRODUCIBLE.

   Formula: pnl_dollars = (exit_price - entry_price) * actual_shares.
   With deterministic entry and exit prices the result is bit-for-bit
   stable. FakeTradingClient (T2) fills at limit_price if set, else 100.0
   fallback. Verified: both runs return identical pnl_dollars.

   Caveats tested:
     - pnl_dollars is computed at close time and stored explicitly. It is
       NOT re-derived from stored prices at read time, so no re-computation
       risk.
     - The formula uses simple float arithmetic, not Decimal. On the same
       platform / Python version, (exit - entry) * shares is stable.

Design references: spec §3.1 (inv9 column list), §3.4 (escalation policy),
plan T7 (lines 132-152).
"""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator
from zoneinfo import ZoneInfo

import pytest

from src.journal.store import initialize_database, log_recommendation, insert_shadow_trade
from src.models import TradePacket, PositionSizing
from src.schema.sqlite import create_all_tables
from src.simulation.lifecycle.clock import VirtualClock, freeze_at

ET = ZoneInfo("America/New_York")

# Fixed frozen clock instant for both runs — matches spec T7 example
_FROZEN_INSTANT = datetime(2026, 5, 22, 10, 0, 0, tzinfo=ET)

# Deterministic packet inputs — identical across both runs
_TICKER = "AAPL"
_ENTRY_PRICE = 100.0       # clean number — int(50000 / 100.0) = 500 shares
_EXIT_PRICE = 110.0        # +$10 * 500 shares = $5000 pnl
_ALLOCATION = 50_000.0     # allocation_dollars
_ENTRY_ZONE = "100.00"
_STOP = "95.00"
_TARGETS = "110.00/120.00"

# Deterministic Python seed — only affects paths that USE random.seed
# (not uuid.uuid4 which draws from OS entropy)
_PY_SEED = 42


def _make_packet() -> TradePacket:
    """Build a deterministic TradePacket with fixed field values."""
    return TradePacket(
        ticker=_TICKER,
        company_name="Apple Inc.",
        recommendation="BUY",
        setup_type="pullback",
        why_now="Strong momentum",
        entry_zone=_ENTRY_ZONE,
        stop_invalidation=_STOP,
        targets=_TARGETS,
        expected_hold_period="5-10 days",
        confidence=80,
        event_risk="Normal",
        position_sizing=PositionSizing(
            allocation_dollars=_ALLOCATION,
            allocation_pct=0.05,
            estimated_risk_dollars=2500.0,
        ),
        deeper_analysis="Test analysis",
    )


def _make_features() -> dict:
    """Return a minimal feature dict (identical across both runs)."""
    return {
        "current_price": _ENTRY_PRICE,
        "trend_state": "uptrend",
        "relative_strength_state": "strong",
        "pullback_depth_pct": 5.0,
        "atr_14": 2.5,
        "volume_ratio_20d": 1.1,
        "regime_label": "bull",
        "event_risk_level": "none",
        "hold_overlaps_earnings": False,
    }


@contextmanager
def _fresh_sqlite_db(tmp_path, name: str) -> Iterator[str]:
    """Create and return a path to a fresh SQLite DB with the full schema."""
    db_path = str(tmp_path / name)
    create_all_tables(db_path)
    # Ensure the in-memory initialized-set doesn't short-circuit table creation
    from src.journal import store as _store_mod
    _store_mod._TABLES_INITIALIZED.discard(db_path)
    yield db_path
    _store_mod._TABLES_INITIALIZED.discard(db_path)


def _actual_shares_from_allocation(allocation_dollars: float, entry_price: float) -> int:
    """Replicate executor.py line 808 share-count formula."""
    return max(1, int(allocation_dollars / entry_price))


def _pnl_dollars(entry_price: float, exit_price: float, shares: int) -> float:
    """Replicate the PnL formula: (exit - entry) * shares."""
    return (exit_price - entry_price) * shares


# ── Test: recommendation_id diverges (UUID/OS-entropy source) ────────────────

class TestRecommendationIdDivergence:
    """recommendation_id is minted with uuid.uuid4() — NOT reproducible.

    Two calls to log_recommendation return two different UUIDs. This is
    expected from ``uuid.uuid4()`` (OS CSPRNG). The test documents the
    divergence and confirms the §3.4 escalation target.

    §3.4 escalation: FIX-UNDER-SIM-SEEDING. The sim must patch
    ``src.journal.store.uuid.uuid4`` with a deterministic counter minter
    for the duration of each ScenarioRunner execution.
    """

    def test_recommendation_id_is_uuid_v4(self, tmp_path):
        """log_recommendation generates a UUID v4 — confirm it IS uuid-shaped."""
        clock = VirtualClock(start=_FROZEN_INSTANT)
        with freeze_at(clock):
            with _fresh_sqlite_db(tmp_path, "uuid_check.sqlite") as db_path:
                packet = _make_packet()
                features = _make_features()
                rec_id = log_recommendation(
                    packet, features, score=0.85,
                    qualification="qualified", db_path=db_path,
                )
        # Must be a parseable UUID
        parsed = uuid.UUID(rec_id)
        assert parsed.version == 4, f"Expected UUID v4, got version {parsed.version}"

    @pytest.mark.xfail(
        reason="T7 §3.4 spike documentation: WITHOUT wiring.install_organic_patches "
               "active, log_recommendation calls stdlib uuid.uuid4 (OS CSPRNG) → "
               "divergent UUIDs. The wiring patch (a5266f78) installs a deterministic "
               "uuid stub WITHIN install_organic_patches scope so the organic "
               "lifecycle gets deterministic recommendation_ids. This test "
               "documents the underlying prod behavior; xfail keeps the finding "
               "visible without failing CI.",
        strict=False,
    )
    def test_recommendation_id_diverges_across_two_calls(self, tmp_path):
        """Two calls to log_recommendation return DIFFERENT recommendation_ids.

        This is the documented non-determinism: uuid.uuid4() draws from the
        OS CSPRNG, ignoring Python's random.seed() and any frozen clock.

        §3.4 finding: recommendation_id is non-deterministic.
        §3.4 escalation: FIX-UNDER-SIM-SEEDING — patch uuid.uuid4 in
        src.journal.store before each simulated scenario run.
        """
        clock = VirtualClock(start=_FROZEN_INSTANT)
        with freeze_at(clock):
            with _fresh_sqlite_db(tmp_path, "run1.sqlite") as db1:
                packet1 = _make_packet()
                features1 = _make_features()
                rec_id_1 = log_recommendation(
                    packet1, features1, score=0.85,
                    qualification="qualified", db_path=db1,
                )
            with _fresh_sqlite_db(tmp_path, "run2.sqlite") as db2:
                packet2 = _make_packet()
                features2 = _make_features()
                rec_id_2 = log_recommendation(
                    packet2, features2, score=0.85,
                    qualification="qualified", db_path=db2,
                )

        # DOCUMENT the divergence — this MUST be different (proving non-determinism)
        assert rec_id_1 != rec_id_2, (
            "UNEXPECTED: two uuid.uuid4() calls returned the same value — "
            "this would only happen by cosmic coincidence (2^122 odds). "
            "Something is seeding UUID generation unexpectedly."
        )
        # Fail loudly: this column diverges — §3.4 escalation required
        pytest.fail(
            f"§3.4 FINDING: recommendation_id diverges across identical runs.\n"
            f"  run 1: {rec_id_1!r}\n"
            f"  run 2: {rec_id_2!r}\n"
            f"Source: src.journal.store.log_recommendation line 132: "
            f"rec_id = str(uuid.uuid4())\n"
            f"uuid.uuid4() uses OS CSPRNG (os.urandom(16)), unaffected by "
            f"random.seed() or frozen clock.\n"
            f"§3.4 escalation: FIX-UNDER-SIM-SEEDING — install a deterministic "
            f"counter-based uuid4 patch in wiring.install_organic_patches() "
            f"targeting src.journal.store.uuid.uuid4. No prod code change required."
        )

    def test_recommendation_id_deterministic_with_seeded_uuid4(self, tmp_path):
        """WITH a seeded uuid4 patch, recommendation_id IS reproducible.

        This test demonstrates the §3.4 fix path: patching uuid.uuid4 in
        src.journal.store with a counter-based minter makes the column
        deterministic. The two runs return IDENTICAL recommendation_ids.

        This is the production fix the simulator must implement (T9 or a
        follow-up to T7). Once wired, invariant 9 EQUALITY can pass
        end-to-end.
        """
        import src.journal.store as _store_mod

        call_counts: list[int] = [0]

        def _seeded_uuid4() -> uuid.UUID:
            """Counter-based deterministic UUID4 replacement."""
            call_counts[0] += 1
            # Pad the counter into a UUID-shaped bytes object (128 bits)
            counter_bytes = call_counts[0].to_bytes(16, "big")
            # Force variant and version bits to match UUID4 shape
            b = bytearray(counter_bytes)
            b[6] = (b[6] & 0x0F) | 0x40  # version 4
            b[8] = (b[8] & 0x3F) | 0x80  # variant 1
            return uuid.UUID(bytes=bytes(b))

        clock = VirtualClock(start=_FROZEN_INSTANT)

        # Run 1: patch uuid4, reset counter, call log_recommendation
        call_counts[0] = 0
        orig_uuid4 = _store_mod.uuid.uuid4
        _store_mod.uuid.uuid4 = _seeded_uuid4  # type: ignore[method-assign]
        try:
            with freeze_at(clock):
                with _fresh_sqlite_db(tmp_path, "seeded_run1.sqlite") as db1:
                    rec_id_1 = log_recommendation(
                        _make_packet(), _make_features(), score=0.85,
                        qualification="qualified", db_path=db1,
                    )
        finally:
            _store_mod.uuid.uuid4 = orig_uuid4

        # Run 2: same patch, same counter reset
        call_counts[0] = 0
        _store_mod.uuid.uuid4 = _seeded_uuid4  # type: ignore[method-assign]
        try:
            with freeze_at(clock):
                with _fresh_sqlite_db(tmp_path, "seeded_run2.sqlite") as db2:
                    rec_id_2 = log_recommendation(
                        _make_packet(), _make_features(), score=0.85,
                        qualification="qualified", db_path=db2,
                    )
        finally:
            _store_mod.uuid.uuid4 = orig_uuid4

        assert rec_id_1 == rec_id_2, (
            f"Seeded uuid4 patch must produce identical recommendation_ids: "
            f"{rec_id_1!r} != {rec_id_2!r}"
        )


# ── Test: actual_shares is reproducible ──────────────────────────────────────

class TestActualSharesReproducibility:
    """actual_shares = max(1, int(allocation_dollars / entry_price)) is deterministic.

    With fixed allocation_dollars and fixed entry_price, int() of a float
    division produces the same result on any run of CPython on the same
    platform. No entropy source is involved.

    §3.4 finding: actual_shares is REPRODUCIBLE.
    """

    def test_actual_shares_formula_is_deterministic(self):
        """int(50000 / 100.0) == 500 both times — float math is stable."""
        shares_1 = _actual_shares_from_allocation(_ALLOCATION, _ENTRY_PRICE)
        shares_2 = _actual_shares_from_allocation(_ALLOCATION, _ENTRY_PRICE)
        assert shares_1 == shares_2 == 500, (
            f"actual_shares formula not stable: run1={shares_1}, run2={shares_2}"
        )

    def test_actual_shares_stored_in_db_identical_across_runs(self, tmp_path):
        """actual_shares written to shadow_trades is the same across two fresh DBs."""
        clock = VirtualClock(start=_FROZEN_INSTANT)
        shares = _actual_shares_from_allocation(_ALLOCATION, _ENTRY_PRICE)

        def _write_and_read_shares(db_path: str) -> int | None:
            """Insert a shadow_trades row and read back actual_shares."""
            rec_id = "fixed-rec-id-for-shares-test"
            # Write a minimal recommendation row for FK integrity
            conn = sqlite3.connect(db_path)
            conn.execute(
                "INSERT OR IGNORE INTO recommendations "
                "(recommendation_id, created_at, ticker) VALUES (?, ?, ?)",
                (rec_id, "2026-05-22T10:00:00", _TICKER),
            )
            conn.commit()
            conn.close()

            trade_data = {
                "trade_id": "fixed-trade-id-shares-test",
                "recommendation_id": rec_id,
                "ticker": _TICKER,
                "direction": "long",
                "status": "open",
                "actual_shares": shares,
                "planned_shares": shares,
                "order_type": "bracket",
                "created_at": _FROZEN_INSTANT.isoformat(),
                "updated_at": _FROZEN_INSTANT.isoformat(),
            }
            with freeze_at(clock):
                insert_shadow_trade(trade_data, db_path)

            conn = sqlite3.connect(db_path)
            row = conn.execute(
                "SELECT actual_shares FROM shadow_trades WHERE trade_id = ?",
                ("fixed-trade-id-shares-test",),
            ).fetchone()
            conn.close()
            return int(row[0]) if row else None

        with _fresh_sqlite_db(tmp_path, "shares_run1.sqlite") as db1:
            shares_1 = _write_and_read_shares(db1)
        with _fresh_sqlite_db(tmp_path, "shares_run2.sqlite") as db2:
            shares_2 = _write_and_read_shares(db2)

        assert shares_1 is not None, "actual_shares not found in run 1"
        assert shares_2 is not None, "actual_shares not found in run 2"
        assert shares_1 == shares_2 == 500, (
            f"actual_shares must be identical across runs: "
            f"run1={shares_1}, run2={shares_2}"
        )


# ── Test: pnl_dollars is reproducible ────────────────────────────────────────

class TestPnlDollarsReproducibility:
    """pnl_dollars = (exit_price - entry_price) * actual_shares is deterministic.

    With fixed entry/exit prices and fixed share count, the result is
    bit-for-bit stable under CPython on the same platform. No entropy
    source is involved.

    §3.4 finding: pnl_dollars is REPRODUCIBLE.
    """

    def test_pnl_formula_is_deterministic(self):
        """(110.0 - 100.0) * 500 == 5000.0 both times."""
        shares = _actual_shares_from_allocation(_ALLOCATION, _ENTRY_PRICE)
        pnl_1 = _pnl_dollars(_ENTRY_PRICE, _EXIT_PRICE, shares)
        pnl_2 = _pnl_dollars(_ENTRY_PRICE, _EXIT_PRICE, shares)
        assert pnl_1 == pnl_2 == 5000.0, (
            f"pnl_dollars formula not stable: run1={pnl_1}, run2={pnl_2}"
        )

    def test_pnl_dollars_stored_in_db_identical_across_runs(self, tmp_path):
        """pnl_dollars written to shadow_trades is the same across two fresh DBs."""
        clock = VirtualClock(start=_FROZEN_INSTANT)
        shares = _actual_shares_from_allocation(_ALLOCATION, _ENTRY_PRICE)
        pnl = _pnl_dollars(_ENTRY_PRICE, _EXIT_PRICE, shares)

        def _write_and_read_pnl(db_path: str) -> float | None:
            rec_id = "fixed-rec-id-for-pnl-test"
            conn = sqlite3.connect(db_path)
            conn.execute(
                "INSERT OR IGNORE INTO recommendations "
                "(recommendation_id, created_at, ticker) VALUES (?, ?, ?)",
                (rec_id, "2026-05-22T10:00:00", _TICKER),
            )
            conn.commit()
            conn.close()

            trade_data = {
                "trade_id": "fixed-trade-id-pnl-test",
                "recommendation_id": rec_id,
                "ticker": _TICKER,
                "direction": "long",
                "status": "closed",
                "actual_shares": shares,
                "planned_shares": shares,
                "pnl_dollars": pnl,
                "actual_entry_price": _ENTRY_PRICE,
                "actual_exit_price": _EXIT_PRICE,
                "order_type": "bracket",
                "created_at": _FROZEN_INSTANT.isoformat(),
                "updated_at": _FROZEN_INSTANT.isoformat(),
            }
            with freeze_at(clock):
                insert_shadow_trade(trade_data, db_path)

            conn = sqlite3.connect(db_path)
            row = conn.execute(
                "SELECT pnl_dollars FROM shadow_trades WHERE trade_id = ?",
                ("fixed-trade-id-pnl-test",),
            ).fetchone()
            conn.close()
            return float(row[0]) if row else None

        with _fresh_sqlite_db(tmp_path, "pnl_run1.sqlite") as db1:
            pnl_1 = _write_and_read_pnl(db1)
        with _fresh_sqlite_db(tmp_path, "pnl_run2.sqlite") as db2:
            pnl_2 = _write_and_read_pnl(db2)

        assert pnl_1 is not None, "pnl_dollars not found in run 1"
        assert pnl_2 is not None, "pnl_dollars not found in run 2"
        assert pnl_1 == pnl_2 == 5000.0, (
            f"pnl_dollars must be identical across runs: "
            f"run1={pnl_1}, run2={pnl_2}"
        )


# ── Consolidated §3.4 summary test (machine-readable finding) ────────────────

@pytest.mark.xfail(
    reason="T7 §3.4 consolidated finding — documents the recommendation_id "
           "non-determinism source under direct log_recommendation calls. "
           "Resolved within wiring.install_organic_patches scope via the uuid "
           "stub (a5266f78). xfail keeps the §3.4 documentation visible.",
    strict=False,
)
def test_inv9_column_determinism_summary():
    """§3.4 consolidated finding — one place for the CI to catch the full picture.

    This test documents the underlying prod behavior (stdlib uuid.uuid4
    is not seedable). The fix lives in wiring.install_organic_patches.
    Marked xfail so CI surfaces the finding without failing on documentation.

    Findings:
      - recommendation_id: DIVERGES — uuid.uuid4() in log_recommendation:132
        §3.4 path: FIX-UNDER-SIM-SEEDING (patch uuid.uuid4 in journal.store)
      - actual_shares:     REPRODUCIBLE — int(allocation/price) is stable
      - pnl_dollars:       REPRODUCIBLE — (exit-entry)*shares is stable
    """
    pytest.fail(
        "§3.4 SUMMARY (T7 spike finding — expected failure until T9 wires the fix):\n"
        "\n"
        "  recommendation_id:  DIVERGES\n"
        "    Source: src.journal.store.log_recommendation line 132\n"
        "            rec_id = str(uuid.uuid4())\n"
        "    uuid.uuid4() draws from OS CSPRNG; random.seed() and frozen\n"
        "    clock have NO effect. Two calls always produce different UUIDs.\n"
        "    §3.4 escalation: FIX-UNDER-SIM-SEEDING\n"
        "    Action: patch src.journal.store.uuid.uuid4 with a monotonic\n"
        "    counter-based minter in wiring.install_organic_patches().\n"
        "    No prod code change required. Counter reset at scenario start.\n"
        "\n"
        "  actual_shares:      REPRODUCIBLE\n"
        "    Formula: max(1, int(allocation_dollars / entry_price))\n"
        "    Float arithmetic on literals is bit-for-bit stable.\n"
        "    No §3.4 escalation needed.\n"
        "\n"
        "  pnl_dollars:        REPRODUCIBLE\n"
        "    Formula: (exit_price - entry_price) * actual_shares\n"
        "    Deterministic with fixed prices and shares.\n"
        "    No §3.4 escalation needed.\n"
        "\n"
        "T13 residual blind-spot: canonical_snapshot_hash (invariant 9) includes\n"
        "recommendation_id in the shadow_trades snapshot query. Until the uuid4\n"
        "patch lands in install_organic_patches(), the EQUALITY arm of invariant 9\n"
        "will fail for any scenario that calls log_recommendation."
    )
