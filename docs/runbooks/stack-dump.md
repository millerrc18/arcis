# Stack-Dump Runbook — ArcisWatchLoop wedge diagnostic

Capture a py-spy stack dump from a wedged ArcisWatchLoop process so the wedge can be root-caused (deadlock vs. blocking syscall vs. tight loop) before the service is restarted and the forensic state is lost.

## When to use

Run this runbook when the live-monitor agent (or an operator) detects a **watchloop wedge**: the ArcisWatchLoop service is running (NSSM reports status STARTED) but arcis.log has been silent for 20+ minutes during market hours and no in-progress task markers are visible. A py-spy stack-dump reveals whether the process is deadlocked, stuck in a blocking syscall, or looping unexpectedly.

Do NOT restart the service before capturing a dump — the dump is the forensic evidence needed to root-cause the wedge.

## Prerequisites

- **py-spy installed in the operator Python environment:**
  ```
  pip install py-spy
  ```
  py-spy is an operator diagnostic tool; it is not listed in `requirements.txt`.

- **Admin terminal capability.** The script elevates automatically via UAC (`Start-Process -Verb RunAs`). You do not need to pre-open an elevated terminal, but you must be able to approve UAC prompts on this machine.

- **PowerShell 7+ (pwsh.exe).** The script uses `Start-Process -RedirectStandardOutput` which requires pwsh, not Windows PowerShell 5.

## Invocation

**Automatic PID discovery (preferred):**
```powershell
pwsh.exe scripts/dump_watchloop.ps1
```

The script queries the NSSM registry key for ArcisWatchLoop's supervised PID first, then falls back to scanning python.exe command lines for `arcis|watch`.

**Explicit PID:**
```powershell
pwsh.exe scripts/dump_watchloop.ps1 -ProcessId 12345
```

Use this when NSSM is not installed or the service has a non-standard name.

## Expected output

On success the script prints the absolute path of the dump file:

```
C:/arcis/halcyon-lab/logs/py-spy-watchloop-20260527T143201.txt
```

The dump file contains a stack trace for every thread in the Python process, for example:

```
Thread 1 (active): "MainThread"
    File "src/scheduler/watch.py", line 312, in run_once
    File "src/data_collection/collectors/finnhub.py", line 88, in fetch
    File ".../httpx/_client.py", line 1020, in send
    ...
```

## What to look for

| Pattern | Likely cause |
|---------|-------------|
| All threads blocked in `socket.recv` / `httpx` / `requests` | Network call hung — check external API timeout config |
| Main thread looping in collector code with no sleep | Tight loop / missing `await` or `time.sleep` — CPU spin |
| `threading.Lock.acquire` / `RLock` across multiple threads | Deadlock between two competing locks |
| `time.sleep` with a very large value | Accidental over-long backoff after error |
| `select` / `poll` in OS-level call (GIL held by another thread) | GIL contention — one thread holding GIL during C-extension call |
| `subprocess.Popen.communicate` or `subprocess.wait` | Child process hung — check ollama or model subprocess |

Cross-reference the file and line numbers against `C:/arcis/halcyon-lab/logs/arcis.log` to find the last successful log entry before the silence. The gap between that entry and the wedge onset narrows the root cause.

## After the dump

1. Save the dump file (it lands in `C:/arcis/halcyon-lab/logs/` automatically).
2. File a GitHub issue with the dump attached if the root cause is non-obvious.
3. Restart the service only after the dump is saved:
   ```
   nssm restart ArcisWatchLoop
   ```
   Avoid restarting between 21:30–22:30 ET (overnight re-launch window).
