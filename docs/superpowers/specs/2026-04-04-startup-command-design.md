# Startup Command — Design Spec

**Date:** 2026-04-04
**Status:** Final — iteration 3

## Problem

Starting Arcis requires 3-4 manual commands in sequence:
```bash
python -m src.main validate-schema --fix
python -m src.main preflight
python -m src.main watch --email-mode digest --overnight
```
This is error-prone. Forgetting a step means silent data loss (schema drift),
missed failures (unconfigured API keys), or suboptimal operation (no overnight
schedule). The Render dashboard has no visibility into startup health, and
there is no Telegram notification that the system is online.

## Solution

A single `python -m src.main startup` command that:
1. Checks for an existing watch loop (PID lockfile) before wasting time on validation
2. Runs tiered validation with progressive real-time output
3. Persists results to `validation_results` table for the Render dashboard
4. Sends a Telegram startup notification with the summary
5. Launches the watch loop with sensible defaults

## CLI Interface

```
python -m src.main startup                         # digest + overnight (defaults)
python -m src.main startup --email-mode silent     # override email mode
python -m src.main startup --no-overnight          # skip overnight schedule
python -m src.main startup --force                 # bypass critical failures
python -m src.main startup --check-only            # validate only, don't launch
```

Defaults: `--email-mode digest`, `--overnight` on.

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | Clean startup (or --check-only with 0 criticals) |
| 1 | Critical failures blocked startup |
| 2 | --check-only completed with warnings (no criticals) |

## Validation Sequence

### Step 0: PID lockfile check (pre-validation)

Before any validation runs, check `data/watch.lock`. If another watch loop
is already running, print a clear message and exit immediately. This avoids
wasting 10+ seconds on validation only to fail at launch.

```
Another watch loop is already running (PID 12345).
Kill it first:  taskkill /PID 12345 /F
```

### Validation tiers

#### CRITICAL (blocks startup, exit code 1 unless --force)

| Check | Why critical | fix_hint |
|-------|-------------|----------|
| Config file exists | Fallback to example = placeholder creds | Create config/settings.local.yaml from settings.example.yaml |
| YAML not using placeholders | Placeholder values mean nothing works | Replace YOUR_* values in settings.local.yaml with real credentials |
| Schema matches SQLite | Drift causes silent query failures | Run: python -m src.main validate-schema --fix |
| Alpaca API reachable | Shadow/live trading silently fails | Check alpaca.api_key and alpaca.api_secret in settings.local.yaml |
| Render DB URL configured (if render.enabled) | Sync thread fails every cycle | Set render.database_url in settings.local.yaml |

#### WARNING (prints, continues, surfaces on dashboard)

| Check | Why warning | fix_hint |
|-------|------------|----------|
| FINNHUB_API_KEY missing | Analyst, insider, short collectors raise at runtime | Set FINNHUB_API_KEY in .env |
| FRED_API_KEY missing | Macro collector raises at runtime | Set FRED_API_KEY in .env |
| Telegram not configured | No notifications | Set telegram.bot_token and telegram.chat_id |
| Email not configured | No digest emails | Configure email section in settings.local.yaml |
| Ollama/LLM unavailable | Scoring disabled, no recommendations | Start Ollama: ollama serve |
| Kill switch active | Trading halted — may be intentional | Clear via: python -m src.main resume-trading |
| Starting capital < $10,000 | Likely misconfiguration | Set risk.starting_capital in settings.local.yaml |
| Model version missing | No fine-tuned model loaded | Run training pipeline or download a model |

Every check has a **mandatory** `fix_hint`. No check may omit it.

## CLI Output Format

Progressive output — each check prints its result line as it completes. The
user sees real-time progress, not a frozen terminal while Alpaca times out.

No redundant status board — the checklist IS the status. One pass, not two.

### Happy path

```
============================================
         ARCIS — STARTUP SEQUENCE
============================================

[1/5] Config
       OK   settings.local.yaml loaded
       OK   No placeholder values detected

[2/5] Schema
       OK   49 tables, 0 drift (2 auto-fixed)

[3/5] Environment
       OK   FRED_API_KEY
       WARN FINNHUB_API_KEY missing
            -> Set FINNHUB_API_KEY in .env

[4/5] Connectivity
       OK   Alpaca paper $107,432
       WARN Ollama unreachable
            -> Start Ollama: ollama serve

[5/5] Services
       OK   Shadow trading enabled
       OK   Render sync enabled
       WARN Email not configured
            -> Configure email section in settings.local.yaml

--- 9 passed | 3 warnings | 0 critical --------
Launching watch loop (overnight + digest)...
[2026-04-04 21:31:00 ET] Watch loop started (PID 12345)
```

### Critical failure

```
[1/5] Config
       FAIL settings.local.yaml not found
            -> Create config/settings.local.yaml from settings.example.yaml
...
[4/5] Connectivity
       FAIL Alpaca API unreachable (timeout after 10s)
            -> Check alpaca.api_key and api_secret in settings.local.yaml
...
--- 5 passed | 1 warning | 2 CRITICAL ---------

Startup blocked — resolve critical issues above.
Use --force to override at your own risk.
```

### Color and terminal handling

- ANSI color when `sys.stdout.isatty()` and `NO_COLOR` not set
- OK = green, WARN = yellow, FAIL = red, category headers = bold
- Degrades to plain text in non-TTY (CI, piped output, NO_COLOR)

## Architecture

### New files

**`src/startup.py`** — Pure validation logic, no CLI/print concerns.

```python
from dataclasses import dataclass

@dataclass
class CheckResult:
    name: str
    category: str           # "config", "schema", "environment", "connectivity", "services"
    status: str             # "ok", "warn", "critical"
    detail: str
    fix_hint: str           # MANDATORY — actionable fix message

@dataclass
class StartupResult:
    checks: list[CheckResult]
    schema_fixes_applied: int
    duration_ms: int
    timestamp: str

    @property
    def criticals(self) -> list[CheckResult]:
        return [c for c in self.checks if c.status == "critical"]

    @property
    def warnings(self) -> list[CheckResult]:
        return [c for c in self.checks if c.status == "warn"]

    @property
    def passed(self) -> list[CheckResult]:
        return [c for c in self.checks if c.status == "ok"]

    @property
    def overall_status(self) -> str:
        if self.criticals:
            return "critical"
        if self.warnings:
            return "degraded"
        return "healthy"
```

**Validation functions** (each independent, returns immediately):

```python
def check_config(config: dict) -> list[CheckResult]:
    """Config file existence + placeholder value detection."""

def check_schema(db_path: str) -> tuple[list[CheckResult], int]:
    """Schema drift detection + auto-fix. Returns (checks, fixes_applied).
    If auto-fix partially fails, remaining issues are reported as critical."""

def check_environment() -> list[CheckResult]:
    """Required env vars: FINNHUB_API_KEY, FRED_API_KEY."""

def check_connectivity(config: dict) -> list[CheckResult]:
    """Alpaca API, Ollama, Render Postgres (if enabled)."""

def check_services(config: dict) -> list[CheckResult]:
    """Shadow trading, Telegram, email, kill switch, model, capital."""

def is_watch_loop_running() -> int | None:
    """Check PID lockfile. Returns PID if running, None otherwise."""

def persist_startup_result(result: StartupResult, db_path: str) -> str:
    """Save to validation_results table with trigger='startup'.
    Reuses existing save_validation_result() by packaging StartupResult
    into the expected dict shape. Returns result_id."""
```

### Modified files

**`src/cli/commands.py`** — New `cmd_startup(args)` function.

```python
STARTUP_CATEGORIES = [
    ("Config",       "config"),
    ("Schema",       "schema"),
    ("Environment",  "environment"),
    ("Connectivity", "connectivity"),
    ("Services",     "services"),
]

def cmd_startup(args):
    from src.startup import (
        is_watch_loop_running, check_config, check_schema,
        check_environment, check_connectivity, check_services,
        StartupResult, persist_startup_result,
    )

    # Step 0: PID check
    existing_pid = is_watch_loop_running()
    if existing_pid and not args.check_only:
        print(f"Another watch loop is already running (PID {existing_pid}).")
        print(f"Kill it first:  taskkill /PID {existing_pid} /F")
        sys.exit(1)

    _print_banner()

    all_checks = []
    total_fixes = 0
    total = len(STARTUP_CATEGORIES)
    start = time.time()

    for i, (label, fn) in enumerate(STARTUP_CATEGORIES, 1):
        print(f"\n[{i}/{total}] {label}")
        result = fn(config, DB_PATH)
        # check_schema returns (checks, fix_count); others return (checks, 0)
        if isinstance(result, tuple):
            checks, fixes = result
            total_fixes += fixes
        else:
            checks = result
        all_checks.extend(checks)
        for c in checks:
            _print_check(c)

    elapsed = int((time.time() - start) * 1000)
    result = StartupResult(
        checks=all_checks,
        schema_fixes_applied=total_fixes,
        duration_ms=elapsed,
        timestamp=datetime.now(ET).isoformat(),
    )

    persist_startup_result(result, DB_PATH)
    _print_summary(result)

    # Telegram notification
    _send_startup_telegram(result)

    if result.criticals and not args.force:
        print("\nStartup blocked — resolve critical issues above.")
        print("Use --force to override at your own risk.")
        sys.exit(1)

    if args.check_only:
        sys.exit(2 if result.warnings else 0)

    overnight = not getattr(args, "no_overnight", False)
    email_mode = getattr(args, "email_mode", "digest")
    print(f"\nLaunching watch loop (overnight={'yes' if overnight else 'no'}"
          f" + {email_mode})...")

    WatchLoop(config, email_mode=email_mode, overnight=overnight).run()
```

**`src/main.py`** — Register the `startup` subparser:
```python
startup = subparsers.add_parser("startup",
    help="Validate system and launch watch loop")
startup.add_argument("--email-mode", default="digest",
    choices=["full_stream", "daily_summary", "digest", "silent"])
startup.add_argument("--no-overnight", action="store_true",
    help="Disable overnight schedule (data collection, news, enrichment)")
startup.add_argument("--force", action="store_true",
    help="Launch despite critical failures")
startup.add_argument("--check-only", action="store_true",
    help="Run validation only, don't launch watch loop")
startup.set_defaults(func=cmd_startup)
```

**`src/api/routes/health.py`** — New `/health/startup` endpoint.

**`src/notifications/telegram.py`** — New `notify_startup_complete()` function.

### Telegram notification

After validation completes (before launching the watch loop), send a
Telegram summary using the existing `send_telegram()` infrastructure:

```
🚀 ARCIS STARTUP

9 passed | 3 warnings | 0 critical
Status: DEGRADED

⚠️ FINNHUB_API_KEY missing
⚠️ Ollama unreachable
⚠️ Email not configured

Watch loop launching (overnight + digest)
```

On critical block:
```
❌ ARCIS STARTUP BLOCKED

5 passed | 1 warning | 2 CRITICAL

❌ settings.local.yaml not found
❌ Alpaca API unreachable

Use --force to override.
```

Uses `notify_system_event` pattern. Skipped if Telegram is not configured
(since that's just another warning, not a crash).

### Dashboard integration

**`/health/startup` API response:**
```json
{
  "timestamp": "2026-04-04T21:31:00-04:00",
  "duration_ms": 3400,
  "overall_status": "degraded",
  "trigger": "startup",
  "summary": {"ok": 9, "warn": 3, "critical": 0},
  "categories": {
    "config": [
      {"name": "config_file", "status": "ok",
       "detail": "settings.local.yaml loaded",
       "fix_hint": "Create config/settings.local.yaml from settings.example.yaml"}
    ],
    "environment": [
      {"name": "finnhub_key", "status": "warn",
       "detail": "FINNHUB_API_KEY missing",
       "fix_hint": "Set FINNHUB_API_KEY in .env"}
    ]
  },
  "previous_status": "healthy"
}
```

**Previous status:** queried from the second-most-recent `validation_results`
row where `trigger='startup'`. Used for transition display on the dashboard
("was healthy, now degraded").

**Dashboard card** on main page:
- Uses existing `StatusBadge` component (HEALTHY/DEGRADED/CRITICAL)
- Shows "Last startup: 3h ago — 9 OK, 3 warnings"
- Categories with failures auto-expand; others collapsed
- Links to Validation page for drill-down

**Validation.jsx integration:**
- The existing CategoryCard component works as-is — same `{name, status, detail}` shape
- Add a "Startup Checks" tab/section alongside the existing "System Validation" section
- Failed categories sort to top

### CLAUDE.md update

The Startup / Restart Sequence section updates from:
```bash
git pull origin main
python -m src.main validate-schema --fix
python -m src.main watch --email-mode digest --overnight
```
To:
```bash
git pull origin main
python -m src.main startup
```

With a note about `--check-only`, `--force`, and `--no-overnight` flags.

## Testing

### Unit tests (src/startup.py) — 15 tests
- `test_check_config_local_exists` — local yaml → ok
- `test_check_config_example_fallback` — example only → critical
- `test_check_config_placeholder_values` — YOUR_* in yaml → critical
- `test_check_schema_no_drift` — clean schema → ok
- `test_check_schema_drift_autofix` — drift + fix → ok with fix count
- `test_check_schema_fix_partial_fail` — partial fix → critical for remaining
- `test_check_environment_all_keys` — keys set → ok
- `test_check_environment_missing_finnhub` — missing → warn with fix_hint
- `test_check_connectivity_alpaca_ok` — 200 → ok with equity
- `test_check_connectivity_alpaca_timeout` — timeout → critical
- `test_check_connectivity_ollama_down` — unreachable → warn
- `test_check_services_all_enabled` — full config → ok
- `test_startup_result_overall_status` — property returns correct tier
- `test_persist_startup_result` — saved to validation_results, readable
- `test_fix_hint_mandatory` — every CheckResult has non-empty fix_hint

### Integration tests (cmd_startup) — 5 tests
- `test_cmd_startup_blocks_on_critical` — exit code 1
- `test_cmd_startup_force_bypasses` — --force launches
- `test_cmd_startup_check_only_clean` — exit 0, doesn't launch
- `test_cmd_startup_check_only_warnings` — exit 2
- `test_cmd_startup_pid_lockfile_blocks` — existing PID → exit 1

### API + notification tests — 4 tests
- `test_health_startup_endpoint_shape` — returns expected JSON
- `test_health_startup_no_results` — returns empty when never run
- `test_health_startup_previous_status` — includes transition field
- `test_notify_startup_telegram` — sends correct summary format
