"""Independent watchdog: alert when the desk's PG or watch-loop heartbeat is down.

Standard module docstring (test_repo_structure).

WHY THIS EXISTS (2026-06-11 incident): prod Postgres (5433, the sole write
target) was down ~21h because Docker Desktop hadn't auto-started after a reboot,
and NOTHING alerted the operator — the watch loop was crash-looping and could not
send its own notification. The lesson: the thing that detects an outage must NOT
depend on the thing that is down. See memory reference_docker_pg_no_autostart.

This monitor is deliberately SELF-CONTAINED and dependency-minimal so it works
precisely when the desk is degraded:
  - heartbeat freshness  → reads data/watchdog.txt (a local file; no DB)
  - prod-PG reachability → a raw TCP socket connect to 127.0.0.1:5433 (no driver)
  - alert delivery       → Telegram HTTP (api.telegram.org; no PG, no watch loop)

It is meant to run on a short cron / Windows Task Scheduler cadence (~10 min),
INDEPENDENT of the watch loop's NSSM service. It is edge-triggered + de-duped:
it pages ONCE when the desk goes DOWN (after `--fail-threshold` consecutive bad
reads, to ride out transient restarts) and ONCE again when it RECOVERS — never a
page every run. State persists in data/heartbeat_monitor_state.json.

Usage:
    python scripts/heartbeat_monitor.py                 # one check (for cron)
    python scripts/heartbeat_monitor.py --dry-run       # check + print, no send
    python scripts/heartbeat_monitor.py --heartbeat-max-age 1800 --fail-threshold 2
"""
from __future__ import annotations

import argparse
import json
import logging
import socket
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("heartbeat_monitor")

ROOT = Path(__file__).resolve().parent.parent
PG_HOST = "127.0.0.1"
PG_PORT = 5433  # prod PG (docker halcyon-pg); see docker-compose.yml
DEFAULT_HEARTBEAT_MAX_AGE_S = 1800  # 30 min — well above normal LLM-scan staleness
DEFAULT_FAIL_THRESHOLD = 2  # consecutive bad reads before paging (anti-flap)


def _default_data_root() -> Path:
    """The repo `data/` dir — where the watch loop writes the heartbeat.

    The watch loop writes `Path("data/watchdog.txt")` RELATIVE to its repo cwd
    (src/scheduler/watch.py:1921), so the heartbeat lives at <repo>/data/ — NOT
    the runtime DB dir (ARCIS_DB_PATH parent, which is outside the repo by design,
    CLAUDE.md). ROOT is derived from this file, so this is correct regardless of
    the monitor's own cwd (it runs from Task Scheduler).
    """
    return ROOT / "data"


def heartbeat_age_seconds(watchdog_path: Path) -> float | None:
    """Age (s) of the watch-loop heartbeat from watchdog.txt, or None if absent
    / unparseable (treated as DOWN by the caller)."""
    if not watchdog_path.exists():
        return None
    try:
        last = datetime.fromisoformat(watchdog_path.read_text().strip())
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - last).total_seconds()
    except Exception:  # noqa: BLE001 — any parse failure is "no fresh heartbeat"
        return None


def pg_reachable(host: str = PG_HOST, port: int = PG_PORT, timeout: float = 3.0) -> bool:
    """True iff a TCP connection to the prod-PG port succeeds. Raw socket — no
    psycopg2 — so the check itself has zero DB-driver dependency."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def evaluate(watchdog_path: Path, heartbeat_max_age_s: int) -> dict:
    """Pure status assessment: {down: bool, reasons: [str], pg_ok, heartbeat_age}."""
    pg_ok = pg_reachable()
    age = heartbeat_age_seconds(watchdog_path)
    reasons = []
    if not pg_ok:
        reasons.append(f"prod PG {PG_HOST}:{PG_PORT} unreachable")
    if age is None:
        reasons.append("watch-loop heartbeat missing/unparseable")
    elif age > heartbeat_max_age_s:
        reasons.append(f"watch-loop heartbeat stale ({int(age)}s > {heartbeat_max_age_s}s)")
    return {"down": bool(reasons), "reasons": reasons, "pg_ok": pg_ok, "heartbeat_age": age}


def _load_state(state_path: Path) -> dict:
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — missing/corrupt state starts fresh
        return {"alerting": False, "consecutive_down": 0, "since": None}


def _save_state(state_path: Path, state: dict) -> None:
    try:
        state_path.write_text(json.dumps(state), encoding="utf-8")
    except OSError as exc:
        logger.warning("[heartbeat-monitor] could not persist state: %s", exc)


def _ensure_env() -> None:
    """Make `src.*` importable and load the repo .env, so the Telegram sender
    resolves even when the monitor is launched as a script from an arbitrary cwd
    (Task Scheduler runs from system32 with sys.path[0]=scripts/). Without the
    sys.path insert `from src.notifications...` fails (No module named 'src');
    without the .env load TELEGRAM_* has no token. Both would make the alert
    channel silently dead. Best-effort."""
    import sys
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except Exception:  # noqa: BLE001 — dotenv missing/unreadable: fall back to ambient env
        pass


def _send_alert(message: str) -> bool:
    """Deliver via Telegram (PG-independent). Imported lazily so the module
    imports cleanly even if notifications is unavailable, and so tests can patch."""
    _ensure_env()
    try:
        from src.notifications.telegram import send_telegram
        return bool(send_telegram(message))
    except Exception as exc:  # noqa: BLE001 — delivery failure must not crash the cron
        logger.error("[heartbeat-monitor] telegram delivery failed: %s", exc)
        return False


def run_once(
    *,
    heartbeat_max_age_s: int = DEFAULT_HEARTBEAT_MAX_AGE_S,
    fail_threshold: int = DEFAULT_FAIL_THRESHOLD,
    dry_run: bool = False,
    data_root: Path | None = None,
) -> dict:
    """One edge-triggered check. Returns the decision dict (for tests/cron logs)."""
    data_root = data_root or _default_data_root()
    watchdog_path = data_root / "watchdog.txt"
    state_path = data_root / "heartbeat_monitor_state.json"

    status = evaluate(watchdog_path, heartbeat_max_age_s)
    state = _load_state(state_path)
    now_iso = datetime.now(timezone.utc).isoformat()
    action = "none"

    if status["down"]:
        state["consecutive_down"] = int(state.get("consecutive_down", 0)) + 1
        if state["consecutive_down"] >= fail_threshold and not state.get("alerting"):
            reasons = "; ".join(status["reasons"])
            msg = (
                "\U0001F534 <b>ARCIS desk DOWN</b>\n"
                f"{reasons}\n"
                f"(heartbeat monitor, {state['consecutive_down']} consecutive bad checks)"
            )
            if not dry_run and _send_alert(msg):
                state["alerting"] = True
                state["since"] = now_iso
            action = "alert-down" if not dry_run else "alert-down(dry-run)"
    else:
        if state.get("alerting"):
            msg = "\U0001F7E2 <b>ARCIS desk RECOVERED</b>\nprod PG + heartbeat healthy again (heartbeat monitor)."
            if not dry_run:
                _send_alert(msg)
            action = "alert-recovered" if not dry_run else "alert-recovered(dry-run)"
        state["alerting"] = False
        state["consecutive_down"] = 0

    if not dry_run:
        _save_state(state_path, state)

    result = {**status, "action": action, "checked_at": now_iso}
    logger.info("[heartbeat-monitor] %s", json.dumps(result))
    return result


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    p = argparse.ArgumentParser(description="Independent PG/heartbeat down-alert watchdog.")
    p.add_argument("--heartbeat-max-age", type=int, default=DEFAULT_HEARTBEAT_MAX_AGE_S,
                   help="Heartbeat staleness threshold in seconds (default 1800).")
    p.add_argument("--fail-threshold", type=int, default=DEFAULT_FAIL_THRESHOLD,
                   help="Consecutive bad checks before paging (default 2, anti-flap).")
    p.add_argument("--dry-run", action="store_true", help="Check + print; never send.")
    p.add_argument("--test-alert", action="store_true",
                   help="Send a one-off install/test alert and exit (verifies the delivery path).")
    args = p.parse_args(argv)

    if args.test_alert:
        ok = _send_alert(
            "\U0001F7E1 <b>ARCIS heartbeat monitor installed</b>\n"
            "One-off test alert — Telegram delivery path verified. You will be "
            "paged if prod PG (5433) or the watch-loop heartbeat goes down."
        )
        logger.info("[heartbeat-monitor] test-alert delivered=%s", ok)
        return 0 if ok else 1

    result = run_once(
        heartbeat_max_age_s=args.heartbeat_max_age,
        fail_threshold=args.fail_threshold,
        dry_run=args.dry_run,
    )
    # exit 1 when DOWN so a cron wrapper / Task Scheduler can also surface it.
    return 1 if result["down"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
