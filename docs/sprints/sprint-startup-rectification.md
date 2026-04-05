# Sprint: Startup Rectification + Log Cleanup — Production-Ready for 24/7

> **Priority:** CRITICAL — system goes 24/7 Monday morning
> **Estimated time:** 3-5 hours CC time
> **Access:** Remote OK — pure code changes
> **Why:** We just added IB integration (v0.14.0). The startup validation (`src/startup.py`) doesn't know IB exists. The daily audit baseline is stale (12 "expected failures" that were fixed months ago). And the logs show errors that need fixing before we trust 24/7 operation.

---

## Pre-Flight

1. Read `MASTER.md`
2. Read `src/startup.py` — current startup checks
3. Read `src/trading/broker_factory.py` — IB config structure
4. Read `config/settings.example.yaml` — IB settings section
5. Run `python -m pytest tests/ -x -q` — baseline

---

## Task 1: Add IB Gateway connectivity check to startup

**File:** `src/startup.py` — `check_connectivity()`

Currently checks: Alpaca, Ollama, Render Postgres. Missing: IB Gateway.

**Add this check when `live_trading.broker == "ib"`:**

```python
# IB Gateway (only when broker is "ib")
live_cfg = config.get("live_trading", {})
if live_cfg.get("broker") == "ib":
    ib_cfg = live_cfg.get("ib", {})
    host = ib_cfg.get("host", "127.0.0.1")
    port = ib_cfg.get("port", 4002)
    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        result = sock.connect_ex((host, port))
        sock.close()
        if result == 0:
            mode = "paper" if port == 4002 else "live" if port == 4001 else f"port {port}"
            results.append(CheckResult(
                name="ib_gateway", category="connectivity", status="ok",
                detail=f"IB Gateway reachable at {host}:{port} ({mode})",
                fix_hint="Start IB Gateway and enable API connections",
            ))
        else:
            results.append(CheckResult(
                name="ib_gateway", category="connectivity", status="critical",
                detail=f"IB Gateway not reachable at {host}:{port}",
                fix_hint="Start IB Gateway. Configure → API → Enable Socket Clients. Port 4002 (paper) or 4001 (live).",
            ))
    except Exception as e:
        results.append(CheckResult(
            name="ib_gateway", category="connectivity", status="critical",
            detail=f"IB Gateway check failed: {str(e)[:60]}",
            fix_hint="Start IB Gateway and verify API settings",
        ))
```

**Also add IB config validation to `check_config()`:**

```python
# IB credentials check (when broker is "ib")
if live_cfg.get("broker") == "ib":
    ib_port = live_cfg.get("ib", {}).get("port")
    if not ib_port:
        results.append(CheckResult(
            name="config_ib", category="config", status="warn",
            detail="IB port not configured — using default 4002 (paper)",
            fix_hint="Set live_trading.ib.port in settings.local.yaml (4002=paper, 4001=live)",
        ))
    elif ib_port == 4001:
        results.append(CheckResult(
            name="config_ib_live", category="config", status="warn",
            detail="IB configured for LIVE trading (port 4001)",
            fix_hint="Verify this is intentional. Use port 4002 for paper testing.",
        ))
```

**Test:** Add test for IB connectivity check (mock socket).

---

## Task 2: Update daily audit baseline

**File:** `config/daily_repo_audit_baseline.json`

The baseline lists 12 "expected failures" from issues #40-#50 — **all of which are closed.** These should no longer be expected failures. They should either pass now, or be removed from the expected list.

**Steps:**
1. Run the daily audit locally: `python scripts/daily_repo_audit.py --output-dir audit-test`
2. Check which of the 12 expected failures now pass
3. Remove the ones that pass from the `expected_failures` list
4. If any still fail (despite the issue being closed), investigate and fix
5. Update the baseline to reflect current state

**The goal:** `python scripts/daily_repo_audit.py` should run clean with zero unexpected failures.

---

## Task 3: Add IB health check to watch loop

**File:** `src/scheduler/watch.py`

During market hours, if `broker == "ib"`, periodically check that IB Gateway is still connected. If disconnected:
1. Log a WARNING
2. Send Telegram alert (market hours only)
3. Skip live trades (paper continues normally)
4. Attempt reconnection on next scan cycle

**Add this to the 60-minute heartbeat block:**

```python
# IB Gateway health check (if broker is "ib")
if self.config.get("live_trading", {}).get("broker") == "ib":
    try:
        from src.trading.broker_factory import get_live_broker
        broker = get_live_broker(self.config)
        if not broker.is_connected():
            logger.warning("[WATCH] IB Gateway disconnected during market hours")
            # Send Telegram alert
            try:
                from src.notifications.telegram import send_telegram, is_telegram_enabled
                if is_telegram_enabled():
                    send_telegram("⚠️ IB Gateway disconnected during market hours. "
                                  "Live trades paused. Paper continues.")
            except Exception:
                pass
    except Exception as e:
        logger.warning("[WATCH] IB health check failed: %s", e)
```

---

## Task 4: Add `startup` command IB awareness

**File:** `src/cli/commands.py` — `cmd_startup()`

The startup command should:
1. Show IB connection status if `broker == "ib"`
2. Show a WARNING if IB Gateway is configured but unreachable
3. Show which port (4001 vs 4002) and what that means (live vs paper)

---

## Task 5: Fix log errors

**[RYAN: PASTE LOG OUTPUT BELOW THIS LINE]**

<!--
Ryan will paste the halcyon.log errors here. For each error:
1. Identify the root cause
2. Open a GitHub issue
3. Add the fix to this sprint

Example format:
ERROR 2026-04-04 10:30:15 [WATCH] VIX refresh failed: ...
→ Root cause: yfinance Timestamp.utcnow deprecation
→ Fix: Already fixed in v0.11.0, verify
→ Issue: #XXX
-->

---

## Task 6: Update startup tests

**File:** `tests/test_startup.py`

Add tests for:
- IB connectivity check passes when socket accepts connection
- IB connectivity check fails gracefully when socket refuses
- IB config validation warns on port 4001 (live)
- IB config validation warns when port not set
- Daily audit baseline is current (no stale expected_failures)

---

## Verification

```bash
python -m pytest tests/ -x -q  # Pass count ≥ baseline
python -m src.main startup     # Should show IB status
python scripts/daily_repo_audit.py --output-dir /tmp/audit  # Zero unexpected failures
```

---

## Commit

```bash
git add -A
git commit -m "fix: startup rectification — IB validation, audit baseline, log cleanup

- check_connectivity: IB Gateway socket check when broker='ib'
- check_config: IB port validation (4001 live warning, 4002 paper)
- watch loop: IB health check on 60-min heartbeat
- cmd_startup: IB connection status display
- Daily audit baseline updated (12 stale expected_failures removed)
- Log errors fixed: [list from Task 5]

Startup is now production-ready for 24/7 operation with IB."
```
