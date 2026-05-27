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
- Invoking `scripts/run_backtest.py` directly (broken `--with-walkforward` import per FA5 / tracked as #118; the skill invokes `run_backtest()` + `run_walkforward()` via Python directly).
- Invoking `src/platform/rigor/walkforward.py:run_walkforward` (non-rigor path; #118 cleanup will reconcile namespace).
- Real-money trading.
- Writing to prod PG.
- Collapsing the three-state outcome to a boolean.
