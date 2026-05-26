# git-historian — Golden-Question Regression Tests

Reference file for `arcis:skill-audit` (#111) and manual operator regression.
Each golden question documents the expected DYNAMIC CONTEXT shape and expected
response shape. These are NOT runtime pass/fail tests — LLM variability makes
exact-match infeasible. Use for visual diff after any agent-prompt or git CLI
interface change. When #107 GitArchaeology lands, re-run all 4 goldens after
the prompt's git invocations refactor to `python -m src.tools.gitarchaeology`.

See spec §6.3 (4 questions) and §6.5 (format rules).

---

## Golden Question 1 — Who last touched reconcile_live_trades

### Question prose

"Who last modified `reconcile_live_trades` and what PR introduced the change?"

### Expected DYNAMIC CONTEXT shape

```
MANDATE: Who last modified the function reconcile_live_trades and what PR
introduced that modification?
TARGET_SYMBOL: reconcile_live_trades
```

Required fields: `MANDATE`.
Optional fields: `TARGET_SYMBOL` (narrows locus resolution; expected present
here), `WORKTREE_PATH` (DA1 opt-in), `VERSION_RANGE`, `PATH_FILTER`.

### Expected response shape

`<git_report>` JSON must contain:

- `target_symbol`: resolved `file:line` (e.g.,
  `src/reconciler/live_trades.py:47`).
- `findings[]` — at minimum one entry with:
  - `commit_sha`: 40-char SHA of the last commit touching the function.
  - `author`: name of the committing author.
  - `date`: ISO-8601 date.
  - `pr_number`: `"#NNN"` parsed from the commit subject (or `null` if not
    determinable).
  - `citation`: `file:line` of the function definition.
  - `description`: summary of what the commit changed, truncated to ≤200
    chars if needed ` [truncated]`.
  - `severity`: `"informational"` for an ordinary last-touch finding; `"anomaly"`
    or `"must_fix"` if the commit introduced a known defect pattern.
- `tool_invocations[]` — must show in order:
  1. `symbolfind reconcile_live_trades --kind def` (timeout 60000) — locus
     resolution.
  2. `git blame -L <start>,<end> -- <file>` (timeout 60000) — commit SHA
     extraction.
  3. `git log --format='%H %ai %an %s' -- <file>` (timeout 60000) — log walk.
  4. `git show --stat <SHA>` + `git show <SHA> -- <file>` (timeout 60000 each).
  5. `prcomments read <PR_NUMBER>` if a `(#NNN)` reference found (timeout
     60000).
- `sibling_search_results[]` — if a defect pattern is found in the commit,
  shows grep for the same anti-pattern at other lines in the same file.
- `coverage_assessment` — REQUIRED (DA6): `mode_used: "n/a"`,
  `tool_invocations_used`: integer, `coverage_judgment: "complete"` when
  author + PR both identified.

### Negative checks

- MUST NOT call `git commit`, `git push`, `git reset`, `git rebase`,
  `git checkout --`, `git branch -D`, `git clean -f`, `git bisect run`, or any
  other mutating git operation (DA constraint enumerated in git-historian
  CONSTRAINTS).
- MUST NOT call `prcomments post` — read-only PR access only.
- MUST NOT contain hardcoded `C:/arcis/halcyon-lab` (DA1).
- MUST NOT show any Bash invocation without explicit `timeout` (DA2).
- If `symbolfind` returns zero hits for `reconcile_live_trades`, that MUST
  appear as an `informational` finding with abort of downstream steps (DA3).
- Commit-message bodies or diff hunks > 200 chars MUST appear truncated with
  ` [truncated]` (DA5).
- `coverage_assessment` MUST be present and non-null (DA6).
- MUST NOT suppress or retry tool failures silently.

---

## Golden Question 2 — Bisect-shaped root-cause for sync_time_column defect

### Question prose

"Find the commit that introduced the `sync_time_column=None` defect on
`live_prices`."

### Expected DYNAMIC CONTEXT shape

```
MANDATE: Find the specific commit that introduced sync_time_column=None for the
live_prices table in src/schema/registry.py. Use bisect-shaped logic across the
git history.
TARGET_SYMBOL: live_prices
PATH_FILTER: src/schema/registry.py
```

Required fields: `MANDATE`.
Optional fields: `TARGET_SYMBOL`, `PATH_FILTER` (expected present to narrow
the blame/log pass), `WORKTREE_PATH` (DA1 opt-in), `VERSION_RANGE`.

### Expected response shape

`<git_report>` JSON must contain:

- `bisect_result`: non-null when the mandate is an "introduced by" question:
  - `introducing_commit`: the 40-char SHA that first set `sync_time_column=None`
    for `live_prices`.
  - `introducing_pr`: `"#NNN"` or `null` if commit was not tied to a PR.
  - `first_clean_commit`: the last SHA where `live_prices` had a valid
    `sync_time_column` (immediately before the introducing commit in the range).
- `findings[]` — at minimum one entry with `severity: "must_fix"` (a
  `sync_time_column=None` on a synced table breaks freshness checks).
  `citation`: `src/schema/registry.py:<line>`.
- `tool_invocations[]` — bisect-shaped narrowing (Workflow Step 7) must appear:
  - `git log --reverse --before=<END> --after=<START> -- src/schema/registry.py`
    (timeout 60000) to enumerate candidates.
  - `git show <SHA> -- src/schema/registry.py` for each candidate (timeout
    60000).
  - Bisect-shaped narrowing does NOT use `git bisect run` — see negative checks.
- `sibling_search_results[]` — after finding the introducing commit, grep
  `src/schema/registry.py` for other `sync_time_column=None` entries to catch
  sibling defects (sibling-search discipline).
- `coverage_assessment` — `coverage_judgment: "complete"` when introducing
  commit identified; `"partial"` if range is narrowed but the exact commit
  is within a large range still un-inspected.

### Negative checks

- Same universal negatives as GQ1.
- MUST NOT use `git bisect run` (mutating; enumerated forbidden op).
- MUST NOT use `git checkout <SHA>` to inspect a historical commit — use
  `git show <SHA>` exclusively.
- `bisect_result` MUST NOT be `null` when the mandate is an "introduced by"
  question — if the bisect is incomplete, `coverage_judgment` must be
  `"partial"` and `gaps_unresolved[]` must explain what remains.
- If `PATH_FILTER` is provided, the log walk MUST be scoped to that path —
  do not walk the entire commit history.

---

## Golden Question 3 — Version-range diff in src/scheduler/watch.py

### Question prose

"What changed in `src/scheduler/watch.py` between v0.36.50 and v0.36.55?"

### Expected DYNAMIC CONTEXT shape

```
MANDATE: Show all changes to src/scheduler/watch.py between git tags v0.36.50
and v0.36.55. Summarize what each commit changed and why.
VERSION_RANGE: v0.36.50..v0.36.55
PATH_FILTER: src/scheduler/watch.py
```

Required fields: `MANDATE`.
Optional fields: `VERSION_RANGE` (expected present), `PATH_FILTER` (expected
present), `WORKTREE_PATH` (DA1 opt-in), `TARGET_SYMBOL`.

### Expected response shape

`<git_report>` JSON must contain:

- `findings[]` — one entry per commit in the range that touched
  `src/scheduler/watch.py`:
  - `commit_sha`, `author`, `date`, `pr_number`, `citation` (file:line of the
    changed function/section), `description` (≤200 chars ` [truncated]`).
  - `severity: "informational"` for routine changes; `"anomaly"` if a revert-
    and-reintroduce pattern is detected.
- Empty log case: if no commits touched `watch.py` in that range, one
  `informational` finding with evidence of the empty log command result (DA3).
- `tool_invocations[]` — must include:
  1. `git log --format='%H %ai %an %s' v0.36.50..v0.36.55 -- src/scheduler/watch.py`
     (single-quoted format string per §2.3.1; timeout 60000).
  2. `git show <SHA> -- src/scheduler/watch.py` for each candidate (timeout
     60000 each; diff hunks > 200 chars truncated per DA5).
  3. `prcomments read <PR>` for any `(#NNN)` references found (timeout 60000).
- `bisect_result`: null (version-range diff is not a "find introducing commit"
  question; `bisect_result` is only applicable to GQ2-type questions).
- `coverage_assessment` — `coverage_judgment: "complete"` when all commits in
  the range inspected and summarized.

### Negative checks

- Same universal negatives as GQ1.
- `bisect_result` MUST be `null` (or have all fields `null`) for a range-diff
  question — it is not applicable here.
- Git format strings MUST be single-quoted in the Bash invocation (§2.3.1).
- If version tags `v0.36.50` or `v0.36.55` do not exist in the repo, the agent
  MUST surface the `git log` exit-code failure verbatim (anti-handwave, DA2
  timeout_exceeded handling) — not silently return an empty findings array.

---

## Golden Question 4 — Agent-provenance PR-rescue commit audit

### Question prose

"For the last 5 PR-rescue commits with `agent-` provenance, list the rescued-
agent session IDs."

### Expected DYNAMIC CONTEXT shape

```
MANDATE: Find the last 5 git commits whose commit messages reference
agent-provenance worktrees (pattern: "agent-" in the branch name or commit
body). Extract the rescued-agent session identifiers from those commits.
```

Required fields: `MANDATE`.
Optional fields: `WORKTREE_PATH` (DA1 opt-in). No `TARGET_SYMBOL` or
`VERSION_RANGE` expected — the mandate is a log-search pattern.

### Expected response shape

`<git_report>` JSON must contain:

- `findings[]` — up to 5 entries matching the `agent-` provenance pattern:
  - `commit_sha`, `author`, `date`, `citation` (file path or null for commit-
    level findings), `description` (extracted session ID or summary; ≤200
    chars ` [truncated]`).
  - `pr_number`: from commit subject if present, else `null`.
  - `severity: "informational"` for routine agent-rescue commits.
- If fewer than 5 such commits exist: surface however many are found as
  findings, plus an `informational` finding noting the total found vs requested
  (DA3 empty-collection discipline applied proportionally).
- `tool_invocations[]` — must include:
  - `git log --format='%H %ai %an %s' --grep='agent-'` or equivalent
    (single-quoted format string; timeout 60000) — the primary pattern search.
  - `git show <SHA>` for each candidate to extract the session ID from the
    commit body (timeout 60000 each; bodies > 200 chars truncated per DA5).
- `bisect_result`: null (not an "introduced by" question).
- `sibling_search_results[]` — if a session ID pattern is found in one commit,
  grep remaining log for the same ID to confirm single-rescue vs multi-rescue
  sessions (sibling-search discipline).
- `coverage_assessment` — `coverage_judgment: "complete"` when 5 commits found
  and session IDs extracted; `"partial"` if the git log search found fewer than
  5 and the scope is genuinely exhausted.

### Negative checks

- Same universal negatives as GQ1.
- MUST NOT use `git commit`, `git push`, or any other mutating op.
- MUST NOT call `prcomments post`.
- If the `--grep='agent-'` log search returns zero results, that MUST appear
  as an `informational` finding (DA3) — not a silent empty `findings[]`.
- Commit bodies > 200 chars MUST appear truncated with ` [truncated]` (DA5).
- `coverage_assessment` MUST be present and `coverage_judgment` MUST reflect
  whether the full 5-commit mandate was satisfied.
