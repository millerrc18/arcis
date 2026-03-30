# Sprint 4C: Dashboard as Control Plane (Claude Code)

> **Executor:** Claude Code
> **Scope:** 8 tasks
> **Prerequisite:** Sprint 4B MERGED (Build Score + page redesigns in place)
> **New session:** Fresh session
> **Principle:** Everything controllable from halcyonlab.app. Local machine only needed for: starting watch loop + running GPU.

---

## System Overview

Arcis (repo: `halcyon-lab`) cloud dashboard is currently **read-only**. All action endpoints return "must be done locally." Settings can't be edited remotely.

**Goal:** Make the dashboard a full control plane via a command queue pattern:
```
Dashboard writes → Render Postgres (pending_commands)
    ↓ pull on 60s sync cycle
Local watch loop executes command
    ↓ push on next sync
Render Postgres (command_results) → Dashboard reads result
```

**Why pull-based:** Render can't push to the local machine (no inbound connections). The local machine already pulls from Render Postgres every 60s via `render_sync.py`. We ride that existing infrastructure.

**Latency:** 0-60 seconds. For instant emergency actions, Telegram `/halt` command remains the fastest path.

---

## Pre-Sprint Checks (MANDATORY)

```bash
find src -name "*.py" ! -path "*__pycache__*" -exec sh -c 'lines=$(wc -l < "$1"); if [ "$lines" -gt 400 ]; then echo "VIOLATION: $1 ($lines lines)"; fi' _ {} \;
python3 -c "
import ast, pathlib
for p in pathlib.Path('src').rglob('*.py'):
    try:
        tree = ast.parse(p.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                length = node.end_lineno - node.lineno
                if length > 60: print(f'VIOLATION: {p}:{node.name} ({length} lines)')
    except: pass
"
find tests -name "test_*.py" -exec grep -c "def test_" {} + | awk -F: '{s+=$2}END{print "Tests:", s}'
```

---

## Task 1: Command Queue DB Schema

Create 4 tables in both SQLite (`scripts/create_missing_tables.py`) and Postgres (`scripts/render_migrate.py`):

```sql
-- Written by dashboard, read by local
CREATE TABLE IF NOT EXISTS pending_commands (
    command_id TEXT PRIMARY KEY,
    command_type TEXT NOT NULL,       -- 'action', 'config_change', 'query'
    command_name TEXT NOT NULL,       -- 'scan', 'council', 'update_setting', etc.
    payload_json TEXT DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',  -- pending/claimed/completed/failed/expired
    priority INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    claimed_at TEXT,
    expires_at TEXT,                  -- auto-expire if not claimed within 5 min
    created_by TEXT DEFAULT 'dashboard'
);

-- Written by local, read by dashboard
CREATE TABLE IF NOT EXISTS command_results (
    result_id TEXT PRIMARY KEY,
    command_id TEXT NOT NULL,
    status TEXT NOT NULL,             -- success/error/partial
    result_json TEXT DEFAULT '{}',   -- truncated to 10KB max
    error_message TEXT,
    execution_ms INTEGER,
    created_at TEXT NOT NULL
);

-- Dashboard-editable settings overlay
CREATE TABLE IF NOT EXISTS config_overrides (
    setting_key TEXT PRIMARY KEY,
    setting_value TEXT NOT NULL,      -- JSON-encoded
    previous_value TEXT,
    updated_at TEXT NOT NULL,
    updated_by TEXT DEFAULT 'dashboard'
);

-- Synced log entries for dashboard viewer
CREATE TABLE IF NOT EXISTS log_entries (
    log_id TEXT PRIMARY KEY,
    log_level TEXT NOT NULL,          -- INFO/WARNING/ERROR/CRITICAL
    source TEXT NOT NULL,             -- watch/scan/council/executor
    message TEXT NOT NULL,
    details_json TEXT,               -- truncated to 5KB
    created_at TEXT NOT NULL
);
```

Add sync config to `src/sync/render_sync.py`:
- `pending_commands`: **cloud → local** (PULL, not push)
- `command_results`: local → cloud (push)
- `config_overrides`: **cloud → local** (PULL)
- `log_entries`: local → cloud (push, last 500 only)

---

## Task 2: Bidirectional Sync

Add `pull_commands()` to `src/sync/render_sync.py`:

1. Connect to Render Postgres
2. Read `pending_commands` WHERE status='pending' AND expires_at > NOW()
3. Insert into local SQLite
4. Update Postgres status to 'claimed' with claimed_at
5. Also pull `config_overrides` (full table replace)
6. Return list of pulled commands for immediate execution

Wire into `watch.py` sync callback:
```python
pulled_commands = pull_commands(pg_conn, self.db_path)
for cmd in pulled_commands:
    self._execute_command(cmd)
```

---

## Task 3: Command Executor

Create `src/commands/executor.py`:

| command_name | command_type | What it does |
|---|---|---|
| `scan` | action | Triggers manual scan cycle |
| `council` | action | Runs council session (payload: `session_type`, optional `question`) |
| `collect-data` | action | Triggers all data collectors |
| `collect-training` | action | Triggers training data collection |
| `train-pipeline` | action | Runs training pipeline |
| `halt-trading` | action | Activates kill switch |
| `resume-trading` | action | Deactivates kill switch |
| `close-position` | action | Closes specific position (payload: `ticker`) |
| `update_setting` | config_change | Updates whitelisted config value |
| `get_logs` | query | Returns recent log entries |

**Safety rules:**
- Commands expire after 5 minutes (don't execute stale commands)
- `update_setting` only allows whitelisted keys (see Task 4)
- All results truncated to 10KB
- Rate limit: max 10 commands per minute
- `close-position` requires valid ticker in payload

---

## Task 4: Config Override System

Create `src/config/overrides.py`:

```python
def get_effective_config(yaml_config: dict, db_path: str) -> dict:
    """Merge settings.yaml with dashboard overrides. Overrides win for whitelisted keys."""
```

**Whitelisted (editable from dashboard):**
- `shadow_trading.max_positions`, `.enabled`, `.timeout_days.default`, `.timeout_days.pullback`
- `risk.planned_risk_pct_min`, `.planned_risk_pct_max`
- `llm.min_conviction_score`, `.enabled`
- `scheduler.scan_interval_minutes`

**NOT editable (require local):** API keys, DB paths, Render connection strings, model paths.

Update `watch.py` to call `get_effective_config()` instead of reading YAML directly.

---

## Task 5: Cloud API — Command Submission

Replace ALL stub action endpoints in `src/api/cloud_routes/core.py`:

**New endpoints:**
- `POST /api/commands/submit` — write command to `pending_commands` in Render Postgres, return `{command_id, status: "pending", expires_at}`
- `GET /api/commands/{id}/status` — check command + result status
- `GET /api/commands/recent` — last 20 commands with results
- `GET /api/logs/recent` — query `log_entries` table (params: level, limit, source)
- `POST /api/settings` — NOW WORKS: submits `update_setting` command via queue

**Replace existing stubs:** `/api/actions/scan`, `/api/actions/council`, `/api/actions/collect-data`, `/api/actions/collect-training`, `/api/actions/train-pipeline`, `/api/halt-trading`, `/api/resume-trading` — each now calls `submit_command_internal()` instead of returning "must be done locally."

Update `frontend/src/api.js` with all new methods.

---

## Task 6: Settings Editor Page

Update `frontend/src/pages/Settings.jsx`:

Replace read-only display with editable form for whitelisted settings:
- Number inputs, toggles, dropdowns as appropriate
- Each setting shows source badge: "yaml default" vs "dashboard override"
- On change → `POST /api/commands/submit` with `command_type: "config_change"`
- Show pending/applied status
- "Reset to YAML" button clears all overrides
- Remove "Changes require local access" warning

---

## Task 7: Log Viewer + Command Status

**Log viewer** — new page `frontend/src/pages/Logs.jsx` or section on existing page:
- Fetch `GET /api/logs/recent?level=INFO&limit=100`
- Table: timestamp, level (color-coded), source, message
- Auto-refresh 30s, filter by level + source

**Command status** — add to Dashboard main page:
- If commands pending: show "Command pending..." indicator
- On completion: flash result briefly

**Local log capture** — add `DBLogHandler` to `src/scheduler/watch.py`:
- Writes structured entries to `log_entries` SQLite table
- Only keep last 500 entries (prune on write)
- Capture WARNING+ by default

---

## Task 8: Documentation Update (MANDATORY)

Run verification commands from `docs/sprint-checklist.md`. Update:
- AGENTS.md counts
- CHANGELOG.md: Sprint 4C entry
- architecture.md: command queue section, new tables, new endpoints
- Create `docs/decisions/012-command-queue-architecture.md` (ADR for pull-based pattern)

**Tests:** Create `tests/test_command_queue.py` ≥12 tests: command submission, expiry, unknown commands, config whitelist, rate limiting, each command type, result truncation, log handler, pull+claim, full round-trip.

```bash
python -m pytest tests/ -x -q
cd frontend && npm run build && cd ..
```

Paste and complete sprint checklist.
