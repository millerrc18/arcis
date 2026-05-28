"""Email-digest hold-over exit-criteria check (#115 — Phase 5 PR-C T16 split).

The DA-MAJ-7 / DA-MAJ-11 hold-over tripwire logic that gates PR 2 (old
digest_builder retirement): handover_check + its 6 private tripwire helpers
(4 DB-backed tripwires, the shadow-files-present check, the row-ID inclusion
check, and the dispatch counter).

Called by: src.notifications.email_digest (re-export), src.cli.commands_ops
Calls:     src.config.load_config, src.utils.db.connect_db
Owns tables: none (reads notifications_digest_queue + notifications_sent via
             a self-opened connection; reads shadow files from disk)
Config keys: email.dual_write_hold_over.{mode,shadow_output_dir}
Tests:     tests/notifications/test_email_digest_handover.py,
           tests/notifications/test_email_digest_holiday.py

Architecture (DD-29): extracted verbatim from email_digest.py; handover_check
is re-exported by the orchestrator so `email_digest.handover_check` and the
CLI's decorated public-API import are byte-for-byte unchanged.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.config import load_config


def _open_handover_conn(db_path: str | None):
    """Open a sqlite connection for handover_check. Overridable in tests."""
    from src.utils.db import connect_db
    from src.config import DB_PATH
    return connect_db(db_path or DB_PATH)


def handover_check(
    *,
    window_days: int = 7,
    compare_window: str | None = None,
    db_path: str | None = None,
) -> dict:
    """DA-MAJ-7 hold-over exit-criteria check (Task 17 — real implementation).

    Returns: {
        'status': 'PASS' | 'FAIL',
        'tripwires': {
            'abandoned_rows_under_threshold': bool,
            'preopen_flushed_5_weekdays': bool,
            'postclose_flushed_5_weekdays': bool,
            'weekly_flushed_within_window': bool,
            'shadow_files_present': bool,           # only meaningful in shadow mode
            'row_id_inclusion_check': bool | None,  # only when compare_window set
        },
        'details': { ... per-tripwire detail strings ... },
    }

    PR 2 merge is gated on status='PASS'.
    """
    cfg = load_config() or {}
    holdover = (cfg.get("email", {}) or {}).get("dual_write_hold_over", {}) or {}
    mode = holdover.get("mode", "shadow")
    shadow_dir = holdover.get("shadow_output_dir", "tmp/digest-shadow")

    tripwires: dict = {}
    details: dict = {}

    conn = _open_handover_conn(db_path)
    try:
        _handover_db_tripwires(
            conn, window_days=window_days,
            tripwires=tripwires, details=details,
        )
    finally:
        try:
            conn.close()
        except Exception:
            pass

    _handover_shadow_tripwire(
        mode, shadow_dir, tripwires=tripwires, details=details,
    )
    _handover_inclusion_tripwire(
        compare_window, shadow_dir, tripwires=tripwires, details=details,
    )

    # Status: PASS iff every non-None tripwire is True.
    status = "PASS"
    for k, v in tripwires.items():
        if v is None:
            continue
        if v is False:
            status = "FAIL"
            break

    return {"status": status, "tripwires": tripwires, "details": details}


def _handover_db_tripwires(conn, *, window_days, tripwires, details) -> None:
    """Populate the 4 DB-backed tripwires (abandoned + 3 dispatch counts)."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=window_days)
    ).isoformat()
    seven_day_cutoff = (
        datetime.now(timezone.utc) - timedelta(days=7)
    ).isoformat()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM notifications_digest_queue "
            "WHERE flush_status='abandoned' AND created_at >= ?",
            (cutoff,),
        ).fetchone()
        abandoned_count = int(row["c"] if row and "c" in row.keys() else 0)
    except Exception:
        abandoned_count = 0
    tripwires["abandoned_rows_under_threshold"] = abandoned_count < 10
    details["abandoned_rows_under_threshold"] = (
        f"{abandoned_count} abandoned rows in past {window_days}d "
        f"(threshold: < 10)"
    )
    for label, pattern, threshold in (
        ("preopen_flushed_5_weekdays", "%preopen%", 5),
        ("postclose_flushed_5_weekdays", "%postclose%", 5),
        ("weekly_flushed_within_window", "%weekly%", 1),
    ):
        n = _count_dispatches(conn, like=pattern, since=seven_day_cutoff)
        tripwires[label] = n >= threshold
        details[label] = (
            f"{n} {pattern.strip('%')} email dispatches in past 7d "
            f"(threshold: >= {threshold})"
        )


def _handover_shadow_tripwire(mode, shadow_dir, *, tripwires, details) -> None:
    """Populate the shadow_files_present tripwire (only meaningful in shadow)."""
    if mode == "shadow":
        try:
            shadow_path = Path(shadow_dir)
            has_files = (
                shadow_path.exists() and any(shadow_path.iterdir())
            )
        except Exception:
            has_files = False
        tripwires["shadow_files_present"] = bool(has_files)
        details["shadow_files_present"] = (
            f"shadow_output_dir={shadow_dir!r} contains files: {has_files}"
        )
    else:
        tripwires["shadow_files_present"] = True  # N/A → not a gate
        details["shadow_files_present"] = (
            f"mode={mode!r} — shadow_files_present check skipped (N/A)"
        )


def _handover_inclusion_tripwire(
    compare_window, shadow_dir, *, tripwires, details,
) -> None:
    """Populate the DA-MAJ-11 row-ID inclusion tripwire if requested."""
    if compare_window:
        ok, detail = _row_id_inclusion_check(shadow_dir)
        tripwires["row_id_inclusion_check"] = ok
        details["row_id_inclusion_check"] = detail
    else:
        tripwires["row_id_inclusion_check"] = None
        details["row_id_inclusion_check"] = "skipped (compare_window not supplied)"


def _count_dispatches(conn, *, like: str, since: str) -> int:
    """Count notifications_sent rows matching event_type LIKE ? AND
    channel='email' AND status='ok' AND sent_at >= since."""
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM notifications_sent "
            "WHERE channel='email' AND status='ok' "
            "  AND event_type LIKE ? AND sent_at >= ?",
            (like, since),
        ).fetchone()
        return int(row["c"] if row and "c" in row.keys() else 0)
    except Exception:
        return 0


def _row_id_inclusion_check(shadow_dir: str) -> tuple[bool, str]:
    """DA-MAJ-11: every shadow_trade.id mentioned in the OLD eod shadow
    files MUST also appear in either a NEW postclose OR a NEW preopen
    shadow file in the same window.

    Returns (ok: bool, detail: str).
    """
    try:
        path = Path(shadow_dir)
        if not path.exists():
            return False, f"shadow_output_dir not found: {shadow_dir}"

        id_re = re.compile(r"shadow_trade\.id\s*=\s*(\d+)")
        old_ids: set[str] = set()
        new_ids: set[str] = set()
        for f in path.iterdir():
            if not f.is_file():
                continue
            try:
                txt = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            ids = set(id_re.findall(txt))
            name = f.name.lower()
            if name.startswith("eod-"):
                old_ids |= ids
            elif name.startswith("postclose-") or name.startswith("preopen-"):
                new_ids |= ids

        missing = old_ids - new_ids
        if missing:
            return False, (
                f"row IDs in old eod missing from new postclose/preopen: "
                f"{sorted(missing)}"
            )
        return True, (
            f"all {len(old_ids)} old-eod shadow_trade.id values present in "
            f"new postclose/preopen shadow files"
        )
    except Exception as e:
        return False, f"row_id_inclusion_check error: {e}"
