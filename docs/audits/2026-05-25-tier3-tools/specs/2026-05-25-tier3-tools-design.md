# Tier 3 Meta-Quality Tools — Design Spec

**Effort:** Task #107 — Tier 3 / phased tools (ContractCheck v1, GitArchaeology, DocConsistency)
**Target version:** v0.36.65 (re-baseline at implementation time)
**Bundling:** ONE PR — three subpackages + one shared foundation extension
**Status:** design complete; implementation pending dual-Opus QA gate
**Revision:** R1 — feasibility-review fixes (FB1 major: `@safe_op` signature; FB2-FB5 minors)

---

## 0. PREAMBLE — No Out-Of-Scope Deferral

This effort delivers **all** of three tools (ContractCheck v1, GitArchaeology, DocConsistency v1) bundled in one PR, sharing one foundation extension. The operator's standing discipline (see operator memory `feedback_complete_efforts_no_deferral`) is that within an effort we deliver ALL of it OR scope the effort smaller — never quietly punt sub-items to operator-memory for "later."

Application to this design:

- **WITHIN scope of #107:** all three tools, their subpackage layouts, their CLIs, their integration tests, the foundation extension (`ContractsConfig` + `.gitignore` allowlist), the initial committed baseline for ContractCheck (`data/contracts/nvidia-smi-watchloop/<timestamp>.json` + `latest_ref.txt`), and the seed `data/docconsistency-allowlist.yaml`. None of these are deferrable. If any of them slips at implementation time, the operator decides whether to scope #107 smaller — they do not become silent backlog items.

- **NEW finding surfaced during design — scoped OUT:** the deep-report Phase 4 analysis confirmed that `src/monitoring/system_metrics.py:36-56` has **no active `[N/A]` defense**. The v0.36.29 hotfix that originally added this defense lived in `src/scheduler/vram_manager.py`, which has since been DELETED by the overnight-handoff-removal refactor (witnessed by `tests/test_overnight_handoff_removed.py:25-32`). ContractCheck v1's first baseline recording (Task T5) will surface this gap immediately — but **fixing the gap is NOT in #107's scope.** Per operator's no-deferral discipline at the *boundary* (not the "fix everything you find" interpretation), this gap is filed as **task #117 "Restore [N/A] defense in system_metrics.py nvidia-smi parser"** (already in the task list, separate effort, separate PR). The spec references #117 explicitly so the surfaced finding is *tracked*, not lost. ContractCheck shipping with this drift signal *on* is the correct outcome: the tool's job is to make the gap visible. Closing the gap is #117's job.

This design adheres to that boundary throughout.

---

## 1. Overview

### 1.1 What Tier 3 is

Tier 3 is the **meta-quality layer** of the arcis tool suite. Where Tier 1 tools (#105: DBQuery, LogTail, CIInvestigate, SymbolFind, TradingState) inspect live state and Tier 2 tools (#106: ProcessManager, HealthProbe, PRComments, CapabilityRegistryQuery, TestPatternScan) inspect tooling and process state, Tier 3 inspects the **codebase's relationship to its own assumptions**:

- **ContractCheck** — a **FORENSIC tool** that guards against silent drift in pinned external-CLI invocations. v1 pins the watchloop's `nvidia-smi` call. When the operator suspects drift, or when ContractCheck.verify() runs on a schedule (post-#107 effort wiring per #111), it detects v0.36.29-class regressions in BOTH value drift (calibrated per-field tolerances) AND shape drift (a `[N/A]` sentinel where a float was expected). v1 does NOT instrument the watchloop at runtime; the watchloop continues to silently swallow `[N/A]` via its broad-except clause until #117 closes. ContractCheck v1's value is to detect-on-demand, not block-at-runtime. The verify-by-mutation north-star is the v0.36.29 `[N/A]` incident — see §4.7 for the honest framing of what ContractCheck v1 proves and what it does not.

- **GitArchaeology** — a read-only wrapper over the 7 most common git CLI ops used across the repo. Mainly serves the `git-historian` specialized agent (#108 / DD-10) by providing a single subprocess-disciplined CLI surface in lieu of ad-hoc `subprocess.check_output(['git', ...])` calls. Forbidden mutating ops are an explicit no-fly list.

- **DocConsistency** — scans `docs/`, `CHANGELOG.md`, `README.md` for inline `file.py:line` references and verifies each refers to a file that exists with at least that many lines. v1 catches **class (a)** — dead `file:line` refs only. Classes (b) API signature drift, (c) docstring-vs-code drift, (d) symbol-existence drift are deliberately deferred to v2/Tier 4.

### 1.2 Why Tier 3 is meta-quality

All three tools share a single property: **they fail loudly when other parts of the codebase silently drift**. None of them mutate state. None of them gate deploys (yet — the operator can elevate them to CI gates post-W21-freeze if the false-positive rate is low). They produce structured findings that the operator (or a downstream automation) triages.

This is the inverse of Tier 1/2 — those tools mostly *answer questions* about the running system. Tier 3 tools mostly *raise questions* about the codebase's correctness.

### 1.3 Relationship to adjacent efforts

| Effort | Relationship to Tier 3 |
|--------|------------------------|
| #108 git-historian agent | GitArchaeology is the agent's single approved subprocess surface (DD-10 in #108's spec — "single-file diff when #107 lands"). After #107 merges, #108's agent prompt is updated to invoke `python -m src.tools.gitarchaeology` rather than `subprocess.check_output(['git', ...])`. |
| #111 periodic discipline | DocConsistency is expected to become part of the periodic skill-audit cadence. v1 ships as opt-in CLI; #111 will wire it into a scheduled run. |
| #117 system_metrics [N/A] defense | ContractCheck v1's first baseline run surfaces this gap. #117 fixes it (separate PR). Both depend on each other only loosely: ContractCheck ships *before* the fix, the fix lands *after* ContractCheck records the live (broken-defense) baseline. |
| #102 test audit | DocConsistency v2 (deferred) shares scanning machinery with the boundary-touch standard; v1 deliberately does not couple to it. |

### 1.4 What this design is NOT

- **Not a CI gate** — none of the three tools fail builds in v1. They produce findings; the operator triages.
- **Not a fix for #117** — ContractCheck *surfaces* the system_metrics gap; it does not fix it.
- **Not v2 of DocConsistency** — class (a) ONLY. No API signature checks, no docstring-vs-code, no symbol existence. Those are explicit follow-ups (see §11.3).
- **Not a full git CLI displacement** — GitArchaeology covers 7 read-only ops. Four direct-`git` sites in `src/` and four in `scripts/` are left in place (see §11.4). The git-historian agent is the primary client; broader displacement is a separate effort.
- **Not symlinks** — operator's Windows-first box; the baseline pointer is a plain text file (`latest_ref.txt`), never `os.symlink` / `Path.symlink_to`.

---

## 2. Architecture

### 2.1 Inherited foundation (Tier 1+2 primitives) + minor additive deltas

All three Tier 3 tools inherit the same five foundation modules under `src/tools/`. **All three Tier 3 tools inherit the foundation modules unchanged in semantics; the deltas below are additive (new error classes, new pydantic model fields) and preserve backward compatibility — existing Tier 1+2 tools remain unchanged.** The deep report confirmed all five primitives are stable; #107's foundation extension only *appends* new symbols, never modifies existing ones.

| Foundation module | Inherited from | Used by Tier 3 for |
|-------------------|----------------|---------------------|
| `src/tools/_config.py` | #104 (v0.36.57) | Load `arcis_config.yaml`; extend `ArcisConfig` with new top-level `contracts:` section via a new nested `ContractsConfig` pydantic model. |
| `src/tools/_subprocess.py` | #104 | Centralized `run()` wrapper (UTF-8, no shell, explicit timeout) for ContractCheck's `nvidia-smi` invocations and GitArchaeology's `git` invocations. Adds two new exception classes via the existing precedent. |
| `src/tools/_cli_envelope.py` | #105 (v0.36.61) | `run_cli(tool_name, fn, args, json_mode=)` wraps every `__main__.py` for uniform `--json` error envelope. No changes to this module. |
| `src/tools/_safety.py` | #104 | `@safe_op(name="<tool>", mutates=False)` decorator pattern (verified signature at src/tools/_safety.py:167-172); *none of Tier 3's ops are mutating* — every public function uses `mutates=False` (DD-7). Used purely for audit-log instrumentation. |
| `src/tools/_execution_log.py` | #104 | JSON-lines audit log at `data/logs/tool-execution.log`. All three Tier 3 tools log every CLI invocation via the `@safe_op` wrapper. |

Foundation deltas in this PR (additive only):
- `src/tools/_config.py` — append `NormalizeRule` / `ContractDef` / `ContractsConfig` models + extend `ArcisConfig.contracts` with a default empty dict (backward-compat preserved).
- `src/tools/_subprocess.py` — append `GitMissingError` + `NvidiaSmiMissingError` classes (mirroring `NssmMissingError` / `GhMissingError` precedent at L31-37); bump `@lru_cache(maxsize=4)` to `maxsize=6` at L39 (per deep report Area 3) to accommodate the two new resolved exes.

### 2.2 New subpackage layout (mirrors Tier 1+2 convention)

Each Tier 3 tool gets its own subpackage under `src/tools/`:

```
src/tools/
├── _cli_envelope.py        (UNCHANGED)
├── _config.py              (MODIFIED — ContractsConfig appended)
├── _execution_log.py       (UNCHANGED)
├── _safety.py              (UNCHANGED)
├── _subprocess.py          (MODIFIED — 2 new error classes appended; lru bump)
├── contractcheck/                NEW
│   ├── __init__.py             (exports `record`, `verify`, `diff`)
│   ├── __main__.py             (argparse + run_cli)
│   └── core.py                 (all logic; no sub-modules — fits in one file)
├── docconsistency/               NEW
│   ├── __init__.py             (exports `scan`)
│   ├── __main__.py             (argparse + run_cli)
│   └── core.py                 (file:line regex + verify + allowlist)
└── gitarchaeology/               NEW
    ├── __init__.py             (exports `log`, `blame`, `show`, `diff`, `rev_list`, `merge_base`, `tag_l`)
    ├── __main__.py             (argparse subcommands + run_cli)
    └── core.py                 (per-op subprocess wrappers + parsers)
```

Every new module's docstring header follows the existing 5-section operator convention (see `src/tools/_subprocess.py:1-22` for the template): `Purpose / Called by / Calls / Owns tables / Config keys / Tests`.

### 2.3 New data layout (baselines)

```
data/
├── reference/                    (EXISTING — committed reference data, precedent)
├── contracts/                    NEW — committed via .gitignore allowlist
│   └── nvidia-smi-watchloop/
│       ├── 2026-05-25T17-30-00Z.json   (first recorded baseline, committed by T5)
│       └── latest_ref.txt              (plain text file containing the filename above; NOT a symlink)
├── docconsistency-allowlist.yaml NEW — committed via .gitignore allowlist (explicit single-file)
└── (other gitignored runtime files unchanged)
```

The two new committed files require **two distinct `.gitignore` appends** (see §3.3).

### 2.4 Cross-cutting standards (inherited verbatim from Tier 1+2)

The deep report Area 17 enumerates the anti-patterns to NOT inherit and the patterns to inherit. Tier 3 applies these uniformly:

1. **`encoding='utf-8'` on every file read/write** (operator memory `feedback_windows_utf8_encoding`). Tier 3 file I/O uses `Path.read_text(encoding='utf-8')` / `Path.write_text(..., encoding='utf-8')` — never `open(...)` with default encoding.

2. **`subprocess.run` only via `src.tools._subprocess.run`** — no direct `subprocess.run` / `subprocess.check_output` in any Tier 3 module. (Exception: the system_metrics watchloop being pinned by ContractCheck is itself a direct-subprocess site; ContractCheck records the LITERAL argv that *that* site uses, not its own subprocess wrapping. ContractCheck's *own* nvidia-smi invocation, when recording, goes through `_subprocess.run`. See §4.2.)

3. **Bind `127.0.0.1` for any ad-hoc HTTP server**, port 8765+ (operator memory `reference_local_ports`). N/A for Tier 3 — no HTTP servers.

4. **5-section docstring header** at the top of every new module (purpose, called by, calls, owns tables, config keys, tests). Already covered in §2.2.

5. **DA4 NEVER-import_module** for any static analysis (deep report Area 5). DocConsistency v1 does NOT need AST/import-module — its check is `Path.read_text().splitlines() ⇒ len() >= line_no`. The AST machinery in `src/tools/testpatternscan/rules.py:36-94` is preserved as the v2 upgrade path; v1 deliberately does not touch it.

6. **Typed errors only** (`ContractMismatchError`, `BaselineNotFoundError`, `GitMissingError`, etc.) — never raw `RuntimeError` / `ValueError`. The `_cli_envelope.run_cli` JSON envelope surfaces `type(exc).__name__` verbatim; typed names give consumers semantic information.

---

## 3. Foundation Extension

### 3.1 `ContractsConfig` pydantic model — append to `src/tools/_config.py`

Append after `PgConfig` (after L114). New code:

```python
class NormalizeRule(BaseModel):
    """How to normalize a single parsed field before comparison.

    Four independent knobs (any combination, all optional):
      - tolerance: absolute numeric tolerance (e.g., 0.5 for gpu_temp_c drift
        within half a degree). Applies to fields that successfully parse as float.
      - mask_regex: regex pattern that, if it matches the *string form* of a
        value, replaces the value with the literal '<MASKED>' before comparison.
        Used for timestamp / hostname / instance-id fields that are expected to
        drift on every run.
      - ignore: bool — when True, the field is dropped entirely from the
        normalized snapshot. Use sparingly; an ignored field can never alert.
      - at_capture_redact (DA2 — RECORDING-TIME sanitization): list[str] of regex
        patterns. When recording (NOT verifying), each matched span in the raw
        stdout is replaced with '<REDACTED>' BEFORE the baseline JSON is
        committed. Use for absolute file paths, usernames, hostnames, MAC
        addresses, or any operator-PII that would otherwise be persisted to the
        repo via the baseline commit. This is the inverse of mask_regex: mask
        normalizes at compare-time; at_capture_redact prevents the secret from
        ever being written. Defaults to empty list (no redaction). Applies to
        the WHOLE raw stdout (pre-parse), so callers must compose regexes
        carefully — anything covered by the regex is gone from the baseline
        forever.
    """

    tolerance: float | None = None
    mask_regex: str | None = None
    ignore: bool = False
    at_capture_redact: list[str] = Field(default_factory=list)


class ContractDef(BaseModel):
    """A single named contract — what to invoke, how to parse, how to normalize.

    The `cmd` field is the LITERAL argv passed to nvidia-smi (or another CLI).
    Drift in `cmd` IS itself a contract change — ContractCheck does not
    auto-update cmd; the operator must explicitly re-record.

    `parse_fields` names the positional CSV columns (in the same order as
    --query-gpu emits them) so that ContractCheck can map columns to names.
    For non-CSV contracts (e.g., a 'git --version' string), parse_fields=[]
    signals 'whole-stdout string compare'.
    """

    cmd: list[str]
    description: str
    timeout_s: int = 10
    parse_fields: list[str] = Field(default_factory=list)
    normalize: dict[str, NormalizeRule] = Field(default_factory=dict)


class ContractsConfig(BaseModel):
    """`contracts:` section — keyed by contract name.

    Empty by default. Tier 3's #107 effort seeds it with one entry:
    `nvidia-smi-watchloop` pinning the watchloop's nvidia-smi invocation.
    """

    # The model is just a dict[str, ContractDef] but wrapping in BaseModel
    # gives us validation + a clear named type for the rest of the codebase.
    entries: dict[str, ContractDef] = Field(default_factory=dict)
```

Then extend `ArcisConfig` (L116-123) by appending one field:

```python
class ArcisConfig(BaseModel):
    """Top-level tooling config — the object returned by `load_arcis_config()`."""

    paths: PathsConfig
    ports: PortsConfig
    services: ServicesConfig
    safety_windows: dict[str, SafetyWindow]
    pg: PgConfig
    contracts: dict[str, ContractDef] = Field(default_factory=dict)   # NEW
```

**Rationale for the flat `dict[str, ContractDef]` (NOT wrapped in `ContractsConfig.entries`):** matches existing `safety_windows: dict[str, SafetyWindow]` (L122) precedent. Top-level extension is one field; nested `entries:` is unnecessary indirection. The `ContractsConfig` class is *defined* for future use (e.g., per-tool methods) but not used directly in `ArcisConfig` in v1. (Alternative considered & rejected: nested `contracts: ContractsConfig` — adds a YAML nesting level for no current gain.)

**Backward compat:** `Field(default_factory=dict)` ensures existing `arcis_config.yaml` files with no `contracts:` section still load cleanly. No Tier 1+2 tool reads the new field — they continue functioning unchanged.

### 3.2 `arcis_config.yaml` — append after L146 (the `pg` section)

Append (operator-tone comments, matching existing yaml style):

```yaml
# ─── CONTRACTS (ContractCheck v1 baselines) ───────────────────────────
# Snapshots of external-CLI invocations whose argv shape + parsed output
# the production code pins. Drift in argv (operator changes the call)
# OR drift in output (vendor changes the CLI's behavior, e.g., nvidia-smi
# emits [N/A] where it used to emit integers) signals upstream regression.
#
# The v0.36.29 [N/A] incident is the north-star: nvidia-smi started
# emitting '[N/A]' for power.draw on a fresh driver install; the watchloop
# silently degraded to 'GPU data unavailable' via its broad except clause.
# ContractCheck v1 catches that by recording the live output once, then
# diffing on every subsequent invocation.
#
# Adding a new contract — PRE-RECORD AUDIT CHECKLIST (DA2):
#   1. Manually run the proposed `cmd` and inspect raw stdout.
#   2. Identify PII in the output: usernames, hostnames, computer names,
#      absolute paths containing them, MAC addresses, IP addresses, license
#      keys. (nvidia-smi --query-gpu CSV emits pure numerics — no PII.
#      nvidia-smi --query-compute-apps emits process paths containing
#      C:\Users\... — IS PII.)
#   3. For each PII class, add an `at_capture_redact` regex entry to that
#      field's `normalize:` section. Recording-time sanitization replaces
#      matches with '<REDACTED>' BEFORE baseline JSON is written. See spec §4.4a.
#   4. Append a new entry below (see nvidia-smi-watchloop for the shape).
#   5. Run `python -m src.tools.contractcheck record <name>` — writes
#      data/contracts/<name>/<ISO-timestamp>.json + latest_ref.txt.
#   6. Inspect the resulting baseline JSON to CONFIRM redaction worked
#      (grep for known PII strings — must return zero matches).
#   7. Commit both artifacts. (data/contracts/ is gitignore-allowlisted.)
contracts:
  nvidia-smi-watchloop:
    description: |
      Watchloop GPU metrics invocation — pinned to
      src/monitoring/system_metrics.py:36-45 verbatim. Five queried fields
      in CSV, no header, no units. 5-second timeout.
    cmd:
      - nvidia-smi
      - --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw
      - --format=csv,noheader,nounits
    timeout_s: 5
    parse_fields:
      - gpu_util_pct
      - gpu_vram_used_mb
      - gpu_vram_total_mb
      - gpu_temp_c
      - gpu_power_w
    normalize:
      gpu_util_pct:
        tolerance: 5.0         # ±5% absolute (operator runs watchloop at near-idle most of the time)
      gpu_vram_used_mb:
        tolerance: 2048.0      # ±2GB (transient cache + active model weights swap-in/out)
      gpu_temp_c:
        tolerance: 10.0        # ±10°C (idle ~45°C vs warm-load ~55°C; thermal swing modest at idle workloads)
      gpu_power_w:
        tolerance: 50.0        # ±50W (idle ~10-20W; baseline recording captures one snapshot — wider than util drift, narrower than full idle→load range)
      # gpu_vram_total_mb: no normalize — should be CONSTANT (catches hardware swap)
```

**Per-field tolerance rationale (DA1-recalibrated):** v1 ContractCheck detects BOTH value drift AND shape drift. Calibrated tolerances are tight enough to surface anomalous values (e.g., GPU util at 90% during a supposed idle window — likely a runaway process) while still suppressing routine second-to-second drift. The earlier all-wide calibration (100%/24576MB/50°C/400W) effectively reduced ContractCheck to shape-only drift detection — a useful subset but strictly less than the tool's design intent. The recalibrated tolerances reflect operator-observed steady-state ranges on the RTX 3090 dev box during watchloop quiet windows.

- `gpu_util_pct: 5.0` — watchloop runs at near-idle most of the time (operator's "quiet window" cadence). A 5% threshold surfaces unexpected sustained load.
- `gpu_vram_used_mb: 2048.0` — accounts for ~2GB transient cache swings without alerting on routine model weight shuffles.
- `gpu_temp_c: 10.0` — thermal swing at idle workloads is modest; 10°C surfaces a thermal anomaly.
- `gpu_power_w: 50.0` — idle is 10-20W; ±50W catches ramp-up to load without triggering on routine telemetry noise.
- `gpu_vram_total_mb`: NO normalization. Constant 24576 on the RTX 3090. Drift = hardware swap = re-record baseline (operator action).

**Reversibility:** these are config values in `arcis_config.yaml`, not source code. If the chosen tolerances prove operator-noisy in production, the operator widens them by editing YAML and re-running verify — no code change, no migration. v1's published calibration is an INITIAL guess; the operator's first weeks of running `verify` produce the empirical data to refine.

**Downstream implication:** with tight tolerances, first-week verify runs may produce `verdict='DRIFT'` events on benign value swings. The operator triages, decides whether to widen tolerance (write YAML), re-record baseline (capture a more representative snapshot), or treat the drift as real and investigate. This is the design intent — value drift is detected, not suppressed.

### 3.3 `.gitignore` — append after L42

Exact change (preserves the 2-line `data/reference/` precedent at L41-42):

```gitignore
# Runtime data
*.sqlite3
*.sqlite3-wal
*.sqlite3-shm
*.sqlite3-journal
*.sqlite3.corrupted
logs/
data/
!data/reference/
!data/reference/**
!data/contracts/                       # NEW — ContractCheck baselines (committed)
!data/contracts/**                     # NEW — content of baselines (per data/reference/ pattern)
!data/docconsistency-allowlist.yaml    # NEW — DocConsistency allow-list (single file)
```

**Why three appends and not two:** `data/contracts/` is a *directory* and needs the 2-line allowlist pattern that `data/reference/` uses. `data/docconsistency-allowlist.yaml` is a single file with no subdirectory — one line suffices. The deep report Area 12 confirmed the data/reference precedent requires both `!data/reference/` AND `!data/reference/**` (gitignore rules).

**Verification at impl time (T1 acceptance check):** after appending, run `git check-ignore --verbose data/contracts/nvidia-smi-watchloop/foo.json` — must return *not ignored* (exit 1). And `git check-ignore --verbose data/halcyon.db` — must return *ignored* (exit 0, preserving existing behavior).

### 3.4 `data/docconsistency-allowlist.yaml` — empty seed (Task T1)

T1 creates this file with a minimal scaffold (operator-curated content added later as DocConsistency v1 surfaces findings):

```yaml
# DocConsistency v1 allow-list — file:line refs that are intentionally
# historical and should NOT be flagged.
#
# Format: each entry is a free-form string equal to the LITERAL match
# DocConsistency emits (e.g., `src/scheduler/vram_manager.py:266` from
# CHANGELOG.md:1304). The DocConsistency scanner compares each found ref
# against this list; any match is suppressed.
#
# The deep-report Phase 4 analysis identified that CHANGELOG.md:1234-1310
# (v0.36.29 hotfix entry) cites multiple now-deleted files. Those refs
# are historically accurate — the entry is documenting a fix that has
# since been refactored away. They go HERE so DocConsistency doesn't
# alert on them.
#
# Operator workflow: when DocConsistency emits a finding the operator
# considers historical, copy the exact `file:line` token here, commit,
# rerun. The empty seed below is intentional — let the operator triage
# real findings rather than pre-curating.
allowlist: []
```

The `allowlist: []` form is parsed by `yaml.safe_load` as an empty list under the `allowlist` key. DocConsistency reads `data['allowlist']` and treats every entry as an exact-match suppress.

---

## 4. ContractCheck — Detailed Design

### 4.1 Tool API

**Module:** `src/tools/contractcheck/`

**Python API:** three top-level functions, exported by `__init__.py`:

```python
def record(name: str, *, config_path: Path | None = None) -> Path:
    """Invoke contract `name`, write a new timestamped baseline, update latest_ref.txt.

    Returns the absolute Path of the newly written baseline JSON.
    Raises:
      - ContractNotConfiguredError: name is not present in arcis_config.yaml's contracts.
      - NvidiaSmiMissingError (or other CLI-specific): the contracted exe is not on PATH.
      - ContractInvocationError: subprocess returned non-zero or timed out.
    Does NOT raise on parse failure — captures stdout verbatim into the baseline.
    """

def verify(name: str, *, config_path: Path | None = None) -> dict:
    """Invoke contract `name`, compare against latest_ref baseline, return diff dict.

    Returns a dict (schema in §4.5):
      {
        'contract': '<name>',
        'baseline_path': '<absolute path>',
        'baseline_timestamp': '<ISO 8601>',
        'live_invocation_ok': bool,
        'fields': {<field_name>: {'baseline': ..., 'live': ..., 'status': 'match'|'tolerance'|'mismatch'|'shape_change'}},
        'verdict': 'PASS' | 'DRIFT' | 'INVOCATION_FAILED',
      }
    Raises BaselineNotFoundError if no latest_ref exists for this contract.
    Does NOT raise on field drift — drift is signaled via verdict='DRIFT'.
    """

def diff(name: str, baseline_a: str, baseline_b: str, *, config_path: Path | None = None) -> dict:
    """Compare two recorded baselines (by filename, not path).

    Useful for operator forensics: 'what changed between Tuesday's baseline
    and Thursday's?' Same return shape as verify() but with 'baseline_a' /
    'baseline_b' instead of 'live'.
    """
```

Each is decorated with `@safe_op(name="contractcheck", mutates=False)` (verified signature at src/tools/_safety.py:167-172; existing call site for reference: src/tools/dbquery/core.py:162). All three operations are read-only in the audit-log sense; `record` writes to `data/contracts/` which is operator-state (auditable, git-tracked), not application-state — hence `mutates=False`.

### 4.2 CLI signature

**Entry point:** `python -m src.tools.contractcheck <subcommand> [options]`

Three subcommands:

```
python -m src.tools.contractcheck record <name> [--json]
python -m src.tools.contractcheck verify <name> [--json]
python -m src.tools.contractcheck diff   <name> <baseline_a> <baseline_b> [--json]
```

For each:
- Success → human-readable output to stdout, `sys.exit(0)`.
- `--json` + success → JSON dict (the dict returned by the function above) to stdout, `sys.exit(0)`.
- Failure (any typed error) → re-raise (or, with `--json`, the standard `_cli_envelope` error envelope to stdout, exit 1).

This matches the existing Tier 1/2 pattern (see `src/tools/capabilityregistry/__main__.py:63-80`).

### 4.3 Baseline storage layout

```
data/contracts/
└── <contract_name>/                       (one directory per contract)
    ├── <ISO-timestamp>.json               (one file per recording)
    ├── <ISO-timestamp>.json               (older recordings retained)
    └── latest_ref.txt                     (single line: filename of the latest)
```

**Timestamp format:** `YYYY-MM-DDTHH-MM-SSZ` (Windows-safe — colons stripped, UTC `Z` suffix). This is the only departure from ISO 8601, motivated by NTFS reserved-character rules (`:` is forbidden in filenames). The contents of the JSON record include a properly-formatted ISO 8601 `recorded_at` field.

**`latest_ref.txt`:** plain ASCII file, single line, **just the filename** (e.g., `2026-05-25T17-30-00Z.json`) — NOT a full path. ContractCheck reads `latest_ref.txt`, strips whitespace, joins with the directory path to resolve the baseline. Plain text — NOT a symlink (DD-3; deep report Area 14 confirmed zero existing symlink patterns in `src/`).

**Why retain old baselines:** auditability. If `verify` reports drift today, the operator wants to see what the baseline was last week to differentiate "vendor changed behavior" from "operator updated baseline." Disk cost is minimal (each JSON ~2-5 KB).

### 4.4 Baseline JSON schema (the thing committed to git)

```json
{
  "contract": "nvidia-smi-watchloop",
  "recorded_at": "2026-05-25T17:30:00.000000Z",
  "cmd": [
    "nvidia-smi",
    "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
    "--format=csv,noheader,nounits"
  ],
  "description": "Watchloop GPU metrics invocation — pinned to src/monitoring/system_metrics.py:36-45 verbatim.",
  "timeout_s": 5,
  "returncode": 0,
  "stdout": "42, 4096, 24576, 58, 175.30\n",
  "stderr": "",
  "parsed_fields": {
    "gpu_util_pct": 42.0,
    "gpu_vram_used_mb": 4096.0,
    "gpu_vram_total_mb": 24576.0,
    "gpu_temp_c": 58.0,
    "gpu_power_w": 175.30
  },
  "parse_ok": true,
  "normalization_applied": {
    "gpu_util_pct": "tolerance=100.0",
    "gpu_vram_used_mb": "tolerance=24576.0",
    "gpu_temp_c": "tolerance=50.0",
    "gpu_power_w": "tolerance=400.0"
  },
  "tool_version": "v0.36.65"
}
```

Written via **atomic write discipline** (CHANGELOG.md:107 documents the ci-investigate cache convention — `data/cache/ci-investigate/` is a runtime-created/gitignored cache and the directory does not exist on disk until first invocation; the documentary precedent is the atomic-write idiom, not the directory itself). The idiom is inheritable from `src/tools/ciinvestigate/core.py:64`ff: tempfile + fsync + `os.replace`. Uses `json.dumps(..., sort_keys=True, indent=2, ensure_ascii=False)` for clean git diffs. Trailing newline. `encoding='utf-8'` explicit. LF line endings (no Windows CRLF) for git-diff readability — `newline='\n'` on `open()`.

### 4.4a Output sanitization at recording time (DA2)

ContractCheck baselines are committed to the git repository — making `data/contracts/<name>/<timestamp>.json` a permanent, blameable, operator-readable artifact. This is the design intent (audit trail). But it carries a corollary risk: **any operator-PII present in the raw stdout — absolute file paths containing usernames, hostnames, MAC addresses, computer names — would be permanently recorded.**

For the v1 `nvidia-smi-watchloop` contract, `nvidia-smi --query-gpu` emits pure CSV numerics — no PII risk. But the contract framework is general; future contracts (e.g., `--query-compute-apps`, which emits process names + paths containing `C:\Users\mille\...` per the v0.36.29 incident) WILL surface PII.

**`at_capture_redact` mechanism (NormalizeRule field added in §3.1):**

When `record()` runs:
1. Captures raw stdout from `_subprocess.run`.
2. Stores raw stdout in `baseline['stdout']` (the field used for human-readable diffing).
3. **Before write**, iterates each contract's per-field `normalize` entries and, for each `at_capture_redact` regex, replaces matches in BOTH `baseline['stdout']` AND `baseline['parsed_fields']` (string form). The replacement is literal `<REDACTED>`.
4. `baseline['stdout']` is the redacted form. The raw, un-redacted stdout is NEVER persisted — it lives only in process memory during `record()`.
5. The `normalization_applied` metadata field records `'at_capture_redact: <N patterns applied>'` for audit.

**v1 default for `nvidia-smi-watchloop`:** empty `at_capture_redact` list. The CSV output is pure numerics; no redaction needed. Documented in the YAML seed (§3.2) for clarity.

**Pre-record audit checklist (operator workflow, also referenced in §3.2):** before adding a new contract to `arcis_config.yaml`, the operator:
1. Manually runs the proposed `cmd` and inspects raw stdout.
2. Identifies any PII: usernames, hostnames, computer names, absolute paths containing them, MAC addresses, IP addresses, license keys.
3. Adds `at_capture_redact` regex entries to the contract's `normalize:` section covering each class of PII.
4. Runs `python -m src.tools.contractcheck record <name>` and inspects the resulting baseline JSON to CONFIRM redaction.
5. Only then commits the baseline.

**Verify-time interaction:** `at_capture_redact` is applied at RECORDING TIME ONLY. When `verify()` runs:
- It re-captures live stdout.
- It re-applies `at_capture_redact` to the live stdout for comparison purposes (so live PII is redacted in the diff dict).
- The live stdout — redacted — is part of the verify return value, NOT committed to disk (verify() doesn't write to data/contracts/).

This double-application ensures comparison correctness: baseline stdout `"<REDACTED>, 4096, ..."` vs live stdout `"<REDACTED>, 4096, ..."` → match. Without redaction at verify time, a live `"<C:\Users\mille\...>"` would never match a baseline `"<REDACTED>, ..."` and DRIFT would be a false positive every run.

**Reversibility:** `at_capture_redact` is config; if the operator decides a contract no longer needs redaction (e.g., the producing CLI changed to never emit PII), removing the regex from `arcis_config.yaml` and re-recording produces a clean baseline.

**Limitation:** `at_capture_redact` operates on the captured stdout — it does NOT protect against stderr leaks (rare for the contracts in scope) or against PII in the `cmd` argv itself (operator-curated). The operator audits `cmd` at config-time.

### 4.5 Verify diff dict (what `verify()` returns)

```python
{
  "contract": "nvidia-smi-watchloop",
  "baseline_path": "C:/arcis/halcyon-lab/data/contracts/nvidia-smi-watchloop/2026-05-25T17-30-00Z.json",
  "baseline_timestamp": "2026-05-25T17:30:00.000000Z",
  "live_invocation_ok": True,
  "fields": {
    "gpu_util_pct":     {"baseline": 42.0, "live": 38.0, "status": "tolerance"},
    "gpu_vram_used_mb": {"baseline": 4096.0, "live": 4192.0, "status": "tolerance"},
    "gpu_vram_total_mb":{"baseline": 24576.0, "live": 24576.0, "status": "match"},
    "gpu_temp_c":       {"baseline": 58.0, "live": 59.0, "status": "tolerance"},
    "gpu_power_w":      {"baseline": 175.30, "live": "[N/A]", "status": "shape_change"},
  },
  "verdict": "DRIFT",
}
```

**Status values (per-field):**
- `match` — values equal (or both `None`).
- `tolerance` — values differ by ≤ the per-field tolerance; counts as match for verdict purposes.
- `mismatch` — values differ by > tolerance (or no tolerance configured and not equal); contributes to DRIFT verdict. **(VALUE drift detection — calibrated per §3.2 DA1-recalibrated tolerances.)**
- `shape_change` — the live value cannot be parsed in the same way as the baseline (e.g., baseline was a float, live is `[N/A]`); contributes to DRIFT verdict. **(SHAPE drift detection — THIS IS THE v0.36.29 NORTH-STAR DETECTOR.)**

**v1 detects BOTH value AND shape drift** (DA1 recalibration). Earlier wide-tolerance calibration effectively reduced ContractCheck to shape-only — see §3.2 for the recalibrated tolerances. Tests for both classes are mandatory (see §9.2 / T6).

**Verdict values (overall):**
- `PASS` — all fields are `match` or `tolerance`, and `live_invocation_ok` is True.
- `DRIFT` — at least one field is `mismatch` or `shape_change`, and `live_invocation_ok` is True.
- `INVOCATION_FAILED` — `live_invocation_ok` is False (subprocess returned non-zero, timed out, or exe missing). Field-level diff is N/A.

### 4.6 Error classes

All defined in `src/tools/contractcheck/core.py`. All subclasses of a single `ContractCheckError(RuntimeError)` root so callers can catch one class.

- `ContractCheckError` — root.
- `ContractNotConfiguredError` — name not in arcis_config.yaml's contracts.
- `BaselineNotFoundError` — `latest_ref.txt` is missing or points to a nonexistent file.
- `BaselineCorruptError` — baseline JSON fails to parse or is missing required fields.
- `ContractInvocationError` — subprocess returned non-zero or timed out (wraps the CompletedProcess.stderr).
- `NvidiaSmiMissingError` — `nvidia-smi` not on PATH (from `_subprocess.resolve_exe`). NEW in `_subprocess.py` per §3.1.

### 4.7 The v0.36.29 north-star — verify-by-mutation testing (FORENSIC-tool framing)

The deep-report Phase 4 analysis confirmed the original v0.36.29 hotfix test file (`tests/test_vram_manager_na_memory.py`) is DELETED along with the source it tested (`src/scheduler/vram_manager.py`). The captured live output from that incident (`'2195136, C:\\Users\\mille\\AppData\\Local\\Programs\\Ollama\\ollama.exe, [N/A]'`) cannot be reused — it came from `--query-compute-apps`, not `--query-gpu`. The v1 contract pins `--query-gpu`.

**Honest framing — what the test PROVES (and what it does NOT prove):**

ContractCheck v1 is a **FORENSIC tool**. The verify-by-mutation test (`test_verify_na_north_star`) proves that ContractCheck's `verify()` LOGIC correctly detects a `[N/A]` sentinel as `shape_change` AND that calibrated value drift triggers `mismatch` — in ISOLATION (with mocked `_subprocess.run`). What it does NOT prove:

- It does NOT prove that the watchloop (`src/monitoring/system_metrics.py:36-56`) at runtime would surface a `[N/A]` to ContractCheck. The watchloop's broad-except clause continues to silently swallow `[N/A]` until #117 closes.
- It does NOT prove that ContractCheck is invoked on a schedule. v1 is operator-invoked only; periodic scheduling is a #111 / future-effort wiring (see §11.5 deferral).
- It does NOT prove that drift is observed *before* a downstream incident. In v0.36.29, the regression was discovered when downstream effects (incorrect VRAM handoff) appeared in operations. ContractCheck v1 catches the same class of regression IF the operator runs `verify` while the regression is active — which requires either operator suspicion or scheduled invocation.

**ContractCheck v1's positive value:**
- When the operator suspects drift (e.g., "my watchloop logs look weird this morning"), one command (`python -m src.tools.contractcheck verify nvidia-smi-watchloop`) provides a structured diff against the committed baseline.
- When #111 wires scheduled invocation, the same logic runs on cron, catching drift within the scheduling window.
- The committed baseline is itself documentation — operators reviewing the PR see the exact argv shape and field values the watchloop assumes.

**Test design (T6 acceptance gate):**

The test does NOT reuse a historical fixture. Instead, it:

1. Records a baseline by mocking `_subprocess.run` to return a known-good stdout: `'42, 4096, 24576, 58, 175.30\n'`.
2. Verifies the JSON written to disk parses all 5 fields cleanly with `parse_ok=true`.
3. Mocks `_subprocess.run` AGAIN — this time returning `'42, 4096, [N/A], 58, 175.30\n'` (simulating the v0.36.29 incident shape: a `[N/A]` sentinel in column 3).
4. Calls `verify('nvidia-smi-watchloop')`.
5. Asserts the returned dict has `fields.gpu_vram_total_mb.status == 'shape_change'` and `verdict == 'DRIFT'`.
6. A SECOND mutation test verifies value drift: with a baseline of `gpu_util_pct=42.0`, a live stdout of `gpu_util_pct=78.0` (delta=36, exceeds DA1-recalibrated tolerance of 5.0) returns `status='mismatch'` and `verdict='DRIFT'`.

This is the **verify-by-mutation north-star** for verify-LOGIC correctness. The vacuous-test pattern (operator memory `feedback_vacuous_test_pattern`) is avoided because both tests FAIL if `verify()` returns `verdict=PASS` — they test the actual code path. The runtime-integration gap (watchloop instrumentation) is acknowledged here and deferred to #111/#117 per §11.5.

### 4.8 Initial baseline recording (Task T5)

After T2 lands the ContractCheck subpackage and T1 lands the foundation extension, Task T5 records the first live baseline:

```
python -m src.tools.contractcheck record nvidia-smi-watchloop
```

This writes:
- `data/contracts/nvidia-smi-watchloop/<live timestamp>.json` (the operator's actual GPU's live values).
- `data/contracts/nvidia-smi-watchloop/latest_ref.txt` (containing the filename).

Both files are then **committed to the PR**. This is the first time `data/contracts/` is non-empty in the repo.

**WHY this is in the PR, not deferred:**

The operator's `feedback_complete_efforts_no_deferral` discipline applied to this effort: ContractCheck without an initial baseline is half-built. A future operator running `python -m src.tools.contractcheck verify nvidia-smi-watchloop` on a fresh clone would hit `BaselineNotFoundError` instead of getting a usable diff. T5 closes that gap *within* this effort.

### 4.9 Latent bug discovery — `system_metrics.py:36-56` (FOLLOW-UP #117)

**Finding (from deep report Phase 4):**

`src/monitoring/system_metrics.py:36-56` has **no active `[N/A]` defense**. The five `float(parts[N])` calls at L51-55 would raise `ValueError` on any `[N/A]` sentinel in the parsed CSV. The broad `except (FileNotFoundError, subprocess.TimeoutExpired, Exception)` at L57 catches this — but it silently degrades to `_gpu_none()`, masking the regression.

The original v0.36.29 hotfix that explicitly handled `[N/A]` lived in `src/scheduler/vram_manager.py:266,340`. That file has been DELETED (`tests/test_overnight_handoff_removed.py:25-32` proves it). The current watchloop relies purely on the broad-except clause for `[N/A]` resilience — which works in the sense of "doesn't crash," but fails in the sense of "doesn't alert."

**Why this is NOT bundled into #107:**

Operator's `feedback_complete_efforts_no_deferral` memory is the deciding principle:

> within an effort deliver ALL of it OR scope the effort smaller; never punt sub-items to operator-memory ('we'll do later')

#107's *scope* is "build three tools that surface meta-quality findings." It is NOT "fix every meta-quality finding the tools surface." Bundling the system_metrics.py fix would inflate scope by an unrelated patch — exactly the kind of scope creep the operator's rigor memo cautions against (`feedback_strict_rigor_no_handwave`).

The correct application of the no-deferral rule at the effort-boundary is: **file the new finding as its own effort with its own tracking ID, not as a memory-note or a TODO comment.** Task #117 "Restore [N/A] defense in system_metrics.py nvidia-smi parser" is filed in the operator's task list (verified above this design). #107 ships with the latent bug present; #117 ships the fix.

The spec acknowledges #117 in §0, §4.7, and §11.5. ContractCheck v1's first run will emit a baseline that *includes* whatever value `power.draw` returns — if the operator's hardware happens to return `[N/A]` at T5 record time, the baseline captures `"[N/A]"` as the live value and `parse_ok=false`. That is correct behavior: the baseline records what the system currently produces. When #117 lands and adds explicit `[N/A]` handling, the operator re-records the baseline.

---

## 5. GitArchaeology — Detailed Design

### 5.1 Op-surface (7 ops per BRIEF)

Operator-confirmed at interview: **7 read-only ops**. The deep-report Area 8 flagged a discrepancy with the git-historian spec (which lists 9), but the operator's interview answer is the authority. The two additional ops the agent spec mentions (`rev-parse`, `remote -v`) are explicit follow-ups (see §11.4), not in v1's surface.

| Op | git invocation pattern | Default timeout | Output shape |
|----|------------------------|-----------------|--------------|
| `log` | `git log --format=<FMT> [<flags>] [-- <path>]` (`format=` + `format_columns=` kwarg pair — see §5.3.1) | 30 s | list of `{sha, author, date, subject, body}` (default columns) |
| `blame` | `git blame -L <start>,<end> -- <file>` | 60 s | list of `{sha, author, content, line}` |
| `show` | `git show <sha> [-- <path>]` | 30 s | dict `{sha, author, date, subject, body, diff}` |
| `diff` | `git diff <ref_a>..<ref_b> [-- <path>]` | 30 s | str (unified diff text) |
| `rev-list` | `git rev-list <range> [-- <path>]` | 30 s | list of `{sha}` |
| `merge-base` | `git merge-base <ref_a> <ref_b>` | 10 s | str (sha) |
| `tag-l` | `git tag -l [<pattern>]` | 10 s | list of `{tag}` |

### 5.2 FORBIDDEN list (mirrors #108 git-historian agent prompt verbatim)

The agent prompt at `docs/audits/2026-05-25-specialized-agents/specs/2026-05-25-specialized-agents-design.md:424` lists the FORBIDDEN ops. GitArchaeology's CLI subcommands are an explicit allow-list — any non-listed op is rejected by argparse. The forbidden list is documented in the module docstring AND enforced structurally (no subcommand exists for them):

- `git commit` — mutates history
- `git push` — mutates remote
- `git reset` — mutates working tree / HEAD
- `git rebase` — mutates history
- `git checkout` (destructive variants) — mutates working tree
- `git branch -D` — destroys branches
- `git clean -f` — destroys untracked files
- `git cherry-pick` — mutates history
- `git stash drop` — destroys stashed work
- `git tag -d` — destroys tags

GitArchaeology's argparse subparsers do not register any of these — invoking, e.g., `python -m src.tools.gitarchaeology commit` raises argparse `error: argument cmd: invalid choice: 'commit'`. Defense by absence, not by runtime check.

### 5.3 Python API (exported from `__init__.py`)

All 7 functions are decorated with `@safe_op(name="gitarchaeology", mutates=False)` (the same pattern used by Tier 1+2 — see src/tools/symbolfind/core.py:153). Signatures:

```python
def log(
    range: str | None = None,
    *,
    path: str | None = None,
    format: str = "%H%x09%an%x09%ai%x09%s",
    limit: int = 50,
    repo: str | None = None,                 # -C <repo>; default = repo root
    timeout_s: int = 30,
) -> list[dict]:
    """Run `git log [--format=<format>] [<range>] [-- <path>]`.

    Returns list of dicts (one per commit). Each dict has keys:
      sha (str, full 40-char hex)
      author (str)
      date (str, ISO 8601 with timezone)
      subject (str)
      body (str, may be empty)

    Note: body is fetched in a separate `git show` call when explicitly
    requested via include_body=True, since `git log` doesn't natively
    return multiline body in a single-line format. For v1, body=''
    unless include_body=True is passed.
    """

def blame(
    file: str,
    *,
    start_line: int | None = None,
    end_line: int | None = None,
    repo: str | None = None,
    timeout_s: int = 60,
) -> list[dict]:
    """Run `git blame -L <start>,<end> -- <file>` (line range optional).

    Returns list of dicts (one per source line):
      sha (str, full 40-char hex of the originating commit)
      author (str)
      content (str, the actual source line, may be empty)
      line (int, line number in the file)
    """

def show(
    sha: str,
    *,
    path: str | None = None,
    repo: str | None = None,
    timeout_s: int = 30,
) -> dict:
    """Run `git show <sha> [-- <path>]`.

    Returns dict:
      sha (str)
      author (str)
      date (str, ISO 8601)
      subject (str)
      body (str)
      diff (str, unified diff text)
    """

def diff(
    ref_a: str,
    ref_b: str,
    *,
    path: str | None = None,
    repo: str | None = None,
    timeout_s: int = 30,
) -> str:
    """Run `git diff <ref_a>..<ref_b> [-- <path>]`. Returns unified diff text."""

def rev_list(
    range: str,
    *,
    path: str | None = None,
    limit: int | None = None,                # None = unlimited (operator-explicit)
    repo: str | None = None,
    timeout_s: int = 30,
) -> list[dict]:
    """Run `git rev-list <range> [-- <path>]`. Returns list of {sha}."""

def merge_base(
    ref_a: str,
    ref_b: str,
    *,
    repo: str | None = None,
    timeout_s: int = 10,
) -> str:
    """Run `git merge-base <ref_a> <ref_b>`. Returns the merge-base sha."""

def tag_l(
    pattern: str | None = None,
    *,
    repo: str | None = None,
    timeout_s: int = 10,
) -> list[dict]:
    """Run `git tag -l [<pattern>]`. Returns list of {tag}."""
```

### 5.3.1 Output parsing contract (DA3)

The `log` op's output parser MUST follow these 5 rules. Other parsers (blame, show, rev-list, tag-l) follow analogous discipline; the spec captures the log case in detail because the embedded-tab risk surfaces most often there.

1. **`str.split('\t', N-1)` with explicit maxsplit, NEVER unbounded `split('\t')`.** For the default 4-column format `%H%x09%an%x09%ai%x09%s` (subject LAST), parser uses `line.split('\t', 3)` → exactly 4 fields. Any extra `\t` in the subject (commit messages with embedded tabs) goes into field [3], the subject — NOT shoved into a phantom 5th column that gets dropped. Without maxsplit, `'abc\tdef\tghi\tjkl\tmno'.split('\t')` returns 5 fields and the parser silently loses data.

2. **`format=` + `format_columns=` kwarg pair on `log()`.** When the caller passes a custom `format=` argument (e.g., `format='%H%x09%an%x09%ae%x09%ai%x09%s%x09%b'`), they MUST also pass `format_columns=['sha', 'author', 'email', 'date', 'subject', 'body']` (length N). The parser uses `len(format_columns) - 1` as the maxsplit. If `format=` is passed without `format_columns=` (or with a mismatched length), `log()` raises `GitArgError` at the API boundary — BEFORE invoking git. This prevents silent column-shift bugs where a custom format is parsed using the default 4-column assumption.

3. **UTF-8 explicit on `_subprocess.run` stdout.** Subject lines contain unicode (operator commit messages have em-dashes, smart quotes, occasional non-Latin glyphs from copy-pasted error messages). `_subprocess.run` is already configured for UTF-8 (foundation-#104); the parser MUST NOT re-decode bytes — it consumes `result.stdout` as `str`.

4. **Subject field is ALWAYS LAST in the format string.** The default format `%H%x09%an%x09%ai%x09%s` places subject last; any custom format passed via `format=` MUST also place subject last (or whatever multi-tab-containing field is last). The parser docstring documents this constraint, and `log()` enforces it by checking `format_columns[-1]` is in `{'subject', 'body', 'message'}` (raising `GitArgError` otherwise).

5. **Malformed output raises `GitParseError`, NOT silent drop.** If a log line splits into fewer fields than expected (e.g., a commit with an empty subject — `git log` emits the trailing `\t` but split returns N-1 fields), the parser raises `GitParseError` with the offending line text and expected column count. This surfaces git-CLI behavior changes loudly instead of silently corrupting the parser output. Tests cover both the happy path (embedded tab in subject parsed correctly) and the unhappy path (malformed line raises GitParseError).

These 5 rules are documented in the `log()` function docstring AND verified by the T7 tests added below (§9.2 / `test_log_subject_with_embedded_tab`, `test_log_custom_format_requires_columns`, `test_log_custom_format_with_columns`, `test_log_parse_failure_raises`).

### 5.4 CLI signature

```
python -m src.tools.gitarchaeology log        [--range <range>] [--path <path>] [--format <fmt>] [--limit N] [--repo <dir>] [--json]
python -m src.tools.gitarchaeology blame      <file> [--start N] [--end N] [--repo <dir>] [--json]
python -m src.tools.gitarchaeology show       <sha> [--path <path>] [--repo <dir>] [--json]
python -m src.tools.gitarchaeology diff       <ref_a> <ref_b> [--path <path>] [--repo <dir>] [--json]
python -m src.tools.gitarchaeology rev-list   <range> [--path <path>] [--limit N] [--repo <dir>] [--json]
python -m src.tools.gitarchaeology merge-base <ref_a> <ref_b> [--repo <dir>] [--json]
python -m src.tools.gitarchaeology tag-l      [--pattern <glob>] [--repo <dir>] [--json]
```

Every subcommand routes through `_cli_envelope.run_cli` for uniform error envelope. Non-JSON mode prints to stdout in a tab-separated or unified-diff format depending on op; JSON mode prints `json.dumps(result)`.

**Default `--limit`:** `log` defaults to 50 (per operator BRIEF); `blame` has no implicit limit (see §5.4a for safety gate); `rev-list` is unbounded by default (matches `git rev-list` behavior) but accepts `--limit` for safety.

**`--max-output-bytes N` CLI flag (DA4):** every CLI subcommand accepts `--max-output-bytes N` to override the per-op default (see §5.4a). Useful when the operator knows a `show` of a very large refactor commit will exceed defaults and explicitly wants to truncate or raise the cap.

### 5.4a Output size governance (DA4)

Read-only git ops can produce arbitrarily large output: `git log --all` on a large repo, `git show` on a refactor-mega-commit, `git blame` on a 50k-line generated file. Without governance, GitArchaeology can consume operator memory (the agent sub-process) and corrupt automation (downstream consumers receive truncated/streamed output without knowing).

**Per-op `max_output_bytes` defaults (in `GitArchaeologyConfig` or operator-default constants in core.py):**

| Op | Default `max_output_bytes` | Rationale |
|----|----------------------------|-----------|
| `blame` | 2_000_000 (2 MB) | A 5000-line file at ~400 bytes/line = 2 MB. Above this, operator likely wants `--start-line / --end-line` not full file. |
| `show` | 10_000_000 (10 MB) | Refactor commits can be huge; cap protects against pathological cases (binary-blob commits, generated lockfile churn). |
| `diff` | 10_000_000 (10 MB) | Same logic as show. |
| `log` | `limit * 200` bytes (50 commits × 200 = 10_000 bytes default) | Per-commit overhead bounded; `limit=` controls total commits. The 200 byte/commit estimate matches a typical `--format=%H%x09%an%x09%ai%x09%s` line. |
| `rev-list` | `limit * 50` bytes (50 SHAs × 50 = 2_500 bytes default) | Pure SHA list — extremely tight. |
| `merge-base` | 100 bytes (single SHA) | Hard ceiling — anomalously larger output indicates git misuse. |
| `tag-l` | 1_000_000 (1 MB) | Tag list grows linearly with releases; 1 MB allows ~10k tags. |

**Pre-invocation gate for `blame`:** if `blame()` is called WITHOUT a `start_line`/`end_line` range AND the target file is >5000 lines (verified by `Path(file).read_text().count('\n')` BEFORE invoking git), raise `GitArgError('blame on a >5000-line file requires start_line + end_line; refusing to invoke git on full file')`. This catches the most common cause of multi-megabyte blame output BEFORE any subprocess is spawned.

**Post-invocation truncation:** after `_subprocess.run` returns, if `len(result.stdout.encode('utf-8')) > max_output_bytes`:
- If the op is `blame`/`show`/`diff` (single-call ops where partial output is meaningful), raise `GitOutputTruncatedError(message=..., partial_output=result.stdout[:max_output_bytes], original_size_bytes=len(result.stdout))`. The exception's `partial_output` and `original_size_bytes` fields allow callers to recover partial results if they catch the error and inspect.
- If the op is `log`/`rev-list`/`tag-l` (list ops), the limit is reached BEFORE the byte threshold via the `--limit`/`-n` argv flag — `max_output_bytes` is a defense-in-depth backstop.

**Operator override:** every CLI subcommand and Python API accepts `max_output_bytes=` to raise or lower the default. CLI: `python -m src.tools.gitarchaeology show <sha> --max-output-bytes 100000000` to fetch a 100 MB commit show. Python: `gitarchaeology.show(sha, max_output_bytes=100_000_000)`.

**`GitOutputTruncatedError` design:** subclass of `GitArchaeologyError`. Fields:
- `message: str` — human-readable explanation including the op, the limit, and the actual size.
- `partial_output: str` — the first `max_output_bytes` of stdout (utf-8 safe — truncated at a codepoint boundary, not mid-byte).
- `original_size_bytes: int` — the true output size.
- `op: str` — the op name (e.g., `'show'`).

This structured form lets downstream callers (the git-historian agent, future automations) decide whether to retry with a higher cap, accept the partial output, or fail cleanly.

### 5.5 Subprocess discipline

Every git invocation goes through `src.tools._subprocess.run` with explicit timeout. The pattern:

```python
from src.tools._subprocess import run, resolve_exe, GitMissingError  # NEW class added in §3.1

def _git(args: list[str], *, timeout_s: int, repo: str | None) -> str:
    exe = resolve_exe('git')                                  # raises GitMissingError
    full_args = [exe]
    if repo is not None:
        full_args.extend(['-C', repo])
    full_args.extend(args)
    result = run(full_args, timeout=timeout_s)
    if result.returncode != 0:
        raise GitInvocationError(
            f'git {args[0]} failed (exit {result.returncode}): {result.stderr.strip()}'
        )
    return result.stdout
```

**Critical detail — `git -C <repo>` precedes the op:** the deep report (Area 6) showed `walkforward_firewall.py:183-188` uses this pattern. GitArchaeology mirrors it. If `--repo` is unspecified, the helper omits `-C` entirely — `git` then uses the current working directory (which agents typically already set to repo root via their dispatch wrapper).

**Dubious-ownership hint (operator memory `reference_nssm_git_ownership`):** if `git` exits with a stderr containing the literal string `'fatal: detected dubious ownership'`, `GitInvocationError`'s message includes a remediation hint: `'run: git config --system --add safe.directory C:/arcis/halcyon-lab'`. Operator's NSSM services hit this; the message saves a debugging cycle.

### 5.6 Error classes

- `GitArchaeologyError` (root subclass of `RuntimeError`).
- `GitMissingError` (subclass of `subprocess.SubprocessError`, added to `_subprocess.py` per §3.1 — mirrors `NssmMissingError` / `GhMissingError`).
- `GitInvocationError` — subprocess exited non-zero. Wraps stderr.
- `GitArgError` — invalid arguments to a GitArchaeology API call (e.g., `blame` with start > end, `log(format=...)` without `format_columns=`, `blame` on a >5000-line file without line-range — DA3+DA4).
- `GitParseError` (DA3) — git subprocess succeeded (exit 0) but the parser cannot map stdout into the expected output shape (malformed/truncated/unexpected-format output). Fields: `message: str`, `offending_line: str`, `expected_columns: int`, `op: str`. Raised by `log()` per §5.3.1 rule 5; analogous parsers for `blame` / `show` raise the same class when their output doesn't match the documented shape.
- `GitOutputTruncatedError` (DA4) — output exceeded `max_output_bytes`. Subclass of `GitArchaeologyError`. Fields: `message: str`, `partial_output: str` (first `max_output_bytes` of stdout, utf-8 codepoint-boundary-safe), `original_size_bytes: int`, `op: str`. Raised per §5.4a post-invocation truncation logic.

### 5.7 Read-only-by-construction enforcement

GitArchaeology has no `commit` / `push` / `reset` / `rebase` / `checkout` / etc. subcommand. The argparse top-level `add_subparsers` registers ONLY the 7 read-only op names. Attempting to invoke a forbidden op fails at argparse parse time with `error: argument cmd: invalid choice`.

**No runtime if-statement is needed to reject mutating ops** — they cannot be reached. This is structural enforcement, not runtime defense.

---

## 6. DocConsistency — Detailed Design

### 6.1 v1 scope (class (a) ONLY)

DocConsistency v1 implements **only class (a)**: dead `file:line` references in markdown documentation. Three classes are explicit DEFERRALS:

- **Class (b)** — API signature drift (docstring claims `def foo(a, b)` but actual is `def foo(a, b, c)`).
- **Class (c)** — docstring-vs-code drift in module headers.
- **Class (d)** — symbol existence (docstring claims `from src.foo import bar` but `bar` doesn't exist in `src.foo`).

These deferrals are operator-confirmed at interview. They require AST parsing (the `src/tools/testpatternscan/rules.py:36-94` pattern). The v2/Tier 4 design path is preserved but not implemented in v1.

### 6.2 Python API

```python
def scan(
    targets: list[str] | None = None,        # None = default scope (see below)
    *,
    allowlist_path: Path | None = None,      # None = data/docconsistency-allowlist.yaml
    repo_root: Path | None = None,           # None = derive from __file__
) -> dict:
    """Scan markdown targets for file:line refs; verify each.

    Returns dict:
      {
        'scan_at': '<ISO 8601>',
        'targets_scanned': ['<path>', ...],
        'refs_found': N,
        'refs_verified_ok': M,
        'refs_allowlisted': K,
        'findings': [
          {
            'doc_path': '<relative path from repo root>',
            'doc_line': N,
            'ref': 'src/foo.py:42',
            'severity': 'file_missing' | 'line_missing',
            'detail': '<human-readable explanation>',
          },
          ...
        ],
      }
    """
```

Decorated `@safe_op(name="docconsistency", mutates=False)`.

### 6.3 CLI signature

```
python -m src.tools.docconsistency scan [--target PATH ...] [--allowlist PATH] [--json]
```

Defaults:
- `--target` omitted → scans the default scope: `CHANGELOG.md`, `README.md`, every `.md` file in `docs/standards/`, `docs/operator-guide.md`, `docs/cli-reference.md`, every `.md` file in `docs/audits/` modified within the last 90 days (filtered by `os.path.getmtime`).
  - **`docs/standards/` existence verified at design time:** the directory exists at the repo root and currently contains `boundary-touch-tests.md`. v1 scans whatever .md files live in that directory at impl time. If a future refactor empties the directory, the glob simply returns no files — no error.
  - Rationale: the deep-report Phase 4 analysis showed `docs/` has 40+ audit subdirs with potentially 5000+ refs total. Scanning all is operator-overwhelming (per the deep report's cross-cutting concern). The 90-day filter is per-file (modification date), not per-section (release date in CHANGELOG) — this is intentionally simpler than the CHANGELOG release-date filter to keep v1 minimal.
  - **`CHANGELOG.md` is ALWAYS scanned in full** (no age filter on its sections) per operator BRIEF. The allowlist absorbs intentional historical refs.
- `--allowlist` omitted → `data/docconsistency-allowlist.yaml`.

### 6.4 file:line ref regex

```python
import re

_REF_PATTERN = re.compile(
    r'`?'                                # optional opening backtick
    r'(?P<path>[\w/.\-]+\.(?:py|md|yaml|yml|json|sql|toml|ini|cfg|sh|js|ts|html))'
    r':'
    r'(?P<line>\d+)'
    r'(?:-\d+)?'                          # optional line RANGE (e.g., :130-147) — capture only start
    r'`?'                                # optional closing backtick
)
```

**v1 supports patterns A + B from the deep report (Area 9):**
- Pattern A: backtick-wrapped single line, e.g., `` `src/foo.py:42` ``
- Pattern B: backtick-wrapped line RANGE, e.g., `` `src/scheduler/watch.py:130-147` `` (verification uses the START line — line 130)

**Pattern C (comma-list, plain no-backtick form, e.g., `vram_manager.py:266,340`) is explicitly DEFERRED to v2** — operator-acknowledged exotic edge case. v1 ignores comma-separated multi-line refs.

**Extension to .md / .yaml / .json refs:** included in v1's regex so doc-to-doc refs (e.g., `docs/standards/foo.md:42`) are also verified. Same verification logic (line count check).

### 6.5 Verification logic

For each `(path, line)` match:

1. **Allow-list check (cheapest first):** if the literal token `f'{path}:{line}'` appears in the allowlist YAML's `allowlist:` list, count as allowlisted, skip remaining checks.
2. **File-exists check:** resolve `path` relative to repo root. If `Path(repo_root / path).is_file()` is False → severity `file_missing`. Add finding. Skip remaining checks.
3. **Line-exists check:** `len(path_obj.read_text(encoding='utf-8').splitlines()) >= line` → if False, severity `line_missing`. Add finding.

**Severity order (per operator BRIEF):** `file_missing > line_missing`. v1 has no `context_mismatch` severity (that would require reading the *content* of line N and comparing to surrounding doc context — operator-deferred as v2).

### 6.6 Allow-list mechanism

`data/docconsistency-allowlist.yaml` (committed to git via `.gitignore` `!data/docconsistency-allowlist.yaml` allowlist). Schema:

```yaml
allowlist:
  - 'src/scheduler/vram_manager.py:266'
  - 'tests/test_vram_manager_na_memory.py:32'
  # ... operator-curated entries ...
```

Matching is **exact string match** on `f'{path}:{line}'` (the canonical form — no backticks, no line ranges, just `path:line`). If a finding emits ref `\`src/foo.py:42\`` (with backticks), the allowlist key is `src/foo.py:42` (without). The scanner normalizes before comparison.

**Allowlist file safety:**
- Read with `encoding='utf-8'`.
- `yaml.safe_load`.
- If the file is missing → empty allowlist (no error). This allows DocConsistency to run on a fresh clone before the operator has curated any entries.
- If the file is malformed → `DocConsistencyAllowlistError`. Surfaces in the JSON envelope; CLI exit 1.

### 6.7 Error classes

- `DocConsistencyError` (root).
- `DocConsistencyAllowlistError` — allowlist YAML malformed.
- `DocConsistencyTargetMissingError` — explicit `--target PATH` that doesn't exist (default-scope misses are silent — files that don't exist aren't scanned).

### 6.8 SymbolFind v2 integration hint (deferred)

The deep-report Area 5 flagged: `src/tools/testpatternscan/rules.py:36-84` has an AST walker that extracts top-level module names with `find_spec`-only import discipline (DA4 NEVER-import_module). DocConsistency v2 will inherit this pattern for class (d) symbol existence. **v1 deliberately does NOT couple to it.** Adding the AST machinery in v1 adds complexity without v1 value.

---

## 7. File Tree

### 7.1 New files (15)

```
src/tools/contractcheck/
├── __init__.py                              (exports: record, verify, diff)
├── __main__.py                              (argparse subcommands; calls run_cli)
└── core.py                                  (all logic: record/verify/diff + helpers)

src/tools/gitarchaeology/
├── __init__.py                              (exports: log, blame, show, diff, rev_list, merge_base, tag_l)
├── __main__.py                              (argparse subcommands; calls run_cli)
└── core.py                                  (per-op _git helper + parsers)

src/tools/docconsistency/
├── __init__.py                              (exports: scan)
├── __main__.py                              (argparse; calls run_cli)
└── core.py                                  (regex + verification + allowlist)

tests/tools/test_contractcheck_integration.py    (unit + integration; covers record/verify/diff + N/A north-star)
tests/tools/test_gitarchaeology_integration.py   (unit + integration; covers 7 ops + forbidden absence)
tests/tools/test_docconsistency_integration.py   (unit + integration; covers scan + allowlist + severity)

data/contracts/nvidia-smi-watchloop/
├── <ISO-timestamp>.json                     (committed; first live baseline)
└── latest_ref.txt                           (committed; points to the above)

data/docconsistency-allowlist.yaml           (committed; empty allowlist seed)
```

**Test file naming convention:** `_integration.py` suffix matches the existing Tier 1+2 convention (verified: `test_dbquery_integration.py`, `test_logtail_integration.py`, etc.). The tests are NOT pure-unit — they exercise the CLI envelope via subprocess + the real filesystem for fixtures — hence the integration suffix is semantically correct as well.

### 7.2 Modified files (4)

```
.gitignore                                   (append 3 lines after L42)
config/arcis_config.yaml                     (append `contracts:` section after L146)
src/tools/_config.py                         (append NormalizeRule, ContractDef, ContractsConfig; extend ArcisConfig)
src/tools/_subprocess.py                     (append GitMissingError + NvidiaSmiMissingError; bump lru_cache maxsize to 6)
```

### 7.3 Documentation files updated (2)

```
CHANGELOG.md                                 (add v0.36.65 entry — Task T8)
MASTER.md                                    (no edit needed — Tier 3 tools auto-discover via src/tools/)
```

Total: 15 new files + 4 modified files + 2 doc-touched. Matches the ~16 files-affected estimate in BRIEF.

---

## 8. Error Handling Strategy

### 8.1 Error class hierarchy (all subclass `RuntimeError` for tool catchability)

```
RuntimeError
├── ContractCheckError
│   ├── ContractNotConfiguredError
│   ├── BaselineNotFoundError
│   ├── BaselineCorruptError
│   └── ContractInvocationError
├── GitArchaeologyError
│   ├── GitInvocationError
│   ├── GitArgError
│   ├── GitParseError           (NEW DA3 — see §5.6)
│   └── GitOutputTruncatedError (NEW DA4 — see §5.6)
├── DocConsistencyError
│   ├── DocConsistencyAllowlistError
│   └── DocConsistencyTargetMissingError
└── ArcisConfigError (inherited from #104)

subprocess.SubprocessError
├── NssmMissingError       (existing #104)
├── GhMissingError         (existing #104)
├── GitMissingError        (NEW #107)
└── NvidiaSmiMissingError  (NEW #107)
```

### 8.2 Error → CLI envelope mapping

Every error class above has a meaningful `__name__`. `_cli_envelope.run_cli` surfaces it verbatim:

```json
{"error": {"type": "BaselineNotFoundError", "message": "no latest_ref.txt for contract 'nvidia-smi-watchloop'", "tool": "contractcheck"}}
```

The `sanitize_error` pass (defense-in-depth from `_cli_envelope` L52) redacts any DSN passwords / bearer tokens in error messages — no Tier 3 error currently includes such secrets, but the pass runs unconditionally.

### 8.3 Non-error "findings" (DRIFT verdict, dead refs)

DRIFT in ContractCheck is NOT an exception. `verify()` returns a dict with `verdict='DRIFT'` and a non-empty list of mismatched fields. CLI exit code is still 0 (success) — the *information* is in the output, not the exit code. **Operators wire DRIFT-to-alert in their own glue scripts; ContractCheck is a reporter, not a gate.**

Same for DocConsistency: `findings` is a list. If empty, scan was clean. If non-empty, the operator triages. CLI exit 0 regardless.

**Future hook for #111:** the periodic skill-audit may wrap these tools with `if verdict == 'DRIFT' or findings: open_issue()` glue. That's #111's design, not #107's.

---

## 9. Testing Strategy

### 9.1 Test infrastructure inherited

- `tests/tools/` is the existing target directory (deep report confirmed: every Tier 1+2 tool has `tests/tools/test_<name>_integration.py`).
- Naming convention: `tests/tools/test_<toolname>_integration.py` (verified by grep: `test_dbquery_integration.py`, `test_logtail_integration.py`, `test_capabilityregistry_integration.py`, etc.). Tier 3 follows this convention.
- `tests/conftest.py` exists (operator memory `reference_living_attack_plan` and prior #96 work) and provides standard fixtures.
- pytest discovers via the existing `pytest.ini` / `pyproject.toml` configuration.

### 9.2 Test files (3 new)

#### `tests/tools/test_contractcheck_integration.py` (Task T6)

Covers:

- **`test_record_writes_baseline`** — happy path: mock `_subprocess.run` returning known stdout, call `record('nvidia-smi-watchloop')`, assert the JSON file exists with correct schema, assert `latest_ref.txt` contains the filename.
- **`test_record_atomic_write`** — verify temp file + os.replace pattern (no partial files left on disk if write is interrupted). Use a context manager that raises mid-write.
- **`test_record_overwrites_latest_ref_safely`** — second `record()` call atomically updates `latest_ref.txt` (read returns old value, then new value — never an empty string).
- **`test_verify_pass`** — given a known baseline + a mocked live invocation matching within tolerance, `verify` returns `verdict='PASS'`, all fields `status='match'` or `'tolerance'`.
- **`test_verify_drift_value_mismatch`** — live value exceeds tolerance, `verdict='DRIFT'`, that field `status='mismatch'`.
- **`test_verify_na_north_star`** — **THE VERIFY-BY-MUTATION NORTH-STAR.** Baseline records 5 floats. Live stdout returns `'42, 4096, [N/A], 58, 175.30'`. Assert `fields.gpu_vram_total_mb.status == 'shape_change'`, `verdict='DRIFT'`. This test PROVES ContractCheck would have caught the v0.36.29 regression at the watchloop's argv shape. **The test must fail if `verify` returns `PASS` — anti-vacuous-test discipline (operator memory `feedback_vacuous_test_pattern`) applied.**
- **`test_verify_invocation_failed`** — subprocess timeout, `verdict='INVOCATION_FAILED'`, no field diff.
- **`test_baseline_not_found`** — fresh contract with no latest_ref → `BaselineNotFoundError`.
- **`test_contract_not_configured`** — name not in arcis_config.yaml → `ContractNotConfiguredError`.
- **`test_baseline_corrupt`** — manually truncate a baseline JSON, verify call → `BaselineCorruptError`.
- **`test_diff_subcommand`** — diff two pre-existing baselines, return same shape as verify but with `baseline_a` / `baseline_b` keys.
- **`test_cli_envelope_record`** — subprocess case: `python -m src.tools.contractcheck record nvidia-smi-watchloop --json` with mocked nvidia-smi → JSON success output, exit 0.
- **`test_cli_envelope_error_json`** — subprocess case: `python -m src.tools.contractcheck verify nonexistent --json` → JSON envelope `{"error": {"type": "ContractNotConfiguredError", ...}}`, exit 1.

Coverage target: ≥95% line coverage on `src/tools/contractcheck/core.py`.

#### `tests/tools/test_gitarchaeology_integration.py` (Task T7)

Covers:

- **`test_log_basic`** — mock `_subprocess.run` returning a 3-commit `git log` output, call `log()`, assert 3 dicts with correct keys.
- **`test_log_path_filter`** — verify `-- <path>` is appended to the argv when `path=` is passed.
- **`test_log_range`** — verify `<range>` is appended.
- **`test_log_limit`** — verify `-n <limit>` is appended; default 50.
- **`test_blame_full_file`** — no start/end → no `-L` flag; expect full-file blame.
- **`test_blame_range`** — start_line=10, end_line=20 → `-L 10,20` in argv.
- **`test_blame_invalid_range`** — start > end → `GitArgError`.
- **`test_show`** — mock returns subject + body + diff; parser separates correctly.
- **`test_diff`** — two refs; verify `<ref_a>..<ref_b>` form.
- **`test_rev_list`** — list of SHAs.
- **`test_merge_base`** — single SHA returned.
- **`test_tag_l`** — list of tags.
- **`test_git_missing`** — `shutil.which('git')` returns None → `GitMissingError` with install hint.
- **`test_git_invocation_error`** — subprocess returns non-zero with stderr; assert `GitInvocationError` includes the stderr text.
- **`test_dubious_ownership_hint`** — stderr contains `'fatal: detected dubious ownership'`; assert remediation hint appears in the raised error message.
- **`test_forbidden_op_argparse_rejected`** — invoke `python -m src.tools.gitarchaeology commit` via subprocess; assert argparse exit code 2 (argparse usage error), assert stderr says `invalid choice: 'commit'`. **This proves the FORBIDDEN list is structurally enforced, not just documented.**
- **`test_cli_envelope_json_log`** — `python -m src.tools.gitarchaeology log --limit 3 --json` returns valid JSON.

Coverage target: ≥95% on `gitarchaeology/core.py`.

#### `tests/tools/test_docconsistency_integration.py` (Task T7)

Covers:

- **`test_scan_finds_existing_refs_ok`** — fixture markdown with `` `src/tools/_config.py:50` ``; assert `findings=[]` (the file exists and has ≥50 lines).
- **`test_scan_file_missing`** — fixture md with `` `src/nonexistent.py:1` ``; assert one finding with `severity='file_missing'`.
- **`test_scan_line_missing`** — fixture md with `` `src/tools/_config.py:99999` ``; assert one finding with `severity='line_missing'`.
- **`test_scan_range_uses_start_line`** — fixture md with `` `src/tools/_config.py:50-60` ``; assert only line 50 is checked (start). If start exists, no finding.
- **`test_scan_allowlist_suppresses`** — fixture md has a missing-file ref; allowlist YAML lists that ref; assert `refs_allowlisted=1`, `findings=[]`.
- **`test_scan_allowlist_missing_file_is_empty`** — allowlist YAML file doesn't exist on disk; scan completes with implicit empty allowlist.
- **`test_scan_allowlist_malformed`** — invalid YAML; assert `DocConsistencyAllowlistError`.
- **`test_scan_pattern_a_backtick`** — Pattern A (single line with backticks) detected.
- **`test_scan_pattern_b_range`** — Pattern B (line range with backticks) detected.
- **`test_scan_pattern_c_ignored`** — Pattern C (comma-list, no backticks, e.g., `vram_manager.py:266,340`) is NOT detected in v1. This test PROVES the v2 deferral is explicit.
- **`test_scan_default_targets_includes_changelog`** — default scan includes `CHANGELOG.md` regardless of age filter.
- **`test_scan_default_targets_includes_docs_standards`** — default scan picks up the existing `docs/standards/boundary-touch-tests.md` (verified to exist at design time).
- **`test_scan_default_targets_age_filters_docs_audits`** — fixture audit dir; mock `os.path.getmtime` to return >90-day-old timestamp; assert that file is excluded from scan.
- **`test_scan_explicit_target_overrides_age_filter`** — `--target docs/old.md`; even if old.md is >90 days, scan includes it because explicit.
- **`test_scan_target_missing`** — explicit `--target` to nonexistent file → `DocConsistencyTargetMissingError`.
- **`test_scan_changelog_md_real_run`** — runs scan against the actual repo `CHANGELOG.md` (no mocking); assert it returns *some* findings (since the deep report confirmed 483 refs, several pointing to deleted files). This is an **integration smoke**, not a content assertion — flake-resistant because the test does NOT assert specific findings, only `refs_found > 100`.
- **`test_cli_envelope_json`** — subprocess invocation returns valid JSON.

Coverage target: ≥95% on `docconsistency/core.py`.

### 9.3 Test discipline standards (operator memory `feedback_vacuous_test_pattern`)

Every test must satisfy the **anti-vacuous-test gate**: before commit, the operator (or QA reviewer) confirms that mutating the production code to be intentionally wrong causes the test to fail. The verify-by-mutation north-star test (`test_verify_na_north_star`) is the highest-value example — if a developer accidentally implemented `verify()` to always return `verdict='PASS'`, this test must fail. The dual-Opus QA gate (per operator memory `feedback_use_coding_team_skill`) verifies this for every Tier 3 test before merge.

### 9.4 Coverage gates

- Per-module: ≥95% line coverage.
- Per-tool (aggregate): ≥95%.
- No skipped tests (`pytest.skip` calls), no `@pytest.mark.xfail` without an open follow-up tracked.
- Subprocess-case tests (calling `python -m src.tools.<tool>` via subprocess.run in pytest) included for each tool, per the existing #105/#106 pattern.

---

## 10. Cross-Cutting Standards Summary

| Standard | Source | Tier 3 application |
|----------|--------|--------------------|
| Foundation primitives (5) | #104 + #105 | All three tools inherit unchanged. Two new error classes appended to `_subprocess.py`. |
| 5-section module docstrings | Tier 1+2 convention | Every new `.py` module gets the operator-readable header. |
| `encoding='utf-8'` explicit | `feedback_windows_utf8_encoding` | Every Path read/write call passes it. |
| `subprocess.run` ONLY via `_subprocess.run` | #104 | Every Tier 3 subprocess invocation goes through the wrapper. ContractCheck uses it for its own nvidia-smi calls; the *contract* it pins is a direct-subprocess site in production code, which is intentional (the production code's argv is the thing being pinned). |
| Bind `127.0.0.1`, ports 8765+ | `reference_local_ports` | N/A — no HTTP servers. |
| `@safe_op(name="<tool>", mutates=False)` decorator | `src/tools/_safety.py:167-172` | Every public Tier 3 entry-point function is decorated with `@safe_op(name="contractcheck"|"gitarchaeology"|"docconsistency", mutates=False)`. The decorator signature has TWO required kwargs: `name` (string) and `mutates` (bool). NO `write=`, `tool=`, or `op=` kwargs — those do not exist on the decorator. Verified call sites: src/tools/dbquery/core.py:162, src/tools/capabilityregistry/core.py:45,51, src/tools/symbolfind/core.py:153. |
| Typed errors (no raw RuntimeError/ValueError) | `_cli_envelope` design | Every Tier 3 error has a semantic class name. |
| Atomic file writes (tempfile + fsync + os.replace) | CHANGELOG.md:107 documented the ci-investigate cache convention | ContractCheck baseline writes inherit the atomic-write idiom from `src/tools/ciinvestigate/core.py:64`ff. (Note: the `data/cache/ci-investigate/` directory itself is runtime-created and gitignored — it does not exist on disk in a fresh clone. The precedent is documentary, codified in CHANGELOG.md:107, and the reusable idiom is the function in ciinvestigate/core.py.) |
| Anti-vacuous-test | `feedback_vacuous_test_pattern` | Every test mutate-verified; verify-by-mutation north-star formalizes this. |
| Sibling-search rule | `feedback_review_sibling_search` | After implementing ContractCheck's nvidia-smi path, grep all 4 nvidia-smi sites (deep report Area 17) and confirm none introduces new latent gaps. |
| Dual-Opus QA on impl | `feedback_use_coding_team_skill` | Implementation goes through arcis:code with 2-independent-Opus-QA merge gate. |
| No skipped tests / no weakened assertions | `feedback_strict_rigor_no_handwave` | T6/T7 acceptance gates enforce. |

---

## 11. Design Decisions Summary

### 11.1 Decision table

| ID | Decision | Source | Rationale |
|----|----------|--------|-----------|
| DD-1 | ContractCheck v1 contract = `system_metrics.py:36-56` watchloop invocation | Operator BRIEF | Highest blast-radius drift surface: watchloop runs every 5 scans; silent drift here masks the v0.36.29-class regression. |
| DD-2 | Baselines committed to git via `!data/contracts/` allowlist | Operator BRIEF + `data/reference/` precedent | Audit trail; baselines are *contracts*, not caches. |
| DD-3 | Pointer file `latest_ref.txt`, NOT symlink | Windows-first env + zero existing symlinks in src/ | Windows symlinks require admin / developer mode; pointer file is portable. |
| DD-4 | ContractCheck normalization grammar = per-field `tolerance` + `mask_regex` + `ignore` + `at_capture_redact` (4 knobs after DA2) | Required by per-field drift semantics + DA2 recording-time PII safety | gpu_util drifts second-to-second (needs calibrated tolerance — see DD-16); gpu_vram_total is constant (no tolerance — catches hardware swap); future contracts may emit PII (at_capture_redact). |
| DD-5 | GitArchaeology surface = 7 ops (log/blame/show/diff/rev-list/merge-base/tag-l) | Operator BRIEF | Operator confirmed 7 at interview despite agent-spec listing 9; honor operator. |
| DD-6 | DocConsistency v1 = class (a) ONLY; (b)+(c)+(d) deferred | Operator BRIEF | Minimal viable v1; AST-based checks add complexity without v1 value. |
| DD-7 | All three tools read-only — `@safe_op(..., mutates=False)` everywhere | Tier 3 meta-quality charter | Tools surface findings; operators triage. Mutation surface is zero. |
| DD-8 | ContractCheck v1 is a FORENSIC tool (operator-invoked, not runtime-instrumented); verify-by-mutation test proves verify-LOGIC in ISOLATION, not runtime-watchloop integration | Deep report Area 2 + DA5 framing | Original v0.36.29 fixture is DELETED; reusing it impossible. Verify-by-mutation re-creates the regression class in a clean isolated test. Honest framing: v1 catches drift when operator runs verify (or when #111 wires scheduled cadence); v1 does NOT instrument the watchloop. #117 closes the runtime-swallow gap independently. |
| DD-9 | Latent bug at `system_metrics.py:36-56` (no [N/A] defense) → filed as task #117, NOT bundled into #107 | Operator memory `feedback_complete_efforts_no_deferral` (at-boundary interpretation) | #107's scope is build-the-tools, not fix-everything-found. #117 is separate effort, separate PR, tracked. |
| DD-10 | Foundation extension via pydantic `ContractsConfig` + `ContractDef` + `NormalizeRule` | #100/#104 PathsConfig precedent | Backward compat via `Field(default_factory=dict)`. |
| DD-11 | `data/contracts/<name>/<timestamp>.json` + `latest_ref.txt` layout (atomic-write idiom from ci-investigate convention) — with recording-time output sanitization via `at_capture_redact` (DA2) ensuring committed baselines NEVER contain operator-PII | CHANGELOG.md:107 documented convention + `src/tools/ciinvestigate/core.py:64` atomic-write helper + DA2 PII safety | Mirrors the documented convention but commits to git (cache is local; contracts are shared). DA2 ensures committed baselines are safe to share publicly — recording-time sanitization is irreversible (operator inspects → regex-redacts → records → commits). v1 nvidia-smi-watchloop contract emits pure numerics so default redact list is empty, but the framework is in place for future contracts that emit paths/usernames. |
| DD-12 | DocConsistency default scope EXCLUDES old `docs/audits/` entries (>90 days) | Deep report Area 10 — 5000-8000 refs total | First-run signal-to-noise; operator triages via allowlist for the rest. |
| DD-13 | `data/docconsistency-allowlist.yaml` empty seed; operator curates by adding entries from real findings | Operator memory `feedback_ask_user_question_for_decisions` | Don't pre-curate — let real findings drive the allowlist. |
| DD-14 | Bundle all three tools in ONE PR (not three) | Operator BRIEF | Shared foundation extension makes the merge atomic; three PRs would race on `_config.py` / `.gitignore`. |
| DD-15 | Initial baseline (`data/contracts/nvidia-smi-watchloop/<timestamp>.json` + `latest_ref.txt`) committed in this PR via Task T5 | `feedback_complete_efforts_no_deferral` | A tool without an initial baseline is half-built. T5 closes the gap within the effort. |
| **DD-16 (DA1)** | ContractCheck v1 tolerances RECALIBRATED to detect BOTH value drift AND shape drift: `gpu_util_pct: 5.0`, `gpu_vram_used_mb: 2048.0`, `gpu_temp_c: 10.0`, `gpu_power_w: 50.0` (NOT the prior wide 100/24576/50/400 calibration) | DA1 adversarial review | Earlier wide calibration silently reduced ContractCheck to shape-only drift detection. v1 design intent is value+shape detection. Recalibrated values reflect operator-observed RTX 3090 steady-state ranges at idle workloads. Reversibility: config YAML — operator widens via edit + re-record if production reveals noise. Downstream: first-week verify runs may produce DRIFT events on benign value swings; operator triages → widens or accepts. |
| **DD-17 (DA2)** | Output sanitization at RECORDING time via `at_capture_redact` regex list on each `NormalizeRule` — replaces PII spans with `<REDACTED>` in committed baseline JSON | DA2 adversarial review | Committed baselines are permanent, public-readable repo artifacts. Future contracts (e.g., `--query-compute-apps` v2 follow-up) will emit `C:\Users\mille\...` paths. Recording-time redaction is the safety gate — the raw un-redacted output NEVER touches disk. v1 nvidia-smi-watchloop default: empty redact list (CSV numerics — no PII). Framework in place + audit checklist in §3.2 + §4.4a. |
| **DD-18 (DA3)** | GitArchaeology `log` output parsing contract uses `str.split('\t', N-1)` with explicit maxsplit + paired `format=`/`format_columns=` kwargs + subject-LAST constraint + raises `GitParseError` on malformed output | DA3 adversarial review | Without maxsplit, commits with embedded tabs in subjects (or custom format= calls with mismatched column counts) silently corrupt parser output — drop fields, shift columns, or fabricate fake values. Explicit maxsplit + kwarg pair + structured error means malformed output is LOUD, not silent. 5-rule contract documented in §5.3.1 + verified by 4 T7 tests. |
| **DD-19 (DA4)** | GitArchaeology output size governance via per-op `max_output_bytes` defaults (blame=2MB, show/diff=10MB, log=limit*200, etc.) + pre-invocation gate for blame on >5000-line files + `GitOutputTruncatedError` with structured `partial_output` + `original_size_bytes` fields + `--max-output-bytes N` CLI flag | DA4 adversarial review | Read-only git ops can produce arbitrary output (refactor commits, generated files). Without governance, GitArchaeology can consume agent memory and corrupt automation with silently-truncated output. Structured truncation error lets callers decide: retry-with-higher-cap, accept-partial, or fail-clean. Operator override always available. Defense-in-depth: limit/-n flag + max_output_bytes backstop + pre-invocation file-size check. |

### 11.2 Alternatives considered & rejected

- **ContractCheck v1 contract = `trainer.py:1105` (dual-GPU preflight)** — rejected: trainer is one-shot at training start, lower blast radius than watchloop's every-5-scan invocation. (System metrics is higher signal.)
- **DocConsistency v1 includes class (d) symbol existence** — rejected: requires AST machinery; operator confirmed v1 = (a) only.
- **GitArchaeology surface = 9 ops (add rev-parse + remote -v)** — rejected at interview: operator confirmed 7. rev-parse + remote -v are §11.4 follow-ups.
- **`data/contracts/` use symlinks for `latest`** — rejected: Windows + admin requirement; deep report Area 14 confirmed zero existing symlink patterns.
- **Baseline filename = SHA of contents** — rejected: hashes are stable but lose temporal information; `<ISO-timestamp>.json` lets the operator browse history chronologically.
- **Three separate PRs for the three tools** — rejected: shared foundation extension creates merge conflicts; one PR is simpler.
- **ContractCheck records only on operator request** — accepted as default; auto-recording on `verify` failure was considered and rejected (silently auto-updating the baseline defeats the purpose — drift would never be visible to the operator).
- **`contracts:` in a separate `config/contracts.yaml`** — rejected: operator BRIEF specifies arcis_config.yaml extension.

### 11.3 DocConsistency v2 / Tier 4 follow-up (deferred)

Not in #107. Possible later effort:

- Class (b) — API signature drift detection. Requires AST parsing of source + matching against docstring claims.
- Class (c) — docstring-vs-code drift (module headers reference functions that don't exist).
- Class (d) — symbol existence (`from src.foo import bar` claims with `bar` actually defined).
- Pattern C — comma-list refs (`file.py:266,340`).
- Context-mismatch severity — line N exists but surrounding doc context describes function `foo` while line N is inside `bar`.
- Integration with SymbolFind (Tier 1) for moved-symbol detection.

### 11.4 GitArchaeology v2 / Tier 4 follow-up (deferred)

- `rev-parse` op (covers `git rev-parse HEAD`, `git rev-parse --abbrev-ref HEAD`). Used by 4 existing direct-git sites in src/ (deep report Area 6).
- `remote -v` op. Used once in git-historian spec; low value.
- `config user.email` op. Used by `scripts/preflight_monday.py:319` (deep report Area 7).
- Full-displacement refactor of the 4 direct-git sites in `src/` and 4 in `scripts/` (deep report Areas 6+7). v1 only satisfies the git-historian agent contract; broader displacement is a follow-up effort.

### 11.5 ContractCheck v2 / Tier 4 follow-up (deferred)

- Pin the other 3 nvidia-smi sites (deep report Area 17): `trainer.py:1105`, `telegram_commands.py:678`, `telegram_commands.py:755`. Each has a different argv shape and timeout.
- Add `git --version` and `python --version` as v2 contracts to catch toolchain drift.
- Add `nvidia-smi --query-compute-apps=pid,process_name,used_memory` (the original v0.36.29 contract) once a viable caller exists post-vram_manager-deletion. **DA2 implication:** this contract WILL surface absolute paths (`C:\Users\mille\AppData\Local\Programs\Ollama\ollama.exe`); the pre-record audit checklist (§4.4a) MUST add `at_capture_redact` patterns for paths-containing-username before recording.
- **Wire `ContractCheck.verify()` into a periodic process (DA5)** — cron, #111 skill-audit periodic cadence, or watchloop startup probe. v1 is operator-invoked only; the FORENSIC framing in §1.1 / §4.7 is honest about this gap. Periodic invocation closes the loop from "operator suspects drift → runs verify" to "system detects drift → alerts operator." Estimated complexity: low (just glue from cron/audit → existing verify() API).
- **Critical pre-requisite for ContractCheck CI-gate elevation:** task #117 must close — once `system_metrics.py:36-56` has a proper `[N/A]` defense, the watchloop's swallow-N/A behavior is auditable, and ContractCheck can become a deploy gate. Until then, ContractCheck is operator-triage-only.

---

## 12. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| `nvidia-smi` returns drifted values on T5 baseline recording (e.g., `[N/A]` for `power.draw` on operator's machine) | Medium | Low | Baseline records the literal output; operator commits whatever was live. If the value drifted at record time, that's the operator's state — re-record once #117 lands. |
| DocConsistency first-run flags 1000+ findings, overwhelming operator | High | Medium | Default-scope age filter (90 days for docs/audits/) + allowlist mechanism + CHANGELOG always full-scope. Operator triages incrementally. |
| GitArchaeology timeout too low for large repo history queries | Medium | Low | Per-op timeout overrides exposed in API + CLI. Defaults are conservative (30s log, 60s blame) and tunable per-call. |
| Foundation extension breaks existing tools | Low | Critical | `Field(default_factory=dict)` ensures backward compat; existing `arcis_config.yaml` files without `contracts:` still load. T1's acceptance check runs the existing Tier 1+2 tool test suite — must pass before T2-T4 start. |
| `.gitignore` allowlist append breaks existing data/ behavior (e.g., accidentally re-includes `data/halcyon.db`) | Low | Critical | T1's verification: `git check-ignore --verbose data/halcyon.db` must still return ignored. T1's acceptance gate. |
| `latest_ref.txt` race condition (two ContractCheck processes recording simultaneously) | Very Low | Low | Atomic write via tempfile + os.replace; concurrent recordings produce two valid timestamped baselines; only one wins the latest_ref. Operator never runs concurrent recordings (no automation invokes record without explicit operator action). |
| Operator merges #107 before #117 → ContractCheck baseline includes broken-defense state | Certain | Low (BY DESIGN) | This is expected and acknowledged. The first baseline is a snapshot of CURRENT state, including the latent gap. After #117 closes, operator re-records; the new baseline supersedes. |
| GitArchaeology FORBIDDEN list bypass | Very Low | Critical | Structural enforcement — no argparse subcommand for forbidden ops; `test_forbidden_op_argparse_rejected` regression-locks this. |
| DocConsistency allowlist gets too long, becoming an unaudited dumping ground | Medium (long-term) | Low | YAML is git-tracked; allowlist additions land in PRs and are reviewable. #111 periodic skill-audit can flag entries older than 6 months as stale. |
| Wrong `@safe_op` kwargs (e.g., `write=` instead of `mutates=`) → import-time TypeError on every Tier 3 module | Very Low | Critical | T2/T3/T4 each must use the verified signature `@safe_op(name="<tool>", mutates=False)`. The pattern is repeatedly demonstrated in Tier 1+2 source — feasibility reviewer flagged in R0 and corrected in R1. |

---

## 13. Implementation Sequencing (high-level — full plan below)

Tier 3 has one foundation-extension task that must land before the three tool subpackages, then three parallel-safe tool tasks, then sequential test + baseline-record + documentation tasks. The detailed task graph is in the `plan` field.

---

## 14. References

- Operator BRIEF for #107 (in DYNAMIC CONTEXT above).
- Deep report Phase 4 (operator-provided JSON file, areas 1-17).
- Tier 1 plan (#105) — sets the `__main__.py` + `_cli_envelope.run_cli` pattern.
- Tier 2 plan (#106) — extends with `_safety.@safe_op` audit logging.
- `src/tools/_safety.py:167-172` — authoritative `safe_op` signature definition.
- `src/tools/dbquery/core.py:162` + `src/tools/capabilityregistry/core.py:45,51` + `src/tools/symbolfind/core.py:153` — exemplar `@safe_op(name="<tool>", mutates=False)` call sites.
- `docs/audits/2026-05-25-specialized-agents/specs/2026-05-25-specialized-agents-design.md` DD-10 — git-historian → GitArchaeology refactor target.
- CHANGELOG.md v0.36.29 entry (L1234-1310) — the verify-by-mutation north-star.
- CHANGELOG.md:107 — documented (not on-disk) atomic-write convention for tool caches.
- `src/tools/ciinvestigate/core.py:64`ff — the reusable atomic-write idiom (tempfile + fsync + os.replace).
- Operator memory entries cited throughout (utf8 encoding, complete-efforts, strict-rigor, vacuous-test, sibling-search, use-coding-team-skill, ask-user-question, windows-symlinks, etc.).
- Task #117 (filed; pending) — Restore [N/A] defense in system_metrics.py nvidia-smi parser.

---

## 15. Revision History

- **R0 (initial design):** complete spec + plan + decisions delivered to feasibility review.
- **R2 (DA-revision pass — 5 adversarial findings addressed):**
  - **DA1 (critical):** tolerance recalibration in §3.2 — value+shape drift detection (not shape-only). DD-16 added. §1.1 + §4.5 + §4.7 cross-referenced. Recalibrated to `gpu_util:5.0 / vram_used:2048 / temp:10 / power:50`.
  - **DA2 (critical):** output sanitization at recording time. NormalizeRule extended with `at_capture_redact: list[str]` field. §4.4a added. §3.2 audit checklist rewritten. DD-17 added. T6 test `test_record_redacts_at_capture_when_configured` added.
  - **DA3 (major):** GitArchaeology log parsing contract — 5-rule §5.3.1 added with maxsplit + format_columns kwarg + UTF-8 + subject-LAST + GitParseError. §5.1 surface mentions format/format_columns. §5.6 + §8.1 add GitParseError. DD-18 added. T7 tests added: `test_log_subject_with_embedded_tab`, `test_log_custom_format_requires_columns`, `test_log_custom_format_with_columns`, `test_log_parse_failure_raises`.
  - **DA4 (major):** GitArchaeology output size governance. §5.4a added with per-op `max_output_bytes` defaults + pre-invocation gate for blame + structured `GitOutputTruncatedError`. §5.6 + §8.1 add `GitOutputTruncatedError`. `--max-output-bytes N` CLI flag added to §5.4. DD-19 added. T7 tests added: `test_blame_large_file_requires_range`, `test_blame_large_file_truncates_cleanly`, `test_show_respects_max_output_bytes`, `test_show_default_max_output_bytes`, `test_cli_max_output_bytes_flag`.
  - **DA5 (major):** Forensic-tool framing. §1.1 ContractCheck bullet rewritten. §4.7 rewritten with honest framing (what verify-by-mutation proves vs doesn't). DD-8 reframed. §11.5 deferral entry added for wiring verify() into periodic process. DD-4, DD-11 cross-referenced.
- **R1 (initial revision):** feasibility-review fixes applied:
  - FB1 (major): replaced erroneous `@safe_op(write=False)` with verified-correct `@safe_op(name="<tool>", mutates=False)` throughout §2.1, §3.1 (note: §3.1 is the pydantic models, not safe_op — clarified in spec), §4.1, §5.3, §6.2 task descriptions, §10 cross-cutting standards table, plan.json T2/T3/T4 descriptions. Dropped non-existent `tool=` / `op=` kwargs.
  - FB2 (minor): rephrased `data/cache/ci-investigate/` references as `CHANGELOG.md:107 documented convention` rather than `on-disk precedent`. Clarified that the atomic-write idiom is inheritable from `src/tools/ciinvestigate/core.py:64`ff.
  - FB3 (minor): renamed test files to `_integration.py` suffix matching Tier 1+2 convention. Updated §7.1, §9.2 headers, plan.json T6/T7 files_in_scope.
  - FB4 (minor): verified `docs/standards/` exists (contains `boundary-touch-tests.md`); kept default-scope inclusion. Added explicit acknowledgement of current contents and graceful-empty handling.
  - FB5 (nit): rephrased §2.1 opening to remove no-modifications/yes-modifications contradiction; now phrased as `inherit unchanged in semantics; the deltas below are additive...`.

---

## Design Decisions Log

(All decisions are also recorded as full entries in `design_decisions.json` alongside this spec.)

| # | Decision | Rationale (short) | Reversibility |
|---|----------|-------------------|---------------|
| ContractCheck v1 contract = `src/monitoring/system_metrics.py | ContractCheck v1 contract = `src/monitoring/system_metrics.py:36-56` watchloop nvidia-smi in... | Highest blast-radius drift surface in the repo. The watchloop invokes this every 5 scans; silent drift here masks regressions of the v0.36.29 [N/A] class. Other nvidia... | ? |
| ? | Baselines committed to git via 2-line `.gitignore` allowlist (`!data/contracts/` + `!data/co... | Audit trail; matches the existing `data/reference/` precedent at .gitignore L41-42 verbatim. Baselines are *contracts* (operator-curated, reviewable, blamable) — they ... | ? |
| ? | Pointer file `latest_ref.txt` (plain ASCII), NOT symlink | Operator's Windows-first environment; deep report Area 14 confirmed zero existing os.symlink / Path.symlink_to usage in src/. Windows symlinks require admin or develop... | ? |
| ? | ContractCheck normalization grammar = per-field `tolerance` + `mask_regex` + `ignore` + `at_... | Different fields drift differently and have different PII risk profiles. tolerance + ignore + mask_regex cover comparison-time normalization (when comparing baseline v... | ? |
| ? | GitArchaeology surface = 7 read-only ops (log, blame, show, diff, rev-list, merge-base, tag-l) | Operator confirmed 7 at interview, overriding the apparent 9-op surface in the git-historian agent spec. The two divergent ops (rev-parse, remote -v) are filed as §11.... | ? |
| DocConsistency v1 = class (a) ONLY (dead file | DocConsistency v1 = class (a) ONLY (dead file:line refs); (b), (c), (d) deferred | v1 minimal viable. Class (a) is line-count check (no AST needed). Class (d) requires AST + find_spec discipline (the src/tools/testpatternscan/rules.py pattern); addin... | ? |
| ? | All three tools read-only — `@safe_op(name="<tool>", mutates=False)` everywhere, NO `mutates... | Tier 3's meta-quality charter: surface findings, don't mutate state. ContractCheck writes to data/contracts/ which is operator-state (auditable, reviewable in git), no... | ? |
| ? | ContractCheck v1 is a FORENSIC tool (operator-invoked, not runtime-instrumented); verify-by-... | Honest framing (DA5 adversarial review). What v1 PROVES: the verify-LOGIC correctly detects shape_change (e.g., [N/A] sentinel) AND value-drift mismatch (DA1-calibrate... | ? |
| Latent bug at `src/monitoring/system_metrics.py | Latent bug at `src/monitoring/system_metrics.py:36-56` (no `[N/A]` defense at the call site)... | Operator's no-out-of-scope-deferral discipline (feedback_complete_efforts_no_deferral) applied at the EFFORT BOUNDARY, not at the 'fix everything you find' interpretat... | ? |
| ? | Foundation extension via pydantic `ContractsConfig` + `ContractDef` + `NormalizeRule` (neste... | Matches the existing PathsConfig (L50-58) / PortsConfig (L68-76) / SafetyWindow (L87-106) precedent at src/tools/_config.py. Backward compat via `Field(default_factory... | ? |
| ? | `data/contracts/<name>/<timestamp>.json` + `latest_ref.txt` layout (atomic-write idiom from ... | Per CHANGELOG.md:107+119, the v0.36.62 ci-investigate cache convention is `data/cache/<tool-name>/<id>.json` with atomic write discipline (tempfile + fsync + os.replac... | ? |
| ? | Bundle three tools in ONE PR (not three), with one shared foundation extension task (T1) | Operator BRIEF specifies bundling. Operationally: the three tools share `_config.py` and `_subprocess.py` extensions — three separate PRs would race-merge on those fil... | ? |
| ? | DocConsistency default scope EXCLUDES old `docs/audits/` entries (>90 days) | Deep report Area 10 — 5000-8000 refs total across audit subdirs. First-run signal-to-noise; operator triages via allowlist for the rest. Age filter uses os.path.getmti... | ? |
| ? | `data/docconsistency-allowlist.yaml` empty seed; operator curates by adding entries from rea... | Operator memory `feedback_ask_user_question_for_decisions` — don't pre-curate. Let real findings drive the allowlist. The deep-report Phase 4 analysis identified that ... | ? |
| ? | Initial baseline (`data/contracts/nvidia-smi-watchloop/<timestamp>.json` + `latest_ref.txt`)... | `feedback_complete_efforts_no_deferral` discipline. A tool without an initial baseline is half-built. T5 closes the gap within the effort. If nvidia-smi unavailable on... | ? |
| DD-16 (DA1) | DD-16 (DA1): ContractCheck v1 tolerances RECALIBRATED to detect BOTH value drift AND shape d... | Earlier wide calibration (gpu_util:100, vram_used:24576, temp:50, power:400) silently reduced ContractCheck to shape-only drift detection — a useful subset but strictl... | ? |
| DD-17 (DA2) | DD-17 (DA2): Output sanitization at RECORDING time via `at_capture_redact` regex list on eac... | Committed baselines are permanent, public-readable repo artifacts. Future contracts (e.g., `--query-compute-apps` v2 follow-up) will emit `C:\Users\mille\AppData\Local... | ? |
| DD-18 (DA3) | DD-18 (DA3): GitArchaeology `log` output parsing contract uses `str.split('\t', N-1)` with e... | Without maxsplit, commits with embedded tabs in subjects (or custom format= calls with mismatched column counts) silently corrupt parser output — drop fields, shift co... | ? |
| DD-19 (DA4) | DD-19 (DA4): GitArchaeology output size governance via per-op `max_output_bytes` defaults + ... | Read-only git ops can produce arbitrary output: `git log --all` on a large repo, `git show` on a refactor-mega-commit, `git blame` on a 50k-line generated file. Withou... | ? |


---

## Known Considerations (devils-advocate minor + nit findings, not blocking)

Surfaced during adversarial review (R2); deemed below the threshold for spec revision. Documented for implementing PM + post-merge consideration.

| # | Concern | Note |
|---|---------|------|
| KC1 | DocConsistency first-run UX is harsh — empty allowlist + 200+ refs in CHANGELOG.md = wall of findings | Recommend `--suggest-allowlist <doc_filter>` helper flag + smart auto-classification for refs to deleted files. Defer to v2 of DocConsistency; v1 ships with operator manually triaging via allowlist. |
| KC2 | No baseline retention/pruning policy in ContractCheck — over years across drivers + hardware swaps, `data/contracts/<name>/` accumulates indefinitely | Add `python -m src.tools.contractcheck prune <name>` subcommand in v2 with `retention_keep_last: int = 10` per-contract config. v1 ships without automated prune; operator handles manually. |
| KC3 | Allowlist staleness — DocConsistency allowlist entries become obsolete when underlying file is fixed | Add `--report-stale-allowlist-entries` flag in v2 that lists allowlist entries which did NOT match findings in this scan. Trivial future addition. |
| KC4 | GitArchaeology behavior undefined for non-quiescent repo states (mid-rebase, mid-bisect, detached HEAD, shallow clone) | Document as 'assumes quiescent repo' in §5.5a. Optional: add `_assert_quiescent(repo)` helper raising GitRepoStateError if `.git/rebase-merge`, `.git/BISECT_LOG`, or `.git/MERGE_HEAD` exists. Defer to v2. |
| KC5 | DocConsistency v1 content-reading exposes file contents in context-grep verification (not in v1 output, but v2 'context-mismatch severity' will introduce secret-leakage risk) | v1 is safe (only line-count check). v2 must apply `_secrets.detect_secret_in_text` to any content read for context comparison. |
| KC6 | ContractCheck timestamp format precision mismatch — filename = 1-second resolution, content `recorded_at` = microsecond | On filename collision (two records in same wall-clock second), atomic-rename silently overwrites first. Mitigation: extend filename to milliseconds OR document as 'space recordings >1 second apart'. v1 documents; v2 extends format. |
| KC7 | `latest_ref.txt` pointing to a deleted/empty/corrupted file | Spec §4.6 covers `BaselineNotFoundError` + `BaselineCorruptError`. Empty-file case not explicitly handled — would manifest as `BaselineNotFoundError`. Worth a test case but not blocking. |
| KC8 (nit) | Spec self-references file:line refs that are at risk of rot | Recommend symbolic references in prose. Ironic: the spec creating DocConsistency cannot self-validate via DocConsistency (specs not in default scope). Future: extend DocConsistency v2 scope to `docs/audits/*/specs/`. |
| KC9 (nit) | DD-7 `mutates=False` for ContractCheck.record is under-justified relative to `_safety.py` semantics | The decision is correct (record writes operator-state, not application-state) but the rationale doesn't reference what `mutates=True` would gate. Add T6 test `test_record_logs_to_audit_with_correct_safe_op_kwargs` to verify the @safe_op decoration's audit-log shape. |

(Per devils-advocate review pass R2 — see `arcis:design-devils-advocate` invocation 2026-05-25.)
