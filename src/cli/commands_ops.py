"""CLI command implementations — ops & system domain (Arcis).

Called by: cli.commands (re-export), main (via re-export)
Calls: config, email.notifier, evaluation.system_validator, journal.store, notifications, notifications.telegram, packets.template, scheduler.watch, schema.validator, services.system_service, startup, utils.deploy_info
Owns tables: none
Config keys: enabled, live_trading
Tests: tests/cli/test_cli_split_integrity.py, tests/cli/test_digest_preview_cli.py, tests/cli/test_email_cli_passthrough.py, tests/test_tier_2_safety.py, tests/test_security.py
"""

import logging
import sys

from src.config import DB_PATH
from src.utils.db import connect_db
from src.email.notifier import send_email
from src.journal.store import initialize_database
from src.notifications import email_digest as _email_digest_mod
from src.notifications import safe_send
from src.notifications.telegram import is_telegram_enabled, send_telegram
from src.packets.template import build_demo_packet

logger = logging.getLogger(__name__)


def _safe_print(text: str) -> None:
    """Print text without crashing on Windows console encoding mismatches."""
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        if hasattr(sys.stdout, "buffer"):
            sys.stdout.buffer.write(text.encode(encoding, errors="replace") + b"\n")
            sys.stdout.flush()
        else:
            print(text.encode(encoding, errors="replace").decode(encoding, errors="replace"))


def cmd_init_db(args):
    initialize_database(args.db_path)
    print(f"Initialized journal database at {args.db_path}")


def cmd_demo_packet(args):
    print(build_demo_packet())


def cmd_send_test_email(args):
    success = send_email(
        "[TRADE DESK] Test Email",
        "This is a test from Arcis. Email delivery is working.",
    )
    print("Test email sent successfully." if success else "Failed to send test email.")


def cmd_send_test_telegram(args):
    if not is_telegram_enabled():
        print("Telegram not configured. Add telegram section to config/settings.local.yaml:")
        print("  telegram:")
        print("    enabled: true")
        print('    bot_token: "your-bot-token"')
        print('    chat_id: "your-chat-id"')
        return
    success = send_telegram(
        "🧪 <b>ARCIS — TEST</b>\n"
        "Telegram notifications are working!\n"
        "You'll receive alerts for:\n"
        "  • Trade opens/closes\n"
        "  • Earnings warnings\n"
        "  • Overnight data collection\n"
        "  • System events"
    )
    _safe_print("Telegram test sent successfully! ✓" if success else "Failed to send Telegram message.")


def cmd_preflight(args):
    from src.config import load_config
    from src.services.system_service import get_system_status

    status = get_system_status(load_config())
    print("\nARCIS - PREFLIGHT CHECK")
    print(f"  Config:    {'OK' if status['config_loaded'] else 'FAIL'}")
    print(f"  Source:    {status.get('config_source', 'unknown')}")
    print(f"  Email:     {'OK' if status['email_configured'] else 'FAIL'}")
    print(f"  Alpaca:    {'OK' if status['alpaca_connected'] else 'FAIL'} {'$' + str(int(status['alpaca_equity'])) if status['alpaca_equity'] else ''}")
    print(f"  Shadow:    {'Enabled' if status['shadow_trading_enabled'] else 'Disabled'}")
    print(f"  Live:      {'Enabled' if status['live_trading_enabled'] else 'Disabled'}")
    print(f"  Telegram:  {'OK' if status['telegram_configured'] else 'FAIL'}")
    print(f"  Halt:      {'ACTIVE' if status['kill_switch_halted'] else 'clear'}")
    print(f"  Ollama:    {'OK' if status['ollama_available'] else 'FAIL'}")
    print(f"  LLM:       {'OK (' + status['llm_model'] + ')' if status['llm_enabled'] and status['ollama_available'] else 'Disabled'}")
    print(f"  Model:     {status['model_version']}")
    print(f"  Journal:   {status['journal_recommendations']} recs, {status['journal_shadow_trades']} trades")
    print(f"  Training:  {'Enabled (' + str(status['training_examples']) + ' examples)' if status['training_enabled'] else 'Disabled'}")
    print(f"  Bootcamp:  {'Phase ' + str(status['bootcamp_phase']) if status['bootcamp_enabled'] else 'Disabled'}")

    if status.get("config_source") == "example":
        _safe_print("\nWARNING: Running on config/settings.example.yaml (template defaults).")
        print("   Create config/settings.local.yaml with real credentials and enabled flags.")


def cmd_config_fix(args):
    """Merge missing keys from settings.example.yaml into settings.local.yaml.

    Uses ruamel.yaml for round-trip parsing — preserves comments, blank lines,
    and formatting in the local config. Falls back to PyYAML if ruamel unavailable.
    """
    from pathlib import Path
    import shutil

    local_path = Path("config/settings.local.yaml")
    example_path = Path("config/settings.example.yaml")

    if not local_path.exists():
        print("ERROR: config/settings.local.yaml not found.")
        print("  Create it first: cp config/settings.example.yaml config/settings.local.yaml")
        return

    if not example_path.exists():
        print("ERROR: config/settings.example.yaml not found.")
        return

    try:
        from ruamel.yaml import YAML
        ryaml = YAML()
        ryaml.preserve_quotes = True
        ryaml.width = 120

        with open(local_path, "r", encoding="utf-8") as f:
            local = ryaml.load(f) or {}
        with open(example_path, "r", encoding="utf-8") as f:
            example = ryaml.load(f) or {}

        use_ruamel = True
    except ImportError:
        import yaml
        print("(ruamel.yaml not installed — formatting will not be preserved)")
        print("  pip install ruamel.yaml")
        with open(local_path, "r", encoding="utf-8") as f:
            local = yaml.safe_load(f) or {}
        with open(example_path, "r", encoding="utf-8") as f:
            example = yaml.safe_load(f) or {}
        use_ruamel = False

    added = []

    def _merge_missing(ex, loc, prefix=""):
        for key in ex:
            full = f"{prefix}.{key}" if prefix else key
            if key not in loc:
                loc[key] = ex[key]
                # Add a blank line before new top-level sections for readability
                if use_ruamel and not prefix and hasattr(loc, 'ca'):
                    try:
                        from ruamel.yaml.tokens import CommentToken
                        from ruamel.yaml.error import CommentMark
                        loc.ca.items[key] = [
                            CommentToken("\n\n", CommentMark(0), None),
                            None, None, None,
                        ]
                    except Exception:
                        pass
                added.append(full)
            elif isinstance(ex[key], dict) and isinstance(loc.get(key), dict):
                _merge_missing(ex[key], loc[key], full)

    _merge_missing(example, local)

    if not added:
        print("Config is up to date — no missing keys.")
        return

    # Backup before writing
    backup_path = local_path.with_suffix(".yaml.bak")
    shutil.copy2(local_path, backup_path)

    if use_ruamel:
        with open(local_path, "w", encoding="utf-8") as f:
            ryaml.dump(local, f)
    else:
        import yaml
        with open(local_path, "w", encoding="utf-8") as f:
            yaml.dump(local, f, default_flow_style=False, sort_keys=False)

    print(f"Added {len(added)} missing keys (backup: {backup_path})")
    for k in added:
        print(f"  + {k}")


def cmd_config_diff(args):
    """Show keys in settings.example.yaml missing from settings.local.yaml."""
    from pathlib import Path
    import yaml

    local_path = Path("config/settings.local.yaml")
    example_path = Path("config/settings.example.yaml")

    if not local_path.exists():
        print("ERROR: config/settings.local.yaml not found.")
        return
    if not example_path.exists():
        print("ERROR: config/settings.example.yaml not found.")
        return

    with open(local_path, "r", encoding="utf-8") as f:
        local = yaml.safe_load(f) or {}
    with open(example_path, "r", encoding="utf-8") as f:
        example = yaml.safe_load(f) or {}

    from src.startup import _find_missing_keys
    missing = []
    _find_missing_keys(example, local, "", missing)

    if not missing:
        print("Config is up to date — no missing keys.")
    else:
        print(f"{len(missing)} missing keys:")
        for k in missing:
            print(f"  - {k}")


def _assert_safe_live_governor_combo(config: dict, force: bool) -> None:
    """#574 — Refuse to launch when live trading is on but the risk
    governor is disabled. That combination auto-approves every trade
    with no daily-loss cap, no per-position size limit, no VIX circuit
    breaker, no sector concentration check, and no correlation cap —
    the textbook system-blow-up scenario.

    The --force flag bypasses the check (logs critically, then proceeds)
    so the operator retains an explicit escape hatch for emergencies.
    """
    live_enabled = bool(config.get("live_trading", {}).get("enabled"))
    governor_enabled = bool(config.get("risk_governor", {}).get("enabled"))
    if live_enabled and not governor_enabled:
        msg = (
            "REFUSING TO LAUNCH: live_trading.enabled=true AND "
            "risk_governor.enabled=false. This auto-approves every trade "
            "with NO daily-loss cap, NO position-size limit, NO VIX "
            "circuit breaker, NO sector concentration cap, NO correlation "
            "limit. Set risk_governor.enabled=true OR pass --force to "
            "bypass (logs critically). (#574)"
        )
        if not force:
            raise RuntimeError(msg)
        # Force-bypass — log critically so the audit trail is unmistakable
        import logging
        logging.getLogger("src.cli.commands").critical(
            "[STARTUP] %s — operator passed --force, proceeding anyway.", msg,
        )


def cmd_startup(args):
    """Validate system and launch watch loop — single startup command."""
    import sys
    import time as _time
    from src.config import load_config
    from src.startup import (
        is_watch_loop_running, persist_startup_result, STARTUP_CATEGORIES,
    )

    config = load_config()
    check_only = getattr(args, "check_only", False)
    force = getattr(args, "force", False)

    if not check_only:
        # #574 — fail-fast on dangerous live+governor combo BEFORE state.
        _assert_safe_live_governor_combo(config, force=force)
        existing_pid = is_watch_loop_running()
        if existing_pid:
            print(f"Another watch loop is already running (PID {existing_pid}).")
            print(f"Kill it first:  taskkill /PID {existing_pid} /F")
            sys.exit(1)

    print("=" * 44)
    print("         ARCIS — STARTUP SEQUENCE")
    print("=" * 44)

    # #630 — Capture deployed git SHA so the operator (and future log dives)
    # can spot when a long-running watch loop is running stale bytecode.
    try:
        from src.utils.deploy_info import log_deployment_info
        info = log_deployment_info("watch_start")
        print(f"  Deployed: {info.get('git_short_sha')} ({info.get('git_branch')}) — committed {info.get('git_commit_age')}")
    except Exception as exc:
        # Never let banner code crash startup.
        print(f"  Deployed: unknown (banner failed: {exc})")

    all_checks = []
    start = _time.time()
    for i, (label, check_fn) in enumerate(STARTUP_CATEGORIES, 1):
        print(f"\n[{i}/{len(STARTUP_CATEGORIES)}] {label}")
        results = check_fn(config, DB_PATH)
        all_checks.extend(results)
        for c in results:
            _print_startup_check(c)

    result = _build_startup_result(all_checks, int((_time.time() - start) * 1000))

    try:
        persist_startup_result(result, DB_PATH)
    except Exception as e:
        print(f"\n  (Could not persist startup result: {e})")

    p, w, c = len(result.passed), len(result.warnings), len(result.criticals)
    print(f"\n--- {p} passed | {w} warnings | "
          f"{c} {'CRITICAL' if c else 'critical'} " + "-" * 8)

    _notify_startup_telegram(result, args, check_only)
    _startup_decision(result, args, config, check_only)


def _build_startup_result(all_checks, elapsed_ms):
    """Build a StartupResult from collected checks."""
    import re
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from src.startup import StartupResult
    result = StartupResult(
        checks=all_checks, schema_fixes_applied=0,
        duration_ms=elapsed_ms,
        timestamp=datetime.now(ZoneInfo("America/New_York")).isoformat(),
    )
    for c in all_checks:
        if c.category == "schema" and "auto-fixed" in c.detail:
            m = re.search(r"(\d+) auto-fixed", c.detail)
            if m:
                result.schema_fixes_applied = int(m.group(1))
    return result


def _notify_startup_telegram(result, args, check_only):
    """Send Telegram notification with startup results."""
    force = getattr(args, "force", False)
    p, w, c = len(result.passed), len(result.warnings), len(result.criticals)
    safe_send(
        "startup_complete",
        overall_status=result.overall_status,
        passed=p, warnings=w, criticals=c,
        warning_details=[ch.detail for ch in result.warnings[:5]],
        critical_details=[ch.detail for ch in result.criticals[:5]],
        launching=(c == 0 or force) and not check_only,
        email_mode=getattr(args, "email_mode", "digest"),
        overnight=not getattr(args, "no_overnight", False),
    )


def _startup_decision(result, args, config, check_only):
    """Handle startup decision: block, check-only exit, or launch watch loop."""
    import sys
    force = getattr(args, "force", False)
    if result.criticals and not force:
        print("\nStartup blocked — resolve critical issues above.")
        print("Use --force to override at your own risk.")
        sys.exit(1)
    if check_only:
        sys.exit(2 if result.warnings else 0)
    overnight = not getattr(args, "no_overnight", False)
    email_mode = getattr(args, "email_mode", "digest")
    print(f"\nLaunching watch loop (overnight={'yes' if overnight else 'no'}"
          f" + {email_mode})...")
    from src.scheduler.watch import WatchLoop
    WatchLoop(config, email_mode=email_mode, overnight=overnight).run()


def _print_startup_check(check):
    """Print a single check result with color if supported."""
    import os
    use_color = os.isatty(1) and not os.environ.get("NO_COLOR")

    status_map = {
        "ok": ("OK  ", "\033[32m" if use_color else ""),
        "warn": ("WARN", "\033[33m" if use_color else ""),
        "critical": ("FAIL", "\033[31m" if use_color else ""),
    }
    label, color = status_map.get(check.status, ("??  ", ""))
    reset = "\033[0m" if use_color else ""

    print(f"       {color}{label}{reset} {check.detail}")
    if check.status != "ok" and check.fix_hint:
        print(f"            -> {check.fix_hint}")


def cmd_watch(args):
    from src.config import load_config
    from src.scheduler.watch import WatchLoop

    WatchLoop(
        load_config(),
        email_mode=getattr(args, "email_mode", None),
        overnight=getattr(args, "overnight", False),
    ).run()


def cmd_dashboard(args):
    import uvicorn

    port = getattr(args, "port", 8000)
    print(f"Starting dashboard at http://localhost:{port}")
    uvicorn.run("src.api.app:app", host="127.0.0.1", port=port, reload=False)


def cmd_validate_system(args):
    """Run system validation checks across all subsystems."""
    import json as _json

    from src.evaluation.system_validator import run_full_validation, save_validation_result

    print("Running system validation...")
    result = run_full_validation()

    if getattr(args, "json", False):
        print(_json.dumps(result, indent=2))
    else:
        status_icon = {"healthy": "[OK]", "degraded": "[WARN]", "critical": "[FAIL]"}.get(result["overall_status"], "?")
        _safe_print(f"\n{status_icon} Overall: {result['overall_status'].upper()}")
        _safe_print(f"   Passed: {result['checks_passed']}  |  Warnings: {result['checks_warning']}  |  Failed: {result['checks_failed']}")
        _safe_print(f"   Total checks: {result['checks_total']}\n")

        for category, checks in result["categories"].items():
            cat_fails = sum(1 for check in checks if check["status"] == "fail")
            cat_warns = sum(1 for check in checks if check["status"] == "warn")
            cat_pass = sum(1 for check in checks if check["status"] == "pass")
            icon = "[FAIL]" if cat_fails else "[WARN]" if cat_warns else "[OK]"
            _safe_print(f"  {icon} {category.upper()} ({cat_pass}P / {cat_warns}W / {cat_fails}F)")
            for check in checks:
                marker = {"pass": "  [OK]", "warn": "  [WARN]", "fail": "  [FAIL]"}.get(check["status"], "  ?")
                _safe_print(f"    {marker} {check['name']}: {check['detail']}")
            print()

    result_id = save_validation_result(result)
    print(f"Result saved: {result_id}")

    if getattr(args, "fix", False):
        print("\n--fix: Attempting auto-fixes...")
        initialize_database()
        print("  Re-ran initialize_database() to ensure all tables exist.")


def cmd_validate_schema(args):
    """Validate database schema against the schema registry."""
    from src.schema.validator import validate_sqlite, validate_codebase, fix_issues

    print("Validating SQLite schema...")
    issues = validate_sqlite(DB_PATH)
    code_issues = validate_codebase()

    all_issues = issues + code_issues
    for issue in all_issues:
        print(f"  {issue}")

    if not all_issues:
        print("Schema OK — no issues found.")
        return

    print(f"\n{len(issues)} database issues, {len(code_issues)} codebase violations")

    if getattr(args, "fix", False) and issues:
        actions = fix_issues(issues, DB_PATH)
        for a in actions:
            print(f"  FIX: {a}")


# ── #115 T15 — Email-digest CLI ───────────────────────────────────────────

_VALID_DIGEST_TIERS = ("preopen", "postclose", "weekly")


def cmd_digest_preview(args):
    """Preview an email digest tier (#115 T15).

    Default mode: render preview_tier(tier) and print plain-text body.
    --pending: query notifications_digest_queue for pending rows matching the
               tier's source_tag prefix and print a table.
    --dry-run: alias for default-preview (explicit no-side-effects flag).
    """
    tier = getattr(args, "tier", None)
    if tier not in _VALID_DIGEST_TIERS:
        raise ValueError(
            f"invalid --tier {tier!r}; expected one of {_VALID_DIGEST_TIERS!r}"
        )

    if getattr(args, "pending", False):
        # Print a table of pending queue rows for this tier.
        source_prefix = f"email:{tier}"
        with connect_db() as conn:
            cur = conn.execute(
                "SELECT id, event_type, severity, source_tag, created_at "
                "FROM notifications_digest_queue "
                "WHERE flush_status = 'pending' "
                "  AND (source_tag = ? OR source_tag LIKE ? || ':%') "
                "ORDER BY created_at ASC",
                (source_prefix, source_prefix),
            )
            rows = cur.fetchall()
        # Header
        header = f"{'id':>6}  {'event_type':<28}  {'severity':<10}  {'source_tag':<40}  created_at"
        _safe_print(header)
        _safe_print("-" * len(header))
        if not rows:
            _safe_print(f"(no pending rows for tier {tier!r})")
            return
        for r in rows:
            # Support both sqlite3.Row and dict-like rows.
            try:
                rid = r["id"]
                etype = r["event_type"]
                sev = r["severity"]
                stag = r["source_tag"]
                created = r["created_at"]
            except (KeyError, IndexError, TypeError):
                rid, etype, sev, stag, created = r
            _safe_print(
                f"{rid!s:>6}  {str(etype):<28}  {str(sev):<10}  {str(stag):<40}  {created}"
            )
        return

    # Default + --dry-run: render and print plain-text body via the
    # decorated public API (preview_tier on the email_digest module).
    body = _email_digest_mod.preview_tier(tier)
    _safe_print(body)


def cmd_digest_handover_check(args):
    """Run handover-readiness tripwires (#115 T15, DA-MAJ-7 + DA-MAJ-11).

    Calls email_digest.handover_check(window_days=...). Exit 0=PASS, 1=FAIL.
    --compare-window 7d triggers the row-ID inclusion check (DA-MAJ-11).
    """
    window_days = int(getattr(args, "window_days", 7))
    compare_window = getattr(args, "compare_window", None)

    # Call handover_check via the decorated public API on email_digest.
    if compare_window:
        result = _email_digest_mod.handover_check(
            window_days=window_days,
            compare_window=compare_window,
        )
    else:
        result = _email_digest_mod.handover_check(window_days=window_days)

    status = str(result.get("status", "FAIL")).upper()
    _safe_print(f"Handover-check: {status}")
    tripwires = result.get("tripwires", {}) or {}
    for name, detail in tripwires.items():
        _safe_print(f"  - {name}: {detail}")

    sys.exit(0 if status == "PASS" else 1)
