# Grafana Cloud MVP — Centralized Observability for Arcis

**Date:** April 14, 2026
**Priority:** Operational improvement — not blocking trading
**Cost:** $0/month (Grafana Cloud Free tier)
**Setup time:** ~1 hour
**Sprint scope:** Saturday or standalone

---

## Why

Three log sources (watch loop, Render dashboard, IB Gateway) across two machines with no unified view. The primary consumer of these logs is AI agents (CC, Claude) who currently require copy-pasted raw text. A single searchable log store with visualizations means faster debugging, pattern detection, and less context window waste.

---

## Grafana Cloud Free Tier Limits

| Resource | Free Limit | Our Usage |
|----------|-----------|-----------|
| Logs (Loki) | 50 GB/month | ~5-10 GB/month |
| Metrics (Prometheus) | 10,000 active series | ~50-100 series |
| Traces | 50 GB/month | Not needed (Phase 2) |
| Users | 3 | 1 (Ryan) |
| Retention | 14 days | Sufficient for debugging |
| Dashboards | 500 | Need ~3 |

We're well within free tier. No risk of surprise charges.

---

## Architecture

```
┌─────────────────────┐     ┌──────────────────────┐
│  Windows PC (local)  │     │    Render (cloud)     │
│                      │     │                       │
│  Watch Loop ─────────┼────►│                       │
│  (halcyon.log)       │     │  FastAPI Dashboard ───┼──┐
│                      │     │  (stdout logs)        │  │
│  LLM Inference ──────┼────►│                       │  │
│  (Ollama)            │     └──────────────────────┘  │
│                      │                                │
│  IB Gateway ─────────┼─►  (Phase 2 - file tailer)    │
│  (local log files)   │                                │
└──────────┬───────────┘                                │
           │                                            │
           │  python-logging-loki                       │
           │  (HTTP push to Grafana Cloud)              │
           ▼                                            ▼
    ┌─────────────────────────────────────────────────────┐
    │              Grafana Cloud (Free Tier)               │
    │                                                     │
    │  Loki ← logs from all sources                       │
    │  Prometheus ← custom metrics (optional Phase 2)     │
    │  Grafana ← dashboards + alerts                      │
    │                                                     │
    └─────────────────────────────────────────────────────┘
```

---

## MVP Scope (Phase 1 — Saturday sprint)

### Task 1: Grafana Cloud account setup

Manual steps (Ryan):
1. Sign up at grafana.com/products/cloud (use halcyonlabai@gmail.com)
2. Create a free stack (region: US)
3. Go to Connections → Loki → note the push URL and generate an API key
4. Save credentials to `settings.local.yaml` under a new `observability` section

```yaml
observability:
  grafana:
    enabled: true
    loki_url: "https://logs-prod-XXX.grafana.net/loki/api/v1/push"
    loki_user: "123456"  # Grafana Cloud user ID
    loki_token: "glc_..."  # API key (write scope)
```

### Task 2: Python logging handler

**File:** `src/observability/loki_handler.py` (new)

Install: `pip install python-logging-loki --break-system-packages`

```python
"""Grafana Loki log handler for centralized observability.

Ships all Python logger output to Grafana Cloud Loki via HTTP push.
Uses a queue-based async handler so log shipping never blocks trading.

Called by: src/config.py (logging setup)
Config keys: observability.grafana.enabled, loki_url, loki_user, loki_token
"""
import logging
import logging.handlers
from multiprocessing import Queue

def setup_loki_handler(config: dict) -> logging.Handler | None:
    """Create a non-blocking Loki handler from config. Returns None if disabled."""
    grafana = config.get("observability", {}).get("grafana", {})
    if not grafana.get("enabled"):
        return None

    try:
        import logging_loki
        handler = logging_loki.LokiQueueHandler(
            Queue(-1),
            url=grafana["loki_url"],
            tags={"application": "arcis", "environment": "production"},
            auth=(str(grafana["loki_user"]), grafana["loki_token"]),
            version="1",
        )
        handler.setLevel(logging.INFO)
        return handler
    except ImportError:
        logging.getLogger(__name__).warning(
            "[OBSERVABILITY] python-logging-loki not installed — Grafana disabled"
        )
        return None
```

### Task 3: Integrate handler into logging setup

**File:** `src/config.py` or wherever root logger is configured

After the existing file/console handlers are set up:

```python
# Grafana Cloud Loki handler (non-blocking, ships logs to cloud)
from src.observability.loki_handler import setup_loki_handler
loki = setup_loki_handler(config)
if loki:
    logging.getLogger().addHandler(loki)
    logging.getLogger(__name__).info("[OBSERVABILITY] Grafana Loki handler active")
```

This is additive — existing file logging and console output are unchanged.

### Task 4: Add structured labels to key log events

The Loki handler ships every log line, but labels make them searchable. Add `extra` tags to high-value log events:

```python
# In executor.py — trade events
logger.info("[EXECUTOR] Opened %s", ticker,
    extra={"tags": {"event": "trade_open", "ticker": ticker, "source": source}})

# In watch.py — cycle events
logger.info("[WATCH] Scan complete",
    extra={"tags": {"event": "scan_complete", "regime": regime}})

# In reconcile.py — reconciliation events
logger.warning("[RECONCILE] Stale closure %s", ticker,
    extra={"tags": {"event": "stale_close", "ticker": ticker, "broker": broker}})
```

Start with 5-10 key events. Don't boil the ocean — every log line is already searchable by text.

### Task 5: Build MVP Grafana dashboard

Create 3 panels in Grafana Cloud UI (manual, not code):

**Panel 1: Log Stream (live tail)**
- Type: Logs panel
- Query: `{application="arcis"}`
- Filter by level: ERROR, WARNING
- This replaces grepping halcyon.log

**Panel 2: Error Rate Over Time**
- Type: Time series
- Query: `rate({application="arcis"} |= "ERROR" [5m])`
- Shows error spikes — useful for "did CC's last sprint break something?"

**Panel 3: Trade Events Timeline**
- Type: Time series
- Query: `count_over_time({application="arcis", event="trade_open"} [1h])`
- Shows trade activity — useful for "is the system actually trading?"

**Panel 4: Watch Loop Health**
- Type: Stat
- Query: `count_over_time({application="arcis"} |= "[WATCH]" [5m])`
- If this drops to zero, the watch loop died

### Task 6: Render logs (deferred to Phase 2)

Render only supports syslog log streams, not Loki natively. Two options:
- **Option A:** Add the same Loki handler to the Render FastAPI app (requires `python-logging-loki` in Render's requirements.txt and Loki credentials as env vars)
- **Option B:** Use a syslog-to-Loki bridge (more complex, not worth it for MVP)

For MVP, skip Render logs. The watch loop ships the same events to Loki directly — the Render dashboard is just a frontend that reads from Postgres. The real operational logs are all local.

### Task 7: IB Gateway logs (deferred to Phase 2)

IB Gateway writes Java log files to `B:\Interactive Brokers\ibgateway\`. These are not Python loggers. Options:
- **Phase 2:** Promtail or Grafana Alloy agent running locally, tailing the IB log files
- **Phase 2:** Custom Python script that tails and pushes to Loki

Skip for MVP. IB Gateway logs are only useful for post-incident analysis, not real-time monitoring.

---

## Phase 2 Additions (not in MVP)

| Feature | When | Why |
|---------|------|-----|
| Prometheus metrics | After 50 trades | GPU util, VRAM, inference latency, trade counts as time series |
| Render log shipping | When Render costs justify it | Duplicate of local logs for now |
| IB Gateway log tailing | When IB goes live | Promtail or Alloy agent |
| Alerting rules | After 2 weeks of data | "Error rate > 10/min for 5 minutes" → Telegram |
| Trading metrics dashboard | After 100 trades | Sharpe rolling, win rate rolling, drawdown — from Prometheus, not Loki |

---

## CC Sprint Prompt

```
MVP Grafana Cloud Loki integration. Branch: feat/grafana-observability

5 tasks:

1. Create src/observability/loki_handler.py with setup_loki_handler(config).
Uses python-logging-loki LokiQueueHandler (non-blocking, queue-based).
Reads config from observability.grafana.enabled/loki_url/loki_user/loki_token.
Returns None if disabled or package not installed. Never crashes — all errors caught.

2. Integrate into root logger setup. Find where the root logger is configured
(likely src/config.py or src/main.py). After existing handlers, call
setup_loki_handler and addHandler if non-None. Log confirmation message.

3. Add extra tags to 10 high-value log events across:
- executor.py: trade_open, trade_close, bracket_placed, exit_triggered
- watch.py: scan_complete, eod_recap, overnight_cycle
- reconcile.py: stale_close, broker_unreachable
- trainer.py: training_started
Use extra={"tags": {"event": "...", "ticker": "...", ...}} format.

4. Add to settings.example.yaml:
observability:
  grafana:
    enabled: false
    loki_url: ""
    loki_user: ""
    loki_token: ""

5. Add python-logging-loki to requirements.txt. Add 2 tests:
- Test: handler returns None when disabled
- Test: handler returns None when package missing (mock ImportError)

Do NOT set up Grafana Cloud account — Ryan does that manually.
Do NOT ship Render or IB Gateway logs — MVP is local Python only.

Push to branch. Do NOT merge.
```

---

## What This Gives You

**Before:** "Hey Claude, here are 200 lines of log output I pasted from three different terminals"

**After:** "Check Grafana, filter by ERROR in the last hour" — or CC can describe what to search for and you screenshot the results. Eventually, CC could query Loki directly via API.

**Cost:** $0/month. 1 hour setup. Zero impact on trading performance (async handler).

---

## Ralph Loop Findings

### Pass 1 — Dependency risk
`python-logging-loki` last released 2020 (v0.3.1). May break on Python 3.12+. **Mitigation:** CC must implement a raw fallback handler using `requests.post()` to `/loki/api/v1/push` with snappy or JSON encoding. The Loki push API accepts:
```json
{"streams": [{"stream": {"app": "arcis", "level": "ERROR"}, "values": [["<unix_nano>", "<log line>"]]}]}
```
This is 20 lines of code with zero external dependencies beyond `requests`. If `python-logging-loki` works, use it. If not, the fallback ships the same data. CC sprint prompt updated to include both paths.

### Pass 2 — Log volume control
Tonight's logs showed ~50 repeated `[SCHEMA] Created/verified 53 tables` messages per cycle. At INFO level, these ship to Loki and consume quota unnecessarily. **Fix:** Add a `DedupFilter` class that suppresses identical messages within a 60-second window. Attach to the Loki handler only (local file logging unchanged). Expected volume reduction: ~80% on noisy cycles. Also: hardcode `handler.setLevel(logging.INFO)` — never ship DEBUG to Loki regardless of root logger config.

```python
class DedupFilter(logging.Filter):
    """Suppress duplicate log messages within a time window."""
    def __init__(self, window_seconds=60):
        super().__init__()
        self._seen = {}
        self._window = window_seconds
    
    def filter(self, record):
        import time
        key = f"{record.name}:{record.getMessage()}"
        now = time.time()
        if key in self._seen and (now - self._seen[key]) < self._window:
            return False
        self._seen[key] = now
        # Prune old entries every 100 inserts
        if len(self._seen) > 1000:
            cutoff = now - self._window
            self._seen = {k: v for k, v in self._seen.items() if v > cutoff}
        return True
```

### Pass 3 — Windows threading safety
`multiprocessing.Queue` on Windows spawns a new process, which can conflict with the watch loop's process model and cause pickle serialization errors for log records. **Fix:** Use `queue.Queue` (threading-based) instead of `multiprocessing.Queue`. Also cap queue size: `Queue(maxsize=10000)` — if Grafana Cloud is unreachable, dropped logs are acceptable, unbounded memory growth is not.

Updated CC sprint prompt addition:
```
IMPORTANT Windows compatibility notes:
- Use queue.Queue (threading), NOT multiprocessing.Queue
- Queue(maxsize=10000) to prevent OOM during Grafana outages
- Add DedupFilter to suppress repeated messages within 60s window
- Implement raw requests-based fallback if python-logging-loki fails to import
- handler.setLevel(logging.INFO) is mandatory — never ship DEBUG to Loki
```
