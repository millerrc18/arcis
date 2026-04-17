"""Claude Code status line for Halcyon Lab.

When to run:
    Automatically by Claude Code as a status bar indicator, or manually
    to get a quick system health snapshot in one line.

What it reads:
    - data/watch.lock (PID lockfile for watch loop)
    - data/watchdog.txt (heartbeat timestamp from watch loop)
    - data/trading_halted (halt flag file)
    - ai_research_desk.sqlite3 (shadow_trades counts)
    - logs/halcyon.log (last log timestamp)

What it writes:
    - Nothing — stdout single-line health summary

Prerequisites:
    - No external dependencies; degrades gracefully if files are missing

Outputs a single line with system health indicators:
  Watch loop | Heartbeat | Halt status | Shadow positions | Live positions | DB size | Last log
"""

import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "ai_research_desk.sqlite3"
WATCH_LOCK = ROOT / "data" / "watch.lock"
WATCHDOG = ROOT / "data" / "watchdog.txt"
HALT_FILE = ROOT / "data" / "trading_halted"
LOG_FILE = ROOT / "logs" / "arcis.log"


def _heartbeat_fresh(max_age_s: int = 300) -> bool:
    """True if watchdog.txt was touched within max_age_s. The heartbeat
    is the watch loop's authoritative liveness signal.
    """
    if not WATCHDOG.exists():
        return False
    try:
        last = datetime.fromisoformat(WATCHDOG.read_text().strip())
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - last).total_seconds() < max_age_s
    except Exception:
        return False


def watch_status():
    """Check if the watch loop is running via PID lockfile + heartbeat.

    Tries OpenProcess first (fast path, works for same-session processes).
    Falls back to heartbeat freshness for service-owned PIDs (Session 0)
    where user-session OpenProcess is denied by Windows session isolation.
    """
    if not WATCH_LOCK.exists():
        return "Watch:OFF"
    try:
        pid = int(WATCH_LOCK.read_text().strip())
        if sys.platform == "win32":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if handle:
                kernel32.CloseHandle(handle)
                return "Watch:ON"
        else:
            os.kill(pid, 0)
            return "Watch:ON"
    except (ValueError, OSError, PermissionError):
        pass
    # Cross-session fallback: heartbeat freshness (NSSM service runs in Session 0)
    if _heartbeat_fresh():
        return "Watch:ON"
    return "Watch:STALE-LOCK"


def heartbeat():
    if not WATCHDOG.exists():
        return "Beat:none"
    try:
        text = WATCHDOG.read_text().strip()
        last = datetime.fromisoformat(text)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        ago_min = int((now - last).total_seconds() / 60)
        if ago_min > 60:
            return f"Beat:{ago_min}m STALE"
        elif ago_min > 5:
            return f"Beat:{ago_min}m?"
        else:
            return f"Beat:{ago_min}m"
    except Exception:
        return "Beat:err"


def halt_status():
    return "HALTED" if HALT_FILE.exists() else "Trading:active"


def position_counts():
    if not DB.exists():
        return "Shadow:? | Live:?"
    try:
        conn = sqlite3.connect(str(DB), timeout=2)
        cur = conn.cursor()
        cur.execute(
            "SELECT source, status, COUNT(*) FROM shadow_trades "
            "WHERE status IN ('open','closed') GROUP BY source, status"
        )
        d = {}
        for src, st, cnt in cur.fetchall():
            d[(src, st)] = cnt
        conn.close()
        so = d.get(("paper", "open"), 0)
        sc = d.get(("paper", "closed"), 0)
        lo = d.get(("live", "open"), 0)
        lc = d.get(("live", "closed"), 0)
        return f"Shadow:{so}o/{sc}c | Live:{lo}o/{lc}c"
    except Exception:
        return "Shadow:? | Live:?"


def db_size():
    if not DB.exists():
        return "DB:?"
    size = DB.stat().st_size
    if size >= 1_073_741_824:
        return f"DB:{size / 1_073_741_824:.1f}G"
    elif size >= 1_048_576:
        return f"DB:{size / 1_048_576:.0f}M"
    else:
        return f"DB:{size / 1024:.0f}K"


def last_log():
    """Get timestamp of the last log entry for staleness detection."""
    if not LOG_FILE.exists():
        return None
    try:
        # Seek to last 512 bytes instead of reading the entire log file.
        # This avoids loading multi-MB log files into memory.
        with open(LOG_FILE, "rb") as f:
            f.seek(0, 2)
            end = f.tell()
            if end == 0:
                return None
            pos = max(0, end - 512)
            f.seek(pos)
            lines = f.read().decode("utf-8", errors="replace").splitlines()
            if lines:
                last = lines[-1]
                # Extract timestamp: "2026-04-01 08:31:04,429 ..."
                if len(last) >= 16 and last[4] == "-":
                    return f"Log:{last[:16]}"
    except Exception:
        pass
    return None


def main():
    parts = [
        watch_status(),
        heartbeat(),
        halt_status(),
        position_counts(),
        db_size(),
    ]
    log = last_log()
    if log:
        parts.append(log)
    print(" | ".join(parts))


if __name__ == "__main__":
    main()
