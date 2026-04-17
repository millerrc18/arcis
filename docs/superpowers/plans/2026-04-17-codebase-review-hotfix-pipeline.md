# Codebase Review + Hotfix Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute the human-directed hotfix pipeline defined in `docs/superpowers/specs/2026-04-17-codebase-review-hotfix-pipeline-design.md` — investigate 16 critical/high open issues + sweep 24h of logs → file any new issues at critical/high → open PRs (non-merging, Disposition C) for each in-scope issue.

**Architecture:** Four serial phases — Phase 0 Baseline → Phase 1 Investigation (self + 3 parallel Explore subagents + log sweep) → Phase 2 Triage → Phase 3 Hotfix Execution (serial per-issue) → Phase 4 Summary. 6 trivial hotfixes have concrete fix code inline in this plan; 10 complex hotfixes reference per-issue fix plans produced by Phase 1 agents into `.tmp/hotfix-plans/issue-<N>.md`.

**Tech Stack:** Python 3.12, pytest, git + gh CLI, Claude Code Agent tool (Explore subagent), SQLite (raw sqlite3, no ORM), FastAPI, CLAUDE.md conventions.

**Adapt-notice:** This is an *execution* plan, not a feature-build plan. Task structure deviates from the writing-plans template's TDD cycle because the "feature" is a process. Task steps are still bite-sized and concrete.

---

## Shared references (used by multiple tasks)

**Spec:** `docs/superpowers/specs/2026-04-17-codebase-review-hotfix-pipeline-design.md`
**Baseline file (written by Task 1):** `.tmp/phase0-baseline.txt`
**Fix plans dir (written by Tasks 4–6):** `.tmp/hotfix-plans/issue-<N>.md`
**Log sweep output (written by Task 7):** `.tmp/phase1-log-findings.md`
**Pipeline scratchpad (updated throughout):** `.tmp/pipeline-state.md`

All `.tmp/` files are ephemeral and will be deleted at end of Phase 4. `.tmp/` is gitignored by convention; Task 1 verifies this.

## Common: branch naming

`fix/<issue-number>-<kebab-short-desc>` — e.g. `fix/462-pyarrow-in-requirements`.

## Common: commit message template

```
fix(<area>): <imperative summary under 72 chars>

<body: what changed, why, root cause>

Fixes #<N>
```
Area options (from git log): `deps`, `security`, `schema`, `startup`, `risk`, `executor`, `reconcile`, `tests`, `ci`, `architecture`.

## Common: PR body template

Use verbatim from spec §"PR body template", filling `<N>`, `<area>`, baseline pass count from `.tmp/phase0-baseline.txt`, test delta from the task's own pytest run, and verification transcript (tail ~20 lines of `pytest tests/ -q`).

## Common: per-issue hotfix task shape

All Phase 3 tasks (Tasks 12–27+) follow this nine-step shape. The *specific* fix/test/commit-body content is inline in each task; the shape is repeated so the task is self-contained and can be read out of order.

1. Checkout `main`, pull, branch: `git checkout main && git pull && git checkout -b fix/<N>-<kebab>`
2. Apply fix (concrete diff or reference to `.tmp/hotfix-plans/issue-<N>.md`)
3. Add/update regression test
4. Run targeted test: `python -m pytest tests/<area> -xvs`, verify pass
5. Run full suite: `python -m pytest tests/ -q`, compare pass/fail counts to `.tmp/phase0-baseline.txt`; abort if counts regressed
6. Update `CHANGELOG.md` `## [Unreleased]` with one-line entry
7. Commit: `git add -A && git commit -m "fix(<area>): <summary>" <body>`
8. Push: `git push -u origin fix/<N>-<kebab>`
9. Open PR: `gh pr create --base <main-or-stacked> --title "fix(<area>): <summary>" --body "<from template>"` — NON-draft; do NOT merge

---

## Phase 0 — Baseline

### Task 1: Capture pytest baseline on clean `main`

**Files:**
- Create: `.tmp/phase0-baseline.txt`
- Create: `.tmp/pipeline-state.md`

- [ ] **Step 1: Verify clean state and working tree**

Run:
```bash
cd /c/arcis/halcyon-lab
git status
git log --oneline -1
```
Expected: clean working tree, branch `main`, last commit hash noted in `.tmp/pipeline-state.md`.

- [ ] **Step 2: Ensure `.tmp/` is gitignored**

Run:
```bash
grep -E '^\.tmp' .gitignore || echo '.tmp/' >> .gitignore && git diff .gitignore
```
If `.gitignore` had to be modified, DO NOT commit — `.tmp/` is a session-local convention. Revert if any change: `git checkout .gitignore`. If already present, no change.

- [ ] **Step 3: Create `.tmp/` dir and run full pytest**

Run:
```bash
mkdir -p .tmp/hotfix-plans
python -m pytest tests/ -q 2>&1 | tee .tmp/phase0-baseline.txt
```
Expected: exit code 0 or non-zero (non-zero is OK if some tests fail — record the counts). Tail shows summary line like `1852 passed, N failed, M skipped in Xs`.

- [ ] **Step 4: Record baseline numbers**

Extract from `.tmp/phase0-baseline.txt` summary line:
- pass count → `BASELINE_PASS`
- fail count → `BASELINE_FAIL`
- error count → `BASELINE_ERR`

Write to `.tmp/pipeline-state.md`:
```markdown
# Pipeline State — 2026-04-17

## Phase 0 baseline
- Commit: <hash>
- Pass: <N>
- Fail: <N>
- Error: <N>
- Skipped: <N>
- Must not drop pass count below: <N>
- Must not raise failure count above: <N>
- CI floor from CLAUDE.md: 1339
```

Abort condition: if pass count is below 1339, STOP the pipeline and surface the regression — something is broken on `main` before we've touched anything.

### Task 2: Load remediation context

**Files:** (read-only)
- Read: `CHANGELOG.md`, `RELEASES.md`
- Run: `git log`

- [ ] **Step 1: Read CHANGELOG `## [Unreleased]` and top 10 versions**

Run:
```bash
sed -n '1,400p' CHANGELOG.md
```
Mentally model: what has been fixed recently and is awaiting release?

- [ ] **Step 2: Read RELEASES.md last 10 entries**

Run:
```bash
sed -n '1,300p' RELEASES.md
```
Mentally model: what landed in the last ~2 weeks?

- [ ] **Step 3: Get 7-day file-commit map**

Run:
```bash
git log --since="2026-04-10" --name-only --pretty=format:"== %h %s"
```
Save to `.tmp/pipeline-state.md` under `## Phase 0 recent commits` — compact format, one line per commit + affected files. This feeds the Phase 2 remediation cross-check.

- [ ] **Step 4: Update `.tmp/pipeline-state.md` with "recently remediated" summary**

List any already-fixed-but-I-might-log-match symptoms — e.g. `signal.signal ValueError`, `yfinance MultiIndex`, `Ollama circuit-breaker`. Phase 4 summary cross-references this.

---

## Phase 1 — Investigation

### Task 3: Self-investigate the 6 trivial existing issues

Read-only investigation. Output: `.tmp/hotfix-plans/issue-<N>.md` per issue with the exact fix I'll apply in Phase 3.

**Files:**
- Read: `requirements.txt`, `requirements-cloud.txt`, `src/**`, `tests/test_coerce_to_schema.py`, `src/api/cloud_routes/trades.py`, `src/startup_checks.py`
- Create: `.tmp/hotfix-plans/issue-455.md`, `.tmp/hotfix-plans/issue-460.md`, `.tmp/hotfix-plans/issue-462.md`, `.tmp/hotfix-plans/issue-435.md`, `.tmp/hotfix-plans/issue-456.md`, `.tmp/hotfix-plans/issue-457.md`

- [ ] **Step 1: #455 beautifulsoup4 — verify + plan fix**

Run:
```bash
grep -rn 'from bs4\|import bs4\|BeautifulSoup' src/ | head -20
grep -E 'beautifulsoup|bs4' requirements*.txt
python -c "import bs4; print(bs4.__version__)"
```
Expected: at least one `from bs4` hit in src/, no match in requirements.txt, installed bs4 version printed. Write `.tmp/hotfix-plans/issue-455.md`:
```
Fix: add `beautifulsoup4>=4.12` line to requirements.txt
Test: no new test needed; importability verified by existing test_imports.
Branch: fix/455-beautifulsoup4-dependency
Area: deps
```

- [ ] **Step 2: #460 scipy + numpy — verify + plan fix**

Run:
```bash
grep -rnE '^(import scipy|from scipy|import numpy|from numpy)' src/ | head -20
grep -E 'scipy|numpy' requirements*.txt
python -c "import scipy, numpy; print(scipy.__version__, numpy.__version__)"
```
Write `.tmp/hotfix-plans/issue-460.md` noting installed versions. Fix: add `scipy>=<major>.<minor>` and `numpy>=<major>.<minor>` matching installed.

- [ ] **Step 3: #462 pyarrow — verify + plan fix**

Run:
```bash
grep -rnE '^(import pyarrow|from pyarrow|import pandas as pd.*parquet)' src/ | head -20
grep -E 'pyarrow' requirements*.txt
python -c "import pyarrow; print(pyarrow.__version__)"
```
Write `.tmp/hotfix-plans/issue-462.md`. Fix: add `pyarrow>=<major>.<minor>`.

- [ ] **Step 4: #435 failing test — reproduce + plan fix**

Run:
```bash
python -m pytest tests/test_coerce_to_schema.py -v 2>&1 | tail -40
```
Expected: see the exact assertion failure. Read `tests/test_coerce_to_schema.py` around the failing assertion. Write `.tmp/hotfix-plans/issue-435.md` with the one-line fix (test fixture or assertion change to match `planned_shares REAL`).

- [ ] **Step 5: #456 cloud_routes/trades.py line count — reproduce + plan fix**

Run:
```bash
wc -l src/api/cloud_routes/trades.py
```
Read file. Identify 1-2 cohesive helpers to extract (e.g. pagination logic, formatting, or a chunk of per-field normalization). Write `.tmp/hotfix-plans/issue-456.md` with:
- Current line count
- Target extraction: helper name, lines it covers, new file path (e.g. `src/api/cloud_routes/_trades_helpers.py`)
- Expected new line count after extraction: <400

- [ ] **Step 6: #457 `_check_render_postgres` — reproduce + plan fix**

Run:
```bash
grep -n '^def _check_render_postgres\|^def ' src/startup_checks.py | head -40
```
Read the function body. Identify inner block to extract. Write `.tmp/hotfix-plans/issue-457.md` with helper name, extracted lines, resulting function length <60.

### Task 4: Dispatch Agent A — Security cluster investigation

**Parallel with Tasks 5, 6, and 7.** Use Agent tool with `subagent_type=Explore` and read-only expectation. The agent writes report to stdout (returned to me); I save it to `.tmp/hotfix-plans/security-cluster.md`, then split into per-issue files.

**Files:**
- Create: `.tmp/hotfix-plans/security-cluster.md`, `.tmp/hotfix-plans/issue-413.md`, `.tmp/hotfix-plans/issue-424.md`, `.tmp/hotfix-plans/issue-439.md`, `.tmp/hotfix-plans/issue-440.md`, `.tmp/hotfix-plans/issue-459.md`

- [ ] **Step 1: Dispatch Agent A**

Invoke Agent tool with description "Security cluster investigation" and `subagent_type=Explore`, prompt:

```
You are investigating five related security issues in the `millerrc18/halcyon-lab` Python trading application at `/c/arcis/halcyon-lab/`. Work read-only — no Edit, no Write, no git operations. Return a structured report, under 2000 words total.

Read these first:
- /c/arcis/halcyon-lab/MASTER.md — conventions
- /c/arcis/halcyon-lab/CLAUDE.md — rules (mocking, schema registry)

Investigate each issue below. For each, return: (1) Root-cause confirmation from reading the actual code; (2) Attack surface (who can exploit, preconditions); (3) Proposed fix with exact code snippet; (4) Test strategy (new test files + cases); (5) Affected files with line numbers.

Issues:
- #413: Unsafe deserialization in data_enrichment cache files. Read `src/data_enrichment/` for the cache-load code path. Finding: the loader accepts cache files whose format permits arbitrary-code execution on load. Fix candidates: migrate cache to JSON; or sign + hmac-verify before deserialize; or restrict to an allowlisted class set.
- #459: Same pattern in `src/training/historical_data.py`. Read that file.
- #439: `verify_auth` in `src/api/cloud_app.py` silently disables auth when env var `API_SECRET` is empty. Read `cloud_app.py` around the auth function. Fix: raise on startup if empty, not per-request silent-pass.
- #440: Bearer token comparison in `cloud_app.py` uses `==` (timing-attack vulnerable). Fix: `hmac.compare_digest`.
- #424: Bot-token leakage via exception logging in `src/notifications/telegram.py`. Read the error-handling path. Fix: redact bearer tokens in exception formatters.

For each issue, the fix proposal must be directly codable in Phase 3 — include the exact before/after for any changed lines, not abstract descriptions.

Return format:
## Issue #<N>
### Root cause
### Attack surface
### Fix (before/after diff)
### Test strategy
### Files
```

- [ ] **Step 2: Save agent output to `.tmp/hotfix-plans/security-cluster.md`**

Copy the returned text verbatim.

- [ ] **Step 3: Split into per-issue files**

For each of #413, #424, #439, #440, #459, extract the corresponding `## Issue #<N>` section into `.tmp/hotfix-plans/issue-<N>.md`.

- [ ] **Step 4: Verify agent's claims myself on the 2 most-security-sensitive (#439, #440)**

Read `src/api/cloud_app.py` auth function directly. Confirm the fix proposal matches reality. Note any discrepancies in `.tmp/hotfix-plans/issue-<N>.md` under a `### Verification` section. Do NOT code yet — that's Phase 3.

### Task 5: Dispatch Agent B — Import graph investigation

**Parallel with Tasks 4, 6, 7.**

**Files:**
- Create: `.tmp/hotfix-plans/import-graph.md`, `.tmp/hotfix-plans/issue-434.md`, `.tmp/hotfix-plans/issue-461.md`

- [ ] **Step 1: Dispatch Agent B**

Invoke Agent tool with description "Import graph investigation" and `subagent_type=Explore`, prompt:

```
You are investigating circular-import issues in `/c/arcis/halcyon-lab/`. Read-only. Under 1500 words total.

Read first:
- /c/arcis/halcyon-lab/MASTER.md
- /c/arcis/halcyon-lab/CLAUDE.md

Investigate:
- #434: Circular import between src/startup.py and src/startup_checks.py. Read both files. Map the cycle (A imports B imports A). Identify which import can be made lazy (deferred inside a function) or moved to TYPE_CHECKING gate.
- #461: Three undocumented circular cycles across production code. Find them via: `python -c "import src.main"` combined with reading top-level module files (src/main.py, src/startup.py, src/startup_checks.py, src/watch.py, src/scheduler/*, src/services/*, src/api/app.py, src/api/cloud_app.py). For each cycle, identify: modules involved, which edge can be broken without behavior change.

For each cycle, return:
## Cycle: A ↔ B [↔ C]
### Import edges
### Root cause (why the cycle exists)
### Proposed break (which import to make lazy / move to TYPE_CHECKING / extract interface)
### Exact code change (before/after)
### Regression test (that the cycle stays broken)
### Files

Return format suitable for Phase 3 code application.
```

- [ ] **Step 2: Save output to `.tmp/hotfix-plans/import-graph.md`**

- [ ] **Step 3: Split: #434 is the startup↔startup_checks cycle specifically; the other 2 cycles belong to #461.**

Create `.tmp/hotfix-plans/issue-434.md` (the specific startup cycle) and `.tmp/hotfix-plans/issue-461.md` (the other two cycles; #461 fix may be one PR with 2 fixes or stacked PRs — decide at Phase 3 based on file overlap).

- [ ] **Step 4: Smoke-test claimed cycles myself**

Run `python -c "import src.startup; import src.startup_checks"` and `python -c "import src.main"`. Note current behavior in `.tmp/hotfix-plans/issue-<N>.md`.

### Task 6: Dispatch Agent C — Trading-safety investigation

**Parallel with Tasks 4, 5, 7.** Highest-stakes cluster — I will re-verify every claim in Phase 3.

**Files:**
- Create: `.tmp/hotfix-plans/trading-safety.md`, `.tmp/hotfix-plans/issue-431.md`, `.tmp/hotfix-plans/issue-436.md`, `.tmp/hotfix-plans/issue-438.md`

- [ ] **Step 1: Dispatch Agent C**

Invoke Agent tool with description "Trading-safety investigation" and `subagent_type=Explore`, prompt:

```
You are investigating three trading-safety bugs in `/c/arcis/halcyon-lab/`. Read-only. Under 2000 words total.

Read first:
- /c/arcis/halcyon-lab/MASTER.md (section on risk governor, broker abstraction)
- /c/arcis/halcyon-lab/CLAUDE.md (trading rules, schema registry rule)
- /c/arcis/halcyon-lab/src/shadow_trading/models.py (status lifecycle)

Investigate:
- #436: ImportError in bracket fallback silently leaves live position unprotected. Read `src/trading/alpaca_broker.py`, `src/shadow_trading/alpaca_adapter.py`, and any bracket-fallback code path. Identify the ImportError-swallowing except clause. Fix must be fail-closed (abort entry), not fail-safe (proceed without bracket).
- #438: Risk governor allows any position size when `equity == 0`. Read `src/risk/governor.py`. Identify the division-or-guard that permits unbounded position when equity is 0. Decide: fail-closed (block trade, log loud) or fail-safe (use a default floor). Recommend fail-closed.
- #431: Reconciler backfill bypasses position-limit governor. Read `src/shadow_trading/` reconcile paths (post_close, intra_day) and find the backfill code that inserts positions without running governor.evaluate(). Fix: gate the backfill through the governor, or raise on attempted violation.

For each issue, return:
## Issue #<N>
### Root cause (exact file:line of the defect)
### Reproduction (conditions that trigger it — what's equity=0? what triggers bracket fallback? what's a backfill?)
### Fix choice (fail-closed vs fail-safe decision with rationale)
### Fix (before/after code)
### Regression test strategy (new test in tests/<area>/, mocking Alpaca/Ollama/yfinance per CLAUDE.md rules, covering the failure mode + the success path)
### Files

Be especially careful with test strategy — these are money-adjacent and the fix must be guarded.
```

- [ ] **Step 2: Save to `.tmp/hotfix-plans/trading-safety.md`**

- [ ] **Step 3: Split into per-issue files**

`.tmp/hotfix-plans/issue-431.md`, `.tmp/hotfix-plans/issue-436.md`, `.tmp/hotfix-plans/issue-438.md`.

- [ ] **Step 4: Re-verify every claim myself**

For each issue, read the cited file:line directly. Run any reproduction one-liner. Add my own `### Verification` section to each `.tmp/hotfix-plans/issue-<N>.md`. If the agent's fix is wrong or incomplete, flag in `.tmp/pipeline-state.md` under `## Phase 1 agent disagreements`.

### Task 7: 24h log sweep

**Files:**
- Read: `logs/arcis.log`, `logs/arcis_err.log`
- Create: `.tmp/phase1-log-findings.md`

- [ ] **Step 1: Verify log file presence + size + freshness**

Run:
```bash
ls -la logs/arcis.log logs/arcis_err.log
ls -la data/logs/ 2>/dev/null | head -5 || echo 'no NSSM logs'
```
Note file sizes and last-modified timestamps in `.tmp/phase1-log-findings.md`.

- [ ] **Step 2: Filter logs to last 24h window**

The cutoff is 2026-04-16T07:00 America/New_York (≈ 24h before "now" at plan-writing time, 2026-04-17). The logger uses `%(asctime)s` via `StructuredFormatter` so timestamps are parseable. Run:
```bash
python - <<'PY'
import re, sys
cutoff = "2026-04-16 07:00"
ts_re = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2})')
for path in ["logs/arcis.log", "logs/arcis_err.log"]:
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = ts_re.match(line)
            if m and m.group(1) >= cutoff:
                sys.stdout.write(line)
PY
```
Redirect to `.tmp/phase1-24h-raw.log`.

- [ ] **Step 3: Extract errors + warnings + tracebacks**

Run:
```bash
grep -nE '\[(ERROR|CRITICAL|WARNING)\]|^Traceback' .tmp/phase1-24h-raw.log > .tmp/phase1-24h-errors.log
wc -l .tmp/phase1-24h-errors.log
```

- [ ] **Step 4: Cluster by logger name + message shape**

Run:
```bash
python - <<'PY'
import re
from collections import Counter
shape_re = re.compile(r"\b\d+\b|\b[A-Z]{1,6}[A-Z0-9]{0,6}\b|'[^']*'|\"[^\"]*\"|\(\S+\)|/\S+\.\w+:\d+")
counts = Counter()
with open(".tmp/phase1-24h-errors.log", encoding="utf-8", errors="replace") as f:
    for line in f:
        skeleton = shape_re.sub("_", line)
        counts[skeleton] += 1
for shape, n in counts.most_common(40):
    print(f"{n:>6}  {shape[:200]}")
PY
```
Capture top-40 clusters in `.tmp/phase1-log-findings.md` under `## Top 40 clusters`.

- [ ] **Step 5: Apply thresholds**

For each cluster, classify per §Section 2 spec rubric:
- CRITICAL / Traceback ≥ 2× → candidate
- ERROR ≥ 5× → candidate
- WARNING ≥ 20× → candidate
- Below threshold → noise (record in Phase 4 top-10 noise report)

Write the candidate list to `.tmp/phase1-log-findings.md` under `## Candidates for filing`.

- [ ] **Step 6: Expand candidates — find example log lines, stack tops, and emitter files**

For each candidate cluster, pick 1–3 example lines (grep with context `-A 30`) and identify the Python module emitting it. Add to the candidate entry.

---

## Phase 2 — Triage & new-issue filing

### Task 8: Aggregate all candidate findings

**Files:**
- Read: `.tmp/phase1-log-findings.md`, `.tmp/pipeline-state.md`
- Create: `.tmp/phase2-candidates.md`

- [ ] **Step 1: List all candidate new findings**

Sources:
- Phase 1 Task 7 log-derived candidates
- Any code-review findings I noticed in Phase 1 while reading files (e.g. while investigating #456, I might have noticed a bug in `trades.py`). Record these in `.tmp/phase2-candidates.md` under `## Code-review side-findings`.

- [ ] **Step 2: Tag each candidate with provisional severity**

Criteria:
- critical: data loss, trading-safety defect, auth bypass, RCE, deploy-blocker
- high: crash on startup, failing test blocking CI, >1h daily error spam
- medium: deprecation, style, non-blocking warnings → drop (respect audit-bot cadence)

Drop medium candidates now; keep critical + high.

### Task 9: Remediation cross-check each candidate

**Files:**
- Read: `CHANGELOG.md`, `RELEASES.md`, git log
- Update: `.tmp/phase2-candidates.md`

- [ ] **Step 1: For each candidate, search CHANGELOG for the symptom**

Run:
```bash
grep -iE '<candidate-keyword>' CHANGELOG.md RELEASES.md | head -10
```
(Substitute keyword per candidate — e.g. `governor`, `bracket`, `signal.signal`, etc.)

- [ ] **Step 2: For each candidate, check git log for the emitter file**

Run:
```bash
git log --since="2026-04-10" --all --oneline -- <emitter-file>
```

- [ ] **Step 3: Compare fix-commit timestamp vs last log occurrence**

For each candidate, classify:
- `already-fixed` — fix commit timestamp > last log occurrence
- `still-active` — keep as candidate
- `regression` — fix commit exists but log occurrence is newer (rare but possible)

Update `.tmp/phase2-candidates.md` with classification.

### Task 10: Open-issue dedup

**Files:**
- Read: open issues via gh CLI
- Update: `.tmp/phase2-candidates.md`

- [ ] **Step 1: Fetch all open issue bodies for matching**

Run:
```bash
gh issue list --repo millerrc18/halcyon-lab --state open --limit 100 --json number,title,body > .tmp/open-issues.json
```

- [ ] **Step 2: Match each candidate against open issues**

For each candidate, grep the JSON for (a) the emitter file path, (b) the stack-top function name, (c) distinctive error-message phrases. If match found: add evidence comment to existing issue rather than file new. Record match in `.tmp/phase2-candidates.md`.

- [ ] **Step 3: For matched candidates, draft evidence comments**

Write comments to `.tmp/phase2-comments/<issue-N>.md`. Comment format:
```
Additional evidence from 24h log sweep (2026-04-17):
- N occurrences between T1 and T2
- Example stack: <first 3 frames>
- Emitting module: <path>
```

### Task 11: File new issues (non-duplicate, still-active candidates)

**Files:**
- Create (via gh CLI): new GitHub issues

- [ ] **Step 1: For each candidate remaining (not dedup'd, not remediated), prepare body**

Body format (canonical audit format):
```markdown
**Focus Area:** <domain>
**Severity:** <critical|high>
**File:** <path>
**Line(s):** <N>

**Finding:**
<description with reproduction conditions>

**Suggested Fix:**
<code snippet or approach>

---
*Opened by Claude Code review — 2026-04-17*
```

Save each prepared body to `.tmp/phase2-new-issues/<slug>.md`.

- [ ] **Step 2: File each issue via gh CLI**

Run for each:
```bash
gh issue create --repo millerrc18/halcyon-lab \
  --title "[Audit] <domain> — <symptom>" \
  --body-file .tmp/phase2-new-issues/<slug>.md \
  --label audit --label bug --label severity:<tier> [--label trading-safety|security|architecture|tests]
```
Record returned issue numbers in `.tmp/pipeline-state.md` under `## Phase 2 new issues`.

- [ ] **Step 3: Post evidence comments to existing-issue matches**

Run for each:
```bash
gh issue comment <N> --repo millerrc18/halcyon-lab --body-file .tmp/phase2-comments/<issue-N>.md
```

- [ ] **Step 4: Build the final Phase 3 queue**

Append any new-issue numbers to the risk-tiered queue in `.tmp/pipeline-state.md` at the appropriate tier, based on their severity label. Queue order is the order Phase 3 tasks will run.

---

## Phase 3 — Hotfix execution (serial, risk-descending)

> For every task in this phase: (1) apply the common 9-step shape from the "Common: per-issue hotfix task shape" section; (2) use the concrete fix/test content inline below; (3) verify Phase 3 pre-flight — on `main`, clean tree, baseline numbers in `.tmp/phase0-baseline.txt`; (4) if full-suite pytest shows any regression vs baseline, abort the task, leave branch unpushed, document in `.tmp/pipeline-state.md`, move to next issue with a note.

### Task 12: Fix #455 — missing `beautifulsoup4` dependency

**Files:**
- Modify: `requirements.txt`
- Read: `.tmp/hotfix-plans/issue-455.md` (from Task 3)

- [ ] **Step 1: Branch**

Run:
```bash
git checkout main && git pull
git checkout -b fix/455-beautifulsoup4-dependency
```

- [ ] **Step 2: Apply fix — add line to `requirements.txt`**

Use the version pin captured in `.tmp/hotfix-plans/issue-455.md` (format `beautifulsoup4>=<installed-major>.<installed-minor>`). Insert the line in alphabetical position within `requirements.txt`. Use Edit tool, not `echo >>`.

- [ ] **Step 3: Add regression test**

Add to `tests/test_dependencies.py` (create if absent):
```python
def test_beautifulsoup4_importable():
    """Regression for #455: bs4 must be declared so fed_collector works on clean deploy."""
    import bs4  # noqa: F401
```
Also add a line to `tests/test_requirements.py` (or create) that parses `requirements.txt` and asserts `beautifulsoup4` is listed.

- [ ] **Step 4: Run targeted test**

Run:
```bash
python -m pytest tests/test_dependencies.py tests/test_requirements.py -xvs
```
Expected: both tests pass.

- [ ] **Step 5: Run full suite**

Run:
```bash
python -m pytest tests/ -q 2>&1 | tail -5
```
Compare to `.tmp/phase0-baseline.txt`. Pass count must not drop. Abort if it does.

- [ ] **Step 6: Update CHANGELOG**

Edit `CHANGELOG.md` `## [Unreleased]` section, under `### Fixed`:
```
- deps: add missing `beautifulsoup4` to requirements.txt — `fed_collector` and CI importability tests were broken on clean deploys (#455)
```

- [ ] **Step 7: Commit**

```bash
git add requirements.txt tests/ CHANGELOG.md
git commit -m "$(cat <<'EOF'
fix(deps): add beautifulsoup4 to requirements.txt

fed_collector imports from bs4 but the dep was never declared,
breaking clean deploys and the CI importability test.

Fixes #455
EOF
)"
```

- [ ] **Step 8: Push**

```bash
git push -u origin fix/455-beautifulsoup4-dependency
```

- [ ] **Step 9: Open PR — NON-draft, NO merge**

```bash
gh pr create --base main --title "fix(deps): add beautifulsoup4 to requirements.txt" --body "<PR body template filled for #455>"
```
PR body uses template from Common section; note baseline pass count; include pytest tail.

### Task 13: Fix #460 — missing `scipy` and `numpy`

**Files:**
- Modify: `requirements.txt`
- Read: `.tmp/hotfix-plans/issue-460.md`

- [ ] **Step 1: Branch from main (not stacked)**

```bash
git checkout main
git checkout -b fix/460-scipy-numpy-dependency
```

- [ ] **Step 2: Apply fix**

Add two lines to `requirements.txt` in alpha order, using pins from `.tmp/hotfix-plans/issue-460.md`. E.g., `numpy>=1.26,<3` and `scipy>=1.11,<2` (real pins captured in Phase 1).

- [ ] **Step 3: Regression test**

Add to `tests/test_dependencies.py`:
```python
def test_scipy_importable():
    """Regression for #460."""
    import scipy  # noqa: F401

def test_numpy_importable():
    """Regression for #460."""
    import numpy  # noqa: F401
```

- [ ] **Step 4: Targeted test**

```bash
python -m pytest tests/test_dependencies.py -xvs
```

- [ ] **Step 5: Full suite + baseline compare** (as Task 12 Step 5)

- [ ] **Step 6: CHANGELOG entry**

```
- deps: add missing `scipy` and `numpy` to requirements.txt — clean deploys were crashing on first analytics import (#460)
```

- [ ] **Step 7: Commit**

```bash
git commit -am "fix(deps): add scipy and numpy to requirements.txt

Analytics modules import both but neither was declared,
breaking clean deploys.

Fixes #460"
```

- [ ] **Step 8: Push** `git push -u origin fix/460-scipy-numpy-dependency`

- [ ] **Step 9: Open PR NON-draft, NO merge**

### Task 14: Fix #462 — missing `pyarrow`

**Files:** `requirements.txt`; read `.tmp/hotfix-plans/issue-462.md`.

- [ ] **Step 1:** `git checkout main && git checkout -b fix/462-pyarrow-dependency`
- [ ] **Step 2:** Add `pyarrow>=<pin-from-plan>` line to `requirements.txt`.
- [ ] **Step 3:** Add `def test_pyarrow_importable(): import pyarrow` to `tests/test_dependencies.py`.
- [ ] **Step 4:** `python -m pytest tests/test_dependencies.py -xvs`
- [ ] **Step 5:** Full suite + baseline compare.
- [ ] **Step 6:** CHANGELOG: `- deps: add missing \`pyarrow\` to requirements.txt — simulation cache crashes on clean deploy (#462)`
- [ ] **Step 7:** `git commit -am "fix(deps): add pyarrow to requirements.txt\n\nSimulation cache loader uses pyarrow; declaring it prevents\ncrash on clean deploy.\n\nFixes #462"`
- [ ] **Step 8:** `git push -u origin fix/462-pyarrow-dependency`
- [ ] **Step 9:** Open PR NON-draft, NO merge.

### Task 15: Fix #436 — ImportError in bracket fallback leaves position unprotected

**Files:**
- Read: `.tmp/hotfix-plans/issue-436.md` (from Agent C)
- Modify: path(s) identified by Agent C; add regression test at `tests/trading/test_bracket_fallback.py` (or existing file per plan)

- [ ] **Step 1:** `git checkout main && git checkout -b fix/436-bracket-fallback-fail-closed`
- [ ] **Step 2:** Apply fix from `.tmp/hotfix-plans/issue-436.md`. Principle: fail-closed — if bracket submission raises ImportError (or any bracket-required-but-unavailable condition), abort entry and log CRITICAL. Do NOT leave position open without bracket.
- [ ] **Step 3:** Add regression test — mock bracket submission to raise ImportError, assert (a) position entry is cancelled or never submitted, (b) ERROR/CRITICAL log emitted, (c) no partial state in DB. Use mocks per CLAUDE.md (no real Alpaca calls).
- [ ] **Step 4:** `python -m pytest tests/trading/test_bracket_fallback.py -xvs`
- [ ] **Step 5:** Full suite + baseline compare.
- [ ] **Step 6:** CHANGELOG: `- executor: fail-closed on bracket fallback ImportError — positions are never left unprotected (#436)`
- [ ] **Step 7:** Commit `fix(executor): fail-closed on bracket fallback ImportError\n\n<body from hotfix-plan>\n\nFixes #436`
- [ ] **Step 8:** Push.
- [ ] **Step 9:** Open PR NON-draft, NO merge. PR body must include a **Risk assessment → Trading-safety impact** paragraph.

### Task 16: Fix #438 — risk governor allows any position size when equity == 0

**Files:**
- Read: `.tmp/hotfix-plans/issue-438.md`
- Modify: `src/risk/governor.py` (per Agent C plan)
- Test: `tests/test_governor_equity_zero.py` (new)

- [ ] **Step 1:** `git checkout main && git checkout -b fix/438-governor-equity-zero`
- [ ] **Step 2:** Apply fix from plan — fail-closed guard: if equity ≤ 0, reject trade with `GovernorRejection("equity_nonpositive")` and log CRITICAL. Do not silently permit.
- [ ] **Step 3:** Add regression test: mock account with `equity=0`, submit a trade intent, assert rejection + log message. Add equity=-1 case. Add equity=0.0 case. Add equity=1 positive case (sanity — should work).
- [ ] **Step 4:** Targeted: `python -m pytest tests/test_governor_equity_zero.py -xvs`
- [ ] **Step 5:** Full suite + baseline.
- [ ] **Step 6:** CHANGELOG: `- risk: governor now fail-closed on equity <= 0 (previously allowed any position size) (#438)`
- [ ] **Step 7:** Commit `fix(risk): fail-closed on equity <= 0`
- [ ] **Step 8:** Push.
- [ ] **Step 9:** Open PR NON-draft, NO merge. Risk assessment note: **CHANGE IN TRADING BEHAVIOR** — any operator running at equity=0 for diagnostic reasons will see trades blocked.

### Task 17: Fix #431 — reconciler backfill bypasses position-limit governor

**Files:**
- Read: `.tmp/hotfix-plans/issue-431.md`
- Modify: reconcile paths identified by Agent C (likely `src/shadow_trading/reconcile.py` or similar)
- Test: `tests/test_reconciler_backfill_governor.py` (new)

- [ ] **Step 1:** `git checkout main && git checkout -b fix/431-reconciler-backfill-governor`
- [ ] **Step 2:** Apply fix from plan — backfill path must gate through `governor.evaluate_position_limit()` before inserting. If limit exceeded, refuse and log WARNING with context.
- [ ] **Step 3:** Regression test: mock governor to reject, call backfill with a position that would push over limit, assert insert is skipped + log + metric increments if applicable.
- [ ] **Step 4:** Targeted.
- [ ] **Step 5:** Full suite + baseline.
- [ ] **Step 6:** CHANGELOG: `- reconcile: backfill path now runs through position-limit governor (#431)`
- [ ] **Step 7:** Commit.
- [ ] **Step 8:** Push.
- [ ] **Step 9:** PR NON-draft, NO merge.

### Task 18: Fix #439 — verify_auth silently disables auth on empty API_SECRET

**Files:**
- Read: `.tmp/hotfix-plans/issue-439.md`
- Modify: `src/api/cloud_app.py`
- Test: `tests/test_cloud_auth.py` (existing — per MASTER.md)

- [ ] **Step 1:** `git checkout main && git checkout -b fix/439-verify-auth-require-secret`
- [ ] **Step 2:** Apply fix from plan — raise on *startup* (not per-request) if `API_SECRET` env var is empty. Fail-closed. Existing startup should import a validator that raises `RuntimeError("API_SECRET must be set")` when empty.
- [ ] **Step 3:** Regression test: mock env with empty secret, assert startup raises. Existing test (per CLAUDE.md note "Tests must mock/patch a non-empty secret") confirms the happy path.
- [ ] **Step 4:** Targeted: `python -m pytest tests/test_cloud_auth.py -xvs`
- [ ] **Step 5:** Full suite + baseline.
- [ ] **Step 6:** CHANGELOG `### Security`: `- security: cloud_app fails closed on startup when API_SECRET is empty (previously silently disabled auth per-request) (#439)`
- [ ] **Step 7:** Commit `fix(security): fail-closed on empty API_SECRET at startup`
- [ ] **Step 8:** Push.
- [ ] **Step 9:** PR NON-draft, NO merge.

### Task 19: Fix #440 — bearer token timing attack

**Files:**
- Read: `.tmp/hotfix-plans/issue-440.md`
- Modify: `src/api/cloud_app.py`
- Test: `tests/test_cloud_auth.py` — add timing-safe comparison test

- [ ] **Step 1:** `git checkout main && git checkout -b fix/440-bearer-token-compare-digest`
- [ ] **Step 2:** Apply fix from plan — replace `==` with `hmac.compare_digest(expected, provided)` in the bearer-token comparison path. Ensure both args are `bytes` or both `str`; use `.encode("utf-8")` if needed.
- [ ] **Step 3:** Regression test: import the comparison helper, call with two equal-length strings, verify True; call with unequal-length strings, verify False; optionally parameterize to ensure timing-safe form is used (no regex-match on `==` in the source).
- [ ] **Step 4:** Targeted.
- [ ] **Step 5:** Full suite + baseline.
- [ ] **Step 6:** CHANGELOG `### Security`: `- security: bearer-token comparison uses hmac.compare_digest (timing-safe) (#440)`
- [ ] **Step 7:** Commit.
- [ ] **Step 8:** Push.
- [ ] **Step 9:** PR NON-draft, NO merge.

### Task 20: Fix #424 — bot-token leakage in telegram exception logging

**Files:**
- Read: `.tmp/hotfix-plans/issue-424.md`
- Modify: `src/notifications/telegram.py`
- Test: `tests/test_telegram_no_token_leak.py` (new)

- [ ] **Step 1:** `git checkout main && git checkout -b fix/424-redact-telegram-token`
- [ ] **Step 2:** Apply fix — in exception formatters, redact bot-token substrings using regex like `r'bot\d+:[A-Za-z0-9_-]{30,}'` → `bot<redacted>`. Also redact `TELEGRAM_BOT_TOKEN` env-var value on startup to avoid accidental dumps.
- [ ] **Step 3:** Regression test: mock an exception whose `str()` contains a fake token, call the exception formatter, assert the token is replaced with `<redacted>`.
- [ ] **Step 4:** Targeted.
- [ ] **Step 5:** Full suite + baseline.
- [ ] **Step 6:** CHANGELOG `### Security`: `- security: redact Telegram bot tokens from exception log output (#424)`
- [ ] **Step 7:** Commit.
- [ ] **Step 8:** Push.
- [ ] **Step 9:** PR NON-draft, NO merge.

### Task 21: Fix #413 — unsafe cache deserialization in data_enrichment

**Files:**
- Read: `.tmp/hotfix-plans/issue-413.md`
- Modify: files identified by Agent A (likely `src/data_enrichment/cache.py` or similar)
- Test: `tests/test_data_enrichment_cache_safe.py` (new)

- [ ] **Step 1:** `git checkout main && git checkout -b fix/413-data-enrichment-safe-cache`
- [ ] **Step 2:** Apply fix — migrate cache loader from the unsafe format to JSON (preferred) or add HMAC signature verification before deserialize, per plan. Prefer JSON unless the cached objects are non-JSON-serializable (e.g. numpy arrays), in which case use a class-allowlisted safe deserializer.
- [ ] **Step 3:** Regression test: write a cache file with a malicious payload (an arbitrary-code reducer constructed by the test itself), call the loader, assert it raises before executing.
- [ ] **Step 4:** Targeted.
- [ ] **Step 5:** Full suite + baseline. **Note:** existing on-disk caches may be invalidated; first post-deploy run takes longer. Flag in PR body.
- [ ] **Step 6:** CHANGELOG `### Security`: `- security: data_enrichment cache uses safe serialization (#413)`
- [ ] **Step 7:** Commit.
- [ ] **Step 8:** Push.
- [ ] **Step 9:** PR NON-draft, NO merge. PR body must note cache invalidation.

### Task 22: Fix #459 — unsafe cache deserialization in training/historical_data

**Files:** analogous to Task 21 but for `src/training/historical_data.py`; read `.tmp/hotfix-plans/issue-459.md`.

- [ ] **Step 1:** `git checkout main && git checkout -b fix/459-training-cache-safe`
- [ ] **Step 2:** Apply fix per plan (same strategy choice as #413).
- [ ] **Step 3:** Regression test analogous to Task 21 Step 3, targeting the training cache path.
- [ ] **Step 4–5:** Targeted + full suite + baseline.
- [ ] **Step 6:** CHANGELOG `### Security`: `- security: training historical-data cache uses safe serialization (#459)`
- [ ] **Step 7–9:** Commit, push, PR NON-draft NO merge; note cache invalidation.

### Task 23: Fix #434 — circular import startup.py ↔ startup_checks.py

**Files:**
- Read: `.tmp/hotfix-plans/issue-434.md` (from Agent B)
- Modify: `src/startup.py` and/or `src/startup_checks.py` per plan
- Test: `tests/test_startup_import_order.py` (new)

- [ ] **Step 1:** `git checkout main && git checkout -b fix/434-startup-circular-import`
- [ ] **Step 2:** Apply fix per plan — lazy-import one edge of the cycle (inside a function body) or move a type-only reference behind `TYPE_CHECKING`. Do NOT extract an interface unless the plan specifies (that's #461's scope).
- [ ] **Step 3:** Regression test — `python -c "import src.startup; import src.startup_checks"` exits 0. Write as pytest using `subprocess.run`.
- [ ] **Step 4:** Targeted.
- [ ] **Step 5:** Full suite + baseline. Also run: `python -m src.main startup --check-only` to smoke-test import path (per spec Appendix C).
- [ ] **Step 6:** CHANGELOG `### Fixed`: `- startup: break circular import between startup.py and startup_checks.py (#434)`
- [ ] **Step 7:** Commit.
- [ ] **Step 8:** Push.
- [ ] **Step 9:** PR NON-draft, NO merge.

### Task 24: Fix #435 — failing test_coerce_to_schema

**Files:**
- Read: `.tmp/hotfix-plans/issue-435.md`
- Modify: `tests/test_coerce_to_schema.py` (or the source-of-truth schema if the test was right and registry drifted — Agent's call)

- [ ] **Step 1:** `git checkout main && git checkout -b fix/435-coerce-to-schema-test`
- [ ] **Step 2:** Apply fix — plan should specify whether test or source is wrong. Default: `planned_shares` was correctly changed INTEGER→REAL in the registry, so update test fixture to use a REAL value (e.g. `100.0` instead of `100`).
- [ ] **Step 3:** No new test needed — this IS a test fix.
- [ ] **Step 4:** Targeted: `python -m pytest tests/test_coerce_to_schema.py -xvs` — must go from FAIL to PASS.
- [ ] **Step 5:** Full suite + baseline. Pass count should *rise* by the number of now-passing tests.
- [ ] **Step 6:** CHANGELOG `### Fixed`: `- tests: update test_coerce_to_schema to match planned_shares INTEGER→REAL schema change (#435)`
- [ ] **Step 7:** Commit `fix(tests): update test_coerce_to_schema for planned_shares REAL`
- [ ] **Step 8:** Push.
- [ ] **Step 9:** PR NON-draft, NO merge.

### Task 25: Fix #456 — `cloud_routes/trades.py` over 400-line CI limit

**Files:**
- Read: `.tmp/hotfix-plans/issue-456.md`
- Modify: `src/api/cloud_routes/trades.py`
- Create: `src/api/cloud_routes/_trades_helpers.py` (or similar per plan)

- [ ] **Step 1:** `git checkout main && git checkout -b fix/456-trades-extract-helpers`
- [ ] **Step 2:** Apply fix per plan — extract cohesive helper(s) into new module. Target `trades.py` line count <400. Preserve public route surface (imports + route decorators unchanged).
- [ ] **Step 3:** No functional change — existing route tests guard behavior. Add a test that the new helper module is importable and the key helper(s) are exported.
- [ ] **Step 4:** Targeted: run existing `tests/test_cloud_*.py` for trades routes.
- [ ] **Step 5:** Full suite + baseline. Also run `tests/test_repo_structure.py` — the file-size guard test must now pass.
- [ ] **Step 6:** CHANGELOG `### Changed`: `- ci: extract helpers from cloud_routes/trades.py to satisfy 400-line CI limit (#456)`
- [ ] **Step 7:** Commit `fix(ci): extract helpers from cloud_routes/trades.py`
- [ ] **Step 8:** Push.
- [ ] **Step 9:** PR NON-draft, NO merge.

### Task 26: Fix #457 — `_check_render_postgres` over 60-line CI limit

**Files:**
- Read: `.tmp/hotfix-plans/issue-457.md`
- Modify: `src/startup_checks.py`

- [ ] **Step 1:** `git checkout main && git checkout -b fix/457-startup-checks-extract-helper`
  *If Task 23 (#434) touched `startup_checks.py` and is not yet merged, stack this branch on `fix/434-…` instead and `gh pr create --base fix/434-…`.*
- [ ] **Step 2:** Apply fix per plan — extract inner block of `_check_render_postgres` into private helper `_probe_render_postgres_connection` (or similar). Target function body <60 lines.
- [ ] **Step 3:** Existing `test_startup.py` guards behavior; no new test unless plan specifies.
- [ ] **Step 4:** Targeted: `tests/test_startup.py` + any `test_startup_checks*.py`.
- [ ] **Step 5:** Full suite + baseline. `test_repo_structure.py` function-length guard now passes for this function.
- [ ] **Step 6:** CHANGELOG `### Changed`: `- ci: extract helper from startup_checks._check_render_postgres to satisfy 60-line CI limit (#457)`
- [ ] **Step 7:** Commit.
- [ ] **Step 8:** Push.
- [ ] **Step 9:** PR NON-draft, NO merge. Note stacked-on relationship in body if stacked.

### Task 27: Fix #461 — three undocumented circular imports

**Files:**
- Read: `.tmp/hotfix-plans/issue-461.md` (from Agent B — has 2 cycles remaining after #434 fixed)
- Modify: per plan

- [ ] **Step 1:** `git checkout main && git checkout -b fix/461-document-and-break-cycles`
  *If Tasks 23 or 26 touched overlapping files and are not merged, stack accordingly.*
- [ ] **Step 2:** Apply fix per plan — for each of the remaining 2 cycles, either break or document. Prefer break. If an extraction is required, keep it minimal and single-purpose.
- [ ] **Step 3:** Regression test: one import-order test per cycle (`python -c "import src.<A>"` exits 0) as subprocess-pytest per Task 23 Step 3.
- [ ] **Step 4:** Targeted.
- [ ] **Step 5:** Full suite + baseline.
- [ ] **Step 6:** CHANGELOG `### Fixed`: `- architecture: break two undocumented circular imports (#461)`
- [ ] **Step 7:** Commit.
- [ ] **Step 8:** Push.
- [ ] **Step 9:** PR NON-draft, NO merge.

### Tasks 28+: New issues from Phase 2 — one task per filed issue

**Template for each new-issue task** (fill in per issue):

- Branch: `fix/<N>-<kebab>`
- Plan source: `.tmp/hotfix-plans/issue-<N>.md` (created by me in Phase 2 during issue filing)
- Steps: identical 9-step shape above; concrete content per plan.
- Inserted into the queue at the appropriate tier based on severity label.

---

## Phase 4 — Summary report

### Task N+1: Generate Phase 4 summary

**Files:**
- Create: `docs/superpowers/reports/2026-04-17-hotfix-pipeline-summary.md`

- [ ] **Step 1: Open PR links**

For each PR opened in Phase 3, collect: branch, base, issue #, key files changed, test delta (from its PR body), stacked-on relationship. Tabulate.

- [ ] **Step 2: Deferred items list**

Any issues we investigated but did NOT open a PR for (e.g. needed schema change + operator-initiated Postgres migration). Write why.

- [ ] **Step 3: Log findings already remediated**

From `.tmp/phase2-candidates.md` entries classified `already-fixed`. List with fix-commit SHAs.

- [ ] **Step 4: Top-10 log noise report**

From `.tmp/phase1-log-findings.md`, the top-10 highest-volume non-filed clusters. Informational.

- [ ] **Step 5: Protocol deviations**

If the pipeline diverged from the spec at any point, note each deviation with rationale.

- [ ] **Step 6: Verify `main` integrity**

Run:
```bash
git checkout main && git status && git log --oneline -5
python -m pytest tests/ -q 2>&1 | tail -5
```
Pass count on `main` must equal Phase 0 baseline (nothing landed on main; we only created branches).

- [ ] **Step 7: Write summary to `docs/superpowers/reports/2026-04-17-hotfix-pipeline-summary.md`**

Use markdown with sections: Summary stats, PRs opened, Issues filed, Deferred items, Already-remediated, Log noise top-10, Protocol deviations. Commit locally with `docs: hotfix pipeline summary 2026-04-17`. Do NOT push (matches user's "local only" directive).

- [ ] **Step 8: Clean up `.tmp/`**

Run:
```bash
rm -rf .tmp/
```
Ephemeral-only; nothing of value should be in there that isn't captured in the summary or PRs.

- [ ] **Step 9: Report to operator**

Post a concise in-chat summary:
- N PRs opened
- M new issues filed
- K log findings already remediated
- Any anomalies or deferrals requiring attention

---

## Abort conditions (apply to any task)

Stop the pipeline and surface to operator if:
- Phase 0 baseline shows pass count < 1339 (something is already broken on main)
- Any full-suite pytest run in Phase 3 drops pass count vs baseline — do NOT push, do NOT force-commit
- `git status` shows unexpected changes I didn't make
- An agent returns a "fix" that would require modifying `config/settings.local.yaml`, `.env`, or bypassing the risk governor
- A schema change is required but would need an immediate Postgres migration (operator-initiated, not automation)

On abort: record the reason in `.tmp/pipeline-state.md` under `## Aborts`, leave all branches in their current state (no deletion), do not force-push, and surface to operator with next-step recommendation.
