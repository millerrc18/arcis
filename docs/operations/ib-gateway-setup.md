# IB Gateway Setup Guide -- Paper Trading on Windows 11

**Audience:** Operator (you).  
**Goal:** Get IB Gateway running on the Arcis trading machine with IBC automation, validated for the 30-day stability gate before any live trading migration.

---

## 1. Prerequisites

Before starting, you need:

- **Interactive Brokers account** with paper trading enabled (account starts with `DU`).
  Apply at [ibkr.com](https://www.interactivebrokers.com). Paper trading is available
  immediately after account approval -- no funding required.
- **IBKR Mobile app** installed on your phone for 2FA confirmations.
- **IB Gateway** (not full TWS) -- lighter, no GUI overhead. Download the **stable** channel
  from [ibkr.com/en/trading/ibgateway-stable.php](https://www.interactivebrokers.com/en/trading/ibgateway-stable.php).
  Install to the default `C:\Jts` directory.
- **IBC** (IB Controller) -- download from [github.com/IbcAlpha/IBC/releases](https://github.com/IbcAlpha/IBC/releases).
  Version 3.23.0+ required for Gateway 1035+ (Java 17 transition). Extract to `C:\IBC`.
- **ib_async** Python library -- already installed in the Arcis venv:
  ```
  .venv\Scripts\python.exe -c "import ib_async; print(ib_async.__version__)"
  ```

---

## 2. IBC Configuration

Edit `C:\IBC\config.ini` with these settings:

```ini
IbLoginId=your_paper_username
IbPassword=your_paper_password
TradingMode=paper

# Daily soft restart -- Gateway shuts down and relaunches (no 2FA needed)
AutoRestartTime=11:45 PM

# Weekly cold restart -- full re-login after Sunday token expiration
ColdRestartTime=Sun 08:00

# 2FA handling
ReloginAfterSecondFactorAuthenticationTimeout=yes
SecondFactorAuthenticationExitInterval=60

# If another session is detected, take over (critical for restarts)
ExistingSessionDetectedAction=primaryoverride
```

**Important:** For paper trading, set `TradingMode=paper`. When you eventually move to live,
you will change this to `live` and update credentials. The validate script refuses port 4001
as a safety net.

---

## 3. Windows Hardening

IB Gateway needs uninterrupted 24/7 operation. Windows 11 will fight you unless you
configure it properly. Run the following PowerShell commands as Administrator:

### Power Management

```powershell
# Enable Ultimate Performance power plan
powercfg -duplicatescheme e9a42b02-d5df-448d-aa00-03f14749eb61
powercfg /change standby-timeout-ac 0
powercfg /change monitor-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /change disk-timeout-ac 0
powercfg /hibernate off

# Disable Modern Standby (S0 Low Power Idle)
reg add "HKLM\System\CurrentControlSet\Control\Power" /v PlatformAoAcOverride /t REG_DWORD /d 0
```

### Windows Update Control

```powershell
# Defer feature updates 365 days, quality updates 14 days
reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate" /v DeferFeatureUpdatesPeriodInDays /t REG_DWORD /d 365
reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate" /v DeferQualityUpdatesPeriodInDays /t REG_DWORD /d 14
```

Via Group Policy (`gpedit.msc`):
- **Windows Update** > "No auto-restart with logged on users" > Enabled
- **Configure Automatic Updates** > Option 4, schedule to Sunday 3 AM
- **Device Installation** > "Do not include drivers with Windows Update" > Enabled

Disable UpdateOrchestrator reboot tasks in Task Scheduler:
`Task Scheduler Library > Microsoft > Windows > UpdateOrchestrator` -- disable **Reboot_AC**
and **Schedule Scan**. Re-check after each feature update.

### Defender Exclusions

```powershell
Add-MpPreference -ExclusionPath "C:\Jts"
Add-MpPreference -ExclusionPath "C:\IBC"
Add-MpPreference -ExclusionProcess "java.exe"
Add-MpPreference -ExclusionProcess "javaw.exe"

# Schedule full scans for Sunday only, 3 AM
Set-MpPreference -ScanScheduleDay 1
Set-MpPreference -ScanScheduleTime "03:00:00"
```

Do NOT disable Defender entirely -- the machine connects to the internet.

### Disable Noise Services

```powershell
Stop-Service "WSearch" -Force; Set-Service "WSearch" -StartupType Disabled
Stop-Service "DiagTrack" -Force; Set-Service "DiagTrack" -StartupType Disabled
Stop-Service "SysMain" -Force; Set-Service "SysMain" -StartupType Disabled
```

### Network Adapter

```powershell
Disable-NetAdapterPowerManagement -Name "*"
```

Also check Device Manager > Network adapter > Properties > Power Management and uncheck
"Allow the computer to turn off this device to save power." For Realtek NICs, also disable
Energy Efficient Ethernet, Ultra Low Power Mode, and System Idle Power Saver in advanced
adapter properties.

### TDR Fix (GPU driver timeout -- critical for Ollama co-residency)

Windows resets the GPU driver if it does not respond within 2 seconds. Ollama inference
can exceed this, causing BSOD if recovery fails repeatedly. Increase the timeout:

```
Registry: HKEY_LOCAL_MACHINE\System\CurrentControlSet\Control\GraphicsDrivers
TdrDelay (DWORD) = 30
```

---

## 4. Java Heap Configuration

Edit `C:\Jts\tws.vmoptions`:

```
-Xmx1536m
```

On the Arcis machine (24GB RAM shared with Ollama and Python), 1024-1536 MB is the sweet
spot. IB recommends a maximum of 2 GB. The daily restart at 11:45 PM resets any heap
accumulation, so aggressive sizing is unnecessary for equity-only data.

Default (768 MB) is sufficient for basic operation but may be tight if you subscribe to
options chains or many streaming market data lines.

---

## 5. IB Gateway API Settings

After starting Gateway for the first time:

1. **Configure > Settings > API > Settings:**
   - Check "Enable ActiveX and Socket Clients"
   - Set Socket port to **4002** (paper -- never 4001 for validation)
   - Check "Download open orders on connection" (critical for reconnection)
   - Set Master API client ID if desired (0 merges with manual trading)
   - Uncheck "Read-Only API" (required for order submission)

2. **Configure > Settings > API > Precautions:**
   - Review the bypass settings -- for paper trading, you can bypass
     order confirmation popups to allow automated order submission.

3. **Market data subscriptions:**
   - In Account Management, subscribe to "US Securities Snapshot and Futures Value Bundle"
     (~$10/month non-professional). This covers all S&P 100 equities.
   - Non-professional classification: confirm your status in Account Management.
     Paper accounts typically auto-qualify as non-professional.

---

## 6. First Connection Test

With IB Gateway running and API enabled on port 4002, run the validation script:

```bash
.venv\Scripts\python.exe scripts/validate_ib_gateway.py --port 4002
```

The script performs 5 checks:
1. Connects to IB Gateway on the configured port
2. Verifies the account is a paper account (starts with `D`)
3. Qualifies 10 S&P 100 contracts (AAPL, MSFT, AMZN, GOOGL, META, NVDA, JPM, V, JNJ, PG)
4. Reads buying power and net liquidation value
5. Takes a market data snapshot on AAPL

**Expected output:** All 5 checks pass. If market data fails, the market may be closed or
the data subscription is not yet active (can take up to 24 hours after subscribing).

**Safety:** The script refuses to connect to port 4001 (live trading). This is a hard block.

---

## 7. Sunday 2FA Procedure

IB invalidates all authentication tokens every Sunday at 01:00 ET. The earliest successful
re-login is approximately Sunday 4:00 PM ET.

**Weekly ritual (~5 minutes):**

1. Sunday afternoon, after 4:00 PM ET, check if Gateway is logged out
   (IBC log or Gateway status window will show "Disconnected")
2. IBC will automatically attempt re-login and send a 2FA challenge
3. Approve the IBKR Mobile app notification on your phone
4. Verify Gateway reconnects (status shows "Connected" or API port is responsive)
5. Run the validation script to confirm:
   ```bash
   .venv\Scripts\python.exe scripts/validate_ib_gateway.py
   ```

If IBC does not trigger re-login automatically, manually restart via:
```powershell
& C:\IBC\StartGateway.bat
```

This cannot be automated for live accounts. Plan for 5 minutes every Sunday afternoon.

---

## 8. Troubleshooting

### Error 502: Couldn't connect to TWS

- IB Gateway is not running, or API is not enabled
- Check: Is Gateway showing "Connected" in its status bar?
- Check: Is API enabled in Configure > Settings > API?
- Check: Is the port correct (4002 for paper)?
- Try restarting Gateway via IBC: `C:\IBC\StartGateway.bat`

### Error 1100: Connectivity between IB and TWS has been lost

- IB's servers are unreachable (network issue or IB outage)
- Action: **Stop all trading immediately.** Do not submit new orders
- Wait for reconnection (usually automatic within 1-5 minutes)
- If during the daily reset window (00:15-01:45 ET), this is expected

### Error 1102: Connectivity restored -- data lost

- Connection recovered but market data state is stale
- Action: **Full state reconciliation required**
  - Call `ib.positions()` to verify position state
  - Call `ib.openOrders()` to verify order state
  - Compare against local SQLite state
  - Resume trading only after reconciliation passes

### Memory Issues (Java OOM, high RAM)

- Check Gateway heap: look for `java.lang.OutOfMemoryError` in IB Gateway logs
  (located in `C:\Jts\ibgateway\<version>\` or `C:\Jts\`)
- If heap is exhausted, increase `-Xmx` in `tws.vmoptions` (max 2GB)
- Check system RAM: if above 85%, Ollama may be holding too many models
  - Verify `OLLAMA_MAX_LOADED_MODELS=1` and `OLLAMA_KEEP_ALIVE=60`
- The daily restart at 11:45 PM resets heap -- if OOM happens mid-day, the
  leak is likely from options data subscriptions (not relevant for equity-only)

### Gateway Won't Start After Update

- IB periodically retires old Gateway versions (refuses login)
- Download the latest stable Gateway from the IB website
- Ensure IBC version is compatible (3.23.0+ for Gateway 1035+)
- Check IBC logs in `C:\IBC\Logs\` for specific error messages

---

## 9. Monitoring (daily_ib_health table)

The `daily_ib_health` table in the schema registry tracks Gateway stability metrics
for the 30-day validation gate. One row per day with these metrics:

| Column | What to watch |
|--------|--------------|
| `uptime_pct` | Target >= 98% during market hours |
| `trade_count` | Paper trades executed that day |
| `error_count` | IB API errors (1100, 1102, 502, etc.) |
| `reconnect_count` | Unplanned reconnections (target: 0) |
| `gateway_version` | Track version changes |
| `market_hours_connected_min` | Minutes connected during 9:30-16:00 ET |
| `market_hours_expected_min` | Expected minutes (390 on full trading days) |
| `notes` | Free text for incidents |

### 30-day stability gate pass/fail criteria

- **Pass:** >= 98% market-hours uptime, <= 2 unplanned interventions per month,
  zero BSOD events, zero OOM crashes, all daily restarts succeed automatically
- **Fail:** Any BSOD, > 3 unplanned interventions, persistent memory leak,
  system paging causing latency during market hours

### What to check daily

1. Was the 11:45 PM auto-restart successful? (Check IBC logs)
2. Is Gateway connected this morning? (Run validate script or check status)
3. Any IB API errors in overnight logs?
4. System RAM utilization (should be below 85%)
5. Record the day's metrics in `daily_ib_health`

The 30-day clock starts when you first achieve 3 consecutive clean trading days.
Do not rush this -- the stability gate exists to protect the live trading migration.
