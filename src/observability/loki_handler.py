"""Grafana Cloud Loki log handler for centralized observability.

Ships Python logger output to Grafana Cloud Loki via HTTP push. Uses
QueueHandler + QueueListener so log shipping never blocks trading: the
calling thread appends to a bounded in-memory queue; a daemon thread
drains the queue, batches records, and POSTs to Loki.

Called by: src/log_config.py (setup_logging)
Calls: requests (stdlib: threading, queue, logging.handlers)
Owns tables: none
Config keys: observability.grafana.enabled, loki_url, loki_user
Env vars: GRAFANA_LOKI_TOKEN
Tests: tests/test_loki_handler.py
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import platform
import sys
import threading
import time
from queue import Queue


class DedupFilter(logging.Filter):
    """Suppress duplicate log messages within a time window.

    Prevents noisy repeated messages (e.g., '[SCHEMA] Created/verified 53
    tables') from consuming Grafana Cloud quota. Attached to the Loki
    handler only — file/console logging is unaffected.
    """

    def __init__(self, window_seconds: float = 60.0):
        super().__init__()
        self._seen: dict[str, float] = {}
        self._window = window_seconds

    def filter(self, record: logging.LogRecord) -> bool:
        key = f"{record.name}:{record.getMessage()}"
        now = time.time()
        last = self._seen.get(key)
        if last is not None and (now - last) < self._window:
            return False
        self._seen[key] = now
        if len(self._seen) > 1000:
            cutoff = now - self._window
            self._seen = {k: v for k, v in self._seen.items() if v > cutoff}
        return True


class LokiHandler(logging.Handler):
    """Batches records and ships to Grafana Cloud Loki via HTTP push.

    Extracts `event` and `ticker` from the existing `record.ctx` dict
    (set via `extra={"ctx": {...}}`) and promotes them to Loki stream
    labels for efficient querying. All other ctx data is included in the
    formatted log line text via StructuredFormatter. Flushes every
    `flush_interval` seconds or when `_buffer` reaches `flush_size`.
    Never raises — drops batches on failure, prints to stderr.
    """

    def __init__(self, url: str, user: str, token: str,
                 flush_interval: float = 5.0, flush_size: int = 50):
        super().__init__()
        self.url = url
        self._auth = (user, token)
        self.flush_interval = flush_interval
        self.flush_size = flush_size
        self._buffer: list[tuple[float, str, str, dict]] = []
        self._lock = threading.Lock()
        self._host = platform.node()
        self._timer: threading.Timer | None = None
        self._schedule_flush()

    def _schedule_flush(self) -> None:
        self._timer = threading.Timer(self.flush_interval, self._flush)
        self._timer.daemon = True
        self._timer.start()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            ctx = getattr(record, "ctx", None) or {}
            entry = (record.created, self.format(record),
                     record.levelname, ctx if isinstance(ctx, dict) else {})
            with self._lock:
                self._buffer.append(entry)
                should_flush_now = len(self._buffer) >= self.flush_size
            if should_flush_now:
                self._flush()
        except Exception as exc:
            print(f"[LOKI] emit failed: {exc}", file=sys.stderr)

    def _flush(self) -> None:
        with self._lock:
            batch = self._buffer
            self._buffer = []
        try:
            if not batch:
                return
            streams: dict[tuple, list[list[str]]] = {}
            for created, line, level, ctx in batch:
                event = str(ctx.get("event", "")) if ctx else ""
                ticker = str(ctx.get("ticker", "")) if ctx else ""
                key = (level, event, ticker)
                streams.setdefault(key, []).append(
                    [str(int(created * 1e9)), line]
                )
            payload_streams = []
            for (level, event, ticker), values in streams.items():
                labels: dict[str, str] = {
                    "application": "arcis",
                    "host": self._host,
                    "level": level,
                }
                if event:
                    labels["event"] = event
                if ticker:
                    labels["ticker"] = ticker
                payload_streams.append({"stream": labels, "values": values})
            import requests
            requests.post(
                self.url,
                auth=self._auth,
                timeout=5,
                headers={"Content-Type": "application/json"},
                data=json.dumps({"streams": payload_streams}),
            )
        except Exception as exc:
            print(f"[LOKI] Flush failed: {exc}", file=sys.stderr)
        finally:
            self._schedule_flush()


def setup_loki_handler(config: dict) -> logging.Handler | None:
    """Create a non-blocking Loki handler from config.

    Returns a QueueHandler wrapping LokiHandler, or None if disabled
    or misconfigured. Uses threading.Queue (NOT multiprocessing.Queue)
    for Windows compatibility. Queue capped at 10,000 records to
    prevent OOM during Grafana outages.
    """
    grafana = config.get("observability", {}).get("grafana", {})
    if not grafana.get("enabled"):
        return None
    token = os.environ.get("GRAFANA_LOKI_TOKEN", "")
    if not token:
        logging.getLogger(__name__).warning(
            "[OBSERVABILITY] GRAFANA_LOKI_TOKEN not set — Loki disabled"
        )
        return None
    loki_url = grafana.get("loki_url")
    loki_user = grafana.get("loki_user")
    if not loki_url or not loki_user:
        logging.getLogger(__name__).warning(
            "[OBSERVABILITY] loki_url/loki_user missing — Loki disabled"
        )
        return None

    from src.log_config import StructuredFormatter
    loki_handler = LokiHandler(url=loki_url, user=str(loki_user), token=token)
    loki_handler.setFormatter(
        StructuredFormatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    )
    loki_handler.addFilter(DedupFilter())

    q: Queue = Queue(maxsize=10000)
    queue_handler = logging.handlers.QueueHandler(q)
    listener = logging.handlers.QueueListener(
        q, loki_handler, respect_handler_level=True
    )
    listener.start()
    queue_handler._loki_listener = listener  # pin to prevent GC
    queue_handler.setLevel(logging.INFO)
    return queue_handler
