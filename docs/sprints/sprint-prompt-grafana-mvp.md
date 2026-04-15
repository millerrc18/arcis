# Sprint: Grafana Cloud Loki MVP — Centralized Log Aggregation

**Branch:** `feat/grafana-observability`
**Priority:** HIGH — watch loop crashes silently with no traceback; need centralized logging for debugging
**Spec:** `docs/sprints/sprint-grafana-observability-mvp.md`
**Estimated time:** 1-2 hours

---

## Pre-flight

- [ ] Read MASTER.md (root)
- [ ] Read `docs/sprints/sprint-grafana-observability-mvp.md` (full spec + Ralph loop findings)
- [ ] Read `src/log_config.py` (current logging setup)
- [ ] Read `src/config/__init__.py` (config loading: settings.local.yaml + .env precedence)
- [ ] Run existing tests: `python -m pytest tests/ -x -q` — must pass before starting
- [ ] File size check: no src/ file > 400 lines, no function > 60 lines

---

## Context

Config architecture:
- `config/settings.local.yaml` — non-secret config (gitignored)
- `.env` — secrets (API keys, tokens)
- `src/config/__init__.py` — loads YAML, dotenv, caches config
- `src/log_config.py` — sets up root logger with StructuredFormatter, console + rotating file handlers

Grafana Cloud credentials (already configured):
- Loki push URL: `https://logs-prod-042.grafana.net/loki/api/v1/push`
- User ID: `1553293`
- Token: stored in `.env` as `GRAFANA_LOKI_TOKEN`

---

## Task 1: Add Grafana config section

**File:** `config/settings.example.yaml`

Add to the end of the file:

```yaml
# ── Observability ──────────────────────────────────────────────────
observability:
  grafana:
    enabled: false  # Set true in settings.local.yaml after configuring credentials
    loki_url: "https://logs-prod-042.grafana.net/loki/api/v1/push"
    loki_user: "1553293"
    # Token goes in .env as GRAFANA_LOKI_TOKEN
```

**File:** `.env.example` (or add comment to existing .env.example if it exists)

Add line: `# GRAFANA_LOKI_TOKEN=glc_...`

---

## Task 2: Create `src/observability/__init__.py` and `src/observability/loki_handler.py`

Create `src/observability/__init__.py` (empty).

Create `src/observability/loki_handler.py`:

Requirements:
- Function `setup_loki_handler(config: dict) -> logging.Handler | None`
- Reads config from `config.get("observability", {}).get("grafana", {})`
- Token from `os.environ.get("GRAFANA_LOKI_TOKEN")` — env var takes precedence (same pattern as other secrets)
- Returns None if `enabled` is False or token is missing
- **CRITICAL Windows safety:** Use `from queue import Queue` (threading), NOT `from multiprocessing import Queue`
- `Queue(maxsize=10000)` — prevents OOM if Grafana Cloud is unreachable
- `handler.setLevel(logging.INFO)` — NEVER ship DEBUG to Loki
- Include a `DedupFilter` class that suppresses identical log messages within 60 seconds (the schema check logs fire 50+ times per cycle)
- Attach DedupFilter to the Loki handler only (not to file/console handlers)

**Two implementation paths — try python-logging-loki first, fall back to raw requests:**

Path A (preferred): Use `python-logging-loki` package
```python
import logging_loki
handler = logging_loki.LokiHandler(
    url=loki_url,
    tags={"application": "arcis", "host": platform.node()},
    auth=(str(loki_user), loki_token),
    version="1",
)
```
Then wrap in `logging.handlers.QueueHandler` + `logging.handlers.QueueListener` with `queue.Queue(maxsize=10000)`.

Path B (fallback): If `python-logging-loki` import fails, implement a minimal `RawLokiHandler(logging.Handler)` that:
- Collects log records in a list (batch)
- Every 5 seconds or 50 records (whichever first), POST to `{loki_url}` with:
  ```json
  {"streams": [{"stream": {"application": "arcis", "level": "ERROR", "host": "SWIFT-PC"}, "values": [["<unix_nano>", "<formatted message>"]]}]}
  ```
- Uses `requests.post(url, json=payload, auth=(user, token), timeout=5)`
- Groups by level label so Grafana can filter `{level="ERROR"}`
- On failure, silently drops the batch (never crashes the watch loop)
- Runs in a daemon thread

**Docstring must include:**
```
Called by: src/log_config.py
Calls: python-logging-loki (optional), requests (fallback)
Owns tables: none
Config keys: observability.grafana.enabled, loki_url, loki_user
Env vars: GRAFANA_LOKI_TOKEN
Tests: tests/test_loki_handler.py
```

---

## Task 3: Integrate into `src/log_config.py`

At the end of `setup_logging()`, after the file handler is added:

```python
# Grafana Cloud Loki handler (non-blocking, ships logs to cloud)
try:
    from src.config import load_config
    from src.observability.loki_handler import setup_loki_handler
    config = load_config()
    loki = setup_loki_handler(config)
    if loki:
        root.addHandler(loki)
        logging.getLogger(__name__).info("[OBSERVABILITY] Grafana Loki handler active — shipping logs to cloud")
except Exception as exc:
    # Never let observability setup crash the application
    logging.getLogger(__name__).warning("[OBSERVABILITY] Loki handler setup failed: %s", exc)
```

**Important:** Wrap in try/except — Loki setup must NEVER crash the watch loop.

---

## Task 4: Add structured tags to 10 high-value log events

Add `extra={"tags": {"event": "...", ...}}` to these existing log lines. Do NOT change the message text — only add the extra dict.

| File | Log line pattern to find | Tags to add |
|------|------------------------|-------------|
| `src/shadow_trading/executor.py` | `[EXECUTOR] Entry order placed` or similar entry log | `{"event": "trade_open", "ticker": ticker, "source": source}` |
| `src/shadow_trading/executor.py` | `[EXIT]` close/exit log | `{"event": "trade_close", "ticker": ticker, "exit_reason": reason}` |
| `src/shadow_trading/executor.py` | `[EXIT] Broker exit failed` | `{"event": "exit_failed", "ticker": ticker}` |
| `src/shadow_trading/executor.py` | `[BRACKET]` placement log | `{"event": "bracket_placed", "ticker": ticker}` |
| `src/scheduler/watch.py` | `[WATCH] Scan cycle #N complete` | `{"event": "scan_complete", "scan_number": n}` |
| `src/scheduler/watch.py` | `EOD recap` or end-of-day log | `{"event": "eod_recap"}` |
| `src/scheduler/overnight.py` | overnight collection start/complete | `{"event": "overnight_complete"}` |
| `src/shadow_trading/reconcile.py` | stale closure or reconcile issue | `{"event": "reconcile_issue", "ticker": ticker}` |
| `src/training/trainer.py` | training started/completed | `{"event": "training_started"}` or `{"event": "training_completed"}` |
| `src/notifications/telegram.py` | telegram send | `{"event": "telegram_sent", "type": msg_type}` |

**Note:** `python-logging-loki` reads `extra["tags"]` natively and converts them to Loki labels. The raw fallback handler should also extract `record.tags` if present and merge into stream labels.

---

## Task 5: Add `python-logging-loki` and `requests` to requirements.txt

- Add `python-logging-loki>=0.3.1` to requirements.txt (if not already present)
- `requests` should already be in requirements.txt — verify, do not duplicate

---

## Task 6: Tests

**File:** `tests/test_loki_handler.py`

4 tests:

1. `test_handler_returns_none_when_disabled` — config has `enabled: false`, assert returns None
2. `test_handler_returns_none_when_token_missing` — config has `enabled: true` but no env var, assert returns None
3. `test_dedup_filter_suppresses_duplicates` — create DedupFilter, log same message twice within 1 second, assert second is filtered
4. `test_dedup_filter_allows_after_window` — create DedupFilter with 0.1s window, sleep 0.2s, assert second message passes

Do NOT test actual Loki connectivity — no network calls in tests.

---

## Task 7: Update MASTER.md Section 2

Update volatile counts:
- Research docs count if changed
- Add to infrastructure section: "Grafana Cloud (free tier) for centralized log aggregation via Loki"

---

## Backward Compatibility

- All changes are additive — zero impact if `observability.grafana.enabled` is false or missing
- Existing file and console logging unchanged
- If `python-logging-loki` is not installed, falls back to raw handler
- If raw handler fails, logs warning and continues
- Watch loop startup is never blocked by observability setup

## Commit Messages

```
feat(observability): Grafana Cloud Loki log handler (SD#40)

- Async log shipping to Grafana Cloud Loki via python-logging-loki
- DedupFilter suppresses noisy repeated messages (60s window)
- Raw requests fallback if python-logging-loki unavailable
- threading.Queue(maxsize=10000) for Windows safety
- 10 structured event tags across executor, watch, reconcile, training
- 4 tests (handler disabled, token missing, dedup filter, dedup window)
- Zero impact when disabled — additive only
```

## Final Checklist

- [ ] `python -m pytest tests/ -x -q` passes
- [ ] No src/ file > 400 lines
- [ ] No function > 60 lines
- [ ] MASTER.md Section 2 updated
- [ ] CHANGELOG.md updated
- [ ] `python -c "from src.observability.loki_handler import setup_loki_handler; print('import OK')"` works
- [ ] Do NOT merge — push to branch, open PR
