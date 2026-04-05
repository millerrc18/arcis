# Sprint: System Utilization & Health Monitoring with Dashboard

> **Priority:** MEDIUM — operational visibility and professional monitoring
> **Estimated time:** 5-7 hours CC time
> **Branch:** `feat/system-monitoring`
> **Access:** LOCAL — requires nvidia-smi, psutil, database access

> ⚠️ **Files touched:**
> - NEW: `src/monitoring/` (new directory — collector, schema, API)
> - MODIFIED: `src/scheduler/watch.py` (add periodic collection trigger)
> - MODIFIED: `src/schema/registry.py` (add 3 new tables)
> - MODIFIED: `src/api/routes/system.py` (add monitoring endpoints)
> - NEW: `frontend/src/pages/Monitoring.jsx` (new dashboard page)
> - MODIFIED: `frontend/src/App.jsx` (add route)
> - MODIFIED: `frontend/src/components/Layout.jsx` (add sidebar entry)
>
> Minor overlap with simulation-engine sprint on schema/registry.py (different tables,
> Git auto-merges cleanly). Merge AFTER simulation sprint to be safe.

---

## What We're Building

A comprehensive system utilization and health tracking system that answers:
- Is the GPU being used efficiently? (target utilization by time of day)
- Are scans running on schedule? (success rate, latency, gaps)
- Is the system staying up? (uptime tracking, restart detection)
- Is the database growing healthily? (table sizes, row counts, disk usage)
- What's the cost efficiency? (compute hours per trade, API calls per scan)

This feeds into the HSHS health score and provides a dedicated dashboard page that
shows system operational health over time — not just trading performance.

---

## Pre-Flight

1. Read `MASTER.md`
2. Verify `nvidia-smi` is available: `nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader`
3. Install psutil if needed: `pip install psutil --break-system-packages`
4. Read existing monitoring: `src/scheduler/vram_manager.py`, `src/scheduler/metrics.py`
5. Read existing health page: `frontend/src/pages/Health.jsx`
6. Run `python -m pytest tests/ -x -q` — record baseline

---

## Task 1: Metric Collector (`src/monitoring/system_metrics.py`)

Create a collector that captures system metrics every 5 minutes.

```python
"""System metrics collector — GPU, CPU, RAM, disk, Ollama status.

Called by: scheduler.watch (every 5 minutes during active hours)
Calls: nvidia-smi (subprocess), psutil, requests (Ollama health)
Owns tables: system_metrics
Config keys: none
Tests: tests/test_system_metrics.py

Captures a snapshot of system utilization every 5 minutes. Stored in
system_metrics table for time-series dashboard display.

WHY every 5 minutes: Balances granularity vs database size.
288 rows/day × 365 days = ~105K rows/year — tiny. Provides enough
resolution to see GPU spikes during inference and training.
"""

import logging
import platform
import sqlite3
import subprocess
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


def collect_system_snapshot(db_path: str = DB_PATH) -> dict:
    """Capture a single system metrics snapshot.
    
    Returns dict with all metrics. Stores to system_metrics table.
    Graceful degradation: if nvidia-smi or psutil unavailable, 
    those fields are None (never crashes).
    """
    snapshot = {
        "snapshot_id": str(uuid.uuid4()),
        "timestamp": datetime.now(ET).isoformat(),
    }
    
    # GPU metrics (via nvidia-smi)
    snapshot.update(_collect_gpu_metrics())
    
    # CPU + RAM (via psutil)
    snapshot.update(_collect_cpu_ram_metrics())
    
    # Disk usage
    snapshot.update(_collect_disk_metrics())
    
    # Ollama status
    snapshot.update(_collect_ollama_status())
    
    # Process-level metrics
    snapshot.update(_collect_process_metrics())
    
    # Store to database
    _store_snapshot(snapshot, db_path)
    
    return snapshot


def _collect_gpu_metrics() -> dict:
    """Query nvidia-smi for GPU utilization, VRAM, temperature."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            parts = [p.strip() for p in result.stdout.strip().split(",")]
            return {
                "gpu_utilization_pct": float(parts[0]),
                "gpu_vram_used_mb": float(parts[1]),
                "gpu_vram_total_mb": float(parts[2]),
                "gpu_vram_pct": round(float(parts[1]) / float(parts[2]) * 100, 1),
                "gpu_temperature_c": float(parts[3]),
                "gpu_power_watts": float(parts[4]),
            }
    except Exception as e:
        logger.debug("[MONITOR] nvidia-smi unavailable: %s", e)
    return {"gpu_utilization_pct": None, "gpu_vram_used_mb": None,
            "gpu_vram_total_mb": None, "gpu_vram_pct": None,
            "gpu_temperature_c": None, "gpu_power_watts": None}


def _collect_cpu_ram_metrics() -> dict:
    """CPU and RAM via psutil."""
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory()
        return {
            "cpu_utilization_pct": cpu,
            "ram_used_gb": round(ram.used / (1024**3), 2),
            "ram_total_gb": round(ram.total / (1024**3), 2),
            "ram_pct": ram.percent,
        }
    except ImportError:
        logger.debug("[MONITOR] psutil not installed")
    return {"cpu_utilization_pct": None, "ram_used_gb": None,
            "ram_total_gb": None, "ram_pct": None}


def _collect_disk_metrics() -> dict:
    """Disk usage for the database and cache directories."""
    import shutil
    try:
        usage = shutil.disk_usage(".")
        return {
            "disk_used_gb": round(usage.used / (1024**3), 2),
            "disk_total_gb": round(usage.total / (1024**3), 2),
            "disk_pct": round(usage.used / usage.total * 100, 1),
        }
    except Exception:
        return {"disk_used_gb": None, "disk_total_gb": None, "disk_pct": None}


def _collect_ollama_status() -> dict:
    """Check if Ollama is running and which model is loaded."""
    try:
        import requests
        resp = requests.get("http://localhost:11434/api/tags", timeout=3)
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            loaded = [m["name"] for m in models] if models else []
            return {"ollama_running": True, "ollama_models_loaded": ",".join(loaded)}
    except Exception:
        pass
    return {"ollama_running": False, "ollama_models_loaded": None}


def _collect_process_metrics() -> dict:
    """Python process memory and uptime."""
    try:
        import psutil
        proc = psutil.Process()
        create_time = datetime.fromtimestamp(proc.create_time(), tz=ET)
        uptime_hours = (datetime.now(ET) - create_time).total_seconds() / 3600
        return {
            "process_rss_mb": round(proc.memory_info().rss / (1024**2), 1),
            "process_uptime_hours": round(uptime_hours, 2),
            "python_version": platform.python_version(),
        }
    except Exception:
        return {"process_rss_mb": None, "process_uptime_hours": None,
                "python_version": platform.python_version()}
```

---

## Task 2: Scan Tracker (`src/monitoring/scan_tracker.py`)

Track every scan pipeline execution — success, failure, latency, results.

```python
"""Scan execution tracker — records every scan pipeline run.

Called by: services.scan_service (at start/end of every scan)
Owns tables: scan_executions
"""

def record_scan_start(scan_id: str, scan_type: str = "universe") -> None:
    """Called at the start of every scan pipeline run."""

def record_scan_end(scan_id: str, result: dict) -> None:
    """Called at the end of every scan. Records outcome and metrics."""
    # result includes: tickers_scanned, packets_generated, trades_opened,
    # duration_seconds, errors, traffic_light_state, enrichment_failures

def get_scan_health(hours: int = 24, db_path: str = DB_PATH) -> dict:
    """Compute scan health metrics over the last N hours.
    
    Returns:
        success_rate: % of scans that completed without error
        avg_duration_seconds: mean scan time
        scans_expected: based on 30-min cadence during market hours
        scans_actual: how many actually ran
        gap_count: number of missed scan windows
        longest_gap_minutes: longest period without a scan
    """
```

**Wire into scan pipeline:**
In `src/services/scan_service.py`, wrap `run_scan()`:
```python
from src.monitoring.scan_tracker import record_scan_start, record_scan_end

def run_scan(config):
    scan_id = str(uuid.uuid4())
    record_scan_start(scan_id)
    try:
        result = _do_scan(config)
        record_scan_end(scan_id, {"status": "success", **result})
        return result
    except Exception as e:
        record_scan_end(scan_id, {"status": "error", "error": str(e)})
        raise
```

---

## Task 3: Uptime Tracker (`src/monitoring/uptime.py`)

Track system uptime and detect restarts.

```python
"""Uptime tracking — detect gaps, restarts, and sleep events.

Called by: scheduler.watch (every cycle)
Owns tables: uptime_events
"""

def record_heartbeat(db_path: str = DB_PATH) -> None:
    """Called every watch loop cycle. Stores timestamp.
    A gap > 5 minutes between heartbeats = potential sleep/crash."""

def detect_gaps(hours: int = 24, gap_threshold_minutes: int = 5,
                db_path: str = DB_PATH) -> list[dict]:
    """Find gaps in heartbeat data that indicate sleep/crash events.
    
    Returns list of {"start": str, "end": str, "duration_minutes": float, "type": str}
    where type is "sleep" (gap < 4 hours) or "restart" (gap > 4 hours).
    """

def get_uptime_stats(days: int = 7, db_path: str = DB_PATH) -> dict:
    """Compute uptime statistics.
    
    Returns:
        uptime_pct: % of market hours with active heartbeat
        total_gaps: number of detected gaps
        total_gap_hours: cumulative gap duration
        longest_gap_minutes: longest single gap
        restarts: number of detected restart events
        current_uptime_hours: time since last restart
    """
```

---

## Task 4: Database Schema

Add to `src/schema/registry.py`:

```python
"system_metrics": {
    "columns": [
        ("snapshot_id", "TEXT PRIMARY KEY"),
        ("timestamp", "TEXT NOT NULL"),
        ("gpu_utilization_pct", "REAL"),
        ("gpu_vram_used_mb", "REAL"),
        ("gpu_vram_total_mb", "REAL"),
        ("gpu_vram_pct", "REAL"),
        ("gpu_temperature_c", "REAL"),
        ("gpu_power_watts", "REAL"),
        ("cpu_utilization_pct", "REAL"),
        ("ram_used_gb", "REAL"),
        ("ram_total_gb", "REAL"),
        ("ram_pct", "REAL"),
        ("disk_used_gb", "REAL"),
        ("disk_total_gb", "REAL"),
        ("disk_pct", "REAL"),
        ("ollama_running", "INTEGER"),
        ("ollama_models_loaded", "TEXT"),
        ("process_rss_mb", "REAL"),
        ("process_uptime_hours", "REAL"),
        ("python_version", "TEXT"),
    ],
},

"scan_executions": {
    "columns": [
        ("scan_id", "TEXT PRIMARY KEY"),
        ("scan_type", "TEXT DEFAULT 'universe'"),
        ("started_at", "TEXT NOT NULL"),
        ("ended_at", "TEXT"),
        ("duration_seconds", "REAL"),
        ("status", "TEXT"),  -- success, error, timeout
        ("tickers_scanned", "INTEGER"),
        ("packets_generated", "INTEGER"),
        ("trades_opened", "INTEGER"),
        ("traffic_light_state", "TEXT"),
        ("enrichment_failures", "INTEGER"),
        ("error_message", "TEXT"),
    ],
},

"uptime_heartbeats": {
    "columns": [
        ("heartbeat_id", "TEXT PRIMARY KEY"),
        ("timestamp", "TEXT NOT NULL"),
        ("watch_loop_cycle", "INTEGER"),
    ],
},
```

---

## Task 5: Watch Loop Integration

In `src/scheduler/watch.py`, add periodic metric collection:

```python
# Every 5 minutes: collect system metrics
if now.minute % 5 == 0 and not self._metrics_collected_this_period:
    self._safe_run("system metrics", self._collect_system_metrics)
    self._metrics_collected_this_period = True
elif now.minute % 5 != 0:
    self._metrics_collected_this_period = False

# Every cycle: heartbeat
record_heartbeat()
```

---

## Task 6: API Endpoints

Add to `src/api/routes/system.py`:

```python
@router.get("/monitoring/system-metrics")
def system_metrics(hours: int = 24):
    """Get system metrics time series for dashboard charts."""

@router.get("/monitoring/scan-health")
def scan_health(hours: int = 24):
    """Get scan execution health metrics."""

@router.get("/monitoring/uptime")
def uptime_stats(days: int = 7):
    """Get uptime statistics and gap detection."""

@router.get("/monitoring/summary")
def monitoring_summary():
    """Combined monitoring dashboard data — single API call.
    
    Returns GPU utilization (current + 24h avg + target),
    scan health (success rate + expected vs actual),
    uptime (% + gaps + current uptime),
    disk (used + growth rate),
    Ollama status,
    cost metrics (API calls, compute hours).
    """
```

Also add to `src/sync/render_sync.py` — add `system_metrics`, `scan_executions`,
and `uptime_heartbeats` to the sync list so the deployed dashboard can see the data.

---

## Task 7: Dashboard Page (`frontend/src/pages/Monitoring.jsx`)

**This is the showpiece.** A Bloomberg-style system monitoring page.

### Layout:

**Top row: 6 real-time gauges** (current utilization snapshot)
```
GPU: 34% [████░░░░░░] 4.1GB/12GB  |  CPU: 12%  |  RAM: 18.2/32GB  |  Disk: 234/500GB  |  Uptime: 47.2h  |  Ollama: ONLINE
```

**Second row: GPU utilization timeline** (24h area chart)
- X axis: time (24h)
- Y axis: GPU % (0-100)
- Overlay: target utilization bands from MASTER.md (market hours 30-40%, overnight 50-70%, weekend 70-80%)
- Color: blue area fill, amber target band borders

**Third row: Scan health panel** (left) + **Uptime panel** (right)

Scan health:
```
Scans (24h): 26/26 (100%)  |  Avg: 4.2 min  |  Packets: 12  |  Trades: 2
Gap detector: 0 missed windows
Last scan: 14:30 ET (2 min ago) — 103 tickers, 3 packets, GREEN
```

Uptime:
```
7-day uptime: 94.2%  |  Market hours: 98.1%  |  Gaps: 3 (total 4.1h)
Current session: 47.2h since last restart
Sleep events: 2 (avg 1.8h) — computer sleep during market hours = root cause
```

**Fourth row: Database growth** (left) + **Cost metrics** (right)

Database:
```
SQLite: 234 MB  |  Growth: +2.1 MB/day  |  Tables: 49  |  Largest: options_chains (89MB)
Postgres (Render): synced 42,646 rows last cycle, 4 errors
```

Cost:
```
Monthly: $64 (Render $14, Claude API ~$50)
Per trade: ~$3.20 (50 API calls × $0.03 + compute)
Per scan: ~$0.08 (0.5 min GPU @ $0.10/hr)
```

**Bottom: Recent events timeline** (horizontal)
Shows scan completions, restarts, sleep events, errors as dots on a 24h timeline.

### Apply Bloomberg styling from the UI sprint:
- Near-black background, monospace numbers, squared corners
- Green/red only for pass/fail, blue for interactive
- Data-dense, minimal padding
- If the UI sprint has already merged, use those CSS variables
- If not, apply the Bloomberg palette directly

### 3× Ralph Loop on this page:
Follow the same protocol as the UI sprint — implement, review for gaps, polish.
Then run the independent agent auditor. Must score ≥ 9.0/10.

---

## Task 8: Route + Sidebar

In `frontend/src/App.jsx`, add:
```jsx
import Monitoring from './pages/Monitoring'
// In Routes:
<Route path="/monitoring" element={<ErrorBoundary><Monitoring /></ErrorBoundary>} />
```

In `frontend/src/components/Layout.jsx`, add to the "System" section:
```jsx
{ to: '/monitoring', icon: Gauge, label: 'Monitoring' },
// Import: import { Gauge } from 'lucide-react'
```

---

## Tests

Create `tests/test_system_monitoring.py`:
- `test_gpu_metrics_with_nvidia_smi()` — mock subprocess, verify parsing
- `test_gpu_metrics_without_nvidia_smi()` — mock failure, verify graceful degradation
- `test_cpu_ram_metrics()` — verify psutil data collection
- `test_cpu_ram_without_psutil()` — verify graceful fallback
- `test_ollama_status_online()` — mock requests, verify detection
- `test_ollama_status_offline()` — mock timeout, verify graceful fallback
- `test_scan_tracker_start_end()` — verify scan recording
- `test_scan_health_computation()` — mock scan data, verify stats
- `test_uptime_heartbeat()` — verify heartbeat storage
- `test_gap_detection()` — insert heartbeats with a gap, verify detection
- `test_uptime_stats()` — verify uptime percentage computation
- `test_monitoring_api_endpoints()` — verify all 4 endpoints return valid JSON
- `test_schema_tables_registered()` — verify 3 new tables in registry

---

## Verification

```bash
python -m pytest tests/ -x -q                          # All pass
python -m pytest tests/test_system_monitoring.py -v     # All new tests pass
cd frontend && npm run build && cd ..                   # Succeeds

# Manual: collect a snapshot
python -c "
from src.monitoring.system_metrics import collect_system_snapshot
import json
snap = collect_system_snapshot()
print(json.dumps({k: v for k, v in snap.items() if v is not None}, indent=2))
"

# Verify dashboard page renders (open in browser at /monitoring)
```

---

## Commit Strategy

```bash
# Commit 1: Backend collectors + schema
git add src/monitoring/ src/schema/registry.py src/scheduler/watch.py src/services/scan_service.py
git commit -m "feat: system monitoring — GPU/CPU/RAM/disk collectors + scan tracker + uptime

3 new tables: system_metrics, scan_executions, uptime_heartbeats.
Metrics collected every 5 minutes via watch loop.
Graceful degradation: nvidia-smi or psutil unavailable = None fields.
Scan tracker wraps every pipeline run with timing + outcome.
Heartbeat-based uptime with gap detection."

# Commit 2: API endpoints + render sync
git add src/api/routes/system.py src/sync/render_sync.py tests/
git commit -m "feat: monitoring API endpoints + render sync

4 endpoints: /monitoring/system-metrics, /scan-health, /uptime, /summary.
Render sync added for all 3 monitoring tables.
13 test cases covering all collectors and API endpoints."

# Commit 3: Dashboard page + routing
git add frontend/
git commit -m "feat: Monitoring dashboard page — Bloomberg-style system health

GPU utilization timeline with target bands, scan health scorecard,
uptime tracker with gap detection, database growth, cost metrics.
Route: /monitoring. Sidebar: System > Monitoring.
3x Ralph Loop + agent auditor verified ≥ 9.0/10."
```

Do NOT merge to main. Push to `feat/system-monitoring` only.
