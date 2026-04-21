#!/usr/bin/env python
"""One-shot DB reconciliation for 2026-04-20 broken-state trades.

Context: 2026-04-20 post-market audit surfaced 19 broken shadow_trades
rows + 1 stale model_versions row. Operator closes the 12 Alpaca short
positions via the UI; after fills confirm, this script updates the DB to
match broker reality. See docs/audit/live_state_analysis_2026-04-20.md
for the per-row rationale.

Runs AFTER operator confirms Alpaca shows zero short positions for the
12 target tickers. Pre-flight check aborts if any ticker still shows a
short position in Alpaca.

Idempotent by design: re-runs skip rows already in target terminal state.

Exit codes:
  0 -- success (or no-op on idempotent re-run)
  2 -- kill-switch file missing
  3 -- Alpaca still has short position(s), or Alpaca API failure
  4 -- post-update verification failed (transaction rolled back)

Called by: operator (manual one-shot after Alpaca UI close-all)
Calls: src.shadow_trading.alpaca_adapter.get_all_positions (read-only),
       sqlite3 (direct, with busy_timeout=30s)
Owns tables: none (writes to shadow_trades + model_versions via UPDATE)
Config keys: none
Tests: tests/scripts/test_reconcile_2026_04_20.py
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.config import DB_PATH
from src.shadow_trading.alpaca_adapter import get_all_positions

# 9 CLOSE_AT_OPEN (incl. GS) + 3 NEEDS_OPERATOR_JUDGMENT = 12 closes total.
# Target: status='closed', exit_reason='manual_reconcile'.
CLOSE_TRADES: list[tuple[str, str, str]] = [
    ("7084665a-bf4f-40d5-aff5-b5cd5ebdd3ee", "CVX",   "Short-overshoot reconciled to flat"),
    ("217eddba-606e-44ea-ad88-78d90c2b0419", "CAT",   "Short-overshoot reconciled to flat"),
    ("07046983-14f1-48ca-bf60-e0c1d8f00d6c", "FDX",   "Short-overshoot reconciled to flat"),
    ("b54f0a67-a4d6-4b34-b9b3-ef4a80c1a6be", "MO",    "Short-overshoot reconciled to flat"),
    ("5bd67cab-092a-478a-84ba-8e3938e7de98", "BK",    "Short-overshoot reconciled to flat"),
    ("a685fc8a-d173-42b3-ab79-ddb5c47035ca", "NEE",   "Short-overshoot reconciled to flat"),
    ("7e71d087-03d4-4dee-bde1-554ceebedabc", "INTC",  "Short-overshoot reconciled to flat"),
    ("3d8251d2-174b-4115-b4d9-bd2b49231a3c", "GM",    "Short-overshoot reconciled to flat"),
    ("d42a5afc-7e2b-4ff3-bba0-6eaf23f61a49", "GS",    "Short-overshoot reconciled to flat"),
    ("3dcf9f7e-2195-4975-b01b-c2387f74e283", "GOOGL", "4x overshoot; single market close at open"),
    ("f01dc590-f4f1-4049-ac73-6572da43b735", "NVDA",  "5x overshoot; split close 100/75/70 at open"),
    ("f00641fe-77b3-4da3-a78d-83d8cef19bd9", "TGT",   "Broker tag was 'ib' but position was on Alpaca; closed on Alpaca; tag corrected this update"),
]

# 4 exit_failed + 3 open-row phantoms = 7 orphans total.
# Target: status='exit_abandoned', exit_reason='phantom_row_cleanup'.
ORPHAN_TRADES: list[tuple[str, str, str]] = [
    ("1630b6c5-d7df-44f6-aca6-d0c4826ca697", "AAPL", "exit_failed 24d with stop=0/target=0; backfill-default path never fired (see #581)"),
    ("bb10c4b7-1952-40fd-9a3a-c5db9b96c018", "WMT",  "Live-era ghost (2026-04-01); current Alpaca +92 belongs to 2026-04-13 open row"),
    ("9ad299c0-cf79-45f1-854a-3aa7b6ee2925", "CAT",  "Live-era ghost (2026-04-01); Alpaca -9 belongs to needs_manual_review row"),
    ("ce1322fd-3035-4e2d-9c08-10ad3755e00b", "CVX",  "Live-era ghost (2026-04-01); Alpaca -38 belongs to needs_manual_review row"),
    ("09b629e3-0bf6-4ba7-8293-73f4f3f90265", "SBUX", "Full phantom; no Alpaca position ever existed for this row"),
    ("748a97f1-c0e9-462c-9ce0-41deaefa00dc", "CAT",  "Phantom open row (2026-04-17); no alpaca_order_id; -9 short belongs to older needs_manual_review row"),
    ("730a113b-eb9b-4040-a320-6aaebacb3f2a", "TGT",  "IB-tagged phantom (2026-04-13); IB dormant; Alpaca -161 belongs to needs_manual_review row"),
]

# TGT #12 above also needs its broker tag corrected from 'ib' to 'alpaca'
# (position was on Alpaca despite the mistagging).
TGT_BROKER_CORRECT_ID = "f00641fe-77b3-4da3-a78d-83d8cef19bd9"

# Model registry: arcis:v1.0.0 was marked rolled_back, but Ollama + config
# agree it is the operational model. Re-activate. Deeper investigation of
# the original rollback tracked in #582.
MODEL_NAME = "arcis:v1.0.0"
MODEL_NOTES = (
    "Re-activated 2026-04-20 after three-way reconciliation (Ollama + "
    "config + DB) found Ollama and config still operational on this "
    "model; rollback was not operationally executed. Archaeology issue "
    "#582 tracks root cause of the original rollback record. See "
    "docs/audit/live_state_analysis_2026-04-20.md."
)

# Tickers whose Alpaca short position must be flat before this script runs.
SHORT_CHECK_TICKERS: tuple[str, ...] = (
    "CVX", "CAT", "FDX", "MO", "GOOGL", "NVDA", "TGT",
    "BK", "NEE", "INTC", "GM", "GS",
)

CLOSE_STATUS = "closed"
CLOSE_REASON_CODE = "manual_reconcile"
ORPHAN_STATUS = "exit_abandoned"
ORPHAN_REASON_CODE = "phantom_row_cleanup"


def reconcile(
    db_path: str = DB_PATH,
    kill_switch_path: str | Path = Path("data/trading_halted"),
    audit_log_path: str | Path = Path("docs/audit/reconcile_2026_04_20_execution.log"),
    positions_fn=None,
) -> int:
    """Run the reconciliation. Returns exit code (0=success, 2/3/4=abort).

    Parameters are injectable for tests; defaults are the production paths.
    """
    kill_switch_path = Path(kill_switch_path)
    audit_log_path = Path(audit_log_path)
    if positions_fn is None:
        positions_fn = get_all_positions

    log_lines: list[str] = []

    def log(msg: str) -> None:
        stamp = datetime.now(timezone.utc).isoformat()
        line = f"{stamp} {msg}"
        print(line)
        log_lines.append(line)

    log("[START] Reconciliation for 2026-04-20 broken-state trades")

    # Pre-flight 1: kill-switch
    if not kill_switch_path.exists():
        log(f"[ABORT] kill-switch file missing: {kill_switch_path}")
        _flush_log(audit_log_path, log_lines)
        return 2

    # Pre-flight 2: Alpaca shows zero shorts for target tickers
    try:
        positions = positions_fn()
    except Exception as e:
        log(f"[ABORT] Alpaca positions fetch failed: {type(e).__name__}: {e}")
        _flush_log(audit_log_path, log_lines)
        return 3
    short_offenders = [
        p for p in positions
        if p.get("symbol") in SHORT_CHECK_TICKERS and float(p.get("qty", 0)) < 0
    ]
    if short_offenders:
        for p in short_offenders:
            log(f"[ABORT] {p.get('symbol')} still short qty={p.get('qty')} on Alpaca")
        log("Close via Alpaca UI before retrying.")
        _flush_log(audit_log_path, log_lines)
        return 3
    log(f"[PREFLIGHT] OK -- zero shorts for {list(SHORT_CHECK_TICKERS)}")

    # Main transaction
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        with sqlite3.connect(db_path, timeout=30) as conn:
            cur = conn.cursor()
            cur.execute("BEGIN IMMEDIATE")

            updates_close = 0
            updates_orphan = 0
            updates_broker = 0

            for trade_id, ticker, detail in CLOSE_TRADES:
                row = cur.execute(
                    "SELECT status, exit_reason FROM shadow_trades WHERE trade_id=?",
                    (trade_id,),
                ).fetchone()
                if row is None:
                    log(f"[SKIP] {ticker} {trade_id}: row not found")
                    continue
                cur_status, cur_reason = row
                if cur_status == CLOSE_STATUS and cur_reason == CLOSE_REASON_CODE:
                    log(f"[SKIP] {ticker} {trade_id}: already resolved")
                    continue
                cur.execute(
                    "UPDATE shadow_trades "
                    "SET status=?, exit_reason=?, updated_at=? WHERE trade_id=?",
                    (CLOSE_STATUS, CLOSE_REASON_CODE, now_iso, trade_id),
                )
                updates_close += 1
                log(
                    f"[CLOSE] {ticker} {trade_id}: "
                    f"{cur_status}/{cur_reason or '(none)'} -> "
                    f"{CLOSE_STATUS}/{CLOSE_REASON_CODE} ; {detail}"
                )

            for trade_id, ticker, detail in ORPHAN_TRADES:
                row = cur.execute(
                    "SELECT status, exit_reason FROM shadow_trades WHERE trade_id=?",
                    (trade_id,),
                ).fetchone()
                if row is None:
                    log(f"[SKIP] {ticker} {trade_id}: row not found")
                    continue
                cur_status, cur_reason = row
                if cur_status == ORPHAN_STATUS and cur_reason == ORPHAN_REASON_CODE:
                    log(f"[SKIP] {ticker} {trade_id}: already resolved")
                    continue
                cur.execute(
                    "UPDATE shadow_trades "
                    "SET status=?, exit_reason=?, updated_at=? WHERE trade_id=?",
                    (ORPHAN_STATUS, ORPHAN_REASON_CODE, now_iso, trade_id),
                )
                updates_orphan += 1
                log(
                    f"[ORPHAN] {ticker} {trade_id}: "
                    f"{cur_status}/{cur_reason or '(none)'} -> "
                    f"{ORPHAN_STATUS}/{ORPHAN_REASON_CODE} ; {detail}"
                )

            # TGT broker-tag correction (idempotent via WHERE clause)
            cur.execute(
                "UPDATE shadow_trades SET broker='alpaca' "
                "WHERE trade_id=? AND broker='ib'",
                (TGT_BROKER_CORRECT_ID,),
            )
            if cur.rowcount == 1:
                updates_broker = 1
                log(f"[BROKER] TGT {TGT_BROKER_CORRECT_ID}: broker ib -> alpaca")
            else:
                log("[SKIP] TGT broker tag: already alpaca (or row missing)")

            # Model registry
            cur.execute(
                "UPDATE model_versions SET status='active', notes=? "
                "WHERE version_name=? AND status != 'active'",
                (MODEL_NOTES, MODEL_NAME),
            )
            if cur.rowcount == 1:
                log(f"[MODEL] {MODEL_NAME}: status -> active")
            else:
                log(f"[SKIP] model_versions: {MODEL_NAME} already active or not found")

            # Post-update verification
            close_ids = [t[0] for t in CLOSE_TRADES]
            orphan_ids = [t[0] for t in ORPHAN_TRADES]
            ph_close = ",".join("?" * len(close_ids))
            ph_orphan = ",".join("?" * len(orphan_ids))
            actual_close = cur.execute(
                f"SELECT COUNT(*) FROM shadow_trades "
                f"WHERE trade_id IN ({ph_close}) AND status=? AND exit_reason=?",
                (*close_ids, CLOSE_STATUS, CLOSE_REASON_CODE),
            ).fetchone()[0]
            actual_orphan = cur.execute(
                f"SELECT COUNT(*) FROM shadow_trades "
                f"WHERE trade_id IN ({ph_orphan}) AND status=? AND exit_reason=?",
                (*orphan_ids, ORPHAN_STATUS, ORPHAN_REASON_CODE),
            ).fetchone()[0]
            actual_model = cur.execute(
                "SELECT COUNT(*) FROM model_versions "
                "WHERE version_name=? AND status='active'",
                (MODEL_NAME,),
            ).fetchone()[0]

            if (
                actual_close != len(CLOSE_TRADES)
                or actual_orphan != len(ORPHAN_TRADES)
                or actual_model != 1
            ):
                log(
                    f"[ABORT] Verification failed: "
                    f"close={actual_close}/{len(CLOSE_TRADES)} "
                    f"orphan={actual_orphan}/{len(ORPHAN_TRADES)} "
                    f"model={actual_model}/1 -- rolling back"
                )
                conn.rollback()
                _flush_log(audit_log_path, log_lines)
                return 4

            conn.commit()
            log(
                f"[SUCCESS] final-state: close={actual_close} "
                f"orphan={actual_orphan} model=1 broker_correction={updates_broker}"
            )
            log(
                f"[SUMMARY] this-run updates: close={updates_close} "
                f"orphan={updates_orphan} broker={updates_broker}"
            )
    except Exception as e:
        log(f"[ABORT] Unexpected error: {type(e).__name__}: {e}")
        _flush_log(audit_log_path, log_lines)
        raise

    _flush_log(audit_log_path, log_lines)
    return 0


def _flush_log(path: Path, lines: list[str]) -> None:
    """Append log lines to the audit log file (created if absent)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")


def main() -> None:
    sys.exit(reconcile())


if __name__ == "__main__":
    main()
