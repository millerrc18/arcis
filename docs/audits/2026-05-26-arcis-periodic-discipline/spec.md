# Periodic Discipline Skill — Design Spec

**Issue:** #111 — meta-skill that audits arcis plugin infrastructure for drift
**Target version:** v0.36.6X (next minor at impl time)
**Status:** design complete — ready for `/arcis:code`
**Author:** design-architect (autonomous mode per `feedback_architect_autonomy 2026-05-26`)
**Reviews:** feasibility = PASS (after path correction); devil's-advocate = APPROVED (after 6-major revision + scope correction)

---

## 1. Overview

### 1.1 Purpose

A scheduled hygiene skill that runs three discipline audits — `audit-skills`, `curate-memory`, `test-tools` — on a cron cadence and on operator demand. It detects drift between living infrastructure (skills, memory, tool boundaries) and the structural invariants the project depends on, surfaces findings as PR-able JSON reports, and exempts conscious deviations via an opt-in allowlist.

Where `arcis:operate` (#109) is **reactive** (incident response when something breaks), this skill is **proactive** — catch infra drift before it bites. The watchdog OF the watchdogs.

### 1.2 Operator Constraint (Load-Bearing)

> **Skill is markdown-only (no Python). Implementation = SKILL.md + commands files + reference files + maybe a thin CI workflow if cron-triggered.**
>
> **OUT OF SCOPE: New tools (compose what's shipped)**

Every scanner in this spec is implemented as a fenced bash + `python -c` / `jq` one-liner block inside `audits/<verb>.md`, composing existing tools (`docconsistency`, `tool-execution.log`) and existing agents (`research-cross-domain-analyst`). No `src/tools/` additions. Pattern reference: `.claude/plugins/arcis/commands/operate.md` (842 lines) which embeds composition recipes the same way.

### 1.3 Goals

- Detect skill drift (file:line refs, agent names, tool module paths, workflow_parity, contradictions).
- Curate memory (duplicate `root_cause_key`, stale entries, contradictions).
- Verify tool boundary contracts (CLI decorators, audit logging, prod-guard).
- Produce JSON findings the operator can triage as PRs.
- Run on cron + on demand. No silent failures.

### 1.4 Non-Goals

- New Python tooling under `src/tools/`.
- Auto-fix mode (findings are advisory; operator decides).
- Replacing existing audit infrastructure (`docconsistency`, `contractcheck`, etc.) — this orchestrates them.
- Cross-plugin auditing (halcyon-audit, deep-research siblings are out of scope).

---

## 2. Architecture

### 2.1 File System Layout

```
.claude/plugins/arcis/skills/periodic-discipline/
├── SKILL.md                          # entry point, frontmatter, top-level orchestration
├── audits/
│   ├── audit-skills.md               # runbook — fenced bash + python -c blocks
│   ├── curate-memory.md              # runbook — fenced bash + jq blocks
│   ├── test-tools.md                 # runbook — fenced bash blocks invoking pytest + jq
│   └── full.md                       # orchestrator runbook — invokes other three sequentially
├── references/
│   ├── scanners.md                   # scanner-by-scanner intent + false-positive guidance
│   ├── findings-schema.md            # finding JSON shape, root_cause_key, dedup, decay rules
│   └── lockfile.md                   # PID-lockfile contract, invocation_id, report rotation
└── allowlist.yaml                    # opt-in exemptions (entries justify themselves)

data/periodic-discipline/
├── reports/                          # per-run JSON findings, rotated at 30d
├── archive/                          # monthly concatenated archives
└── .lock                             # PID lockfile (gitignored)

.github/workflows/periodic-discipline.yml  # cron + manual dispatch, mirrors runbook fences inline

tests/
├── skills/test_periodic_discipline.py            # pytest — verifies skill orchestration + findings shape
└── tools/test_periodic_discipline_boundary.py    # pytest — CLI decorator chain verification (Tier-1/Tier-2)
```

### 2.2 Invocation Model

Two entry surfaces, both routing through the same `audits/<verb>.md` runbooks:

1. **Skill invocation** (operator-on-demand): `Skill("periodic-discipline")` → reads `SKILL.md` → `SKILL.md` dispatches to one of the four `audits/<verb>.md` files based on user intent or argument.
2. **CI cron** (scheduled): `.github/workflows/periodic-discipline.yml` runs the same fenced bash blocks inline (faithful copy of runbook fences) on schedule.

The `workflow_parity` scanner (see §3.1) detects drift between these two surfaces.

### 2.3 Runbook Pattern

Each `audits/<verb>.md` follows this skeleton:

````markdown
---
verb: audit-skills
---

# Audit-Skills Runbook

## Preamble (lockfile + invocation_id)

```bash
set -euo pipefail
VERB="audit-skills"
INVOCATION_ID="PD-${VERB}-$(uuidgen | cut -c1-8)"
LOCKFILE="data/periodic-discipline/.lock"
if [ -f "$LOCKFILE" ] && kill -0 "$(cat $LOCKFILE)" 2>/dev/null; then
  echo "periodic-discipline already running (pid=$(cat $LOCKFILE))"; exit 1
fi
echo $$ > "$LOCKFILE"; trap "rm -f $LOCKFILE" EXIT
FINDINGS=()
REPORT="data/periodic-discipline/reports/${INVOCATION_ID}.json"
mkdir -p data/periodic-discipline/reports
```

## Scanner 1: file:line drift

```bash
python -m src.tools.docconsistency --json --paths '.claude/plugins/arcis/skills/**/*.md' \
  | jq -c '.findings[] | {scanner: "file_line_drift", root_cause_key: ("docconsistency:" + .file + ":" + (.line|tostring)), severity: .severity, payload: .}' \
  >> "$REPORT.raw"
```

## Scanner 2: subagent_type resolver

```bash
# Extract every subagent_type reference in skills/commands, verify a frontmatter file exists for each
grep -rhEo 'subagent_type[:= ]"[a-z-]+"' .claude/plugins/arcis/{skills,commands}/**/*.md \
  | sed -E 's/.*"([a-z-]+)".*/\1/' | sort -u \
  | while read agent; do
      python -c "import yaml, glob, sys; \
found = any((yaml.safe_load(open(p).read().split('---')[1]) or {}).get('name')=='$agent' \
for p in glob.glob('.claude/plugins/arcis/agents/*.md')); \
sys.exit(0 if found else 1)" || echo "{\"scanner\":\"subagent_unresolved\",\"root_cause_key\":\"agent:$agent\",\"severity\":\"major\",\"payload\":{\"agent\":\"$agent\"}}" >> "$REPORT.raw"
    done
```

## ... (remaining scanners follow same fence pattern) ...

## Postamble (dedup + write report)

```bash
jq -s 'group_by(.root_cause_key) | map(.[0])' "$REPORT.raw" > "$REPORT"
rm -f "$REPORT.raw"
# Apply allowlist filter
python -c "import yaml,json,sys; allow=set(yaml.safe_load(open('.claude/plugins/arcis/skills/periodic-discipline/allowlist.yaml'))['keys']); f=json.load(open('$REPORT')); json.dump([x for x in f if x['root_cause_key'] not in allow], open('$REPORT','w'), indent=2)"
# Rotate reports older than 30 days
find data/periodic-discipline/reports -type f -mtime +30 -name '*.json' -delete
exit 0
```
````

### 2.4 Integration Points

| Existing surface | How periodic-discipline composes it |
|------------------|--------------------------------------|
| `src/tools/docconsistency` | Invoked via `python -m` for file:line drift scanner |
| `data/logs/tool-execution.log` | Filtered via `jq 'select(.session_id == env.INVOCATION_ID)'` for boundary tests |
| `.claude/plugins/arcis/agents/research-cross-domain-analyst` | Dispatched for LLM contradiction scanner |
| `tests/tools/test_*_integration.py` pattern | New `tests/tools/test_periodic_discipline_boundary.py` follows same shape |
| `data/periodic-discipline/` | New directory (created by runbooks, gitignored except `.gitkeep`) |

### 2.5 Self-exclusion contract

All scanners apply a path-glob filter excluding `.claude/plugins/arcis/skills/periodic-discipline/**`. This is hardcoded into every fenced block and documented in `references/scanners.md`. Findings about the skill's own files are out-of-scope by design (the skill's prose is not a meaningful audit target for itself; the allowlist.yaml is the recovery surface if a false-positive slips through).

---

## 3. Scanner Catalog

### 3.1 audit-skills runbook

| Scanner | Implementation | Severity | False-positive guard |
|---------|----------------|----------|----------------------|
| `file_line_drift` | `python -m src.tools.docconsistency --json` | major | tool's own confidence flag |
| `subagent_unresolved` | `grep -hEo 'subagent_type[:= ]"[a-z-]+"'` + Python frontmatter check | major | only flags refs in `.claude/plugins/arcis/{skills,commands}/**/*.md` |
| `tool_module_missing` | `grep -hEo 'python -m src\.tools\.[a-z_]+'` + `test -d src/tools/<name>` | major | excludes code fences inside reference docs |
| `workflow_parity` | `python -c` diff of CI workflow inline-bash blocks vs. corresponding `audits/<verb>.md` fenced blocks (normalized: strip leading/trailing whitespace, comment lines) | critical | only fires if both surfaces exist; missing-on-one-side is its own finding |
| `llm_contradiction` | Dispatch `Agent(subagent_type="research-cross-domain-analyst")` with skills+commands corpus, capture JSON findings | minor (advisory) | agent self-reports confidence; advisory marker excludes from CI state transitions |

**subagent_unresolved generic resolver detail:** Parses `name:` frontmatter field from every `.claude/plugins/arcis/agents/*.md` to build `valid_agent_names`. The three known frontmatter-vs-filename mismatches (`domain-lead.md → research-domain-lead`, `specialist.md → research-specialist`, `cross-domain-analyst.md → research-cross-domain-analyst`) are NOT special-cased — the resolver discovers correct names via frontmatter parse and finds them all. Implementation notes in `references/scanners.md`.

### 3.2 curate-memory runbook

| Scanner | Implementation | Severity |
|---------|----------------|----------|
| `duplicate_root_cause_key` | `awk '/root_cause_key:/ {print}' memory/*.md \| sort \| uniq -c \| awk '$1 > 1'` | major |
| `stale_entry` | `find memory -name '*.md' -mtime +90` minus allowlist | minor |
| `memory_contradiction` | Dispatch `research-cross-domain-analyst` with memory corpus | minor (advisory) |

**Decay policy:** opt-in via allowlist only — no automatic time-based suppression. An entry stays a finding until added to allowlist (with rationale comment) OR the underlying drift is fixed. This honors the operator's strict-rigor preference: silent suppression is worse than persistent surfacing.

**Memory tree location:** `C:\Users\mille\.claude\projects\c--arcis\memory\` (operator-machine-local; outside repo). `curate-memory` is local-only (refused in CI via env check).

### 3.3 test-tools runbook

| Scanner | Implementation | Severity |
|---------|----------------|----------|
| `cli_decorator_chain` | For each `<name>` in `src/tools/*/__main__.py`: run `ARCIS_SESSION_ID=$INVOCATION_ID python -m src.tools.<name> --help`, then `jq 'select(.session_id == env.INVOCATION_ID) \| select(.decorator_chain \| contains(["prod_guard","safety_window","audit_log"]))' data/logs/tool-execution.log` — flag any tool whose chain doesn't include all required decorators per its tier | critical |
| `boundary_test_missing` | `find src/tools -name '__main__.py' \| xargs -I{} bash -c 'tool=$(...); test -f tests/tools/test_${tool}_boundary.py'` | major |

**PR #1175 regression class guarantee:** All boundary tests use subprocess invocation (`python -m src.tools.<name> ...`), never in-process import. This catches the exact failure mode that PR #1175 cycle-1 identified — `__main__.py` importing `_impl` helpers bypassing the decorator stack. Per `feedback_cli_decorated_public_api.md`.

**Concurrency constraint:** the boundary suite runs serially (no pytest-xdist parallel). While it runs, the operator should NOT manually invoke audited tools. Documented at the top of `audits/test-tools.md`.

---

## 4. Finding Schema

Every finding is a JSON record:

```json
{
  "invocation_id": "PD-audit-skills-a1b2c3d4",
  "verb": "audit-skills",
  "scanner": "subagent_unresolved",
  "root_cause_key": "agent:research-cross-domain-anlayst",
  "severity": "major",
  "first_seen_utc": "2026-05-26T14:00:00Z",
  "advisory": false,
  "payload": {"agent": "research-cross-domain-anlayst", "refs": ["skills/foo.md:42"]}
}
```

### 4.1 root_cause_key dedup

- `root_cause_key` is the dedup primary key. `jq -s 'group_by(.root_cause_key) | map(.[0])'` keeps the earliest.
- Different surface symptoms (same missing agent referenced from 5 skills) collapse to a single finding with all 5 refs in payload.refs.
- Allowlist filtering happens AFTER dedup. Audit-log records BOTH `raw_finding_count` and `root_cause_count` for diagnostic.

### 4.2 Advisory marker

LLM-derived findings (`llm_contradiction`, `memory_contradiction`) set `advisory: true`. The stdout summary shows them in a separate "Advisory findings (LLM-derived): N" section. CI workflow does NOT count them toward state transitions — workflow stays GREEN even when many advisory findings exist.

### 4.3 Allowlist format

`.claude/plugins/arcis/skills/periodic-discipline/allowlist.yaml`:

```yaml
keys:
  - agent:research-cross-domain-analyst-OLD-NAME  # rationale: renamed 2026-05-20, pending sweep
  - docconsistency:CLAUDE.md:42                    # rationale: false positive — points to known-good ref
```

If a finding's `root_cause_key` matches an allowlist entry, it is suppressed and counted in audit-log as `suppressed_count`. Malformed allowlist → run with empty allowlist + emit `allowlist_malformed` **critical** finding pointing at the parse error (the report is the recovery surface; we never refuse the verb).

### 4.4 Severity rubric

- **critical** — runtime breakage today (tool CLI missing decorator, audit-log silent, workflow_parity drift)
- **major** — drift that will break soon (broken xref, dead agent name, missing tool module)
- **minor** — cosmetic / style + LLM-advisory findings
- **info** — opt-in nudges (one info finding per run listing memory categories without decay coverage, if applicable)

---

## 5. Lockfile + Invocation ID Contract

- `data/periodic-discipline/.lock` holds the running PID. Concurrent run check: `kill -0 $(cat .lock) 2>/dev/null`. Trap-EXIT cleanup ensures removal even on failure. Stale PID auto-clears (kill -0 returns 1).
- `INVOCATION_ID="PD-${verb}-$(uuidgen | cut -c1-8)"` — 8-char suffix prevents collision; verb prefix makes log filtering trivial.
- Boundary tests propagate via `ARCIS_SESSION_ID=$INVOCATION_ID python -m src.tools.<name> ...`. The audit-log JSON line includes `session_id`, so `jq 'select(.session_id == env.INVOCATION_ID)'` isolates this run's tool events from concurrent traffic.
- This eliminates the TOCTOU race that the original line-count delta approach had against the watch loop and concurrent operator sessions.

---

## 6. Report Rotation

- Per-run reports: `data/periodic-discipline/reports/PD-<verb>-<id>.json`
- Daily: `find data/periodic-discipline/reports -mtime +30 -type f -name '*.json' -delete` (in runbook postamble)
- Monthly archive (manual or future CI): `cat reports/*.json > archive/$(date +%Y-%m).json` — operator decides retention policy on archives
- `data/periodic-discipline/reports/` is gitignored except `.gitkeep`; `archive/` is committable

---

## 7. CI Workflow (`.github/workflows/periodic-discipline.yml`)

```yaml
name: periodic-discipline
on:
  schedule:
    - cron: '0 7 * * 1'        # Mondays 07:00 UTC — audit-skills
    - cron: '0 7 * * 4'        # Thursdays 07:00 UTC — curate-memory + test-tools
  workflow_dispatch:
    inputs:
      verb:
        type: choice
        options: [audit-skills, curate-memory, test-tools, full]
        required: true
permissions:
  contents: read
jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: '3.11'}
      - run: pip install -r requirements.txt
      - name: Run runbook (mirror of audits/<verb>.md fenced blocks)
        run: |
          # NOTE: this script is a faithful copy of the fenced bash in
          # .claude/plugins/arcis/skills/periodic-discipline/audits/${{ inputs.verb || 'audit-skills' }}.md
          # Drift between this and the runbook is detected by the workflow_parity scanner.
          # ... full inline bash ...
      - uses: actions/upload-artifact@v4
        with:
          name: periodic-discipline-${{ github.run_id }}
          path: data/periodic-discipline/reports/*.json
```

**Per `feedback_audit_workflow_constraints.md` (operator-memory rule, not copied from pg-tests.yml which has no permissions block):**
- `permissions: contents: read` only
- NO blanket `continue-on-error: true`
- Three job states: green/clean | green/findings-with-summary | RED/scanner-crashed
- Findings surface via uploaded artifact + `$GITHUB_STEP_SUMMARY`; job goes RED only on crash

---

## 8. SKILL.md (entry point)

Frontmatter (bare-naming convention — name + description only):

```yaml
---
name: periodic-discipline
description: Cron-triggered + on-demand hygiene audits — skill drift, memory curation, tool boundary verification. Composes existing tools and agents; produces JSON findings. Use when the operator asks to run discipline audits, check skill/memory/tool hygiene, or investigate drift in the plugin infrastructure.
---
```

Body routes to `audits/<verb>.md` based on argument or asks the operator which verb to run via AskUserQuestion.

---

## 9. Error Handling

| Failure mode | Behavior |
|--------------|----------|
| Lockfile held by live PID | Exit 1 with message; CI run marked failed (alerts operator) |
| `docconsistency` missing | Detected by `tool_module_missing` scanner on first non-fenced invocation in any skill — runbook itself uses `command -v` guard and fails fast with explicit message |
| Agent dispatch fails | Capture stderr, emit `scanner_error` finding with severity=minor; do not abort run |
| Allowlist YAML malformed | Run with empty allowlist + emit `allowlist_malformed` **critical** finding (do NOT refuse the verb — the report is the recovery surface) |
| `data/periodic-discipline/` doesn't exist | `mkdir -p` in preamble |
| `tool-execution.log` missing | Boundary test scanner emits `log_missing` finding (critical); skips per-tool checks |
| Memory tree unreachable | `curate-memory` and `full` refuse cleanly with clear error; `audit-skills` and `test-tools` continue |
| `AskUserQuestion` not available (CI) | `curate-memory` and `full` refuse cleanly at PARSE-step env check (GITHUB_ACTIONS detection) |

---

## 10. Testing Strategy

Tests are pytest files under `tests/skills/` and `tests/tools/` — these are not new "tools," they follow the project's existing test pattern (see `tests/tools/test_<tool>_integration.py`).

### 10.1 `tests/skills/test_periodic_discipline.py`

1. `SKILL.md` + each `audits/<verb>.md` frontmatter parses as valid YAML
2. Each scanner block in `audits/audit-skills.md` produces JSON conforming to finding-schema (use `subprocess.run` against a fixture skill tree)
3. Lockfile contention — run two instances back-to-back; second exits 1
4. Invocation-id propagation — assert audit log line with matching `session_id` exists after a fixture run
5. Allowlist filtering — finding present in `allowlist.yaml` does not appear in final JSON
6. `root_cause_key` dedup — fixture produces 3 raw findings with same key; final JSON has 1
7. `workflow_parity` scanner detects deliberate drift between `.github/workflows/periodic-discipline.yml` and `audits/audit-skills.md`
8. Report rotation — populate `reports/` with `mtime` >30d files; postamble removes them

**Vacuous-test discipline (per `feedback_vacuous_test_pattern.md`):** each test must be able to FAIL — verify by temporarily breaking a runbook fence (drop a scanner block, run workflow_parity test, confirm RED) before approving. Tests that mock subprocess.run without exercising the runbook are theater.

### 10.2 `tests/tools/test_periodic_discipline_boundary.py`

For each Tier-1/Tier-2 tool in `src/tools/`:
- Subprocess-invoke `python -m src.tools.<name> --help` with `ARCIS_SESSION_ID` set
- Tail `data/logs/tool-execution.log`, filter by session_id, assert `decorator_chain` contains `prod_guard`, `safety_window`, `audit_log` per tier requirements

---

## 11. Cadence

- **Mondays 07:00 UTC:** `audit-skills` (catches drift from weekend operator work + Sunday agent dispatches)
- **Thursdays 07:00 UTC:** `curate-memory` + `test-tools` (mid-week health check)
- **On-demand:** any verb via `workflow_dispatch` or `Skill("periodic-discipline")` invocation
- **`full` verb:** runs all three sequentially; intended for pre-release; local-only (refused in CI because curate-memory needs memory tree)

---

## 12. Out of Scope

- Auto-fix mode
- Slack/Telegram/email notification
- New tools under `src/tools/` — this skill orchestrates existing infrastructure
- Changes to `docconsistency`, agent definitions, or `tool-execution.log` schema
- Cross-plugin auditing (halcyon-audit, deep-research siblings)

---

## 13. Design Decisions Log

| DD | Decision | Reversibility |
|---|---|---|
| DD1 | Every scanner is a fenced bash + python-c / jq one-liner in `audits/<verb>.md`, composing existing tools and agents | medium |
| DD2 | Allowlist is opt-in only — entries never auto-decay; operator explicitly curates allowlist.yaml | high |
| DD3 | File system layout under `.claude/plugins/arcis/skills/periodic-discipline/` with audits/, references/, allowlist.yaml as siblings of SKILL.md | high |
| DD4 | Cron-triggered CI workflow with two schedules (Mon audit-skills, Thu curate-memory + test-tools) plus workflow_dispatch | high |
| DD5 | Findings are JSON records with required fields `{invocation_id, verb, scanner, root_cause_key, severity, first_seen_utc, payload}` | high |
| DD6 | LLM contradiction scanner dispatches `research-cross-domain-analyst` agent with corpus, captures JSON findings | high |
| DD7 | PID lockfile at `data/periodic-discipline/.lock` with trap-EXIT cleanup; concurrent run detection via `kill -0` | high |
| DD8 | Report rotation at 30 days; older reports deleted in runbook postamble | high |
| DD9 | `root_cause_key` is the dedup primary key; `jq -s 'group_by(.root_cause_key) \| map(.[0])'` collapses duplicates | high |
| DD10 | `INVOCATION_ID="PD-${verb}-$(uuidgen \| cut -c1-8)"`; `ARCIS_SESSION_ID` propagates to tool subprocesses; `jq 'select(.session_id == env.INVOCATION_ID)'` filters tool-execution.log | high |
| DD11 | Honor markdown-only / no-new-tools constraint — all scanner logic in audits/<verb>.md as fenced bash + python-one-liner blocks composing existing tools; no `src/tools/` additions | low |

### DD1 — Scanners as fenced bash + python-oneliner blocks

**Rationale:** Operator constraint (markdown-only, no new tools) and pattern parity with `commands/operate.md` (842-line bash-composition runbook). Scanners that look "too complex for bash" (workflow_parity, root_cause_key dedup) are still expressible as 10–20 line `python -c` invocations against the JSON output of existing tools.

**Alternatives considered:**
- Extract scanners into `src/tools/periodic_discipline/` Python package — REJECTED (operator constraint violation; this was the pass-2 scope drift that DD11 documents)
- Use jq + bash only (no python -c) — REJECTED (YAML frontmatter parsing needs Python; pure jq makes workflow_parity diffing brittle)
- Helper scripts under `.github/scripts/` shared between runbook and workflow — REJECTED (still introduces a new "tool surface"; the workflow_parity scanner is the cleaner safety mechanism)

### DD2 — Allowlist opt-in only

**Rationale:** Time-based auto-decay was the DA Pass 1 major finding. Operator wants conscious exemptions with rationale comments. Allowlist file is reviewed alongside the findings PR.

**Alternatives considered:**
- 30-day auto-decay of allowlist entries — REJECTED (creates silent suppression, the failure mode this skill exists to prevent)
- Severity-based suppression (auto-decay minor only) — REJECTED (same silent-suppression risk)
- No allowlist (every finding always surfaces) — REJECTED (operator has known false-positives like renamed agents during transition periods)

### DD3 — File system layout

**Rationale:** Mirrors existing arcis plugin skill convention. `audits/` separates per-verb runbooks; `references/` holds documentation that wouldn't fit cleanly in SKILL.md. `allowlist.yaml` at top level so operator can find/edit it easily.

**Alternatives considered:**
- Single SKILL.md file with all runbooks embedded — REJECTED (>1500 lines becomes unreadable; per-verb separation matches operate.md's structure)
- audits/ under references/ — REJECTED (audits are first-class executable runbooks, not reference material)
- allowlist.yaml under `.claude/plugins/arcis/config/` — REJECTED (loses locality with the skill that consumes it)

### DD4 — Two cron schedules + workflow_dispatch

**Rationale:** Mon catches weekend drift; Thu catches mid-week drift before the Friday review cadence. Splitting the heavier scanners across two days keeps each run under 5 min. `workflow_dispatch` lets operator force a run before pre-release.

**Alternatives considered:**
- Single daily cron — REJECTED (excessive noise; findings repeat until allowlisted/fixed)
- Pre-commit hook — REJECTED (LLM contradiction scanner needs minutes, not seconds; operator wants async findings)
- GitHub Actions workflow_call from other workflows — DEFERRED (no current caller; can add later)

### DD5 — JSON finding records

**Rationale:** JSON is greppable, jq-queryable, and pasted directly into PR descriptions. `invocation_id` ties a finding to its log slice. severity ∈ {critical, major, minor, info} maps to existing project conventions. payload is scanner-specific.

**Alternatives considered:**
- SARIF format — REJECTED (overkill; GitHub Code Scanning integration not requested)
- Markdown findings — REJECTED (harder to dedup programmatically)
- TOML — REJECTED (no benefit over JSON; jq is the lingua franca)

### DD6 — LLM contradiction via research-cross-domain-analyst

**Rationale:** Existing agent specialized for cross-document contradiction analysis. Composition pattern matches the rest of the skill. No need to invent a new contradiction-detection mechanism. Findings carry `advisory: true` so CI doesn't gate on non-deterministic output.

**Alternatives considered:**
- Embedding-similarity heuristic in pure Python — REJECTED (false-positive-prone; operator has explicitly said "rather take a full day than hand-wave")
- Run a Claude prompt inline via subprocess — REJECTED (bypasses the agent system; loses the agent's specialized prompting)
- Skip this scanner — REJECTED (the LLM contradiction class is exactly the kind of drift this skill exists to catch)

### DD7 — PID lockfile

**Rationale:** Standard POSIX lockfile pattern; survives Ctrl-C via EXIT trap. CI and local runs share the same lockfile because both touch `data/`. `kill -0` distinguishes a stale lockfile (PID gone) from a live run.

**Alternatives considered:**
- Python `filelock` library — REJECTED (introduces a Python dependency surface for a 5-line bash check)
- `flock` command — REJECTED (not available on macOS by default; runbook should be platform-portable)
- No lockfile — REJECTED (concurrent CI + operator-on-demand can race on tool-execution.log filtering)

### DD8 — 30-day report rotation

**Rationale:** Findings have value while a PR is open; after 30d the file is either fixed (no longer reproduces) or allowlisted (won't reappear). Archive directory exists for future operator-driven monthly snapshots — not auto-populated to avoid silent retention growth.

**Alternatives considered:**
- Retain forever — REJECTED (data/ grows unbounded)
- 7-day rotation — REJECTED (too aggressive; operator may not triage weekly)
- Auto-archive monthly into archive/ — DEFERRED (operator can decide retention; this skill provides the directory but not the policy)

### DD9 — root_cause_key dedup

**Rationale:** DA Pass 1 finding: surface-level findings (e.g., 5 skills referencing the same missing agent) inflate noise. `root_cause_key` (e.g., `agent:research-cross-domain-anlayst`) collapses them to one finding with the 5 references listed in `payload.refs`. Allowlist filters by `root_cause_key` after dedup so a single allowlist entry suppresses all surface occurrences.

**Alternatives considered:**
- Dedup by (scanner, payload) tuple — REJECTED (misses cross-scanner duplicates and is brittle to payload field reordering)
- No dedup — REJECTED (DA Pass 1 explicitly called this out as major)
- Dedup at scanner-emit time rather than postamble — REJECTED (scanners run in parallel-eligible blocks; centralized postamble dedup is simpler)

### DD10 — invocation_id session marker

**Rationale:** DA Pass 1 finding: boundary tests need to assert decorator-chain events without seeing concurrent traffic from other watch-loop activity. Setting `ARCIS_SESSION_ID` env-var before subprocess invocation, then `jq`-filtering the log by that value, gives a clean per-run slice. 8-char suffix is collision-safe (256M IDs) without being unwieldy.

**Alternatives considered:**
- Filter log by timestamp window — REJECTED (clock skew across CI runners; brittle)
- Spawn each tool with `--log-file` flag pointing at a per-run log — REJECTED (tools don't all support that flag; would require modifying existing tools, violating operator constraint)
- Full UUID — REJECTED (unnecessarily long for log filtering)
- Original line-count snapshot before/after — REJECTED (TOCTOU race against concurrent writers, identified by DA Pass 1)

### DD11 — Honor markdown-only / no-new-tools constraint

**Rationale:** Operator constraint explicit in the original brief. Architect-autonomy memory (2026-05-26) does NOT cover MUST-override of explicit constraints — only routine design choices. This skill is fundamentally an orchestrator of existing infrastructure (docconsistency, agents, tool-execution.log), not a new infrastructure layer. The scanners that felt "too complex for markdown" in Pass 2 (workflow_parity, root_cause_key dedup, lockfile, report rotation) are all expressible as short `python -c` / `jq` invocations against the JSON output of existing tools. Embedding them in runbook fences follows the established `commands/operate.md` (842-line bash-composition runbook) pattern.

**Alternatives considered:**
- New Python tool under `src/tools/periodic_discipline/` (Pass 2 approach) — REJECTED: operator-constraint violation; would require explicit operator override that was not granted. Would touch ~8 new Python files / ~150 LOC plus integration tests. Structurally aligns with the rest of the plugin but violates the explicit brief constraint
- Helper Bash scripts under `.github/scripts/` — REJECTED: still a "tool surface" by another name. The workflow_parity scanner is the cleaner safety mechanism for preventing CI/runbook drift, not script extraction
- Surface override question to operator before producing the revision — CONSIDERED: rejected because the constraint is explicit and unambiguous; surfacing it would be procedural ceremony, not genuine MUST-override territory. If implementation experience reveals the markdown approach is untenable, an override question is the right escalation at THAT point — not preemptively

**Reversibility:** **low**. If reversed, would require adding a new `src/tools/` tool. The orchestrator-only approach is a deliberate choice; un-doing it is substantial code addition (~150 LOC + integration tests).

---

## 14. Known Considerations (post-DA minor issues)

These were flagged by Devil's Advocate as minor issues and merit operator awareness during implementation but do not block design:

1. **gh CLI auth in CI** — `curate-memory` only runs locally so this is moot; if a future change moves PR-ref scanning to CI, the workflow will need `permissions: pull-requests: read` added explicitly.
2. **Windows mtime semantics for stale_entry** — the 90d `find -mtime` check is OS-dependent on Windows; runbook should use Git Bash or WSL for portable mtime behavior. Documented in `audits/curate-memory.md` preamble.
3. **LLM determinism for advisory findings** — `research-cross-domain-analyst` may produce different findings across runs. The `advisory: true` marker and CI-ignore policy isolate this non-determinism; operator should expect some churn in advisory finding counts.
4. **Memory category coverage** — the initial allowlist will likely need 5–10 seed entries for currently-acceptable drift (renamed agents during transitions, intentional historical refs). Operator curates these on first run.
5. **Audit-log absence in CI** — `tool-execution.log` may not exist on a fresh CI checkout; the runbook handles this with a `log_missing` critical finding, but the first CI run will surface this until the log is generated by another workflow.

---

## 15. Implementation Notes

- Spec consumable by `/arcis:code` in a fresh session
- Target version at impl time: v0.36.6X (next minor after current)
- All 4 tasks fit in ONE PR
- Dual-Opus QA on merge (operator's standard merge gate)
- Per `feedback_use_coding_team_skill.md`: this is a multi-task feature spec, so use `/arcis:code` PM-orchestrator flow (not direct coding-developer dispatches)
