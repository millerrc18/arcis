# IB Gateway 24/7 stability on Windows 11: a complete operational guide

**IB Gateway can achieve 98–99% market-hours uptime over 30 days, but it is architecturally designed around mandatory daily restarts and weekly re-authentication — true "set and forget" operation is impossible.** Your biggest operational risks on this specific system are the weekly Sunday 2FA requirement (which cannot be fully automated for live accounts), RAM contention between IB Gateway, Ollama, and Python processes on 24GB, and NVIDIA GPU driver instability triggering system-wide crashes. With proper IBC automation, Windows hardening, and a disciplined monitoring stack, practitioners report running for weeks with only 1–2 unplanned interventions per month.

---

## How IB Gateway's daily lifecycle actually works

IB Gateway is designed to restart every single day. This is non-negotiable and built into Interactive Brokers' architecture at two distinct levels: the client application restart and the server-side infrastructure reset.

The **client-side auto-restart** defaults to **11:45 PM in the system's local timezone**. When triggered, the Gateway process shuts down and relaunches — a "soft restart" that reuses existing authentication credentials, requiring no 2FA. Practitioners report the actual downtime is **30 seconds to 2 minutes**. This time is configurable via Configure → Lock and Exit → Auto Restart in the Gateway UI, or through IBC's `AutoRestartTime` setting. IB explicitly recommends setting this restart "sometime during the internal reset times 23:45–00:45 ET."

The **server-side reset** for North America runs from **00:15 ET to 01:45 ET** (Sunday through Friday). IB's official language clarifies this is a window, not continuous downtime: "It does not indicate that the entire system will be unavailable for the full reset period." QuantConnect, which runs thousands of live IB accounts, reports actual unavailability of **15–30 minutes**, with reconnection typically completing by 12:45 AM. During this window, all API connections drop, simulated orders (IB-side stop orders, trailing stops) are delayed, but native exchange-held orders continue operating normally. GTC orders persist through daily resets and are only cancelled at end of the next calendar quarter, on corporate actions, or after 90 days of account inactivity.

**Weekend behavior introduces the hardest constraint.** IB runs a full system shutdown every Friday from **23:00 ET to Saturday 03:00 ET** — a 4-hour complete outage across all regions. More critically, IB invalidates all authentication tokens **every Sunday at 01:00 ET**, forcing full re-authentication with 2FA before the new trading week. The earliest successful re-login is approximately **Sunday 4:00 PM ET**, one hour before forex markets open. This weekly forced logout cannot be disabled, bypassed, or automated for live trading accounts. It is a hard manual intervention point — you must approve the 2FA notification on your phone every Sunday.

---

## The failure modes that will actually bite you

### Memory leaks are real but manageable

IB Gateway runs on a bundled JVM (switched from Oracle Java 8 to **Azul Zulu Java 17** starting with Gateway 1035 on Windows, as of early 2025). The default heap is **768 MB** (`-Xmx768m`), configured in `C:\Jts\tws.vmoptions`. Baseline memory consumption sits at **123–150 MB** for basic operation, roughly 40% less than full TWS.

**The documented memory leak is specific and severe**: subscribing to options chains (particularly ATM options with greeks/model computation across multiple expirations) can exhaust the heap within a single trading day, producing `java.lang.OutOfMemoryError: Java heap space`. IB acknowledged this and released memory optimization patches, but users on Elite Trader disputed the effectiveness. If you trade equities or futures without heavy options data, the leak is far less aggressive — the daily mandatory restart effectively resets it.

An additional client-side leak exists in ib_insync: the `reqRealTimeBars` method returns a `BarDataList` that **grows infinitely** — bars are appended but never removed. Long-running Python processes using this will eventually crash with OOM regardless of Gateway health.

IB recommends a maximum heap of **2 GB** and explicitly warns against going higher. On your 24GB system shared with Ollama and Python, **1024–1536 MB** is the sweet spot — enough headroom for market data subscriptions while leaving room for co-resident processes.

### JVM crashes, version traps, and API limits

Outright JVM crashes are rare with proper heap configuration — practitioners on Elite Trader report going "several years" without a crash during weekday operation. The most common non-OOM failure is a startup error during auto-restart: the log message "Attempted to append to non-started appender d" appears somewhat randomly and causes the restart sequence to fail, requiring manual intervention. IBC issues #25 and #41 document this.

**Version management is a recurring operational hazard.** IB periodically retires old Gateway versions by refusing login — Gateway 10.23 was retired as of March 20, 2025, for example, requiring upgrade to 10.30.1+. These retirements are announced weeks to months in advance via in-app messages. The Java 8 to Java 17 transition broke older versions of IBC, requiring IBC 3.21.0+ on Linux and 3.22.0+ on Windows. NinjaTrader dropped IB Gateway support entirely in early 2025 after failing to keep pace with these changes.

**API connection limit is 32 simultaneous clients** per Gateway instance, each requiring a unique `clientId` integer. ClientId 0 has special behavior (merges with manual trading). Market data lines are separate — defaulting to 100 per user, with pacing limited to 50 requests per second. Breaking pacing limits three times terminates the API session with `WinError 10053`.

### Windows 11 will fight you unless you fight back

Windows 11's aggressive power management is the single most common cause of "mysterious disconnections" reported by algo traders. The OS puts network adapters to sleep, enables Modern Standby (S0 Low Power Idle), runs background maintenance tasks, and will force-restart the machine for updates — all of which are catastrophic for 24/7 Gateway operation.

**Network adapter sleep** is especially insidious: Windows 11 can power down both WiFi and Ethernet adapters even on a desktop. The Power Management tab in Device Manager may be hidden for certain adapters on Windows 11. Realtek NICs are particularly problematic — disable Energy Efficient Ethernet, Ultra Low Power Mode, and System Idle Power Saver in the advanced adapter properties.

**Windows Update is the nuclear risk.** Even on Windows 11 Pro, Active Hours max out at an 18-hour window — insufficient for 24/7 coverage. The mitigation stack requires multiple layers of defense (detailed in the configuration section below).

---

## The configuration playbook for maximum stability

### IBC: the essential automation layer

IBC (IB Controller), hosted at `github.com/IbcAlpha/IBC` with 1.4k stars, is the standard tool for automating IB Gateway lifecycle. The current release is **IBC 3.23.0** (July 2025), which is required for Gateway 1035+ on Windows due to the Java 17 transition.

IBC works by loading Gateway as a subprocess and monitoring it via Java's accessibility framework. It auto-fills login credentials, dismisses popups, and manages the daily restart cycle. The critical `config.ini` settings for your setup:

```ini
IbLoginId=your_username
IbPassword=your_password
TradingMode=live
AutoRestartTime=11:45 PM
ColdRestartTime=Sun 08:00
ReloginAfterSecondFactorAuthenticationTimeout=yes
SecondFactorAuthenticationExitInterval=60
ExistingSessionDetectedAction=primaryoverride
```

**IBC handles daily soft restarts reliably but does not handle process crashes.** If the Gateway JVM crashes outright, IBC (running in the same context) may also die. You need an external watchdog — either Windows Task Scheduler (IBC 3.20.0+ includes a template) or a custom PowerShell script checking every 1–5 minutes:

```powershell
$process = Get-Process -Name "ibgateway" -ErrorAction SilentlyContinue
if (-not $process) {
    Start-Process "C:\IBC\StartGateway.bat"
    # Send alert notification
}
```

The ib_insync library (now archived after the maintainer's passing in March 2024; succeeded by **ib_async** v2.1.0) includes a `Watchdog` class that integrates IBC control with reconnection logic. It monitors the connection, sends probe requests, and triggers a full Gateway restart via IBC if probes fail. Manual reconnection using `disconnectedEvent` callbacks with exponential backoff is the other common production pattern.

### Windows 11 hardening: the complete PowerShell script

Apply all of these settings on your dedicated trading machine:

```powershell
# === POWER MANAGEMENT ===
powercfg -duplicatescheme e9a42b02-d5df-448d-aa00-03f14749eb61  # Ultimate Performance
powercfg /change standby-timeout-ac 0
powercfg /change monitor-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /change disk-timeout-ac 0
powercfg /hibernate off

# USB selective suspend off
powercfg -attributes 2a737441-1930-4402-8d77-b2bebba308a3 48e6b7a6-50f5-4782-a5d4-53bb8f07e226 -ATTRIB_HIDE
powercfg /SETACVALUEINDEX SCHEME_CURRENT 2a737441-1930-4402-8d77-b2bebba308a3 48e6b7a6-50f5-4782-a5d4-53bb8f07e226 0

# PCI Express ASPM off
powercfg /SETACVALUEINDEX SCHEME_CURRENT 501a4d13-42af-4429-9fd1-a8218c268e20 ee12f906-d277-404b-b6da-e5fa1a576df5 0

# Processor min/max 100%
powercfg /SETACVALUEINDEX SCHEME_CURRENT 54533251-82be-4824-96c1-47b60b740d00 893dee8e-2bef-41e0-89c6-b55d0929964c 100
powercfg /SETACVALUEINDEX SCHEME_CURRENT 54533251-82be-4824-96c1-47b60b740d00 bc5038f7-23e0-4960-96da-33abaf5935ec 100
powercfg /SETACTIVE SCHEME_CURRENT

# Disable Modern Standby
reg add "HKLM\System\CurrentControlSet\Control\Power" /v PlatformAoAcOverride /t REG_DWORD /d 0

# === WINDOWS UPDATE CONTROL ===
reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate" /v DeferFeatureUpdatesPeriodInDays /t REG_DWORD /d 365
reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate" /v DeferQualityUpdatesPeriodInDays /t REG_DWORD /d 14

# === DISABLE NOISE SERVICES ===
Stop-Service "WSearch" -Force; Set-Service "WSearch" -StartupType Disabled
Stop-Service "DiagTrack" -Force; Set-Service "DiagTrack" -StartupType Disabled
Stop-Service "SysMain" -Force; Set-Service "SysMain" -StartupType Disabled

# === DEFENDER EXCLUSIONS ===
Add-MpPreference -ExclusionPath "C:\Jts"
Add-MpPreference -ExclusionPath "C:\IBC"
Add-MpPreference -ExclusionProcess "java.exe"
Add-MpPreference -ExclusionProcess "javaw.exe"
Set-MpPreference -ScanScheduleDay 1  # Sunday only
Set-MpPreference -ScanScheduleTime "03:00:00"

# === NETWORK ADAPTER ===
Disable-NetAdapterPowerManagement -Name "*"
```

Additionally, via Group Policy (`gpedit.msc`):
- **Sleep Settings** → "Allow Standby States (S1-S3) When Sleeping (Plugged In)" → Disabled
- **Windows Update** → "No auto-restart with logged on users" → Enabled
- **Configure Automatic Updates** → Option 4, schedule to Sunday 3 AM
- **Device Installation** → "Do not include drivers with Windows Update" → Enabled

For the Task Scheduler, disable UpdateOrchestrator reboot tasks at `Task Scheduler Library > Microsoft > Windows > UpdateOrchestrator` — disable **Reboot_AC** and **Schedule Scan**. Windows may re-enable these after feature updates, so verify periodically.

Windows Defender real-time scanning has a **documented significant impact on Java applications** (confirmed by JetBrains, Eclipse, and Microsoft's own java-wdb project). The exclusions above for `C:\Jts`, `java.exe`, and `javaw.exe` are essential. Do not completely disable Defender — the machine connects to the internet for IB Gateway connectivity.

### Firewall rules and API port configuration

IB Gateway uses **port 4001** (live) or **4002** (paper) for inbound API connections, and connects outbound to IB servers on port 443 and various market data farm ports. Create explicit rules:

```powershell
New-NetFirewallRule -DisplayName "IB Gateway Outbound" -Direction Outbound `
    -Program "C:\Jts\ibgateway\<version>\jre\bin\java.exe" -Action Allow
New-NetFirewallRule -DisplayName "IB Gateway API" -Direction Inbound `
    -LocalPort 4001 -Protocol TCP -Action Allow -RemoteAddress 127.0.0.1
```

---

## Your RTX 3060 and Ollama: the co-residency risk matrix

**IB Gateway does not use the GPU at all** — there is zero direct GPU resource contention with Ollama. The risk is entirely indirect: GPU driver instability causing system-wide failures.

### The TDR problem is real and specific

Windows' Timeout Detection and Recovery (TDR) mechanism resets the GPU driver if it doesn't respond within **2 seconds** (default). Ollama inference kernels on an RTX 3060 can exceed this threshold, especially with larger models or long context windows. A TDR event itself won't kill IB Gateway — the screen flickers, the driver resets, and non-GPU processes continue. But if TDR recovery **fails** (5+ hangs within 1 minute), Windows triggers a BSOD (Bug Check 0x116 — VIDEO_TDR_FAILURE), which takes down everything.

**Increase the TDR timeout to 30–60 seconds** via registry:
```
HKEY_LOCAL_MACHINE\System\CurrentControlSet\Control\GraphicsDrivers
TdrDelay (DWORD) = 30
```

### Memory budget is tight at 24GB

This is your most significant architectural concern. Here's the realistic allocation:

| Component | RAM Budget |
|-----------|-----------|
| Windows 11 OS overhead | 3–4 GB |
| IB Gateway (Java heap) | 0.75–1 GB |
| Python processes + FastAPI | 2.5–5 GB |
| Ollama (system RAM spillover) | 2–4 GB |
| Page cache and buffers | 4–6 GB |
| **Total estimated** | **12–20 GB** |

When RAM exceeds ~85–90% utilization, Windows begins paging to disk, causing latency spikes that can affect IB Gateway's responsiveness to market data. Ollama is the wild card: it uses system RAM in addition to VRAM when models don't fit entirely in the RTX 3060's 12GB VRAM. A 7–8B parameter model at Q4_K_M quantization consumes roughly 4–5GB VRAM, but KV cache and overhead can spill into system RAM.

**Critical Ollama settings for co-residency:**
```
OLLAMA_MAX_LOADED_MODELS=1
OLLAMA_KEEP_ALIVE=60        # Unload after 60 seconds idle
OLLAMA_KV_CACHE_TYPE=q8_0   # Halve KV cache memory
```

Set IB Gateway to **Above Normal** process priority and Ollama to **Below Normal**. Process Lasso (bitsum.com) can persist these settings across restarts. On your Ryzen's 12+ cores, CPU contention is unlikely unless Ollama falls back to CPU inference when VRAM is exhausted — this would spike all cores to 100% and starve Gateway's network I/O threads.

### NVIDIA driver management for production

**Uninstall GeForce Experience entirely.** Install only the driver component manually from nvidia.com, preferring **Studio Drivers** over Game Ready for stability. Block Windows Update from pushing GPU drivers via Group Policy ("Do not include drivers with Windows Update" → Enabled) and via Device Installation Settings (Settings → System → About → Advanced → Hardware → "No"). Pin to a known-stable driver version and only update during scheduled Saturday maintenance windows.

---

## What practitioners actually achieve in production

The most instructive data comes from operators who have run IB Gateway for months to years:

- **Elite Trader user "Val"** runs a Dockerized setup with IBC and auto-healing health checks. Reports "approximately one failure on a startup per month" and the ability to "disconnect for 1–2 weeks" without issues. Problems are "found every other month and typically dealt with after-hours."

- **QuantConnect** operates thousands of live IB accounts using their IBAutomater tool (open-source, C#/.NET, Apache 2.0 license). Their architecture handles soft restarts automatically and sends push notifications for Sunday 2FA.

- **Juri Sarbach's cloud robo-advisor** on Google Kubernetes Engine uses Kubernetes liveness probes to detect and auto-restart frozen Gateway instances. He describes Gateway's "tendency to hang, cause a burst in memory usage, lose connection, or log you out" as the core operational challenge.

- **Hartza Capital** runs production on AWS ECS with Docker containers (2048 MB memory, 1024 CPU units), using IBC for automation with multiple release channels (stable/latest/nightly).

The consensus across these case studies: **99%+ market-hours uptime is achievable** with proper automation, but the system requires active monitoring and a 5–10 minute weekly Sunday ritual. "Production-grade" for IB Gateway means automated daily restarts, health monitoring with alerting, and planned weekly 2FA re-login. It does not mean unattended 30-day operation.

---

## Designing your 30-day validation gate

### What to measure

Track these metrics continuously throughout the validation period:

- **Gateway uptime ratio**: minutes connected divided by minutes expected (target: ≥98% during market hours)
- **Daily restart success rate**: auto-restarts succeeding without intervention (target: 100%)
- **Unexpected disconnections**: count and duration, categorized by cause (IB server reset vs. local failure)
- **Java heap trajectory**: plot heap usage over time to detect leaks — a sawtooth pattern peaking near max is normal GC behavior; sustained near-max is a leak
- **System RAM utilization**: overall committed memory, with alerts at 80% (target: never paging during market hours)
- **IB API error frequency**: specifically error codes 1100 (connectivity lost), 1102 (connectivity restored, data lost), and 502 (can't connect)
- **GPU TDR events**: monitor Windows Event Log Event ID 4101 ("Display driver stopped responding")
- **Order execution fidelity**: orders placed vs. orders confirmed (target: 100%)

### Pass/fail criteria

Define these thresholds before starting:

- **Pass**: ≥98% market-hours uptime, ≤2 unplanned interventions per month, zero BSOD events, zero OOM crashes, zero missed trades, all daily restarts succeed automatically, system RAM never exceeds 85% during market hours
- **Fail**: any BSOD, >3 unplanned interventions, persistent memory leak (heap not recovered after daily restart), missed trade due to Gateway failure, system paging causing measurable latency during market hours

### Issues that emerge only after 1–2 weeks

Several failure modes are invisible during short tests. Java memory leaks with options data subscriptions accumulate gradually, becoming critical only after days of continuous operation. Ollama model accumulation in RAM (if `OLLAMA_KEEP_ALIVE` is set too high) compounds over sessions. Windows Update can accumulate deferred updates and eventually force a restart. IB Gateway log files grow and can consume significant disk space with Detail-level logging. And network micro-interruptions that the daily restart masks can reveal underlying NIC power management issues only during extended runs.

### Failure simulation tests to run before going live

Before starting the 30-day clock, execute each of these scenarios and verify recovery:

1. Kill the Java process (`taskkill /F /IM java.exe`) and verify IBC + Task Scheduler restart it
2. Disconnect the network cable for 60 seconds and verify Gateway reconnects
3. Run Ollama at full GPU utilization during market data streaming and verify Gateway responsiveness
4. Intentionally trigger a TDR (run a GPU stress test like FurMark) and verify IB Gateway survives the driver reset
5. Walk through the complete Sunday 2FA re-login process end to end
6. Simulate the daily 11:45 PM restart and verify your Python application reconnects and resubscribes to market data
7. Let the system run over a full weekend and verify Monday morning behavior

---

## Conclusion: what this means for your architecture

IB Gateway on Windows 11 is a viable platform for 24/7 algorithmic trading, but it demands respect for its architectural constraints. **The daily restart is a feature, not a bug** — it prevents memory leaks and refreshes contract definitions. The weekly Sunday 2FA is the single hardest constraint and the one most likely to cause a missed trading session if you're unavailable.

Your 24GB RAM is the tightest resource. Ollama sharing system memory with a Java heap, multiple Python processes, and FastAPI creates a realistic risk of paging under load. **Upgrading to 32GB would eliminate the most probable failure mode.** If upgrading isn't possible, strictly enforce `OLLAMA_MAX_LOADED_MODELS=1` and aggressive model unloading.

The optimal stack for your specific system: **IBC 3.23.0** for Gateway automation, **Windows Task Scheduler** as the crash-recovery watchdog, **ib_async** (successor to ib_insync) with `Watchdog` class or manual `disconnectedEvent` handling for Python-side reconnection, the complete Windows hardening script above, NVIDIA Studio Drivers pinned to a stable version with TDR timeout increased to 30 seconds, and a monitoring dashboard tracking the metrics listed in the validation gate section. Budget for one mandatory 5-minute Sunday intervention and 1–2 unplanned interventions per month. With this configuration, **98–99% market-hours uptime over 30 days is a realistic and achievable target.**