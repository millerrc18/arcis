# Sprint: Grafana Cloud Loki MVP — Centralized Log Aggregation

**Branch:** `feat/grafana-observability`
**Priority:** HIGH — watch loop crashes silently with no traceback; need centralized logging
**Spec:** `docs/sprints/sprint-grafana-observability-mvp.md`
**Estimated time:** 1-2 hours

---

## Pre-flight

- [ ] Read MASTER.md (root)
- [ ] Read `docs/sprints/sprint-grafana-observability-mvp.md` (full spec + Ralph loop findings)
- [ ] Read `src/log_config.py` — current logging: `StructuredFormatter` appends `|ctx:{json}`, console + rotating file handlers
- [ ] Read `src/config/__init__.py` — config loads from `config/settings.local.yaml` + `.env` via dotenv
- [ ] Run existing tests: `python -m pytest tests/ -x -q` — must pass before starting
- [ ] File size check: no src/ file > 400 lines, no function > 60 lines

---

## Critical Context

### Config architecture
- `config/settings.local.yaml` — non-secret YAML config (gitignored)
- `.env` — secrets via dotenv (API keys, tokens)
- `src/config/__init__.py` → `load_config()` returns merged dict

### Existing structured logging pattern
The codebase already uses `extra={"ctx": {"event": "...", "ticker": "...", ...}}` on many log lines. The `StructuredFormatter` in `src/log_config.py` reads `record.ctx` and appends `|ctx:{json}` to the message.

**DO NOT introduce a new `extra={"tags": {...}}` key.** The Loki handler must read from the existing `ctx` dict and extract labels from it. This is a zero-touch integration — most key events already have structured ctx.

### Grafana Cloud credentials
- Loki push URL: `https://logs-prod-042.grafana.net/loki/api/v1/push`
- User ID: `1553293`
- Token: stored in `.env` as `GRAFANA_LOKI_TOKEN`

---

## Task 1: Add Grafana config section (2 files)

**File:** `config/settings.example.yaml` — append to end:

```yaml
# ── Observability ──────────────────────────────────────────────────
observability:
  grafana:
    enabled: false  # Set true in settings.local.yaml after configuring credentials
    loki_url: "https://logs-prod-042.grafana.net/loki/api/v1/push"
    loki_user: "1553293"
    # Token goes in .env as GRAFANA_LOKI_TOKEN
```

**File:** `.env.example` — if this file exists, append: `# GRAFANA_LOKI_TOKEN=glc_...`
If `.env.example` does not exist, skip — do not create it.

---

## Task 2: Create `src/observability/loki_handler.py`

Create `src/observability/__init__.py` (empty file).

Create `src/observability/loki_handler.py` with these components:

### 2a: `DedupFilter` class

```python
class DedupFilter(logging.Filter):
    """Suppress duplicate log messages within a time window.
    
    Prevents noisy repeated messages (e.g., '[SCHEMA] Created/verified 53 tables')
    from consuming Grafana Cloud quota. Attached to Loki handler only —
    file/console logging is unaffected.
    """
    def __init__(self, window_seconds: int = 60):
        super().__init__()
        self._seen: dict[str, float] = {}
        self._window = window_seconds

    def filter(self, record: logging.LogRecord) -> bool:
        import time
        key = f"{record.name}:{record.getMessage()}"
        now = time.time()
        if key in self._seen and (now - self._seen[key]) < self._window:
            return False
        self._seen[key] = now
        # Prune stale entries to prevent unbounded growth
        if len(self._seen) > 1000:
            cutoff = now - self._window
            self._seen = {k: v for k, v in self._seen.items() if v > cutoff}
        return True
```

### 2b: `LokiHandler` class — raw HTTP handler (NO external dependency)

**Why not python-logging-loki:** The package was last released in 2020 (v0.3.1), is untested on Python 3.12+, and uses `extra["tags"]` which conflicts with our existing `extra["ctx"]` pattern. A raw handler is ~40 lines, zero dependency risk, and reads our `ctx` natively.

```python
class LokiHandler(logging.Handler):
    """Ships log records to Grafana Cloud Loki via HTTP push.
    
    Extracts 'event' and 'ticker' from the existing record.ctx dict
    (set via extra={"ctx": {...}}) and promotes them to Loki labels
    for efficient querying in Grafana. All other ctx data is included
    in the log line text via StructuredFormatter.
    
    Batches records and flushes every flush_interval seconds or
    flush_size records, whichever comes first. Runs flush in a
    daemon thread. Never raises — silently drops on failure.
    """
```

Requirements for `LokiHandler`:
- Constructor args: `url: str, user: str, token: str, flush_interval: float = 5.0, flush_size: int = 50`
- Stores auth as `(user, token)` tuple for HTTP Basic Auth
- Internal `_buffer: list` guarded by `threading.Lock`
- `emit(record)` appends `(record.created, self.format(record), record.levelname, getattr(record, 'ctx', {}))` to `_buffer`. If `len(_buffer) >= flush_size`, triggers `_schedule_flush()`
- A `threading.Timer` daemon thread calls `_flush()` every `flush_interval` seconds. Timer restarts after each flush.
- `_flush()` method:
  - Acquire lock, swap `_buffer` with `[]`, release lock
  - If empty batch, return immediately
  - Group records by `(level, event, ticker)` into Loki streams
  - Extract `event` and `ticker` from the saved ctx dict. If ctx is missing or empty, use empty strings (omit labels)
  - Build payload:
    ```json
    {
      "streams": [
        {
          "stream": {
            "application": "arcis",
            "host": "<platform.node()>",
            "level": "ERROR",
            "event": "exit_failed",
            "ticker": "GOOGL"
          },
          "values": [
            ["<nanosecond_timestamp>", "<formatted log line>"],
            ...
          ]
        }
      ]
    }
    ```
  - Nanosecond timestamp: `str(int(created * 1e9))`
  - Only include `event` and `ticker` in stream labels if they are non-empty strings
  - POST to `self.url` with `auth=self._auth, timeout=5, headers={"Content-Type": "application/json"}`
  - On ANY exception: `print(f"[LOKI] Flush failed: {exc}", file=sys.stderr)` — use print to stderr, NOT logger (avoids infinite recursion). Drop the batch and continue.

### 2c: `setup_loki_handler(config: dict) -> logging.Handler | None`

```python
def setup_loki_handler(config: dict) -> logging.Handler | None:
    """Create a non-blocking Loki handler from config.
    
    Returns a QueueHandler wrapping LokiHandler, or None if disabled/misconfigured.
    Uses threading.Queue (NOT multiprocessing.Queue) for Windows compatibility.
    Queue capped at 10,000 records to prevent OOM during Grafana outages.
    """
```

Implementation steps (follow exactly):
1. Read `grafana = config.get("observability", {}).get("grafana", {})`
2. If not `grafana.get("enabled")`, return None
3. Read token from `os.environ.get("GRAFANA_LOKI_TOKEN")` — if missing or empty, log warning, return None
4. Read `loki_url` and `loki_user` from grafana dict — if either missing, log warning, return None
5. Create `loki_handler = LokiHandler(url=loki_url, user=str(loki_user), token=token)`
6. Import `StructuredFormatter` from `src.log_config` and set it as `loki_handler`'s formatter: `loki_handler.setFormatter(StructuredFormatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s"))`
7. Attach `DedupFilter()` to `loki_handler`: `loki_handler.addFilter(DedupFilter())`
8. Create `from queue import Queue` → `q = Queue(maxsize=10000)` — **MUST be `queue.Queue` (threading), NOT `multiprocessing.Queue`**
9. Create `queue_handler = logging.handlers.QueueHandler(q)`
10. Create `listener = logging.handlers.QueueListener(q, loki_handler, respect_handler_level=True)`
11. **`listener.start()`** — do not forget this line, the listener does nothing without it
12. Store listener reference to prevent garbage collection: `queue_handler._loki_listener = listener`
13. Set `queue_handler.setLevel(logging.INFO)` — **never ship DEBUG to Loki**
14. Return `queue_handler`

**Docstring:**
```
Called by: src/log_config.py
Calls: requests (stdlib: threading, queue, logging.handlers)
Owns tables: none
Config keys: observability.grafana.enabled, loki_url, loki_user
Env vars: GRAFANA_LOKI_TOKEN
Tests: tests/test_loki_handler.py
```

---

## Task 3: Integrate into `src/log_config.py`

At the **end** of `setup_logging()`, after the file handler block, add:

```python
    # Grafana Cloud Loki handler (non-blocking, ships logs to cloud)
    try:
        from src.config import load_config
        from src.observability.loki_handler import setup_loki_handler
        loki_handler = setup_loki_handler(load_config())
        if loki_handler:
            root.addHandler(loki_handler)
            logging.getLogger(__name__).info(
                "[OBSERVABILITY] Grafana Loki handler active — shipping logs to cloud"
            )
    except Exception as exc:
        # Never let observability setup crash the application
        logging.getLogger(__name__).warning(
            "[OBSERVABILITY] Loki setup failed (non-fatal): %s", exc
        )
```

**Constraint:** This entire block is wrapped in try/except. Loki setup must NEVER prevent the watch loop from starting. If load_config() fails, if the import fails, if anything fails — the watch loop starts normally without Loki.

---

## Task 4: Add `ctx` to log events that are missing it

Many key events ALREADY have `extra={"ctx": {"event": "...", ...}}`. Read each file to verify before editing. Do NOT modify lines that already have ctx.

**Only add ctx to events that don't have it yet.** Likely candidates (verify by reading each file):

| File | Log line to find | ctx to add |
|------|-----------------|------------|
| `src/shadow_trading/executor.py` | Entry order placed / trade opened (search for `[EXECUTOR]` near order submission) | `extra={"ctx": {"event": "trade_open", "ticker": ticker}}` |
| `src/shadow_trading/executor.py` | Bracket placed (search for `[BRACKET]` near bracket order creation) | `extra={"ctx": {"event": "bracket_placed", "ticker": ticker}}` |
| `src/scheduler/overnight.py` | Overnight collection complete (search for the final summary log) | `extra={"ctx": {"event": "overnight_complete"}}` |
| `src/shadow_trading/reconcile.py` | Stale trade auto-closed (search for `[RECONCILE]` + `closed` or `stale`) | `extra={"ctx": {"event": "stale_close", "ticker": ticker}}` |

**Events that ALREADY have ctx (verify, do NOT touch):**
- `executor.py` — `exit_failed`, `exit_success` already have full ctx dicts
- `watch.py` — `scan_summary` already has full ctx dict with scan_number, universe, etc.

**Rule:** Read each file BEFORE editing. If the log line already has `extra={"ctx": {...}}`, skip it. If in doubt, don't add — fewer clean labels are better than wrong labels. It is better to tag 3 events correctly than 10 events badly.

---

## Task 5: Verify `requests` in requirements.txt

- `requests` should already be in requirements.txt — verify it is present
- Do NOT add `python-logging-loki` — we are not using it
- If `requests` is missing, add `requests>=2.28`

---

## Task 6: Tests

**File:** `tests/test_loki_handler.py`

5 tests:

```python
"""Tests for Grafana Loki log handler.

Tests handler configuration, DedupFilter, and error paths.
No network calls — all tests are offline.
"""
import logging
import time
import pytest
from src.observability.loki_handler import setup_loki_handler, DedupFilter


def test_handler_returns_none_when_disabled():
    """Config has enabled: false."""
    config = {"observability": {"grafana": {"enabled": False}}}
    assert setup_loki_handler(config) is None


def test_handler_returns_none_when_config_missing():
    """No observability section at all."""
    assert setup_loki_handler({}) is None


def test_handler_returns_none_when_token_missing(monkeypatch):
    """Config enabled but GRAFANA_LOKI_TOKEN env var not set."""
    monkeypatch.delenv("GRAFANA_LOKI_TOKEN", raising=False)
    config = {"observability": {"grafana": {
        "enabled": True, "loki_url": "http://fake", "loki_user": "123"
    }}}
    assert setup_loki_handler(config) is None


def test_dedup_filter_suppresses_duplicates():
    """Same message within window is filtered."""
    f = DedupFilter(window_seconds=60)
    record = logging.LogRecord("test", logging.INFO, "", 0, "hello", (), None)
    assert f.filter(record) is True
    assert f.filter(record) is False  # duplicate suppressed


def test_dedup_filter_allows_after_window():
    """Message allowed again after window expires."""
    f = DedupFilter(window_seconds=0.1)
    record = logging.LogRecord("test", logging.INFO, "", 0, "hello", (), None)
    assert f.filter(record) is True
    time.sleep(0.15)
    assert f.filter(record) is True  # window expired
```

Do NOT test actual Loki connectivity — no network calls in tests.

---

## Task 7: Update docs

**MASTER.md Section 2** — update volatile counts:
- Research docs: update count if changed
- Add to infrastructure/tools section: "Grafana Cloud (free tier, $0/mo) for centralized log aggregation via Loki"

**CHANGELOG.md** — add entry under next version:
```
### Added
- Grafana Cloud Loki integration for centralized log aggregation (SD#40)
- DedupFilter suppresses noisy repeated log messages
- Structured ctx labels promoted to Loki labels for efficient querying
```

---

## Constraints Summary

- **Zero new pip dependencies** — only `requests` (already present) and stdlib
- **Zero changes to existing log lines that already have ctx** — additive only
- **DO NOT use `extra={"tags": {...}}`** — use existing `extra={"ctx": {...}}` pattern
- **`queue.Queue` (threading), NOT `multiprocessing.Queue`** — Windows safety
- **`Queue(maxsize=10000)`** — prevents OOM during Grafana Cloud outages
- **`handler.setLevel(logging.INFO)`** — never ship DEBUG to Loki
- **All Loki code wrapped in try/except** — never crashes the watch loop
- **Errors in LokiHandler._flush() go to stderr via print()** — NOT via logger (prevents recursion)
- **No src/ file > 400 lines, no function > 60 lines**
- `loki_handler.py` target: ≤120 lines total (DedupFilter ~25, LokiHandler ~50, setup ~30, imports ~15)

## Commit Message

```
feat(observability): Grafana Cloud Loki log handler (SD#40)

- Raw HTTP handler ships logs to Grafana Cloud Loki (zero new dependencies)
- DedupFilter suppresses noisy repeated messages (60s window)
- Extracts event/ticker from existing ctx dicts as Loki labels
- threading.Queue(maxsize=10000) async wrapper for Windows safety
- 5 tests (disabled, missing config, missing token, dedup, dedup window)
- Zero impact when disabled — additive only, never crashes watch loop
```

## Final Checklist

- [ ] `python -m pytest tests/ -x -q` passes
- [ ] `python -c "from src.observability.loki_handler import setup_loki_handler; print('OK')"` works
- [ ] No src/ file > 400 lines, no function > 60 lines
- [ ] MASTER.md Section 2 updated
- [ ] CHANGELOG.md updated
- [ ] Existing tests still pass (especially test_log_config if it exists)
- [ ] Do NOT merge — push to branch `feat/grafana-observability`, open PR
