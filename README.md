# Arcis

## What this is

A personal research project testing whether a long-only pullback strategy on the point-in-time S&P 500 has an edge worth trading. Not a product, not advice, no capital at risk today.

## Status

Current step: SCOPE.md §5 **Step 1** — the forward news recorder (sprint S01, branch `feat/s01-news-recorder`).

What exists: the binding charter (SCOPE.md v1.0, tagged `charter-v1`), the research preregistration (draft v0.7), the research log (entries R01–R12), and the S01 news recorder — built 2026-10-02 (105 tests, 94% coverage, live smoke passed; PR pending).

What deliberately does not exist yet: the data plane beyond news, no ranker, no simulator, no live lane. Per the charter, nothing is built before its step.

### Roadmap

The gates are SCOPE.md §5's "done means" and PREREGISTRATION.md; this table adds dates and does not restate them. **Forecast** dates move with the work. **Clock** dates are fixed by the preregistration once their anchor exists, and nothing built can bring them forward. **Count** dates depend on closed trades and are the earliest possible.

| Milestone | Needs | Date | Kind | If it fails |
|---|---|---|---|---|
| Step 0 · `charter-v1` | — | 2026-09-27 | done | — |
| S01 T1 · news-access preflight | Paper API keys | 2026-10-02 | done | — |
| S01 T2–T10 · recorder built | — | 2026-10-02 | done | — |
| Step 1 · recorder, 7 clean days | S01 merged | 2026-10-03 | done | Recorder live; 15-min poll, hourly heartbeat |
| Step 2 · S02 report, `incumbent_v1` frozen | — | 2026-10-04 | done | Frozen `524dd858…` (`tools/verify_incumbent_freeze.py`) |
| Step 2m · S03 power figures | S01 merged, S02 T4 | 2026-10-04 | done | 24-mo §2.1 MDE 18.3 bp at 5% planning rate (< 25 bp); §3.2 MDE 2.0 bp — prereg-v1 clear (S03) |
| **Step 2t · `prereg-v1`; the Q1 clock starts** | Steps 2 and 2m | **2026-10-04** | done | Q1/Q2/Q3 clocks running |
| Step 3 · data plane (S04) | `prereg-v1` | 2026-10-05 | done | Partial: T2/T4/T7 UNRESOLVED (see `docs/research/data-plane-audit.md`) |
| Step 4 · ranker, cost model, metrics | Step 3 | — | next | — |
| Step P · paper lane | Step 4 | — | forecast | — |
| Step 5 · simulator, ledger, harness, registry | Step 4 | — | forecast | — |
| Implementation freeze (PREREGISTRATION.md §0 rule 4) | Steps 3–5, and `textscore` for Q2/Q3 | before Oct 2027 | deadline | No look can be evaluated without it |
| §2.4 historical check, run once | Step 5 | Q3–Q4 2027 | forecast | Net alpha ≤ 0 retires the incumbent |
| Q1 12-month look | The freeze | Oct 2027 | clock | `b_Q` ≤ 0 fails Q1; it may also stop for futility |
| **Q1 24-month look: the gating decision** | The 12-month look | **Oct 2028** | clock | No capital |
| Q2/Q3 12-month look | The freeze; OD-3 | Oct 2027 | clock | It may stop for futility (nonbinding) |
| Q2/Q3 24-month look: efficacy | The 12-month look | Oct 2028 | clock | PREREGISTRATION.md §3.4 |
| $2,000 live canary to 60 closed trades | A Q1 pass, paper plumbing holding, OD-1, OD-2, OD-8 | Dec 2028 → Dec 2029 at the earliest | count | No $5,000 stage; the kill rule runs from its first trade |
| $5,000 first real-money stage | The canary's fill-quality pass | Jan 2030 at the earliest | count | Kill rule: a 25% drawdown, or the edge bound below zero after 150 trades |
| Doublings to the $40,000 cap | 150 more closed trades each, estimate ≥ 25 bp | 2032 at the earliest | count | No doubling |

**Critical path:** S01 and S02, then S03, then `prereg-v1`, then 24 months, then the Q1 decision, the canary, and $5,000.

**Upkeep:** when a step closes or a look is evaluated, its row gets the actual date, and the forecast rows after it are re-dated in the same commit.

## Documentation map

| Document | Question it answers | When to read it |
|---|---|---|
| SCOPE.md | What is in scope, what each component must do, and what was decided | Before proposing or building anything |
| PREREGISTRATION.md | What counts as evidence and what decides each research question | Before running or interpreting any test |
| docs/research/research-log.md | What outside evidence the choices rest on | When questioning a decision's basis |
| docs/research/2026-09-27-rq-12-quoted-values-verification.md | Saved report: verification of quoted paper values (RQ-12) | When citing RQ-12 |
| docs/research/RESEARCH-QUESTIONS.md | What is still open and what would answer it | When picking up a research thread |
| docs/research/old-platform-inventory.md | What the old platform did, what is worth carrying forward, and what is unresolved (S02) | When porting specs or freezing the incumbent |
| docs/research/power-measurement.md | Measured power for the preregistered tests: MDEs, second moments, and biases (S03) | When citing §2.1/§3.2 power figures |
| docs/research/data-plane-audit.md | Data plane audit: coverage, adjustments, availability, survivorship (S04, partial — T2/T4/T7 UNRESOLVED) | When citing panel coverage or survivorship |
| docs/research/trial-ledger.csv | Every configuration the old platform evaluated against returns (S02 T5) | When auditing trial counts or Deflated Sharpe |
| config/incumbent_v1.yaml | The frozen incumbent strategy definition (currently UNRESOLVED, S02 T2) | Before any backtest or forward test |
| docs/sprints/ | What the current unit of work is | When doing the work |
| docs/runbooks/ | How to operate what is running | When running or monitoring the system |
| docs/reference-architecture.md | What good looks like | When designing a component |
| CLAUDE.md | What rules every agent session follows | Before touching anything (agents) |
| .github/pull_request_template.md | The merge checklist every PR must pass | When opening a PR |
| CHANGELOG.md | What changed | When catching up |

## Quickstart

```sh
uv sync
uv run python tools/checks.py   # ruff, mypy, ledger/size/hygiene checks, pytest
# configure the recorder (see docs/runbooks/news-recorder.md), then:
uv run arcis-recorder universe
uv run arcis-recorder poll
uv run arcis-recorder verify
```

## Where the data lives

Outside the repository and outside any cloud-sync folder, under the configured data root. Both matter: the repository is public, and a SQLite database once kept in a OneDrive folder caused a full data loss (SCOPE.md I-7). The recorder refuses to start if the data root is inside the repo or a sync folder.

## What this repository never contains

Credentials, market data, news article text, personal records, or large binaries (SCOPE.md I-13, I-16). The repository is public for review; nothing private is ever committed to it.

## How decisions get made

SCOPE.md §6: nothing is built without a ledger row, and every proposal names the gate it moves. A proposal that moves no gate is recorded in §10 and not built. The owner decides; agents propose.

## Disclaimer and rights

Personal research. Not investment advice. No warranty. All rights reserved: no license is granted, and this repository is public for review only (SCOPE.md D-014, D-016).
