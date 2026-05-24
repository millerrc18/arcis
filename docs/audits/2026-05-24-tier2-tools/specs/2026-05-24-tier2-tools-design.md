# Arcis #106 Tier 2 Tools — Design Spec

## 1. Overview

Five composable Python-API + CLI tools that build on the #104 safety foundation (`src/tools/_config.py`, `_safety.py`, `_execution_log.py`) AND the #105 Tier 1 frozen patterns (subpackage layout, `_db.py`, `_cli_envelope.py`, dual-render markdown/JSON, sub-module-when-needed). Release target = **v0.36.63 assuming #105 merges as v0.36.62 first; PM re-baselines version atomically at implementation time** (lesson from #105: brief said v0.36.57, actual main was v0.36.61).

| Tool | Purpose | Mutates | Seam |
|------|---------|---------|------|
| **ProcessManager** | nssm wrapper for service status/start/stop/restart | restart/start/stop only | `nssm` CLI + `tasklist`/`taskkill` (Windows) |
| **HealthProbe** | Composite NSSM-state + port + heartbeat + recent-error counts | no | nssm CLI + socket + filesystem |
| **PRComments** | Post + read PR comments with secret-shape pre-flight | post only | `gh` CLI |
| **CapabilityRegistryQuery** | Inspect `src.schema.registry.TABLES` | no | Python import of frozen data |
| **TestPatternScan** | AST-based detector for vacuous tests + @patch drift | no | Python `ast` module |

### 1.1 Role in the broader roadmap (SECOND-FOUNDATION inheritance)

The Tier-1 + Tier-2 combined surface is the substrate every downstream layer inherits:

- **#107 Tier 3** — ContractCheck (uses CapabilityRegistryQuery + DBQuery), GitArchaeology (subprocess house pattern from PRComments).
- **#108 specialized agents** — db-investigator (DBQuery + CapabilityRegistryQuery), ci-investigator (CIInvestigate + PRComments), live-monitor (ProcessManager + HealthProbe), git-historian.
- **#109 `arcis:operate`** — invokes ProcessManager.restart + HealthProbe + PRComments via `python -m src.tools.<name>` subprocess + `--json` envelope.
- **#110 `arcis:strategy`** — TradingState + DBQuery composition.
- **#111 periodic discipline** — TestPatternScan in CI, HealthProbe in cron, skill-audit reads tool-execution.log written by every Tier 1/2 tool.

## 2. Architecture

### 2.1 Module layout (delta from current `src/tools/`)

```
src/tools/
  __init__.py                   (UNCHANGED)
  _config.py                    (MODIFIED — PathsConfig pydantic model gains watchdog_heartbeat field; see §3.1 + DD-10)
  _safety.py                    (UNCHANGED, #104)
  _execution_log.py             (MODIFIED — _VALID_RESULTS gains 'secret_leak_block')
  _db.py                        (UNCHANGED, #105)
  _cli_envelope.py              (UNCHANGED, #105)
  _secrets.py                   (NEW — detect_secret_in_text(body) helper; see §3.3)
  _subprocess.py                (NEW — shared subprocess.run wrapper with timeout + nssm/gh-resolved-once)
  processmanager/
    __init__.py | __main__.py | core.py | nssm.py | taskkill.py    (5 files — sub-module split, see §4.8)
  healthprobe/
    __init__.py | __main__.py | core.py | checks.py                (4 files — checks.py owns the 4 per-service probes)
  prcomments/
    __init__.py | __main__.py | core.py                            (3 files)
  capabilityregistry/
    __init__.py | __main__.py | core.py                            (3 files)
  testpatternscan/
    __init__.py | __main__.py | core.py | rules.py                 (4 files — rules.py owns AST detectors per rule)

config/arcis_config.yaml         (MODIFIED — paths.watchdog_heartbeat default added; see §3.1 + DD-10)

tests/tools/
  test_safe_op_integration.py   (UNCHANGED, keystone)
  test_execution_log.py         (MODIFIED — parametrize enum coverage + frozenset-equality assertion; FB1)
  test_secrets.py               (NEW)
  test_processmanager_integration.py (NEW)
  test_healthprobe_integration.py    (NEW)
  test_prcomments_integration.py     (NEW)
  test_capabilityregistry_integration.py (NEW)
  test_testpatternscan_integration.py    (NEW)

CHANGELOG.md                    (MODIFIED)
src/version.py                  (MODIFIED — v0.36.62 → v0.36.63)
tests/test_version.py           (MODIFIED — literal bump)
```

Net new files: 22 source/test + 5 modified (was 3; +2 from FB1 test_execution_log + FB2 _config.py + config/arcis_config.yaml). Still within the brief's ~25 new files + 3-5 modified budget.

### 2.2 Forbidden imports (reviewer grep-list — Tier-2 inherits Tier-1 + adds Tier-2 anti-patterns)

Every file under `src/tools/<name>/` and `tests/tools/test_<name>_*.py` MUST NOT contain any of:

```
from src.config
import src.config
from src.utils.db
import src.utils.db
os.environ.get('DATABASE_URL'
os.getenv('DATABASE_URL'
load_dotenv
subprocess.run(.*shell=True
```

**Exception (operator-confirmed):** `from src.schema.registry import TABLES` is PERMITTED in `src/tools/capabilityregistry/core.py` ONLY. The import pulls module-level frozen data, no runtime apparatus. Documented in §3.4.

**Tier-2-new sibling anti-patterns to NOT reintroduce (with file:line citations):**

- `src/scheduler/watch.py:130-147` — `_sc_query_running` (no timeout + bare `except Exception: return False`). DO NOT replicate in ProcessManager.status or HealthProbe.
- `src/scheduler/watch.py:1161-1163` — `tick_watchdog_liveness` wraps the already-soft `_sc_query_running` in ANOTHER `except Exception: is_running = False` — DOUBLE-SOFT swallow. Tier-2 tools surface typed errors uncaught.
- `scripts/archive_bootcamp_2026_04_24.py:166-167` — silent FileNotFoundError on missing `nssm` (acceptable for one-shot script, NOT for ProcessManager). Tier-2 raises `NssmMissingError(SubprocessError)` with PATH suggestion.
- `scripts/archive_bootcamp_2026_04_24.py:157-169` — NEGATIVE state parsing (`'SERVICE_STOPPED' not in stdout`). ProcessManager uses POSITIVE substring matches per §3.1.
- `src/scheduler/watch.py:1722-1734` + `scripts/statusline.py:38-55` — CWD-RELATIVE `Path('data/watchdog.txt')` (write) paired with discovery-based `_resolve_data_root()` (read). Tier-2 ProcessManager + HealthProbe consume `cfg.paths.watchdog_heartbeat` (explicit config key, decoupled from db_canonical's location) — see §3.1 + DD-10. DO NOT replicate the cwd-relative-write OR the multi-path discovery walk in new code.

### 2.3 Shared helpers introduced by Tier 2

**`src/tools/_secrets.py`** — content-driven secret scanner (KEY-driven `_SECRET_KEY_PATTERNS` in `_execution_log.py` is insufficient for PRComments body text):

**DA3-revised pattern list:** The original 9 regex patterns had a substantial false-negative class for a tool whose CONTRACT is preventing leaks. Per DA3 remediation, the pattern list is extended to cover GitHub server/user tokens, GitLab PATs, Stripe live keys, JWT shape, and a high-entropy fallback. Precision/recall trade-off documented inline. The first 14 patterns are HIGH-confidence (known prefixes); the high-entropy fallback is LOW-confidence and produces a separate code path the caller (PRComments.post) treats identically for blocking purposes but the audit row labels distinctly so operators can override via a doc comment if needed.

```python
# Purpose: Content-based secret detector for free-text bodies (PRComments).
# Called by: src/tools/prcomments/core.py
# Calls: re
# Owns tables: none
# Config keys: none
# Tests: tests/tools/test_secrets.py

import re

# HIGH-CONFIDENCE patterns — known prefixes for live token formats.
_BODY_SECRET_PATTERNS = [
    re.compile(r'\bghp_[A-Za-z0-9]{20,}\b'),                          # GitHub personal access token
    re.compile(r'\bgithub_pat_[A-Za-z0-9_]{20,}\b'),                  # GitHub fine-grained PAT
    re.compile(r'\bgho_[A-Za-z0-9]{20,}\b'),                          # GitHub OAuth
    re.compile(r'\bghs_[A-Za-z0-9]{36,}\b'),                          # GitHub server-to-server (DA3 — currently live in this org)
    re.compile(r'\bghu_[A-Za-z0-9]{36,}\b'),                          # GitHub user-to-server (DA3)
    re.compile(r'\bglpat-[A-Za-z0-9_\-]{20,}\b'),                     # GitLab personal access token (DA3)
    re.compile(r'\bsk-[A-Za-z0-9]{20,}\b'),                           # OpenAI / Anthropic-style
    re.compile(r'\bsk_live_[A-Za-z0-9]{24,}\b'),                      # Stripe live secret key (DA3)
    re.compile(r'\bpk_live_[A-Za-z0-9]{24,}\b'),                      # Stripe live publishable key (DA3)
    re.compile(r'\bxox[abprs]-[A-Za-z0-9-]{10,}\b'),                  # Slack tokens
    re.compile(r'\beyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]{20,}\b'),  # JWT 3-segment (DA3)
    re.compile(r'(?i)\b(password|api[_-]?key|secret|token)\s*[=:]\s*[^\s]{6,}'),     # `password=xyz` shapes
    re.compile(r'(?i)\bauthorization:\s*bearer\s+[^\s]{10,}'),        # Bearer headers
    re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----'),                # PEM key blocks
    re.compile(r'\bAKIA[0-9A-Z]{16}\b'),                              # AWS access key id
]

# LOW-CONFIDENCE fallback — any 40+ char alphanumeric/base64-like run that did NOT match a known prefix above.
# Catches: AWS secret access keys (40-char base64), generic high-entropy tokens, unknown vendor formats.
# Trade-off: higher false-positive rate; operator can override via a doc-comment 'this is a test fixture'
# style if a legitimate string trips this (the PR body still blocks — the override is editorial on the source).
_HIGH_ENTROPY_PATTERN = re.compile(r'\b[A-Za-z0-9+/]{40,}\b')

def detect_secret_in_text(body: str) -> tuple[bool, str, str]:
    """Scan body for token-shaped substrings.

    Returns (is_leak, redacted_preview, kind):
      - is_leak: True if ANY known-prefix pattern OR high-entropy fallback hit
      - redacted_preview: body with ***REDACTED*** substituted
      - kind: 'known_prefix' if any of _BODY_SECRET_PATTERNS hit, else 'high_entropy_unknown'
              (purely a label for the audit row; both kinds block equally)
    """
    redacted = body
    known_hit = False
    for pat in _BODY_SECRET_PATTERNS:
        if pat.search(redacted):
            known_hit = True
            redacted = pat.sub('***REDACTED***', redacted)
    if known_hit:
        return True, redacted, 'known_prefix'
    # No known prefix hit — try high-entropy fallback.
    if _HIGH_ENTROPY_PATTERN.search(redacted):
        redacted = _HIGH_ENTROPY_PATTERN.sub('***REDACTED***', redacted)
        return True, redacted, 'high_entropy_unknown'
    return False, body, 'none'
```

**Precision/recall trade-off (DA3 documented):** The known-prefix patterns are HIGH precision (vanishingly few false positives — strings starting with `ghp_` or `sk_live_` etc. are essentially always real tokens). The high-entropy fallback is MEDIUM precision (40-char base64 runs can include legitimate test fixtures, git SHAs combined with paths, base64-encoded test data); it is included because the CONTRACT of PRComments leak-detection is preventing leaks, and AWS secret access keys + generic vendor tokens have no recognizable prefix. Net effect: false-positive rate is acceptable for an interactive operator-facing tool (the body is rejected at the CLI; operator inspects the redacted preview and decides whether to edit + retry). The kind label `'high_entropy_unknown'` lets periodic skill-audit (#111) measure the false-positive rate empirically over time.

**`src/tools/_subprocess.py`** — single-source `nssm.exe` / `gh.exe` resolution + the canonical subprocess wrapper (replaces inline `subprocess.run` calls across ProcessManager/HealthProbe/PRComments):

```python
# Purpose: shared subprocess wrappers for Tier-2 CLI tools.
# Called by: src/tools/processmanager/nssm.py, healthprobe/checks.py, prcomments/core.py
# Calls: subprocess.run, shutil.which
# Owns tables: none
# Config keys: none
# Tests: indirect (via each tool's integration test)

import shutil, subprocess
from functools import lru_cache

class NssmMissingError(subprocess.SubprocessError):
    """Raised when nssm.exe cannot be located on PATH."""

class GhMissingError(subprocess.SubprocessError):
    """Raised when gh.exe cannot be located on PATH."""

@lru_cache(maxsize=4)
def resolve_exe(name: str) -> str:
    """Return absolute path to executable on PATH (cached). Raise if missing."""
    exe = shutil.which(name)
    if not exe:
        if name == 'nssm':
            raise NssmMissingError(f'nssm not on PATH. Install via choco install nssm or download from https://nssm.cc/')
        if name == 'gh':
            raise GhMissingError(f'gh not on PATH. Install via winget install GitHub.cli or https://cli.github.com/ (>= 2.0 required for --body-file - stdin)')
        raise subprocess.SubprocessError(f'{name} not on PATH')
    return exe

def run(args: list[str], *, timeout: int = 10, check: bool = False, input_data: str | None = None) -> subprocess.CompletedProcess:
    """Standardized subprocess.run. NEVER shell=True. Always capture_output, text, encoding='utf-8'."""
    return subprocess.run(args, capture_output=True, text=True, encoding='utf-8', timeout=timeout, check=check, input=input_data)
```

### 2.4 Decorator stack — Tier 2 augmentations

Decorator order is OUTER→INNER: `@safe_op` → `@safety_window` → `@prod_guard` → function. Tier-2 stacks per tool (`@prod_guard` is OMITTED where no DSN parameter exists):

| Tool / API | Stack |
|------------|-------|
| ProcessManager.status | `@safe_op(mutates=False)` |
| ProcessManager.start | `@safe_op(mutates=True)` |
| ProcessManager.stop | `@safe_op(mutates=True)` |
| ProcessManager.restart | `@safe_op(mutates=True)` → `@safety_window('no_restart_overnight')` |
| HealthProbe.check | `@safe_op(mutates=False)` |
| PRComments.read | `@safe_op(mutates=False)` |
| PRComments.post | `@safe_op(mutates=True)` (NO safety_window — GitHub writes are low-risk + rate-limited) |
| CapabilityRegistryQuery.tables/.table | `@safe_op(mutates=False)` |
| TestPatternScan.scan | `@safe_op(mutates=False)` |

**Why no `@prod_guard` anywhere in Tier 2:** none of the Tier-2 tools take a DSN parameter. ProcessManager talks to NSSM/Windows; HealthProbe talks to NSSM + sockets + filesystem; PRComments talks to gh; CapabilityRegistryQuery reads frozen Python data; TestPatternScan reads filesystem.

**Why `@safety_window` ONLY on ProcessManager.restart:** per scout finding, the `no_restart_overnight` window exists specifically to prevent mid-cycle restart redundant-relaunch (operator memory `feedback_no_restart_during_overnight_window`). start/stop/post-comment are NOT under the window. ProcessManager.restart is the FIRST production consumer of `safety_windows.no_restart_overnight` per scout report. The decorator's pluggable `now_et` seam (per `_safety.py:291-324`) is already in place for tests.

### 2.5 Audit-log result kinds — Tier-2 extension

`_VALID_RESULTS` in `src/tools/_execution_log.py:50-56` is the frozen enumeration. Tier-2 adds ONE new kind:

```python
_VALID_RESULTS = frozenset({
    'success', 'dry_run', 'safety_window_block', 'prod_guard_block', 'error',
    'secret_leak_block',   # NEW — emitted by PRComments.post on PRCommentLeakError
})
```

This is the ONLY modification to #104 frozen infrastructure. Grep-able dedicated kind so periodic skill-audit (#111) can count leak-block events distinctly from generic 'error'.

**Test-side exhaustiveness guarantee (FB1):** `tests/tools/test_execution_log.py:192-194` parametrizes the existing 5-kind enum and MUST be updated atomically with the source extension. Two changes required in the same task (see Task 2 in plan):
1. Add `'secret_leak_block'` to the parametrize list at line ~193.
2. Add an explicit frozenset-equality assertion: `assert _VALID_RESULTS == frozenset({'success','dry_run','safety_window_block','prod_guard_block','error','secret_leak_block'})` — guards against silent drift if a future change extends the enum without updating the test.

## 3. Per-tool design

### 3.1 ProcessManager (`src/tools/processmanager/`)

**Purpose:** Operator-facing wrapper around `nssm` for the 3 Arcis services (ArcisWatchLoop, ArcisOllamaWatchdog, ArcisDashboard). Inherits CLEAN pattern from `scripts/archive_bootcamp_2026_04_24.py:155-169` (timeout=10, list-args, capture_output, text=True) but with POSITIVE state parsing and typed errors.

**Foundation config extension (FB2 — DD-10):** ProcessManager.restart's wait-and-verify step 4 needs the canonical absolute path to `watchdog.txt`. The watch loop writes via CWD-relative `Path('data/watchdog.txt')` at `src/scheduler/watch.py:1722-1734`, which resolves to `<NSSM AppDirectory>/data/watchdog.txt`. `scripts/statusline.py:38-55` has a `_resolve_data_root()` walk that papers over this. Tier-2 declines BOTH options (cwd-relative-derived OR statusline-discovery) and instead introduces an EXPLICIT config key:

```yaml
# config/arcis_config.yaml — paths section gains:
paths:
  watchdog_heartbeat: "C:/arcis/halcyon-lab/data/watchdog.txt"   # operator-confirmed actual location
```

```python
# src/tools/_config.py — PathsConfig pydantic model gains:
class PathsConfig(BaseModel):
    # ... existing fields ...
    watchdog_heartbeat: Path = Path("C:/arcis/halcyon-lab/data/watchdog.txt")
```

**Why an explicit config key (DD-10):**
1. **Explicit** — operator sees the key in `arcis_config.yaml`; no hidden discovery walk.
2. **Decoupled from `db_canonical.parent`** — original spec resolved via `cfg.paths.db_canonical.parent / 'watchdog.txt'` = `C:/arcis/data/watchdog.txt`, but NSSM AppDirectory is `C:/arcis/halcyon-lab` → actual heartbeat is `C:/arcis/halcyon-lab/data/watchdog.txt`. Hard-link to db_canonical would ALWAYS report `verified=False, log_evidence=None`.
3. **Future-proof against SQLite-PG cutover** — `db_canonical`'s location may change again post-cutover; the heartbeat path should not move sympathetically.
4. **Decouples ProcessManager from statusline's `_resolve_data_root()` discovery** — statusline is a status-line script; ProcessManager is a foundation tool. Inheritance from a sibling script would create cross-domain coupling.

Statusline can opt-into the new key in a follow-up (out-of-scope for #106; the discovery walk continues to work as-is).

**Sub-module split (per §4.8 — TradingState precedent):**

- `core.py` (≤300 LOC) — decorated entry points: `status(service)`, `start(service, *, confirm=False)`, `stop(service, *, confirm=False)`, `restart(service, *, confirm=False, emergency=False)`. Service-alias resolution via `cfg.services.{watch_loop|ollama_watchdog|dashboard}`. Accepts either alias (`'watch'`, `'watch_loop'`) OR full NSSM name (`'ArcisWatchLoop'`).
- `nssm.py` (≤250 LOC) — pure subprocess wrappers: `nssm_status(service) -> ServiceState`, `nssm_start/stop/restart(service) -> CompletedProcess`. Wait-and-verify protocol (see below).
- `taskkill.py` (≤150 LOC) — PID-scoped force-stop escalation, used ONLY if `nssm stop` times out. Mirrors `src/scheduler/ollama_watchdog.py:180-260` verbatim: `tasklist /fo csv /nh /fi 'imagename eq <exe>'` discovery; PID-scoped `taskkill /f /t /pid <pid>` then PowerShell `Stop-Process -Id <pid> -Force` escalation. **NEVER `/im`, NEVER by name (line 226-227 discipline).**

**Python API:**

```python
from dataclasses import dataclass
from enum import Enum

class ServiceState(str, Enum):
    RUNNING = 'RUNNING'
    STOPPED = 'STOPPED'
    STARTING = 'STARTING'        # SERVICE_START_PENDING
    STOPPING = 'STOPPING'        # SERVICE_STOP_PENDING
    PAUSED = 'PAUSED'
    PAUSE_PENDING = 'PAUSE_PENDING'
    CONTINUE_PENDING = 'CONTINUE_PENDING'
    UNKNOWN = 'UNKNOWN'           # nssm output not parseable

@dataclass(frozen=True)
class RestartResult:
    restarted: bool         # nssm restart returned 0
    verified: bool          # service reached RUNNING + log evidence within window
    elapsed_s: float        # wall-clock seconds
    log_evidence: str | None  # filename + mtime that proved liveness, or None
    state: ServiceState     # final observed state

def status(service: str) -> ServiceState: ...
def start(service: str, *, confirm: bool = False) -> ServiceState: ...
def stop(service: str, *, confirm: bool = False) -> ServiceState: ...
def restart(service: str, *, confirm: bool = False, emergency: bool = False) -> RestartResult: ...
```

**POSITIVE state parsing (CRITICAL CALL-OUT):** `nssm status` returns one of: `SERVICE_STOPPED`, `SERVICE_START_PENDING`, `SERVICE_STOP_PENDING`, `SERVICE_RUNNING`, `SERVICE_CONTINUE_PENDING`, `SERVICE_PAUSE_PENDING`, `SERVICE_PAUSED`. The mapping table uses POSITIVE substring matches in this order (first match wins):

```python
_STATE_MAP = [
    ('SERVICE_RUNNING',          ServiceState.RUNNING),
    ('SERVICE_START_PENDING',    ServiceState.STARTING),
    ('SERVICE_STOP_PENDING',     ServiceState.STOPPING),
    ('SERVICE_CONTINUE_PENDING', ServiceState.CONTINUE_PENDING),
    ('SERVICE_PAUSE_PENDING',    ServiceState.PAUSE_PENDING),
    ('SERVICE_PAUSED',           ServiceState.PAUSED),
    ('SERVICE_STOPPED',          ServiceState.STOPPED),
]
# Iteration order matters — SERVICE_STOPPED is the substring of nothing else,
# but it's listed LAST so SERVICE_STOP_PENDING / SERVICE_START_PENDING / etc.
# match their pending variants first (defensive, even though substring uniqueness holds).
```

**Wait-and-verify protocol (restart) — DA2-revised with SUSTAINED-RUNNING flap detection:** Operator-confirmed requirement — fire-and-forget REJECTED. The protocol must detect NSSM AppRestartDelay flapping (service crashes immediately, NSSM auto-restarts; a single RUNNING observation during the flap-then-relaunch transient can mislead the poll into a false-positive `verified=True`).

1. Record `restart_start_monotonic = time.monotonic()` and `restart_start_walltime = time.time()`.
2. `nssm_restart(service)` returns; check returncode.
3. **SUSTAINED-RUNNING poll (DA2):** Poll `nssm_status(service)` every 1.0s up to **30s initial deadline**. On the FIRST `RUNNING` observation, enter SUSTAINED-WINDOW: continue polling 3 more times (additional 3s) at 1.0s intervals — ALL 3 follow-up observations must remain `RUNNING`. If ANY follow-up observation is NOT `RUNNING` (STARTING/STOPPING/STOPPED/UNKNOWN/PAUSED), the sustained-window timer **resets** — the poll re-enters the initial-deadline phase. The OVERALL deadline is **33s** (30s initial + up to 3s sustained window); the initial-deadline timer continues to run during sustained-window evaluation (a flap reset does not extend the 30s initial budget — it just means we're still in the initial phase). On 3-consecutive-RUNNING success, exit poll loop with `elapsed_s = time.monotonic() - restart_start_monotonic` and proceed to step 4.
4. Verify log evidence within **5s window** AFTER sustained-running confirmation:
   - For ArcisWatchLoop: `cfg.paths.watchdog_heartbeat` (NEW config key per DD-10 above — defaults to `C:/arcis/halcyon-lab/data/watchdog.txt`) mtime must be ≥ `restart_start_walltime`.
   - For ArcisDashboard: `cfg.paths.logs_runtime / 'arcis-dashboard.log'` mtime must be ≥ `restart_start_walltime`.
   - For ArcisOllamaWatchdog: `cfg.paths.logs_runtime / 'arcis-ollama-watchdog.log'` mtime must be ≥ `restart_start_walltime`.
5. Return `RestartResult(restarted=True, verified=<log_evidence_seen>, elapsed_s=..., log_evidence=<filepath if seen else None>, state=<final>)`.

If step 3 33s overall deadline elapses without 3-consecutive-RUNNING → `RestartResult(restarted=True, verified=False, elapsed_s=~33.0, log_evidence=None, state=<last observation>)`. The caller (operator / agent / #109 `arcis:operate`) decides what to do; `verified=False` is the explicit signal to escalate.

If step 4 timeout elapses without log evidence → still return RestartResult with `verified=False` — service might be technically running but hasn't emitted a heartbeat (transient launch hang). Don't escalate to taskkill from restart() — escalation is operator-decided.

**Why SUSTAINED-RUNNING matters (DA2 rationale, recorded as DD-16):** NSSM's AppRestartDelay (default ~1500ms) auto-restarts a crashed service. If our service crashes within the first 1-2 seconds after `nssm restart`, the poll sequence can be: `STARTING → RUNNING (1ms before crash) → STOPPED → STARTING → RUNNING (now stable from auto-restart)`. The original single-observation protocol would exit on the first RUNNING and proceed to step 4. The mtime advance on the heartbeat file FROM THE PREVIOUS (now-dead) PROCESS could satisfy the `>= restart_start_walltime` check (the dying process wrote one last heartbeat just before crashing). The 3-consecutive-RUNNING window catches the flap by observing the STOPPED/STARTING in between. Downstream #109 `arcis:operate` consumes `RestartResult.verified` to decide whether to escalate to taskkill or page the operator — a false `verified=True` skips needed escalation.

**Errors:**

```python
class ProcessManagerError(RuntimeError): pass            # base
class NssmMissingError(SubprocessError): pass            # from _subprocess.resolve_exe
class UnknownServiceError(ProcessManagerError): pass      # service alias not in cfg.services
class NssmCommandFailedError(ProcessManagerError): pass    # nssm returncode != 0
# SafetyWindowError raised by @safety_window on restart inside overnight window
```

**CLI:** `python -m src.tools.processmanager <verb> <service> [--confirm] [--emergency] [--json]`

Markdown output (status):
```
# Service Status
| Service              | State    |
|----------------------|----------|
| ArcisWatchLoop       | RUNNING  |
```

Markdown output (restart success):
```
# Restart Result: ArcisWatchLoop
- restarted: True
- verified:  True
- elapsed:   3.2s
- evidence:  C:/arcis/halcyon-lab/data/watchdog.txt mtime 2026-05-24T14:32:01-04:00
- state:     RUNNING
```

### 3.2 HealthProbe (`src/tools/healthprobe/`)

**Purpose:** Composite read-only health check for incident response. Operator-facing aggregation that the existing `src/api/routes/health.py` does NOT cover — health.py is DB-centric (trading system gates), HealthProbe is process/service-centric (Are the services running? Are ports listening? Is the log stale?). The two are orthogonal — confirmed by scout.

**Sub-module split:**

- `core.py` (≤250 LOC) — `check(*, services=None, stale_seconds=None)` orchestrator + verdict aggregation. Default services = all three from cfg.
- `checks.py` (≤300 LOC) — 4 per-service probe functions:
  - `_check_service_state(service) -> ServiceState` (re-uses ProcessManager.nssm.nssm_status — IMPORT, not duplicate code; HealthProbe does NOT mutate so this import is a read-only public surface).
  - `_check_port(port, host='127.0.0.1') -> bool` — `socket.socket().connect_ex((host, port))` with 0.5s timeout. Non-binding.
  - `_check_heartbeat(path, max_age_s) -> tuple[bool, str | None]` — subsumes `scripts/statusline.py:72-84` (`_heartbeat_fresh`): reads watchdog.txt as ISO timestamp, treats no-tz as UTC, returns (fresh, reason). Reasons: 'file_missing' / 'parse_error' / f'age={N}s>threshold={M}s' / None on fresh. Path resolved from `cfg.paths.watchdog_heartbeat` (DD-10) — NO `_resolve_data_root()` discovery walk.
  - `_check_recent_errors(log_path, window_minutes=15) -> int` — count ERROR/CRITICAL lines in last N minutes. Uses LogTail.tail() internally (`from src.tools.logtail import tail` — Tier-1 → Tier-2 inheritance per §1.1).

**HARD PRECONDITION (FB3):** HealthProbe requires #105 to be MERGED on main with `src/tools/logtail/` exporting `tail`. Implementation MUST verify at the start of Task 4 (HealthProbe) that `from src.tools.logtail import tail` is importable. No fallback path — if the dependency is missing, the task blocks and surfaces via AskUserQuestion. Rationale: a fallback file-tail would silently degrade error-count accuracy; mandating the merge guarantees one canonical tail implementation.

**Python API:**

```python
from typing import TypedDict

class ServiceHealth(TypedDict):
    service: str                # NSSM name e.g. 'ArcisWatchLoop'
    state: str                  # ServiceState.value
    heartbeat_fresh: bool | None
    heartbeat_reason: str | None
    port_listening: bool | None # None if no associated port
    recent_error_count: int
    verdict: str                # 'OK' | 'DEGRADED' | 'DOWN'

class ProbeResult(TypedDict):
    services: dict[str, ServiceHealth]
    overall: str                # worst-of: 'OK' | 'DEGRADED' | 'DOWN'
    as_of_et: str               # ISO timestamp ET

def check(*, services: list[str] | None = None, stale_seconds: int | None = None) -> ProbeResult: ...
```

**Per-service staleness thresholds (operator-confirmed in brief):**

| Service                | Default staleness | Heartbeat source |
|------------------------|-------------------|------------------|
| ArcisWatchLoop         | 60s               | `cfg.paths.watchdog_heartbeat` (ISO content) |
| ArcisDashboard         | 300s (5min)       | `cfg.paths.logs_runtime/arcis-dashboard.log` mtime |
| ArcisOllamaWatchdog    | 30s               | `cfg.paths.logs_runtime/arcis-ollama-watchdog.log` mtime |

CLI override: `--stale-seconds N` applies to ALL services uniformly. Future v2 may add per-service yaml config (out of scope v1).

**Port-reachability table:**

| Service             | Port checked |
|---------------------|--------------|
| ArcisWatchLoop      | none (no listener) |
| ArcisDashboard      | `cfg.ports.cloud_api.range_start` (8000) — first port in dashboard's range |
| ArcisOllamaWatchdog | `cfg.ports.ollama` (11434) |

Non-binding `socket.connect_ex` with 0.5s timeout. Returns True if connect_ex == 0 (accepting connections).

**Verdict matrix per service:**

| state    | heartbeat | port    | verdict   |
|----------|-----------|---------|-----------|
| RUNNING  | fresh     | listening (or N/A) | OK |
| RUNNING  | stale     | any     | DEGRADED |
| RUNNING  | any       | not listening (where applicable) | DEGRADED |
| STARTING / STOPPING / PAUSED | any | any | DEGRADED |
| STOPPED / UNKNOWN | any | any | DOWN |

Overall = worst-of all per-service verdicts (OK < DEGRADED < DOWN).

**Errors:** `HealthProbeError(RuntimeError)` for catastrophic failure (cfg load fails). Per-service failures are absorbed into the verdict (DOWN with reason) — HealthProbe always returns a result; it never raises just because a service is down.

**CLI:** `python -m src.tools.healthprobe [--services NAME[,NAME...]] [--stale-seconds N] [--json]`

Markdown output:
```
# Health Probe (2026-05-24T14:32:01-04:00)

## Overall: DEGRADED

| Service              | State   | Heartbeat | Port | Recent Errors (15m) | Verdict   |
|----------------------|---------|-----------|------|---------------------|-----------|
| ArcisWatchLoop       | RUNNING | fresh (2s) | N/A  | 0                  | OK        |
| ArcisDashboard       | RUNNING | STALE (412s>300s) | 8000 listening | 3 | DEGRADED |
| ArcisOllamaWatchdog  | STOPPED | file_missing | 11434 not listening | 1 | DOWN |
```

### 3.3 PRComments (`src/tools/prcomments/`)

**Purpose:** Wrapper around `gh pr comment` (post) + `gh pr view --json comments` (read), with pre-flight secret-shape detection (operator-confirmed: `PRCommentLeakError` on leak detection; manual scrub required before retry).

**Greenfield call-out:** ZERO existing `gh pr` / `gh run view` Python callers in the codebase per scout finding. PRComments is precedent-setting for `gh-from-Python` — adopts subprocess house style verbatim (list-args + `capture_output=True` + `text=True` + `encoding='utf-8'` + `timeout=N`, NEVER `shell=True`).

**Single-file (`core.py` ≤350 LOC).**

**External preconditions (FB6):**

- **Minimum `gh` CLI version: `>= 2.0`** — required for `--body-file -` stdin support (added in gh 2.0.0, August 2021). PRComments does NOT pre-flight `gh --version`; we rely on the gh-side error if a too-old binary is encountered (gh emits a clear "unknown flag" stderr). Error is surfaced as `GhCommandFailedError` with stderr verbatim. The `>= 2.0` requirement is documented in `_subprocess.GhMissingError` message text (when gh is absent) and in the CLI `--help` text.
- **Authentication precondition:** PRComments does NOT call `gh auth status` proactively. We rely on gh's own auth-failure error (returncode != 0 with stderr like `error: authentication required, run 'gh auth login'`). The error is surfaced as `GhCommandFailedError(returncode=N, stderr='<gh's auth message>', hint='Run `gh auth status` then `gh auth login` if needed.')`. Hint is embedded in the exception's message string. No silent retry, no auto-login.
- **GitHub secondary rate-limit handling:** PRComments does NOT implement retry/backoff. If GitHub rate-limits, gh's stderr (e.g., `HTTP 403: API rate limit exceeded for user ID...` or secondary-limit messages) is surfaced VERBATIM in `GhCommandFailedError.stderr`. Caller (operator / agent / #109 `arcis:operate`) decides retry policy — Tier-2 PRComments stays simple.

**Python API:**

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class PRComment:
    author: str       # GitHub login
    body: str         # comment text
    created_at: str   # ISO timestamp
    url: str          # comment URL

def read(pr: int, *, repo: str | None = None) -> list[PRComment]: ...
def post(pr: int, body: str, *, confirm: bool = False, repo: str | None = None) -> dict: ...
# post returns {'pr': pr, 'comment_url': '...'} on success
```

**Secret-leak pre-flight (post only):** Before invoking `gh pr comment`, body is scanned via `_secrets.detect_secret_in_text(body)`. If `is_leak=True`:

1. Raise `PRCommentLeakError` (NEW subclass of `RuntimeError` — NOT `SafetyError`, because this is a tool-internal check, not a decorator guard).
2. Error message includes the redacted preview (first 500 chars of `redacted_preview`).
3. `@safe_op` catches the exception; rather than the default `'error'` event, PRComments.post handles it specially: BEFORE raising PRCommentLeakError, it calls `write_event(..., result='secret_leak_block', params={'pr': pr, 'body_redacted': redacted_preview[:500]})` directly with the new result kind. Then raises. `@safe_op` sees the exception, but the dedicated write_event call has already landed the audit row — `@safe_op`'s wrapper writes ANOTHER `'error'` event (this is acceptable: the `secret_leak_block` row carries the redacted body for forensics; the `'error'` row is the standard catch-all). Two-event pattern matches the existing safe_op + safety_window 2-event behavior on block.

**Why NOT raise `SafetyError`:** SafetyError is reserved for time-of-day / DSN-signature guards (#104 contract at `_safety.py:56-70`). Body-content scanning is a tool-specific concern, not a cross-cutting safety primitive. Future Tier-3 could elevate to a `@content_guard` decorator if the pattern recurs.

**Gh invocation patterns:**

- **Read:** `gh pr view <PR> --json comments [-R <repo>]` → parse JSON `result.stdout` → map `comments[]` → `PRComment(author=c['author']['login'], body=c['body'], created_at=c['createdAt'], url=c['url'])`.
- **Post:** `gh pr comment <PR> --body-file - [-R <repo>]` with `input_data=body` to stdin. **stdin pipe (not `--body <string>`)** to sidestep shell-escaping issues for arbitrary content. Requires gh >= 2.0.

**Errors:**

```python
class PRCommentsError(RuntimeError): pass               # base
class PRCommentLeakError(PRCommentsError):              # body contains secret-shaped token
    def __init__(self, redacted_preview: str): ...
class GhMissingError(SubprocessError): pass             # from _subprocess.resolve_exe
class GhCommandFailedError(PRCommentsError):            # gh returncode != 0; covers auth-failure + rate-limit
    def __init__(self, returncode: int, stderr: str, *, hint: str | None = None): ...
class GhJsonParseError(PRCommentsError): pass            # gh stdout not valid JSON
```

**CLI:** `python -m src.tools.prcomments <verb> <pr> [--body <text> | --body-file <path>] [--repo <owner/repo>] [--confirm] [--json]`

Markdown output (read):
```
# PR #1234 Comments (3)

## @alice — 2026-05-24T10:15:00Z
Looks good to me.

## @bob — 2026-05-24T11:00:00Z
One nit on line 42...
```

Markdown output (post success):
```
# Posted to PR #1234
Comment URL: https://github.com/.../pull/1234#issuecomment-...
```

### 3.4 CapabilityRegistryQuery (`src/tools/capabilityregistry/`)

**Purpose:** Read-only inspection of `src.schema.registry.TABLES` — the 80-table Python source-of-truth (confirmed by scout: 4 frozen-style dataclasses, TableDef has 11 fields including 6 sync_* fields).

**V1 scope (operator-confirmed):** PURE registry — no DBQuery composition. `dataclasses.asdict(table)` returns the dict directly (registry.py has no `to_dict()` method per scout). Future ContractCheck v2 in #107 may compose with live row counts.

**Single-file (`core.py` ≤200 LOC).** No sub-module split needed.

**Python API:**

```python
import dataclasses
from src.schema.registry import TABLES  # PERMITTED EXCEPTION (§2.2)

def tables(*, sync_only: bool = False) -> dict[str, dict]:
    """Return all 80 tables as {name: asdict(TableDef)}. sync_only filters sync_to_postgres=True."""
    items = TABLES.items()
    if sync_only:
        items = ((n, t) for n, t in items if t.sync_to_postgres)
    return {name: dataclasses.asdict(t) for name, t in items}

def table(name: str) -> dict:
    """Return single table as asdict(TableDef). Raises CapabilityRegistryError if name not registered."""
    if name not in TABLES:
        raise CapabilityRegistryError(f'Unknown table: {name!r}. {len(TABLES)} registered.')
    return dataclasses.asdict(TABLES[name])
```

**Output shape (verbatim):**

Each table dict has 11 keys: `name`, `description`, `columns` (list of column dicts: `name`/`type`/`nullable`/`default`/`description`/`autoincrement`), `primary_key` (str OR list[str] — composite), `indexes`, `foreign_keys`, `sync_to_postgres`, `sync_mode`, `sync_time_column`, `sync_pk`, `sync_conflict_col`, `sync_reconcile`.

**Errors:** `CapabilityRegistryError(RuntimeError)` only.

**CLI:** `python -m src.tools.capabilityregistry [--table NAME] [--sync-only] [--json]`

Markdown output (single table):
```
# Table: shadow_trades
shadow ledger of trade lifecycle from issue → close (mirrors Alpaca orders).

## Columns (24)
| Name | Type | Null | Default | Note |
|------|------|------|---------|------|
| id | INTEGER | NO | (auto) | autoincrement primary key |
...

## Primary Key: id
## Sync: sync_to_postgres=True, mode=incremental, time_column=created_at
```

Markdown output (all tables):
```
# Capability Registry (80 tables, 67 sync'd)
| Name | Description | Columns | Sync |
|------|-------------|---------|------|
| shadow_trades | shadow ledger... | 24 | True (incremental) |
...
```

### 3.5 TestPatternScan (`src/tools/testpatternscan/`)

**Purpose:** Static AST-based detector for the 4 brief-specified test anti-patterns. Builds on `tests/api/test_local_routes_auth_coverage.py:66-124` AST walker shape per scout (ast.walk + isinstance + ast.Call→Attribute→Name traversal).

**Sub-module split:**

- `core.py` (≤250 LOC) — `scan(*, path=None, kinds=None)` discovery + orchestration. Default `path = repo_root / 'tests'`. Default `kinds=['vacuous', 'patch_drift']` (ON-by-default rules). `--kinds mock_only,side_effect_unreached` opt-in.
- `rules.py` (≤400 LOC) — 4 rule detectors, each implementing `Rule.detect(tree, source) -> list[Finding]`.

**The 4 rules (with precision/recall classification per operator-confirmed brief):**

| Rule key | Default | Detector | Precision | Recall | Anchored at |
|----------|---------|----------|-----------|--------|-------------|
| `vacuous` | ON | `@patch` or `Mock()` setup with NO `.assert_*` call in function body | HIGH (precision-favored — false positives rare) | MEDIUM (misses subtle assertion-via-result patterns) | `docs/standards/boundary-touch-tests.md` §2 (T1 pattern) |
| `patch_drift` | ON | `@patch('module.symbol')` where the module's SOURCE FILE (located via `importlib.util.find_spec`) cannot be ast-parsed OR the symbol is not present in the module's top-level AST node table. **PURE-AST resolver — no `importlib.import_module`, no `getattr` walk** (DA4) | HIGH | MEDIUM-HIGH (misses dynamically-injected symbols like `setattr(module, name, value)` in module body — acceptable for a static analyzer) | Mock-target vs real call site — `docs/standards/boundary-touch-tests.md` §1(a) |
| `mock_only` | OFF | Test function whose ONLY assertions are on `mock.assert_called_with(...)` / `mock.call_args` (never asserts on real return values from the SUT) | MEDIUM (legitimate mock-interaction tests get flagged) | LOW (subtle return-value assertions evade) | `docs/standards/boundary-touch-tests.md` §1(b)/(c) — mock-only is a sub-shape of mock-signature drift |
| `side_effect_unreached` | OFF | `mock.side_effect = Exception(...)` set but mock is the ONLY thing exercised in the path that would raise (T18 pattern: `sc_query.return_value=True` so the NOT-RUNNING branch is never reached) | LOW (heuristic — true coverage requires runtime branch analysis) | LOW | `docs/standards/boundary-touch-tests.md` §2 (T18 pattern) |

**DA4 PURE-AST symbol resolver (PatchDriftRule implementation contract):**

The original spec said `importlib.util.find_spec` on module + getattr-walk for symbol. The getattr-walk requires `importlib.import_module(module_name)`, which EXECUTES top-level code: scanning a test that patches `src.api.app.something` would IMPORT `src.api.app` and trigger `load_dotenv`, model registration, DB connection openers, FastAPI app instantiation. The scan tool would become a side-effect bomb and could attempt prod-DB connections in CI. PURE-AST resolver eliminates this entirely.

Implementation sketch for `_resolve_symbol_in_module(module_name, symbol) -> bool` in `rules.py`:

- Call `importlib.util.find_spec(module_name)` (IMPORT-FREE per Python contract). If the call raises ImportError/ValueError or returns None or `.origin is None` or `.origin == 'built-in'` — return False; emit `patch_drift` finding with detail "module not importable".
- Read the `.origin` path with `Path(spec.origin).read_text(encoding='utf-8')`. If `suffix != '.py'` (.pyd / .so / namespace package), return False with detail "non-Python source — symbol resolution unavailable".
- `ast.parse(source)` the file. On SyntaxError / UnicodeDecodeError, return False with detail "source parse error".
- Walk `tree.body` (TOP-LEVEL ONLY — DO NOT recurse into function/class bodies) and collect names into a set:
  - `ast.Assign` targets that are `ast.Name` (handle tuple-targets too)
  - `ast.AnnAssign` target if `ast.Name`
  - `ast.FunctionDef` / `ast.AsyncFunctionDef` / `ast.ClassDef` `.name`
  - `ast.Import` aliases: use `alias.asname or alias.name.split('.')[0]`
  - `ast.ImportFrom` aliases: use `alias.asname or alias.name`
- Cache the resulting frozenset per module via `@lru_cache(maxsize=512)` on a helper `_module_top_level_names(module_name)`.
- For the requested symbol (which may be dotted like `a.b.c`), split on `.` and check if the FIRST segment is in the cached set. Misses dynamic attribute chains on classes (e.g. `Foo.bar.baz` where `Foo` exists but `bar` is added by `__init__`) — DOCUMENTED in rule docstring as MEDIUM-HIGH recall.

PatchDriftRule.detect logic: for each `@patch('module.symbol')` it sees, call `_resolve_symbol_in_module(module, symbol)`. If find_spec returned None → flag with `detail='module not importable'` (high-confidence). If symbol not in top-level names → flag with `detail=f'symbol {symbol!r} not in top-level AST of {module_name}'` (medium-high confidence — could be a dynamically-injected name).

**Side-effect safety guarantee (DA4):** Task 9 grep-asserts that `src/tools/testpatternscan/` contains ZERO `importlib.import_module` calls and ZERO `__import__` calls. The scanner is read-only on file content; scanning a test that patches `src.api.app.X` MUST NOT trigger `load_dotenv`, DB connections, or FastAPI app instantiation. Task 7 includes a dedicated side-effect test that monkeypatches `os.environ` lookups + DB connection openers to RAISE on access, then scans a test file that patches `src.api.app.something` — the scan must complete without triggering any of the monkeypatched raises.

**Out-of-scope (DEFERRED — per scout's `boundary-touch-tests.md` re-read):**

- Schema source-of-truth drift (§1(d)) → Tier 3 ContractCheck.
- Decorator-composition (§1(e)) → already covered by `tests/tools/test_safe_op_integration.py` integration tests at runtime.

**Python API:**

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class Finding:
    rule: str                # 'vacuous' / 'patch_drift' / 'mock_only' / 'side_effect_unreached'
    file: str                # repo-relative path
    line: int                # 1-indexed
    function: str            # def name
    detail: str              # human-readable
    confidence: str          # 'high' / 'medium' / 'low'

def scan(*, path: Path | None = None, kinds: list[str] | None = None) -> list[Finding]: ...
```

**Errors:** `TestPatternScanError(RuntimeError)` for unknown rule kind or path doesn't exist.

**CLI:** `python -m src.tools.testpatternscan [--path DIR] [--kinds KIND[,KIND...]] [--json]`

Markdown output:
```
# TestPatternScan: 7 findings

## vacuous (3 high)
- tests/foo/test_bar.py:42  test_thing       — @patch used but no .assert_* on mock
- tests/foo/test_bar.py:58  test_other_thing — Mock() created but never asserted on
...

## patch_drift (4 high)
- tests/foo/test_bar.py:12  test_x — @patch('src.foo.gone_symbol') — symbol not in src.foo
...
```

## 4. Cross-cutting standards

### 4.1 Subpackage layout (Tier-1 inherited)

Every tool lives at `src/tools/<name>/`. Mandatory files: `__init__.py` (export public API + error classes), `__main__.py` (argparse + `_cli_envelope.run_cli` dispatch), `core.py` (decorated entry points). Optional sub-modules per §4.8.

### 4.2 Module-header convention (Tier-1 inherited — verbatim)

Every new file's docstring includes a 6-line block:

```
Purpose: <one-line>
Called by: <subpackage / agent / skill / cron — pick all that apply>
Calls: <stdlib / subprocess / src.tools._* — non-trivial deps>
Owns tables: <table names or 'none'>
Config keys: <yaml dot-paths from arcis_config.yaml, or 'none'>
Tests: tests/tools/test_<tool>_integration.py
```

### 4.3 Argparse house style (Tier-1 inherited)

- `--json` is a STORE_TRUE boolean (NOT a value).
- Required positionals come BEFORE optional `--`.
- All argparse uses the `_cli_envelope.run_cli(fn, args, json_mode=args.json)` dispatch — exception → `{"error": {"type", "message", "tool"}}` JSON envelope under `--json`, Python default traceback otherwise.

### 4.4 Subprocess house pattern (Tier-1 reinforced, Tier-2 codified in `_subprocess.run`)

```python
subprocess.run(
    [exe, arg1, arg2, ...],   # list-args, NEVER shell=True
    capture_output=True,
    text=True,
    encoding='utf-8',
    timeout=N,                # ALWAYS set
    check=False,              # examine returncode explicitly
)
```

Forbidden-grep: `subprocess.run(.*shell=True` MUST return zero matches under `src/tools/`.

### 4.5 PID-scoped kill discipline (Tier-2-new — copied verbatim from `src/scheduler/ollama_watchdog.py:226-227`)

**"PID-scoped only — never /im, never by name"** — applies to ProcessManager's optional taskkill escalation. If a future ProcessManager.kill is added (TIER 3, deferred), it MUST verify PID identity via `tasklist /fi 'imagename eq <exe>'` returning the target PID BEFORE issuing `taskkill /f /t /pid <pid>`. The #87 dual-GPU stale-PID guard already established this discipline.

### 4.6 POSITIVE nssm-state parsing (Tier-2-new)

Do NOT inherit `archive_bootcamp_2026_04_24.py:157-169` NEGATIVE check (`'SERVICE_STOPPED' not in stdout`). Use POSITIVE substring matches against the 7-state vocabulary per §3.1. Distinguishing STARTING/STOPPING/PAUSED from RUNNING is essential for ProcessManager's correctness.

### 4.7 Audit log result kinds (Tier-2 extension to #104)

`secret_leak_block` added to `_VALID_RESULTS`. Only PRComments.post emits it (on PRCommentLeakError). PRComments writes BOTH a `secret_leak_block` event (via direct `write_event` call with redacted body) AND lets `@safe_op` write its standard `'error'` event — two-row audit pattern matches existing safe_op + safety_window 2-event behavior. Test-side exhaustiveness (`tests/tools/test_execution_log.py` parametrize + frozenset-equality assertion) is updated atomically with the source extension (FB1).

### 4.8 Sub-module pattern (Tier-1 §4.8 inherited)

When `core.py` exceeds ~300 LOC, split into orthogonal sub-modules. Tier-2 examples:

- ProcessManager: `core.py` (decorators + alias) + `nssm.py` (subprocess) + `taskkill.py` (escalation).
- HealthProbe: `core.py` (orchestrator) + `checks.py` (per-service probes).
- TestPatternScan: `core.py` (discovery) + `rules.py` (per-rule detectors).
- PRComments + CapabilityRegistryQuery stay in `core.py` alone (under budget).

### 4.9 Foundation config extension (Tier-2-new — DD-10)

`PathsConfig` pydantic model in `src/tools/_config.py` gains `watchdog_heartbeat: Path` (default `C:/arcis/halcyon-lab/data/watchdog.txt`). Corresponding key added to `config/arcis_config.yaml` under `paths:`. ProcessManager.restart and HealthProbe._check_heartbeat both consume the key. The watch loop's own cwd-relative WRITE at `src/scheduler/watch.py:1722-1734` is NOT changed in this design (out of scope; behavior continues unchanged). Future cleanup (post-#106) may align the watch-loop write to read from the same key.

## 5. Error handling strategy

Every tool defines a base `<Tool>Error(RuntimeError)` and per-condition subclasses. `@safe_op`'s single-log discipline (`_safety.py:137-164`) is preserved — SafetyError subclasses (from `@safety_window` / `@prod_guard`) skip the duplicate `'error'` write. All other exceptions raise → `@safe_op` writes `'error'` + re-raises.

PRComments deliberately writes a `secret_leak_block` row BEFORE raising PRCommentLeakError — `@safe_op`'s default handler then writes an additional `'error'` row when it catches the propagating exception (single-log discipline applies only to SafetyError subclasses per `_safety.py:137-164`; non-SafetyError exceptions always produce an `'error'` row). Operator-confirmed: two rows are fine — the `secret_leak_block` row carries the redacted body for forensics; the `'error'` row is the standard catch-all. This is the ONLY 2-row-without-SafetyError pattern in Tier 2.

## 6. Testing strategy

Each tool gets `tests/tools/test_<tool>_integration.py` following the `test_safe_op_integration.py` keystone template (real decorator stack + tmp_path audit log + injected seam + single-log assertion + N terminal states).

### 6.1 Boundary-touch matrix per tool

| Tool | Real seam | Injectable seam in tests | Boundary-touch states |
|------|-----------|--------------------------|------------------------|
| ProcessManager | real `nssm` subprocess + tasklist | monkeypatch `subprocess.run` returning canned `nssm status` outputs (one per state); monkeypatch `time.monotonic` for deadline | status-RUNNING / status-STOPPED / restart-success-verified / restart-success-unverified / restart-deadline-elapsed / safety-window-block / nssm-missing |
| HealthProbe | real socket + nssm + LogTail | monkeypatch `socket.connect_ex` returning 0/ETIMEDOUT; tmp_path heartbeat file; monkeypatch `nssm_status` returning per-state | OK / DEGRADED (stale heartbeat) / DEGRADED (port not listening) / DOWN (service stopped) / cfg-load-error |
| PRComments | real `gh` subprocess; for write tests, gh-not-on-PATH path | monkeypatch `subprocess.run` returning canned JSON; inline secret-laden body strings | read-success / post-success / post-leak-blocked / gh-missing / gh-failed / gh-json-parse-error / gh-auth-failure |
| CapabilityRegistryQuery | real `src.schema.registry.TABLES` import | inline minimal `TableDef` fixture via monkeypatch of TABLES dict | all-tables / single-table-found / unknown-table-raises / sync-only-filter |
| TestPatternScan | real `ast.parse` | inline test-source strings (per `test_local_routes_auth_coverage.py:251-281` pattern) — one positive + one negative per rule | vacuous-positive / vacuous-negative / patch-drift-positive / patch-drift-negative / mock-only-opt-in / side-effect-unreached-opt-in / unknown-kind-raises |

### 6.2 Verify-by-mutation (Tier-1 inherited)

Each test's docstring enumerates a 1-line mutation that, if applied to the SUT, breaks the test. Example for ProcessManager: "remove the POSITIVE state-map order → status() misreports SERVICE_STOP_PENDING as RUNNING → status() test fails." Example for PRComments: "comment out `detect_secret_in_text` pre-flight → leak-block test (c) passes the body to gh and the `secret_leak_block` event is never written → test (c) fails on missing audit row."

### 6.3 Single-log discipline assertions

Every integration test asserts `len(events) == 1` for the standard path (matches keystone). PRComments leak-block test asserts `len(events) == 2` with one `secret_leak_block` + one `error` — the only Tier-2 exception, documented in the test.

### 6.4 Real-seam smoke tests (FB5 — skip-unless-on-PATH gates)

Mocked tests above exercise edge cases comprehensively, but mocked subprocess gives no signal that the ACTUAL binary contract matches our expectations. Two real-seam smoke tests are added (gated by `@pytest.mark.skipif(shutil.which('<exe>') is None)` so CI without the binary still passes):

- **`test_processmanager_real_nssm_smoke`** in `test_processmanager_integration.py`:
  - Gate: `@pytest.mark.skipif(shutil.which('nssm') is None, reason='nssm.exe not on PATH')`.
  - Body: `state = nssm_status('ArcisWatchLoop')` — assert returned `state.value in {'RUNNING','STOPPED','STARTING','STOPPING','PAUSED','PAUSE_PENDING','CONTINUE_PENDING','UNKNOWN'}` (one of the 8 enum values; the 7 NSSM states + UNKNOWN fallback). Verifies real nssm.exe stdout still parses against our `_STATE_MAP`.
  - NEVER mutates — read-only contract probe.

- **`test_prcomments_real_gh_smoke`** in `test_prcomments_integration.py`:
  - Gate: `@pytest.mark.skipif(shutil.which('gh') is None, reason='gh.exe not on PATH')`. Also gated on `os.getenv('GH_TOKEN') or shutil.which('gh')` having auth (if `gh auth status` returns non-zero, skip with reason).
  - Body: `comments = read(pr=<known-merged-PR-from-this-repo>, repo='millerrc18/halcyon-lab')` — assert `isinstance(comments, list)` and (if non-empty) `isinstance(comments[0], PRComment)` with the 4 expected fields. Verifies real gh stdout JSON still maps to our PRComment dataclass.
  - Read-only — does NOT exercise `post()`.

Mocked tests STAY for full edge-case coverage. Real-seam smokes add the contract-with-actual-binary signal. If both binaries are absent (CI), the smokes skip cleanly without RED.

## 7. Anti-pattern call-outs (with exact file:line)

| Anti-pattern | Cited at | Why we don't inherit |
|--------------|----------|----------------------|
| `_sc_query_running` — no timeout + bare `except` | `src/scheduler/watch.py:130-147` | Tier-2 uses `_subprocess.run(..., timeout=N)` + typed errors. ProcessManager.status and HealthProbe both use `nssm status` (single source of truth) — NOT `sc query`. |
| `tick_watchdog_liveness` — double-soft swallow wrapping `_sc_query_running` | `src/scheduler/watch.py:1161-1163` | Sibling-search call-out — the same pattern is wrapped AGAIN. Tier-2 raises typed errors all the way up; no double-soft compounding. |
| Silent `FileNotFoundError` on missing nssm | `scripts/archive_bootcamp_2026_04_24.py:166-167` | Acceptable for one-shot scripts. ProcessManager raises `NssmMissingError(SubprocessError)` with PATH-install hint. |
| NEGATIVE state parse (`'SERVICE_STOPPED' not in stdout`) | `scripts/archive_bootcamp_2026_04_24.py:157-169` | Conflates STARTING/STOPPING/PAUSED with RUNNING. ProcessManager parses positively against the 7-state vocabulary. |
| Kill-by-name (`taskkill /im X.exe`) | (not in src/ — already avoided per `ollama_watchdog.py:226-227`) | Tier-2 preserves the discipline. If taskkill escalation is needed, PID-scoped only. |
| CWD-relative heartbeat write + multi-path discovery read | `src/scheduler/watch.py:1722-1734` (write) + `scripts/statusline.py:38-55` (read discovery) | Tier-2 introduces explicit `cfg.paths.watchdog_heartbeat` config key (DD-10). ProcessManager + HealthProbe consume the key directly — no discovery walk, no cwd-dependent resolution. |

## 8. Design decision summary table

All 16 rows below are recorded as full entries in `design_decisions.json` (DA1 remediation — 16 entries, each with `options_considered` / `rationale` / `reversibility` / `downstream_implication`).

| # | Decision | Reversibility |
|---|----------|---------------|
| DD-1 | POSITIVE nssm-state parsing (7-state vocab) | Cheap — table-driven |
| DD-2 | PID-scoped kill discipline only | Irreversible (safety contract) |
| DD-3 | restart wait-and-verify: 30s state poll + 5s log-evidence verify | Cheap — constants in nssm.py |
| DD-4 | PRComments.post → PRCommentLeakError + new `secret_leak_block` audit kind + extended pattern list (DA3) | Cheap — _VALID_RESULTS line + pattern list extension |
| DD-5 | TestPatternScan: vacuous + patch_drift ON; mock_only + side_effect_unreached OPT-IN; **PatchDriftRule uses PURE-AST symbol resolver — no module-import side effects** (DA4) | Cheap — default kinds list constant + AST scan in lieu of getattr-walk |
| DD-6 | CapabilityRegistryQuery v1 PURE registry (no DBQuery composition) | Cheap — additive in v2 |
| DD-7 | HealthProbe staleness defaults in code; CLI override via `--stale-seconds N` (no per-service yaml in v1) | Cheap — yaml schema additive in v2 |
| DD-8 | Explicit anti-pattern call-outs in spec by file:line + Task 9 grep-asserts | Irreversible (operator feedback) |
| DD-9 | Shared `_secrets.py` + `_subprocess.py` helpers; `_secrets` content-driven (NOT key-driven extension of `sanitize_params`) | Cheap — additive |
| DD-10 | NEW `paths.watchdog_heartbeat` config key — explicit, decoupled from `db_canonical.parent`; ProcessManager + HealthProbe consume it | Cheap — config schema additive |
| DD-11 | Sub-module split heuristic: when `core.py` exceeds ~300 LOC, split into orthogonal sub-modules. ProcessManager (3), HealthProbe (2), TestPatternScan (2). PRComments + CapabilityRegistryQuery stay single-core.py (under budget) | Cheap — refactor |
| DD-12 | Shared `_subprocess.run` + `resolve_exe` helpers vs. inline subprocess calls per tool | Cheap — additive |
| DD-13 | `from src.schema.registry import TABLES` is the ONLY allowed `src.*` import in tools/ subpackages (CapabilityRegistryQuery only) — registry-import exception | Cheap — forbidden-imports grep allows the exception |
| DD-14 | PRComments uses `gh pr comment --body-file -` (stdin pipe) — NOT `--body <string>`; requires gh >= 2.0 | Cheap — argument shape |
| DD-15 | Real-seam smoke tests for ProcessManager + PRComments with `skipif(shutil.which() is None)` gates | Cheap — 2 small tests |
| DD-16 | ProcessManager.restart SUSTAINED-RUNNING flap-detection — 3-consecutive-RUNNING window after first RUNNING observation; 33s overall deadline (DA2) | Cheap — constants in nssm.py |

## 9. CHANGELOG sketch (v0.36.63)

```
## v0.36.63 — 2026-05-25 — #106 Tier 2 tools (ProcessManager, HealthProbe, PRComments, CapabilityRegistryQuery, TestPatternScan)

- ProcessManager: nssm wrapper with POSITIVE state parsing (7 states), restart wait-and-verify (30s state poll + 3s sustained-running flap-detection window + 5s log evidence; 33s overall deadline), @safety_window('no_restart_overnight') first production consumer.
- HealthProbe: composite read-only check (nssm state + heartbeat freshness + port reachability + recent error count) per service. Defaults: 60s/300s/30s staleness for watch_loop/dashboard/ollama_watchdog.
- PRComments: greenfield `gh pr comment` wrapper with content-based secret-leak pre-flight (PRCommentLeakError). Pattern list extended to 14 known-prefix patterns (ghp_/github_pat_/gho_/ghs_/ghu_/glpat-/sk-/sk_live_/pk_live_/xox*/JWT/password=/Bearer/PEM/AKIA) + high-entropy fallback for AWS-secret-key-shaped and generic 40+ char base64-like runs. New `secret_leak_block` audit kind in _execution_log._VALID_RESULTS. Requires gh >= 2.0 for stdin pipe.
- CapabilityRegistryQuery: pure-registry read via dataclasses.asdict(TABLES). 80-table source-of-truth surfaced for agents.
- TestPatternScan: AST scanner for 4 boundary-touch rules. Defaults: vacuous + patch_drift ON; mock_only + side_effect_unreached opt-in via --kinds. PatchDriftRule uses PURE-AST symbol resolution — never imports the target module — eliminating side-effect risk (load_dotenv, DB connections, FastAPI app instantiation) when scanning tests that patch heavy modules.
- New helpers: src/tools/_secrets.py (content-based secret scanner), src/tools/_subprocess.py (shared subprocess.run wrapper + resolve_exe).
- New config key: paths.watchdog_heartbeat (default C:/arcis/halcyon-lab/data/watchdog.txt) — decouples heartbeat path from db_canonical.parent; consumed by ProcessManager.restart + HealthProbe.
- Decorator stacks: ProcessManager.restart=[safe_op,safety_window]; others=[safe_op]. NO @prod_guard in Tier 2 (no DSN params).
- Anti-patterns explicitly NOT inherited: watch.py:130-147 (_sc_query_running no-timeout+bare-except), watch.py:1161-1163 (double-soft swallow), archive_bootcamp_2026_04_24.py:157-169 (NEGATIVE state parse + silent FileNotFoundError), watch.py:1722-1734 + statusline.py:38-55 (cwd-relative-write + discovery-read; replaced by explicit cfg.paths.watchdog_heartbeat).
- Real-seam smoke tests added for ProcessManager (nssm) + PRComments (gh) with skip-unless-on-PATH gates.
- _VALID_RESULTS enum-exhaustive test (tests/tools/test_execution_log.py) updated atomically with the source extension.
- Dual-Opus QA matrix per #98 standard.
```

---

## Design Decisions Log

(All 16 decisions also recorded as full entries in `design_decisions.json` alongside this spec.)

| # | Decision | Rationale (short) | Reversibility |
|---|----------|-------------------|---------------|
| DD-1 | DD-1: POSITIVE nssm-state parsing with ordered _STATE_MAP (7-state vocab) | Negative parse conflates STARTING/STOPPING/PAUSED with RUNNING — operator-prohibited. POSITIVE substring matches against the 7-state vocab in ordered iterati... | cheap (table-driven) |
| DD-2 | DD-2: PID-scoped kill discipline (NEVER /im, NEVER by name) | Operator's #87 dual-GPU follow-up established this discipline. Tier 2 ProcessManager inherits verbatim. Discovery uses 'tasklist /fi imagename eq <exe>' but ... | irreversible (safety contract) |
| DD-3 | DD-3: ProcessManager.restart wait-and-verify protocol with 30s state-poll + 5s log-evid... | Operator-confirmed in brief. 30s deadline matches watch loop's ~60s heartbeat cadence; 5s log-evidence window catches 'process running but stuck before first... | cheap (constants in nssm.py) |
| DD-4 | DD-4: PRComments leak-refuse semantics — new 'secret_leak_block' audit kind + 2-row pat... | Distinct audit kind is grep-able for periodic skill-audit (#111). 2-row pattern matches existing safe_op + safety_window 2-event behavior on block. Mandatory... | cheap (single _VALID_RESULTS line + helper function + pattern list) |
| DD-5 | DD-5: TestPatternScan rule defaults: vacuous + patch_drift ON; mock_only + side_effect_... | Operator brief explicitly specified the defaults matrix. Precision/recall per spec §3.5: vacuous (HIGH precision, MEDIUM recall), patch_drift (HIGH precision... | cheap (default kinds list constant + AST scan replacing getattr-walk) |
| DD-6 | DD-6: CapabilityRegistryQuery v1 PURE registry — no DBQuery composition | Brief-confirmed PURE registry scope for v1. Composition with live DB row counts is deferred to #107 ContractCheck v2. dataclasses.asdict produces nested dict... | cheap (additive in v2) |
| DD-7 | DD-7: HealthProbe staleness defaults (60s/300s/30s) in code; --stale-seconds N CLI over... | Brief specified the 3 defaults — these match observed write cadences (watch.py heartbeat ~60s; ollama_watchdog log ~30s; dashboard request-driven so 5min is ... | cheap (yaml schema additive in v2) |
| DD-8 | DD-8: Explicit anti-pattern call-outs in spec by file:line — watch.py:130-147 (_sc_quer... | Per operator feedback feedback_review_sibling_search. Task 1 grep-records confirmed instances of _sc_query_running siblings + cwd-relative heartbeat write/re... | irreversible (lesson from operator feedback) |
| DD-9 | DD-9: Shared _secrets.py + _subprocess.py helpers (Tier-2-new module-level additions) | _subprocess.run codifies the house pattern in a single source. resolve_exe(name) with @lru_cache prevents repeated shutil.which calls and centralizes NssmMis... | cheap (additive) |
| DD-10 | DD-10: NEW paths.watchdog_heartbeat config key (FB2) — explicit, decoupled from db_cano... | Three reasons for chosen option per FB2: (1) EXPLICIT — operator sees the key in arcis_config.yaml; no hidden discovery walk. (2) DECOUPLED from db_canonical... | cheap (additive — new optional field on PathsConfig with sensible default; existing configs without the key use the default) |
| DD-11 | DD-11: Sub-module split heuristic — when core.py exceeds ~300 LOC, split into orthogona... | Tier-1 §4.8 established the ~300 LOC threshold for core.py with TradingState (4 sub-modules: core/queries/positions/orders). Tier-2 applies the same heuristi... | cheap (refactor — splits or merges are mechanical) |
| DD-12 | DD-12: Shared _subprocess.run + resolve_exe helpers vs. inline subprocess calls per tool | Three tools (ProcessManager, HealthProbe via nssm_status import, PRComments) all need subprocess invocations. Inline calls per tool would invite drift (forgo... | cheap (additive — could be removed in favor of inline calls if needed, but operator pattern matches #104 _safety.py + #105 _db.py / _cli_envelope.py house-helper precedent) |
| DD-13 | DD-13: `from src.schema.registry import TABLES` is the ONLY allowed src.* import in too... | The forbidden-imports list (`from src.config`, `from src.utils.db`, `load_dotenv`, etc.) exists to keep tools/ subpackages from accidentally re-bootstrapping... | cheap (forbidden-imports grep allows the named exception — if registry ever gains runtime apparatus, revisit) |
| DD-14 | DD-14: PRComments uses `gh pr comment --body-file -` (stdin pipe) — NOT `--body <string... | Arbitrary PR comment bodies contain markdown formatting, code blocks with backticks, possibly $variable references. Passing via --body <string> requires shel... | cheap (argument shape — could revert to --body if gh ever removes stdin support) |
| DD-15 | DD-15: Real-seam smoke tests for ProcessManager + PRComments with skipif(shutil.which()... | Mocked tests cover edge-case logic but tell us nothing about whether real-binary contracts have drifted. nssm could change its status-output format in a futu... | cheap (2 small tests — can be removed if real-binary access becomes a CI burden) |
| DD-16 | DD-16: ProcessManager.restart SUSTAINED-RUNNING flap-detection (DA2) | DA2 identified that NSSM's AppRestartDelay (default ~1500ms) auto-restarts a crashed service. If a service crashes immediately after `nssm restart`, the poll... | cheap (constants in nssm.py — sustained_window_observations=3, poll_interval_s=1.0, initial_deadline_s=30) |


---

## Known Considerations (devils-advocate minor + nit findings, not blocking)

Surfaced during adversarial review; deemed below the threshold for spec revision. Documented for future tooling work.

| # | Concern | Note |
|---|---------|------|
| KC1 | NSSM service-not-registered taxonomy (operator typo) yields same `NssmCommandFailedError` as a real failure | Recommended `ServiceNotRegisteredError(ProcessManagerError)` raised when `nssm` stderr contains `Can't get info`. Defer to Tier 3 hardening. |
| KC2 | `watchdog.txt` resolves to a DIRECTORY (operator setup error) — `_check_heartbeat` reasons enum has no `is_directory` case | Add `Path.is_file()` check before reading; add `is_directory` to reasons enum. Trivial post-merge follow-up. |
| KC3 | `gh pr comment` may succeed but GitHub holds the comment for moderation — gh exits 0, comment invisible | Caller responsible for verifying via subsequent `read()`. Document in §3.3 (post-merge). |
| KC4 | `gh` exits 1 with "you are not authorized to push" — surfaces same as auth-failure with `gh auth login` hint, which is misleading | Inspect stderr for `'authentication required'` vs `'not authorized'` / `'forbidden'` / `'permission denied'` substrings; tailor hint accordingly. |
| KC5 | Real-seam smokes use `@skipif(shutil.which('X') is None)` — both will SKIP in CI (binaries not installed), gating zero contract coverage | Smokes are LOCAL-DEV-ONLY by design. Consider adding `choco install nssm` + verifying pre-installed `gh` on CI runners (post-merge enhancement); alternatively, manual pre-merge checklist item for developer-box smoke run. |
| KC6 | `ProcessManager.restart` blocks for up to 33s with no progress indicator — operator Ctrl-C is ambiguous | Document recovery: nssm restart already fired, service restarting in background; re-run `status` + `healthprobe` to verify. Optional: stderr dot-per-poll progress indicator in non-`--json` mode. |
| KC7 | `paths.watchdog_heartbeat` default is absolute — worktree dev inherits main-repo's watchdog path | Add env-var override pattern (e.g., `pydantic Field(env='ARCIS_WATCHDOG_HEARTBEAT')`) so worktree dev can override per-clone. Operator-doc footnote. |
| KC8 | File:line citations to anti-patterns (`watch.py:130-147` etc.) will rot if those files are reformatted | Optional hash-check pattern: Task 1 records `sha256` of cited line range; Task 9 re-checks. Lightweight ~5 LOC. Defer to #111 periodic discipline. |
| KC9 (nit) | `open('a', encoding='utf-8')` on Windows does NOT guarantee atomic line-append; concurrent invocations can interleave at byte level | Single-writer assumed; concurrent invocation OUT OF SCOPE for Tier 2. File-level locking (`msvcrt.locking` / `fcntl.flock`) when introducing concurrent invocation pattern. |
| KC10 (nit) | Task 2 added new config key — risk of "let's add one more foundation key" pattern per tier | Add to §4.9 a heuristic: "new config key in consuming tier iff (1) only that tier consumes it AND (2) default doesn't affect non-tier code; otherwise patch #104 foundation." Bounds future scope creep. |

(Per devils-advocate review pass — see `arcis:design-devils-advocate` invocation 2026-05-24.)
