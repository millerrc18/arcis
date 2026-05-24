# Arcis #105 Tier 1 Tools — Design Spec (REV 2)

## 1. Overview

Five composable Python-API + CLI tools that build on the v0.36.57 #104 foundation (`src/tools/_config.py`, `_safety.py`, `_execution_log.py`). Release target = **v0.36.62** atop v0.36.61 main.

| Tool | Purpose | Seam |
|------|---------|------|
| **DBQuery** | Read-only SQL query against test PG (5434) | psycopg2 |
| **LogTail** | Tail / filter `arcis.log` with multi-line awareness | filesystem |
| **CIInvestigate** | Pull + cache GitHub Actions run details | `gh` CLI |
| **SymbolFind** | Locate Python symbol definitions / references | `rg` CLI |
| **TradingState** | Snapshot of open positions + recent audit + GPU health | psycopg2 + SQLite fallback |

### Role in the broader roadmap

The per-tool subpackage layout (`src/tools/<name>/{__init__.py, __main__.py, core.py, ...}`), the markdown-CLI / dict-API dual-render pattern, and the **sub-module-when-needed pattern** (see §4.8) are inherited by:

- **#106 Tier 2 tools** — wear the full decorator stack (`@safe_op` + `@safety_window` + `@prod_guard`).
- **#107 Tier 3 orchestrators** (MorningCheck, EveningClose).
- **#108 specialized agents** — import tools as Python API.
- **#109 `arcis:operate` skill** — invokes tools via `python -m src.tools.<name>` subprocess + parses `--json`.
- **#111 periodic discipline** — calls TradingState + CIInvestigate via cron.

## 2. Architecture

### 2.1 Module layout (delta from current `src/tools/`)

```
src/tools/
  __init__.py                  (UNCHANGED — descriptive only)
  _config.py                   (UNCHANGED, #104)
  _safety.py                   (UNCHANGED, #104)
  _execution_log.py            (UNCHANGED, #104)
  _db.py                       (NEW — thin psycopg2 helper supporting read_only +
                                  isolation_level kwargs; no src.utils.db, no src.config)
  _cli_envelope.py             (NEW — shared --json error-envelope wrapper; see §4.6)
  dbquery/
    __init__.py | __main__.py | core.py
  logtail/
    __init__.py | __main__.py | core.py
  ciinvestigate/
    __init__.py | __main__.py | core.py
  symbolfind/
    __init__.py | __main__.py | core.py
  tradingstate/
    __init__.py | __main__.py | core.py | queries.py | render.py    (5 modules — see §4.8)

tests/tools/
  test_safe_op_integration.py    (UNCHANGED, keystone)
  test_db_helper.py              (NEW)
  test_dbquery_integration.py    (NEW)
  test_logtail_integration.py    (NEW)
  test_ciinvestigate_integration.py (NEW)
  test_symbolfind_integration.py (NEW)
  test_tradingstate_integration.py (NEW — covers Python API; created by Task 6)
  test_tradingstate_cli.py       (NEW — covers CLI + render; created by Task 7)

CHANGELOG.md                   (MODIFIED)
src/version.py                 (MODIFIED — v0.36.61 → v0.36.62)
tests/test_version.py          (MODIFIED — literal bump)
```

Net new files: 24 (was 22 in REV1; +1 for `_cli_envelope.py`, +2 for `tradingstate/queries.py` + `tradingstate/render.py`, +1 for `test_tradingstate_cli.py`, –1 because parity test is augment-not-create per known location).

### 2.2 Forbidden imports (reviewer grep-list)

Every file under `src/tools/<name>/` and `tests/tools/test_<name>_*.py` MUST NOT contain any of:

```
from src.config
import src.config
from src.utils.db
import src.utils.db
from src.schema.registry
import src.schema.registry
os.environ.get('DATABASE_URL'
os.getenv('DATABASE_URL'
load_dotenv
```

### 2.3 Shared psycopg2 helper (`src/tools/_db.py`)

```python
# Purpose: Thin psycopg2 context-manager helper for Tier-1+ tools.
# Called by: src/tools/dbquery/core.py, src/tools/tradingstate/core.py
# Calls: psycopg2.connect, psycopg2.extras.RealDictCursor
# Owns tables: none (cross-cutting)
# Config keys: pg.test_dsn (caller passes in)
# Tests: tests/tools/test_db_helper.py, tests/tools/test_config.py (parity)

from contextlib import contextmanager
import psycopg2, psycopg2.extras
from psycopg2.extensions import ISOLATION_LEVEL_REPEATABLE_READ

class DBHelperError(RuntimeError): pass

@contextmanager
def pg_connect(dsn: str, *, read_only: bool = False,
               isolation_level: str | None = None, timeout: int = 10,
               named_cursor: str | None = None):
    """Connect to PG via DSN, yield (conn, cursor).

    read_only=True             → conn.set_session(readonly=True) post-connect
                                  (PG enforces; belt-and-suspenders for the regex check).
    isolation_level='REPEATABLE READ' → conn.set_session(isolation_level=...) BEFORE
                                  cursor() yield. Caller gets a single consistent snapshot
                                  across multiple queries on the yielded cursor.
    named_cursor='<name>'      → server-side cursor (streamable; required for itersize
                                  to take effect — DBQuery uses this).
    Always uses RealDictCursor.
    Always sets connect_timeout. Always commits/closes via context manager.
    """
```

This helper does NOT couple to `cfg`, does not read `.env`, and does not import any other `src.*` module.

## 3. Per-tool design

### 3.1 DBQuery

**Purpose:** Execute read-only SELECT/WITH against test PG; return rows as list-of-dicts.

**Python API:**
```python
def query(sql: str, *, dsn: str | None = None, limit: int = 1000) -> list[dict]:
    ...
```

**CLI:** `python -m src.tools.dbquery "SELECT ..." [--limit 1000] [--json] [--dsn DSN]`

**Decorator stack:**
```python
@safe_op(name='dbquery', mutates=False)
@prod_guard(dsn_param='dsn')
def query(sql, *, dsn=None, limit=1000): ...
```

**Read-only enforcement (two layers):**
1. String layer: `re.match(r'^\s*(SELECT|WITH)\s', sql_stripped, re.IGNORECASE)` after stripping leading `--` comment lines — fail → `WriteNotPermittedError`.
2. Transaction layer: `pg_connect(..., read_only=True)`.

**Limit semantics (DA4):** DBQuery uses a **server-side named cursor** to avoid materializing the entire result set client-side, which prevents bandwidth/memory bombs for jsonb-heavy tables:
```python
with pg_connect(dsn, read_only=True, named_cursor='dbquery_stream') as (conn, cur):
    cur.itersize = limit + 1     # streamed chunk size from server
    cur.execute(sql)
    rows = cur.fetchmany(limit + 1)
    if len(rows) > limit:
        # signals 'more rows exist' — drop the sentinel, set truncated=True in metadata
        rows = rows[:limit]
        truncated = True
    else:
        truncated = False
```

**LIMIT clause NOT appended to user SQL.** The user's own `LIMIT` (if any) is respected verbatim; the tool's `limit` is applied via `fetchmany`. The Python API returns `list[dict]` only; the CLI markdown/JSON output includes a `(N rows, truncated=True/False)` footer.

**jsonb-row warning:** DBQuery does NOT page-size individual rows. A single jsonb column (e.g., `audit_reports.full_report`) can be MB-scale; `SELECT full_report FROM audit_reports LIMIT 1000` can pull gigabytes. The CLI `--help` text and module docstring MUST warn callers: *"To inspect jsonb fields, narrow the projection (`SELECT id, full_report->'summary' AS summary`) — do not blanket-select jsonb columns."*

**Error types:**
- `WriteNotPermittedError(ValueError)` — pre-connect, SQL fails regex.
- `DBQueryError(RuntimeError)` — wraps `psycopg2.Error`.

### 3.2 LogTail

**Purpose:** Tail the last N entries of `arcis.log` (multi-line aware).

**Python API:**
```python
def tail(*, lines: int = 100, log_path: Path | None = None,
         level: str | None = None, grep: str | None = None) -> list[str]:
    ...
```

**Open-time semantics + rotation handling (DA5):** LogTail's contract:

> *"LogTail opens the log file at invocation time and reads it backwards in a single pass. The file handle is held for the duration of the call. If the file is rotated, renamed, or truncated by NSSM (or any external rotator) DURING the read, the tool detects the size shrink via `os.fstat(handle).st_size` and raises `LogTailError('file rotated/truncated mid-read; retry')`. Callers should retry on this error; back-to-back retries yielding the same error indicate a busy rotation period and the caller should backoff."*

Implementation:
```python
with open(log_path, 'rb') as f:
    initial_size = os.fstat(f.fileno()).st_size
    # ... backward chunked read ...
    final_size = os.fstat(f.fileno()).st_size
    if final_size < initial_size:
        raise LogTailError('file rotated/truncated mid-read; retry')
```

**Decorator:** `@safe_op(name='logtail', mutates=False)` only.

**Error types:** `LogTailError(RuntimeError)` wraps FileNotFoundError, PermissionError, encoding errors, and the rotation-mid-read case.

All `open()` calls specify `encoding='utf-8', errors='replace'`.

Default `log_path = cfg.paths.logs_runtime / 'arcis.log'` (`C:/arcis/logs/arcis.log` — NSSM-managed). Do NOT inherit `src/main.py:319`'s CWD-relative dev default.

### 3.3 CIInvestigate

**Purpose:** Wrap `gh run view`. Cache COMPLETED runs, but **validate cache freshness against `updatedAt`** on every hit.

**Python API:**
```python
def investigate(run_id: int | str, *, repo: str | None = None,
                cache_dir: Path | None = None) -> dict: ...
```

**Cache semantics (DA3 — REVISED):**

> A completed CI run is **NOT immutable** under `gh run rerun`, which reuses the same run_id and mutates `conclusion`, `status`, `jobs`, and `updatedAt`. The cache must validate freshness on every hit.

Flow:
1. If `<cache_dir>/<run_id>.json` does NOT exist → fetch full payload via `gh run view <id> --json conclusion,status,displayTitle,headBranch,headSha,createdAt,updatedAt,jobs`; if `conclusion` is truthy, write cache atomically; return payload.
2. If cache exists → run **lightweight head-check**: `gh run view <id> --json status,conclusion,updatedAt`. If head `updatedAt` is newer than cached `updatedAt` OR head `status != 'completed'`, fetch full payload, atomic-rewrite cache (only if completed), return. Else return cached payload.
3. `--no-cache` skips step 2 entirely (forces full re-fetch).

**Atomic cache write contract (DA1 — CRITICAL):**

> All cache writes MUST be atomic. The implementation MUST serialize payload to `<run_id>.json.tmp` in the same directory, then call `os.replace('<run_id>.json.tmp', '<run_id>.json')`. `os.replace` is atomic on both POSIX and Windows (NTFS), eliminating the partial-write window. Ctrl-C between `write` and `replace` leaves the `.tmp` file behind (harmless; reaped on next write).

Implementation:
```python
tmp_path = cache_path.with_suffix('.json.tmp')
with open(tmp_path, 'w', encoding='utf-8') as f:
    json.dump(payload, f, indent=2, default=str)
    f.flush()
    os.fsync(f.fileno())          # durability before rename
os.replace(tmp_path, cache_path)  # atomic on Windows + POSIX
```

**Corrupt-cache recovery contract (DA1):**

> On `json.JSONDecodeError` reading an existing cache file, the tool MUST: (a) log a WARNING with the cache path + the decode-error message, (b) delete the corrupt cache file via `os.unlink(cache_path)`, (c) fall through to re-fetch as if cache did not exist. This is mandatory because two concurrent invocations (or a killed prior invocation) can leave a corrupt cache, and the tool MUST self-heal rather than perma-fail.

```python
try:
    with open(cache_path, encoding='utf-8') as f:
        cached = json.load(f)
except json.JSONDecodeError as e:
    logger.warning('corrupt cache %s: %s — deleting + refetching', cache_path, e)
    os.unlink(cache_path)
    cached = None  # fall through
```

**Cache convention:** `data/cache/ci-investigate/<run_id>.json` (going-forward standard for all Tier-1+ tool caches).

**Decorator:** `@safe_op(name='ciinvestigate', mutates=False)` only.

**Error types:** `CIInvestigateError(RuntimeError)` — gh missing, non-zero exit, JSON parse error from gh, run-not-found.

### 3.4 SymbolFind

Unchanged from REV1. **Python API:**
```python
def find(symbol: str, *, kind: str = 'any', path: Path | None = None) -> list[dict]: ...
```
Fails fast when `rg` missing (operator decision #8 stands). `subprocess.run(['rg','--json','--type','py', pattern, str(path)], ..., timeout=30)`.

### 3.5 TradingState

**Purpose:** Single-shot snapshot of current trading-day state. Reads PG (preferred) → falls back to SQLite.

**Sub-module layout (DA8):** TradingState splits into 5 modules within `src/tools/tradingstate/`:
- `__init__.py` — exports.
- `__main__.py` — argparse CLI (delegates to core + render).
- `core.py` — `state()` Python API + dataclasses + decorator stack. Target ≤300 LOC.
- `queries.py` — SQL string constants (PG variants + SQLite variants).
- `render.py` — markdown rendering (3 sections: Positions / Audit / GPU Health).

Rationale: a single core.py for TradingState would realistically reach 700–900 LOC for 3 PG queries + 3 SQLite-syntax duplicates + datetime arithmetic + pivot + 3-section markdown + JSON + argparse + error wrapping. Splitting keeps each file under 300 LOC and establishes the **sub-module-when-needed pattern** that Tier 2 inherits (§4.8).

**Python API (`state()` in core.py):**
```python
def state(*, dsn: str | None = None, sqlite_path: Path | None = None) -> dict:
    """
    Schema:
        {
          'as_of_et': ISO-8601 timestamp,
          'open_positions': [{'ticker','trade_id','source','status','entry_price',
                              'entry_time','thesis_text','quarantined'}, ...],
          'most_recent_audit': {'audit_id','created_at','overall_assessment','stale': bool} | None,
          'gpu_health': {'ollama_ok': bool|None, 'training_ok': bool|None, 'metric_date': YYYY-MM-DD},
          'data_source': 'pg' | 'sqlite_fallback',
        }
    """
```

**Snapshot-consistency contract (DA2):** All 3 queries execute against a **single connection** opened with `isolation_level='REPEATABLE READ'`. This guarantees the open_positions, audit, and gpu_health rows reflect a single point-in-time view of the database, even if the watch loop is concurrently writing.

Implementation:
```python
from src.tools._db import pg_connect
from src.tools.tradingstate.queries import (
    OPEN_POSITIONS_PG, RECENT_AUDIT_PG, GPU_METRICS_PG,
    OPEN_POSITIONS_SQLITE, RECENT_AUDIT_SQLITE, GPU_METRICS_SQLITE,
)

with pg_connect(dsn, read_only=True, isolation_level='REPEATABLE READ') as (conn, cur):
    cur.execute(OPEN_POSITIONS_PG)
    positions = cur.fetchall()
    cur.execute(RECENT_AUDIT_PG)
    audit = cur.fetchone()
    cur.execute(GPU_METRICS_PG)
    metrics_rows = cur.fetchall()
```

**Why REPEATABLE READ and not SERIALIZABLE:** REPEATABLE READ is sufficient for read-only snapshots — it pins the snapshot at the first statement and guarantees consistent reads across subsequent statements. SERIALIZABLE adds serialization-failure retry semantics, unnecessary for a read-only operation. Documented in the `_db.py` docstring + here.

**Output dict key naming (UNCHANGED from REV1):**
- `entry_time` (aliased in SQL: `actual_entry_time AS entry_time`) — semantic-over-literal.
- `overall_assessment` (verbatim from column) — literal-as-semantic.

**Queries (in `queries.py`):**
```python
# queries.py
OPEN_POSITIONS_PG = """
SELECT st.trade_id, st.ticker, st.source, st.status,
       st.entry_price,
       st.actual_entry_time AS entry_time,
       st.quarantined,
       r.thesis_text
FROM shadow_trades st
LEFT JOIN recommendations r ON r.recommendation_id = st.recommendation_id
WHERE st.source = 'live'
  AND st.status IN ('open', 'exit_pending')
  AND COALESCE(st.quarantined, 0) = 0
ORDER BY st.actual_entry_time DESC
"""

RECENT_AUDIT_PG = """
SELECT audit_id, created_at, overall_assessment
FROM audit_reports
ORDER BY created_at DESC
LIMIT 1
"""

GPU_METRICS_PG = """
SELECT metric_name, metric_value
FROM schedule_metrics
WHERE metric_date = CURRENT_DATE
"""

OPEN_POSITIONS_SQLITE = OPEN_POSITIONS_PG  # identical (LEFT JOIN, COALESCE, CURRENT_DATE all valid)
RECENT_AUDIT_SQLITE = RECENT_AUDIT_PG
GPU_METRICS_SQLITE = GPU_METRICS_PG
```

If SQLite syntax diverges in practice during implementation, `queries.py` is the single place to fork them.

**SQLite fallback:** On `psycopg2.OperationalError`, try `sqlite3.connect(cfg.paths.db_canonical, timeout=5)`. SQLite has no REPEATABLE READ analog — its default is snapshot-isolation-equivalent via SQLite's MVCC, which is acceptable. Set `data_source = 'sqlite_fallback'`. Both unavailable → `TradingStateError`.

**Pivot:** `metrics = {row['metric_name']: row['metric_value'] for row in metrics_rows}`. `ollama_ok = bool(metrics['gpu_health_ollama_ok']) if 'gpu_health_ollama_ok' in metrics else None`. Missing rows yield `None`, NEVER `False`.

**Render (in `render.py`):**
```python
def render_markdown(snapshot: dict) -> str: ...
# 3 sections; each section is its own internal function for testability.
```

**Decorator stack (on `core.state`):**
```python
@safe_op(name='tradingstate', mutates=False)
@prod_guard(dsn_param='dsn')
def state(*, dsn=None, sqlite_path=None): ...
```

## 4. Cross-cutting standards

### 4.1 Module header (every new .py file)
Six-line `#`-comment header (Purpose / Called by / Calls / Owns tables / Config keys / Tests).

### 4.2 Encoding
Every `open()` specifies `encoding='utf-8'`; log/stderr reads also pass `errors='replace'`.

### 4.3 Logging
One `_execution_log.write_event(...)` per invocation, implicitly via `@safe_op`.

### 4.4 Sanitization
`_execution_log.write_event` already redacts DSN passwords. DBQuery additionally truncates `params['sql']` to 200 chars at the boundary.

### 4.5 Sibling-search discipline (test-encoded)
Parity test for `prod_dsn_signatures`: Task 1 first runs `grep -rn 'prod_dsn_signatures' tests/tools/`. Expected hit is `tests/tools/test_config.py:88-99` (`test_load_arcis_config_pg_signatures_match_prod_guard`). If present + adequate, no new file is added. If absent or weaker, Task 1 creates `tests/tools/test_prod_signature_parity.py` with the canonical assertion.

### 4.6 CLI conventions + JSON error envelope (DA6)

Per operator decision #4: argparse; long-form flags only; `--json` boolean toggle; help text short, sentence-case, no trailing period.

**Error-output schema when `--json` is set:** Every tool's `__main__.py` MUST wrap the core call in `src.tools._cli_envelope.run_cli(...)` which on exception emits a JSON envelope to stdout + exits 1:

```python
# Envelope schema (stdout when --json AND exception raised):
{
  "error": {
    "type": "<ExceptionClassName>",     # e.g., "WriteNotPermittedError"
    "message": "<str(e)>",              # exception message verbatim
    "tool": "<tool_name>"               # e.g., "dbquery"
  }
}
```

Without `--json`: traceback prints to stderr as usual, exit code 1 (argparse / Python default). This dual-mode design serves both #109 arcis:operate (consumes `--json` programmatically) and interactive operator use (raw traceback is more debuggable).

**Shared implementation in `src/tools/_cli_envelope.py`:**
```python
def run_cli(tool_name: str, fn, args_namespace, *, json_mode: bool):
    """Invoke fn(**vars(args_namespace)), render markdown or JSON, handle errors.

    If json_mode and fn raises: print envelope to stdout, sys.exit(1).
    If not json_mode and fn raises: re-raise (Python default traceback).
    Else: print result + sys.exit(0).
    """
```

Each tool's `__main__.py` delegates to this helper. Each tool's integration test asserts: `(f) tool raises X under --json → subprocess stdout matches envelope schema, exit code == 1`.

### 4.7 Decorator contract (NEW per DA7)

The decorator stack on every Tier-1+ tool function obeys an explicit four-point contract:

**(a) Decorator order:** `@safe_op` is the OUTER decorator (closest to the function name visually, listed FIRST in the `@decorator` stack); `@prod_guard` (and Tier-2's `@safety_window`) is INNER:
```python
@safe_op(name='dbquery', mutates=False)   # OUTER — wraps everything below
@prod_guard(dsn_param='dsn')              # INNER
def query(...): ...
```

**(b) Per-guard event emission:** Each guard writes its OWN `_execution_log` event BEFORE raising its specific exception. `@prod_guard` writes a `'prod_guard_block'` event before raising `ProdGuardError`. `@safety_window` (Tier-2) writes `'safety_window_block'` before raising `SafetyWindowError`.

**(c) `@safe_op` does NOT double-log:** `@safe_op`'s exception handler MUST catch `SafetyError` subclasses (`ProdGuardError`, `SafetyWindowError`) and re-raise them WITHOUT writing a duplicate `'error'` event. This preserves `'prod_guard_block'` and `'safety_window_block'` as the canonical terminal-state events for those exception classes. Generic `Exception` (anything that is NOT a `SafetyError` subclass) IS logged as `'error'` by `@safe_op` before propagating.

**(d) Reference implementation:** `src/simulation/lifecycle/prod_guard.py` + `src/tools/_safety.py:144-156` confirm this layering — Task 1 grep-verifies BEFORE Tasks 2/6 dispatch (single grep: `grep -n 'isinstance.*SafetyError\|SafetyError.*raise' src/tools/_safety.py` — verify that the exception classification skips logging for SafetyError subclasses).

Test assertion pattern (every integration test):
```python
# DBQuery + TradingState
assert events[-1]['event_type'] == 'prod_guard_block'  # NOT 'error'
assert events[-1]['tool'] == 'dbquery'
assert len([e for e in events if e['event_type'] == 'error']) == 0  # no duplicate
```

### 4.8 Sub-module-when-needed pattern (NEW per DA8)

**Default structure (Tier 1 minimum):** `<tool>/{__init__.py, __main__.py, core.py}` for tools whose realistic LOC budget for core.py is ≤500.

**Sub-module structure (when needed):** Tools that would exceed ≤500 LOC for core.py split into:
- `core.py` — Python API (function signatures, decorator stack, dataclasses). Target ≤300 LOC.
- `queries.py` — SQL constants / external-command argument templates.
- `render.py` — markdown / human-output rendering, with one function per section.
- (Optional Tier-2) `validators.py` — input-validation helpers for mutating tools.
- (Optional Tier-2) `executors.py` — write-path helpers, separated from read-path.

**Rule:** Split when the realistic LOC budget would exceed ≤500 for core.py. **TradingState splits today** because its 3 PG + 3 SQLite queries + datetime arithmetic + 3-section markdown + JSON serialization realistically push past 500 LOC. **DBQuery / LogTail / CIInvestigate / SymbolFind do NOT split** in this PR — their cores fit under 500. Tier 2 ShadowClose, PromoteModel, Postmortem WILL split.

The `__main__.py` always remains small (argparse + dispatch to core + render).

### 4.9 Network discipline
All subprocess calls construct DSNs with `127.0.0.1`, never `localhost`.

## 5. Test strategy

### 5.1 Per-tool boundary-touch integration test
Each tool has `tests/tools/test_<name>_integration.py` modeled on `test_safe_op_integration.py`:
- `tmp_path` for log isolation.
- Real seam (real `127.0.0.1:5434` / real file / real `gh` / real `rg`).
- Asserts on OUTPUT contract; never on `mock.assert_called_with(...)`.
- Verify-by-mutation: each test has a deliberate negative-control assertion ("if X were broken, this assertion would catch it").

### 5.2 Vacuous-test guard
For each test, the author records in a comment: "this test fails when <specific implementation line> is deleted/changed." Reviewer checks.

### 5.3 Tool-specific test additions (REV2)

**DBQuery (`test_dbquery_integration.py`):** Adds assertion that under `--json` with a malformed SELECT, subprocess stdout matches the envelope schema, exit code 1. Adds assertion that `limit=10` with a 100-row fixture returns exactly 10 rows + `truncated=True` in the markdown footer.

**LogTail (`test_logtail_integration.py`):** Adds **rotation-mid-read** test: fixture creates a 200KB log file → opens it in a background thread via the tool's tail() → main thread truncates the file mid-read (via `os.truncate(path, 0)` while the read is in flight) → assert `LogTailError('file rotated/truncated mid-read; retry')` is raised. Synchronization via `threading.Event` — set after the tool opens the handle but before completion. (If timing is hard to achieve reliably, use a fixture that calls `os.fstat` monkey-patched to return a smaller size on the second invocation — both forms verify the contract.)

**CIInvestigate (`test_ciinvestigate_integration.py`):**
- **Concurrent-writers test (DA1):** Spawn 2 subprocess invocations racing on the same `run_id` against an in-memory fixture that simulates `gh` returning a completed payload (monkey-patched subprocess.run with a 50ms artificial delay). Assert the cache file is valid JSON after both complete + no `.tmp` artifacts remain.
- **Corrupt-cache recovery test (DA1):** Pre-write a corrupt cache file (`{"conclusion": "success"` — truncated, no closing brace) → call `investigate(run_id)` → assert the corrupt file is deleted, the tool re-fetches via gh, and the new cache file parses cleanly.
- **Rerun-invalidation test (DA3):** Pre-write a cached payload with `updatedAt=T0` and `conclusion='failure'`. Monkey-patch subprocess.run so that `gh run view --json status,conclusion,updatedAt` returns `updatedAt=T1` (T1 > T0) and `conclusion='success'`; the full-payload call returns the success body. Call `investigate(run_id)` → assert the returned dict has `conclusion='success'` and the cache file on disk has been atomic-replaced with the success body.
- Existing assertions stand: in-progress payload not cached; `--no-cache` forces re-fetch; gh-missing raises CIInvestigateError; --json error envelope under failure.

**TradingState (`test_tradingstate_integration.py` + `test_tradingstate_cli.py`):**
- **Snapshot-consistency-across-3-queries test (DA2):** Real 127.0.0.1:5434. Fixture inserts initial state (1 open position, 1 audit, 2 GPU metrics). Spawn a background-thread concurrent writer that, after a 50ms delay, mutates `shadow_trades` (closes the open position) and inserts a new audit. Call `state(dsn=...)` from the main thread. Assert the returned dict shows the position as STILL OPEN (proving the REPEATABLE READ snapshot was pinned at the first query). Synchronization via `threading.Event` to ensure the writer fires AFTER the first query but BEFORE the second.
- Existing assertions stand (open positions excluded for closed/quarantined/paper; audit stale flag; metrics None vs False distinction; data_source pg/sqlite_fallback; prod_guard_block; JSON envelope on --json error).
- The CLI test in `test_tradingstate_cli.py` subprocess-invokes `python -m src.tools.tradingstate --json` against a fixture-loaded PG and asserts the markdown 3-section structure (without --json) + the JSON shape (with --json) + the error envelope (under a forced failure, e.g., bad DSN).

### 5.4 `_db.py` test (`test_db_helper.py`)
- RealDictCursor default behavior.
- `read_only=True` triggers ReadOnlySqlTransaction on INSERT.
- `isolation_level='REPEATABLE READ'` triggers REPEATABLE READ on connection (verify via `SHOW transaction_isolation`).
- `named_cursor='foo'` yields a streamable server-side cursor.
- `timeout=1` against dead port raises OperationalError within ~1s.

## 6. CHANGELOG sketch (v0.36.62)

```
## v0.36.62 — Tier 1 Tools (#105)

### Added
- Five composable tools building on the #104 (v0.36.57) foundation:
  - `src/tools/dbquery/` — read-only SQL query (server-side cursor streaming for jsonb safety)
  - `src/tools/logtail/` — multi-line-aware tail with NSSM-rotation-safe semantics
  - `src/tools/ciinvestigate/` — `gh run view` wrapper with atomic-write cache +
     updatedAt-validated freshness on cache hit (`gh run rerun` correctness)
  - `src/tools/symbolfind/` — `rg`-backed Python symbol lookup
  - `src/tools/tradingstate/` — open-positions + audit + GPU-health snapshot in
     REPEATABLE READ for cross-query consistency
- Each tool ships as a per-tool subpackage callable as both Python API and CLI
  (`python -m src.tools.<name>`).
- TradingState introduces the sub-module-when-needed pattern (core/queries/render).
  Tier 2 tools inherit this.
- `src/tools/_db.py` — thin psycopg2 helper supporting read_only +
  isolation_level + named_cursor kwargs; does NOT couple to src.config / src.utils.db.
- `src/tools/_cli_envelope.py` — shared --json error envelope wrapper.
- New tool-cache convention: `data/cache/<tool-name>/`. CIInvestigate writes
  `<run_id>.json` atomically (tempfile + os.replace) for completed runs.
- Parity test enforces `cfg.pg.prod_dsn_signatures == prod_guard._PROD_SIGNATURES`.

### CLI conventions established for Tier 1+ tools
- argparse, long-form flags, `--json` boolean toggle (matches `cto-report`).
- Under `--json`, errors are emitted as a JSON envelope to stdout + exit 1;
  without `--json`, traceback prints to stderr as usual.

### Decorator contract (documented in spec §4.7)
- `@safe_op` is the OUTER decorator; `@prod_guard` is INNER.
- Each guard writes its own terminal-state event before raising;
  `@safe_op` does NOT double-log SafetyError subclasses.
```

## 7. Design decisions (rationale-summary)

Eleven non-obvious decisions, full record in `design_decisions[]`. Decision 5 revised per DA3 (cache validates updatedAt on hit). New decisions 12–13 added for atomic cache writes (DA1) and snapshot consistency (DA2).

---

## Design Decisions Log

| # | Decision | Rationale (short) | Reversibility |
|---|----------|-------------------|---------------|
| ? | Add src/tools/_db.py (single contextmanager) rather than inlining psycopg2 pe... | DBQuery and TradingState both need RealDictCursor + connect_timeout + context-manager discipline. Inlining duplicates boilerplate. REV2 adds two kw... | cheap |
| ? | DBQuery wears @prod_guard despite being read-only | Operator-confirmed. Three reasons: (a) defense in depth before connection attempt; (b) establishes the pattern for Tier-2 siblings; (c) zero runtim... | cheap |
| ? | Per-tool subpackage src/tools/<name>/{__init__.py, __main__.py, core.py, ...}... | Tier 2/3 tools grow multi-module. Establishing the subpackage shape at Tier 1 means Tier 2 inherits the layout. __main__.py gives uniform `python -... | expensive once #109 hardcodes the calling convention |
| ? | Markdown CLI output is default; --json flag overrides; Python API returns nat... | Operator-confirmed dual-render. REV2 adds the error-envelope schema (DA6) because #109 arcis:operate subprocess-parses --json output — without an e... | cheap — envelope schema is centralized |
| ? | CIInvestigate cache key = run_id; cache validates updatedAt on hit (REV2 — DA... | REV1 claimed CI runs are immutable — DA3 corrected: `gh run rerun` reuses run_id and mutates updatedAt + conclusion + jobs. REV2 cache flow: (1) ca... | cheap — cache files deletable |
| ? | TradingState reads shadow_trades (NOT Alpaca API) for open positions | Operator-confirmed. Alpaca path requires .env (forbidden coupling). shadow_trades is the local source-of-truth maintained by the reconciler. | cheap |
| ? | schedule_metrics pivot in Python (not SQL); None preserved for absent metrics | Operator-confirmed — schedule_metrics is row-per-metric. Python pivot is one line and self-documenting. Missing rows yield None (not False) — disti... | cheap |
| ? | SymbolFind fails fast when rg is missing (no pure-Python fallback) | rg is already a system dependency (feature-dev skill uses it). Silent fallback would mask env issues and create divergent perf. Fail-fast with reme... | cheap — could add --fallback-python opt-in |
| ? | Parity test for prod_dsn_signatures augments existing tests/tools/test_config... | Operator-confirmed. Single locus for the invariant avoids drift risk between duplicate assertions. | irreversible at the assertion level |
| ? | TradingState SQL aliases `actual_entry_time AS entry_time`; output dict key i... | F3 fix. shadow_trades has actual_entry_time but no opened_at. Operator's mental model = fill time, sourced from actual_entry_time. Output key is `e... | cheap |
| ? | TradingState audit dict key `overall_assessment` matches column name verbatim... | F4 fix. audit_reports.overall_assessment is the column; overall_verdict is the phantom that burned REV1 reviewers. Output key matches column for gr... | irreversible (locks column-name-as-key) |
| ? | TradingState wraps its 3 queries in a single connection with isolation_level=... | TradingState is a 'snapshot' tool by name. Without explicit isolation, the 3 sequential queries can observe interleaved writes from the watch loop ... | cheap — change one kwarg |
| ? | CIInvestigate cache writes are atomic via tempfile + os.replace; corrupt cach... | Two concurrent CIInvestigate invocations (e.g., two parallel agents debugging the same run) can race on the same cache file. A naive `open(path, 'w... | cheap |


---

## Known Considerations (devils-advocate minor findings, not blocking)

These were surfaced during adversarial review but ruled minor — documented here for future tooling work and operator awareness.

| # | Concern | Note |
|---|---------|------|
| KC1 | Verify-by-mutation is honor-system at design-time, not CI-enforced | Sufficient for Tier 1. If Tier 2+ surfaces a vacuous test that slipped through, escalate to `mutmut` integration in CI (gates `src/tools/` paths only). |
| KC2 | DBQuery read-only does NOT block resource-exhaustion SELECTs (`pg_sleep`, `pg_read_file`, jsonb DoS via large `audit_reports.full_report`) | Test PG (5434) is operator-controlled, blast radius bounded. Operator MUST treat DBQuery as a privileged tool against trusted PG only. PII in CLI params (`thesis_text`, `gh` JSON author emails) is persisted to `tool-execution.log` without redaction — review log retention before sharing externally. |
| KC3 | Spec section 7 enumerates 13 decisions; ensure body references stay in sync as decisions are added in future revisions | Mechanical drift risk — Tier 2 spec inheriting this template should add a CI lint that counts decisions in body vs `design_decisions.json`. |
| KC4 | TradingState has no operator-verified markdown exemplar | First-render layout review happens at PR time. If operator demands layout changes, follow-up v0.36.63 may be needed. Spec section 3.5 should be extended with an exemplar block during implementation Task 6. |

(Per devils-advocate review pass — see `arcis:design-devils-advocate` invocation 2026-05-24.)
