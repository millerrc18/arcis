"""Detect manual-intervention drift between broker state and local DB intent.

Emits DriftFinding objects when the operator closes a paper position directly
in the Alpaca dashboard but the local shadow_trade row still says "active".

Called by: src/scheduler/watch.py (tick_drift_detector — Wave C T4, 30min cadence)
Calls: none (returns findings; watch.py calls safe_send for notification)
Owns tables: platform_events (INSERT only — TableDef owned by T2 / src/schema/registry.py)
Config keys: none
Tests: tests/monitoring/test_manual_intervention_drift.py
           tests/monitoring/test_drift_detector_no_recursion.py

Decision 23: lives in src/monitoring/, NOT src/diagnostics/.
Decision 21: state file shape is precursor to T12 notification_retry_state.json.

SCOPE FENCE: this module MUST NOT call safe_send. The watch-loop caller is
responsible for notification dispatch. See test_drift_detector_no_recursion.py.
"""

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Union

from src.monitoring.errors import MonitoringDataError

logger = logging.getLogger(__name__)

_DEDUP_WINDOW_HOURS = 24


@dataclass
class BrokerPosition:
    """Minimal broker-side position view consumed by the drift detector."""
    ticker: str
    status: str  # "open" | "closed" | "partial"


@dataclass
class DBPosition:
    """Minimal DB-side shadow_trade view consumed by the drift detector."""
    ticker: str
    status: str  # "active" | "closed" | "pending" etc.


@dataclass
class DriftFinding:
    """A single detected divergence between broker state and DB intent."""
    ticker: str
    expected_state: str
    actual_state: str
    divergence_age_minutes: float

    def as_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "expected_state": self.expected_state,
            "actual_state": self.actual_state,
            "divergence_age_minutes": round(self.divergence_age_minutes, 1),
        }


def _atomic_write_json(path: Path, data: dict) -> None:
    """Write JSON atomically via a temp file in the same directory."""
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def _load_state(state_path: Path) -> dict:
    """Load state file; return empty dict if absent or corrupt."""
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _is_divergence(broker_pos: BrokerPosition, db_pos: DBPosition) -> bool:
    """Return True when broker says position is closed but DB says active."""
    return broker_pos.status in ("closed", "partial") and db_pos.status in ("active", "open")


def _parse_utc(iso: str, fallback: datetime) -> datetime:
    """Parse ISO timestamp; attach UTC if naive; return fallback on error."""
    try:
        dt = datetime.fromisoformat(iso)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return fallback


def _should_alert(entry: dict, now_utc: datetime, threshold_minutes: int) -> bool:
    """Return True if the divergence is old enough and not within the dedup window."""
    first_seen = _parse_utc(entry.get("first_seen_iso", ""), now_utc)
    age_minutes = (now_utc - first_seen).total_seconds() / 60.0
    if age_minutes < threshold_minutes:
        return False
    last_alerted_iso = entry.get("last_alerted_iso")
    if not last_alerted_iso:
        return True
    last_alerted = _parse_utc(last_alerted_iso, now_utc - timedelta(hours=_DEDUP_WINDOW_HOURS + 1))
    return (now_utc - last_alerted) >= timedelta(hours=_DEDUP_WINDOW_HOURS)


def _write_platform_events_row(conn: sqlite3.Connection, finding: DriftFinding) -> None:
    """INSERT a forensic-trail row into platform_events for this finding."""
    payload = json.dumps(finding.as_dict())
    conn.execute(
        "INSERT INTO platform_events (event_type, severity, payload_json, source, created_at) "
        "VALUES (?, 'high', ?, 'drift_detector', CURRENT_TIMESTAMP)",
        ("drift_detected", payload),
    )
    conn.commit()


def _process_ticker(
    ticker: str,
    broker_pos: BrokerPosition,
    db_pos: DBPosition,
    state: dict,
    now_utc: datetime,
    threshold_minutes: int,
    conn: sqlite3.Connection,
) -> "DriftFinding | None":
    """Evaluate one ticker; update state in-place; return finding or None."""
    if not _is_divergence(broker_pos, db_pos):
        state.pop(ticker, None)
        return None
    entry = state.get(ticker)
    if entry is None:
        state[ticker] = {
            "first_seen_iso": now_utc.isoformat(),
            "last_alerted_iso": None,
            "expected_state": broker_pos.status,
            "actual_state": db_pos.status,
        }
        return None
    if not _should_alert(entry, now_utc, threshold_minutes):
        return None
    first_seen = _parse_utc(entry["first_seen_iso"], now_utc)
    age_minutes = (now_utc - first_seen).total_seconds() / 60.0
    finding = DriftFinding(
        ticker=ticker,
        expected_state=broker_pos.status,
        actual_state=db_pos.status,
        divergence_age_minutes=age_minutes,
    )
    entry["last_alerted_iso"] = now_utc.isoformat()
    entry["expected_state"] = broker_pos.status
    entry["actual_state"] = db_pos.status
    try:
        _write_platform_events_row(conn, finding)
    except sqlite3.Error as exc:
        logger.error("[DRIFT] Failed to write platform_events row for %s: %s", ticker, exc)
    return finding


def detect_drift(
    broker_positions: Union[dict[str, BrokerPosition], None],
    db_positions: dict[str, DBPosition],
    threshold_minutes: int = 30,
    *,
    state_path: Path,
    conn: sqlite3.Connection,
) -> list[DriftFinding]:
    """Detect divergences between broker state and local DB intent.

    Returns findings. Caller (watch.py tick) emits via safe_send — this
    function MUST NOT call safe_send (see test_drift_detector_no_recursion.py).

    broker_positions=None signals a broker outage; returns [] (no false alerts).
    """
    if broker_positions is None:
        logger.warning("[DRIFT] broker_positions=None — outage guard, skipping drift check")
        return []
    now_utc = datetime.now(timezone.utc)
    state = _load_state(state_path)
    findings: list[DriftFinding] = []
    seen_tickers: set[str] = set()
    for ticker, broker_pos in broker_positions.items():
        if ticker not in db_positions:
            continue
        seen_tickers.add(ticker)
        result = _process_ticker(
            ticker, broker_pos, db_positions[ticker], state, now_utc, threshold_minutes, conn
        )
        if result is not None:
            findings.append(result)
    stale_keys = [k for k in list(state) if k not in seen_tickers and k not in db_positions]
    for k in stale_keys:
        state.pop(k, None)
    try:
        _atomic_write_json(state_path, state)
    except OSError as exc:
        logger.error("[DRIFT] Failed to persist state file %s: %s", state_path, exc)
    return findings
