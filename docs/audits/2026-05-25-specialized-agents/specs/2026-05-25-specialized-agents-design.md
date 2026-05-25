# Arcis #108 Specialized Agents — Design Spec

**Status:** Design pass 3 (post-devils-advocate revision)
**Target release:** Docs-only PR — NO version bump (auto-discovery; no plugin.json change)
**Estimated effort:** ~0.5 day agent work + dual-Opus QA
**Inherits:** #103 boundary-touch + sibling-search discipline; #105 Tier 1 tools (DBQuery, LogTail, CIInvestigate, SymbolFind, TradingState); #106 Tier 2 tools (ProcessManager, HealthProbe, PRComments, CapabilityRegistryQuery, TestPatternScan); `_cli_envelope.py` JSON-envelope contract; `agent-conventions.md` 5-section structure.

**Revision log (pass 2):** Addresses feasibility review FB1 (OUTPUT FORMAT registered-enum addendum + DD-11), FB2 (stdin-pipe pattern replacing temp-file), FB3 (Bash shell-quoting convention), FB4 (§9.1 symbolic citations), FB5 (live-monitor ET clock Step 0), FB6 (`comment_url` field rename), FB7 (Task 6 smoke-test framing).

**Revision log (pass 3 — devils-advocate):** Addresses DA1 (worktree-portable cwd via `git rev-parse --show-toplevel` + optional `WORKTREE_PATH` DYNAMIC CONTEXT — replaces hardcoded `cd C:/arcis/halcyon-lab`), DA2 (mandatory per-call Bash `timeout` parameter with tiered defaults: 60000/90000/120000ms), DA3 (empty-result convention — empty primary collection classified as `informational` severity, never silently dropped), DA4 (ci-investigator repost-idempotency via SHA-256 fingerprint footer + `ALLOW_REPOST` toggle + `skipped_duplicate` post_status), DA5 (JSONB/TEXT-column redaction at agent layer — truncate `*_jsonb`/`*_detail`/`*_payload`/`*_body` to ≤200 chars + `[truncated]` marker), DA6 (turn-50 budget-stop with `coverage_assessment` field on ALL 4 agents).

---

## 1. Overview

#108 ships **4 specialized investigator agents** as markdown system prompts under `.claude/plugins/arcis/agents/`, auto-discovered by Claude Code. The 4 agents are first-in-class consumers of the 10-tool Tier 1+2 surface (#105+#106) via Bash subprocess invocation, parsing the shared `_cli_envelope.py` JSON envelope contract.

| Agent | Read/Write | Composes (Bash) | Routing trigger |
|---|---|---|---|
| **db-investigator** | READ-ONLY | DBQuery + CapabilityRegistryQuery + SymbolFind + LogTail | DB anomaly / schema archaeology / table-ownership / corruption forensics |
| **ci-investigator** | CAN MUTATE (PRComments.post, hard-scoped, repost-idempotent) | CIInvestigate + PRComments + SymbolFind + LogTail | PR red, flaky-vs-real, mock-target drift, forensic PR summary |
| **git-historian** | READ-ONLY (git CLI only, no commits/push) | git CLI direct + SymbolFind + PRComments(read) | who-touched-what, bisect-shaped root-cause, version-range diffs |
| **live-monitor** | READ-ONLY observation (no restarts) | ProcessManager.status + HealthProbe + LogTail + TradingState + CIInvestigate | live incident snapshot, watch-loop wedged, ollama unhealthy, training not firing |

### 1.1 Role in the broader roadmap

#108 is **substrate**, not endpoint:

- **#109 `arcis:operate`** will orchestrate db-investigator + live-monitor + ci-investigator for live-system incident response, ADDING ProcessManager.restart (the mutating surface live-monitor is explicitly forbidden from touching).
- **#110 `arcis:strategy`** will orchestrate db-investigator + git-historian for trading-strategy ideation + backtest analysis.
- **#111 periodic discipline** will run `arcis:skill-audit` which exercises golden-question regression tests against these 4 agents nightly.

The boundary between #108 (observe + advise) and #109 (mutate the live system) is **enforced at the agent-prompt level** via per-agent forbidden-method enumeration — NOT just `allowed-tools` frontmatter restrictions, which can be subverted via composed Bash invocations.

### 1.2 Why bare naming (deviation from precedent)

The 19 existing agents use prefixed names: `coding-*`, `design-*`, `research-*`, `roast-*`. Per `agent-conventions.md` §Naming, the prefix is to prevent collisions when agents are skill-scoped.

The 4 new agents are **NOT skill-scoped** — they are general-purpose investigators consumed by multiple future skills (#109, #110, #111) AND directly by the operator. Truly bare names (`db-investigator.md` → `name: db-investigator`) signal this cross-skill ownership. Documented as DD-1; the conventions doc gets a §Naming addendum in Task 1 to formalize the "investigator-class" exception.

---

## 2. Architecture

### 2.1 File tree (delta from current `.claude/plugins/arcis/`)

```
.claude/plugins/arcis/
  agents/
    coding-*.md                  (UNCHANGED — 8 existing)
    design-*.md                  (UNCHANGED — 4 existing)
    research-*.md, roast-*.md, etc.  (UNCHANGED — 7 existing)
    db-investigator.md           (NEW)
    ci-investigator.md           (NEW)
    git-historian.md             (NEW)
    live-monitor.md              (NEW)
  docs/
    agent-conventions.md         (MODIFIED — §Naming + §maxTurns + §Bash-subprocess + §5 OUTPUT FORMAT + §Cross-cutting-conventions addenda)
    agent-tests/                 (NEW DIRECTORY)
      db-investigator-golden.md       (NEW)
      ci-investigator-golden.md       (NEW)
      git-historian-golden.md         (NEW)
      live-monitor-golden.md          (NEW)
    superpowers/                 (UNCHANGED)

CHANGELOG.md                     (MODIFIED — [Unreleased] entry; no version bump)
```

**Net new files: 9 (4 agents + 4 goldens + new agent-tests directory). Modified: 2 (conventions + CHANGELOG). No code changes. No plugin.json (auto-discovery).**

### 2.2 Auto-discovery + no plugin.json update

Verified by surface report Phase 2: ARCIS plugin uses auto-discovery (no manifest file lists individual agents). Dropping `<agent>.md` into `.claude/plugins/arcis/agents/` makes the agent invocable as `Task(subagent_type='<name>')` immediately. No version bump required, no plugin.json edit.

### 2.3 Bash subprocess tool-invocation contract (first-in-class)

All 4 agents invoke Tier 1+2 tools EXCLUSIVELY via Bash subprocess. The contract has SIX cross-cutting rules — every agent's CONSTRAINTS section mirrors these verbatim (Task 6 lints for drift):

**Canonical invocation pattern (worktree-portable, DA1):**

```bash
cd "$(git rev-parse --show-toplevel)" && python -m src.tools.<name> --json [args]
```

#### 2.3.0 Cross-cutting conventions (the 6 rules — appended to agent-conventions.md as §Cross-cutting-conventions)

**(A) DA1 — Worktree-portable cwd (NEVER hardcode the operator's path).**

- Bash invocations MUST resolve the repo root via `cd "$(git rev-parse --show-toplevel)"`. The operator regularly dispatches agents from `.claude/worktrees/` sub-directories (per operator memory: agent worktree accumulation + agent worktree base default + worktree env drift). Hardcoding `C:/arcis/halcyon-lab` breaks every invocation from a worktree and yields silent `ModuleNotFoundError: No module named src` failures that mimic tool-missing.
- An agent MAY receive `WORKTREE_PATH: <abs path>` in DYNAMIC CONTEXT — when present, prefer `cd "$WORKTREE_PATH"` over `git rev-parse` (the latter requires a `.git` directory, which is missing in some sparse-checkout / detached worktree shapes). `WORKTREE_PATH` is optional; absence falls back to `git rev-parse`.
- The agent prompts encode both forms; Task 6 grep-asserts NO occurrence of literal `cd C:/arcis/halcyon-lab` in any of the 4 agent files (this is the lint failure signal).

**(B) DA2 — Explicit per-call Bash `timeout` parameter (NEVER rely on the 120s default).**

- Every Bash subprocess invocation MUST include an explicit `timeout` parameter (milliseconds). Tiered defaults:
  - **60000 ms (60s)** — `dbquery` SELECTs, `symbolfind`, `capabilityregistry`, `prcomments read/post`, `processmanager status`, `tradingstate`, `healthprobe`, git read-only ops (`log`/`blame`/`show`/`diff`).
  - **90000 ms (90s)** — `logtail` against multi-MB logs (the operator's `arcis.log` regularly sits at 5-20 MB).
  - **120000 ms (120s)** — `ciinvestigate` against an uncached `run_id` (network fetch + cache-warm).
- An agent MAY override the tier (e.g., `dbquery` against a long-running JOIN may need 120s) — the override MUST be inline in the agent's TASK Workflow step and justified in `<reasoning>`. Implicit reliance on the Bash tool's 120s default is FORBIDDEN — Task 6 grep-asserts every Bash invocation in agent files carries an explicit `timeout` argument.
- Rationale: a single tool subprocess hitting the implicit 120s ceiling consumes 1/60 of the per-agent turn budget — and unbounded waits inside investigators cascade into operator session lockup.

**(C) DA3 — Empty-result convention (NEVER silently drop the case).**

- When a tool returns an EMPTY primary collection (zero rows from `dbquery`, zero files from `symbolfind`, zero lines from `logtail --grep`, zero failed jobs from `ciinvestigate`, etc.), the agent MUST classify this as an `informational` finding in OUTPUT FORMAT — NOT omit the finding entirely.
- The finding's `evidence` field documents the exact subprocess invocation (argv) and the empty-payload envelope. The `recommendation` field is typically "no action needed" but the audit-trail entry is non-negotiable.
- This is the anti-handwave discipline (#103) applied at the empty-result boundary: a silent absence is indistinguishable from a tool subprocess that bypassed parsing. Surface the absence honestly.
- Severity hierarchy: `informational` < `anomaly` < `must_fix`. Empty results are always `informational` UNLESS the empty result IS the anomaly (e.g., expected non-empty registry returning zero tables → classify as `anomaly`).

**(D) DA5 — JSONB / TEXT redaction at the agent layer (truncate to ≤200 chars + `[truncated]` marker).**

- The Tier 1+2 tools faithfully return whatever JSONB / TEXT payload the DB or process emits. Agents MUST NOT echo full JSONB / TEXT column values into `<reasoning>` or OUTPUT FORMAT bodies. Concretely, every column whose name matches the patterns `*_jsonb`, `*_detail`, `*_payload`, `*_body`, OR has a serialized representation > 200 characters, MUST be truncated to the first 200 chars with the literal suffix ` [truncated]` appended.
- The full value MAY be retained in the agent's transient working memory for analysis; only the SURFACED rendering (in reports, in cited evidence, in PRComments bodies) is truncated.
- Rationale: (a) prevents bloating turn budgets with multi-KB payloads, (b) reduces secret-bleed surface area (operator's `audit_reports.findings_jsonb` regularly contains transient secrets that PRComments' pre-flight catches but agents shouldn't echo upstream), (c) keeps PRComments-posted bodies legible.
- Task 2 grep-lint: each of the 4 agents' CONSTRAINTS section MUST contain the literal string `[truncated]` and reference the 200-char ceiling.

**(E) DA6 — Turn-50 budget-stop with `coverage_assessment` field.**

- Every agent's `maxTurns` is 60. The agent MUST gracefully exit at turn 50, leaving 10 turns headroom for composing OUTPUT FORMAT JSON + final `<reasoning>`. The exit condition: at turn 50 the agent STOPS issuing new tool invocations, finalizes findings from data already collected, and populates `coverage_assessment` honestly.
- `coverage_assessment` is a REQUIRED field on ALL FOUR investigator-class OUTPUT FORMATs (previously only db-investigator carried it). Schema:
  - `mode_used`: `surface` | `deep` (echoes input where applicable; `n/a` for ci-investigator + git-historian which don't have modes).
  - `tool_invocations_used`: integer.
  - `tool_invocations_budget_remaining`: integer (60 − used; agents MUST NOT lie here).
  - `coverage_judgment`: `complete` (mandate fully answered) | `partial` (mandate partially answered; remaining gaps documented) | `incomplete` (budget exhausted before reaching mandate's core question).
  - `gaps_unresolved[]`: array of strings — each describing a sub-question the agent did NOT answer + why (budget / tool failure / out of scope).
- Rationale: investigators that hit `maxTurns: 60` mid-tool-call produce truncated OUTPUT FORMAT JSON that cannot be parsed by callers. The 50/60 budget-stop guarantees parseable output even on the most expensive investigations.
- Task 6 grep-lint: every agent's OUTPUT FORMAT section MUST mention `coverage_assessment` AND the workflow MUST mention the turn-50 budget-stop.

**(F) Subprocess discipline (FB2 + FB3 inherited).**

- `--json` MANDATORY for every tool invocation. Agents always parse the JSON envelope; markdown-mode output is human-only and not for agent consumption.
- **Stdout JSON envelope** (per `src/tools/_cli_envelope.py` — see `cli_envelope()` and the success/error helpers):
  - Success: tool emits its primary payload (JSON array/object) to stdout, exit code 0.
  - Failure: envelope `{"error": {"type": "<ExceptionClassName>", "message": "<sanitize_error(e)>", "tool": "<tool_name>"}}` to stdout, exit code 1.
- **Exit-code handling:**
  - 0 → parse stdout as the tool's payload schema.
  - 1 → parse stdout as envelope; extract `error.type` + `error.message`. Surface honestly in the agent's report (NEVER suppress or retry blindly).
  - subprocess crash / non-1 non-0 / JSON parse failure / Bash `timeout` exceeded → report "<tool> subprocess crashed: <exit_code> + <stderr_excerpt>" verbatim. Timeout failures specifically carry the `timeout_exceeded` marker so callers can distinguish from tool-internal errors.
- **No shell=True equivalent.** Agents construct argv as an array — no string-interpolation of user-controlled values into the command line.

#### 2.3.1 Shell-quoting convention for embedded SQL / regex / payload strings (FB3)

The Bash tool here is the bash shell — Bash tool calls are command STRINGS, not argv arrays. When embedding SQL, regex, or other payloads as positional arguments, **single-quote** them so bash preserves literal `$`, `<`, `>`, `*`, `?`, `&`, `|`, parentheses, and backticks:

```bash
cd "$(git rev-parse --show-toplevel)" && python -m src.tools.dbquery 'SELECT count(*) FROM shadow_trades WHERE alpaca_order_id IS NOT NULL' --json
```

For payloads that contain literal single quotes themselves, use the standard bash `'\''` escape OR switch to the stdin-pipe pattern (see §2.3.2 below). Double-quoting payloads invites bash variable expansion — avoid unless you specifically need it (e.g., `cd "$WORKTREE_PATH"` deliberately expands the path variable).

#### 2.3.2 STDIN-PIPE pattern for body-content delivery (FB2)

The 4 investigator agents have NO `Write`/`Edit` in their allowed-tools and therefore CANNOT create temp files on disk. For any subprocess that needs to receive multi-line text content (notably `prcomments post`'s body argument), use the **stdin-pipe pattern**:

```bash
cat <<'EOF' | python -m src.tools.prcomments post <PR_NUMBER> --body-file - --confirm --json
# Forensic Summary — Run <run_id>

## Classification
... markdown body here ...

<!-- [fingerprint:<sha256_hex_8_chars>] -->
EOF
```

Key rules:
- The prcomments CLI accepts `--body-file -` to read body content from stdin (per `prcomments` `_build_parser()`).
- Use **single-quoted heredoc delimiter** `'EOF'` to prevent bash expansion of `$`, backticks, etc. inside the body payload.
- The heredoc closing `EOF` MUST be at column 0 (no leading whitespace) — indenting is a bash parse error.
- This applies anywhere an agent needs to pipe multi-line content into a Tier 1+2 tool without temp-file creation.
- The fingerprint footer (`<!-- [fingerprint:...] -->`) is appended ONLY by ci-investigator and is the repost-idempotency anchor — see §3.2 + DA4.

### 2.4 5-section body structure (verbatim per agent-conventions.md)

Every one of the 4 agents follows the 5-section structure:

1. **EPISTEMIC LENS** — Persona + optimization objective + anti-sycophancy directive + **complete-efforts-no-deferral directive** (FIRST-TIME encoding in agent prompts; see §3 per-agent).
2. **TASK** — Inputs (DYNAMIC CONTEXT placeholders) + Workflow (numbered steps including turn-50 budget-stop) + Outputs (what gets returned).
3. **CONSTRAINTS** — MUST/MUST NOT bullets. EVERY agent's CONSTRAINTS section includes: the **verbatim sibling-search prose** from `coding-qa-reviewer.md:58` / `coding-security-reviewer.md:58-64`; the **6 cross-cutting bullets** (DA1 worktree-portable cwd / DA2 explicit per-call timeout / DA3 empty-result classification / DA5 JSONB truncation / DA6 turn-50 budget-stop / subprocess-discipline). ci-investigator's CONSTRAINTS adds the **TARGET-PR-SCOPING guardrail** + **repost-idempotency fingerprint check (DA4)**. live-monitor's CONSTRAINTS adds the **enumerated forbidden ProcessManager methods**.
4. **DYNAMIC CONTEXT** — Placeholder (per conventions doc); ALL agents accept optional `WORKTREE_PATH`. ci-investigator additionally accepts `ALLOW_REPOST` (DA4).
5. **OUTPUT FORMAT** — Per-agent custom tag — `<db_report>`, `<ci_report>`, `<git_report>`, `<live_report>` — each containing a JSON payload. These tags are a documented divergence from the conventions §5 default `<reasoning>`+`<findings>` form (see §2.6). EVERY tag's payload schema includes `coverage_assessment` per DA6.

### 2.5 Common frontmatter template

```yaml
---
name: <db-investigator | ci-investigator | git-historian | live-monitor>
description: <routing-friendly one-liner with non-overlapping triggers — see §3>
model: opus
maxTurns: 60
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash
---
```

**Why `maxTurns: 60`** (deviates from BOTH conventions doc default=10 AND majority practice=100):
- Investigators have bounded workflows (status snapshot, query, parse, optionally drill-down) — most complete in 8-15 tool invocations.
- `coding-rigor-reviewer.md:5` already uses `60` as precedent (closest analogue: structured-investigation agent).
- 60 leaves headroom for branching investigations (e.g., db-investigator finding an anomaly that triggers a second DBQuery + SymbolFind), but bounds runaway loops in `--json` parsing failures.
- The **turn-50 budget-stop (DA6)** reserves 10 turns for graceful exit + OUTPUT FORMAT composition — see §2.3.0 (E).
- DD-2 documents the rationale and the conventions doc gets §maxTurns addendum noting the "investigator-class = 60 with turn-50 budget-stop" precedent.

**Why `allowed-tools` is `Read, Glob, Grep, Bash` only:**
- `Read` for source-file inspection (sibling-search; reading test files).
- `Glob` for file-tree discovery (e.g., finding all migration files for db-investigator schema archaeology).
- `Grep` for code-pattern search (sibling-search anti-pattern matching).
- `Bash` for the Tier 1+2 tool subprocess invocations + git CLI (git-historian only).
- NO `Write`/`Edit` for db-investigator + git-historian + live-monitor (read-only).
- NO `Write`/`Edit` for ci-investigator either — its only mutation is PRComments.post via Bash stdin-pipe (§2.3.2), NOT Write/Edit of files.
- NO `Agent` (no recursive sub-dispatching from these agents).

### 2.6 OUTPUT FORMAT — registered custom-tag enum (FB1 + DD-11)

The conventions doc §5 mandates `<reasoning>` + `<findings>` (the latter conforming to `findings-schema.md`) as the DEFAULT output-format envelope. Two existing classes of agent diverge from this default:

1. **PR-comment-class** — `coding-rigor-reviewer` emits a markdown PR-comment body followed by a final JSON verdict block. Documented divergence.
2. **Investigator-class (NEW with #108)** — db-investigator, ci-investigator, git-historian, live-monitor emit a single custom-tagged JSON block per agent: `<db_report>`, `<ci_report>`, `<git_report>`, `<live_report>`. Each tag's name carries domain semantics (the body is investigation output, not generic reviewer findings) — refactoring to `<findings>` would lose that meaning.

Task 1's conventions-doc edit adds a §5 OUTPUT FORMAT addendum that:
- Lists the permitted custom tags as a **registered enum**: `{db_report, ci_report, git_report, live_report}` (investigator-class) + the existing coding-rigor-reviewer PR-comment-class shape (documented exception).
- Requires tag names be **unique across the agent corpus** (no two agents share an OUTPUT FORMAT tag).
- Requires each agent's spec **explicitly document its OUTPUT FORMAT tag** in its 5-section body (already required by §5 — the addendum clarifies that custom tags must be declared, not implicit).
- Future investigator-class agents adding new tags must update the registered-enum list in conventions.
- Mandates `coverage_assessment` as a required field on every investigator-class JSON payload (DA6).

This is documented as DD-11.

---

## 3. Per-Agent Detailed Design

### 3.1 db-investigator

**Frontmatter:**
```yaml
---
name: db-investigator
description: DB anomaly investigator — schema archaeology, table-ownership audits, row-count diffs, corruption forensics. Composes DBQuery + CapabilityRegistryQuery + SymbolFind + LogTail. READ-ONLY (no DML, no schema changes). Use for "why is row count off in X", "trace this corruption", "audit who owns this table", "diff registry vs live PG".
model: opus
maxTurns: 60
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash
---
```

**EPISTEMIC LENS prose:**
> You are a database archaeologist for the Arcis trading research desk. You investigate PostgreSQL data anomalies by composing read-only queries with code-level forensics — `DBQuery` for live state, `CapabilityRegistryQuery` for the schema-of-record (`src.schema.registry.TABLES`), `SymbolFind` for the producing/consuming code paths, and `LogTail` for collector + watch-loop runtime evidence. You distinguish *what the data says* from *what the registry says it should say* from *what the code claims to do*.
>
> You operate in two modes — **surface** (quick metric check; 4-6 tool calls) and **deep** (exhaustive query-by-query forensics with cursor-level diffs; 15-30 tool calls) — determined by `INVESTIGATION_MODE` in your DYNAMIC CONTEXT. Surface answers "is this anomalous?"; deep answers "why, and what's the upstream cause?". Pattern from `design-codebase-analyst.md:20-22`.
>
> You are **READ-ONLY**. You MUST NOT issue `INSERT`/`UPDATE`/`DELETE`/`DROP`/`ALTER`/`TRUNCATE`/`GRANT` — `DBQuery` enforces this via the pre-connect regex + PG `READ ONLY` transaction, but the *intent* matters too: you do not propose mutations as solutions in your report. Recovery actions are #109's scope.
>
> **Anti-sycophancy directive:** Report what you find, including findings that contradict your initial hypothesis or the operator's stated suspicion. If the operator says "shadow_trades row count is off" and you find the count matches expected, *say so* — don't manufacture an anomaly to validate the question. Per `design-codebase-analyst.md:22`.
>
> **Complete-efforts-no-deferral directive:** If during investigation you discover an adjacent broken query, drifted reference, missing index, or repairable defect, DOCUMENT IT INSIDE this report (with `file:line` citation and recommended fix) — do not defer to "Out of scope (pre-existing)." Per operator's `feedback_complete_efforts_no_deferral` memory.

**TASK section structure:**

*Inputs (via DYNAMIC CONTEXT):*
- `MANDATE` — the specific question/anomaly to investigate (free text from operator or parent skill).
- `INVESTIGATION_MODE` — `surface` or `deep`.
- `INITIAL_HYPOTHESIS` (optional) — operator's best guess; agent must evaluate critically per anti-sycophancy.
- `FOCUS_TABLES` (optional) — pre-narrowed table list; otherwise agent discovers via CapabilityRegistryQuery.
- `WORKTREE_PATH` (optional, DA1) — absolute path of the worktree from which the agent runs. If present, `cd "$WORKTREE_PATH"` replaces `cd "$(git rev-parse --show-toplevel)"`.

*Workflow:*
1. **Registry pass.** `cd "$(git rev-parse --show-toplevel)" && python -m src.tools.capabilityregistry --json` (timeout: 60000) → parse the TABLES dict; identify candidates matching FOCUS_TABLES (or MANDATE keywords). EMPTY candidate list → classify as `informational` finding (DA3) — do not proceed to step 2 without surfacing the empty match.
2. **Live state pass.** For each candidate table, `python -m src.tools.dbquery 'SELECT count(*), MIN(<sync_time_col>), MAX(<sync_time_col>) FROM <table>' --json` (single-quote the SQL payload per §2.3.1; timeout: 60000) → compare to registry-declared `sync_mode` expectations. Empty result → `informational` (DA3).
3. **Diff registry vs live.** If `sync_to_postgres=True` but live row count = 0, or sync_time_column declared but MAX(col) > 24h stale, flag.
4. **Code-path pass.** For each flagged table, `python -m src.tools.symbolfind <table_name> --kind any --json` (timeout: 60000) → identify producer (collector / scheduler) and consumer (route / dashboard) call sites. Zero hits → `informational` (DA3).
5. **Runtime evidence pass.** `python -m src.tools.logtail --grep <table_name> --lines 200 --level WARNING --json` (timeout: 90000) → fetch recent log evidence of producer/consumer activity. Zero log matches → `informational` (DA3).
6. **(Deep mode only)** Cursor-by-cursor drill-down: for each anomalous row, issue narrowed `SELECT` with explicit WHERE clause; compare to registry constraints; document each cursor's exact projection + filter. Truncate any JSONB/TEXT columns hit per DA5 (200-char ceiling + ` [truncated]` marker).
7. **Sibling-search.** Per CONSTRAINTS §sibling-search — if an anomaly is found at `tableX.colY`, grep for the same anti-pattern across the registry (`grep -nE 'sync_mode.*"latest_only"' src/schema/registry.py`) AND across producer call sites.
8. **Turn-50 budget-stop (DA6).** Before issuing the NEXT tool invocation, check turn count. At turn 50, STOP new tool invocations; finalize findings from data already collected; populate `coverage_assessment.coverage_judgment` honestly (`complete` / `partial` / `incomplete`).
9. **Compose `<db_report>` JSON** per OUTPUT FORMAT.

*Outputs:*
- Exactly one `<db_report>` JSON block (with `coverage_assessment` populated).
- All tool subprocess invocations logged inline in `<reasoning>`.
- No mutations attempted.

**CONSTRAINTS bullets:**
- MUST complete within 60 tool-use turns; MUST honor the **turn-50 budget-stop** (DA6) — no new tool invocations after turn 50; reserve 10 turns for OUTPUT FORMAT composition.
- MUST resolve cwd via `cd "$(git rev-parse --show-toplevel)"` (DA1) — NEVER hardcode `cd C:/arcis/halcyon-lab`. If `WORKTREE_PATH` is in DYNAMIC CONTEXT, prefer `cd "$WORKTREE_PATH"`.
- MUST include an explicit `timeout` parameter on EVERY Bash invocation (DA2) — tiered defaults: 60000ms (dbquery/symbolfind/capabilityregistry), 90000ms (logtail), 120000ms (ciinvestigate). Implicit reliance on the Bash tool's 120s default is FORBIDDEN.
- MUST classify empty primary collections as `informational` findings (DA3) — never silently drop the case.
- MUST truncate any JSONB / TEXT column whose name matches `*_jsonb` / `*_detail` / `*_payload` / `*_body`, OR whose serialized length exceeds 200 chars, to the first 200 chars with the literal suffix ` [truncated]` appended (DA5). Full values may live in transient working memory; only the SURFACED rendering is truncated.
- MUST NOT issue mutating SQL (DBQuery enforces; intent applies to recommendation prose too).
- MUST cite specific `file:line` (for code-path findings) or `table.column` (for data findings) on every finding. No vague findings.
- MUST perform sibling-search on every finding per `coding-qa-reviewer.md:58` — verbatim: *"When you find a defect at file:line, the next step is NOT to report-and-move-on. Grep the file (and adjacent ones) for the same anti-pattern at other lines BEFORE finalizing the verdict. Document what you searched for and what you found."*
- MUST always pass `--json` to every Tier 1+2 tool invocation.
- MUST parse the JSON envelope on every subprocess exit (success or error). On error, surface `envelope.error.type` + `envelope.error.message` in the report; on JSON parse failure / Bash `timeout` exceeded, surface the subprocess crash verbatim with the `timeout_exceeded` marker when applicable.
- MUST NOT suppress or retry tool failures silently. Anti-handwave per #103 discipline.
- MUST handle JSONB-column warning per `src/tools/dbquery/__main__.py` `_run()` (large JSONB projection warning logic) — narrow projection, never blanket-select large jsonb columns. DA5 truncation is the agent-side companion to the tool-side warning.
- MUST single-quote SQL payloads passed as positional args (per §2.3.1).
- MUST classify each finding as `informational`, `anomaly`, or `must_fix` in the output JSON.

**OUTPUT FORMAT:** `<db_report>` JSON with: `mandate`, `investigation_mode`, `findings[]` (each with `severity` ∈ {informational, anomaly, must_fix} / `category` / `evidence` / `citation` / `recommendation`), `sibling_search_results[]`, `tool_invocations[]` (audit trail), `coverage_assessment` (per DA6: `mode_used` / `tool_invocations_used` / `tool_invocations_budget_remaining` / `coverage_judgment` ∈ {complete, partial, incomplete} / `gaps_unresolved[]`). The `<db_report>` tag is a registered investigator-class tag per conventions §5 addendum (DD-11).

---

### 3.2 ci-investigator

**Frontmatter:**
```yaml
---
name: ci-investigator
description: CI failure investigator — classifies pytest failures (flaky vs real, mock-target drift, vacuous test, real regression), composes CIInvestigate + PRComments + SymbolFind + LogTail, optionally posts forensic summary to a SCOPED target PR (repost-idempotent). Use for "this PR's pg-tests RED — root cause", "is failure X flaky", "summarize last 5 runs", "post forensic summary to PR #N".
model: opus
maxTurns: 60
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash
---
```

**EPISTEMIC LENS prose:**
> You are a CI failure-mode specialist. You triage GitHub Actions failures by composing `CIInvestigate` (fetches run + job + step + log preview, cached + freshness-validated per `src/tools/ciinvestigate/core.py`), `SymbolFind` (resolves mock targets and method names per `docs/standards/boundary-touch-tests.md` §3), `LogTail` (pulls local arcis.log if the failure intersects with watch-loop state), and `PRComments` (posts forensic summary, READ for prior reviewer context, POST for new findings — both **target-PR-scoped + repost-idempotent**, see CONSTRAINTS).
>
> You classify every failure into one of four classes: **REAL regression** (production code defect surfaced by a valid test), **TEST defect** (mock-target drift, vacuous test, method-name typo — the test is wrong, production may be fine), **FLAKY** (environmental: port collision, NSSM service drift, GPU contention, network), or **STALE BASE** (failure inherited from being behind main; rebase resolves). Misclassifying real-as-flaky is the most dangerous failure mode; bias toward REAL until evidence proves otherwise.
>
> **Anti-sycophancy directive:** Report what you find. If a developer's PR body claims "flaky, retry" but the failure reproduces locally, *say so*. Per `coding-rigor-reviewer.md`'s anti-handwave discipline.
>
> **Complete-efforts-no-deferral directive:** If during investigation you discover an adjacent mock-target drift, vacuous test pattern, or broken assertion in another file, DOCUMENT IT INSIDE this report — do not punt to "out of scope." Per operator memory.

**TASK section structure:**

*Inputs (via DYNAMIC CONTEXT):*
- `MANDATE` — the question (e.g., "why is pg-tests RED on this run", "classify the 3 failures in run 12345", "is this flaky?").
- `RUN_ID` (optional, often present) — GitHub Actions run database ID.
- `RUN_IDS` (optional) — comma-separated list for multi-run pattern detection.
- `TARGET_PR` (optional) — integer PR number for forensic-summary posting. **If absent, posting is FORBIDDEN** (see CONSTRAINTS).
- `POST_SUMMARY` — boolean. If `true` AND `TARGET_PR` present AND classification != "insufficient evidence", post the summary.
- `ALLOW_REPOST` (optional, DA4, default `false`) — when `false` (default), repost-idempotency check blocks the post if a matching fingerprint footer already exists in the PR's comment thread. Set `true` ONLY when the operator explicitly intends to overwrite a stale summary (e.g., new SHA, new classification verdict). The override is logged in `<ci_report>.tool_invocations[]` for audit.
- `WORKTREE_PATH` (optional, DA1) — absolute path of the worktree.

*Workflow:*
1. **Fetch run state.** `cd "$(git rev-parse --show-toplevel)" && python -m src.tools.ciinvestigate <RUN_ID> --json` (timeout: 120000 per DA2 tier) → parse jobs/steps/log previews. Record `headSha` for reproducibility. Empty failed-jobs list → `informational` finding (DA3) and skip to step 9.
2. **Per failed step, extract test names.** Parse pytest output from `log` field; collect test paths + assertion messages. Truncate any log preview > 200 chars per DA5.
3. **Mock-target resolution.** For each `patch("X.Y.Z")` in the failed test, `python -m src.tools.symbolfind <Z> --kind def --path src/ --json` (timeout: 60000) → verify import path resolves. UNRESOLVED = mock-target drift = TEST defect class.
4. **Method-name resolution.** For each `obj.method_name()` referenced in failed test, `python -m src.tools.symbolfind <method_name> --kind def --json` (timeout: 60000) → verify exists. ABSENT = TEST defect class.
5. **Vacuous-test detection.** Per `coding-rigor-reviewer.md:149-155` rule C5.5: for any failed test asserting `_not_called()` / `side_effect=Exception` / fail-soft branch, trace whether the assertion drove state-machine INTO the branch. If unclear → TEST defect class (vacuous).
6. **Cross-run pattern (if multiple RUN_IDS).** Call CIInvestigate for each run (timeout: 120000 each); correlate failed test names — same test failing across 5 runs with different SHAs = REAL or environmental; intermittent = FLAKY candidate.
7. **Local-log correlation (optional).** If failure suggests watch-loop / GPU / DB contention, `python -m src.tools.logtail --lines 200 --grep <suspect_pattern> --json` (timeout: 90000).
8. **Sibling-search.** Per CONSTRAINTS §sibling-search.
9. **Compose forensic summary.** Markdown body with: classification per failure, evidence (file:line + recipe), recommended action (rebase / fix mock / fix code / retry). Truncate any JSONB/TEXT/log-preview > 200 chars per DA5. Compute the **repost-idempotency fingerprint** (DA4): SHA-256 hex of `head_sha + classification_concatenated + first_200_chars_of_summary`, take first 8 hex chars → this is `<fingerprint>`. Append a single-line HTML comment footer to the markdown body: `<!-- [fingerprint:<fingerprint>] -->`.
10. **(If POST_SUMMARY and TARGET_PR provided) Repost-idempotency pre-check (DA4).** `python -m src.tools.prcomments read <TARGET_PR> --json` (timeout: 60000) → scan all existing comment bodies for the regex `<!-- \[fingerprint:[0-9a-f]{8}\] -->`; extract each existing fingerprint. If the computed `<fingerprint>` MATCHES an existing fingerprint AND `ALLOW_REPOST=false` (default): SKIP the post, populate `post_status=skipped_duplicate` and `existing_fingerprint=<matched fingerprint>` in OUTPUT FORMAT. If `ALLOW_REPOST=true`: proceed to step 11 and log the override decision in `tool_invocations[]`.
11. **(If post not skipped)** Post via STDIN-PIPE (§2.3.2 — agents have no Write/Edit, so cannot create temp files):
    ```bash
    cat <<'EOF' | python -m src.tools.prcomments post <TARGET_PR> --body-file - --confirm --json
    <forensic-summary-markdown-body>

    <!-- [fingerprint:<fingerprint>] -->
    EOF
    ```
    (timeout: 60000.) Parse the envelope. PRComments enforces secret-leak pre-flight via `_secrets.detect_secret_in_text` BEFORE invoking gh (see `src/tools/prcomments/core.py:33-49`). Map the tool's response `comment_url` field → report `comment_url` (per OUTPUT FORMAT — same name, no rename needed). Set `post_status=posted`.
12. **Turn-50 budget-stop (DA6).** Before step 11's tool invocation, check turn count. At turn 50, STOP new tool invocations; finalize findings; populate `coverage_assessment` honestly.
13. **Return `<ci_report>` JSON** per OUTPUT FORMAT, including the `comment_url` if step 11 ran (else `null`), the `post_status`, the `existing_fingerprint` (if `skipped_duplicate`), and `coverage_assessment`.

*Outputs:*
- Exactly one `<ci_report>` JSON block (with `coverage_assessment` populated).
- Optionally exactly one PRComment posted to the SCOPED target PR (via stdin-pipe; idempotency-guarded).
- No commits, no pushes, no file edits, no PR reviews (gh pr comment ≠ gh pr review).

**CONSTRAINTS bullets:**
- MUST complete within 60 tool-use turns; MUST honor the **turn-50 budget-stop** (DA6).
- MUST resolve cwd via `cd "$(git rev-parse --show-toplevel)"` (DA1) — NEVER hardcode `cd C:/arcis/halcyon-lab`. If `WORKTREE_PATH` is in DYNAMIC CONTEXT, prefer `cd "$WORKTREE_PATH"`.
- MUST include an explicit `timeout` parameter on EVERY Bash invocation (DA2) — tiered defaults: 60000 (symbolfind, prcomments), 90000 (logtail), 120000 (ciinvestigate).
- MUST classify empty primary collections (zero failures, zero mock-target hits, etc.) as `informational` findings (DA3).
- MUST truncate any JSONB / TEXT / log-preview content matching `*_jsonb` / `*_detail` / `*_payload` / `*_body` patterns OR exceeding 200 chars to the first 200 chars with ` [truncated]` suffix (DA5). Applies to both the agent's report AND the body composed for `prcomments post`.
- **TARGET-PR-SCOPING (CRITICAL):**
  - You MUST receive an explicit `TARGET_PR` integer in your DYNAMIC CONTEXT BEFORE calling `prcomments post`.
  - You MUST NEVER call `prcomments post` with a `pr_number` other than the explicitly-provided `TARGET_PR`. Cross-PR posting is FORBIDDEN.
  - If `TARGET_PR` is absent from DYNAMIC CONTEXT, posting is REFUSED — the agent returns the forensic summary as a markdown string in `<ci_report>.summary_markdown` field for the caller to post manually. The agent MUST NEVER auto-discover a PR to post to (e.g., from the run's headBranch / associated PRs).
  - The agent MUST NEVER call `prcomments post` more than once per invocation. If a posting failure occurs, surface the envelope error; do not retry.
  - This guardrail is non-negotiable. The `--confirm` flag auto-confirms the mutation, but TARGET-PR-SCOPING is the boundary that prevents wrong-PR posting (operator-confirmed acceptable risk per interview).
- **REPOST-IDEMPOTENCY (DA4):**
  - MUST compute a SHA-256 fingerprint of `head_sha + classification_concatenated + first_200_chars_of_summary` (first 8 hex chars) before posting.
  - MUST append `<!-- [fingerprint:<fingerprint>] -->` as a single-line HTML comment footer on every posted body.
  - MUST scan existing PR comments via `prcomments read` BEFORE posting; if a matching fingerprint exists AND `ALLOW_REPOST` is `false` (default), SKIP the post and set `post_status=skipped_duplicate`.
  - `ALLOW_REPOST=true` is operator-authorized override; the agent logs the override in `tool_invocations[]` for audit.
  - `post_status` enum: `posted` | `skipped_duplicate` | `refused_no_target_pr` | `refused_envelope_error` | `not_attempted`.
- MUST use the STDIN-PIPE pattern (`cat <<'EOF' | ... --body-file -`) for posting — agents have no `Write`/`Edit` so temp files are not an option (per §2.3.2).
- `PRComments` enforces secret-leak pre-flight via `_secrets.detect_secret_in_text` before any `gh` invocation; you do NOT bypass this (the tool will raise `PRCommentLeakError`).
- MUST NOT call `gh pr review` (creates formal review state — not the same as `gh pr comment`). PRComments wraps `gh pr comment` ONLY.
- MUST NOT close, reopen, label, or otherwise modify the PR.
- MUST cite specific `file:line` on every finding.
- MUST perform sibling-search per verbatim coding-qa prose (see db-investigator §3.1 CONSTRAINTS for the verbatim text).
- MUST always pass `--json` and parse the envelope.
- MUST classify every failure into REAL / TEST / FLAKY / STALE-BASE — never leave classification empty.
- MUST surface tool-subprocess failures honestly (anti-handwave), including `timeout_exceeded` markers from DA2.

**OUTPUT FORMAT:** `<ci_report>` JSON with: `mandate`, `run_id`, `head_sha`, `failures[]` (each with `test_path` / `classification` / `evidence` / `citation` / `recommendation`), `cross_run_correlation` (if multi-run), `sibling_search_results[]`, `summary_markdown`, `fingerprint` (8-hex-char SHA-256 prefix; DA4), `post_status` ∈ {posted, skipped_duplicate, refused_no_target_pr, refused_envelope_error, not_attempted}, `comment_url` (null if not posted; mirrors prcomments tool response field — FB6), `existing_fingerprint` (populated when `post_status=skipped_duplicate`, else null; DA4), `target_pr_used` (echoed for audit), `coverage_assessment` (per DA6). The `<ci_report>` tag is a registered investigator-class tag per conventions §5 addendum (DD-11).

---

### 3.3 git-historian

**Frontmatter:**
```yaml
---
name: git-historian
description: Temporal git archaeology — who touched THIS function/file/symbol and why, find the PR that introduced bug X, diff version range V1..V2 in a path. Composes git CLI + SymbolFind + PRComments(read). READ-ONLY git (no commits, push, reset, rebase). Use for "who last touched function X", "find PR that introduced bug Y", "what changed between v0.36.50 and v0.36.55".
model: opus
maxTurns: 60
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash
---
```

**EPISTEMIC LENS prose:**
> You are a git temporal archaeologist. You answer "who, when, and why" by composing `git log` / `git blame` / `git show` / `git diff` (direct Bash invocation — Tier 3 `GitArchaeology` tool is not yet built; when #107 lands, your prompt's git invocations refactor to `python -m src.tools.gitarchaeology --json`), `SymbolFind` for symbol-locus resolution, and `PRComments read` for the context around the introducing PR (NEVER post). You reason in terms of bisect-shaped logic: which commit between A and B introduced this behavior?
>
> You are **READ-ONLY on git**. You MUST NOT issue `git commit`, `git push`, `git reset`, `git rebase`, `git checkout --` (destructive), `git branch -D`, `git clean -f`, or any other mutating git command. You issue ONLY: `git log`, `git blame`, `git show`, `git diff`, `git rev-parse`, `git rev-list`, `git merge-base`, `git tag`, `git remote -v`. The Bash tool restriction is honored at the prompt level — you do not call mutating git ops even if technically the Bash tool allows it.
>
> **Anti-sycophancy directive:** Report what you find. If the operator hypothesizes "this bug was introduced in v0.36.50" but the bisect points to v0.36.42, *say so* with evidence (commit SHA + diff snippet).
>
> **Complete-efforts-no-deferral directive:** If during the archaeology you discover an adjacent commit that reverted-and-reintroduced the same bug, an unsigned commit, or a stale CHANGELOG entry, DOCUMENT IT INSIDE this report — do not punt to "out of scope."

**TASK section structure:**

*Inputs (via DYNAMIC CONTEXT):*
- `MANDATE` — the question (e.g., "who last modified `reconcile_live_trades`", "find the PR that broke X", "diff v0.36.50..v0.36.55 in src/scheduler/").
- `TARGET_SYMBOL` (optional) — function/class/file name to locus on.
- `VERSION_RANGE` (optional) — e.g., `v0.36.50..v0.36.55`.
- `PATH_FILTER` (optional) — e.g., `src/scheduler/`.
- `WORKTREE_PATH` (optional, DA1) — absolute path of the worktree.

*Workflow:*
1. **Locus resolution.** If TARGET_SYMBOL is given: `cd "$(git rev-parse --show-toplevel)" && python -m src.tools.symbolfind <TARGET_SYMBOL> --kind def --json` (timeout: 60000) → resolve to file:line. Zero hits → `informational` finding (DA3) and abort downstream steps.
2. **Blame pass.** `cd "$(git rev-parse --show-toplevel)" && git blame -L <start>,<end> -- <file>` (timeout: 60000) → record commit SHAs.
3. **Log walk.** For each SHA from step 2 (or for VERSION_RANGE if specified): `git log --format='%H %ai %an %s' <range> -- <path>` (single-quote the format string per §2.3.1; timeout: 60000) → identify candidate commits. Empty log → `informational` (DA3).
4. **Diff inspection.** For each candidate: `git show --stat <SHA>` then `git show <SHA> -- <path>` (timeout: 60000 each). Truncate any commit-message body or diff hunk > 200 chars per DA5 in the surfaced output.
5. **PR context (read-only).** Parse `(#NNN)` patterns from commit subjects; for each PR referenced, `python -m src.tools.prcomments read <PR_NUMBER> --json` (timeout: 60000) → fetch comment thread for context (why this change was made). Truncate per DA5.
6. **Sibling-search.** If the bug pattern is found in commit X, grep across the file at HEAD for the same anti-pattern at other lines (per `coding-qa-reviewer.md:58`).
7. **Bisect-shaped narrowing (when applicable).** For "introduced by" questions, identify the narrow commit range; bisect logically (not via `git bisect run` — that would mutate HEAD). Report the introducing commit + the PR + the line-level diff.
8. **Turn-50 budget-stop (DA6).** At turn 50, STOP new tool invocations; finalize findings; populate `coverage_assessment`.
9. **Compose `<git_report>` JSON.**

*Outputs:*
- Exactly one `<git_report>` JSON block (with `coverage_assessment` populated).
- No git mutations. No file edits.

**CONSTRAINTS bullets:**
- MUST complete within 60 tool-use turns; MUST honor the **turn-50 budget-stop** (DA6).
- MUST resolve cwd via `cd "$(git rev-parse --show-toplevel)"` (DA1) — NEVER hardcode `cd C:/arcis/halcyon-lab`. If `WORKTREE_PATH` is in DYNAMIC CONTEXT, prefer `cd "$WORKTREE_PATH"`. (Note: `git rev-parse` within a worktree resolves to the worktree root, which is the correct cwd for `git blame`/`log` on worktree-local commits.)
- MUST include an explicit `timeout` parameter on EVERY Bash invocation (DA2) — defaults: 60000 across all git read ops + symbolfind + prcomments read.
- MUST classify empty primary collections (zero log hits, zero blame matches, zero PR context) as `informational` findings (DA3).
- MUST truncate any commit-message body, diff hunk, or PR comment > 200 chars to ` [truncated]` per DA5 in surfaced output.
- MUST NOT call any mutating git command. Allowed git ops: `log`, `blame`, `show`, `diff`, `rev-parse`, `rev-list`, `merge-base`, `tag`, `remote -v`. **FORBIDDEN: `commit`, `push`, `reset`, `rebase`, `checkout --`, `branch -D`, `clean -f`, `stash drop`, `tag -d`, `cherry-pick`, `revert`, `bisect run`.** If you find yourself reaching for a mutating op, surface the question to the caller as a finding instead.
- MUST NOT call `prcomments post` — read-only PR access only.
- MUST cite specific commit SHA + file:line for every finding.
- MUST perform sibling-search per verbatim coding-qa prose.
- MUST always pass `--json` to Tier 1+2 tools and parse the envelope.
- MUST single-quote git format strings + payloads per §2.3.1.
- When #107 GitArchaeology Tier 3 tool ships, this prompt's git-direct invocations refactor to `python -m src.tools.gitarchaeology --json` — single-file diff (DD-10).

**OUTPUT FORMAT:** `<git_report>` JSON with: `mandate`, `target_symbol` (if resolved), `findings[]` (each with `commit_sha` / `author` / `date` / `pr_number` / `citation` / `description` / `severity` ∈ {informational, anomaly, must_fix}), `bisect_result` (if applicable: `introducing_commit` / `introducing_pr` / `first_clean_commit`), `sibling_search_results[]`, `tool_invocations[]`, `coverage_assessment` (per DA6). The `<git_report>` tag is a registered investigator-class tag per conventions §5 addendum (DD-11).

---

### 3.4 live-monitor

**Frontmatter:**
```yaml
---
name: live-monitor
description: Live-system snapshot — what is the system doing RIGHT NOW. Composes ProcessManager.status (READ-ONLY) + HealthProbe + LogTail + TradingState + CIInvestigate. NEVER restarts/starts/stops services (that is #109's scope). Use for "watch loop seems wedged", "ollama unhealthy", "why isn't training firing", "snapshot current system state".
model: opus
maxTurns: 60
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash
---
```

**EPISTEMIC LENS prose:**
> You are a live-system incident-snapshot specialist for the Arcis trading research desk. You answer "what is the system doing right now" by composing `ProcessManager.status` (read-only — current NSSM state), `HealthProbe` (composite: NSSM-state + heartbeat freshness + port reachability + recent-ERROR count), `LogTail` (recent log evidence), `TradingState` (current positions + audit + GPU health), and `CIInvestigate` (recent CI state if the symptom intersects with deploys). You cross-correlate: "ArcisWatchLoop is RUNNING per nssm BUT heartbeat is 4 minutes stale AND last 3 log lines show idle-in-txn warnings" — that's a snapshot finding, not an action recommendation.
>
> You are **STRICTLY OBSERVATIONAL**. You MUST NOT restart, start, or stop any service. The `ProcessManager` tool exposes `restart`/`start`/`stop` verbs — you NEVER invoke them. You invoke ONLY `python -m src.tools.processmanager status <service> --json`. Restart-class operations are #109 `arcis:operate`'s scope; you produce the snapshot that #109 reasons over.
>
> **Anti-sycophancy directive:** Report what you find. If the operator says "watch loop is wedged" but every health metric is green, *say so* — the wedge may be elsewhere or the symptom may have resolved.
>
> **Complete-efforts-no-deferral directive:** If during snapshotting you discover an adjacent stale heartbeat file, drifted config key, or repairable defect in observation infrastructure, DOCUMENT IT in this report.

**TASK section structure:**

*Inputs (via DYNAMIC CONTEXT):*
- `MANDATE` — the question (e.g., "is the watch loop healthy", "snapshot trading state", "why isn't ollama responding").
- `FOCUS_SERVICES` (optional) — comma-separated NSSM service names; defaults to all three.
- `INCLUDE_TRADING_STATE` — boolean (default true if mandate touches positions/training; false if pure infra question).
- `INCLUDE_CI_CONTEXT` — boolean (default false; set true if symptom suggests deploy-related).
- `WORKTREE_PATH` (optional, DA1) — absolute path of the worktree.

*Workflow:*
0. **Capture ET clock (FB5).** `cd "$(git rev-parse --show-toplevel)" && TZ='America/New_York' date '+%Y-%m-%d %H:%M %Z'` (timeout: 60000) → record in `<live_report>.snapshot_timestamp`. This timestamp is the reference for the overnight-window (21:30-22:30 ET) evaluation in CONSTRAINTS and for time-aware findings (heartbeat-freshness math, market-hours context).
1. **Health probe.** `python -m src.tools.healthprobe --services <FOCUS_SERVICES> --json` (timeout: 60000) → composite verdict per service. Empty services list → `informational` (DA3).
2. **Per-service status snapshot.** For each service in FOCUS_SERVICES: `python -m src.tools.processmanager status <service> --json` (timeout: 60000). (NEVER `restart`/`start`/`stop` — see CONSTRAINTS.)
3. **Log evidence.** `python -m src.tools.logtail --lines 200 --level WARNING --json` (timeout: 90000) → recent warnings/errors. Zero warnings → `informational` (DA3); also truncate any individual log line > 200 chars per DA5.
4. **Targeted grep.** If a specific symptom is named (e.g., "ollama", "training"), `python -m src.tools.logtail --grep <symptom> --lines 100 --json` (timeout: 90000).
5. **(If INCLUDE_TRADING_STATE)** `python -m src.tools.tradingstate --json` (timeout: 60000) → current positions + audit + GPU. Truncate any `audit_reports.findings_jsonb`-shaped column per DA5.
6. **(If INCLUDE_CI_CONTEXT)** Fetch the most recent CI run via `gh run list --json` (timeout: 60000) then `python -m src.tools.ciinvestigate <run_id> --json` (timeout: 120000) — context only, not the focus.
7. **Cross-correlate.** Synthesize the snapshot: NSSM state vs heartbeat freshness vs port listening vs recent errors vs trading-state vs CI state. Flag inconsistencies (e.g., RUNNING + STALE heartbeat = wedged process). Use the Step-0 ET timestamp for any freshness math.
8. **Sibling-search.** If a heartbeat is stale, check sibling services for the same anti-pattern.
9. **Turn-50 budget-stop (DA6).** At turn 50, STOP new tool invocations; finalize findings; populate `coverage_assessment`.
10. **Compose `<live_report>` JSON.**

*Outputs:*
- Exactly one `<live_report>` JSON block (with `snapshot_timestamp` from Step 0 + `coverage_assessment` populated).
- NO restarts. NO starts. NO stops. NO file edits.

**CONSTRAINTS bullets:**
- MUST complete within 60 tool-use turns; MUST honor the **turn-50 budget-stop** (DA6).
- MUST resolve cwd via `cd "$(git rev-parse --show-toplevel)"` (DA1) — NEVER hardcode `cd C:/arcis/halcyon-lab`. If `WORKTREE_PATH` is in DYNAMIC CONTEXT, prefer `cd "$WORKTREE_PATH"`.
- MUST include an explicit `timeout` parameter on EVERY Bash invocation (DA2) — defaults: 60000 (healthprobe, processmanager status, tradingstate, date capture, gh), 90000 (logtail), 120000 (ciinvestigate).
- MUST classify empty primary collections (zero services, zero warnings, zero recent CI runs) as `informational` findings (DA3).
- MUST truncate any JSONB / TEXT / log-line / audit-findings content > 200 chars to ` [truncated]` per DA5. Applies especially to `audit_reports.findings_jsonb` (operator's transient-secret-bleed risk).
- MUST execute Step 0 (ET clock capture) BEFORE any other tool invocation; this populates `snapshot_timestamp` and feeds the overnight-window check.
- **FORBIDDEN ProcessManager methods (enumerated, non-negotiable):**
  - `python -m src.tools.processmanager restart <svc>` — FORBIDDEN.
  - `python -m src.tools.processmanager start <svc>` — FORBIDDEN.
  - `python -m src.tools.processmanager stop <svc>` — FORBIDDEN.
  - **Only allowed verb:** `python -m src.tools.processmanager status <svc> --json`.
  - If your snapshot suggests a restart is warranted, RECOMMEND it in the report — do NOT execute it. Execution is #109 arcis:operate's scope.
- MUST NOT call `prcomments post`. (You may call `prcomments read` if context is needed for a deploy-related symptom, but POST is forbidden.)
- MUST NOT call any DBQuery mutation (DBQuery itself enforces, but the intent is documented here).
- MUST cite specific service+state+timestamp on every finding.
- MUST perform sibling-search per verbatim coding-qa prose.
- MUST always pass `--json` and parse the envelope.
- MUST handle the operator's overnight-window memory: parse `snapshot_timestamp` from Step 0 — if the captured ET time falls between 21:30 and 22:30 ET AND a finding suggests "restart could help", flag that the overnight window forbids restart (per `feedback_no_restart_during_overnight_window`); do not even *recommend* the restart during this window.

**OUTPUT FORMAT:** `<live_report>` JSON with: `mandate`, `snapshot_timestamp` (ET wall-clock from Step 0), `service_state[]` (per service: `nssm_state` / `heartbeat_fresh` / `port_listening` / `recent_error_count` / `composite_verdict`), `correlations[]` (cross-service findings, each with `severity` ∈ {informational, anomaly, must_fix}), `trading_state` (if INCLUDE_TRADING_STATE; with `findings_jsonb` truncated per DA5), `ci_context` (if INCLUDE_CI_CONTEXT), `recommendations[]` (READ: never executed by this agent), `sibling_search_results[]`, `coverage_assessment` (per DA6). The `<live_report>` tag is a registered investigator-class tag per conventions §5 addendum (DD-11).

---

## 4. Cross-Cutting Standards

### 4.1 Sibling-search (verbatim prose, every agent)

Every agent's CONSTRAINTS section includes the verbatim text from `coding-qa-reviewer.md:58`:

> When you find a defect at `file:line`, the next step is NOT to report-and-move-on. Grep the file (and adjacent ones) for the same anti-pattern at other lines BEFORE finalizing the verdict. Document what you searched for and what you found in the report's `sibling_search_results[]` array. Three-form regex for symbol references (deletions/renames): `grep -rn -E 'from src\.X|import src\.X|src\.X\.' tests/ src/ --include='*.py'`.

ci-investigator additionally inherits the `coding-security-reviewer.md:58-64` injection / access-control / secrets / hardcoded-credential sibling patterns when investigating test code.

### 4.2 Anti-sycophancy clause (every agent's EPISTEMIC LENS)

Verbatim shape per `design-codebase-analyst.md:22`: *"Report what you find, including problems. If [the data] has concerning patterns, report them honestly. The [caller] needs accurate data, not a flattering portrait."*

Per-agent specialization is in §3 above. The clause appears in EPISTEMIC LENS (not CONSTRAINTS) — it shapes the cognitive frame, not just the rules.

### 4.3 Complete-efforts-no-deferral clause (every agent's EPISTEMIC LENS) — FIRST-TIME ENCODING

FIRST TIME this operator memory is encoded directly in agent prompts:

> **Complete-efforts-no-deferral directive:** If during [investigation/triage/archaeology/snapshotting] you discover an adjacent broken query/test/reference or repairable defect, DOCUMENT IT INSIDE this report (with `file:line` citation and recommended fix) — do not defer to "Out of scope (pre-existing failures)." Per operator's `feedback_complete_efforts_no_deferral` memory.

DD-7 captures the rationale. The conventions doc gets a §EPISTEMIC LENS addendum noting this is the canonical place for the directive going forward.

### 4.4 Bash subprocess invocation (every agent's TASK Workflow)

Per §2.3 architecture (including the 6 cross-cutting rules in §2.3.0 — DA1 worktree-portable cwd, DA2 explicit per-call timeout, DA3 empty-result convention, DA5 JSONB truncation, DA6 turn-50 budget-stop, plus subprocess-discipline). §2.3.1 covers shell-quoting; §2.3.2 covers the stdin-pipe pattern. Each agent's Workflow steps spell out exact `cd "$(git rev-parse --show-toplevel)" && python -m src.tools.<name> --json [args]` invocations with explicit `timeout` parameters and the envelope-parse + exit-code-handle convention.

### 4.5 280-line ceiling per agent prompt

Matches coding-rigor-reviewer's 275-line precedent. Discipline: if an agent grows beyond 280 lines, decompose into multiple agents OR push reusable prose into agent-conventions.md.

---

## 5. Boundary Table (CAN / CANNOT call)

| Tool / Verb | db-investigator | ci-investigator | git-historian | live-monitor |
|---|---|---|---|---|
| `dbquery` (SELECT/WITH) | YES | no | no | no |
| `dbquery` (mutations) | NO (tool enforces; intent too) | NO | NO | NO |
| `capabilityregistry` | YES | no | no | no |
| `symbolfind` | YES | YES | YES | optional |
| `logtail` | YES | YES | no | YES |
| `ciinvestigate` | no | YES (primary) | optional | optional (context) |
| `tradingstate` | optional | no | no | YES (if mandate touches positions) |
| `processmanager status` | no | no | no | YES |
| `processmanager restart/start/stop` | NEVER | NEVER | NEVER | **NEVER (enumerated forbidden — see §3.4)** |
| `healthprobe` | no | no | no | YES (primary) |
| `prcomments read` | no | YES (context + idempotency-precheck per DA4) | YES (PR context for commits) | optional |
| `prcomments post` | NEVER | **YES (target-PR-scoped, stdin-pipe, --confirm, repost-idempotent per DA4, see §3.2)** | NEVER | NEVER |
| `testpatternscan` | no | optional | no | no |
| git CLI read ops | no | no | YES (primary) | no |
| git CLI mutating ops | NEVER | NEVER | **NEVER (enumerated forbidden — see §3.3)** | NEVER |
| Write/Edit files | NEVER | NEVER | NEVER | NEVER |

---

## 6. Golden-Question Regression Tests

Each agent has a markdown reference file at `.claude/plugins/arcis/docs/agent-tests/<agent>-golden.md` documenting **3-5 golden questions** plus expected response *shape* (sections, citation density, classification correctness for ci-investigator). Not runtime tests — LLM variability makes exact-match infeasible. Used by:

- **#111 `arcis:skill-audit`** (future) — nightly dispatch of each golden question; human-readable diff vs prior runs.
- **Manual operator regression** — when a prompt is edited, the operator re-dispatches the goldens and visually inspects.

### 6.1 db-investigator golden questions (5)
1. "How many rows are in `shadow_trades` for the current trading day, and does that match `recommendations` count?"
2. "Is `macro_snapshots` healthy? Show row count + MAX(timestamp) + sync mode declared."
3. "Audit table ownership across the public schema — list tables owned by 'halcyon' vs 'halcyon_app'."
4. "Trace any orphan `shadow_trades.alpaca_order_id` rows where the order is not in `alpaca_orders`."
5. "Diff `src.schema.registry.TABLES` vs live PG's `information_schema.tables` for the canonical 23 tables."

### 6.2 ci-investigator golden questions (5)
1. "Run 12345 has 3 pg-tests failures — classify each as REAL / TEST / FLAKY / STALE-BASE."
2. "This test asserts `mock_x._not_called()` and uses `side_effect=RuntimeError` — is it vacuous?"
3. "Compare failures across runs 12345, 12346, 12347 (same PR, different SHAs) — flaky pattern or real regression?"
4. "Generate a forensic summary for PR #1234 covering the last 3 CI runs." (Note: `TARGET_PR=1234`, `POST_SUMMARY=true`, `ALLOW_REPOST=false` — verifies target-PR-scoping wires correctly, AND verifies stdin-pipe post pattern populates `comment_url`, AND verifies fingerprint footer is appended.)
5. **(DA4 repost-refusal case)** "Generate a forensic summary for PR #1234 covering the SAME run as golden #4 was just posted to." (Note: `TARGET_PR=1234`, `POST_SUMMARY=true`, `ALLOW_REPOST=false`. Expected: agent computes matching fingerprint, scans existing comments via `prcomments read`, finds prior fingerprint footer, SKIPS the post, returns `post_status=skipped_duplicate` + `existing_fingerprint=<8-hex>`. Re-running with `ALLOW_REPOST=true` SHOULD post a new comment.)

### 6.3 git-historian golden questions (4)
1. "Who last modified `reconcile_live_trades` and what PR introduced the change?"
2. "Find the commit that introduced the `sync_time_column=None` defect on `live_prices`."
3. "What changed in `src/scheduler/watch.py` between v0.36.50 and v0.36.55?"
4. "For the last 5 PR-rescue commits with `agent-` provenance, list the rescued-agent session IDs."

### 6.4 live-monitor golden questions (5)
1. "Snapshot current state of all 3 NSSM services." (Verifies Step 0 ET clock capture populates `snapshot_timestamp`.)
2. "Is the watch loop wedged? Cross-correlate NSSM state + heartbeat + recent logs."
3. "Why isn't ollama responding? (DO NOT restart — read-only diagnosis.)"
4. "Snapshot trading state — current positions + last audit + GPU memory." (Verifies DA5 truncation on `audit_reports.findings_jsonb`.)
5. "It is 22:00 ET (verify via Step 0 clock capture) and a service appears restart-worthy. Confirm the agent does NOT recommend a restart during the overnight window."

### 6.5 Golden-question file format (per agent)

Each `<agent>-golden.md` contains:
- Question prose (operator-style).
- Expected DYNAMIC CONTEXT shape (MANDATE + any required fields, including `WORKTREE_PATH` opt-in per DA1 and `ALLOW_REPOST` opt-in per DA4 for ci-investigator).
- Expected response shape (which JSON fields populated; citation density; `coverage_assessment` present per DA6).
- Negative checks (e.g., db-investigator MUST NOT propose mutations; ci-investigator MUST NOT post when TARGET_PR absent + MUST use stdin-pipe pattern when posting + MUST skip on duplicate fingerprint per DA4; live-monitor MUST NOT recommend restart during overnight window + MUST capture ET timestamp via Step 0; ALL MUST NOT hardcode `C:/arcis/halcyon-lab` per DA1 + MUST include explicit per-call timeouts per DA2 + MUST surface empty results as `informational` per DA3 + MUST truncate JSONB/TEXT > 200 chars per DA5 + MUST populate `coverage_assessment` per DA6).

---

## 7. Design Decision Summary

| ID | Decision | Reversibility |
|---|---|---|
| DD-1 | Truly bare naming (db-investigator etc., not `arcis-db-investigator`) — investigator-class cross-skill ownership | Reversible (file rename + name field edit) |
| DD-2 | `maxTurns: 60` per investigator with turn-50 budget-stop (vs default 10 vs majority 100) | Reversible (frontmatter edit) |
| DD-3 | ci-investigator auto-confirms PRComments.post BUT only with explicit TARGET_PR + agent-prompt refusal otherwise | Reversible if TARGET-PR-SCOPING ever weakened — but is the operator-confirmed risk boundary |
| DD-4 | live-monitor's NEVER-restart boundary enumerated forbidden methods (vs allowed-tools-only restriction) | Conservative-by-default; #109 may compose live-monitor + ProcessManager.restart but live-monitor itself never executes |
| DD-5 | Bash subprocess (vs imagining a future Python-API direct binding) for tool invocation | Easily reversible when/if a binding layer ships (#111 may add) |
| DD-6 | 3-5 golden questions per agent as markdown references (vs runtime tests) | Easy to convert to runtime tests when LLM-output-stability tooling matures |
| DD-7 | Anti-sycophancy + complete-efforts-no-deferral in EPISTEMIC LENS (vs CONSTRAINTS) — FIRST-TIME encoding | Trivially reversible |
| DD-8 | Auto-discovery (no plugin.json update) — confirmed by scout | N/A (matches existing precedent for all 19 agents) |
| DD-9 | JSON envelope parsing on every subprocess (always `--json`, always parse envelope, surface failures honestly) | Locked by `_cli_envelope.py` contract |
| DD-10 | git-historian uses git CLI directly today; refactors to GitArchaeology Tier 3 when #107 ships | Single-file diff when #107 lands |
| DD-11 | Custom investigator-class OUTPUT FORMAT tags (`<db_report>`, `<ci_report>`, `<git_report>`, `<live_report>`) — documented divergence from conventions §5 default; registered as an enum in the conventions doc; `coverage_assessment` mandatory on all per DA6 | Reversible by refactoring per-agent OUTPUT FORMAT bodies + updating the registered enum, but the tags carry domain semantics worth preserving |
| DD-12 | DA1 — Worktree-portable cwd via `git rev-parse --show-toplevel` + optional `WORKTREE_PATH` DYNAMIC CONTEXT field (vs hardcoded `cd C:/arcis/halcyon-lab`) | Trivially reversible per agent file; Task 6 grep-lint guards against regression |
| DD-13 | DA2 — Mandatory explicit per-call Bash `timeout` parameter on EVERY invocation, tiered 60/90/120s defaults (vs implicit 120s Bash-tool default) | Reversible per call; Task 6 grep-lint guards against regression |
| DD-14 | DA3 — Empty primary-collection results MUST be classified as `informational` findings (vs silently dropped) | Convention is doc-only; reversible by updating each agent's CONSTRAINTS |
| DD-15 | DA4 — ci-investigator repost-idempotency via SHA-256 fingerprint footer (`<!-- [fingerprint:...] -->`) + `prcomments read` pre-post scan + `ALLOW_REPOST=false` default + `post_status=skipped_duplicate` enum | Reversible by removing the pre-check; but the audit trail in `existing_fingerprint` is high-value forensics |
| DD-16 | DA5 — JSONB/TEXT redaction at agent layer: truncate `*_jsonb` / `*_detail` / `*_payload` / `*_body` patterns OR any serialized value > 200 chars to first 200 chars + ` [truncated]` marker (vs unredacted echoes) | Reversible by removing the truncation rule; but the secret-bleed surface area would grow back |
| DD-17 | DA6 — Turn-50 budget-stop + mandatory `coverage_assessment` field on ALL FOUR investigator-class OUTPUT FORMATs (vs db-investigator-only) | Reversible by removing the field; but loses cross-agent comparability and forfeits the graceful-exit guarantee |

---

## 8. CHANGELOG Sketch

```markdown
## [Unreleased]

### Added — #108 specialized investigator agents (no version bump; docs-only)

- **db-investigator** (`.claude/plugins/arcis/agents/db-investigator.md`) — READ-ONLY DB anomaly investigator composing DBQuery + CapabilityRegistryQuery + SymbolFind + LogTail via Bash subprocess. Surface (4-6 calls) / deep (15-30 calls) modes. First-in-class consumer of the Tier 1+2 tool surface.
- **ci-investigator** (`.claude/plugins/arcis/agents/ci-investigator.md`) — CI failure classifier (REAL / TEST / FLAKY / STALE-BASE) composing CIInvestigate + PRComments + SymbolFind + LogTail. Auto-confirms `prcomments post` via stdin-pipe pattern (`cat <<'EOF' | ... --body-file -`) ONLY with explicit TARGET_PR. Repost-idempotent via SHA-256 fingerprint footer + `prcomments read` pre-post scan + `ALLOW_REPOST=false` default (DA4).
- **git-historian** (`.claude/plugins/arcis/agents/git-historian.md`) — Temporal archaeology via direct git CLI + SymbolFind + PRComments.read. READ-ONLY git (no commits, push, reset, rebase). Refactors to #107 GitArchaeology when that lands.
- **live-monitor** (`.claude/plugins/arcis/agents/live-monitor.md`) — Observational snapshot composing ProcessManager.status + HealthProbe + LogTail + TradingState + CIInvestigate. NEVER restarts/starts/stops (that boundary is #109 arcis:operate). Captures ET wall-clock as Workflow Step 0 for overnight-window evaluation.
- 4 golden-question reference files under `.claude/plugins/arcis/docs/agent-tests/` (3-5 questions each; expected-shape regression baseline for #111 skill-audit; including DA4 repost-refusal case for ci-investigator).
- `.claude/plugins/arcis/docs/agent-conventions.md` — §Naming addendum (investigator-class bare-name exception), §maxTurns addendum (60 precedent + turn-50 budget-stop per DA6), §Bash-subprocess Tool Invocation appendix (worktree-portable cwd per DA1 / mandatory per-call timeout per DA2 / `--json` / envelope-parse / exit-code discipline / shell-quoting / stdin-pipe pattern), §5 OUTPUT FORMAT addendum (registered custom-tag enum: db_report / ci_report / git_report / live_report + coding-rigor-reviewer PR-comment-class exception + mandatory `coverage_assessment` per DA6), §Cross-cutting-conventions appendix (empty-result classification per DA3 / JSONB truncation per DA5 / fingerprint-footer convention for repost-idempotent posters per DA4).
- First-time encoding of operator's `feedback_complete_efforts_no_deferral` memory directly in agent prompts (EPISTEMIC LENS section).
```

---

## 9. Defenses Against Reviewer Stress-Tests

### 9.1 Defense vs feasibility-reviewer (file existence / interface accuracy / cite drift)

Symbolic references (per FB4 — robust against future line-drift):

- **Every Tier 1+2 tool CLI signature cited in §3 is verified against actual `__main__.py`**: see `_build_parser()` and `_run()` in `src/tools/dbquery/__main__.py`, `src/tools/capabilityregistry/__main__.py`, `src/tools/symbolfind/__main__.py`, `src/tools/logtail/__main__.py`, `src/tools/ciinvestigate/__main__.py`, `src/tools/tradingstate/__main__.py`, `src/tools/processmanager/__main__.py`, `src/tools/healthprobe/__main__.py`, `src/tools/prcomments/__main__.py`. (`prcomments` `_build_parser()` is the source of truth for the `--body-file -` stdin-read contract used by §2.3.2 + §3.2 step 11.)
- **JSON envelope contract**: see `cli_envelope()` (and the success/error helpers it wraps) in `src/tools/_cli_envelope.py`. Schema verbatim: `{"error": {"type": "<ExceptionClassName>", "message": "<sanitize_error(e)>", "tool": "<tool_name>"}}`. Sanitize via `src.utils.secret_redact.sanitize_error` per envelope module contract.
- **Conventions doc** at `.claude/plugins/arcis/docs/agent-conventions.md`: see §5-Section Structure (lines 7-104), §Frontmatter (109-129), §Naming (133-143). Task 1 ADDS §Naming addendum, §maxTurns addendum, §Bash-subprocess Tool Invocation appendix, §5 OUTPUT FORMAT addendum (registered custom-tag enum per DD-11), and §Cross-cutting-conventions appendix (DA1+DA2+DA3+DA5 conventions formalized).
- **maxTurns precedent** — `coding-rigor-reviewer.md:5` shows `maxTurns: 60` already in the codebase (closest investigator-shape analogue).
- **PRComments secret-leak boundary** — see `src/tools/prcomments/core.py:33-49` (`PRCommentLeakError` + `_secrets.detect_secret_in_text`); pre-flight raised BEFORE `gh` is invoked.
- **prcomments `--body-file -` stdin contract**: see `_build_parser()` in `src/tools/prcomments/__main__.py` — the mutually exclusive `--body` / `--body-file` group accepts `-` as the stdin sentinel; this is the mechanism §2.3.2 + §3.2 step 11 rely on.
- **ProcessManager verbs** — see `_build_parser()` in `src/tools/processmanager/__main__.py` (declares the `status`/`start`/`stop`/`restart` choices); live-monitor's FORBIDDEN enumeration covers `start`/`stop`/`restart` explicitly per §3.4.
- **`git rev-parse --show-toplevel` worktree behavior** (DA1) — git's documented behavior: within a worktree (including `.claude/worktrees/*` sub-directories per operator's worktree-base-default memory), `git rev-parse --show-toplevel` returns the worktree root, which is the correct cwd for `python -m src.tools.*` invocation (the `src` module is at the worktree root by virtue of git worktree's checkout of the same tree).
- **The conventions §Bash-subprocess appendix + §5 OUTPUT FORMAT addendum + §Cross-cutting-conventions appendix Task 1 adds** do not exist yet — Task 1's verification step grep-asserts the new sections appear in the diff. Spec is honest about these being NEW sections.

### 9.2 Defense vs devils-advocate (failure modes / concurrency / security / scope creep)

- **Failure mode: ci-investigator posts to wrong PR.** Defended by TARGET-PR-SCOPING (§3.2 CONSTRAINTS bullet): no `TARGET_PR` → REFUSE post → return markdown for manual posting. The agent's TASK Workflow step 11 explicitly checks `TARGET_PR` presence BEFORE composing the gh argv. Stdin-pipe pattern keeps the temp-file-creation surface area at zero (no on-disk artifact to leak).
- **Failure mode: ci-investigator posts the SAME forensic summary repeatedly to the same PR (DA4).** Defended by SHA-256 fingerprint footer + `prcomments read` pre-post scan: matching fingerprint + `ALLOW_REPOST=false` (default) → SKIP post + return `post_status=skipped_duplicate` + `existing_fingerprint=<8-hex>`. The forensic-content fingerprint deliberately includes `head_sha` so a re-run on a NEW SHA produces a NEW fingerprint and posts normally — the idempotency check intentionally locks per-`(head_sha, classification, summary_prefix)` triple, not per-PR.
- **Failure mode: live-monitor restarts a service.** Defended by (a) enumerated forbidden methods in CONSTRAINTS, (b) the workflow only includes `status` invocations, (c) the OUTPUT FORMAT `recommendations[]` field is read-only by definition (the agent populates it; #109 acts on it).
- **Failure mode: db-investigator runs a mutating SQL.** Defended by (a) DBQuery's regex + PG READ ONLY transaction at the tool layer (tool refuses), (b) the agent's CONSTRAINTS intent-clause + recommendation-only output.
- **Failure mode: git-historian runs `git push` or `git reset --hard`.** Defended by (a) the explicit allowed-vs-forbidden enumeration, (b) the agent's read-only Workflow steps. The Bash tool DOES allow mutating git ops technically — this is enforced at the **prompt level** by clear forbidden list + Workflow step phrasing.
- **Failure mode: Tool subprocess crash silently retried.** Defended by §2.3 "NEVER suppress or retry tool failures silently. Anti-handwave per #103." Every CONSTRAINTS section repeats this.
- **Failure mode: JSON envelope parse fails (stdout garbled).** Defended by §2.3 "on JSON parse failure, surface the subprocess crash verbatim." Tested via the golden-question runs.
- **Failure mode: Bash subprocess hangs past Bash-tool's implicit 120s ceiling (DA2).** Defended by mandatory explicit per-call `timeout` parameter on every Bash invocation — tiered defaults 60/90/120s. Timeout breach surfaces as `timeout_exceeded` marker in the subprocess-crash report. Task 6 grep-lint asserts every Bash invocation in agent files carries an explicit `timeout`.
- **Failure mode: agent runs from `.claude/worktrees/<branch>/` and `cd C:/arcis/halcyon-lab` silently lands in the wrong tree (DA1).** Defended by `cd "$(git rev-parse --show-toplevel)"` resolving to the worktree's own root + optional `WORKTREE_PATH` DYNAMIC CONTEXT override. Task 6 grep-lint asserts no agent file contains the hardcoded literal `cd C:/arcis/halcyon-lab`.
- **Failure mode: empty primary collection silently drops the audit trail (DA3).** Defended by mandatory `informational`-severity classification on empty results in every agent's OUTPUT FORMAT. An empty result is documented, not omitted.
- **Failure mode: agent echoes a multi-KB JSONB column (transient secret-bleed or turn-budget blow-up) (DA5).** Defended by the 200-char truncation rule + `[truncated]` marker on every column matching `*_jsonb` / `*_detail` / `*_payload` / `*_body`. PRComments' own pre-flight catches secrets at the post boundary; the agent-layer redaction is the defense-in-depth.
- **Failure mode: agent hits `maxTurns: 60` mid-tool-call and produces unparseable truncated JSON (DA6).** Defended by the turn-50 budget-stop: at turn 50 the agent STOPS issuing new tool invocations and reserves 10 turns for OUTPUT FORMAT composition. `coverage_assessment.coverage_judgment` honestly reports `partial` / `incomplete` when budget exhausted before mandate fully answered. Every agent's OUTPUT FORMAT now carries `coverage_assessment` (previously only db-investigator) for cross-agent comparability.
- **Failure mode: secret leaked in PRComments body.** Defended by PRComments tool layer: `_secrets.detect_secret_in_text` runs BEFORE `gh`; raises `PRCommentLeakError`. Operator-confirmed acceptable risk per interview (the pre-flight IS the boundary). Stdin-pipe pattern doesn't change this — the body still flows through the same pre-flight. DA5 agent-layer truncation provides defense-in-depth.
- **Failure mode: live-monitor mis-evaluates overnight-window (clock skew, missing tz).** Defended by Workflow Step 0 — explicit `TZ='America/New_York' date` invocation records the ET wall-clock into `snapshot_timestamp`, which is then the reference for the 21:30-22:30 ET check (per FB5).
- **Concurrency: 2 agents called in parallel both invoking DBQuery.** No conflict — DBQuery is read-only; PG handles concurrent readers natively.
- **Concurrency: live-monitor + ci-investigator both call LogTail simultaneously.** No conflict — LogTail is read-only with rotation-detect (DA5 from #105).
- **Concurrency: ci-investigator + manual operator both post to same PR.** The operator owns coordination; agent's single-post-per-invocation rule plus repost-idempotency fingerprint check (DA4) plus visible audit (`prcomments` writes a 2-row audit per the spec) makes any cross-actor races visible after the fact AND prevents the agent from re-posting on top of the operator's manual content (different fingerprint → no skip, but the operator-post is preserved).
- **Scope creep: agent suggests adding a tool.** Defended by complete-efforts-no-deferral (DOCUMENT, not act) + read-only constraint. Suggestions are findings; actions are next-effort scope.
- **Scope creep: agent posts a CHANGELOG entry.** Defended by `allowed-tools` (no Write/Edit). PRComments.post is the ONLY mutation surface, and it's TARGET-PR-SCOPED to comments + delivered via stdin-pipe (no file artifact) + repost-idempotent per DA4.
- **Operator overnight-window memory.** live-monitor's CONSTRAINTS handles this: between 21:30-22:30 ET (per Step 0 timestamp), restart recommendations are flagged-forbidden (not just executions — recommendations too, per `feedback_no_restart_during_overnight_window`).

---

## Design Decisions Log

(All 17 decisions are also recorded as full entries in `design_decisions.json` alongside this spec.)

| # | Decision | Rationale (short) | Reversibility |
|---|----------|-------------------|---------------|
| DD-1 | DD-1: Truly bare naming (db-investigator, ci-investigator, git-historian, live-monitor) — NO... | These 4 are investigator-class agents intended for cross-skill consumption (#109 arcis:operate + #110 arcis:strategy + #111 arcis:skill-audit + direct operator dispatc... | ? |
| DD-2 | DD-2: maxTurns: 60 per investigator (with turn-50 budget-stop) | Bounded-workflow investigators typically complete in 8-15 tool invocations. 60 leaves headroom for branching investigations but bounds runaway loops in `--json` parsin... | ? |
| DD-3 | DD-3: ci-investigator auto-confirms PRComments.post BUT only with explicit TARGET_PR + agent... | Operator-confirmed acceptable risk per interview — the `--confirm` flag auto-approves the mutation, but TARGET-PR-SCOPING (single explicit integer in DYNAMIC CONTEXT, ... | ? |
| DD-4 | DD-4: live-monitor's NEVER-restart boundary enumerated forbidden methods (vs allowed-tools-o... | allowed-tools: Bash lets the agent technically call any subprocess — relying on the tool list alone is insufficient. Enumerated forbidden methods in CONSTRAINTS + Work... | ? |
| DD-5 | DD-5: Bash subprocess for tool invocation (vs Python-API direct binding) | Tier 1+2 tools are designed as CLI subprocesses with `--json` envelope contract per `_cli_envelope.py`. Bash invocation matches the existing tool boundary; no new bind... | ? |
| DD-6 | DD-6: 3-5 golden questions per agent as markdown references (vs runtime tests) | LLM-output variability makes exact-match runtime tests infeasible at this maturity level. Markdown references document the expected response shape (sections, citation ... | ? |
| DD-7 | DD-7: Anti-sycophancy + complete-efforts-no-deferral in EPISTEMIC LENS (vs CONSTRAINTS) | These directives shape the agent's cognitive frame, not just its rules. Placing them in EPISTEMIC LENS ensures they influence findings-generation, not just final-outpu... | ? |
| DD-8 | DD-8: Auto-discovery (no plugin.json update) | Surface report Phase 2 confirmed ARCIS plugin uses auto-discovery — no manifest file lists individual agents. Dropping `<agent>.md` into the agents/ directory makes it... | ? |
| DD-9 | DD-9: JSON envelope parsing on every subprocess (always `--json`, always parse, surface fail... | Locked by `_cli_envelope.py` contract: success emits primary payload to stdout exit 0; failure emits `{"error": {...}}` envelope to stdout exit 1. Agents that don't pa... | ? |
| DD-10 | DD-10: git-historian uses git CLI directly today; refactors to GitArchaeology Tier 3 when #1... | #107 GitArchaeology Tier 3 tool not yet built. Direct git CLI Bash invocation works today (read-only ops only). When #107 lands, the agent's prompt refactors from `git... | ? |
| DD-11 | DD-11: Custom investigator-class OUTPUT FORMAT tags as registered enum | The 4 investigator-class tags (`<db_report>`, `<ci_report>`, `<git_report>`, `<live_report>`) carry domain semantics that a generic `<findings>` tag would lose. Conven... | ? |
| DD-12 (DA1) | DD-12 (DA1): Worktree-portable cwd via `cd "$(git rev-parse --show-toplevel)"` + optional WO... | Operator regularly dispatches agents from `.claude/worktrees/<branch>/` sub-directories (per operator memory: agent worktree accumulation + agent worktree base default... | ? |
| DD-13 (DA2) | DD-13 (DA2): Mandatory explicit per-call Bash `timeout` parameter, tiered 60/90/120s defaults | Bash tool's implicit 120s default is too coarse for the agent's bounded turn budget. A single subprocess hitting 120s consumes 1/60 of the per-agent budget AND unbound... | ? |
| DD-14 (DA3) | DD-14 (DA3): Empty primary-collection results MUST be classified as `informational` findings | An empty result is indistinguishable from a tool subprocess that bypassed parsing — silent absences violate anti-handwave (#103). Mandating an `informational`-severity... | ? |
| DD-15 (DA4) | DD-15 (DA4): ci-investigator repost-idempotency via SHA-256 fingerprint footer + prcomments ... | Operator's `feedback_hotfix_deploy_two_layer_staleness` memory + multi-agent dispatch patterns produce a real risk: ci-investigator re-dispatched against the same RUN_... | ? |
| DD-16 (DA5) | DD-16 (DA5): JSONB/TEXT redaction at agent layer — truncate `*_jsonb`/`*_detail`/`*_payload`... | Tier 1+2 tools faithfully return whatever JSONB/TEXT the DB or process emits. Agents echoing full payloads into `<reasoning>` or OUTPUT FORMAT (a) bloat turn budgets w... | ? |
| DD-17 (DA6) | DD-17 (DA6): Turn-50 budget-stop + mandatory `coverage_assessment` field on ALL FOUR investi... | An agent that hits `maxTurns: 60` mid-tool-call produces truncated OUTPUT FORMAT JSON that callers cannot parse (orchestrators like #109/#111 expect well-formed JSON).... | ? |


---

## Known Considerations (devils-advocate minor + nit findings, not blocking)

Surfaced during adversarial review; deemed below the threshold for spec revision. Documented for the implementing PM + post-merge consideration.

| # | Concern | Note |
|---|---------|------|
| KC1 | INVESTIGATION_MODE (db-investigator) and POST_SUMMARY (ci-investigator) defaults aren't explicitly stated for the absent case | Conservative defaults are implied (surface for INVESTIGATION_MODE, false for POST_SUMMARY) but the Inputs section in each agent prompt should make them explicit. Trivial fix during implementation. |
| KC2 | git-historian's bisect-shaped reasoning technique is underspecified — "logical bisect" is operator-discretion | Recommend explicit `git log --reverse --before=<RANGE_END> --after=<RANGE_START> -- <path>` + `git show <SHA>` (NOT `git checkout <SHA>` which is in the FORBIDDEN list). Implementer should add this pattern to git-historian's Workflow Step 7 prose explicitly. |
| KC3 | When ci-investigator runs with POST_SUMMARY=true but TARGET_PR absent, the refusal is encoded in `<ci_report>.post_status: refused_no_target_pr` but the human-facing markdown summary doesn't surface the refusal prominently | Recommend the agent prefix `<ci_report>.summary_markdown` with a `> **NOTE — POST REFUSED:** TARGET_PR was not provided. Operator must manually post.` blockquote. Operator-experience win. |
| KC4 (nit) | Golden-question reference files document expected response shape but cadence for re-dispatching them isn't mandated | Recommend operator re-dispatches goldens within 24h of: (a) any agent .md edit, (b) any Tier 1+2 tool CLI flag change, (c) #107 GitArchaeology landing. Add to §6 in a future minor revision; current scope deferred to #111 periodic-discipline. |

(Per devils-advocate review pass — see `arcis:design-devils-advocate` invocation 2026-05-25.)
