# Monday Pre-Market Checklist — April 14, 2026

> **DO THIS SUNDAY NIGHT OR BEFORE 7:30 AM ET MONDAY.**
> The system has 6 hotfixes + quarantine + execution safety fixes that need
> to be deployed locally before the trading week begins.

---

## Step 1: Stop the watch loop

```powershell
# Kill any running watch loop before updating code
# Ctrl+C in the terminal running the watch loop, or:
taskkill /IM python.exe /F
```

---

## Step 2: Pull all updates

```powershell
cd C:\Users\mille\OneDrive\04 - Projects\halcyon-lab\halcyon-lab
git stash  # if you have local changes
git pull origin main
```

This pulls 6 hotfixes (v0.16.1–v0.16.6), execution safety (#348–#360), data quarantine, and the manual backfill pipeline.

---

## Step 3: Run schema fix + quarantine

```powershell
# Add the quarantined column to shadow_trades
python -m src.main validate-schema --fix

# Flag the 77 compromised records from April 10
python scripts/quarantine_april10.py
```

**Expected output from quarantine:**
```
Quarantined 42 rejected trades (buying power failures)
Quarantined ~27-34 reconciled-stale trades (no exit price)
Quarantined 1 stale WMT open trade(s)

=== QUARANTINE SUMMARY ===
Quarantined: ~70-77
Clean: ~20 (18 closed, 2 open)
Verified trades: 18, Total P&L: $603.96
```

If the numbers don't match approximately, stop and investigate.

---

## Step 4: Verify open positions match Alpaca

```powershell
python -m src.main shadow-status
```

Check that the positions shown match what's actually in your Alpaca paper account. After the cascade cleanup, you should see only legitimate open positions (CAT, CVX were the last confirmed live ones — they may have closed by now).

If there's a mismatch, run:
```powershell
python -m src.main reconcile
```

---

## Step 5: Verify LLM is responding cleanly

```powershell
python -m src.main scan --dry-run --verbose
```

This runs a full scan without writing to the journal or sending emails. Watch the output for:
- ✅ LLM produces valid XML (`<why_now>`, `<analysis>`, `<metadata>`)
- ✅ No repetition loops (the repeat_penalty fix from v0.16.4)
- ✅ No prompt leakage (the validation fix from v0.16.4)
- ❌ If you see `===` repeated or data fields echoed back, the model may need a restart

If the LLM is producing garbage, restart Ollama:
```powershell
ollama stop halcyon-v1.0.0
ollama run halcyon-v1.0.0 "test"
```

---

## Step 6: Run preflight checks

```powershell
python -m src.main preflight
```

This verifies all dependencies: Ollama running, model loaded, Alpaca API connected, database accessible, SMTP configured, Telegram configured. Everything should be green.

---

## Step 7: Run tests

```powershell
python -m pytest tests/ -x -q --ignore=tests/test_ingestion.py
```

All tests should pass. If any fail, do NOT start the watch loop — investigate first.

---

## Step 8: Start the watch loop

```powershell
python -m src.main watch --email-mode full_stream
```

Monitor the first scan cycle (7:30–8:00 AM) to confirm:
- Scans complete without errors
- Recommendations generate successfully
- Shadow trades submit to Alpaca without buying power failures
- Telegram notifications arrive
- Dashboard at halcyonlab.app shows correct numbers (18 closed trades, not 52+)

---

## What Changed Since Last Stable Run (Summary)

| Version | Fix | Impact |
|---------|-----|--------|
| v0.16.0 | Execution safety + data quarantine | Prevents cascade, quarantines bad data |
| v0.16.1 | pandas 3.0 deadlock pin | Prevents Windows startup hang |
| v0.16.2 | MR scan import path fix | Mean reversion scanning works again |
| v0.16.3 | Write-boundary type coercion | Numeric values stored as proper types (not strings) |
| v0.16.4 | LLM repeat penalty + output validation | Fixes 37% prompt leakage, repetition loops |
| v0.16.5 | Postgres auto-fix schema drift | No more manual schema fixes on Render |
| v0.16.6 | Council dynamic weights join | Council P&L tracking actually works |

---

## If Something Goes Wrong During Market Hours

1. **LLM producing bad output:** Check Telegram for alerts. If persistent, the system will auto-skip bad outputs and continue scanning.

2. **Buying power failures:** The v0.16.0 execution safety fixes now: check Alpaca positions before entry (prevents duplicates), alert after 3+ consecutive failures, and use typed exception handling.

3. **Reconciliation mismatches:** The intra-day reconciler runs every 15 minutes. It now cancels pending orders before closing stale positions and sets protective stops on backfilled orphans.

4. **Dashboard shows wrong numbers:** The quarantine filter (`COALESCE(quarantined, 0) = 0`) is applied to ALL analytics queries. If you still see 52+ trades, the quarantine script didn't run — go back to Step 3.

5. **Kill switch:** If anything looks seriously wrong:
```powershell
# Stop the watch loop
Ctrl+C

# Cancel all open orders on Alpaca
python -m src.main shadow-close-all

# Investigate
python -m src.main shadow-status
```
