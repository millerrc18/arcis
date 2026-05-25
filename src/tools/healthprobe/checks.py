"""HealthProbe checks — 4 probe functions for service state, port, heartbeat, error-count.

Called by: src.tools.healthprobe.core
Calls: src.tools.processmanager.nssm.nssm_status, src.tools.logtail.tail, socket
Owns tables: none
Config keys: none (paths/ports injected by caller)
Tests: tests/tools/test_healthprobe_integration.py
"""

from __future__ import annotations

import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from src.tools._subprocess import NssmMissingError
from src.tools.processmanager.nssm import NssmCommandFailedError, ServiceState, nssm_status


def _check_service_state(service: str) -> ServiceState:
    """Query NSSM for the current service state.

    Per spec §3.2: per-service failures absorbed into UNKNOWN verdict, never raised.
    HealthProbe always returns a result — it never raises just because a service is down.
    """
    try:
        return nssm_status(service)
    except (NssmMissingError, NssmCommandFailedError, Exception):
        return ServiceState.UNKNOWN


def _check_port(port: int, host: str = "127.0.0.1") -> bool:
    """Non-binding socket probe: True if port is accepting connections."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            result = s.connect_ex((host, port))
            return result == 0
    except OSError:
        return False


def _check_heartbeat(
    path: Path,
    max_age_s: int,
    *,
    mode: Literal["iso", "mtime"] = "iso",
) -> tuple[bool, str | None]:
    """Check whether a heartbeat source is fresh.

    Args:
        path:      Path to the heartbeat file.
        max_age_s: Maximum acceptable age in seconds.
        mode:      'iso' reads the file content as an ISO timestamp (watch_loop).
                   'mtime' uses the file's last-modified time (dashboard/ollama logs).

    Returns:
        (fresh, reason) where reason is None on success, or one of:
          'file_missing' / 'parse_error' / 'age={N}s>threshold={M}s'
    """
    if not path.exists():
        return False, "file_missing"

    if not path.is_file():
        return False, "not_a_file"

    try:
        if mode == "iso":
            content = path.read_text(encoding="utf-8").strip()
            last = datetime.fromisoformat(content)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
        else:
            last = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except Exception:
        return False, "parse_error"

    now = datetime.now(timezone.utc)
    age_s = int((now - last).total_seconds())
    if age_s > max_age_s:
        return False, f"age={age_s}s>threshold={max_age_s}s"

    return True, None


def _check_recent_errors(log_path: Path, window_minutes: int = 15) -> int:
    """Count log entries within the last window_minutes that are ERROR or CRITICAL.

    Uses src.tools.logtail.tail (FB3 mandatory — Tier-1 v0.36.62 hard dependency).
    Suppresses tail-failure as 0 (don't crash the probe).
    Parses leading 'YYYY-MM-DD HH:MM:SS.ffffff' from each joined entry.
    """
    from src.tools.logtail import tail

    try:
        entries = tail(lines=500, log_path=log_path, level="ERROR")
    except Exception:
        return 0

    if not entries:
        return 0

    now = datetime.now(timezone.utc)
    cutoff = now.timestamp() - (window_minutes * 60)
    count = 0

    for entry in entries:
        # Extract leading timestamp from first line of each entry
        first_line = entry.split("\n")[0] if "\n" in entry else entry
        # Format: 'YYYY-MM-DD HH:MM:SS.ffffff ...' OR 'YYYY-MM-DD HH:MM:SS,...'
        ts_str = first_line[:26]
        # Normalize comma to period for microseconds (Python logging uses comma)
        ts_str = ts_str.replace(",", ".")
        try:
            ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S.%f")
            ts = ts.replace(tzinfo=timezone.utc)
            if ts.timestamp() >= cutoff:
                count += 1
        except (ValueError, IndexError):
            continue

    return count
