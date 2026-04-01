# Sprint 7: Reliability & Critical Bug Fixes (Claude Code)

> **Executor:** Claude Code
> **Scope:** 10 tasks (addressing ~25 GitHub issues)
> **Prerequisite:** Sprint 6 partial MERGED (.env migration). Sprint 6 Tasks 1-6 can happen later — reliability comes first.
> **Read first:** AGENTS.md, docs/conventions.md
> **Context:** CC deep audit filed 71 issues. Combined with prior audit, 87 open issues total. This sprint fixes the ones that could cause data loss, silent failures, or unattended system crashes. The system is trading autonomously — reliability is the #1 priority.
> **Test baseline:** 1,125 tests. Must not decrease.

---

## Priority Triage

**P0 — Fix now (trading risk / system crash):**
- #159: No top-level exception handler — unhandled exception crashes entire system
- #101: DAY time-in-force leaves positions unprotected over weekends/holidays
- #100: Exit_pending positions become zombies if exit order fails
- #105: Timestamp parse failure silently disables timeout — trades live forever
- #89: Traffic Light API still returns UNKNOWN stub
- #161: Render sync thread crash goes undetected
- #90: load_dotenv() missing from watch.py

**P1 — Fix this sprint (will cause problems soon):**
- #150: No heartbeat/liveness indicator
- #151: No scan overlap prevention
- #160: SQLite connections missing busy_timeout
- #124: Silent failure when API keys missing — no Telegram alert
- #102: Alpaca API failure silently skips all price checks
- #130: Overlapping sync cycles cause duplicate rows

**Grouped into 10 tasks below. Close the referenced issues in commit messages.**

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
# Must be ≥ 1125
```

---

## Task 1: Watch Loop Crash Protection (#159, #155, #157)

The watch loop has no top-level exception handler. One unhandled exception kills the entire system.

**File:** `src/scheduler/watch.py` — the main `run()` method

**Fix:**
1. Wrap the main loop body in `try/except Exception` — log the error, send Telegram CRITICAL alert, and CONTINUE (don't crash)
2. Handle `SystemExit` and `SIGTERM` gracefully alongside `KeyboardInterrupt`
3. Fix the `_safe_run` cooldown (#157) — 5-minute block after 3 errors is too aggressive. Use exponential backoff: 10s, 30s, 60s, then cap at 60s. Reset on success.
4. Add a restart counter — if the loop recovers from >5 exceptions in 1 hour, send a Telegram alert: "Watch loop unstable — {count} exceptions in last hour"

**Test:** Create `tests/test_watch_resilience.py` with ≥3 tests: exception doesn't crash loop, SIGTERM handled, backoff resets on success.

**Closes:** #159, #155, #157

---

## Task 2: load_dotenv in watch.py + Heartbeat (#90, #150)

**File:** `src/scheduler/watch.py`

**Fix 1 (#90):** Add `from dotenv import load_dotenv; load_dotenv()` at the top of the file (after imports). This ensures .env works even if watch.py is started directly instead of through main.py.

**Fix 2 (#150):** Add a heartbeat indicator. Every 5 minutes, write a timestamp to `data/watchdog.txt`. If the file is >10 minutes old, the system is stuck. Add a Telegram `/heartbeat` command that reports the age of this file.

```python
# In the main loop, every 5 minutes:
Path("data/watchdog.txt").write_text(datetime.now(ET).isoformat())
```

**Closes:** #90, #150

---

## Task 3: Traffic Light API — Replace Stub (#89)

**File:** `src/api/cloud_routes/analytics.py`

The Traffic Light stub still returns `{"regime": "UNKNOWN", "score": 0, "vix": 0}`. Replace with real query:

```python
@router.get("/api/traffic-light/current", dependencies=[Depends(verify_auth)])
def get_traffic_light_current():
    row = runtime.query_one(
        "SELECT current_regime, last_total_score FROM traffic_light_state WHERE id = 1"
    )
    vix_row = runtime.query_one(
        "SELECT vix FROM vix_term_structure ORDER BY collected_date DESC LIMIT 1"
    )
    return {
        "regime": row["current_regime"] if row else "UNKNOWN",
        "score": row["last_total_score"] if row else 0,
        "vix": round(float(vix_row["vix"]), 2) if vix_row else 0,
    }
```

**Closes:** #89

---

## Task 4: Bracket Order Safety (#101, #100, #105, #103)

**File:** `src/shadow_trading/executor.py`, `src/shadow_trading/alpaca_adapter.py`

**Fix 1 (#101):** Change bracket order time-in-force from DAY to GTC (Good-Til-Canceled). DAY orders expire at market close, leaving positions unprotected overnight and over weekends.

**Fix 2 (#100):** When an exit order fails, mark the trade as `exit_failed` (not leave it as `exit_pending` forever). Add a recovery mechanism: on each scan cycle, check for `exit_failed` trades and retry the exit. Send Telegram alert on first failure.

**Fix 3 (#105):** In `check_and_manage_open_trades()`, when datetime parsing fails for `actual_entry_time`, default to `days_open = 999` (force timeout) instead of `days_open = 0` (disable timeout). Log a warning.

**Fix 4 (#103):** When checking bracket legs for exit fills, record whether the exit was stop-loss or take-profit in the `exit_reason` field. Currently both are recorded the same way.

**Tests:** ≥4 tests: GTC order format, exit_failed recovery, timestamp parse failure triggers timeout, stop vs target leg identification.

**Closes:** #101, #100, #105, #103

---

## Task 5: Render Sync Resilience (#161, #130)

**File:** `src/sync/render_sync.py`

**Fix 1 (#161):** The sync thread runs in a background thread. If it crashes, the dashboard silently stops updating with no alert. Add:
- Wrap the sync loop in try/except — on crash, send Telegram alert "Render sync crashed: {error}"
- Set a `sync_last_success` timestamp. If it's >5 minutes old when checked during the main loop, send an alert.

**Fix 2 (#130):** Add a mutex/lock so overlapping sync cycles can't run concurrently. If a sync is already in progress when the next cycle triggers, skip it.

**Closes:** #161, #130

---

## Task 6: SQLite Safety (#160)

**File:** `src/scheduler/watch.py` and anywhere else that opens SQLite connections

**Fix (#160):** Ensure EVERY `sqlite3.connect()` call sets `busy_timeout`:
```python
conn = sqlite3.connect(db_path)
conn.execute("PRAGMA busy_timeout=5000")
```

Search the entire codebase: `grep -rn "sqlite3.connect" src/ --include="*.py"` — every one needs the busy_timeout pragma. The watch loop sets it in `_ensure_all_tables()` but individual module functions that open their own connections don't.

**Closes:** #160

---

## Task 7: Scan Overlap Prevention (#151)

**File:** `src/scheduler/watch.py`

**Fix:** Add a simple flag that prevents a scan from starting if the previous one hasn't finished:

```python
if self._scan_in_progress:
    logger.warning("[WATCH] Previous scan still running — skipping this cycle")
    return
self._scan_in_progress = True
try:
    self._run_scan(now)
finally:
    self._scan_in_progress = False
```

**Closes:** #151

---

## Task 8: Silent API Key Failure Alert (#124)

**File:** `src/data_enrichment/enricher.py` and all data collectors

**Fix (#124):** When an API key is missing (FRED, Finnhub, Anthropic), send a ONE-TIME Telegram alert "Missing API key: {KEY_NAME} — data collection degraded." Use a set to track which alerts have been sent so it doesn't spam.

```python
_missing_key_alerts_sent = set()

def _alert_missing_key(key_name: str):
    if key_name not in _missing_key_alerts_sent:
        _missing_key_alerts_sent.add(key_name)
        try:
            from src.notifications.telegram import send_telegram
            send_telegram(f"⚠️ Missing API key: {key_name} — data collection degraded")
        except Exception:
            pass
```

**Closes:** #124

---

## Task 9: Quick Cosmetic Fixes (#94, #96, #91)

**Fix 1 (#94):** `src/scheduler/watch.py` lines 333 and 365 — change "HALCYON LAB" to "ARCIS"

**Fix 2 (#96):** `src/evaluation/build_score.py` line 1 — change "Halcyon Lab" to "Arcis"

**Fix 3 (#91):** `src/evaluation/system_validator.py` line 534 — replace hardcoded `halcyon-lab-api.onrender.com` with env var or config: `os.environ.get("RENDER_API_URL", "https://halcyon-lab-api.onrender.com")`

**Closes:** #94, #96, #91

---

## Task 10: Documentation Update (MANDATORY)

1. Update AGENTS.md counts
2. CHANGELOG.md (Sprint 7 entry listing all closed issues)
3. Regenerate `config/known_violations.json`
4. List all issues closed by this sprint in the commit message

```bash
python -m pytest tests/ -x -q
cd frontend && npm run build && cd ..
find tests -name "test_*.py" -exec grep -c "def test_" {} + | awk -F: '{s+=$2}END{print "Tests:", s}'
```

Paste and complete sprint checklist.

---

## Issues Addressed by This Sprint

| Task | Issues Closed | Category |
|---|---|---|
| 1 | #159, #155, #157 | Watch loop crash protection |
| 2 | #90, #150 | load_dotenv + heartbeat |
| 3 | #89 | Traffic Light API stub |
| 4 | #101, #100, #105, #103 | Bracket order safety |
| 5 | #161, #130 | Render sync resilience |
| 6 | #160 | SQLite busy_timeout |
| 7 | #151 | Scan overlap prevention |
| 8 | #124 | Missing API key alerts |
| 9 | #94, #96, #91 | Cosmetic Halcyon→Arcis |
| 10 | — | Documentation |

**Total: ~22 issues closed by this sprint.**

---

## What's NOT in this sprint (for later)

- #110, #111: Training data self-blinding fixes (need careful design — Sprint 8)
- #99: Race condition on duplicate position check (needs atomic SQLite transaction design)
- #114: Holdout temporal split leakage (training pipeline redesign)
- #137, #136, #148: Security issues (frontend auth, XSS) — Sprint 8 or 9
- #149: Market holiday awareness (needs holiday calendar data source)
- #152: Computer sleep recovery (already partially addressed by UPS purchase plan)
- #123: Unbounded table growth (retention policy design needed)
- Sprint 6 Tasks 1-6: Frontend visibility (dashboard polish — separate sprint)
