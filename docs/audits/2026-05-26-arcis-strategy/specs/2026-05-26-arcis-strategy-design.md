# Arcis #110 — `arcis:strategy` Skill Design Specification

**Target version:** v0.36.6X (re-baselined at impl time, current main: v0.36.65)
**PR target:** dual-Opus QA — operator-experience capstone for the research-desk track
**Status:** Spec + plan, ready for `/arcis:code --spec ... --plan ...`

---

## 0. Summary & Operator Workflow

`arcis:strategy` is the operator's single trading-strategy research surface. At 9 AM, when the operator has a hypothesis — "tighten ATR-stops on momentum names after a forensic-audit week" — they type ONE thing:

```
/arcis:strategy ideate "tighter ATR stops on post-audit momentum names"
```

…and the skill dispatches db-investigator + git-historian + research-team (domain-lead + specialist + cross-domain-analyst), composes their findings into a hypothesis report with a proposed YAML scaffold, and writes the report to `docs/strategy-ideation/`.

Then, when the hypothesis matures into a spec at `src/platform/specs/<strategy_id>.yaml`:

```
/arcis:strategy backtest post_audit_ruleset_v1
```

…and the skill drives the **full walkforward stack** via `src/platform/rigor/walkforward_runner.run_walkforward()` — R8 firewall + López de Prado purging + 5-day embargo + point-in-time S&P 100 universe + 5 historical windows. Outcome: a `walkforward_results` row with literal three-state `outcome_state` (PASS / FAIL / INCONCLUSIVE), plus per-window `walkforward_trades` rows.

For exploratory iteration:

```
/arcis:strategy backtest post_audit_ruleset_v1 --quick
```

…and the skill runs a **single in-sample backtest** via `src/platform/backtest_engine.run_backtest()`, persists to `backtest_results` + `backtest_trades`, and surfaces with the **⚠ IN-SAMPLE ONLY — not rigor-grade** banner displayed unmissably on every output line of the result block.

For statistical follow-up:

```
/arcis:strategy analyze <run_id>
```

…and the skill computes Deflated Sharpe Ratio (DSR) via `dsr.py` using current `trials_registry.N_eff`, optionally computes CSCV if ≥2 prior runs exist for the same strategy_id, surfaces the verbatim three-state `outcome_state` + reason, and recommends next steps preserving the original verdict.

For situational awareness:

```
/arcis:strategy status
```

…and the skill produces a read-only snapshot: filesystem spec catalog (via `list_available_specs()`), `strategy_registry` lifecycle states, recent backtest + walkforward runs, and an FS-vs-DB diff (specs without registry rows; registry rows without spec files; **malformed YAML files silently skipped by `list_available_specs()`** — surfaced as anomalies per `no-out-of-scope-deferral`).

**The four verbs:**

1. `/arcis:strategy ideate <theme>` — investigate prior art via db-investigator + git-historian + research-team (domain-lead + specialist + cross-domain-analyst), compose a hypothesis + counter-evidence report, write to disk, propose a strategy-YAML scaffold. **NO MUTATIONS** (writes are markdown reports only).
2. `/arcis:strategy backtest <strategy-id> [--quick]` — drive the canonical backtest stack (default = full walkforward; `--quick` = in-sample only). Writes to **local research DB** only; refuses if `ARCIS_ALLOW_PROD_PG` env var is set.
3. `/arcis:strategy analyze <run-id>` — compute DSR + PSR + (optional) CSCV against `backtest_results` or `walkforward_results`. **READ-ONLY** at the result layer; writes one `trials_registry` row per analyze invocation (FA11 — keeps N_eff fresh for downstream multiplicity correction). Surfaces literal three-state outcome.
4. `/arcis:strategy status [strategy-id]` — read-only snapshot. FS spec catalog + DB lifecycle state + recent run history + drift surface. NO confirms. NO agent dispatch.

This skill is the **research-desk capstone**: it converts every prior platform investment (canonical backtest engine per FA1, R8 firewall per FA9, walkforward runner per FA7, López de Prado purging per FA8, point-in-time universe per FA10, DSR + CSCV + trials_registry per FA11, schema registry per FA12) into a single workflow the operator invokes without remembering which sub-component to call first.

**Why state-machine (not freeform):** Backtest mutations have multi-step write paths (engine → backtest_results, then runner → walkforward_results + trials_registry, linked via `derived_from_backtest_id`). The state machine forces explicit phase transitions, AskUserQuestion at the backtest write gate, and audit-log writes at known boundaries. Mirrors `arcis:operate` (#109) structurally for operator muscle-memory.

**Why this is genuinely first-in-class:**

- First skill to compose `<db_report>` + `<git_report>` + `<findings>` (from 3 research-team agents) into a single ideation report.
- First skill to **preflight R8 at the skill layer** (FA9) — operator gets a friendly "spec missing `derived_from` key" message instead of a Python `R8ViolationError` traceback.
- First skill to orchestrate the dual-persist path (engine + runner) and link via `derived_from_backtest_id`.
- First skill to **refuse prod-PG explicitly** via the `ARCIS_ALLOW_PROD_PG` sentinel.
- First skill to preserve a three-state outcome verbatim through the entire pipeline (audit log → operator output → analyze recomputation).

**Scope expansion acknowledged (DA1 revision):** v1 includes a 1-column schema migration in `src/schema/registry.py` to add `provenance_kind` to `backtest_results`. This is the smallest possible schema change required to enforce three-state outcome preservation at the data layer (operator-confirmed Option A — schema column over runtime guard). T0 (wave 0) handles the schema migration AND a 1-kwarg signature update to `src/platform/backtest_persist.py:persist_backtest_result` to accept the new column. All other code-touching scope remains markdown/orchestration; T0 is the only Python edit.

**Defense-in-depth layers added (DA-revision pass):**

- **DA2/DA7** — Spec snapshot at B1 to `data/logs/spec_snapshots/<run_id>.yaml`; B7 heredoc loads from snapshot (not live file). Eliminates the 5-second mutation window between B5 confirm and B7 execute, AND the 5-window mid-loop drift.
- **DA4** — Audit-event sequence on the per-window loop (`wf_run_attempt` / `window_persisted` / `wf_complete` OR `wf_partial`); on partial-run failure, AskUserQuestion offers `provenance_kind='wf_is_window_orphan_partial_run'` backfill for forensic inspection.
- **DA5** — Portalocker file-lock at `data/locks/strategy/<strategy_id>.lock` prevents concurrent multi-session backtests on the same strategy.
- **DA9** — Post-resolution `db_path` inspection refuses prod-PG DSN signatures inside the heredoc, immediately before any persist call (defense-in-depth to the `ARCIS_ALLOW_PROD_PG` env sentinel).

---

## 1. File Structure

| Path | Purpose | Est. lines |
|------|---------|------------|
| `.claude/plugins/arcis/skills/strategy/SKILL.md` | Descriptor — user-facing surface for skill listing / discovery | 95 |
| `.claude/plugins/arcis/commands/strategy.md` | Orchestrator — slash-command executable. Parses verb + dispatches per-verb phase machines. | 540 |
| `.claude/plugins/arcis/skills/strategy/references/verb-conventions.md` | Reference — argument parsing table, error envelopes, JSON envelope contract, agent dispatch convention. Single source of truth referenced from `commands/strategy.md`. | 95 |
| `.claude/plugins/arcis/skills/strategy/references/rigor-stack-integration.md` | Reference — R8 firewall preflight, purging + embargo guarantees, point-in-time universe semantics, three-state outcome reducer. Cited by backtest + analyze verb prose. | 110 |
| `.claude/plugins/arcis/skills/strategy/references/statistical-rigor.md` | Reference — DSR + PSR + CSCV semantics, trials_registry N_eff bookkeeping, T<30 fallback, paper-erratum notes. Cited by analyze verb prose. | 95 |
| `.claude/plugins/arcis/skills/strategy/references/error-envelopes.md` | Reference — error envelope shapes the operator sees for each failure class | 70 |
| `.claude/plugins/arcis/skills/strategy/templates/strategy-spec-scaffold.yaml` | Template — empty derived_from-compliant strategy YAML scaffold the `ideate` verb emits | 50 |
| `.claude/plugins/arcis/skills/strategy/templates/ideation-report-template.md` | Template — header / hypothesis / evidence / counter-evidence / proposed spec body shape `ideate` writes to `docs/strategy-ideation/` | 80 |
| `src/schema/registry.py` (modified — T0 wave 0) | **DA1 schema migration** — add `provenance_kind` TEXT NOT NULL CHECK column to the `backtest_results` TABLES dict entry. +1 column; no migration script needed (registry.py is the source of truth — `bootstrap_db` re-applies the dict on startup). | (+1 column line) |
| `src/platform/backtest_persist.py` (modified — T0 wave 0) | **DA1 signature update** — add `provenance_kind: str` kwarg to `persist_backtest_result()` (currently `(result, *, db_path, git_sha='unknown')` per src/platform/backtest_persist.py:30); add the new column to the INSERT statement. NOT optional — schema CHECK constraint refuses NULL. | (+3 lines) |
| `CHANGELOG.md` (modified) | Add v0.36.6X entry — "Skill: `/arcis:strategy` ships with 4 verbs (ideate / backtest / analyze / status) + provenance_kind column on backtest_results" | (~3 lines added) |

**Schema diff (T0, DA1):** In `src/schema/registry.py`'s `TABLES` dict, the `backtest_results` entry gets the line:

```sql
ALTER TABLE backtest_results ADD COLUMN provenance_kind TEXT NOT NULL
  CHECK (provenance_kind IN ('quick_in_sample', 'wf_is_window', 'wf_is_window_orphan_partial_run'))
```

Equivalently, the existing CREATE TABLE clause in registry.py is extended in-place with the same column + CHECK constraint. Since registry.py is the source of truth and `bootstrap_db()` is idempotent, no separate migration script is needed — fresh-database starts pick up the column from registry.py, and existing-database starts apply the ALTER on first invocation via the existing bootstrap path.

**Persist signature update (T0, DA1):** `persist_backtest_result(result, *, db_path, git_sha='unknown')` → `persist_backtest_result(result, *, db_path, provenance_kind, git_sha='unknown')`. `provenance_kind` is **required** (no default — the CHECK constraint refuses NULL, and the caller always knows which kind it is writing). The INSERT statement at backtest_persist.py:48-54 gets `provenance_kind` appended to the column list + VALUES tuple.

**Note on layout:** References live at `skills/strategy/references/` (same convention as `coding-team/references/`, `research-team/references/`, `operate/references/` — adopted as standard for skills with operator-facing reference docs). Templates live at `skills/strategy/templates/` (greenfield for skills — no prior precedent; rationale: ideation verb writes both a markdown report AND a proposed YAML scaffold, both authored from on-disk templates the implementing PM keeps in sync with the live `StrategySpec` contract).

**Total surface:** 8 new files + 3 modified files (CHANGELOG + src/schema/registry.py + src/platform/backtest_persist.py). All markdown/YAML for the new files; the 2 Python edits are 1+3 lines each (T0 scope).

---

## 2. SKILL.md Descriptor

**FULL VERBATIM CONTENT** of `.claude/plugins/arcis/skills/strategy/SKILL.md`:

```markdown
---
name: strategy
description: Trading-strategy research workflow — ideate hypotheses via specialized agents, drive the canonical backtest + walkforward + statistical-rigor stack, compute Deflated Sharpe + CSCV, surface three-state PASS/FAIL/INCONCLUSIVE outcomes. Writes ONLY to local research DB; refuses prod-PG. Composes the src/platform/ backtest engine + src/platform/rigor/ pipeline with the 4 specialized agents (#108) and research-team agents.
---

# Strategy

This skill provides the `/arcis:strategy` command for trading-strategy ideation, backtest orchestration, statistical analysis, and registry visibility on the halcyon-lab research desk.

## Approach: Verb-Dispatched State Machine

1. **PARSE** — Extract verb (`ideate` | `backtest` | `analyze` | `status`) from POSITIONAL_INPUT[0]; parse verb-specific args.
2. **ENV GATE** — For the `backtest` verb only: refuse if `ARCIS_ALLOW_PROD_PG` env var is set (any truthy value). The skill writes ONLY to the local research DB; the prod-PG sentinel is a defense-in-depth refusal at the skill layer on top of the tool-layer `@prod_guard` decorator.
3. **SPEC RESOLUTION** — For `backtest` / `analyze` / per-strategy `status`: resolve `strategy_id` via filesystem (`load_spec(strategy_id)` per FA2) — filesystem is canonical for existence. DB `strategy_registry` is canonical for lifecycle state and is joined on top.
4. **R8 PREFLIGHT** (backtest only) — Validate the spec YAML has `derived_from` key (null OR full dict) via `walkforward_firewall.validate_derived_from()`. Surface `R8ViolationError` at the skill layer with operator-readable framing BEFORE invoking `run_walkforward()`.
5. **DISPATCH** — Invoke tools via `python -m src.tools.<name> --json`; invoke runner via `python -c "..."` inline subprocess; dispatch agents via `Agent(subagent_type: "<name>")`. Parse JSON envelopes and registered output tags (`<db_report>`, `<git_report>`, `<findings>`).
6. **COMPOSE** — When the `ideate` verb fires 3-5 agents, merge findings into one operator-facing hypothesis report (OR-of-evidence rule for supporting findings; surface ALL counter-evidence; no silent drops).
7. **CONFIRM** — The `backtest` verb requires a single operator confirm before invocation (writes ~MB of rows; takes minutes). Other verbs are read-only or write-tiny-report-files-only; no confirm needed.
8. **EXECUTE & VERIFY** — Execute backtest stack; after walkforward persist, re-query `walkforward_results` and `trials_registry` row counts to confirm the writes landed.
9. **AUDIT** — Write a skill-level event to `data/logs/tool-execution.log` with `tool_name="arcis_strategy.<verb>"` and a per-run `RUN_ID` (backtest/analyze) or `SESSION_ID` (ideate). Per-tool events inherited from the decorator stack. `status` is read-only and writes no skill-level audit event.

## Agent Hierarchy

```
Strategy Director (command orchestrator, opus)
├── db-investigator (opus, maxTurns:60)        — DB substrate for strategy ideation: relevant table coverage,
│                                                 prior backtest result hits, fills/recommendations history.
│                                                 Read-only. Dispatched in ideate only.
├── git-historian (opus, maxTurns:60)          — Temporal git archaeology over src/platform/specs/ + strategy_registry
│                                                 commits + prior strategy YAML rationale. Read-only. Dispatched in ideate only.
├── research-domain-lead (opus, maxTurns:100)  — Domain-bounded research over financial-economic preset.
│                                                 Spawns specialists. Returns <findings> JSON.
├── research-specialist (sonnet, maxTurns:100) — Spawned by domain-lead; depth-2 sub-investigation.
│                                                 Returns <findings> JSON with confidence ≤ Moderate.
└── research-cross-domain-analyst (opus, ...)  — Reads DOMAIN_REPORTS, surfaces synthesis + tensions. Optional.
                                                  Dispatched in ideate only on operator-confirm.
```

The orchestrator does NOT have its own subagent file — it lives in `commands/strategy.md` and dispatches the 5 referenced agents directly. None of the agents are owned by this skill; they are inherited as read-only sensors.

## Key Properties

- **Skill-layer R8 preflight** — defense-in-depth: the skill validates `derived_from` BEFORE invoking the walkforward runner, so the operator sees a clean refusal with a remediation hint rather than a Python traceback from the firewall raise.
- **Prod-PG refusal** — `ARCIS_ALLOW_PROD_PG` is treated as a no-go sentinel. The skill never writes outside the local research DB target. If the sentinel is set, the backtest verb refuses with an explicit error envelope.
- **Mutation confirmation gate** — every `backtest` invocation requires a single `AskUserQuestion` approval (the only writeable verb in v1). Operator sees the full plan + estimated runtime + write target before approval.
- **Dual-persist orchestration** — full-walkforward backtest writes BOTH `backtest_results` (one per IS window) AND `walkforward_results` (one aggregate). The aggregate's `derived_from_backtest_id` links to the IS row; the operator can JOIN both layers for full provenance.
- **Three-state outcome preservation** — `walkforward_results.outcome_state ∈ {PASS, FAIL, INCONCLUSIVE}` surfaces verbatim through audit log and operator output. NEVER collapses to boolean.
- **No out-of-scope deferral** — within an invocation, the skill surfaces ALL discovered defects to the operator (e.g., malformed YAML files filtered silently by `list_available_specs()` — FA2 line 392 — are surfaced as anomalies). The skill never silently defers to a "follow-up task."
- **Trials_registry stewardship** — every `analyze` invocation calls `trials.record_trial()` to keep the global N_eff counter fresh for DSR's multiplicity correction. The backtest verb also records a trial entry per invocation (param-sweep or otherwise; see §8).
- **Post-execution verification** — after walkforward persist, the skill re-queries `walkforward_results` and `trials_registry` row counts to confirm the writes landed. Surfaces row IDs to operator.
- **Audit trail by inheritance + skill-layer summary** — per-tool events land in `data/logs/tool-execution.log` automatically; the skill also writes bracketing `arcis_strategy.<verb>.started` and `arcis_strategy.<verb>.completed` events keyed by `RUN_ID` / `SESSION_ID`.

## Verbs

| Verb | Behavior | Writes | Agent dispatch |
|------|----------|--------|----------------|
| `ideate <theme>` | Investigate prior art, propose hypothesis + spec scaffold | Markdown report to docs/strategy-ideation/ | db-investigator + git-historian + 3 research-team agents |
| `backtest <id> [--quick]` | Execute backtest stack (default WF; --quick = in-sample) | backtest_results / walkforward_results / walkforward_trades / trials_registry rows in LOCAL DB | None |
| `analyze <run-id>` | Compute DSR + PSR + CSCV; surface 3-state outcome | trials_registry row (one per analyze invocation) in LOCAL DB | None |
| `status [strategy-id]` | Read-only snapshot; FS-vs-DB diff | None | None |

## Arguments

| Flag | Purpose |
|------|---------|
| `<positional>[0]` | Verb (`ideate` / `backtest` / `analyze` / `status`) — required |
| `<positional>[1...]` | Verb-specific args (theme string / strategy-id / run-id) |
| `--quick` | For `backtest`: in-sample only (skip walkforward); surface ⚠ banner |
| `--no-cross-domain` | For `ideate`: skip the cross-domain-analyst pass (save ~3 min) |
| `--run-id <id>` | Continue a prior run (replays RUN_ID into audit stream) |
| `--out <path>` | For `ideate`: override default `docs/strategy-ideation/<date>-<slug>.md` write path |

## Out of scope (v1)

- Auto-execution of backtest without operator confirmation.
- Promotion of a strategy to `shadow_trading` or `production` — see #119 (future).
- Invoking `src/evaluation/` modules (canonical backtester is `src/platform/`).
- Invoking `scripts/run_backtest.py` directly (`--with-walkforward` deprecated as of #118; the skill invokes `run_backtest()` + `run_walkforward()` via Python directly).
- Invoking `src/platform/rigor/walkforward.py:run_walkforward` (non-rigor path; reconciled by #118).
- Real-money trading.
- Writing to prod PG.
- Collapsing the three-state outcome to a boolean.
```

---

## 3. commands/strategy.md Orchestrator

**FULL VERBATIM CONTENT** of `.claude/plugins/arcis/commands/strategy.md` (the executable orchestrator the LLM reads at slash-command invocation):

```markdown
---
name: strategy
description: "Trading-strategy research workflow — ideate / backtest / analyze / status. Composes the src/platform/ backtest engine + rigor stack with 5 specialized + research-team agents. Writes ONLY to local research DB."
---

# Strategy — Research-Desk Director

You are the Director of the ARCIS Strategy skill. The operator invokes you at 9 AM with a hypothesis or a registered strategy. Your job: dispatch the right agents (ideate) or drive the canonical rigor stack (backtest) or compute statistical follow-ups (analyze) or surface registry state (status). You do NOT diagnose with your own reasoning when an investigator agent exists for the domain — you dispatch the agent and synthesize its findings.

## NO OUT-OF-SCOPE DEFERRAL

Within an invocation, you must surface ALL discovered defects to the operator. If `status` finds 3 malformed YAML files alongside the requested strategy lookup, your output lists all 3 — never "we'll handle the other 2 later." If you find a defect in adjacent code while running a backtest (e.g., an FS-vs-DB drift where a `strategy_registry` row has no matching spec file, or a `walkforward_results` row with a NULL `derived_from_backtest_id`), surface it as a numbered finding alongside the primary result. The operator decides what to act on now vs. queue. You do not silently defer.

**This is the operator's explicit standard** (memory: `feedback_complete_efforts_no_deferral`). Honor it verbatim in every ideate report, every backtest result, every analyze recommendation, every status snapshot.

## ARGUMENT PARSING

Parse the user's input for these flags:

| Flag | Variable | Default |
|------|----------|---------|
| `--quick` | `QUICK` | false |
| `--no-cross-domain` | `NO_CROSS_DOMAIN` | false |
| `--run-id <id>` | `RUN_ID_OVERRIDE` | null |
| `--out <path>` | `OUT_PATH` | null |

Then split the remaining tokens (everything before/between/after flags) as `POSITIONAL_INPUT[]`.

- `POSITIONAL_INPUT[0]` is the **VERB** — required. One of: `ideate` | `backtest` | `analyze` | `status`.
- `POSITIONAL_INPUT[1...]` is verb-specific (see per-verb sections below).

If `RUN_ID_OVERRIDE` is null, generate a fresh id at the verb entry point. Distinguish two flavors:

- `ideate` verb: `SESSION_ID="$(date -u '+ideate-%Y-%m-%dT%H-%M-%SZ')-$(python -c "import secrets; print(secrets.token_hex(3))")"`
- `backtest` / `analyze`: `RUN_ID="$(date -u '+run-%Y-%m-%dT%H-%M-%SZ')-$(python -c "import secrets; print(secrets.token_hex(3))")"`
- `status`: no audit id (read-only, no skill-level audit event written).

Result shape examples: `ideate-2026-05-26T13-15-00Z-9c3f1a`, `run-2026-05-26T13-15-00Z-7a02fc`. Store as `SESSION_ID` or `RUN_ID` and use as the `session_id` argument for every audit-log write in this invocation.

**If `--run-id` flag is supplied:**

1. Regex-validate: `^(ideate|run)-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z-[0-9a-f]{6}$`. On mismatch → ERROR envelope `unknown run-id format: '<received>'`. STOP.
2. If matches existing audit event in last 1 hour: AskUserQuestion: `"A run with id <id> already has audit events in last hour. Merge into that stream?"` — options: `"Yes — merge"`, `"Cancel"`. Cancel → STOP.
3. Otherwise, use as-is.

### Verb-unknown handling

If `POSITIONAL_INPUT[0]` is missing or not in {`ideate`, `backtest`, `analyze`, `status`}:

1. Print:
   ```
   ERROR — unknown verb: "<received>". Expected one of: ideate, backtest, analyze, status.
   Usage:
     /arcis:strategy ideate "<theme>"                  — investigate prior art + propose spec scaffold
     /arcis:strategy backtest <strategy-id> [--quick]  — drive backtest stack (default walkforward; --quick = IS only)
     /arcis:strategy analyze <run-id>                  — compute DSR + PSR + CSCV; surface 3-state outcome
     /arcis:strategy status [strategy-id]              — read-only registry + recent-runs snapshot
   ```
2. STOP. Do NOT proceed to any phase. Do NOT write to audit log.

### PROD-PG GATE (backtest only)

Run only on `VERB == backtest`. Before any other phase:

```bash
if [ -n "${ARCIS_ALLOW_PROD_PG}" ]; then
  echo "REFUSE — ARCIS_ALLOW_PROD_PG is set."
  echo "  Reason: arcis:strategy writes ONLY to local research DB. Prod-PG writes are forbidden by skill policy."
  echo "  Resolution: unset ARCIS_ALLOW_PROD_PG and re-run."
  exit 1
fi
```

Write `arcis_strategy.backtest.prod_pg_refused` audit event. STOP.

This is the skill-layer gate. The tool-layer `@prod_guard` decorator is the floor (catches DSN-string signatures `localhost:5433` / `127.0.0.1:5433` / `halcyon_app:` — see FA17). The env-var sentinel is the ceiling.

---

## PHASE 0: COMMON PREAMBLE (all verbs)

### Step 0.1 — Capture ET wall-clock (audit-prelude only)

```bash
NOW_ET=$(python -c "import os, datetime; from zoneinfo import ZoneInfo; o=os.environ.get('ARCIS_NOW_ET_OVERRIDE'); now=datetime.datetime.fromisoformat(o) if o else datetime.datetime.now(ZoneInfo('America/New_York')); print(now.strftime('%Y-%m-%d %H:%M %Z'))")
```

Store as `NOW_ET`. Used in audit-prelude bracket events ONLY. The skill has no safety-window check (no overnight gate for research), so the env-var override has no operational effect — kept for parity with #109 audit prelude.

### Step 0.2 — Verify working directory

```bash
cd "$(git rev-parse --show-toplevel)" 2>&1 || cd "$WORKTREE_PATH"
pwd
```

If neither resolves, refuse with the §10 ERROR envelope `cannot resolve repo root via git rev-parse`. STOP.

### Step 0.3 — Write run-start audit event

Skip if `VERB == status` (read-only).

```bash
python - <<PY
from src.tools._execution_log import write_event
import json, os
positional = json.loads(os.environ['POSITIONAL_INPUT_JSON'])
write_event(
    tool_name=f"arcis_strategy.{os.environ['VERB']}.started",
    params={"positional": positional, "flags": {"quick": $QUICK, "no_cross_domain": $NO_CROSS_DOMAIN}},
    result="success",
    duration_ms=0,
    session_id=os.environ['SESSION_ID_OR_RUN_ID'],
)
PY
```

**stdin-driven shell-out (mirror #109 DA3 fix):** every operator-typed string passes through environment / stdin, NEVER inline interpolation into the Python string. The orchestrator MUST set `POSITIONAL_INPUT_JSON` env var (JSON-escaped operator input) before calling the snippet. Inline interpolation of operator strings into Python code is forbidden — it leaks shell-meta on every operator typo.

Failure of this write is non-blocking. Log a warning, continue.

### Step 0.4 — Tier-1+2+3 availability probe (status / ideate only)

Status and ideate verbs may compose tool subprocesses (dbquery, gitarchaeology). Probe availability:

```bash
for tool in dbquery gitarchaeology; do
  python -m src.tools.$tool --help 2>/dev/null 1>/dev/null && echo "$tool=available" || echo "$tool=missing"
done
```

Store as `TOOL_AVAILABLE[<name>]`. On any `missing`, the affected verb step warns + continues per the §10 graceful-degradation pattern. Do NOT crash. The backtest verb does NOT use the tool layer (it invokes the runner via Python directly).

---

## VERB: ideate

**Usage:** `/arcis:strategy ideate "<theme>"`

Ideate is **READ-ONLY at the platform layer**. It writes only a markdown report to `docs/strategy-ideation/`. AskUserQuestion budget: ≤2 per invocation (theme-clarification if unclear; cross-domain-confirm).

### Phase I1 — Theme classification

`POSITIONAL_INPUT[1...]` joined by spaces is the `THEME` string. If empty:

```
ERROR — ideate requires a theme. Usage: /arcis:strategy ideate "<theme>"
  Example: /arcis:strategy ideate "tighter ATR stops on post-audit momentum names"
```

STOP.

Classify the theme using keyword heuristics for what data substrate matters:

| Keyword in $THEME (case-insensitive) | Likely focus tables | Dispatch hint |
|---|---|---|
| `atr`, `stop`, `target`, `exit`, `trailing` | backtest_trades, strategy_registry, recommendations | db-investigator focused on exit metadata |
| `audit`, `forensic`, `post-audit`, `ruleset` | shadow_trades, audit_reports, strategy_registry | db-investigator focused on forensic_audit lineage |
| `momentum`, `factor`, `lazy prices`, `event-driven` | edgar_filings, sp100_historical_constituents | db-investigator focused on signal source coverage |
| `walkforward`, `oos`, `r8`, `firewall` | walkforward_results, walkforward_trades, trials_registry | db-investigator focused on prior WF runs |
| `regression`, `worked before`, `last quarter` | git_log on src/platform/specs/, strategy_registry | git-historian primary |
| (no keyword match) | (broad) | go to AskUserQuestion below |

If theme was **unclear** (no keyword match), use AskUserQuestion to disambiguate:

> Theme "$THEME" does not match a known signal area. Which is closest?
> - "Exit / stop / target mechanics"
> - "Forensic-audit derived signals"
> - "Factor / event-driven signals"
> - "Walkforward / OOS / statistical-rigor concerns"
> - "Regression vs. a prior commit"
> - "Other / broad exploration — proceed with no focus tables"

Then re-derive focus + dispatch hints.

### Phase I2 — Parallel dispatch (5 agents in a single Agent batch)

Dispatch ALL 5 agents in parallel (single message with 5 `Agent(...)` blocks).

**Note on the agent merge algorithm (Decision DD-11 in §13):** The 5 agents fire in **two waves**. Wave A (db-investigator + git-historian + research-domain-lead) fires immediately. The research-domain-lead internally spawns its own research-specialists per the agent's own contract — those are NOT counted as separate skill-level dispatches. Wave B (research-cross-domain-analyst) fires ONLY after Wave A reports return, because the cross-domain-analyst's DYNAMIC CONTEXT requires `DOMAIN_REPORTS` from completed leads. If `NO_CROSS_DOMAIN=true`, skip Wave B.

**DYNAMIC CONTEXT for db-investigator:**
```
## DYNAMIC CONTEXT

**MANDATE:** Investigate trading-strategy data substrate available for theme: "{THEME}". Focus on coverage, prior backtest results, and any data anomalies that would block backtesting this idea. Read-only.
**INVESTIGATION_MODE:** surface
**INITIAL_HYPOTHESIS:** "{Director's best guess based on keyword classification}"
**FOCUS_TABLES:** {classified focus tables from I1, comma-separated}
**WORKTREE_PATH:** {pwd from Step 0.2}
```

**DYNAMIC CONTEXT for git-historian:**
```
## DYNAMIC CONTEXT

**MANDATE:** Survey prior strategy YAML commits + strategy_registry mutations related to theme: "{THEME}". Identify abandoned ideas, recently-shelved strategies, and any commit-message rationale that would inform this hypothesis.
**TARGET_SYMBOL:** null
**VERSION_RANGE:** "last 90d"
**PATH_FILTER:** "src/platform/specs/,src/schema/registry.py,src/platform/strategy_spec.py"
**WORKTREE_PATH:** {pwd from Step 0.2}
```

**DYNAMIC CONTEXT for research-domain-lead:**
```
## DYNAMIC CONTEXT

**ORIGINAL_QUERY:** "{THEME}"
**DOMAIN:** financial-economic
**DOMAIN_PRESET_PATH:** ".claude/plugins/arcis/skills/research-team/references/domain-presets/financial-economic.md"
**RIGOR:** moderate
**MAX_DEPTH:** 2
**SUB_AGENT_BUDGET:** 3 specialists
**FRESHNESS:** "last 24 months"
**OPERATOR_NOTES:** "Output should be consumable by a research-desk operator iterating on a YAML strategy spec. Surface academic + practitioner literature, market-regime applicability, and known counter-evidence."
```

(The domain-lead then spawns 0-3 research-specialists per its own contract; those are observable in the agent's `<findings>.specialist_reports[]` block, not at the orchestrator level.)

**DYNAMIC CONTEXT for research-cross-domain-analyst (Wave B, conditional):**
```
## DYNAMIC CONTEXT

**ORIGINAL_QUERY:** "{THEME}"
**DOMAIN_REPORTS:** {JSON list of the <findings> blocks from research-domain-lead}
**DOMAIN_SUMMARIES:** {<reasoning> blocks from same}
**CROSS_DOMAIN_HOOKS:** {extracted from domain-lead's findings.cross_domain_hooks[] if present, else []}
**TASK:** "Surface tensions between the domain-lead's narrative and the db-investigator's substrate report. Identify any gap where the proposed strategy would face data-availability or operational risk not surfaced by either source individually."
```

**TOTAL_WALL_CLOCK_BUDGET for Wave A:** 8 minutes (3 agents in parallel; the domain-lead with its specialist sub-tree is the slowest). If any Wave A agent has not returned at 8 min, mark it `source: agent_timeout` and proceed to I3 with the available reports. The domain-lead's specialists are NOT separately timeboxed at the orchestrator level — they roll up under the domain-lead's 8-min budget.

**TOTAL_WALL_CLOCK_BUDGET for Wave B:** 5 minutes.

### Phase I3 — Compose findings into hypothesis report

**DA6 — Minimum agent set + degraded-banner pattern:**

Before composing, gate on the I2 wave-return status. Define "returned" precisely: the agent's tagged report block contains **at least 1 `key_finding`** (NOT just an empty response shell).

| Required-agent state | Action |
|---|---|
| `research-domain-lead` did NOT return ≥1 key_finding within 8-min Wave A budget | **INCOMPLETE — DO NOT SYNTHESIZE.** Surface ERROR envelope §10.15 (below). Audit `arcis_strategy.ideate.incomplete_no_spine`. STOP. |
| `research-domain-lead` returned + db-investigator + git-historian returned | Proceed to normal synthesis. |
| `research-domain-lead` returned but db-investigator OR git-historian timed out / failed | Proceed with **DEGRADED synthesis** — prepend the operator-facing summary's line 1 with `⚠ IDEATE DEGRADED — N of M agents returned; synthesis is partial.` |

**§10.15 envelope — IDEATE INCOMPLETE:**

```
ERROR — ideate: research-domain-lead did not return findings within Wave A budget (8 min).

  research-domain-lead is REQUIRED for synthesis — it carries the literature spine without
  which the merge algorithm has no structured narrative to anchor db-investigator's substrate
  findings or git-historian's code evolution against.
  
  Wave A status:
    research-domain-lead: $STATUS  (TIMEOUT | no_output_tag | empty_findings)
    db-investigator:      $DB_STATUS
    git-historian:        $GIT_STATUS
  
  Resolution: re-run with extended budget:
    /arcis:strategy ideate "$THEME" --extended-wave-a-budget 16   (raises budget to 16 min)
  Or dispatch research-domain-lead directly for diagnostic:
    /arcis:research domain-lead "$THEME"   (standalone invocation; surfaces underlying agent failure)
  
  No report written. No partial synthesis surfaced.
```

Parse the registered output tags from each agent:

- `<db_report>` per `db-investigator.md:59`: `findings[]`, `coverage_assessment`
- `<git_report>` per `git-historian.md:99`: `findings[]`, `bisect_result`, `coverage_assessment`
- `<findings>` per `research-domain-lead.md:198+`: `key_findings[]`, `evidence_digest[]`, `specialist_reports[]`, `synthesis`
- `<findings>` per `research-cross-domain-analyst.md:110+`: `cross_domain_tensions[]`, `synthesis`

**Composition algorithm (Decision DD-12 in §13):**

1. Collect all findings/key_findings/correlations from all agents, tagging each with `source_agent`.
2. **Categorize as one of three kinds:**
   - **Supporting evidence** — finding that supports the hypothesis (e.g., "factor exposure has been historically tradeable", "post-audit strategies have shown OOS Sharpe > 1.0 in 2 prior runs")
   - **Counter-evidence** — finding that argues against the hypothesis (e.g., "lazy_prices_v1 was shelved citing post-2023 alpha decay", "data coverage on edgar_filings has gaps Q3 2024")
   - **Operational concern** — finding about substrate/data/code availability (e.g., "edgar_filings table has 12% NULL on signal_score in last 6mo", "git log shows derived_from key was added in commit X, predates 3 specs that lack it")
3. **Dedup criteria:** two findings are duplicates if they share `(symbol_or_table, claim_kind)` where `claim_kind` is one of `{exposure_validity, data_coverage, prior_result, regime_dependence}`. Preserve both source references in `evidence_sources[]`.
4. **Ordering:** within each kind, sort by `confidence` desc (High → Moderate → Low), then by `source_agent` (research-domain-lead → db-investigator → git-historian → research-cross-domain-analyst). Print Supporting → Counter → Operational in that order.
5. **Synthesis paragraph:** ≤300 words. Director composes from research-domain-lead's `synthesis` field as the spine, weaves in db-investigator's `coverage_assessment` and git-historian's commit rationale as substrate validation, and surfaces cross-domain-analyst's tensions in a "but consider" subsection if Wave B ran.
6. **Proposed YAML scaffold:** Director emits an annotated stub from `templates/strategy-spec-scaffold.yaml`, pre-filling:
   - `strategy_id:` blank for operator to fill
   - `display_name:` derived from theme
   - `derived_from: null` (MUST be present per R8 — Director writes the literal key with `null` value to make R8-compliance explicit)
   - `entry.kind:` Director's best guess from theme keywords (`event_driven` if "audit" or "factor"; `scheduled` if "daily" / "weekly")
   - `universe.tickers: sp100` (default)
   - `position_sizing` / `exit` blocks: `# TODO — fill from research synthesis above`

### Phase I4 — Write report

Resolve OUT_PATH:

- If `--out <path>` supplied: validate path is writable, use it.
- Else: `OUT_PATH="docs/strategy-ideation/$(date -u '+%Y-%m-%d')-$(echo "$THEME" | tr ' ' '-' | head -c 50 | tr -dc 'a-zA-Z0-9-').md"`

Write the report using the `templates/ideation-report-template.md` shape. Header includes: SESSION_ID, NOW_ET, theme, agents dispatched, agents succeeded/failed. Body: synthesis + supporting / counter / operational findings + proposed YAML scaffold.

### Phase I5 — Operator-facing summary

Print to operator. **ALL findings shown; first 5 per category in detail; remaining as one-line summary each.** Mirrors #109 §3 Phase T5.

```
IDEATION $SESSION_ID — COMPLETE
Theme: $THEME
Captured: $NOW_ET
Wave A agents: $WAVE_A_LIST (succeeded: $WAVE_A_SUCCESS; failed: $WAVE_A_FAIL)
Wave B agent: $WAVE_B_STATUS (skipped if --no-cross-domain)
Report written: $OUT_PATH

SYNTHESIS (verbatim, ≤300 words):
$SYNTHESIS

SUPPORTING EVIDENCE ($N_SUP total — first 5 in detail):
1. [$CONFIDENCE] $TITLE — source: $AGENT
   $EVIDENCE (≤200 chars)
2. ...

(items 1-5 in detail; remaining as one-line each ordered same)

COUNTER-EVIDENCE ($N_COUNTER total):
1. ... (same shape)

OPERATIONAL CONCERNS ($N_OPS total):
1. ... (same shape)

PROPOSED NEXT ACTIONS:
  A. Open $OUT_PATH and refine the YAML scaffold.
  B. /arcis:strategy backtest <strategy_id> --quick    (once spec exists; in-sample sanity check)
  C. /arcis:strategy backtest <strategy_id>            (default = full walkforward; rigor-grade)
```

### Phase I6 — Audit completion

Write `arcis_strategy.ideate.completed` event:

```python
params={
  "theme": THEME,
  "wave_a_dispatched": WAVE_A_LIST,
  "wave_a_succeeded": WAVE_A_SUCCESS,
  "wave_b_dispatched": (not NO_CROSS_DOMAIN),
  "out_path": OUT_PATH,
  "supporting_count": N_SUP,
  "counter_count": N_COUNTER,
  "operational_count": N_OPS,
}
```

---

## VERB: backtest

**Usage:** `/arcis:strategy backtest <strategy-id> [--quick]`

Backtest is the **only writeable verb**. Goes through PROD-PG GATE (at orchestrator entry), then SPEC RESOLUTION + R8 PREFLIGHT + AskUserQuestion confirm + execute + verify + persist. AskUserQuestion budget: ≤1 per invocation (the action itself; ≤2 if state-change between confirm-time and execute-time triggers re-confirm per Step B5.1).

### Phase B1 — Spec resolution

`POSITIONAL_INPUT[1]` is `STRATEGY_ID`. If empty:

```
ERROR — backtest requires a strategy id. Usage: /arcis:strategy backtest <strategy-id> [--quick]
  Known specs: $(python -c "from src.platform.strategy_spec import list_available_specs; print(', '.join(list_available_specs()))")
```

STOP.

Resolve the spec via:

```bash
STRATEGY_ID="$STRATEGY_ID" python - <<'PY'
import json, os, sys
from src.platform.strategy_spec import load_spec
try:
    spec = load_spec(os.environ["STRATEGY_ID"])
    print(json.dumps({
        "ok": True,
        "strategy_id": spec.strategy_id,
        "display_name": spec.display_name,
        "source": spec.source,
        "spec_hash": __import__("src.platform.backtest_persist", fromlist=["spec_hash"]).spec_hash(spec.raw),
        "status_in_yaml": spec.raw.get("status"),
        "derived_from_present": "derived_from" in spec.raw,
        "derived_from_value": spec.raw.get("derived_from"),
        "entry_kind": spec.entry.get("kind"),
    }))
except FileNotFoundError as e:
    print(json.dumps({"ok": False, "error_type": "FileNotFoundError", "message": str(e)}))
    sys.exit(1)
except ValueError as e:
    print(json.dumps({"ok": False, "error_type": "ValueError", "message": str(e)}))
    sys.exit(1)
PY
```

Parse the JSON envelope. On `ok=false`:

```
ERROR — spec resolution failed for "$STRATEGY_ID":
  Type: $ERROR_TYPE
  Detail: $MESSAGE
  Resolution: confirm spec file exists at src/platform/specs/$STRATEGY_ID.yaml and passes validate_spec().
```

STOP. Write `arcis_strategy.backtest.spec_resolution_failed` audit event.

On `status_in_yaml == "shelved"`:

> Strategy $STRATEGY_ID is marked `status: shelved` in its YAML (per FA3 — e.g., lazy_prices_v1).
> Shelved strategies should not normally be backtested (the operator already removed them from the live catalog).
> Proceed anyway?
> - "Yes — backtest a shelved strategy" — continue
> - "No — abort" — STOP, write `arcis_strategy.backtest.shelved_abort` audit event

On `entry_kind == "python_plugin"`:

```
ERROR — strategy $STRATEGY_ID has entry.kind="python_plugin", which is not supported in v1 (per backtest_engine.py:386 — raises NotImplementedError).
  Resolution: file an issue or rewrite the spec as scheduled / event_driven.
```

STOP. Write `arcis_strategy.backtest.python_plugin_unsupported` audit event.

**Phase B1.5 — Spec snapshot (DA2 — eliminates 5-second + 5-window mutation windows):**

After B1's spec resolution succeeds, snapshot the live YAML file contents to `data/logs/spec_snapshots/<RUN_ID>.yaml` BEFORE the existing B1 spec-hash capture. The snapshot is the binding contract for the entire run — every subsequent phase loads spec from the snapshot path, not from `src/platform/specs/<id>.yaml`.

```bash
SNAPSHOT_DIR="data/logs/spec_snapshots"
mkdir -p "$SNAPSHOT_DIR"
SPEC_SNAPSHOT_PATH="${SNAPSHOT_DIR}/${RUN_ID}.yaml"
cp "src/platform/specs/${STRATEGY_ID}.yaml" "$SPEC_SNAPSHOT_PATH"
# Compute spec_hash from the snapshot (not the live file)
SPEC_HASH=$(STRATEGY_ID="$STRATEGY_ID" SPEC_SNAPSHOT_PATH="$SPEC_SNAPSHOT_PATH" python - <<'PY'
import json, os
from src.platform.strategy_spec import load_spec_from_path  # OR adapt load_spec to accept a path; PM verifies
from src.platform.backtest_persist import spec_hash
spec = load_spec_from_path(os.environ["SPEC_SNAPSHOT_PATH"])
print(spec_hash(spec.raw))
PY
)
```

Note: if `load_spec_from_path` does not exist, PM adapts `load_spec` at T0 to accept an explicit path OR uses a direct YAML read + the spec_hash function. The binding contract is: **the snapshot file is the spec, for this entire run**.

**Audit:** Write `arcis_strategy.backtest.snapshot_captured` event with `params={spec_snapshot_path, spec_hash, strategy_id, run_id}`.

### Phase B2 — R8 preflight

This is the skill-layer defense-in-depth check that runs BEFORE invoking the runner. The runner itself does the same check at entry (FA9), but a skill-layer raise surfaces a friendlier message.

```bash
STRATEGY_ID="$STRATEGY_ID" python - <<'PY'
import json, os, sys
from src.platform.strategy_spec import load_spec
from src.platform.rigor.walkforward_firewall import validate_derived_from, R8ViolationError
try:
    spec = load_spec(os.environ["STRATEGY_ID"])
    validate_derived_from(spec.raw)
    print(json.dumps({"ok": True}))
except R8ViolationError as e:
    print(json.dumps({"ok": False, "error_class": "R8ViolationError", "message": str(e)}))
    sys.exit(1)
PY
```

On `ok=false`:

```
REFUSE — R8 firewall preflight failed for $STRATEGY_ID:
  $MESSAGE
  
  R8 requires the strategy YAML to declare a `derived_from` key (value may be null OR a dict
  with source_type ∈ {forensic_audit_ruleset, bootcamp_backtest, shadow_trading_cohort, other},
  source_run_id (regex [A-Za-z0-9_.\-]+), source_date_range {start, end}, optional source_trade_ids).
  
  Resolution: add `derived_from:` to src/platform/specs/$STRATEGY_ID.yaml and re-run.
  
  No mutation attempted. No backtest tables written.
```

STOP. Write `arcis_strategy.backtest.r8_violation` audit event with `params.error_class = "R8ViolationError"` and `params.message = $MESSAGE`.

Skip B2 if `QUICK=true` — the `--quick` in-sample path does NOT invoke `run_walkforward()`, so R8 is not a precondition (FA9 only fires inside the runner). However, the implementing PM SHOULD note in the operator output banner that `--quick` skips R8 (see B6 below).

### Phase B3 — Plan the run

Compose the planned-invocation summary the operator will see in the confirm prompt.

**For default (full walkforward):**

```
Planned action: full walkforward backtest of $STRATEGY_ID

  Engine: src.platform.backtest_engine.run_backtest()
  Runner: src.platform.rigor.walkforward_runner.run_walkforward()
  Windows: 5 (DEFAULT_WINDOWS per walkforward_config.py:85-91; IS spans 2017-01-01 → 2022-12-31; OOS spans 2019-01-01 → 2024-09-30; 15-month OOS each except 9-month tail window)
  Per-window calls: 2 engine invocations (IS slice + OOS slice) → 10 engine calls total
  R2 purging: applied per window (López de Prado 2018 §7.4)
  R2 embargo: 5 trading days (Mon-Fri arithmetic; not NYSE-holiday-aware per FA8)
  R8 firewall: validated at preflight + re-validated at runner entry
  Universe: $UNIVERSE_KIND (point-in-time S&P 100 if "sp100"; else as-declared)
  
  Writes:
    - backtest_results: 1 row per IS window → 5 rows
    - backtest_trades: N rows (N depends on signal density)
    - walkforward_results: 1 row aggregate (outcome_state ∈ {PASS, FAIL, INCONCLUSIVE})
    - walkforward_trades: N rows (OOS only — IS trades not duplicated)
    - trials_registry: 1 row (skill records via trials.record_trial() per FA11 — see §8)
  
  Write target: LOCAL research DB (paths.db_canonical OR test_dsn per arcis_config.yaml — see §14 open question DD-13)
  Estimated runtime: 10-30 min (5 windows × 2 engine calls; depends on universe size + signal density)
  Spec hash: $SPEC_HASH
  Code git sha: $CODE_GIT_SHA

  Note (DA12): this run takes 10-30 min. Keep the session active. If the session disconnects,
  re-attach with /arcis:strategy status $STRATEGY_ID to see in-flight wf_run_id (Active Runs
  section); the run CONTINUES even if the orchestrator drops (the per-window persist is durable
  + the lock at data/locks/strategy/$STRATEGY_ID.lock is reclaimed after the lock-file mtime
  exceeds the runtime budget). A --detach flag is §14 v1.x future.
```

**For `--quick`:**

```
⚠ IN-SAMPLE ONLY — not rigor-grade (banner will repeat in every output line of the result)

Planned action: in-sample backtest of $STRATEGY_ID

  Engine: src.platform.backtest_engine.run_backtest()
  Runner: NOT invoked (--quick = skip walkforward)
  Window: 2018-01-01 → 2024-12-31 (v1 canonical research-desk window; strategy YAML does
          not carry a window field — see §14 OQ7 for v1.x follow-up).
  R2 purging: NOT applied (single window — no IS/OOS to purge across)
  R2 embargo: NOT applied
  R8 firewall: NOT checked (R8 only fires on walkforward — see B2 note)
  
  Writes:
    - backtest_results: 1 row
    - backtest_trades: N rows
    - walkforward_results: NOT written (no walkforward ran)
    - trials_registry: 1 row (skill records per §8)
  
  Write target: LOCAL research DB
  Estimated runtime: 1-3 min
  Spec hash: $SPEC_HASH
  Code git sha: $CODE_GIT_SHA
```

### Phase B4 — Confirmation (AskUserQuestion #1 of 1)

> $PLANNED_ACTION_BLOCK (verbatim B3 output above)
> 
> $QUICK_BANNER_REPEATED (if QUICK=true, the ⚠ banner appears as the FINAL line before "Approve?")
> 
> Approve?

Options:
- "Approve — run backtest" — continue to B5
- "Cancel" — STOP, write `arcis_strategy.backtest.cancelled` audit event
- "Show me the rigor stack reference" — read + print `references/rigor-stack-integration.md`, then re-ask the same prompt

**After operator approves (DA8-equivalent — DD-8 in §13):** write `arcis_strategy.backtest.confirmed` event with:

- `prompt_hash` = SHA-256 of the prompt prose shown above
- `option_text` = verbatim string operator selected (e.g., `"Approve — run backtest"`)
- `params.strategy_id`, `params.quick`, `params.spec_hash`

BEFORE proceeding to B5.

### Phase B5 — Re-capture preview (DA10-equivalent — DD-9 in §13)

Between B4 approve and B5 execute, the spec file COULD have been edited by another process. **DA2 dual-hash check:** Verify the snapshot (captured at B1.5) AND the live YAML have not drifted from B1's claim.

1. Compute `snapshot_hash` over the snapshot file at `$SPEC_SNAPSHOT_PATH` (taken at B1.5).
2. Compute `live_hash` by re-loading from `src/platform/specs/$STRATEGY_ID.yaml`.
3. Compare both to `$SPEC_HASH` from B1:
   - `snapshot_hash == SPEC_HASH` and `live_hash == SPEC_HASH` → no drift; proceed silently.
   - `snapshot_hash != SPEC_HASH` → **anomaly** (snapshot file was tampered between B1.5 and B5). REFUSE the run; write `arcis_strategy.backtest.snapshot_tampered` audit event. STOP.
   - `snapshot_hash == SPEC_HASH` but `live_hash != SPEC_HASH` → operator edited the live YAML between B4 approve and B5. Surface to operator at B5 (not at B7, where the snapshot will mask the drift):

```
SPEC CHANGED on disk between approve and execute.
  B1 spec_hash (snapshot binding):    $SPEC_HASH
  B5 live YAML spec_hash:             $LIVE_HASH
  Note: the snapshot at $SPEC_SNAPSHOT_PATH is locked — B7 will execute against the B1 contents.
  Diff vs snapshot: <truncated git-style diff of spec.raw between snapshot and live, ≤500 chars + " [truncated]" if longer>
  Proceed?
  - "Yes — run against the snapshot (operator's original B4 approval)"
  - "Re-approve with the updated live YAML"  → re-snapshot from live + recompute SPEC_HASH + re-confirm B4
  - "Cancel" — STOP, write `arcis_strategy.backtest.cancelled_spec_changed`
```

The B4 confirm prompt prose MUST also state explicitly: `"spec snapshot captured at $B1_TS — the snapshot binds B7 execute. If the live YAML changes before execute, you'll be re-prompted at B5."`

### Phase B5.5 — Concurrency guard (DA5)

After B5's hash check passes, BEFORE B5.9 / B7, acquire an advisory file-lock keyed on the strategy_id:

```bash
LOCK_DIR="data/locks/strategy"
mkdir -p "$LOCK_DIR"
LOCK_PATH="${LOCK_DIR}/${STRATEGY_ID}.lock"
# portalocker is cross-platform (works on Windows and POSIX); PM verifies it is in requirements.txt; if not, add it.
```

Inside the Python heredoc that wraps B7+B8+B9:

```python
import portalocker
import time
lock_start = time.time()
try:
    with portalocker.Lock(LOCK_PATH, timeout=10) as lock:
        # ... B7 + B8 + B9 body here ...
        pass
except portalocker.LockException:
    # Surface ERROR envelope §10.12 concurrent_refused
    ...
```

On lock timeout (10s default), surface §10.12 envelope:

```
ERROR — backtest: concurrent backtest detected for $STRATEGY_ID.
  Another /arcis:strategy backtest run is currently holding the lock at $LOCK_PATH.
  Started: $LOCK_HELD_SINCE (read from lock file mtime).
  
  Refusing to overlap (concurrent writes to the same strategy_id would corrupt audit invariants).
  
  Resolution: wait for the active run to complete (see /arcis:strategy status — Active Runs section).
  Or use --force to bypass (NOT recommended; will produce overlapping audit events + duplicate trials_registry rows).
```

Audit: write `arcis_strategy.backtest.concurrent_refused` with `params.strategy_id, lock_path, lock_held_since`. STOP.

The lock is released on B9 completion OR on ANY failure path (the `with` context manager handles this even on exception).

### Phase B5.9 — db_path defense-in-depth (DA9)

After the lock is acquired, BEFORE any `persist_*` call inside the heredoc, inspect the resolved `db_path` against prod-DSN signatures. This is a second line of defense beyond the orchestrator's ARCIS_ALLOW_PROD_PG sentinel (DD-14) — defense-in-depth per DD-15.

```python
# Inside the B7/B6 heredoc, after cfg = load_arcis_config() and db_path = str(cfg.paths.db_canonical):
def _validate_db_path_not_prod(path: str, cfg, env: dict) -> None:
    # (a) explicit prefix
    if path.startswith('postgresql://') or path.startswith('postgres://'):
        # Allow only if the path matches pg.test_dsn (separate test PG at 5434 per DD-13)
        if path == str(getattr(cfg.pg, 'test_dsn', None) or ''):
            return
        raise RuntimeError(f"db_path '{path}' refused: prod-PG DSN signature.")
    # (b) prod_dsn_signatures from arcis_config.yaml
    sigs = getattr(cfg.pg, 'prod_dsn_signatures', None) or []
    for sig in sigs:
        if sig and sig in path:
            raise RuntimeError(f"db_path '{path}' refused: matches prod_dsn_signature '{sig}'.")
    # (c) env-var blacklist
    blacklist = env.get('PROD_PG_HOSTS_BLACKLIST', '').split(',')
    for host in (h.strip() for h in blacklist if h.strip()):
        if host in path:
            raise RuntimeError(f"db_path '{path}' refused: host '{host}' in PROD_PG_HOSTS_BLACKLIST.")

_validate_db_path_not_prod(db_path, cfg, os.environ)
```

On refusal, audit `arcis_strategy.backtest.db_path_blocked` with `params.strategy_id, db_path_redacted (last 30 chars), matched_signature`. Surface error envelope §10.13:

```
REFUSE — backtest: resolved db_path matches a prod-PG signature.
  db_path (last 30 chars): ...$DB_PATH_TAIL
  Matched signature: $MATCHED_SIG
  
  Reason: arcis:strategy writes ONLY to local research DB. Defense-in-depth check inside heredoc.
  Resolution: confirm arcis_config.yaml paths.db_canonical points to local SQLite or pg.test_dsn (port 5434).
  
  No mutation attempted. No audit event for mutation written.
```

STOP.

### Phase B6 — Execute (--quick branch)

If `QUICK=true`:

```bash
STRATEGY_ID="$STRATEGY_ID" SPEC_SNAPSHOT_PATH="$SPEC_SNAPSHOT_PATH" WALKFORWARD_AUTOFIRE_ENABLED=false python - <<'PY'
import json, sys, os
from src.platform.strategy_spec import load_spec_from_path  # DA2 — load from snapshot, not by id
from src.platform.backtest_engine import run_backtest, BacktestConfig
from src.platform.backtest_persist import persist_backtest_result
from src.platform.rigor.trials import record_trial
from src.tools._config import load_arcis_config
# NB: no _git_sha import — the BacktestResult already carries result.reproducibility["code_git_sha"]
# (run_backtest writes it via the platform's own _git_sha helper). If a separate skill-layer git SHA
# is ever needed, shell out: subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True,
# text=True, cwd=repo_root).stdout.strip().

cfg = load_arcis_config()
db_path = str(cfg.paths.db_canonical)  # ArcisConfig is a pydantic model (src/tools/_config.py:179-187); attr access, not subscript. See §14 DD-13 open question.

# DA9 — Defense-in-depth db_path check before any persist
_validate_db_path_not_prod(db_path, cfg, os.environ)  # raises RuntimeError → envelope §10.13

# DA2 — Load spec from snapshot path (NOT from src/platform/specs/) so live-file edits during
# the run cannot affect outcomes. Snapshot was captured at B1.5; SPEC_SNAPSHOT_PATH env var
# threaded through B5.5+B7 wrapping lock context.
spec = load_spec_from_path(os.environ["SPEC_SNAPSHOT_PATH"])
# v1: canonical 2018-2024 backtest window for --quick mode (no YAML schema field exists
# in src/platform/specs/*.yaml — verified against FA2/strategy_spec.py).
# DA11 — strategy YAML does not carry a window field; see §14 OQ7. The "full spec date range"
# prose in earlier B3 drafts was FALSE — the window is hardcoded canonical research-desk.
start_date = "2018-01-01"
end_date   = "2024-12-31"

bt_config = BacktestConfig(
    strategy=spec,
    start_date=start_date,
    end_date=end_date,
    initial_capital=100_000,
    commission_bps=0,
    slippage_bps=3.0,
    spread_bps=1.5,
    random_seed=42,
    survivorship_haircut_bps=spec.raw.get("survivorship_haircut_bps", 75),
)
result = run_backtest(bt_config)
# Walkforward autofire disabled via the WALKFORWARD_AUTOFIRE_ENABLED=false env var
# set on the python invocation line above (transport convention per §9.4).

# DA1 — provenance_kind is REQUIRED by the schema CHECK constraint.
# --quick path = 'quick_in_sample' (single in-sample run, no walkforward composition).
result_id = persist_backtest_result(
    result,
    db_path=db_path,
    git_sha=result.reproducibility["code_git_sha"],
    provenance_kind='quick_in_sample',
)

# Record trial entry for DSR's N_eff bookkeeping (skill stewards trials_registry per §8).
sr_raw = result.metrics.get("sharpe", 0.0)
n_trades = len(result.trades)
trial_id = record_trial(
    strategy_id=spec.strategy_id,
    spec_hash=result.reproducibility["spec_hash"],
    sr_raw=sr_raw,
    sr_ann=sr_raw,  # quick path does not annualize separately; surface raw twice
    n_trades=n_trades,
    skew=result.metrics.get("skew", 0.0),
    kurt=result.metrics.get("kurt", 3.0),
    passed_dsr_gate=0,  # gate evaluated by analyze verb, not backtest
    params_searched_json="{}",
    n_params_searched=1,
    db_path=db_path,
)

print(json.dumps({
    "ok": True,
    "result_id": result_id,
    "trial_id": trial_id,
    "strategy_id": spec.strategy_id,
    "metrics": {k: result.metrics.get(k) for k in
        ["n_trades", "total_return_pct", "sharpe", "sortino", "calmar",
         "max_drawdown_pct", "win_rate", "profit_factor"]},
    "spec_hash": result.reproducibility["spec_hash"],
    "code_git_sha": result.reproducibility["code_git_sha"],
}))
PY
```

Parse the JSON envelope. On error: surface verbatim, write `arcis_strategy.backtest.engine_failed` audit event with `params.error = error_envelope`.

### Phase B7 — Execute (default = full walkforward branch)

**Architecture lock (DA14):** Phase B7 specifies INLINE per-window orchestration via heredoc. `scripts/backtest/run_walkforward.py` is OUT OF SCOPE for v1 — regardless of whether the file exists at impl time, the skill does not call it. Removes ambiguity from §14.2 (formerly OQ1 fork).

If `QUICK=false`:

```bash
STRATEGY_ID="$STRATEGY_ID" SPEC_SNAPSHOT_PATH="$SPEC_SNAPSHOT_PATH" WALKFORWARD_AUTOFIRE_ENABLED=false python - <<'PY'
import json, sys, os, portalocker, hashlib
from src.platform.strategy_spec import load_spec_from_path  # DA2 — load from snapshot
from src.platform.backtest_engine import run_backtest, BacktestConfig
from src.platform.backtest_persist import persist_backtest_result, spec_hash
from src.platform.rigor.walkforward_runner import run_walkforward, persist_run_result
from src.platform.rigor.walkforward_config import WalkForwardConfig, DEFAULT_WINDOWS
from src.platform.rigor.trials import record_trial
from src.platform.rigor.walkforward_universe import resolve_universe_as_of
from src.tools._config import load_arcis_config
from src.utils.db import connect_db  # for orphan UPDATE on failure (DA4)
import datetime as _dt

cfg = load_arcis_config()
db_path = str(cfg.paths.db_canonical)  # ArcisConfig is a pydantic model — attr access, not subscript
_validate_db_path_not_prod(db_path, cfg, os.environ)  # DA9 — defense-in-depth

# DA5 — Wrap the entire B7+B8+B9 mutation phase in the strategy_id file-lock acquired at B5.5
LOCK_PATH = f"data/locks/strategy/{os.environ['STRATEGY_ID']}.lock"

# DA2 — Load spec from snapshot (not live YAML); the snapshot is the run's binding contract
spec = load_spec_from_path(os.environ["SPEC_SNAPSHOT_PATH"])
wf_config = WalkForwardConfig(strategy_id=spec.strategy_id)  # required strategy_id (no default); else defaults: 5 windows, embargo_days=5 (DEFAULT_EMBARGO_DAYS per walkforward_config.py:40), corpus_id=None (FA7 — corpus binding deferred per v1)
spec_hash_val = spec_hash(spec.raw)

# DA4 — Phase B7.0: announce per-window attempt (audit-event sequence covers the loop end-to-end)
WF_RUN_ID_PLANNED = None  # populated after run_walkforward returns; the .wf_run_attempt event carries the planned IS-row count instead
_audit_started_event = {
    "tool_name": "arcis_strategy.backtest.wf_run_attempt",
    "params": {
        "strategy_id": spec.strategy_id,
        "spec_hash": spec_hash_val,
        "spec_snapshot_path": os.environ["SPEC_SNAPSHOT_PATH"],
        "expected_is_rows": len(wf_config.windows),  # 5 by default
        "lock_path": LOCK_PATH,
    },
}
# (write_event invocation here — passed through stdin to _execution_log; PM verifies pattern)

# Per-window engine orchestration (FA7 — runner does NOT call engine; caller pre-computes window trades)
window_trades = {}
is_persist_result_ids = []
for window_idx, window in enumerate(wf_config.windows):
    # IS slice — passed to runner as window_trades[i]["is"]
    is_config = BacktestConfig(
        strategy=spec,
        start_date=window.train_start,
        end_date=window.train_end,
        initial_capital=100_000,
        commission_bps=0, slippage_bps=3.0, spread_bps=1.5,
        random_seed=42,
        survivorship_haircut_bps=spec.raw.get("survivorship_haircut_bps", 75),
    )
    is_result = run_backtest(is_config)
    # DA1 — provenance_kind='wf_is_window' for the 5 per-window IS rows
    is_result_id = persist_backtest_result(
        is_result,
        db_path=db_path,
        git_sha=is_result.reproducibility["code_git_sha"],
        provenance_kind='wf_is_window',
    )
    is_persist_result_ids.append(is_result_id)
    # DA4 — per-window audit event
    # write_event(tool_name='arcis_strategy.backtest.window_persisted',
    #             params={'window_idx': window_idx, 'is_result_id': is_result_id, 'spec_hash': spec_hash_val})
    
    # OOS slice — passed to runner as window_trades[i]["oos"]
    oos_config = BacktestConfig(
        strategy=spec,
        start_date=window.test_start,
        end_date=window.test_end,
        initial_capital=100_000,
        commission_bps=0, slippage_bps=3.0, spread_bps=1.5,
        random_seed=42,
        survivorship_haircut_bps=spec.raw.get("survivorship_haircut_bps", 75),
    )
    oos_result = run_backtest(oos_config)
    # OOS engine result is NOT persisted as a backtest_results row; it lives only in walkforward_trades after persist_run_result.
    
    window_trades[window_idx] = {"is": is_result.trades, "oos": oos_result.trades}

# Universe size for the aggregate row
universe_str = spec.universe.get("tickers")
effective_universe_size = 0
if universe_str == "sp100":
    # Resolve at first OOS start as a representative size
    first_oos = wf_config.windows[0].test_start
    effective_universe_size = len(resolve_universe_as_of(first_oos, db_path=db_path))

# Run the walkforward — R8 firewall + per-window rigor + outcome reducer
wf_result = run_walkforward(
    strategy_spec_raw=spec.raw,
    config=wf_config,
    window_trades=window_trades,
    spec_path=spec.source,
    forensic_audits=(),
    max_hold_days=21,
    effective_universe_size=effective_universe_size,
    repo_root=".",
    derived_from_backtest_id=is_persist_result_ids[0],  # link aggregate to FIRST IS row (representative)
)

# Persist the walkforward aggregate + per-window OOS trades.
# persist_run_result returns None (walkforward_runner.py:347-352); capture run_id from the result object.
wf_run_id = wf_result.run_id
oos_trades_per_window = {i: window_trades[i]["oos"] for i in window_trades}
persist_run_result(
    wf_result,
    strategy_spec_raw=spec.raw,
    oos_trades_per_window=oos_trades_per_window,
    db_path=db_path,
)
# DA4 — wf_complete audit event (clean completion path)
# write_event(tool_name='arcis_strategy.backtest.wf_complete',
#             params={'strategy_id': spec.strategy_id, 'wf_run_id': wf_run_id,
#                     'is_persist_result_ids': is_persist_result_ids, 'spec_hash': spec_hash_val})

# Record trial entry — N_eff bookkeeping for DSR (skill stewards trials_registry per §8)
sr_raw = wf_result.pooled_sharpe
total_oos_trades = sum(len(t["oos"]) for t in window_trades.values())
trial_id = record_trial(
    strategy_id=spec.strategy_id,
    spec_hash=spec_hash_val,
    sr_raw=sr_raw,
    sr_ann=sr_raw,
    n_trades=total_oos_trades,
    skew=0.0,  # walkforward result does not surface skew/kurt — implementing PM verifies; defaults acceptable for N_eff counting
    kurt=3.0,
    passed_dsr_gate=0,
    params_searched_json="{}",
    n_params_searched=1,
    db_path=db_path,
)

print(json.dumps({
    "ok": True,
    "wf_run_id": wf_run_id,
    "trial_id": trial_id,
    "is_persist_result_ids": is_persist_result_ids,
    "strategy_id": spec.strategy_id,
    "outcome_state": wf_result.outcome.outcome_state,  # "PASS" | "FAIL" | "INCONCLUSIVE" — verbatim
    "reason": wf_result.outcome.reason,
    "pooled_sharpe": wf_result.pooled_sharpe,
    "pooled_mde": wf_result.pooled_mde,
    "n_windows": len(window_trades),
    "n_windows_pass": wf_result.outcome.n_windows_pass,
    "n_windows_fail": wf_result.outcome.n_windows_fail,
    "n_windows_inconclusive_data": wf_result.outcome.n_windows_inconclusive_data,
    "n_windows_inconclusive_power": wf_result.outcome.n_windows_inconclusive_power,
    "n_windows_inconclusive_duration": wf_result.outcome.n_windows_inconclusive_duration,
    "effective_universe_size": effective_universe_size,
    "spec_hash": spec_hash_val,
    "code_git_sha": wf_result.code_git_sha,
}))
PY
```

Parse JSON. On error envelope: surface verbatim, write `arcis_strategy.backtest.runner_failed` event.

**Phase B7-failure-path (DA4 — mid-run orphan recovery):**

If `run_walkforward()` raises after `is_persist_result_ids` is non-empty (i.e., one or more IS windows persisted before the aggregation/OOS step crashed), the loop body's try/except writes an `arcis_strategy.backtest.wf_partial` audit event with `params.written_is_rows = is_persist_result_ids` AND surfaces an operator-facing AskUserQuestion:

```
WALKFORWARD RUN INCOMPLETE — partial state remains.
  Strategy: $STRATEGY_ID
  Failure stage: $FAILURE_STAGE   (e.g., "run_walkforward outcome reducer", "persist_run_result", "OOS-slice window N")
  IS rows persisted before failure: $N_ORPHAN  (result_ids: $LIST)
  walkforward_results: NOT written
  trials_registry: NOT written
  
  Options:
  - "Roll back the $N_ORPHAN orphan IS rows" — DELETE FROM backtest_results WHERE result_id IN ($LIST)
  - "Keep — backfill provenance_kind=wf_is_window_orphan_partial_run for forensic inspection"
      (UPDATE backtest_results SET provenance_kind='wf_is_window_orphan_partial_run' WHERE result_id IN ($LIST);
       these rows are then queryable from /arcis:strategy status as "orphans" and refused by analyze per AN1.)
```

The `wf_partial` audit event carries:

```python
params={
  "strategy_id": STRATEGY_ID,
  "spec_hash": SPEC_HASH,
  "spec_snapshot_path": SPEC_SNAPSHOT_PATH,
  "failure_stage": FAILURE_STAGE,
  "written_is_rows": IS_PERSIST_RESULT_IDS,
  "error": <verbatim exception envelope>,
}
```

On operator "Roll back": run `DELETE FROM backtest_results WHERE result_id IN (...)` via the same `db_path` connection; verify deletion via dbquery; surface `Cleaned $N_ORPHAN orphan IS rows.` and STOP.

On operator "Keep": run `UPDATE backtest_results SET provenance_kind='wf_is_window_orphan_partial_run' WHERE result_id IN (...)`; verify update via dbquery; surface `$N_ORPHAN rows marked as wf_is_window_orphan_partial_run for forensic inspection.` and STOP.

**Why provenance_kind solves orphans:** AN1's dispatch (see VERB: analyze, Phase AN1 revised below) reads `provenance_kind` first. A row marked `wf_is_window_orphan_partial_run` is REFUSED by analyze with a clear envelope, eliminating the failure mode where an operator analyzes a partial-run IS slice without knowing it.

**No new cleanup verb in v1:** Operator manages orphans via existing `/arcis:strategy status` surface (now showing `orphan_is_rows` count from the new `provenance_kind` column) + the AskUserQuestion fork above. A standalone `cleanup` verb is §14 future.

### Phase B8 — Post-execution verification

Re-query the local DB to confirm the writes landed.

```bash
# --quick branch:
python -m src.tools.dbquery --json "SELECT COUNT(*) AS n FROM backtest_results WHERE result_id = '$RESULT_ID'"
python -m src.tools.dbquery --json "SELECT COUNT(*) AS n FROM trials_registry WHERE trial_id = '$TRIAL_ID'"

# default branch:
python -m src.tools.dbquery --json "SELECT COUNT(*) AS n FROM walkforward_results WHERE run_id = '$WF_RUN_ID'"
python -m src.tools.dbquery --json "SELECT COUNT(*) AS n FROM walkforward_trades WHERE run_id = '$WF_RUN_ID'"
python -m src.tools.dbquery --json "SELECT COUNT(*) AS n FROM trials_registry WHERE trial_id = '$TRIAL_ID'"
```

Each must return `n=1` (walkforward_trades may be > 1; just assert > 0). If any returns 0, surface as `[anomaly] verify failed: <table>` in B9 output. Do NOT auto-retry the write.

### Phase B9 — Operator-facing report + audit completion

**For `--quick`:**

```
⚠ ⚠ ⚠  IN-SAMPLE ONLY — not rigor-grade  ⚠ ⚠ ⚠
(no walkforward; no OOS validation; results CANNOT be used to gate promotion to shadow_trading)

BACKTEST --quick — RESULT
RUN_ID: $RUN_ID
Strategy: $STRATEGY_ID
Engine: backtest_engine.run_backtest()  
result_id: $RESULT_ID  (backtest_results row)
trial_id: $TRIAL_ID    (trials_registry row)

Metrics:
  n_trades:           $N_TRADES
  total_return_pct:   $TOTAL_RETURN_PCT
  sharpe:             $SHARPE          (raw — NOT deflated; use /arcis:strategy analyze $RESULT_ID for DSR)
  sortino:            $SORTINO
  calmar:             $CALMAR
  max_drawdown_pct:   $MAX_DD
  win_rate:           $WIN_RATE
  profit_factor:      $PROFIT_FACTOR

Provenance:
  spec_hash: $SPEC_HASH
  code_git_sha: $CODE_GIT_SHA

Next actions:
  /arcis:strategy analyze $RESULT_ID   — compute DSR + PSR; surface multiplicity correction
  /arcis:strategy backtest $STRATEGY_ID  — promote to full walkforward (rigor-grade)

⚠ ⚠ ⚠  IN-SAMPLE ONLY — not rigor-grade  ⚠ ⚠ ⚠
```

The ⚠ banner appears as the FIRST line AND the LAST line of the result block — unmissable framing.

**For default (full walkforward):**

```
BACKTEST (full walkforward) — RESULT
RUN_ID: $RUN_ID
Strategy: $STRATEGY_ID
Runner: walkforward_runner.run_walkforward()
wf_run_id: $WF_RUN_ID  (walkforward_results row — analyze this id)
trial_id: $TRIAL_ID     (trials_registry row)

OUTCOME_STATE: $OUTCOME_STATE   ← PASS | FAIL | INCONCLUSIVE  (verbatim from walkforward_results.outcome_state)
Reason: $REASON

Window breakdown:
  PASS:                 $N_PASS / $N_TOTAL
  FAIL:                 $N_FAIL / $N_TOTAL
  INCONCLUSIVE (data):  $N_INC_DATA / $N_TOTAL
  INCONCLUSIVE (power): $N_INC_POWER / $N_TOTAL
  INCONCLUSIVE (duration): $N_INC_DUR / $N_TOTAL

Pooled stats:
  pooled_sharpe:       $POOLED_SHARPE  (raw — NOT deflated; use /arcis:strategy analyze for DSR)
  pooled_mde:          $POOLED_MDE
  effective_universe_size: $UNIV_SIZE (point-in-time S&P 100 at first OOS start, per FA10)

Rigor guarantees by construction:
  R2 purging applied:  yes (López de Prado 2018 §7.4)
  R2 embargo:          5 trading days (Mon-Fri arithmetic per FA8)
  R8 firewall:         passed (derived_from validated at preflight + runner entry)
  Universe lookahead:  none (point-in-time S&P 100 per FA10)

Provenance:
  spec_hash: $SPEC_HASH
  code_git_sha: $CODE_GIT_SHA

Next actions:
  /arcis:strategy analyze $WF_RUN_ID   — compute DSR over pooled trades; surface multiplicity correction
  (review the literal outcome_state above; do NOT collapse to boolean)

Internal provenance (forensic queries only — DO NOT analyze these IS slices; use $WF_RUN_ID above):
  IS-window result_ids: [$IS_PERSIST_RESULT_IDS]   (5 backtest_results rows, provenance_kind='wf_is_window')
  spec_snapshot_path: $SPEC_SNAPSHOT_PATH
  Active lock released: data/locks/strategy/$STRATEGY_ID.lock
```

Per **DA8**, the 5 IS-window `result_ids` are moved BELOW the "Next actions" section into an explicit "Internal provenance" block, so the operator's eye lands on `wf_run_id` (the correct analyze target) — not on one of the 5 IS-slice ids (which the `provenance_kind='wf_is_window'` column now actively REFUSES in AN1 with a re-target suggestion).

Write `arcis_strategy.backtest.completed` event:

```python
params={
  "strategy_id": STRATEGY_ID,
  "quick": QUICK,
  "spec_hash": SPEC_HASH,                      # DA2 — equals confirmed.spec_hash by construction (snapshot binding)
  "spec_snapshot_path": SPEC_SNAPSHOT_PATH,    # DA2 — the snapshot file the run actually executed against
  "code_git_sha": CODE_GIT_SHA,
  "wf_run_id": WF_RUN_ID or None,
  "result_id": RESULT_ID or None,
  "trial_id": TRIAL_ID,
  "outcome_state": OUTCOME_STATE or None,
  "reason": REASON or None,
  "is_persist_result_ids": IS_PERSIST_RESULT_IDS or [],
  "provenance_kind_per_row": PROVENANCE_KIND_PER_ROW or {},  # DA1 — {result_id: provenance_kind}
  "verify_failures": VERIFY_FAILURES or [],
}
```

**DA2 invariant:** `confirmed.spec_hash` MUST equal `completed.spec_hash` for the same `RUN_ID`. The snapshot mechanism guarantees this by construction (B7 loads from `SPEC_SNAPSHOT_PATH`, not from `src/platform/specs/`). If a future audit-log query finds a `RUN_ID` whose `confirmed.spec_hash != completed.spec_hash`, the snapshot mechanism failed and an anomaly event MUST be written (see §9.2).

---

## VERB: analyze

**Usage:** `/arcis:strategy analyze <run-id-or-result-id>`

Analyze is **read-only at the result-layer**; writes ONE `trials_registry` row per invocation. AskUserQuestion budget: ≤1 per invocation (optional disambiguation if the id matches both `backtest_results.result_id` and `walkforward_results.run_id`, which would imply a UUID collision — surface as `[anomaly]` and ask which the operator means).

### Phase AN1 — Resolve id (DA1 + DA8 dispatch logic)

`POSITIONAL_INPUT[1]` is `RUN_ID_ARG`. The optional `--as <backtest|walkforward>` flag forces the dispatch branch (escape hatch for advanced users; default = auto-dispatch via provenance_kind).

```bash
RUN_ID_ARG="$RUN_ID_ARG" AS_OVERRIDE="$AS_OVERRIDE" python - <<'PY'
import json, os
from src.tools._config import load_arcis_config
from src.utils.db import connect_db
cfg = load_arcis_config()
db_path = str(cfg.paths.db_canonical)  # ArcisConfig is a pydantic model — attr access, not subscript
con = connect_db(db_path)
arg = os.environ["RUN_ID_ARG"]

# DA1 — read provenance_kind FIRST, so the dispatch knows whether this is a quick / wf / orphan row.
br = con.execute("""SELECT result_id, strategy_id, spec_hash, provenance_kind
                    FROM backtest_results WHERE result_id=?""", (arg,)).fetchone()
wr = con.execute("""SELECT run_id, strategy_id, spec_hash, outcome_state, reason, pooled_sharpe,
                           derived_from_backtest_id
                    FROM walkforward_results WHERE run_id=?""", (arg,)).fetchone()
print(json.dumps({"backtest_results_match": dict(br) if br else None,
                  "walkforward_results_match": dict(wr) if wr else None}))
PY
```

**Dispatch matrix (DA1 + DA8):**

| Match | provenance_kind | Action |
|---|---|---|
| neither | n/a | ERROR envelope `unknown run-id: '$RUN_ID_ARG'`. STOP. |
| both (collision) | any | AskUserQuestion `[anomaly] UUID collision: ... — which did you mean?` |
| backtest only | `'quick_in_sample'` | Proceed with existing `RESULT_TYPE='backtest'` path + ⚠ IN-SAMPLE banner (DD-15). |
| backtest only | `'wf_is_window'` | **REDIRECT (DA8)** — AskUserQuestion: see prose below. |
| backtest only | `'wf_is_window_orphan_partial_run'` | **REFUSE (DA1)** — see envelope §10.14 below. STOP. |
| walkforward only | n/a | Proceed with `RESULT_TYPE='walkforward'`. |

**`provenance_kind == 'wf_is_window'` AskUserQuestion (DA8):**

```
This result_id is the IS slice of walkforward run $WF_RUN_ID (looked up via
derived_from_backtest_id back-reference from walkforward_results.run_id where
derived_from_backtest_id = $RESULT_ID, OR via the composite key
(strategy_id, spec_hash, train_start, train_end) when first-IS-only FK doesn't match).

Did you mean to analyze the walkforward (preserves OOS, computes DSR over the rigor-grade
trade series)? The IS slice alone is in-sample only and would surface a misleading DSR.

  - "Yes — switch to wf_run_id $WF_RUN_ID and analyze the walkforward"  (RECOMMENDED)
  - "No — analyze the IS slice anyway (informational; will display ⚠ IN-SAMPLE banner)"
```

`--as walkforward` flag short-circuits to "Yes" (auto-redirect). `--as backtest` short-circuits to "No" (analyze the IS slice with banner).

**`provenance_kind == 'wf_is_window_orphan_partial_run'` REFUSE (DA1):**

Surface envelope §10.14:

```
REFUSE — analyze: result_id $RESULT_ID is from a partial walkforward run that did NOT complete.
  provenance_kind: wf_is_window_orphan_partial_run
  strategy_id: $STRATEGY_ID
  
  The walkforward aggregation step failed mid-run; this IS slice is forensic-only.
  No walkforward_results row exists; no OOS validation was performed.
  
  Resolution: re-run /arcis:strategy backtest $STRATEGY_ID to produce a clean walkforward result.
  If you need to inspect the orphan IS metrics for debugging, query backtest_results directly
  via /arcis:strategy status $STRATEGY_ID (orphans surfaced in the "Active Runs / Orphans" section).
```

STOP. Write `arcis_strategy.analyze.refused_orphan` audit event.

### Phase AN2 — Read result + reconstruct trade-return series

For `RESULT_TYPE == backtest`:

```bash
python -m src.tools.dbquery --json "SELECT result_id, strategy_id, spec_hash, total_trades, sharpe, sortino, calmar, max_drawdown_pct, win_rate, profit_factor, created_at FROM backtest_results WHERE result_id = '$RESULT_ID'"

python -m src.tools.dbquery --json "SELECT trade_id, ticker, entry_date, exit_date, pnl_pct, excess_return, hold_days, vix_at_entry FROM backtest_trades WHERE result_id = '$RESULT_ID' ORDER BY entry_date"
```

For `RESULT_TYPE == walkforward`:

```bash
python -m src.tools.dbquery --json "SELECT run_id, strategy_id, spec_hash, outcome_state, reason, pooled_sharpe, pooled_mde, n_windows, n_windows_pass, n_windows_fail, n_windows_inconclusive_data, n_windows_inconclusive_power, n_windows_inconclusive_duration, heavy_tail_flag, vix_tier_coverage FROM walkforward_results WHERE run_id = '$RUN_ID'"

python -m src.tools.dbquery --json "SELECT trade_id, window_index, is_in_is_window, ticker, entry_date, exit_date, pnl_pct, excess_return, vix_tier, purged, embargoed FROM walkforward_trades WHERE run_id = '$RUN_ID' ORDER BY window_index, entry_date"
```

Filter trade series to OOS-only (`is_in_is_window = 0 AND purged = 0 AND embargoed = 0 AND quarantined = 0`) for DSR input.

### Phase AN3 — Compute DSR + PSR (DA3 family-variance gate + DA13 RuntimeWarning capture)

**DA3 gate — programmatic check on family diversity:** BEFORE the DSR compute, query `SELECT COUNT(DISTINCT strategy_id) FROM trials_registry`. If `> 3`, escalate to AskUserQuestion:

```
Family-variance approximation degraded: trials_registry has $N distinct strategy families.
The v0.25 implementation reads GLOBAL variance (family WHERE clause is TODO — trials.py:97);
with >3 distinct families, the global-variance approximation no longer reasonably stands in
for family-specific variance.

  - "Proceed with global-variance DSR (will surface ⚠ degraded-approximation banner)"
  - "Cancel — file follow-up task to wire family WHERE clause in trials.py:97"
```

On "Cancel": STOP. Write `arcis_strategy.analyze.deferred_family_variance` audit event.

On "Proceed": continue, and prepend a ⚠ banner to the AN5 output:

```
⚠ DSR uses GLOBAL trial variance (family filter v0.25 TODO; trials.py:97).
  With $N distinct strategy_ids in trials_registry, this approximates family-specific DSR;
  expect downward bias on the multiplicity penalty (DSR may be slightly optimistic).
```

```bash
STRATEGY_ID="$STRATEGY_ID" STRATEGY_FAMILY="$STRATEGY_FAMILY" SPEC_HASH="$SPEC_HASH" TRADE_RETURNS_JSON="$TRADE_RETURNS_JSON" python - <<'PY'
import json, os, warnings
from src.platform.rigor.dsr import deflated_sharpe_ratio, probabilistic_sharpe_ratio
from src.platform.rigor.trials import get_current_n_eff, get_variance_for_strategy_family, record_trial
from src.tools._config import load_arcis_config
cfg = load_arcis_config()
db_path = str(cfg.paths.db_canonical)  # ArcisConfig is a pydantic model — attr access, not subscript

trade_returns = json.loads(os.environ["TRADE_RETURNS_JSON"])  # list[float] from AN2
strategy_id = os.environ["STRATEGY_ID"]
spec_hash = os.environ["SPEC_HASH"]

n_eff = get_current_n_eff(db_path=db_path)
strategy_family = os.environ.get("STRATEGY_FAMILY")  # surfaced in AN3 lead-in; semantically clear even if v0.25 ignores it

# DA13 — capture the fallback RuntimeWarning so the forensic audit-event records whether the fallback fired
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    trials_sr_variance = get_variance_for_strategy_family(family=strategy_family, db_path=db_path)
fallback_warning_fired = any('fallback' in str(w.message).lower() or '_VARIANCE_FALLBACK' in str(w.message)
                              for w in caught)
# Determine variance_source — informs the audit event + the operator-facing output prose
if fallback_warning_fired:
    variance_source = 'fallback_with_warning'
elif trials_sr_variance == 0.02/250:  # the documented _VARIANCE_FALLBACK constant (trials.py:33)
    variance_source = 'fallback'
else:
    variance_source = 'empirical'

# trials_count_at_analyze_time — recorded in audit event for forensic recovery
trials_count_at_analyze_time = n_eff

# v0.25 limitation: the `family` parameter is currently UNUSED — implementation reads global trial variance
# (trials.py:97 — no WHERE family=... clause; v0.25 TODO). N_eff is family-correct via get_current_n_eff, but
# variance fallback is global. See §8.2 + §14 OQ5. DA3 — programmatic gate above bounds the approximation.

dsr_result = deflated_sharpe_ratio(
    trade_returns=trade_returns,
    n_trials=n_eff,
    trials_sr_variance=trials_sr_variance,
)

# Record this analyze invocation as a trial entry (keeps N_eff fresh for next analyze)
sr_raw = dsr_result["SR_hat"]
n_trades = len(trade_returns)
analyze_trial_id = record_trial(
    strategy_id=strategy_id,
    spec_hash=spec_hash,
    sr_raw=sr_raw,
    sr_ann=sr_raw,
    n_trades=n_trades,
    skew=dsr_result["skew"],
    kurt=dsr_result["kurt"],
    passed_dsr_gate=1 if dsr_result["DSR"] > 0.95 else 0,  # PM verifies gate threshold; brief says "DSR" surfaced; standard threshold is 0.95
    params_searched_json="{}",
    n_params_searched=1,
    db_path=db_path,
)

print(json.dumps({
    "ok": True,
    "n_eff_used": n_eff,
    "trials_sr_variance": trials_sr_variance,
    "variance_source": variance_source,                          # DA13 — 'empirical' | 'fallback' | 'fallback_with_warning'
    "trials_count_at_analyze_time": trials_count_at_analyze_time, # DA13 — frozen at analyze invocation
    "fallback_warning_fired": fallback_warning_fired,             # DA13 — explicit boolean for audit
    "dsr": dsr_result,
    "analyze_trial_id": analyze_trial_id,
}))
PY
```

### Phase AN4 — Compute CSCV (optional; informational)

```bash
python -m src.tools.dbquery --json "SELECT COUNT(*) AS n_results FROM backtest_results WHERE strategy_id = '$STRATEGY_ID'"
```

If `n_results < 2`:

```
CSCV (Combinatorially Symmetric Cross-Validation) is INFORMATIONAL — unavailable.
  Reason: CSCV requires ≥2 distinct backtest_results rows for $STRATEGY_ID; found $N_RESULTS.
  Resolution: run param-sweep backtests (deferred to a future verb per FA11), then re-analyze.
```

(Surface; do not stop.)

If `n_results >= 2`: pull all per-result daily PnL via JOIN to `backtest_trades`, construct the T×N matrix, call `cscv.pbo_from_pnl_matrix()`:

```bash
PNL_MATRIX_JSON="$PNL_MATRIX_JSON" python - <<'PY'
import json, os, pandas as pd
from src.platform.rigor.cscv import pbo_from_pnl_matrix
# Build T×N matrix from JSON-passed daily pnl per result_id (transport convention per §9.4)
matrix = pd.DataFrame(json.loads(os.environ["PNL_MATRIX_JSON"]))  # columns = result_ids, rows = dates
cscv_result = pbo_from_pnl_matrix(matrix, S=16)
print(json.dumps({"ok": True, "cscv": cscv_result}))
PY
```

If `cscv.PBO > 0.5` → flag in output as "PBO suggests overfit risk."

### Phase AN5 — Operator-facing report

**For RESULT_TYPE == walkforward:**

```
ANALYZE — RESULT
RUN_ID (analyze): $RUN_ID
Source: walkforward_results.run_id = $SOURCE_RUN_ID
Strategy: $STRATEGY_ID
Source created_at: $CREATED_AT

OUTCOME_STATE: $OUTCOME_STATE   ← preserved verbatim from walkforward_results

  Interpretation:
    PASS         — Walkforward outcome reducer accepted. Multiple OOS windows showed positive risk-adjusted return with adequate power. Eligible for shadow_trading promotion (operator decides).
    FAIL         — Walkforward outcome reducer rejected. Insufficient evidence the strategy beats benchmark + costs OOS. Do not promote.
    INCONCLUSIVE — Reducer could not decide. Sub-reason (data | power | duration) below. Treat as not-yet-deployable; re-run with more universe history / longer windows / larger position sizing where appropriate.

  Sub-reason: $REASON
  Window breakdown: PASS=$N_PASS, FAIL=$N_FAIL, INC(data)=$N_INC_DATA, INC(power)=$N_INC_POWER, INC(duration)=$N_INC_DUR

Statistical follow-up (computed by analyze):

$DA3_FAMILY_VARIANCE_BANNER  (printed if distinct_strategy_ids > 3 OR if --quick distinct check skipped)
$DA13_VARIANCE_SOURCE_BANNER  (printed if variance_source ∈ {'fallback', 'fallback_with_warning'} — see prose below)

  Deflated Sharpe Ratio (López de Prado 2018):
    SR_hat:     $SR_HAT       (raw observed Sharpe over OOS trades)
    skew:       $SKEW
    kurt:       $KURT
    T:          $T            (n_trades used)
    E_SR_max:   $E_SR_MAX     (expected max under N_eff = $N_EFF independent trials)
    PSR:        $PSR          (Probabilistic Sharpe Ratio vs SR_benchmark=0)
    DSR:        $DSR          (multiplicity-corrected; <0.95 = not significant at 95% conf)
    
  $T_GUARD_WARNING:  (printed iff T < 30 — "T<30 — DSR unreliable; PSR more trustworthy. Reference: dsr.py:85")

  CSCV (Combinatorially Symmetric Cross-Validation):
    $CSCV_BLOCK   (printed iff n_results>=2; else the AN4 unavailability message)

Provenance:
  Source spec_hash: $SPEC_HASH
  Source code_git_sha: $CODE_GIT_SHA
  N_eff used (trials_registry global count): $N_EFF
  trials_sr_variance: $VAR  (source: $VARIANCE_SOURCE — one of 'empirical' / 'fallback' / 'fallback_with_warning')
  trials_count_at_analyze_time: $TRIALS_COUNT  (frozen at this analyze invocation for forensic replay)
  analyze_trial_id recorded: $ANALYZE_TRIAL_ID

$DA13_BANNER:
  (printed iff variance_source != 'empirical')
  ⚠  analyze: DSR computed against variance fallback (trials_registry had $TRIALS_COUNT trials < 20 threshold).
     Source: _VARIANCE_FALLBACK = 0.02/250 (trials.py:33; RuntimeWarning emitted at trials.py:109).
     Forensic note: variance_source=$VARIANCE_SOURCE recorded in audit event params.

Recommendation:
$REC  (synthesized from outcome_state + DSR; see decision matrix in references/statistical-rigor.md)
```

**For RESULT_TYPE == backtest:**

```
ANALYZE — RESULT (in-sample backtest)

⚠  Source is an IN-SAMPLE backtest_results row (no walkforward; no OOS validation).
   Statistical follow-up below is informational; do not use for promotion gating.

RUN_ID (analyze): $RUN_ID
Source: backtest_results.result_id = $SOURCE_RESULT_ID
Strategy: $STRATEGY_ID
Source created_at: $CREATED_AT

Source metrics (verbatim from backtest_results):
  n_trades:           $N_TRADES
  total_return_pct:   $TOTAL_RETURN_PCT
  sharpe:             $SHARPE
  sortino / calmar / max_dd / win_rate / profit_factor: $...

Statistical follow-up (computed by analyze):
  $DSR_BLOCK (same shape as walkforward branch)
  $CSCV_BLOCK

Recommendation:
$REC

Next:
  /arcis:strategy backtest $STRATEGY_ID   — re-run as full walkforward (rigor-grade) to validate OOS
```

### Phase AN6 — Audit completion

Write `arcis_strategy.analyze.completed` event:

```python
params={
  "source_run_id": SOURCE_RUN_ID_OR_RESULT_ID,
  "result_type": RESULT_TYPE,
  "provenance_kind": PROVENANCE_KIND or None,   # DA1 — null for walkforward source; quick/wf/orphan for backtest source
  "strategy_id": STRATEGY_ID,
  "outcome_state": OUTCOME_STATE or None,        # walkforward only
  "dsr": DSR_VALUE,
  "psr": PSR_VALUE,
  "n_eff_used": N_EFF,
  "variance_source": VARIANCE_SOURCE,            # DA13 — 'empirical' | 'fallback' | 'fallback_with_warning'
  "trials_count_at_analyze_time": TRIALS_COUNT, # DA13 — frozen at analyze for forensic replay
  "fallback_warning_fired": FALLBACK_WARNING_FIRED,  # DA13 — explicit boolean
  "cscv_pbo": CSCV_PBO or None,
  "analyze_trial_id": ANALYZE_TRIAL_ID,
  "distinct_strategy_ids_at_analyze_time": DISTINCT_FAMILIES,  # DA3 — for DSR-degradation tracking
}
```

---

## VERB: status

**Usage:** `/arcis:strategy status [strategy-id]`

Status is **read-only**. No agent dispatch. No mutations. No confirms. No skill-level audit event.

### Phase S1 — Compose snapshot

Run the tools IN PARALLEL (single message, multiple Bash blocks). Each python heredoc receives operator-typed positional inputs via env vars (transport convention per §9.4); the `STRATEGY_ID` scoping arg is passed as `STRATEGY_ID="$STRATEGY_ID"` on the python invocation line when the optional positional argument is present.

```bash
# Filesystem catalog — list_available_specs() silently skips malformed
python - <<'PY'
import json, os, glob
from src.platform.strategy_spec import list_available_specs, _SPECS_DIR
specs_via_loader = list_available_specs()  # silently filtered

# Raw filesystem listing — surfaces malformed
raw_files = sorted(os.path.basename(p)[:-5] for p in glob.glob(str(_SPECS_DIR / "*.yaml")))
silently_skipped = sorted(set(raw_files) - set(s.strategy_id for s in specs_via_loader))

print(json.dumps({
    "specs": [{"strategy_id": s.strategy_id, "display_name": s.display_name,
               "source": s.source, "status_in_yaml": s.raw.get("status"),
               "derived_from_present": "derived_from" in s.raw,
               "universe_tickers": s.universe.get("tickers"),
               "entry_kind": s.entry.get("kind")} for s in specs_via_loader],
    "silently_skipped_malformed": silently_skipped,
}))
PY

# DB lifecycle state
python -m src.tools.dbquery --json "SELECT strategy_id, display_name, current_status, current_spec_hash, survivorship_haircut_bps, last_status_change FROM strategy_registry ORDER BY strategy_id"

# Recent backtest_results (last 30d)
python -m src.tools.dbquery --json "SELECT result_id, strategy_id, spec_hash, sharpe, total_return_pct, max_drawdown_pct, created_at FROM backtest_results WHERE created_at >= datetime('now', '-30 days') ORDER BY created_at DESC LIMIT 20"

# Recent walkforward_results (last 30d)
python -m src.tools.dbquery --json "SELECT run_id, strategy_id, spec_hash, outcome_state, reason, pooled_sharpe, n_windows_pass, n_windows_fail, derived_from_backtest_id, created_at FROM walkforward_results WHERE created_at >= datetime('now', '-30 days') ORDER BY created_at DESC LIMIT 20"

# trials_registry count (N_eff context)
python -m src.tools.dbquery --json "SELECT COUNT(*) AS n_eff_global FROM trials_registry"
```

If `[strategy-id]` argument provided, scope queries to that strategy_id (WHERE clauses appended).

### Phase S2 — Compute FS-vs-DB drift

```
SPECS_IN_FS = set(specs.strategy_id for specs in snapshot)
SPECS_IN_DB = set(strategy_registry.strategy_id for rows in snapshot)

DRIFT:
  fs_only = SPECS_IN_FS - SPECS_IN_DB    (spec file exists, no registry row)
  db_only = SPECS_IN_DB - SPECS_IN_FS    (registry row exists, no spec file)
  fs_and_db = SPECS_IN_FS & SPECS_IN_DB

ANOMALIES (surfaced per no-out-of-scope-deferral):
  silently_skipped_malformed  (from list_available_specs filter — FA2 line 392)
  specs_missing_derived_from  (R8-noncompliant specs that would fail backtest)
  wf_rows_with_null_derived_from_backtest_id  (orphaned aggregate rows)
```

### Phase S3 — Operator-facing report

```
STATUS SNAPSHOT — $NOW_ET
Scope: $SCOPE   (all strategies | strategy_id = $STRATEGY_ID_ARG)

Filesystem specs ($N_FS total):
  $STRATEGY_ID  $DISPLAY_NAME  (status: $STATUS_IN_YAML | entry: $ENTRY_KIND | universe: $UNIV | derived_from: $YES_NO)
  ...

DB strategy_registry ($N_DB total):
  $STRATEGY_ID  current_status=$CURRENT_STATUS  haircut_bps=$HAIRCUT  last_status_change=$LAST_CHANGE
  ...

Recent backtests (last 30d, top 20):
  $RESULT_ID  $STRATEGY_ID  sharpe=$SHARPE  total_return=$TR%  max_dd=$DD%  $CREATED_AT
  ...

Recent walkforwards (last 30d, top 20):
  $WF_RUN_ID  $STRATEGY_ID  outcome=$OUTCOME_STATE  reason="$REASON"  pooled_sharpe=$SHARPE  pass/fail/inc=$P/$F/$I  $CREATED_AT
  ...

trials_registry global N_eff: $N_EFF

FS ↔ DB DRIFT:
  fs_only (spec file but no registry row, $N count):  $LIST  ← may indicate spec authored but never backtested
  db_only (registry row but no spec file, $N count):  $LIST  ← may indicate stale registry row from deleted spec
  in sync ($N): $LIST

ANOMALIES (per no-out-of-scope-deferral):
  Malformed YAML files silently skipped by list_available_specs() ($N):
    $LIST  ← these YAML files exist but failed validate_spec(); they will not appear in /arcis:strategy backtest <id>
  R8-noncompliant specs (missing derived_from key, $N):
    $LIST  ← these will fail R8 preflight in /arcis:strategy backtest
  walkforward_results with NULL derived_from_backtest_id ($N):
    $LIST  ← orphaned aggregate rows; cannot JOIN back to IS row for full provenance

Snapshot complete. Status is read-only — no audit event written.
```

### Phase S4 — No audit write

Status is read-only and inherits per-tool audit events automatically. No skill-level audit event.

---

## ERROR ENVELOPES (operator-facing)

Every error class has a defined operator-facing shape. See `references/error-envelopes.md` (§10) for full examples. Quick reference:

- **Verb-unknown** → see ARGUMENT PARSING section above.
- **PROD-PG refused** → REFUSE prose; STOP immediately.
- **Spec resolution failed (FileNotFoundError / ValueError)** → see Phase B1.
- **R8 firewall violation** → see Phase B2; surfaces friendly remediation hint.
- **Engine failure** → surface JSON envelope verbatim; do NOT retry.
- **Walkforward runner failure** → same.
- **Tool JSON ERROR envelope** → surface `error.message` verbatim.
- **Operator denial at confirm** → STOP, audit event, no mutation.
- **Tier-tool unavailable** (dbquery / gitarchaeology missing) → warn + skip; never crash.
- **UUID collision (analyze)** → surface as anomaly; AskUserQuestion to disambiguate.

---

## AUDIT TRAIL CONVENTIONS

Every verb (except `status`) writes events to `data/logs/tool-execution.log` (the canonical log per #109 FA10). Conventions:

- `tool_name = "arcis_strategy.<verb>.<phase>"` where phase ∈ {`started`, `completed`, `dispatched.<agent>` (ideate only), `prod_pg_refused`, `cancelled`, `r8_violation`, `engine_failed`, `runner_failed`, `confirmed`, `cancelled_spec_changed`}.
- `session_id` = `$SESSION_ID` (ideate) or `$RUN_ID` (backtest, analyze). Never `$INCIDENT_ID` — research runs are not incidents.
- `params` contains the sanitized inputs + outputs.
- Operator-typed strings are JSON-escaped via env vars before interpolation (stdin-driven shell-out per #109 DA3 fix).
- Confirm events carry `prompt_hash` (SHA-256 of prompt prose) + `option_text` (verbatim option selected).

Per-tool events from underlying `python -m src.tools.<name>` calls are inherited automatically via the decorator stack. The bracketing skill events let the operator grep by `session_id=$SESSION_ID_OR_RUN_ID` and reconstruct the timeline from skill brackets alone.

**Note on session_id propagation:** Same as #109 — the orchestrator runs subprocesses with `ARCIS_SESSION_ID=$SESSION_ID_OR_RUN_ID python -m src.tools.<name> ...`. The tool's CLI envelope (`_cli_envelope.run_cli`) does not currently read this env var into `write_event`. The skill compensates by writing its own bracketing events. See §14 Open Question.

---

## END OF ORCHESTRATOR
```

---

## 4. Verb Conventions

### 4.1 Argument parsing convention

POSITIONAL_INPUT[0] is the verb. Flags follow standard CLI conventions (`--quick`, `--no-cross-domain`, `--run-id <id>`, `--out <path>`). All flags parsed BEFORE positional args are extracted (single-pass left-to-right; `--flag value` consumes two tokens, bare `--flag` consumes one).

### 4.2 Tool JSON envelope contract

All `python -m src.tools.<name> --json` invocations follow the FA16 envelope shape:

- Success: `{...verb-specific result fields...}` (the success body is the result; no wrapper key).
- Failure: `{"error": {"type": "...", "message": "...", "tool": "..."}}` (presence of top-level `error` key indicates failure).

The skill checks `"error" in result` to branch error-vs-success. On error: surface `error.message` verbatim; do NOT pretty-print or paraphrase.

### 4.3 Python-inline subprocess contract

For backtest engine + runner orchestration (Phase B6, B7), the skill invokes Python via `python - <<'PY' ... PY` heredoc subprocess. The Python writes a JSON envelope to stdout matching the same `{...} OR {"error": {...}}` shape. Heredoc form is chosen over `python -c "..."` because the orchestration blocks span 30-80 lines.

**Operator-input safety:** Inside the heredoc, operator-controlled strings (like `strategy_id`) MUST be read from environment variables, NEVER inline-interpolated into the Python source. The orchestrator sets `STRATEGY_ID` env var BEFORE heredoc; the heredoc reads `os.environ["STRATEGY_ID"]`. Inline interpolation would inject shell-meta on malformed input.

### 4.4 Agent dispatch convention

Agent dispatch is via the `Agent(subagent_type: "<name>", prompt: <inject DYNAMIC CONTEXT>)` tool. DYNAMIC CONTEXT is composed inline in commands/strategy.md per phase. The skill parses registered output tags (`<db_report>`, `<git_report>`, `<findings>`) from the agent's response.

Failure modes:
- Agent returns no output tag → SOURCE FAILURE; surface as numbered finding in composed report; proceed.
- Agent dispatch errors at the tool layer → SOURCE FAILURE; surface; proceed.
- Agent timeout at orchestrator budget → mark as `source: agent_timeout`; proceed with available reports.

### 4.5 Error envelope shape (operator-facing)

Every operator-facing error follows a uniform shape:

```
<REFUSE | ERROR> — <verb>: <one-line summary>
  $REASON_OR_DETAIL
  $RESOLUTION_HINT

<post-amble: state about what was/wasn't mutated; audit event id written>
```

E.g.:

```
REFUSE — backtest: ARCIS_ALLOW_PROD_PG is set.
  Reason: arcis:strategy writes ONLY to local research DB.
  Resolution: unset ARCIS_ALLOW_PROD_PG and re-run.

No mutation attempted. No audit event for mutation written.
```

---

## 5. Per-Verb Specifications

### §5.1 ideate

**When to use:** Operator has a hypothesis or theme but no spec yet. Wants to see prior art (db substrate + git history + literature) before authoring a strategy YAML.

**Prerequisites:**
- Operator can articulate the theme as a phrase (e.g., "tighter ATR stops on post-audit momentum names"). Theme may be vague — the skill disambiguates via AskUserQuestion.
- db-investigator + git-historian + research-domain-lead agents are present in `.claude/plugins/arcis/agents/` (verified via Glob at orchestrator entry).

**Step-by-step:**

| Step | Action | Expected output | Decision point | Escalation |
|---|---|---|---|---|
| I1 | Theme classification by keyword | Focus tables + dispatch hint | If no keyword match → AskUserQuestion disambig | Continue with operator's selected closest match |
| I2-A | Parallel dispatch of Wave A (db-investigator + git-historian + research-domain-lead) | 3 `<*_report>` / `<findings>` blocks | If any agent returns no tag → SOURCE FAILURE | Continue with remaining; surface failed agent as finding |
| I2-B | Conditional dispatch of Wave B (research-cross-domain-analyst) | 1 `<findings>` block | Skip if `--no-cross-domain` | n/a |
| I3 | Compose 3-category report (supporting / counter / operational) | Synthesized markdown | n/a | n/a |
| I4 | Write report to OUT_PATH | File on disk | If write fails (permission etc.) → ERROR envelope | STOP |
| I5 | Operator-facing summary | Verbatim text + filenames | n/a | n/a |
| I6 | Audit completion event | Single `arcis_strategy.ideate.completed` event | If write fails → log warning, continue | n/a |

**Expected duration:** 8-12 minutes wall-clock (Wave A = ~8 min; Wave B = ~5 min if invoked; I3-I6 = seconds).

**Success criteria:**
- Report file exists at OUT_PATH.
- Audit event `arcis_strategy.ideate.completed` written with non-empty `wave_a_succeeded` list.
- Operator sees synthesis paragraph + at least 1 supporting finding + 1 counter-finding OR an explicit "no counter-evidence found — proceed with caution; consider hostile-prior-search next round."

---

### §5.2 backtest

**When to use:** Operator has a registered spec at `src/platform/specs/<id>.yaml` and wants to evaluate it. Default = full rigor (walkforward). `--quick` = exploratory in-sample only.

**Prerequisites:**
- Spec file exists at `src/platform/specs/$STRATEGY_ID.yaml`.
- Spec passes `validate_spec()` (FA2).
- For default path: spec has `derived_from` key (null OR full dict; R8 preflight).
- For default path: spec's `entry.kind` is not `python_plugin` (unsupported in v1; FA1 line 386).
- `ARCIS_ALLOW_PROD_PG` env var is NOT set.
- Local research DB is writable.

**Step-by-step:**

| Step | Action | Expected output | Decision point | Escalation |
|---|---|---|---|---|
| (entry) | PROD-PG GATE | Pass/refuse | If set → REFUSE | STOP, audit event written |
| B1 | Spec resolution via load_spec() | JSON envelope with spec metadata | If FileNotFoundError / ValueError → ERROR envelope; if status=shelved → AskUserQuestion; if python_plugin → ERROR | STOP on error/cancel |
| B2 | R8 preflight (default only) | Pass/refuse | If R8ViolationError → REFUSE prose with friendly hint | STOP, audit event written |
| B3 | Plan composition | Verbatim planned-action block | n/a | n/a |
| B4 | AskUserQuestion confirm | Operator decision | Cancel → STOP | n/a |
| B5 | Re-capture preview | spec_hash match | If hashes differ → re-confirm | STOP on operator cancel |
| B6 (quick) | Execute engine | JSON envelope with result_id + trial_id | If engine raises → surface envelope | Write failed audit event; STOP |
| B7 (default) | Per-window engine loop + run_walkforward + persist | JSON envelope with wf_run_id + trial_id + outcome_state | If any window fails / runner raises → surface envelope | Write failed audit event; STOP |
| B8 | Post-execution verification | dbquery row counts | If any count = 0 → surface as anomaly | Continue to B9 (do not auto-retry) |
| B9 | Operator-facing report + audit | Verbatim report + completed event | n/a | n/a |

**Expected duration:**
- `--quick`: 1-3 minutes
- default (full walkforward): 10-30 minutes (5 windows × 2 engine calls; depends on universe size + signal density)

**Success criteria:**
- For `--quick`: `backtest_results` row exists at `result_id`; `trials_registry` row exists at `trial_id`; operator sees ⚠ banner at first AND last line of result block.
- For default: `walkforward_results` row exists with non-null `outcome_state` ∈ {PASS, FAIL, INCONCLUSIVE}; 5 `backtest_results` rows exist with `is_persist_result_ids`; aggregate's `derived_from_backtest_id` is non-null; `trials_registry` row exists; operator sees verbatim `outcome_state` (NOT collapsed to boolean).

---

### §5.3 analyze

**When to use:** Operator has a result_id (from `--quick`) or run_id (from default walkforward) and wants statistical follow-up: DSR + PSR + optional CSCV + recommendation preserving the three-state outcome.

**Prerequisites:**
- Result row exists in `backtest_results` OR `walkforward_results`.
- `trials_registry` may be empty (DSR's N_eff computation has a documented fallback constant `_VARIANCE_FALLBACK = 0.02/250` at trials.py:33; `RuntimeWarning` is emitted from trials.py:109).

**Step-by-step:**

| Step | Action | Expected output | Decision point | Escalation |
|---|---|---|---|---|
| AN1 | Resolve id (try both tables) | result_type ∈ {backtest, walkforward} | If both match → AskUserQuestion (UUID collision anomaly); if neither → ERROR | STOP on neither-match |
| AN2 | Read result + reconstruct trade returns | List of pnl_pct floats | OOS-only filter for walkforward; full for backtest | n/a |
| AN3 | DSR + PSR | DSR result dict + analyze_trial_id | If T<30 → surface guard warning | Continue |
| AN4 | CSCV (optional) | CSCV result dict or unavailability message | If n_results < 2 → unavailable | Continue with informational note |
| AN5 | Operator-facing report | Verbatim with three-state outcome preserved | n/a | n/a |
| AN6 | Audit completion event | Single `arcis_strategy.analyze.completed` | n/a | n/a |

**Expected duration:** 30-90 seconds.

**Success criteria:**
- DSR + PSR values surfaced verbatim from `dsr.deflated_sharpe_ratio()`.
- Three-state `outcome_state` preserved verbatim for walkforward source.
- `trials_registry` row written for this analyze invocation.
- Recommendation prose maps outcome_state → action (PASS → "eligible for shadow_trading review (operator decides)"; FAIL → "do not promote"; INCONCLUSIVE → "re-run with more data / longer window").

---

### §5.4 status

**When to use:** Operator wants a snapshot of the strategy catalog — what specs exist, what their lifecycle states are, what's been run recently, and any FS-vs-DB drift.

**DA12 + DA1/DA4 — status surfaces TWO new sections:**

1. **Active runs** (DA12): backtests with `.started` event but no `.completed` event within last 60 min. Computed by querying `data/logs/tool-execution.log` for `arcis_strategy.backtest.started` events whose `RUN_ID` has no corresponding `.completed` or `.cancelled*` event within the lookback window. Includes the planned `wf_run_id` (if known) so a disconnected operator can re-attach forensically.

2. **Orphans** (DA1/DA4): `backtest_results` rows with `provenance_kind='wf_is_window_orphan_partial_run'`. Per-strategy count + recent (last 30d) result_ids. Surfaced as ANOMALIES per no-out-of-scope-deferral. Also includes a `wf_run_attempt` audit-event count (from DA4) without matching `wf_complete` — these are runs that crashed mid-loop without operator-driven cleanup.

**Prerequisites:** Local research DB readable; `src/platform/specs/` directory exists.

**Step-by-step:**

| Step | Action | Expected output | Decision point | Escalation |
|---|---|---|---|---|
| S1 | Parallel snapshot (FS catalog + 4 DB queries) | JSON envelopes | Any dbquery error → include in report; do not fail | Continue |
| S2 | Compute FS-vs-DB drift | Three lists + anomalies | n/a | n/a |
| S3 | Operator-facing report | Verbatim text | n/a | n/a |
| S4 | (no audit) | n/a | n/a | n/a |

**Expected duration:** 5-15 seconds.

**Success criteria:**
- Operator sees `n_fs` + `n_db` counts + recent runs.
- `silently_skipped_malformed` list explicitly surfaced (per no-out-of-scope-deferral; FA2 line 392 silent-skip surfaced).
- `fs_only` / `db_only` drift surfaced.
- No skill-level audit event written (read-only verb).

---

## 6. R8 Firewall + Rigor Stack Integration

### 6.1 R8 firewall — what it enforces

Per FA9 (`walkforward_firewall.py`), R8 is a three-part contract:

- **R8(a)** `validate_derived_from(spec_raw)` — REQUIRES the `derived_from` key be present in the spec dict. Value may be:
  - `null` (literature-derived, no in-house provenance)
  - A dict with: `source_type ∈ {forensic_audit_ruleset, bootcamp_backtest, shadow_trading_cohort, other}`, `source_run_id` (regex `[A-Za-z0-9_.\-]+`), `source_date_range {start, end}` (ISO dates), optional `source_trade_ids` (list[str])
  - Malformed → `R8ViolationError`
- **R8(b)** `assert_no_overlap(derived_from, windows)` — `source_date_range` MUST NOT overlap ANY OOS window. No-op when `derived_from is None`. Raises `R8ViolationError` on overlap.
- **R8(d)** `ensure_bootcamp_off(bootcamp_override)` — refuses if `WalkForwardConfig.bootcamp_override=True`. Defense-in-depth at runner entry.

### 6.2 Skill-layer R8 preflight (Phase B2)

The skill runs `validate_derived_from(spec.raw)` BEFORE invoking `run_walkforward()`. This:

1. Surfaces R8(a) violations at the skill layer with operator-friendly prose (the §3 Phase B2 REFUSE envelope).
2. Catches the most common case (newly-authored spec forgot to add `derived_from: null`) before the runner spends 10 min computing windows it'll throw away.
3. Does NOT preflight R8(b) (overlap check) — that requires the full window set; the runner does it at entry (FA7 line 246-260) and surfaces the same error class.

**Skip B2 if `QUICK=true`** — the `--quick` in-sample path does NOT invoke `run_walkforward()`, so R8 is moot. The skill SHOULD note in the operator B9 output banner that `--quick` skips R8.

### 6.3 Purging + embargo (R2)

Per FA8 (`walkforward_purging.py`):

- `purge_is_trades(is_trades, test_start, test_end)` — drops IS trades whose [entry, exit] overlaps the OOS interval. Citation: López de Prado 2018 §7.4.
- `embargo_oos_trades(oos_trades, test_start, test_end, embargo_days=5)` — drops OOS trades entered within 5 trading days (Mon-Fri arithmetic — NOT NYSE-holiday-aware) of OOS start.

Both run INSIDE `walkforward_runner.process_window()` at lines 169-179. The skill does NOT invoke them directly. They are GUARANTEED-applied when `run_walkforward()` is called. The skill surfaces this as a "look-ahead-bias guarantees by construction" line in Phase B9 output.

### 6.4 Point-in-time universe

Per FA10 (`walkforward_universe.py`):

- `resolve_universe_as_of(as_of_date, db_path)` returns sorted S&P 100 tickers as-of an ISO date. Membership: `added_date <= date AND (removed_date IS NULL OR date < removed_date)`. Source: `data/reference/sp100_historical.csv`. Survivorship-bias-free.

The skill passes the resolved universe size via `effective_universe_size` to `run_walkforward()` (Phase B7).

### 6.5 Three-state outcome reducer

Per FA7 line 304 (`walkforward_runner.reduce_outcome`): `outcome_state ∈ {PASS, FAIL, INCONCLUSIVE}` + `reason` + window-breakdown counts.

The skill PRESERVES the literal `outcome_state` verbatim through:
- The `arcis_strategy.backtest.completed` audit event params.
- The Phase B9 operator-facing report.
- The `walkforward_results.outcome_state` DB column.
- The `arcis_strategy.analyze.completed` audit event params.
- The Phase AN5 operator-facing report.

NEVER collapsed to boolean. NEVER summarized as "passed" or "failed" without the literal three-state.

---

## 7. Backtest Orchestration

### 7.1 The dual-persist path (post-DA1 provenance_kind dispatch)

For default (full walkforward), the skill invokes BOTH:

1. `backtest_engine.run_backtest()` — once per window per IS/OOS slice (5 windows × 2 = 10 invocations).
2. `walkforward_runner.run_walkforward()` — once, aggregating per-window trades.

The skill writes BOTH layers:

- `persist_backtest_result()` writes `backtest_results` + `backtest_trades` for the IS slice of each window. **Per DA1**, each row gets `provenance_kind='wf_is_window'` so AN1 can disambiguate. The OOS slice's engine call is NOT separately persisted via `persist_backtest_result()` — its trades land only in `walkforward_trades` via `persist_run_result()`.
- `persist_run_result()` writes `walkforward_results` + `walkforward_trades` (OOS only — IS trades not duplicated; per FA7). Returns `None`; capture `run_id` from `wf_result.run_id` (set inside `run_walkforward()` at walkforward_runner.py:326 via `str(uuid.uuid4())`).

**DA1 — provenance_kind enforcement at the data layer.** The `backtest_results.provenance_kind` column (TEXT NOT NULL CHECK in {`quick_in_sample`, `wf_is_window`, `wf_is_window_orphan_partial_run`}) makes the three outcome categories distinguishable at the row level — no composite-key archaeology required for AN1's dispatch.

| provenance_kind | Written by | AN1 behavior |
|---|---|---|
| `'quick_in_sample'` | Phase B6 --quick path | Proceed with existing ⚠ IN-SAMPLE banner (DD-15) |
| `'wf_is_window'` | Phase B7 per-window loop (5 rows per default run) | **REDIRECT** — AskUserQuestion offering wf_run_id (DA8) |
| `'wf_is_window_orphan_partial_run'` | Phase B7-failure-path UPDATE on operator "Keep" (DA4) | **REFUSE** — envelope §10.14 |

**Phase B6/B7 contract — provenance_kind is a required kwarg on persist_backtest_result(). The schema CHECK refuses NULL; T0 enforces the signature update.** This is the smallest possible change that gives AN1 unambiguous dispatch — no composite-key join, no audit-log scan.

The aggregate's `derived_from_backtest_id` STILL points to the FIRST IS-window's `result_id` (representative). v1 still picks first-IS-only. The other 4 IS-window rows are now **explicitly typed** as `wf_is_window`, queryable by:

```sql
-- All 5 IS rows of a particular walkforward run
SELECT result_id FROM backtest_results
  WHERE strategy_id = ? AND spec_hash = ?
  AND provenance_kind = 'wf_is_window'
  AND (start_date, end_date) IN (
    -- pulled from walkforward_results.config_json.windows[*].train_start/train_end
  );
```

Composite-key recovery is now an explicit forensic query — not the only way to disambiguate. The provenance_kind column makes the per-row category a first-class data attribute.

### 7.2 The per-window loop (verbatim from Phase B7)

```python
for window_idx, window in enumerate(wf_config.windows):
    is_result = run_backtest(BacktestConfig(strategy=spec, start_date=window.train_start, end_date=window.train_end, ...))
    is_result_id = persist_backtest_result(is_result, db_path=db_path, git_sha=is_result.reproducibility["code_git_sha"])
    is_persist_result_ids.append(is_result_id)
    
    oos_result = run_backtest(BacktestConfig(strategy=spec, start_date=window.test_start, end_date=window.test_end, ...))
    # oos_result NOT persisted via persist_backtest_result — its trades live only in walkforward_trades.
    
    window_trades[window_idx] = {"is": is_result.trades, "oos": oos_result.trades}
```

### 7.3 Then call run_walkforward

```python
wf_result = run_walkforward(
    strategy_spec_raw=spec.raw,
    config=wf_config,
    window_trades=window_trades,
    spec_path=spec.source,
    forensic_audits=(),
    max_hold_days=21,
    effective_universe_size=effective_universe_size,
    repo_root=".",
    derived_from_backtest_id=is_persist_result_ids[0],
)
```

`run_walkforward()` does:
- R8 firewall (re-validates derived_from + checks overlap)
- Per-window R2 purging + R2 embargo + R4 cost + R6 metrics + R6 power
- Pooled Sharpe + pooled MDE + heavy-tail check + VIX-tier coverage
- Outcome reducer → `OutcomeResult` dataclass

### 7.4 Then persist the aggregate

```python
oos_trades_per_window = {i: window_trades[i]["oos"] for i in window_trades}
wf_run_id = wf_result.run_id
persist_run_result(wf_result, strategy_spec_raw=spec.raw, oos_trades_per_window=oos_trades_per_window, db_path=db_path)  # returns None
```

`persist_run_result()` writes `walkforward_results` (1 row) + `walkforward_trades` (N OOS rows per window, with `is_in_is_window=0` and `purged` / `embargoed` flags from `classify_trades_for_audit()`).

### 7.5 Auto-fire suppression

`scripts/run_backtest.py:97` triggers `walkforward_autofire` post-persist. The skill explicitly sets `WALKFORWARD_AUTOFIRE_ENABLED=false` in the subprocess env (Phase B6 / B7) so the autofire side-effect does NOT fork another walkforward. The skill already runs walkforward explicitly; autofire would double-fire.

### 7.6 Runtime budget

5 windows × 2 engine calls × per-call ~1-3 min (universe size × signal density dependent) = **~10-30 min wall-clock** for default backtest.

The skill surfaces this estimate in Phase B3's planned-action block so the operator knows what they're approving.

---

## 8. Statistical Rigor — DSR + CSCV + trials_registry

### 8.1 Deflated Sharpe Ratio (DSR)

Per FA11 (`dsr.py`):

- `deflated_sharpe_ratio(trade_returns, n_trials, trials_sr_variance=None) -> dict` with keys `SR_hat, skew, kurt, T, E_SR_max, PSR, DSR`.
- DSR formula: SR multiplicity-corrected by `E[max SR | N_eff]` from extreme-value theory. Threshold: `DSR > 0.95` = significant at 95% conf.
- `probabilistic_sharpe_ratio(sr_hat, sr_benchmark=0, T, skew, kurt)` — pre-multiplicity PSR; also surfaced.
- Small-sample warning: at `T < 30`, DSR unreliable; surface PSR instead and surface the guard explicitly (dsr.py:85 RuntimeWarning).

### 8.2 N_eff (trials_registry)

Per FA11 (`trials.py`):

- `get_current_n_eff(db_path)` — global count of all rows in `trials_registry`. Used as `N` in DSR's `E_SR_max` formula.
- `get_variance_for_strategy_family(family=<str|None>, db_path)` — signature per trials.py:84-85. As of v0.25 the `family` parameter is IGNORED (trials.py:97 has no WHERE family=… clause; v0.25 TODO); the function returns GLOBAL trial variance when ≥20 trials exist, else the documented fallback `_VARIANCE_FALLBACK = 0.02/250` (trials.py:33) with `RuntimeWarning` emitted at trials.py:109. N_eff via `get_current_n_eff` is family-correct; only the variance fallback is global. Surfaced as §14 OQ for operator to confirm global-variance v1 behavior OR file follow-up to wire the family WHERE clause.
- `record_trial(strategy_id, spec_hash, sr_raw, sr_ann, n_trades, skew, kurt, passed_dsr_gate, params_searched_json, n_params_searched, db_path) -> trial_id` — writes one row.

### 8.3 Skill stewardship of trials_registry

**Both backtest AND analyze record a trial** (Decision DD-5 in §13):

- **Backtest verb (Phase B6 / B7):** records ONE trial after persist completes. Purpose: each backtest run is a "trial attempt" and should bump N_eff so subsequent analyze sees the multiplicity correctly. `passed_dsr_gate=0` (backtest does not compute DSR; analyze does).
- **Analyze verb (Phase AN3):** records ONE additional trial entry. Purpose: each analyze is itself a search-step (operator examined a result + computed DSR). `passed_dsr_gate=1 if DSR > 0.95 else 0`.

**Why both?** Per FA11 cross-cutting concern, scripts/run_backtest.py does NOT call `record_trial()` — historical N_eff is undercounted. The skill fills the gap (no out-of-scope deferral). Recording in both phases conservatively bumps N_eff and keeps DSR's multiplicity correction defensible.

**Alternative considered (DD-5 in §13):** Skill records ONLY in backtest, NOT in analyze. Rejected because analyze re-examines a result — examining N results to pick the best IS the multiplicity DSR is designed to correct, so each analyze IS a search step.

### 8.4 CSCV (Combinatorially Symmetric Cross-Validation)

Per FA11 (`cscv.py`):

- `pbo_from_pnl_matrix(pnl_matrix, S=16)` — input T×N matrix (T daily obs × N strategy configs); returns `{PBO, logit_distribution, performance_degradation_points}`. Reject threshold: `PBO > 0.5`.
- Needs ≥2 distinct backtest configs to be meaningful.

**Skill semantics (Phase AN4):** CSCV is INFORMATIONAL. If `< 2` prior `backtest_results` rows exist for the strategy_id, surface "CSCV unavailable: <2 backtests for $STRATEGY_ID" as an informational line; do NOT fail. If `>= 2`: pull all per-result daily PnL via JOIN to `backtest_trades`, construct the matrix, call `pbo_from_pnl_matrix`, surface result.

### 8.5 Three-state outcome — operator-facing prose

The skill renders `outcome_state` verbatim with the §3 Phase AN5 interpretation guide:

- **PASS** — "Walkforward outcome reducer accepted. Multiple OOS windows showed positive risk-adjusted return with adequate power. Eligible for shadow_trading promotion (operator decides)."
- **FAIL** — "Walkforward outcome reducer rejected. Insufficient evidence the strategy beats benchmark + costs OOS. Do not promote."
- **INCONCLUSIVE** — "Reducer could not decide. Sub-reason ($REASON) below. Treat as not-yet-deployable; re-run with more universe history / longer windows / larger position sizing where appropriate."

NEVER collapse to boolean. NEVER paraphrase as "the strategy works" or "the strategy doesn't work."

---

## 9. Audit Trail

### 9.1 Bracket events per verb

| Verb | Started event | Mid events | Completed event |
|---|---|---|---|
| ideate | `arcis_strategy.ideate.started` | `.dispatched.db-investigator`, `.dispatched.git-historian`, `.dispatched.research-domain-lead`, `.dispatched.research-cross-domain-analyst` (conditional), `.recheck_result` (n/a — ideate has no re-check) | `arcis_strategy.ideate.completed` |
| backtest | `arcis_strategy.backtest.started` | `.r8_violation` (if fails), `.confirmed` (after B4), `.cancelled_spec_changed` (if B5 re-confirm denied), `.engine_failed` / `.runner_failed` (per phase) | `arcis_strategy.backtest.completed` |
| analyze | `arcis_strategy.analyze.started` | (none — analyze is single-shot) | `arcis_strategy.analyze.completed` |
| status | (no audit event — read-only) | n/a | n/a |

Plus skill-layer refusal events: `.prod_pg_refused`, `.spec_resolution_failed`, `.shelved_abort`, `.python_plugin_unsupported`, `.cancelled` (operator-cancel at confirm).

### 9.2 Schema per event

All events use the existing `_execution_log.write_event` shape:

```python
write_event(
    tool_name=str,          # "arcis_strategy.<verb>.<phase>"
    params=dict,            # sanitized inputs + outputs
    result=Literal["success", "failure"],
    duration_ms=int,
    session_id=str,         # SESSION_ID (ideate) or RUN_ID (backtest/analyze)
)
```

**`params` contents per phase:**

- `started`: `{positional, flags}` (sanitized; operator-typed strings JSON-encoded via env vars)
- `snapshot_captured` (DA2 — backtest only): `{spec_snapshot_path, spec_hash, strategy_id, run_id}`
- `confirmed`: `{prompt_hash: sha256, option_text: verbatim, strategy_id, quick, spec_hash, spec_snapshot_path}` — DA2 adds `spec_snapshot_path`
- `r8_violation`: `{error_class: "R8ViolationError", message, strategy_id, spec_hash}`
- `concurrent_refused` (DA5): `{strategy_id, lock_path, lock_held_since}`
- `db_path_blocked` (DA9): `{strategy_id, db_path_redacted, matched_signature}`
- `snapshot_tampered` (DA2 anomaly): `{strategy_id, run_id, b1_hash, b5_snapshot_hash}` — written if snapshot file mutated post-B1.5
- `wf_run_attempt` (DA4): `{strategy_id, spec_hash, spec_snapshot_path, expected_is_rows, lock_path}`
- `window_persisted` (DA4): `{window_idx, is_result_id, spec_hash}`
- `wf_complete` (DA4): `{strategy_id, wf_run_id, is_persist_result_ids, spec_hash}`
- `wf_partial` (DA4): `{strategy_id, spec_hash, spec_snapshot_path, failure_stage, written_is_rows, error}`
- `engine_failed` / `runner_failed`: `{error: <verbatim envelope dict>, strategy_id, spec_hash, phase}`
- `completed`: per-verb (see §3 verb sections for full param schemas — DA1/DA2 add `provenance_kind_per_row` + `spec_snapshot_path`)
- `refused_orphan` (DA1, analyze only): `{result_id, strategy_id, provenance_kind}`
- `deferred_family_variance` (DA3, analyze only): `{distinct_strategy_ids}`

**DA2/DA7 invariant — spec_hash immutability across a RUN_ID:** `confirmed.spec_hash` MUST equal `completed.spec_hash` for any RUN_ID where both events exist. This is guaranteed by construction (B7 loads from the snapshot path captured at B1.5; the snapshot file is the binding contract for the run). If a future audit-log query finds `confirmed.spec_hash != completed.spec_hash` for the same RUN_ID, the snapshot mechanism failed and an anomaly event (`arcis_strategy.backtest.spec_hash_drift_detected`) MUST be written by the auditor.

### 9.3 prompt_hash + option_text on confirms

Mirror #109 DA8. For every `AskUserQuestion` that gates a mutation (Phase B4; Phase B5 re-confirm if hashes differ), write:

- `prompt_hash` = SHA-256 of the verbatim prompt prose shown to operator (use `hashlib.sha256(prompt.encode()).hexdigest()`).
- `option_text` = the exact text of the option the operator selected (e.g., `"Approve — run backtest"`).

This lets the operator audit-trace: "what was the operator asked, and what did they pick?" without re-reading the orchestrator source.

### 9.4 stdin-driven shell-out (JSON safety)

Every Bash subprocess that interpolates operator-typed strings (e.g., `STRATEGY_ID`, `THEME`) MUST pass them via env vars or stdin, NOT inline interpolation:

```bash
# CORRECT (env var):
STRATEGY_ID="$STRATEGY_ID" python - <<'PY'
import os
sid = os.environ["STRATEGY_ID"]
...
PY

# WRONG (inline interpolation — FAILS on operator typo with shell-meta):
python - <<PY  # note: no 'PY' quoting, so heredoc interpolates
sid = "$STRATEGY_ID"
PY
```

Per #109 DA3 fix — single-quoted heredoc delimiter (`<<'PY'`) prevents shell interpolation; operator-typed strings reach Python via `os.environ` ONLY.

---

## 10. Error Envelopes

Per §3 Error Envelopes section, every error has a uniform `<REFUSE | ERROR> — <verb>: <summary>` shape. Full examples below; the implementing PM commits these in `references/error-envelopes.md`:

### 10.1 Verb-unknown
```
ERROR — unknown verb: "<received>". Expected one of: ideate, backtest, analyze, status.
Usage: ...
```

### 10.2 PROD-PG refused
```
REFUSE — backtest: ARCIS_ALLOW_PROD_PG is set.
  Reason: arcis:strategy writes ONLY to local research DB. Prod-PG writes are forbidden by skill policy.
  Resolution: unset ARCIS_ALLOW_PROD_PG and re-run.

No mutation attempted. No audit event for mutation written.
```

### 10.3 Spec not found
```
ERROR — backtest: spec resolution failed for "<strategy_id>":
  Type: FileNotFoundError
  Detail: src/platform/specs/<strategy_id>.yaml does not exist
  Resolution: confirm spec file exists and re-run. Available specs: <list from list_available_specs()>
```

### 10.4 Spec malformed
```
ERROR — backtest: spec resolution failed for "<strategy_id>":
  Type: ValueError
  Detail: <validate_spec error message>
  Resolution: fix the YAML at src/platform/specs/<strategy_id>.yaml and re-run.
```

### 10.5 R8 firewall violation
```
REFUSE — R8 firewall preflight failed for <strategy_id>:
  <verbatim R8ViolationError message>
  
  R8 requires the strategy YAML to declare a `derived_from` key (value may be null OR a dict
  with source_type ∈ {forensic_audit_ruleset, bootcamp_backtest, shadow_trading_cohort, other},
  source_run_id (regex [A-Za-z0-9_.\-]+), source_date_range {start, end}, optional source_trade_ids).
  
  Resolution: add `derived_from:` to src/platform/specs/<strategy_id>.yaml and re-run.
  
  No mutation attempted. No backtest tables written.
```

### 10.6 Engine failure (mid-run)
```
ERROR — backtest: engine raised unexpectedly:
  <verbatim Python exception class + message + first 3 lines of stack>
  
  Phase: <B6 (--quick) | B7 window <N> IS-slice | B7 window <N> OOS-slice>
  Strategy: <strategy_id>
  spec_hash: <hash>
  
  No further mutations attempted. Partial state may exist:
    is_persist_result_ids written so far: [<list>]
  
  Resolution: inspect partial rows via /arcis:strategy status <strategy_id>; manually clean up if needed.
```

### 10.7 Walkforward runner failure
```
ERROR — backtest: walkforward runner raised unexpectedly:
  <verbatim Python exception class + message>
  
  Strategy: <strategy_id>
  spec_hash: <hash>
  Windows processed before failure: <N>
  
  Note: per-window IS backtest_results rows DID persist (the runner failed at aggregation, not per-window engine).
  No walkforward_results row written. No trials_registry row written.
  
  Resolution: inspect IS rows via /arcis:strategy status; investigate runner error.
```

### 10.8 Corpus binding failure (defensive — v1 leaves corpus_id=None)
```
REFUSE — backtest: corpus manifest missing for declared corpus_id <id>:
  <verbatim RuntimeError message from FA7 line 233-244>
  
  Resolution: either bind a corpus via the (future) corpus verb, or leave config.corpus_id=None for v1.
  
  v1 default behavior is corpus_id=None — this error indicates the implementing PM set corpus_id explicitly.
```

### 10.9 Unknown action / unknown run-id (analyze)
```
ERROR — analyze: unknown run-id: "<received>". Not found in backtest_results or walkforward_results.
  Resolution: verify the id with /arcis:strategy status; re-run with correct id.
```

### 10.10 Operator denial at confirm
```
backtest CANCELLED by operator at Phase B4. No mutation attempted. Audit event arcis_strategy.backtest.cancelled written.
```

### 10.11 Tool unavailable (graceful degradation)
```
WARNING — tool <name> not available (python -m src.tools.<name> --help exited non-zero).
  Affected: <verb step>
  Continuing with reduced output. Refresh tooling or re-run.
```

### 10.12 Concurrent backtest refused (DA5)
```
ERROR — backtest: concurrent backtest detected for <strategy_id>.
  Another /arcis:strategy backtest run is currently holding the lock at data/locks/strategy/<strategy_id>.lock.
  Started: <lock_held_since>
  
  Refusing to overlap (concurrent writes to the same strategy_id would corrupt audit invariants).
  
  Resolution: wait for the active run to complete (see /arcis:strategy status — Active Runs section).
  Or use --force to bypass (NOT recommended).
```

### 10.13 db_path matches prod-PG signature (DA9 — defense-in-depth)
```
REFUSE — backtest: resolved db_path matches a prod-PG signature.
  db_path (last 30 chars): ...<tail>
  Matched signature: <signature>
  
  Reason: arcis:strategy writes ONLY to local research DB. Defense-in-depth check inside heredoc.
  Resolution: confirm arcis_config.yaml paths.db_canonical points to local SQLite or pg.test_dsn (port 5434).
  
  No mutation attempted. No audit event for mutation written.
```

### 10.14 Analyze refused on orphan IS row (DA1)
```
REFUSE — analyze: result_id <result_id> is from a partial walkforward run that did NOT complete.
  provenance_kind: wf_is_window_orphan_partial_run
  strategy_id: <strategy_id>
  
  The walkforward aggregation step failed mid-run; this IS slice is forensic-only.
  No walkforward_results row exists; no OOS validation was performed.
  
  Resolution: re-run /arcis:strategy backtest <strategy_id> to produce a clean walkforward result.
  If you need to inspect the orphan IS metrics for debugging, query backtest_results directly
  via /arcis:strategy status <strategy_id> (Orphans section).
```

### 10.15 Ideate incomplete — research-domain-lead missing (DA6)
```
ERROR — ideate: research-domain-lead did not return findings within Wave A budget (8 min).
  research-domain-lead is REQUIRED for synthesis.
  
  Wave A status:
    research-domain-lead: <status>
    db-investigator:      <status>
    git-historian:        <status>
  
  Resolution: re-run with extended budget:
    /arcis:strategy ideate "<theme>" --extended-wave-a-budget 16
  Or dispatch research-domain-lead directly for diagnostic:
    /arcis:research domain-lead "<theme>"
  
  No report written. No partial synthesis surfaced.
```

### 10.16 Analyze WARNING — variance fallback fired (DA13)
```
WARNING — analyze: DSR computed against variance fallback (trials_registry has <N> trials, below 20 threshold).
  Source: _VARIANCE_FALLBACK = 0.02/250 (trials.py:33; RuntimeWarning emitted at trials.py:109).
  variance_source: fallback_with_warning
  
  This is informational — analyze continues. DSR is computed with the documented fallback variance,
  which is a conservative under-estimate of true family variance. Forensic recovery 6 months later
  can use the audit-event params.variance_source field to determine if this fallback was active.
```

---

## 11. Golden Transcripts

### 11.1 ideate — happy path

```
$ /arcis:strategy ideate "tighter ATR stops on post-audit momentum names"

SESSION_ID: ideate-2026-05-26T13-15-00Z-7a02fc
NOW_ET: 2026-05-26 13:15 EDT
Working directory: C:/arcis/halcyon-lab

Theme classified: keyword match on "atr" + "post-audit" → focus tables: backtest_trades, shadow_trades, audit_reports, strategy_registry. Domain: financial-economic.

Dispatching Wave A (db-investigator + git-historian + research-domain-lead) in parallel...

[8 min elapsed]

Wave A returned:
  db-investigator      → <db_report> received (3 findings, coverage=high)
  git-historian        → <git_report> received (4 findings, last commit on specs/ within 14d)
  research-domain-lead → <findings> received (2 specialist sub-reports synthesized)

Dispatching Wave B (research-cross-domain-analyst)...

[4 min elapsed]

Wave B returned: <findings> received (2 cross-domain tensions surfaced)

Report written: docs/strategy-ideation/2026-05-26-tighter-atr-stops-on-post-audit-momentum-names.md

═════════════════════════════════════════════════════════════════
IDEATION ideate-2026-05-26T13-15-00Z-7a02fc — COMPLETE
Theme: tighter ATR stops on post-audit momentum names
Captured: 2026-05-26 13:15 EDT
Wave A agents: [db-investigator, git-historian, research-domain-lead] (succeeded: 3, failed: 0)
Wave B agent: research-cross-domain-analyst (succeeded)
Report written: docs/strategy-ideation/2026-05-26-tighter-atr-stops-on-post-audit-momentum-names.md

SYNTHESIS:
Post-audit momentum strategies have a documented edge in 2-week horizons after forensic audits surface
sector-skewed rulesets (research-domain-lead synthesis from Cohen-Malloy 2020 + Frazzini 2018). 
Tighter ATR stops (e.g., ATR×1.5 vs the post_audit_ruleset_v1 default of ATR×2.5) would compress
drawdown but at risk of premature exits in vol spikes — db-investigator reports VIX>25 OOS trades in
post_audit_ruleset_v1's prior backtest had 23% higher early-stop rates already at ATR×2.5. The
research-cross-domain-analyst surfaces a tension: literature supports tighter stops in low-vol regimes
only, but the registered universe (S&P 100) spans all regimes. Recommended next step: parameter-sweep
ATR multiplier ∈ {1.5, 2.0, 2.5} with regime-conditional logic.

SUPPORTING EVIDENCE (4 total — first 4 in detail):
1. [High] Post-audit alpha persists across regimes — source: research-domain-lead
   Evidence: Forensic-audit-driven signals show 12-18mo persistence in academic literature; in-house...
   ...

COUNTER-EVIDENCE (2 total):
1. [Moderate] Tighter ATR stops doubled premature-exit rate in low-vol OOS — source: db-investigator
   ...

OPERATIONAL CONCERNS (3 total):
1. [High] post_audit_ruleset_v1 has only 1 prior walkforward run — N_eff for DSR insufficient
   ...

PROPOSED NEXT ACTIONS:
  A. Open docs/strategy-ideation/2026-05-26-tighter-atr-stops-on-post-audit-momentum-names.md
     and refine the YAML scaffold (sections: exit.atr_multiplier, position_sizing).
  B. /arcis:strategy backtest post_audit_ruleset_v1 --quick  (in-sample sanity)
  C. /arcis:strategy backtest post_audit_ruleset_v1          (full walkforward)
```

### 11.2 backtest --quick — happy path

```
$ /arcis:strategy backtest post_audit_ruleset_v1 --quick

RUN_ID: run-2026-05-26T13-30-00Z-9c3f1a
NOW_ET: 2026-05-26 13:30 EDT
PROD_PG_GATE: not set → proceed
Working directory: C:/arcis/halcyon-lab

Phase B1 — Resolving spec post_audit_ruleset_v1...
  spec resolved: derived_from present (forensic_audit_ruleset / april-2026-forensic-audit)
  status_in_yaml: (none) — active
  entry_kind: event_driven — supported
  spec_hash: a3b7c... (sha256)
  
Phase B2 — R8 preflight SKIPPED (--quick path)
Phase B3 — Planning run...

⚠ IN-SAMPLE ONLY — not rigor-grade

Planned action: in-sample backtest of post_audit_ruleset_v1
  Engine: src.platform.backtest_engine.run_backtest()
  Runner: NOT invoked (--quick = skip walkforward)
  Window: 2018-01-01 → 2024-12-31 (v1 canonical research-desk window; strategy YAML does not carry a window field — see §14 OQ7)
  R2 purging: NOT applied (single window)
  R2 embargo: NOT applied
  R8 firewall: NOT checked
  Writes: backtest_results × 1, backtest_trades × N, trials_registry × 1
  Write target: LOCAL research DB
  Estimated runtime: 1-3 min
  Spec hash: a3b7c...
  Code git sha: 4d2e8...

⚠ IN-SAMPLE ONLY — not rigor-grade

Phase B4 — Approve?
  [operator selects: "Approve — run backtest"]

audit event: arcis_strategy.backtest.confirmed (prompt_hash=..., option_text="Approve — run backtest")

Phase B5 — Re-capturing spec_hash... unchanged. Proceed.
Phase B6 — Executing engine... [97s elapsed]
Phase B8 — Verifying writes...
  backtest_results: 1 row ✓
  trials_registry: 1 row ✓

═════════════════════════════════════════════════════════════════
⚠ ⚠ ⚠  IN-SAMPLE ONLY — not rigor-grade  ⚠ ⚠ ⚠
(no walkforward; no OOS validation; results CANNOT be used to gate promotion to shadow_trading)

BACKTEST --quick — RESULT
RUN_ID: run-2026-05-26T13-30-00Z-9c3f1a
Strategy: post_audit_ruleset_v1
Engine: backtest_engine.run_backtest()
result_id: f01a8e02-3...
trial_id:  7c0a91b1-d...

Metrics:
  n_trades:           284
  total_return_pct:   43.2
  sharpe:             1.81       (raw — NOT deflated; use /arcis:strategy analyze run-... for DSR)
  sortino:            2.13
  calmar:             0.92
  max_drawdown_pct:   -18.4
  win_rate:           0.59
  profit_factor:      1.42

Provenance:
  spec_hash:     a3b7c...
  code_git_sha:  4d2e8...

Next actions:
  /arcis:strategy analyze f01a8e02-3...
  /arcis:strategy backtest post_audit_ruleset_v1   (promote to full walkforward)

⚠ ⚠ ⚠  IN-SAMPLE ONLY — not rigor-grade  ⚠ ⚠ ⚠

audit event: arcis_strategy.backtest.completed (quick=true)
```

### 11.3 backtest (default = full walkforward) — happy path

```
$ /arcis:strategy backtest post_audit_ruleset_v1

RUN_ID: run-2026-05-26T13-45-00Z-3e21fa
PROD_PG_GATE: not set → proceed

Phase B1 — Resolving spec... OK (entry_kind: event_driven; derived_from present)
Phase B2 — R8 preflight... PASS (validate_derived_from succeeded)
Phase B3 — Planning run...

Planned action: full walkforward backtest of post_audit_ruleset_v1
  Engine: src.platform.backtest_engine.run_backtest()
  Runner: src.platform.rigor.walkforward_runner.run_walkforward()
  Windows: 5 (DEFAULT_WINDOWS, 2017-2024)
  Per-window calls: 2 engine invocations → 10 total
  R2 purging + embargo: applied per window
  R8 firewall: validated at preflight + runner entry
  Universe: sp100 (point-in-time, ~98-102 tickers across windows per FA10)
  Writes:
    - backtest_results: 5 rows (one per IS window)
    - backtest_trades: N rows
    - walkforward_results: 1 row (with outcome_state literal)
    - walkforward_trades: N OOS rows
    - trials_registry: 1 row
  Write target: LOCAL research DB
  Estimated runtime: 10-30 min
  Spec hash: a3b7c...
  Code git sha: 4d2e8...

Phase B4 — Approve?
  [operator selects: "Approve — run backtest"]

Phase B5 — spec_hash unchanged. Proceed.
Phase B7 — Executing per-window loop + run_walkforward...
  Window 0 IS: 2015-2016 → run_backtest() → persist_backtest_result() → result_id 8a1f...
  Window 0 OOS: 2017-2018 → run_backtest()
  Window 1 IS: ... [22 min total elapsed]
  ...
  Window 4 OOS: complete
  run_walkforward() — R8 firewall PASS, per-window rigor processed
  outcome_state: INCONCLUSIVE
  persist_run_result() → wf_run_id b9c2...

Phase B8 — Verifying writes...
  walkforward_results: 1 row ✓
  walkforward_trades: 421 rows ✓
  trials_registry: 1 row ✓

═════════════════════════════════════════════════════════════════
BACKTEST (full walkforward) — RESULT
RUN_ID: run-2026-05-26T13-45-00Z-3e21fa
Strategy: post_audit_ruleset_v1
Runner: walkforward_runner.run_walkforward()
wf_run_id: b9c2...   ← analyze this id
trial_id:  4f8a...

OUTCOME_STATE: INCONCLUSIVE   ← preserved verbatim from walkforward_results.outcome_state
Reason: 3 of 5 windows inconclusive (power) — OOS trade count <30 in windows 2-4

Window breakdown:
  PASS:                 1 / 5
  FAIL:                 1 / 5
  INCONCLUSIVE (data):  0 / 5
  INCONCLUSIVE (power): 3 / 5
  INCONCLUSIVE (duration): 0 / 5

Pooled stats:
  pooled_sharpe:       0.78  (raw — NOT deflated)
  pooled_mde:          0.42
  effective_universe_size: 98 (point-in-time S&P 100 at first OOS start, per FA10)

Rigor guarantees by construction:
  R2 purging applied:  yes
  R2 embargo:          5 trading days
  R8 firewall:         passed
  Universe lookahead:  none

Provenance:
  spec_hash:     a3b7c...
  code_git_sha:  4d2e8...

Next actions:
  /arcis:strategy analyze b9c2...   — compute DSR + multiplicity correction
  (review the literal outcome_state above; do NOT collapse to boolean)

Internal provenance (forensic queries only — DO NOT analyze these IS slices; use b9c2... above):
  IS-window result_ids: [8a1f..., d20c..., e74b..., a12f..., c0d9...]  (provenance_kind='wf_is_window')
  spec_snapshot_path: data/logs/spec_snapshots/run-2026-05-26T13-45-00Z-3e21fa.yaml
  Active lock released: data/locks/strategy/post_audit_ruleset_v1.lock

audit event: arcis_strategy.backtest.completed (outcome_state=INCONCLUSIVE, spec_hash unchanged from confirm)
audit event: arcis_strategy.backtest.wf_complete (wf_run_id=b9c2..., expected_is_rows=5, actual=5)
```

### 11.4 analyze — happy path on the walkforward run above

```
$ /arcis:strategy analyze b9c2...

RUN_ID: run-2026-05-26T14-15-00Z-1f08bc
Resolving id... matched walkforward_results.run_id

Phase AN2 — reading result + trade returns...
  421 OOS trades (after purge/embargo filter)
Phase AN3 — DSR + PSR...
  N_eff from trials_registry: 14
  trials_sr_variance: 0.02/250 (fallback — family has <20 trials)
Phase AN4 — CSCV...
  n_results for post_audit_ruleset_v1: 6 → CSCV available
  pbo_from_pnl_matrix(S=16) → PBO=0.41

═════════════════════════════════════════════════════════════════
ANALYZE — RESULT
RUN_ID (analyze): run-2026-05-26T14-15-00Z-1f08bc
Source: walkforward_results.run_id = b9c2...
Strategy: post_audit_ruleset_v1
Source created_at: 2026-05-26 14:08 UTC

OUTCOME_STATE: INCONCLUSIVE   ← preserved verbatim from walkforward_results

  Interpretation:
    PASS         — Walkforward outcome reducer accepted. Eligible for shadow_trading promotion.
    FAIL         — Walkforward outcome reducer rejected. Do not promote.
    INCONCLUSIVE — Reducer could not decide. Sub-reason below.

  Sub-reason: 3 of 5 windows inconclusive (power) — OOS trade count <30 in windows 2-4
  Window breakdown: PASS=1, FAIL=1, INC(data)=0, INC(power)=3, INC(duration)=0

Statistical follow-up:

  Deflated Sharpe Ratio (López de Prado 2018):
    SR_hat:     0.78
    skew:       -0.12
    kurt:       3.42
    T:          421
    E_SR_max:   0.51   (expected max under N_eff = 14 independent trials)
    PSR:        0.94   (Probabilistic Sharpe Ratio vs SR_benchmark=0)
    DSR:        0.81   (multiplicity-corrected; <0.95 = not significant at 95% conf)

  CSCV (Combinatorially Symmetric Cross-Validation):
    PBO:        0.41   (Probability of Backtest Overfit — <0.5 = acceptable)
    Performance degradation:  -0.18 (median rank degradation IS→OOS)

Provenance:
  Source spec_hash: a3b7c...
  Source code_git_sha: 4d2e8...
  Source provenance_kind: (walkforward source — not applicable)
  N_eff used: 14
  trials_sr_variance: 0.02/250  (source: fallback_with_warning — trials_registry has 14 trials < 20 threshold; trials.py:33 + RuntimeWarning at trials.py:109; family filter is v0.25 TODO — trials.py:97)
  trials_count_at_analyze_time: 14
  analyze_trial_id recorded: 1a3f...

⚠  analyze: DSR computed against variance fallback (trials_registry had 14 trials < 20 threshold).
   Source: _VARIANCE_FALLBACK = 0.02/250. variance_source=fallback_with_warning recorded in audit event params.

Recommendation:
  Outcome=INCONCLUSIVE + DSR=0.81 (below 0.95) + PSR=0.94 (above 0.95 but pre-multiplicity).
  Reducer needs more OOS trades to decide. The DSR vs PSR gap (0.81 vs 0.94) reflects
  multiplicity penalty from N_eff=14 — note that 14 includes both prior backtests AND prior
  analyzes for this strategy family.
  
  Suggested next step: extend universe (add S&P 500 names from large-cap universe) OR
  extend backtest window (push earlier start to 2010 if data available) to surface more OOS trades.
  Do NOT promote to shadow_trading on INCONCLUSIVE outcome.

audit event: arcis_strategy.analyze.completed (outcome_state=INCONCLUSIVE preserved)
```

### 11.5 status — happy path

```
$ /arcis:strategy status

STATUS SNAPSHOT — 2026-05-26 14:30 EDT
Scope: all strategies

Filesystem specs (2 total):
  lazy_prices_v1         Lazy Prices             (status: shelved   | entry: event_driven | universe: sp100 | derived_from: yes)
  post_audit_ruleset_v1  Post-Audit Ruleset      (status: (active)  | entry: event_driven | universe: sp100 | derived_from: yes)

DB strategy_registry (3 total):
  lazy_prices_v1          current_status=deprecated     haircut_bps=75  last_status_change=2025-08-12
  post_audit_ruleset_v1   current_status=backtested     haircut_bps=75  last_status_change=2026-05-15
  legacy_momentum_v0      current_status=deprecated     haircut_bps=75  last_status_change=2024-11-03

Recent backtests (last 30d, top 20):
  f01a8e02...  post_audit_ruleset_v1  sharpe=1.81  total_return=43.2%  max_dd=-18.4%  2026-05-26 13:31
  8a1f...      post_audit_ruleset_v1  sharpe=2.04  total_return=22.1%  max_dd=-9.2%   2026-05-26 13:48
  d20c...      post_audit_ruleset_v1  sharpe=1.32  total_return=14.5%  max_dd=-15.1%  2026-05-26 13:51
  ...

Recent walkforwards (last 30d, top 20):
  b9c2...  post_audit_ruleset_v1  outcome=INCONCLUSIVE  reason="3 of 5 windows inconclusive (power)"  pooled_sharpe=0.78  pass/fail/inc=1/1/3  2026-05-26 14:08

trials_registry global N_eff: 14
trials_registry distinct strategy_ids: 2  (DA3 threshold for family-variance approximation is ≤3 — currently OK)

Active runs (DA12 — backtests with .started but no .completed within last 60 min):
  (none — all recent runs completed)

FS ↔ DB DRIFT:
  fs_only (2): []   ← no drift; both FS specs have registry rows
  db_only (1): [legacy_momentum_v0]   ← registry row but no spec file
                 → likely stale row from a deleted spec (consider DELETE FROM strategy_registry)
  in sync (2): [lazy_prices_v1, post_audit_ruleset_v1]

ANOMALIES (per no-out-of-scope-deferral):
  Malformed YAML files silently skipped by list_available_specs() (0): []
  R8-noncompliant specs (missing derived_from key, 0): []
  walkforward_results with NULL derived_from_backtest_id (0): []
  Orphans — backtest_results with provenance_kind='wf_is_window_orphan_partial_run' (0): []
  wf_run_attempt audit events without matching wf_complete (last 30d, 0): []

Snapshot complete. Status is read-only — no audit event written.
```

---

## 12. Manual Verification Checklist

Implementing PM runs through this checklist BEFORE requesting dual-Opus QA. Each item must be PASS.

1. **Cold-read by fresh session** — open a clean Claude Code session, type `/arcis:strategy` with no args; verify the verb-unknown ERROR envelope fires verbatim per §10.1.
2. **PROD-PG refusal** — set `ARCIS_ALLOW_PROD_PG=1` in env; run `/arcis:strategy backtest post_audit_ruleset_v1`; verify the §10.2 REFUSE prose fires; verify audit event `arcis_strategy.backtest.prod_pg_refused` lands in `data/logs/tool-execution.log`; verify NO row written to any backtest table.
3. **Spec resolution failure** — run `/arcis:strategy backtest nonexistent_strategy`; verify §10.3 fires with the `list_available_specs()` list in the resolution hint.
4. **Shelved-strategy gate** — author a spec with `status: shelved` (e.g., temporarily set lazy_prices_v1.yaml's status to shelved if not already); run `/arcis:strategy backtest lazy_prices_v1`; verify the shelved AskUserQuestion fires; verify both "Yes" and "No" branches work.
5. **R8 preflight** — author a test spec without `derived_from` key; run `/arcis:strategy backtest <test_id>`; verify §10.5 fires with the friendly remediation hint; verify NO walkforward_results row written; verify audit event `arcis_strategy.backtest.r8_violation` lands.
6. **Spec-hash re-capture** — start `/arcis:strategy backtest post_audit_ruleset_v1`; at the B4 confirm prompt, in a separate terminal, append a comment to the spec YAML (which changes spec_hash but is semantically inert); approve at B4; verify the B5 re-confirm prompt fires showing the diff; verify both "Yes — re-approve" and "Cancel" branches work.
7. **Backtest --quick happy path** — run `/arcis:strategy backtest post_audit_ruleset_v1 --quick`; verify ⚠ banner appears at FIRST and LAST line of the result block; verify `backtest_results` and `trials_registry` rows land; verify post-execution verify queries return n=1 for both.
8. **Backtest default happy path** — run `/arcis:strategy backtest post_audit_ruleset_v1`; verify 5 `backtest_results` rows land; verify 1 `walkforward_results` row lands with non-null `outcome_state` ∈ {PASS, FAIL, INCONCLUSIVE}; verify `derived_from_backtest_id` is non-null; verify `trials_registry` row lands; verify operator output shows the literal `outcome_state` (NOT boolean).
9. **Walkforward autofire suppression** — after step 8 completes, verify no SECOND walkforward run was auto-fired (no duplicate `walkforward_results` row from autofire); check that `WALKFORWARD_AUTOFIRE_ENABLED=false` was set in the subprocess env (grep the audit log for two consecutive walkforward.* events on the same spec_hash within seconds).
10. **Analyze on walkforward** — run `/arcis:strategy analyze <wf_run_id from step 8>`; verify DSR + PSR computed and printed; verify `outcome_state` preserved verbatim from walkforward_results; verify `analyze_trial_id` row lands in trials_registry; verify N_eff used is the post-backtest N_eff (incremented by 1 from backtest's trial entry, then +1 again by analyze's own trial entry).
11. **Analyze T<30 guard** — author or contrive a result with <30 trades; run analyze; verify the T<30 guard warning prose fires; verify PSR is still surfaced (PSR doesn't require T≥30).
12. **CSCV unavailable** — pick a strategy with exactly 1 prior `backtest_results` row; run analyze on it; verify the CSCV unavailability message ("<2 backtests for this strategy") fires informationally; verify analyze continues to AN5 + AN6 successfully.
13. **CSCV available** — pick a strategy with ≥2 prior backtest_results rows; run analyze; verify CSCV PBO is computed and surfaced.
14. **Status no-drift baseline** — run `/arcis:strategy status` on a clean repo; verify the three drift lists print; verify NO audit event written for status; verify status completes in <30s.
15. **Status surfaces malformed YAML** — temporarily place a malformed YAML file at `src/platform/specs/broken.yaml` (e.g., invalid YAML syntax); run `/arcis:strategy status`; verify `silently_skipped_malformed: [broken]` is surfaced in the ANOMALIES section (no-out-of-scope-deferral discipline).
16. **Status surfaces R8-noncompliant specs** — author a test spec without `derived_from`; run `/arcis:strategy status`; verify `R8-noncompliant specs` list surfaces the test spec.
17. **Status surfaces FS↔DB drift** — manually INSERT a fake row into `strategy_registry` with no matching spec file (e.g., `strategy_id='fake_strategy_v1'`); run `/arcis:strategy status`; verify `db_only` list includes `fake_strategy_v1`. Clean up with DELETE after.
18. **Ideate cold-path** — run `/arcis:strategy ideate "test theme for cold-path verification"`; verify 4 agent dispatches fire (db-investigator + git-historian + research-domain-lead + research-cross-domain-analyst); verify report file lands at `docs/strategy-ideation/<date>-test-theme...md`; verify each section (synthesis / supporting / counter / operational / proposed YAML) is present and non-empty.
19. **Ideate --no-cross-domain** — same theme as 18 but with `--no-cross-domain`; verify only 3 agents dispatch (Wave A only); verify Wave B is skipped in the audit event and operator output.
20. **Audit-trail bracket events** — after running each verb at least once, grep `data/logs/tool-execution.log` for `arcis_strategy.<verb>.started` and `arcis_strategy.<verb>.completed`; verify `session_id` matches the operator-visible RUN_ID/SESSION_ID for each invocation; verify `prompt_hash` and `option_text` present on `arcis_strategy.backtest.confirmed` events.
21. **stdin-driven shell-out (DA3 mirror)** — run `/arcis:strategy ideate "theme with shell-meta $(rm -rf /)"`; verify the theme is treated as a literal string, NOT executed as shell; verify the audit event has the theme value JSON-escaped.
22. **Worktree isolation** — run all of the above inside an agent worktree (not the operator's main checkout); verify all verbs work end-to-end inside the worktree (no env drift assumptions per `feedback_worktree_env_drift`).
23. **Engine→Runner composition harness (FB+DA-revision named pre-PR gate)** — `pytest -xvs tests/skills/strategy/test_engine_runner_compose.py` exits 0. Test invokes the full per-window orchestration against `lazy_prices_v1` + a 2-window `WalkForwardConfig(strategy_id='lazy_prices_v1', windows=[w1, w2])` stub, runs `run_backtest()` IS-slice + OOS-slice → `run_walkforward()` → `persist_run_result()` end-to-end. Asserts ALL of (DA10):
    - (a) `SELECT COUNT(*) FROM backtest_results WHERE strategy_id='lazy_prices_v1' AND provenance_kind='wf_is_window' AND created_at > <test_start>` == **2** (one per IS window of the 2-window config)
    - (b) `SELECT COUNT(*) FROM walkforward_results WHERE strategy_id='lazy_prices_v1' AND created_at > <test_start>` == **1** (autofire suppression verified — DD-16)
    - (c) `derived_from_backtest_id IS NOT NULL` AND points to a row in `backtest_results` with `provenance_kind='wf_is_window'`
    - (d) `SELECT COUNT(*) FROM trials_registry WHERE created_at > <test_start>` == **1**
    - (e) `wf_run_id` captured from `wf_result.run_id` equals `walkforward_results.run_id`
    - (f) ALL `backtest_results` rows have `provenance_kind` set (no NULL) — verifies the CHECK constraint at the schema layer

    Exercises the four FB-revision codebase contracts: `WalkForwardConfig(strategy_id=...)` required-arg instantiation, `window.train_start/train_end/test_start/test_end` field names, `wf_result.run_id` capture (persist_run_result returns None), `cfg.paths.db_canonical` attr-access (not subscript). Plus the DA1 provenance_kind kwarg contract on `persist_backtest_result()`.
24. **DA1 provenance_kind round-trip** — Invoke a fresh `/arcis:strategy backtest post_audit_ruleset_v1 --quick` AND a default `/arcis:strategy backtest lazy_prices_v1` (5-window default). Query: `SELECT provenance_kind, COUNT(*) FROM backtest_results WHERE created_at > <test_start> GROUP BY provenance_kind`. Assert: `(quick_in_sample, 1)` + `(wf_is_window, 5)`. Verify the schema CHECK constraint refuses NULL by attempting a hand-crafted INSERT with `provenance_kind=NULL` → must fail.
25. **DA2 spec_hash snapshot binding** — Start `/arcis:strategy backtest post_audit_ruleset_v1`. At Phase B5 confirm (post-approve), in a separate terminal, append a comment to `src/platform/specs/post_audit_ruleset_v1.yaml` (changes live spec_hash). Re-confirm at B5 with "Yes — run against the snapshot". Verify `arcis_strategy.backtest.completed.spec_hash == arcis_strategy.backtest.confirmed.spec_hash` for the same `RUN_ID`. Verify the snapshot file at `data/logs/spec_snapshots/<RUN_ID>.yaml` matches B1's content (not the post-edit live content).
26. **DA4 mid-run orphan flow** — Manually contrive a runner failure (e.g., temporarily monkey-patch `walkforward_runner.run_walkforward` to raise `RuntimeError` after 2 IS persists). Start `/arcis:strategy backtest lazy_prices_v1`. Verify: (a) `wf_partial` audit event fires with `written_is_rows = [<2 result_ids>]`; (b) operator-facing AskUserQuestion offers Roll back vs Keep; (c) on "Keep" → UPDATE sets `provenance_kind='wf_is_window_orphan_partial_run'` on those 2 rows; (d) subsequent `/arcis:strategy analyze <orphan_result_id>` fires §10.14 REFUSE envelope; (e) `/arcis:strategy status lazy_prices_v1` surfaces the orphans in the Orphans anomaly section.
27. **DA5 multi-session concurrency refuse** — Invoke 2 backtests concurrently (e.g., two terminals firing `/arcis:strategy backtest post_audit_ruleset_v1` within 5s of each other). Verify the second one refuses with §10.12 envelope + `arcis_strategy.backtest.concurrent_refused` audit event. Verify the lock file at `data/locks/strategy/post_audit_ruleset_v1.lock` is released after the first run's B9 completes.
28. **DA6 ideate REQUIRED agent gating** — Simulate `research-domain-lead` timeout (e.g., paused stub or 1-min budget). Invoke `/arcis:strategy ideate "test theme"`. Verify: (a) §10.15 INCOMPLETE envelope fires; (b) `arcis_strategy.ideate.incomplete_no_spine` audit event lands; (c) NO partial synthesis surfaces to operator (no markdown report written). Then simulate db-investigator or git-historian timeout (but research-domain-lead returns) — verify the ⚠ DEGRADED banner appears as line 1 of the operator summary.
29. **DA8 walkforward-redirect** — Take a `wf_is_window` result_id from item 23 step (a). Run `/arcis:strategy analyze <that_result_id>`. Verify the AskUserQuestion fires with "switch to wf_run_id" option (RECOMMENDED). Verify `--as backtest` flag bypasses the redirect (analyzes the IS slice with ⚠ banner). Verify `--as walkforward` short-circuits to "Yes — switch".
30. **DA9 db_path defense-in-depth** — Unset `ARCIS_ALLOW_PROD_PG` (so the orchestrator-entry gate passes). In `arcis_config.yaml`, point `paths.db_canonical` at a `postgresql://localhost:5433/halcyon` DSN (matching `pg.prod_dsn_signatures`). Invoke `/arcis:strategy backtest post_audit_ruleset_v1 --quick`. Verify §10.13 REFUSE envelope fires inside the heredoc + `arcis_strategy.backtest.db_path_blocked` audit event lands. Verify NO row written to backtest_results.

---

## 13. Implementation Discipline

### 13.1 Sibling-search

Per `feedback_review_sibling_search`: when reviewer/dev agent finds an anti-pattern at file:line during implementation, GREP the rest of the file for the same anti-pattern. Specifically for this skill:

- If the `commands/strategy.md` orchestrator has a missing `<<'PY'` single-quote on one heredoc (DA3 risk), grep for ALL heredoc-starts and verify all are single-quoted.
- If one phase forgets to JSON-escape operator-typed strings, grep for ALL `os.environ[` reads in heredocs and verify each is preceded by env-var setting.
- If the engine call in one window misses the `WALKFORWARD_AUTOFIRE_ENABLED=false` env, grep for ALL `run_backtest` / `persist_backtest_result` calls and verify the env is set.
- **DA2 — spec source verification:** every `spec_hash` reference in the spec MUST trace back to the snapshot file at `$SPEC_SNAPSHOT_PATH`, NOT the live spec at `src/platform/specs/<id>.yaml`. Grep for ALL `load_spec(`, `load_spec_from_path(`, and `spec_hash(` invocations; verify each operates on the snapshot inside the B5.5+B7 lock scope.
- **DA1 — provenance_kind required:** grep for ALL `persist_backtest_result(` invocations; verify each passes `provenance_kind=` as a kwarg (one of the three CHECK values). Schema CHECK refuses NULL — if any call site is missed, the INSERT crashes.
- **DA5 — every persist call must be inside the lock:** grep for ALL `persist_backtest_result(`, `persist_run_result(`, `record_trial(` calls in commands/strategy.md; verify each is INSIDE the `with portalocker.Lock(...)` block scope at Phase B5.5.
- **DA9 — every persist call must be after `_validate_db_path_not_prod`:** grep for ALL `persist_*` invocations; verify the db_path inspection runs before the FIRST persist in each heredoc.

### 13.2 Verify-by-mutation

Per `feedback_vacuous_test_pattern` + `feedback_strict_rigor_no_handwave`: every checklist item in §12 must be verifiable by an actual run, not just by reading the code. Implementing PM PROVES each item by:
- Running the command.
- Inspecting the resulting DB rows / log entries / file contents.
- Re-running with a deliberate breaking change (e.g., remove `derived_from` from a spec) to confirm the verification path actually fires.

### 13.3 No out-of-scope deferral

Per `feedback_complete_efforts_no_deferral`: any adjacent defect discovered during implementation (e.g., a stale test, a missing index, a typo in a sibling file) is EITHER fixed in the same PR OR explicitly surfaced in §14 Open Questions with operator decision. NEVER silently deferred to "we'll do it later."

### 13.4 Dual-Opus QA

Per `feedback_use_coding_team_skill`: foundation-class PRs require two independent Opus QA reviewers. Each runs the §12 manual verification checklist + reviews the spec + reviews the implementation against the spec. Both must approve at 100% confidence (per operator standard).

### 13.5 Per-PR versioning

Target v0.36.6X (re-baselined at impl time). Current main: v0.36.65. Implementing PM picks the next version at PR open.

### 13.6 Windows UTF-8 encoding

Per `feedback_windows_utf8_encoding`: any markdown files authored by the skill must be written via Edit tool or with explicit `encoding='utf-8'` flag. JSON round-trips via `json.dumps(...).encode('utf-8')`. Default `open()` is cp1252 on this box.

### 13.7 Worktree isolation

Per `feedback_use_coding_team_skill` + `feedback_worktree_env_drift`: implementing PM dispatches dev agents in worktrees with explicit env propagation (esp. any env vars the skill's tests assume). Tests must pass in both worktree AND post-merge environments.

---

## 14. Open Questions & Design Boundaries

### 14.1 Resolved during design

All operator-confirmed decisions in the brief are LOCKED. Recorded in §13 of design_decisions.json.

### 14.2 Coverage gaps from deep_report (implementing PM verifies)

Per deep_report.coverage_gaps:

1. **`scripts/backtest/run_walkforward.py` — ARCHITECTURE LOCKED (DA14):** Spec specifies INLINE per-window orchestration via heredoc regardless of whether `scripts/backtest/run_walkforward.py` exists at impl time. The script is OUT OF SCOPE for v1 — even if it exists and is usable, the skill does NOT call it (eliminates ambiguity from the formerly-divergent inline-vs-subprocess fork; mainline path is the heredoc in §3 Phase B7 with the snapshot, lock, and provenance_kind contracts).
2. **`src/platform/promotion.py`** — gate logic between `backtested → shadow_trading → production`. Architect did not read. v1 of arcis:strategy does NOT mutate `strategy_promotion_events`. Implementing PM should CONFIRM by grepping the spec implementation for any reference to `strategy_promotion_events` — should be ZERO.
3. **`src/platform/shadow_harness.py`** — referenced from `plugin_registry.py` docstring. Architect did not read. Likely irrelevant for v1; PM CONFIRMS by grep.
4. **`research-team/references/domain-presets/financial-economic.md`** content — Architect did not read. PM MUST read at impl time to confirm fit for trading-strategy ideation. If a different preset fits better (e.g., a hypothetical `quantitative-finance.md`), PM updates Phase I2 DYNAMIC CONTEXT for research-domain-lead.
5. **End-to-end engine→runner composition gate** — PROMOTED in FB-revision to a NAMED pre-PR gate (plan.json Task 8 subgoal). Write `tests/skills/strategy/test_engine_runner_compose.py` that invokes the full per-window orchestration against `lazy_prices_v1` + a 2-window `WalkForwardConfig` stub and asserts a `walkforward_results` row is written with valid `outcome_state` ∈ {PASS, FAIL, INCONCLUSIVE}. Implementation PR MUST NOT open until this test exists and passes. (FB1-FB4 field/signature mismatches confirm the gap; this is the surgical mitigation.)
6. **`research-team/SKILL.md` content** — Architect did not read; PM SHOULD read at impl time to confirm framing the architect should mirror, though `commands/research.md` was read and gives the orchestration pattern.
7. **`_git_sha` helper location** — FIXED IN FB-REVISION: dead import removed from Phase B6 / B7. The BacktestResult already carries `result.reproducibility["code_git_sha"]` (populated by `run_backtest` internally) and the WalkForwardRunResult exposes `wf_result.code_git_sha`. If a SEPARATE skill-layer git SHA is ever needed, shell out: `subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True, cwd=repo_root).stdout.strip()` — do NOT import the private platform-internal helpers (`backtest_engine.py:176` or `walkforward_runner.py:117`).
8. **Full #109 operate spec** — Architect read only the first 927 lines. Sections after may include runbook conventions, references/action-authorization-matrix.md schema details, and Open Questions. PM SHOULD read the rest at impl time to confirm no #109 pattern was missed that arcis:strategy should mirror (notably the runbook convention — but arcis:strategy has no runbook concept, so safe to skip §5 of #109).

### 14.3 Design boundaries deferred per requirements

- Promotion verb (#119 future).
- Lifecycle simulator integration (separate concern).
- Param-sweep verb (architect explicitly notes CSCV is informational in v1; param-sweep is post-v1).
- New strategy specs (out of scope per brief).
- Real-money trading.

### 14.4 Latent coupling to surface

- **`walkforward_runner.py:47` imports `_gate_corpus_or_raise` from `src.evaluation.walkforward`** (FA7). The skill does NOT touch `src/evaluation/` directly, but the runner does, silently. If `src/evaluation/` is ever deleted, the runner breaks and the skill breaks with it. INFORMATIONAL — not a v1 blocker.
- **`scripts/run_backtest.py:83` has stale import** (FA5 — `from src.platform.rigor.walkforward import run_walkforward` — no such module). The skill does NOT call this script; tracked as #118 hotfix. INFORMATIONAL.
- **`scripts/run_backtest.py` does not call `trials.record_trial()`** (FA11 cross-cutting concern) — historical N_eff is undercounted. The skill FILLS the gap by recording trials in both backtest and analyze verbs (DD-5). The historical undercount remains; cleaning up scripts/run_backtest.py to also call record_trial is OUT of scope (could be a separate hotfix).

### 14.5 Critical clarification needed (per FA17 DRIFT)

**DD-13 — Write target path:** The brief says "Write target = local PG via paths.db_canonical". But per FA17:
- `paths.db_canonical` = SQLite at `C:/arcis/data/ai_research_desk.sqlite3` (per arcis_config.yaml:44, "fallback / pre-cutover path")
- `pg.prod_dsn_signatures` (per arcis_config.yaml:137-140) BLOCKS `localhost:5433` / `127.0.0.1:5433` — but the LOCAL PG sidecar runs at exactly that port (5433).
- `pg.test_dsn` = `postgresql://test:test@127.0.0.1:5434/halcyon` (separate test PG at port 5434).

**Three options, implementing PM picks:**
- **Option A — SQLite via `paths.db_canonical`** — matches existing `scripts/run_backtest.py` default which uses `DB_PATH = SQLite`. No schema port needed. No prod_guard tension. Architect RECOMMENDS this for v1.
- **Option B — Test PG via `pg.test_dsn` at port 5434** — separate test DB, no prod-guard tension. Good for CI / reproducibility. Architect's SECONDARY recommendation.
- **Option C — Local PG at 5433 with explicit `@prod_guard` override** — DANGEROUS; matches prod_dsn_signature pattern; would require the skill to disable prod_guard locally, which conflicts with the skill's PROD-PG REFUSE policy. REJECTED.

PM MUST decide A or B at impl time via AskUserQuestion to operator. Spec §3 phase B6 / B7 heredocs reference `paths.db_canonical` as PLACEHOLDER for the operator's choice; PM updates the resolution after the decision.

**DD-14 — ARCIS_ALLOW_PROD_PG semantics:** The brief says "skill refuses if ARCIS_ALLOW_PROD_PG is set" — the brief's policy. Architect implements this as: ANY truthy value blocks. `unset` (env var not present) OR `""` (empty string) = proceed. PM CONFIRMS the truthiness check matches operator intent at impl time.

**DD-15 (DA9) — Post-resolution db_path inspection is REQUIRED defense-in-depth.** PM cannot rely solely on the env-var sentinel (DD-14): an operator could `unset` the sentinel and still have `paths.db_canonical` pointing at a prod-DSN (e.g., via `arcis_config.yaml` drift or a `.env` override). The Phase B5.9 `_validate_db_path_not_prod` check inside the heredoc, immediately before any persist call, refuses any db_path matching `pg.prod_dsn_signatures` from arcis_config.yaml OR a hostname in `PROD_PG_HOSTS_BLACKLIST` env var. The exception is `pg.test_dsn` (port 5434), which IS allowed by an explicit allowlist clause.

### 14.6 Operator-decision questions (surface to operator if uncovered at impl time)

1. **N_eff threshold for "trustworthy" DSR** — Architect picks the standard `DSR > 0.95` threshold. Operator may want a stricter (0.99) or looser (0.90) threshold for their research-desk. Recorded as `references/statistical-rigor.md` constant; PM asks operator at impl time.
2. **Default `--no-cross-domain` behavior** — Architect made cross-domain-analyst OPT-OUT (runs by default). Operator may prefer OPT-IN (`--cross-domain` flag to enable). PM asks at impl time.
3. **Should `backtest --quick` also write `walkforward_results` row with `outcome_state='INCONCLUSIVE'`?** — Currently NO (per §3 phase B6 — quick only writes backtest_results). Alternative: write a placeholder walkforward_results row with outcome_state=INCONCLUSIVE and reason="not_a_walkforward_run" to make `status` output more uniform. Architect REJECTS (would muddy the walkforward_results table semantics). PM CONFIRMS at impl time.
4. **`ideate` agent merge — handle conflicting High-confidence claims?** — If db-investigator says "data is clean" (High) but research-domain-lead's specialist says "data has known gaps" (High), what does the synthesis say? Architect picks: surface BOTH in the supporting/counter respectively; let the operator reconcile. PM CONFIRMS at impl time.
5. **Family-filtered trial variance (FB+DA-revision)** — `get_variance_for_strategy_family(family=...)` accepts `family` but trials.py:97 ignores it (v0.25 TODO; no WHERE family=... clause). Returns GLOBAL trial variance when ≥20 trials exist, else `_VARIANCE_FALLBACK = 0.02/250` (trials.py:33). N_eff via `get_current_n_eff` is family-correct; only the variance fallback is global. **Per DA3, the threshold is LOCKED: global-variance v1 acceptable ONLY while `distinct_strategy_ids ≤ 3` in trials_registry.** AN3 has a programmatic gate — if `SELECT COUNT(DISTINCT strategy_id) FROM trials_registry > 3`, the skill escalates to AskUserQuestion before computing DSR. **OQ5b (follow-up):** when this threshold is crossed in operator practice, file a hotfix task to wire the `family WHERE` clause at trials.py:97 — the AskUserQuestion at AN3 will surface the trigger.
6. **IS→WF provenance linkage (FB-revision)** — `walkforward_results.derived_from_backtest_id` links to only ONE (FIRST) of the 5 IS-window `backtest_results` rows. The other 4 are orphan-but-recoverable via composite `(strategy_id, spec_hash, start_date, end_date)` lookup against `walkforward_results.config_json.windows[*].train_start/train_end`. **Operator decides:** accept first-IS-only-FK as v1 floor OR file follow-up to add a provenance-link table for full N-to-1 traceability. Architect's recommendation: accept v1 (composite lookup is reliable for forensic queries; an explicit link table is a nice-to-have, not a correctness gap).
7. **--quick default window source (FB-revision)** — `--quick` uses hardcoded `2018-01-01` → `2024-12-31` because strategy YAML specs (`src/platform/specs/*.yaml`) carry no `default_backtest_window` key (verified against FA2 / `strategy_spec.py`). **Operator decides:** accept hardcoded canonical v1 window OR file follow-up to add `default_backtest_window: {start, end}` to the strategy YAML schema and backfill existing specs. Architect's recommendation: accept v1 (the 2018-2024 window is the de-facto research-desk standard; YAML override is a v1.x ergonomic improvement, not a v1 blocker).

---

## End of Spec

**Architect note to dual-Opus QA reviewers:**

This spec is dense by design — the four verbs each compose 3-7 phases, the dual-persist orchestration is non-obvious, and the three-state outcome preservation is a load-bearing semantic invariant. Items most worth stress-testing:

1. **Phase B7 per-window loop** — does it correctly handle the case where `is_result.trades` or `oos_result.trades` is empty (no signal in that window)?
2. **Trial-recording dual-write** — does §8.3's recording in BOTH backtest and analyze produce double-counting that distorts DSR's N_eff downstream?
3. **Spec-hash re-capture (B5)** — is the "spec_hash changed between B4 and B5" recovery path actually useful, or operator nuisance? Reviewer judgment.
4. **R8 preflight skip on --quick** — is it safe to skip R8 entirely on the in-sample path, or should we still validate spec structure (without the overlap check)?
5. **Analyze AN1 UUID collision** — is the surface-as-anomaly response correct, or should we hard-error?
6. **`silently_skipped_malformed` surface in status** — does §14.2's verification path (manually placing a broken YAML) actually exercise the FA2:line-392 silent-skip behavior?
