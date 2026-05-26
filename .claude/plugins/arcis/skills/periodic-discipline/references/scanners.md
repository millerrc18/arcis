# Scanner Reference

Per-scanner intent, implementation strategy, and false-positive guidance for the `periodic-discipline` skill.

**Self-exclusion contract (all scanners):** Every scanner applies the path-glob filter:

```bash
--exclude-path '.claude/plugins/arcis/skills/periodic-discipline/**'
```

This is hardcoded into every fenced block in `audits/<verb>.md`. The skill does not audit its own files. If a false-positive slips through, add the `root_cause_key` to `allowlist.yaml` with a rationale comment.

---

## audit-skills Scanners (5)

### `file_line_drift`

**Intent:** Detect broken file:line cross-references in skill and command markdown files. A broken ref is one that points to a file that no longer exists, or a line number that has shifted past the referenced symbol.

**Implementation:** Invoke `python -m src.tools.docconsistency scan --json` against the arcis skills and commands directory tree, excluding the periodic-discipline skill path. The tool returns a JSON envelope with a `findings[]` array; each finding is mapped to a periodic-discipline finding record.

```bash
python -m src.tools.docconsistency scan \
  --target '.claude/plugins/arcis/skills' \
  --target '.claude/plugins/arcis/commands' \
  --json \
  | jq -c --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" '
      .findings[]
      | select(.doc_path | test(".claude/plugins/arcis/skills/periodic-discipline/") | not)
      | {
          invocation_id: $ENV.INVOCATION_ID,
          verb: "audit-skills",
          scanner: "file_line_drift",
          root_cause_key: ("docconsistency:" + .doc_path + ":" + (.doc_line|tostring)),
          severity: .severity,
          first_seen_utc: $ts,
          advisory: false,
          payload: .
        }' \
  >> "$REPORT.raw"
```

**False-positive guidance:** The `docconsistency` tool carries its own confidence flag per finding. If the tool reports a ref as dead but you believe it is live (e.g., a ref to a generated file), add the `root_cause_key` to `allowlist.yaml` with a comment explaining why. Do not suppress via code — the allowlist is the escape valve.

**Severity:** Inherits severity from the `docconsistency` finding (typically `major`).

---

### `subagent_unresolved`

**Intent:** Detect `subagent_type` references in skills and commands that point to an agent name not backed by any real agent file. This catches the class of drift where an agent is renamed (e.g., `cross-domain-analyst.md` → frontmatter `name: research-cross-domain-analyst`) but a skill still references the old name.

**Implementation strategy:** Two-phase.

Phase 1 — collect all `subagent_type` references in the corpus:

```bash
grep -rhEo 'subagent_type[:=][[:space:]]*"[a-z-]+"' \
  '.claude/plugins/arcis/skills' \
  '.claude/plugins/arcis/commands' \
  --include='*.md' \
  | grep -v 'periodic-discipline' \
  | sed -E 's/.*"([a-z-]+)".*/\1/' \
  | sort -u > /tmp/pd_agent_refs.txt
```

Phase 2 — parse `name:` from every agent frontmatter, build valid-names set, diff:

```bash
python -c "
import glob, yaml, sys, json, os
from datetime import datetime, timezone

valid = set()
for p in glob.glob('.claude/plugins/arcis/agents/*.md'):
    try:
        content = open(p, encoding='utf-8').read()
        fm = content.split('---')[1] if '---' in content else ''
        data = yaml.safe_load(fm) or {}
        if data.get('name'):
            valid.add(data['name'])
    except Exception:
        pass

ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
inv_id = os.environ.get('INVOCATION_ID', '')

with open('/tmp/pd_agent_refs.txt') as f:
    for line in f:
        agent = line.strip()
        if not agent:
            continue
        if agent not in valid:
            rec = {
                'invocation_id': inv_id,
                'verb': 'audit-skills',
                'scanner': 'subagent_unresolved',
                'root_cause_key': f'agent:{agent}',
                'severity': 'major',
                'first_seen_utc': ts,
                'advisory': False,
                'payload': {'agent': agent}
            }
            print(json.dumps(rec))
" >> "\$REPORT.raw"
```

**Known frontmatter-vs-filename mismatches (do NOT special-case):** The resolver discovers correct names via frontmatter parse, not hardcoded mapping. The three mismatches in the current codebase (`domain-lead.md` → `name: research-domain-lead`, `specialist.md` → `name: research-specialist`, `cross-domain-analyst.md` → `name: research-cross-domain-analyst`) are found generically because Phase 2 reads every agent's frontmatter `name:` field. Any future rename is caught automatically.

**False-positive guidance:** During agent rename transitions, the old name may appear in skills that haven't been updated yet. Add `agent:<old-name>` to `allowlist.yaml` with a rationale comment and a tracker reference (e.g., `# rationale: pending sweep in #NNN`).

**Scope guard:** Only fires on refs in `.claude/plugins/arcis/{skills,commands}/**/*.md` — does not scan test files or Python code.

**Severity:** `major`

---

### `tool_module_missing`

**Intent:** Detect `python -m src.tools.<name>` invocations in skill and command markdown files that reference a tool module that no longer exists (or was never shipped).

**Implementation:**

```bash
grep -rhEo 'python -m src\.tools\.[a-z_]+' \
  '.claude/plugins/arcis/skills' \
  '.claude/plugins/arcis/commands' \
  --include='*.md' \
  | grep -v 'periodic-discipline' \
  | sed -E 's/.*python -m (src\.tools\.[a-z_]+).*/\1/' \
  | sort -u \
  | while IFS= read -r module; do
      tool_dir="${module//./\/}"
      if [ ! -d "$tool_dir" ]; then
        python -c "
import json, os
from datetime import datetime, timezone
ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
print(json.dumps({
    'invocation_id': os.environ.get('INVOCATION_ID',''),
    'verb': 'audit-skills',
    'scanner': 'tool_module_missing',
    'root_cause_key': 'tool_module:$module',
    'severity': 'major',
    'first_seen_utc': ts,
    'advisory': False,
    'payload': {'module': '$module', 'expected_dir': '$tool_dir'}
}))"
      fi
    done >> "$REPORT.raw"
```

**Scope guard:** Excludes code fences inside reference docs (the grep scans for actual invocation patterns that would be executed, not example snippets — but the self-exclusion path filter prevents this scanner from scanning its own fences). Additional guard: exclude lines inside triple-backtick fences in any file under `references/`.

**False-positive guidance:** If a module is intentionally deferred (e.g., gated on a future PR), add `tool_module:<module>` to `allowlist.yaml` with a tracker reference.

**Severity:** `major`

---

### `workflow_parity`

**Intent:** Detect drift between the fenced bash blocks in `audits/<verb>.md` runbooks and the corresponding inline bash in `.github/workflows/periodic-discipline.yml`. These two surfaces must stay in sync — the CI workflow is supposed to be a faithful copy of the runbook fences.

**Implementation:** Normalize both surfaces (strip comment lines, collapse whitespace, ignore shebang), then diff:

```bash
python -c "
import re, json, os, subprocess
from datetime import datetime, timezone

def normalize(text):
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        lines.append(stripped)
    return '\n'.join(lines)

ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
inv_id = os.environ.get('INVOCATION_ID', '')

workflow = '.github/workflows/periodic-discipline.yml'
if not os.path.exists(workflow):
    rec = {
        'invocation_id': inv_id,
        'verb': 'audit-skills',
        'scanner': 'workflow_parity',
        'root_cause_key': 'workflow_parity:workflow_missing',
        'severity': 'critical',
        'first_seen_utc': ts,
        'advisory': False,
        'payload': {'detail': 'CI workflow file not found; expected ' + workflow}
    }
    print(json.dumps(rec))
" >> "\$REPORT.raw"
```

**Note:** Full implementation in `audits/audit-skills.md` extracts fenced blocks from both surfaces using a regex fence parser, normalizes each block, and emits a `critical` finding per divergent block. The scanner only fires if BOTH surfaces exist — a missing-on-one-side state produces its own `workflow_parity:workflow_missing` or `workflow_parity:runbook_missing` finding.

**False-positive guidance:** Minor formatting differences (trailing newlines, comment style) are filtered by the normalization step. If a deliberate divergence is needed (e.g., CI adds `--ci` flag), allowlist the specific `root_cause_key` with a rationale.

**Severity:** `critical` (CI/runbook drift is a runtime breakage risk on the next cron run)

---

### `llm_contradiction`

**Intent:** Detect logical contradictions within the skill and command corpus that static analysis cannot find — e.g., two skills that give conflicting advice about the same operational scenario, or a command doc that contradicts a reference doc.

**Implementation:** Dispatch `research-cross-domain-analyst` with the skills+commands corpus as `DOMAIN_REPORTS`, capture the `<findings>` JSON block, and map contradictions to periodic-discipline findings with `advisory: true`.

```
Agent(subagent_type: "research-cross-domain-analyst")
  DYNAMIC CONTEXT:
    DOMAIN_REPORTS: <concatenated text of .claude/plugins/arcis/{skills,commands}/**/*.md>
    ORIGINAL_QUERY: "Identify logical contradictions, conflicting instructions, or inconsistent guidance within this corpus of arcis skill and command files."
    OUTPUT_FORMAT: JSON array of {claim_a, claim_b, location_a, location_b, severity: high|medium|low, confidence: High|Moderate|Low}
```

Map each contradiction to a finding with:
- `scanner: "llm_contradiction"`
- `advisory: true`
- `severity: "minor"` (LLM findings are advisory by design)
- `root_cause_key: "llm_contradiction:<hash_of_claim_pair>"` (truncated SHA1 of sorted claim strings)

**Advisory marker:** `advisory: true` — these findings appear in the stdout summary under "Advisory findings (LLM-derived): N" and are NOT counted toward CI state transitions. The workflow stays GREEN even when many advisory findings exist.

**False-positive guidance:** LLM-derived findings are non-deterministic across runs. Expect some churn in advisory finding counts. Do not allowlist LLM findings unless the same contradiction key appears in 3+ consecutive runs (it's a stable false-positive at that point).

**Severity:** `minor` (advisory)

---

## curate-memory Scanners (3)

Memory tree location: `C:\Users\mille\.claude\projects\c--arcis\memory\` (operator-machine-local; outside repo). These scanners are **local-only** — refused in CI via `GITHUB_ACTIONS` env check.

### `duplicate_root_cause_key`

**Intent:** Detect memory entries that share the same `root_cause_key:` value — duplicate keys violate the dedup invariant and cause findings to be silently collapsed or over-suppressed.

**Implementation:**

```bash
MEMORY_DIR="$HOME/.claude/projects/c--arcis/memory"
if [ ! -d "$MEMORY_DIR" ]; then
  echo "memory tree unreachable: $MEMORY_DIR" >&2
  exit 1
fi

awk '/root_cause_key:/ {print $2}' "$MEMORY_DIR"/*.md \
  | sort \
  | uniq -c \
  | awk '$1 > 1 {print $2}' \
  | while IFS= read -r key; do
      python -c "
import json, os
from datetime import datetime, timezone
ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
print(json.dumps({
    'invocation_id': os.environ.get('INVOCATION_ID',''),
    'verb': 'curate-memory',
    'scanner': 'duplicate_root_cause_key',
    'root_cause_key': 'memory_dup:$key',
    'severity': 'major',
    'first_seen_utc': ts,
    'advisory': False,
    'payload': {'key': '$key'}
}))"
    done >> "$REPORT.raw"
```

**Severity:** `major`

---

### `stale_entry`

**Intent:** Surface memory entries that have not been touched in more than 90 days. Stale entries may describe superseded incidents, resolved bugs, or outdated operator preferences.

**Implementation:**

```bash
MEMORY_DIR="$HOME/.claude/projects/c--arcis/memory"
find "$MEMORY_DIR" -name '*.md' -mtime +90 \
  | while IFS= read -r filepath; do
      fname=$(basename "$filepath")
      python -c "
import json, os
from datetime import datetime, timezone
ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
print(json.dumps({
    'invocation_id': os.environ.get('INVOCATION_ID',''),
    'verb': 'curate-memory',
    'scanner': 'stale_entry',
    'root_cause_key': 'memory_stale:$fname',
    'severity': 'minor',
    'first_seen_utc': ts,
    'advisory': False,
    'payload': {'file': '$filepath'}
}))"
    done >> "$REPORT.raw"
```

**Note on Windows mtime semantics:** The `find -mtime +90` check is OS-dependent. On Windows, this scanner must run in Git Bash or WSL for correct POSIX mtime semantics. Documented in `audits/curate-memory.md` preamble as a precondition check.

**False-positive guidance:** Add `memory_stale:<filename>` to `allowlist.yaml` for entries you have reviewed and intentionally keep (e.g., foundational operator preferences that rarely change but should persist). Include a brief rationale.

**Severity:** `minor`

---

### `memory_contradiction`

**Intent:** Detect contradictions within the operator-memory corpus — e.g., two memory files that give conflicting advice about the same workflow, or a newer entry that implicitly supersedes an older one without removing it.

**Implementation:** Same dispatch pattern as `llm_contradiction` but with the memory corpus as input.

```
Agent(subagent_type: "research-cross-domain-analyst")
  DYNAMIC CONTEXT:
    DOMAIN_REPORTS: <concatenated text of $MEMORY_DIR/*.md>
    ORIGINAL_QUERY: "Identify logical contradictions, conflicting guidance, or entries that appear to supersede each other within this operator-memory corpus."
    OUTPUT_FORMAT: JSON array of {entry_a, entry_b, conflict_description, confidence: High|Moderate|Low}
```

Map each contradiction to a finding with:
- `scanner: "memory_contradiction"`
- `advisory: true`
- `severity: "minor"`
- `root_cause_key: "memory_contradiction:<hash_of_entry_pair>"`

**Advisory marker:** `advisory: true` — CI does not count these toward state transitions.

**Severity:** `minor` (advisory)

---

## test-tools Scanners (2)

### `cli_decorator_chain`

**Intent:** Verify that every tool `__main__.py` invokes the full required decorator stack when called via `python -m src.tools.<name> --help`. This catches the PR #1175 failure class where `__main__.py` imports `_impl` helpers directly, bypassing `@prod_guard` / `@safety_window` / `@audit_log`.

**Implementation:** Subprocess-invoke each tool with `ARCIS_SESSION_ID` set, then inspect the tool-execution.log for the decorator chain audit event.

```bash
for tool_dir in src/tools/*/; do
  tool=$(basename "$tool_dir")
  [ -f "src/tools/$tool/__main__.py" ] || continue

  # Invoke the tool; capture exit code (--help always exits 0 for well-formed CLIs)
  ARCIS_SESSION_ID="$INVOCATION_ID" python -m "src.tools.$tool" --help \
    > /dev/null 2>&1

  # Inspect log: does this invocation's event include the required decorators?
  python -c "
import json, os, sys
log_path = 'data/logs/tool-execution.log'
inv_id = os.environ.get('INVOCATION_ID','')
tool = '$tool'
required_tier1 = ['prod_guard', 'safety_window', 'audit_log']
# Read log lines for this session
if not os.path.exists(log_path):
    rec = {
        'invocation_id': inv_id,
        'verb': 'test-tools',
        'scanner': 'cli_decorator_chain',
        'root_cause_key': f'decorator_chain:log_missing',
        'severity': 'critical',
        'advisory': False,
        'payload': {'detail': 'tool-execution.log not found'}
    }
    print(json.dumps(rec))
    sys.exit(0)

found_chain = None
with open(log_path, encoding='utf-8') as f:
    for line in f:
        try:
            ev = json.loads(line)
            if ev.get('session_id') == inv_id and ev.get('tool_name', '').startswith(tool):
                found_chain = ev.get('decorator_chain', [])
        except json.JSONDecodeError:
            pass

from datetime import datetime, timezone
ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

if found_chain is None:
    rec = {
        'invocation_id': inv_id,
        'verb': 'test-tools',
        'scanner': 'cli_decorator_chain',
        'root_cause_key': f'decorator_chain:no_event:{tool}',
        'severity': 'critical',
        'first_seen_utc': ts,
        'advisory': False,
        'payload': {'tool': tool, 'detail': 'no audit event found for this invocation'}
    }
    print(json.dumps(rec))
elif not all(d in found_chain for d in required_tier1):
    missing = [d for d in required_tier1 if d not in found_chain]
    rec = {
        'invocation_id': inv_id,
        'verb': 'test-tools',
        'scanner': 'cli_decorator_chain',
        'root_cause_key': f'decorator_chain:missing:{tool}',
        'severity': 'critical',
        'first_seen_utc': ts,
        'advisory': False,
        'payload': {'tool': tool, 'missing_decorators': missing, 'found_chain': found_chain}
    }
    print(json.dumps(rec))
" >> "$REPORT.raw"
done
```

**PR #1175 regression class guarantee:** All checks use subprocess invocation (`python -m src.tools.<name> --help`), never in-process import. This is the only way to catch a `__main__.py` that bypasses the decorator stack by importing `_impl` directly.

**Concurrency note:** This scanner runs serially (no parallelism). Operator should not manually invoke audited tools while `test-tools` is running — concurrent invocations can produce false-positive log events that muddy the per-session filter.

**Severity:** `critical` (missing decorator = silent audit bypass = PR #1175 failure class)

---

### `boundary_test_missing`

**Intent:** Detect tool modules that ship `__main__.py` but lack a corresponding `tests/tools/test_<name>_boundary.py`. The boundary test file is the enforcement point for subprocess-level decorator-chain verification.

**Implementation:**

```bash
find src/tools -name '__main__.py' \
  | while IFS= read -r mainfile; do
      tool=$(echo "$mainfile" | sed -E 's|src/tools/([^/]+)/__main__.py|\1|')
      boundary_test="tests/tools/test_${tool}_boundary.py"
      if [ ! -f "$boundary_test" ]; then
        python -c "
import json, os
from datetime import datetime, timezone
ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
print(json.dumps({
    'invocation_id': os.environ.get('INVOCATION_ID',''),
    'verb': 'test-tools',
    'scanner': 'boundary_test_missing',
    'root_cause_key': 'boundary_test:$tool',
    'severity': 'major',
    'first_seen_utc': ts,
    'advisory': False,
    'payload': {'tool': '$tool', 'expected': '$boundary_test'}
}))"
      fi
    done >> "$REPORT.raw"
```

**False-positive guidance:** If a tool is intentionally untested at the boundary level (e.g., an internal utility without a CLI public contract), add `boundary_test:<name>` to `allowlist.yaml` with a rationale.

**Severity:** `major`
