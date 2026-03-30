# Sprint 4C: Dashboard as Control Plane (Command Queue Architecture)

> **Executor:** Claude Code
> **Scope:** 8 tasks
> **Prerequisite:** Sprint 4B merged (Build Score, page redesigns, .env all in place)
> **New session:** Do NOT run in the same session as Sprint 4B
> **Principle:** Everything controllable from the Render dashboard. Local machine only needed for: (1) starting the watch loop, (2) running the GPU.

---

## System Overview

You are working on Arcis (GitHub repo: `halcyon-lab`), an autonomous AI-powered equity trading system.

**Current problem:** The Render cloud dashboard (halcyonlab.app) is read-only. All action endpoints return "must be done locally." Settings can't be edited. The dashboard is a monitoring tool, not a control plane.

**Goal:** Make the dashboard a full control plane. Ryan should be able to trigger actions, edit settings, view logs, and manage the system entirely from his phone — without SSH, CLI, or touching the local machine.

**Architecture:** Command queue pattern.
- Dashboard writes commands → Render Postgres `pending_commands` table
- Local watch loop polls `pending_commands` on each sync cycle (every 60s)
- Watch loop executes the command locally → writes result to `command_results` table
- Result syncs back to Render Postgres on next sync
- Dashboard shows command status and results

**Why this pattern?** Render can't push to the local machine (no inbound connections). But the local machine already pulls from Render Postgres on every sync cycle. We ride that existing sync infrastructure instead of building webhooks or tunnels.

---

## Codebase Architecture (relevant parts)

```
src/
├── sync/render_sync.py          # SQLite ↔ Render Postgres bidirectional sync
│                                 # Currently: local → cloud (one-way)
│                                 # Sprint 4C: add cloud → local for commands
├── scheduler/watch.py            # Main watch loop (APScheduler)
│                                 # Runs sync every 60s, scans every ~30min
├── api/cloud_routes/core.py      # Cloud API — currently stubs for all actions
└── api/cloud_app.py              # Cloud app bootstrap
```

### Current Sync Flow (one-way)
```
Local SQLite → render_sync.py → Render Postgres → Dashboard reads
```

### Sprint 4C Sync Flow (bidirectional for commands)
```
Dashboard writes → Render Postgres (pending_commands)
                          ↓ (pull on sync cycle)
                   Local watch loop
                          ↓ (execute)
                   Local SQLite (command_results)
                          ↓ (push on sync cycle)
                   Render Postgres (command_results)
                          ↓
                   Dashboard reads result
```

---

## Pre-Sprint Checks (MANDATORY)

```bash
# File size guardrail
find src -name "*.py" ! -path "*__pycache__*" -exec sh -c 'lines=$(wc -l < "$1"); if [ "$lines" -gt 400 ]; then echo "VIOLATION: $1 ($lines lines)"; fi' _ {} \;

# Function length guardrail
python3 -c "
import ast, pathlib
for p in pathlib.Path('src').rglob('*.py'):
    try:
        tree = ast.parse(p.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                length = node.end_lineno - node.lineno
                if length > 60:
                    print(f'VIOLATION: {p}:{node.name} ({length} lines)')
    except: pass
"

# Current test count baseline
find tests -name "test_*.py" -exec grep -c "def test_" {} + | awk -F: '{s+=$2}END{print "Tests:", s}'
```

Fix any violations BEFORE starting feature work.

---

## Task 1: Command Queue Database Schema

Create tables for the command queue in both SQLite and Postgres.

### `pending_commands` — written by dashboard, read by local
```sql
CREATE TABLE IF NOT EXISTS pending_commands (
    command_id TEXT PRIMARY KEY,              -- UUID
    command_type TEXT NOT NULL,               -- 'action', 'config_change', 'query'
    command_name TEXT NOT NULL,               -- 'scan', 'council', 'collect-data', 'update_setting', etc.
    payload_json TEXT DEFAULT '{}',           -- Command-specific parameters
    status TEXT NOT NULL DEFAULT 'pending',   -- 'pending', 'claimed', 'completed', 'failed', 'expired'
    priority INTEGER DEFAULT 0,              -- Higher = execute first
    created_at TEXT NOT NULL,                -- When dashboard submitted
    claimed_at TEXT,                         -- When watch loop picked it up
    expires_at TEXT,                         -- Auto-expire if not claimed within 5 minutes
    created_by TEXT DEFAULT 'dashboard'      -- Source identification
);
```

### `command_results` — written by local, read by dashboard
```sql
CREATE TABLE IF NOT EXISTS command_results (
    result_id TEXT PRIMARY KEY,              -- UUID
    command_id TEXT NOT NULL,                -- FK to pending_commands
    status TEXT NOT NULL,                    -- 'success', 'error', 'partial'
    result_json TEXT DEFAULT '{}',           -- Command output (truncated to 10KB max)
    error_message TEXT,                      -- Error details if failed
    execution_ms INTEGER,                    -- How long it took
    created_at TEXT NOT NULL                 -- When local finished execution
);
```

### `config_overrides` — dashboard-editable settings
```sql
CREATE TABLE IF NOT EXISTS config_overrides (
    setting_key TEXT PRIMARY KEY,            -- e.g. 'shadow_trading.max_positions'
    setting_value TEXT NOT NULL,             -- JSON-encoded value
    previous_value TEXT,                     -- For audit trail
    updated_at TEXT NOT NULL,
    updated_by TEXT DEFAULT 'dashboard'
);
```

### `log_entries` — synced subset of local logs
```sql
CREATE TABLE IF NOT EXISTS log_entries (
    log_id TEXT PRIMARY KEY,
    log_level TEXT NOT NULL,                 -- 'INFO', 'WARNING', 'ERROR', 'CRITICAL'
    source TEXT NOT NULL,                    -- 'watch', 'scan', 'council', 'executor', etc.
    message TEXT NOT NULL,
    details_json TEXT,                       -- Extra context (truncated to 5KB)
    created_at TEXT NOT NULL
);
```

Add all 4 tables to:
- `scripts/create_missing_tables.py` (SQLite)
- `scripts/render_migrate.py` (Postgres)
- `src/sync/render_sync.py` (sync config)

**Sync direction:**
- `pending_commands`: cloud → local (PULL from Postgres, not push)
- `command_results`: local → cloud (normal push)
- `config_overrides`: cloud → local (PULL)
- `log_entries`: local → cloud (push, last 500 entries only)

---

## Task 2: Bidirectional Sync in render_sync.py

Currently `render_sync.py` only pushes local → cloud. Add a `pull_commands()` function that:

1. Connects to Render Postgres
2. Reads `pending_commands` WHERE status = 'pending' AND expires_at > NOW()
3. Inserts them into local SQLite
4. Updates Postgres status to 'claimed' with claimed_at = NOW()
5. Also pulls `config_overrides` (full table, not incremental)

```python
def pull_commands(pg_conn, local_db_path: str) -> list[dict]:
    """Pull pending commands from Render Postgres to local SQLite.
    
    Returns list of commands that were pulled for immediate execution.
    Called during each sync cycle in watch.py.
    """
    # Read pending commands from Postgres
    # Insert into local SQLite
    # Mark as 'claimed' in Postgres
    # Return the commands for the watch loop to execute
```

**Critical:** This is the ONLY place where cloud data flows to local. The sync is pull-based (local initiates), not push-based (cloud can't reach local).

**Add to the existing sync cycle** in `watch.py`:
```python
# In the sync scheduler callback:
pulled_commands = pull_commands(pg_conn, self.db_path)
for cmd in pulled_commands:
    self._execute_command(cmd)
```

---

## Task 3: Command Executor in watch.py

Create `src/commands/executor.py` (new module) that processes commands from the queue.

### Supported Commands

| command_name | command_type | payload_json | What it does |
|---|---|---|---|
| `scan` | action | `{}` | Triggers a manual scan cycle |
| `council` | action | `{"session_type": "daily"}` or `{"session_type": "strategic", "question": "..."}` | Runs a council session |
| `collect-data` | action | `{}` | Triggers all data collectors |
| `collect-training` | action | `{}` | Triggers training data collection |
| `train-pipeline` | action | `{}` | Runs the training pipeline |
| `halt-trading` | action | `{}` | Activates kill switch |
| `resume-trading` | action | `{}` | Deactivates kill switch |
| `close-position` | action | `{"ticker": "AAPL"}` | Closes a specific position |
| `update_setting` | config_change | `{"key": "shadow_trading.max_positions", "value": 20}` | Updates a config value |
| `get_logs` | query | `{"level": "ERROR", "limit": 50}` | Returns recent log entries |

```python
def execute_command(command: dict, db_path: str, config: dict) -> dict:
    """Execute a command and return the result.
    
    Args:
        command: dict with command_id, command_type, command_name, payload_json
        db_path: path to local SQLite
        config: current settings dict
    
    Returns:
        dict with status ('success'/'error'), result_json, error_message, execution_ms
    """
    start = time.monotonic()
    try:
        handler = COMMAND_HANDLERS.get(command["command_name"])
        if not handler:
            return {"status": "error", "error_message": f"Unknown command: {command['command_name']}"}
        
        payload = json.loads(command.get("payload_json", "{}"))
        result = handler(payload, db_path, config)
        
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {"status": "success", "result_json": json.dumps(result)[:10240], "execution_ms": elapsed_ms}
    except Exception as e:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {"status": "error", "error_message": str(e)[:1024], "execution_ms": elapsed_ms}
```

**Safety rules:**
- Commands expire after 5 minutes (don't execute stale commands)
- `halt-trading` and `resume-trading` require no payload validation
- `close-position` requires a valid ticker in the payload
- `update_setting` only allows keys from a whitelist (not arbitrary config mutation)
- All results are truncated to 10KB max to prevent sync bloat
- Rate limit: max 10 commands per minute (prevent dashboard abuse)

---

## Task 4: Config Override System

Create `src/config/overrides.py` that layers dashboard overrides on top of `settings.yaml`.

```python
def get_effective_config(yaml_config: dict, db_path: str) -> dict:
    """Merge settings.yaml with dashboard overrides.
    
    Dashboard overrides take precedence over YAML for whitelisted keys.
    This allows editing settings from the dashboard without touching local files.
    """
    overrides = _load_overrides(db_path)  # From config_overrides table
    merged = deep_merge(yaml_config, overrides)
    return merged
```

**Whitelisted settings (editable from dashboard):**
- `shadow_trading.max_positions`
- `shadow_trading.enabled`
- `shadow_trading.timeout_days.default`
- `shadow_trading.timeout_days.pullback`
- `risk.planned_risk_pct_min`
- `risk.planned_risk_pct_max`
- `llm.min_conviction_score`
- `llm.enabled`
- `scheduler.scan_interval_minutes`

**NOT editable from dashboard (require local access):**
- API keys, secrets (managed via .env)
- Database paths
- Render connection strings
- Model names/paths

Update `watch.py` to call `get_effective_config()` instead of reading YAML directly, so dashboard overrides take effect on the next scan cycle without a restart.

---

## Task 5: Cloud API — Command Submission Endpoints

Replace the stub action endpoints in `src/api/cloud_routes/core.py` that currently return "must be done locally."

```python
@router.post("/api/commands/submit")
async def submit_command(request: Request):
    """Submit a command to the queue for local execution."""
    body = await request.json()
    command_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    expires = (datetime.utcnow() + timedelta(minutes=5)).isoformat()
    
    with get_pg_conn() as conn:
        conn.execute(
            "INSERT INTO pending_commands (command_id, command_type, command_name, "
            "payload_json, status, created_at, expires_at) VALUES (%s, %s, %s, %s, 'pending', %s, %s)",
            (command_id, body["command_type"], body["command_name"],
             json.dumps(body.get("payload", {})), now, expires)
        )
    return {"command_id": command_id, "status": "pending", "expires_at": expires}

@router.get("/api/commands/{command_id}/status")
async def get_command_status(command_id: str):
    """Check status of a submitted command."""
    with get_pg_conn() as conn:
        cmd = conn.execute(
            "SELECT status, claimed_at FROM pending_commands WHERE command_id = %s", (command_id,)
        ).fetchone()
        result = conn.execute(
            "SELECT status, result_json, error_message, execution_ms FROM command_results "
            "WHERE command_id = %s", (command_id,)
        ).fetchone()
    return {
        "command_id": command_id,
        "command_status": cmd["status"] if cmd else "not_found",
        "claimed_at": cmd["claimed_at"] if cmd else None,
        "result": dict(result) if result else None,
    }

@router.get("/api/commands/recent")
async def get_recent_commands():
    """List recent commands and their statuses."""
    # Return last 20 commands with results
```

Also replace ALL the existing stub action endpoints with wrappers that call `submit_command`:
```python
# Replace this:
@router.post("/api/actions/scan")
async def trigger_scan():
    return {"error": "cloud_mode", "message": "Must be done locally"}

# With this:
@router.post("/api/actions/scan")
async def trigger_scan():
    return await submit_command_internal("action", "scan", {})
```

Do the same for: `/api/actions/council`, `/api/actions/collect-data`, `/api/actions/collect-training`, `/api/actions/train-pipeline`, `/api/actions/score`, `/api/halt-trading`, `/api/resume-trading`.

---

## Task 6: Settings Editor Page

Create `frontend/src/pages/SettingsEditor.jsx` (or update existing `Settings.jsx`).

**Replace the current read-only settings display with an editable form:**
1. Load current effective config from `GET /api/config`
2. For each whitelisted setting, show an editable input (number, toggle, dropdown)
3. On change, submit via `POST /api/commands/submit` with `command_type: "config_change"`
4. Show pending/applied status for each setting
5. Show the override source (YAML default vs dashboard override)

**Layout:**
```
┌──────────────────────────────────────────────────┐
│ Settings                        [Reset to YAML]  │
├──────────────────────────────────────────────────┤
│ Trading                                          │
│   Max positions     [20]        ← dashboard      │
│   Enabled           [ON]        ← yaml default   │
│   Timeout (pullback) [7] days   ← dashboard      │
├──────────────────────────────────────────────────┤
│ Risk                                             │
│   Min risk %        [0.02]      ← yaml default   │
│   Max risk %        [0.05]      ← yaml default   │
├──────────────────────────────────────────────────┤
│ Model                                            │
│   Min conviction    [65]        ← yaml default   │
│   LLM enabled       [ON]        ← yaml default   │
│   Scan interval     [30] min    ← yaml default   │
└──────────────────────────────────────────────────┘
```

Remove the "Changes require local access" warning from the existing Settings page.

---

## Task 7: Log Viewer + Command Status on Dashboard

Add a lightweight log viewer and command status panel.

### Log Viewer
Create `frontend/src/pages/Logs.jsx` or add as a section to an existing page:
1. Fetch from `GET /api/logs/recent?level=INFO&limit=100`
2. Show timestamp, level (color-coded), source, message
3. Auto-refresh every 30 seconds
4. Filter by level (INFO, WARNING, ERROR, CRITICAL)
5. Filter by source (watch, scan, council, executor, etc.)

### Command Status
Add to the Dashboard main page (bottom section, above activity feed):
1. If any commands are pending, show a small "Command pending..." indicator
2. If a command completed, flash the result briefly
3. Link to full command history page

**Cloud API for logs:**
```python
@router.get("/api/logs/recent")
async def get_recent_logs(level: str = "INFO", limit: int = 100, source: str = None):
    """Return recent log entries synced from local machine."""
    # Query log_entries table from Render Postgres
```

### Local Log Capture
In `src/scheduler/watch.py`, add a log handler that writes structured entries to the `log_entries` SQLite table:

```python
class DBLogHandler(logging.Handler):
    """Captures log entries to SQLite for dashboard sync."""
    def emit(self, record):
        # Write to log_entries table
        # Only keep last 500 entries (prune on each write)
        # Only capture WARNING+ by default, INFO+ when debug mode on
```

---

## Task 8: Documentation Update (MANDATORY)

1. **AGENTS.md** — Verify ALL counts match reality
2. **CHANGELOG.md** — Add Sprint 4C entry:
```markdown
## Sprint 4C: Dashboard as Control Plane (YYYY-MM-DD)
- Added: Command queue architecture (pending_commands, command_results tables)
- Added: Bidirectional sync (cloud → local for commands, local → cloud for results)
- Added: 10 command types (scan, council, collect, train, halt, resume, close, settings, logs)
- Added: Config override system (dashboard settings take precedence over YAML)
- Added: Settings editor page (editable from dashboard)
- Added: Log viewer (structured logs synced to dashboard)
- Added: Command status display on dashboard
- Removed: "Must be done locally" stubs — all actions now work from dashboard
```

3. **docs/architecture.md** — Add command queue architecture section, new tables, new API endpoints
4. **ADR:** Create `docs/decisions/012-command-queue-architecture.md` documenting the pull-based pattern and why (no inbound connections to local machine)

---

## Final Verification

```bash
# 1. All tests pass
python -m pytest tests/ -x -q

# 2. Test count hasn't decreased
find tests -name "test_*.py" -exec grep -c "def test_" {} + | awk -F: '{s+=$2}END{print "Tests:", s}'

# 3. Frontend builds
cd frontend && npm run build && cd ..

# 4. No file over 400 lines
find src -name "*.py" ! -path "*__pycache__*" -exec sh -c 'lines=$(wc -l < "$1"); if [ "$lines" -gt 400 ]; then echo "VIOLATION: $1 ($lines lines)"; fi' _ {} \;

# 5. Command queue tables exist
python3 -c "
import sqlite3
conn = sqlite3.connect('data/halcyon.db')
for table in ['pending_commands', 'command_results', 'config_overrides', 'log_entries']:
    count = conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
    print(f'{table}: {count} rows')
"

# 6. Bidirectional sync works
# Submit a test command via cloud API, verify it appears locally within 60s
```

---

## Sprint Checklist

Paste the contents of `docs/sprint-checklist.md` here and complete every applicable item before marking this sprint done.

---

## Testing Requirements

Create `tests/test_command_queue.py` with ≥12 tests:
- Command submission creates pending record
- Expired commands are not executed
- Unknown command types return error
- Config override merges correctly with YAML
- Config whitelist prevents non-whitelisted keys
- Rate limiter rejects >10 commands/minute
- Command executor handles each command type
- Result truncation at 10KB
- Log handler captures entries to DB
- Pull_commands marks commands as claimed
- Duplicate command_id is rejected
- Full round-trip: submit → claim → execute → result
