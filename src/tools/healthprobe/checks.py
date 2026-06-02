"""HealthProbe checks — 4 probe functions for service state, port, heartbeat, error-count.

Called by: src.tools.healthprobe.core
Calls: src.tools.processmanager.nssm.nssm_status, src.tools.logtail.tail, socket
Owns tables: none
Config keys: none (paths/ports injected by caller)
Tests: tests/tools/test_healthprobe_integration.py
"""

from __future__ import annotations

import re
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

# arcis.log timestamps are emitted by Python logging in the host's local wall
# clock, which on this deployment is America/New_York (ET). They are naive
# (no offset). Interpret them in ET before any window comparison.
_LOG_TZ = ZoneInfo("America/New_York")
# Leading 'YYYY-MM-DD HH:MM:SS' of a log line (seconds precision; the comma- or
# period-separated millis/micros fragment is intentionally ignored so the parse
# is robust to both Python-logging comma-3-digit and ISO period-6-digit formats).
_LOG_TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")

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
        # Extract the leading 'YYYY-MM-DD HH:MM:SS' (seconds precision is plenty
        # for a minutes-wide window). A fixed-width slice is brittle: real
        # arcis.log uses Python logging's comma + 3-digit millis ('...03,072' =
        # 23 chars), so the prior 26-char slice grabbed trailing ' [' and
        # strptime raised on EVERY real line -> recent_error_count stuck at 0
        # (the second half of the live-monitor bug 2026-06-02). Match to seconds
        # via regex and ignore the comma/period millis fragment entirely.
        first_line = entry.split("\n")[0] if "\n" in entry else entry
        m = _LOG_TS_RE.match(first_line)
        if not m:
            continue
        try:
            ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        # Log timestamps are ET wall-clock (naive). Tag them ET — NOT UTC — or
        # during EDT every entry lands ~4h outside the window and the probe
        # under-reports recent errors as 0 (live-monitor bug 2026-06-02).
        ts = ts.replace(tzinfo=_LOG_TZ)
        if ts.timestamp() >= cutoff:
            count += 1

    return count
