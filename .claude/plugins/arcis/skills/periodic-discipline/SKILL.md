---
name: periodic-discipline
description: Cron-triggered + on-demand hygiene audits — skill drift, memory curation, tool boundary verification. Composes existing tools and agents; produces JSON findings. Use when the operator asks to run discipline audits, check skill/memory/tool hygiene, or investigate drift in the plugin infrastructure.
---

# Periodic Discipline

## NO OUT-OF-SCOPE DEFERRAL

Within any audit verb, you must surface ALL discovered findings to the operator. If `audit-skills` finds 7 drift issues, the report lists all 7 — never "we'll investigate the others later." The operator decides what to act on now vs. queue. You do not silently defer.

This is the operator's explicit standard (memory: `feedback_complete_efforts_no_deferral`). Honor it verbatim in every verb, every scanner, every postamble.

---

## Overview

This skill is the **watchdog of the watchdogs** — a scheduled hygiene layer that runs three discipline audits on a cron cadence and on operator demand. It detects drift between the living plugin infrastructure (skills, memory, tool boundaries) and the structural invariants the project depends on, surfaces findings as JSON reports, and exempts conscious deviations via an opt-in allowlist.

Where `arcis:operate` is **reactive** (incident response when something breaks), this skill is **proactive** — catch infrastructure drift before it bites. Typical targets: a skill referencing an agent that was renamed, a decorator stripped from a tool CLI, a memory note that contradicts newer established fact.

This skill is **markdown-only**. All scanner logic is implemented as fenced bash + `python -c` / `jq` one-liner blocks inside `audits/<verb>.md`, composing existing tools and agents. No new Python tooling.

---

## Verb Routing

| Verb | What it does | Local eligible | CI eligible |
|------|-------------|---------------|------------|
| `audit-skills` | Detect drift in skill/command files: broken file:line refs, dead agent names, missing tool modules, CI/runbook parity, LLM contradictions | Yes | Yes (Mon 07:00 UTC) |
| `curate-memory` | Detect operator-memory hygiene issues: duplicate root_cause_keys, stale entries (>90d untouched), LLM contradictions | Yes | No (memory tree is local) |
| `test-tools` | Verify tool boundary contracts: CLI decorator chain completeness, boundary test coverage | Yes | Yes (Thu 07:00 UTC) |
| `full` | Run all three verbs sequentially in order: audit-skills → curate-memory → test-tools | Yes | No (curate-memory refuses in CI) |

**Argument parsing:** Extract the verb from POSITIONAL_INPUT[0]. If absent or unrecognized, invoke `AskUserQuestion` with options `["audit-skills", "curate-memory", "test-tools", "full"]`.

**Dispatch:** Route to `audits/<verb>.md`. Each runbook is self-contained with its own preamble (lockfile + invocation_id), scanner sequence, and postamble (dedup + allowlist filter + rotation).

**CI detection for curate-memory:** check `GITHUB_ACTIONS` env var. If set and verb is `curate-memory` (or `full`), print `"curate-memory requires local memory tree — refused in CI"` and exit 1 cleanly.

---

## Composition Table

### Tools (13 existing — composed, not re-implemented)

| Tool module | Used by |
|------------|---------|
| `src.tools.docconsistency` | `audit-skills` → `file_line_drift` scanner (composed in v1) |
| `src.tools._execution_log` | `test-tools` → `cli_decorator_chain` scanner (log reader; composed in v1) |
| `src.tools.capabilityregistry` | available; not used in v1 scanners |
| `src.tools.ciinvestigate` | available; not used in v1 scanners |
| `src.tools.contractcheck` | available; not used in v1 scanners |
| `src.tools.dbquery` | available; not used in v1 scanners |
| `src.tools.gitarchaeology` | available; not used in v1 scanners |
| `src.tools.healthprobe` | available; not used in v1 scanners |
| `src.tools.logtail` | available; not used in v1 scanners |
| `src.tools.prcomments` | available; not used in v1 scanners |
| `src.tools.processmanager` | available; not used in v1 scanners |
| `src.tools.symbolfind` | available; not used in v1 scanners |
| `src.tools.testpatternscan` | available; not used in v1 scanners |
| `src.tools.tradingstate` | available; not used in v1 scanners |

### Agents (4 existing — dispatched for LLM-derived findings)

| Agent name (`subagent_type`) | Dispatched by |
|------------------------------|--------------|
| `research-cross-domain-analyst` | `audit-skills` → `llm_contradiction` scanner; `curate-memory` → `memory_contradiction` scanner |
| `coding-qa-reviewer` | available; not dispatched in v1 |
| `coding-rigor-reviewer` | available; not dispatched in v1 |
| `db-investigator` | available; not dispatched in v1 |

---

## Self-Exclusion Contract

All scanners apply a path-glob filter excluding `.claude/plugins/arcis/skills/periodic-discipline/**`. The skill does not audit itself. Findings about its own files are out of scope by design — the allowlist is the recovery surface if a false-positive slips through.

See `references/scanners.md` for the per-scanner path filter implementation.

---

## Audit-Log Bracket Contract

Every verb write a skill-level event to `data/logs/tool-execution.log` at the START (preamble) and END (postamble) of the run, using `ARCIS_SESSION_ID=$INVOCATION_ID`. This brackets the run's tool events for per-invocation filtering:

```bash
jq 'select(.session_id == env.INVOCATION_ID)' data/logs/tool-execution.log
```

Tool subprocess events land in the log automatically via the decorator stack. The skill-layer bracket events are written manually via `python -m src.tools._execution_log`.

See `references/lockfile.md` for the full invocation_id format and ARCIS_SESSION_ID propagation contract.

---

## Finding Schema Summary

Each finding is a JSON record with:
- `invocation_id` — ties finding to its log slice
- `verb` — which audit produced it
- `scanner` — which scanner produced it
- `root_cause_key` — dedup primary key (e.g., `agent:research-specialist`, `docconsistency:CLAUDE.md:42`)
- `severity` — `critical` | `major` | `minor` | `info`
- `first_seen_utc` — ISO 8601 timestamp
- `advisory` — `true` for LLM-derived findings (CI ignores for status transitions)
- `payload` — scanner-specific detail

See `references/findings-schema.md` for the full schema, dedup contract, allowlist semantics, and severity rubric.

---

## Out of Scope

- **No auto-fix.** Findings are advisory — the operator triages and opens PRs. This skill never modifies the files it audits.
- **No new tools.** All scanner logic composes existing infrastructure via fenced bash + python-c / jq one-liners.
- **No schema changes.** The `tool-execution.log` format, agent frontmatter structure, and skill file layout are read-only inputs.
- **No cross-plugin auditing.** Only `.claude/plugins/arcis/**` is in scope. halcyon-audit, deep-research, and other sibling plugins are excluded.
- **No Slack/Telegram/email notifications.** Findings surface as JSON report files and `$GITHUB_STEP_SUMMARY`; operator triages at their cadence.
- **No severity escalation.** Findings do not auto-escalate or auto-page; they persist until allowlisted or fixed.
