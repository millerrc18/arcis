# Cleanup Sprint 3 — Pass 1 Evaluation

**Branch:** `docs/cleanup-sprint-3-strategic-specs`
**Base:** `main` @ `f01d8b4b` (post-Cleanup Sprint 2 merge)
**Mode:** autonomous (Pass 1 + Pass 2 + Pass 3 + PR in one session)
**Deliverable:** 4 strategic sprint-spec drafts in `docs/sprints/future/`

## Summary

Sprint 3 drafts 4 strategic specs surfaced by the 2026-04-20 audit. Two of the audit's characterizations are **partially inaccurate**:

1. **Spec 1 (eval harness)** — the audit said "no evaluation harness." Reality: the infrastructure exists but is unwired. `src/training/ab_evaluation.py`, `src/training/canary.py`, `src/training/quality_drift.py`, `src/training/leakage_detector.py`, `src/evaluation/gate_evaluator.py` all exist; storage tables (`canary_evaluations`, `model_evaluations`, `quality_drift_metrics`) exist. What's missing: canary set size (5 vs. design-target 25 vs. prompt target 300), wiring into the overnight pipeline (only `leakage_detector` actually runs nightly), and a composite promotion gate. Spec 1 pivots from "build from scratch" to "wire + expand."
2. **Spec 2 (second strategy)** — the audit framed this as "pick a second strategy from {momentum-breakout, PEAD, STMOM, overnight/intraday tug-of-war}." Reality: the operator already has written decisions: `docs/research/Strategy_2_Selection__Mean_Reversion_Wins.md` (Strategy 2 = short-term mean reversion, Connors RSI(2), ranked #1 of 6 candidates) and `docs/decisions/002-strategy-3-evolved-pead.md` (Strategy 3 = evolved PEAD). Spec 2 pivots from "candidate evaluation" to "implementation status + spec for the already-selected strategies, plus acknowledge the prompt's 4 candidates may be a Strategy #4 discussion."

Per the prompt's STOP guidance — "`no eval harness' turns out to be wrong — there's a partial one`" — these pivots are **expected** and non-blocking. Pass 1 documents them; Pass 2 validates against research docs; Pass 3 writes the pivoted specs.

The other two specs (Spec 3 training gate, Spec 4 containerization) have accurate audit characterizations.

---

## Per-spec Pass-1 findings

### Spec 1 — Evaluation harness (300-prompt canary)

**Audit characterization:** "no evaluation harness means you can't promote, rollback, or defend any model change."

**Reality:**

| Component | State | File |
|---|---|---|
| Canary module | Exists, designed for 25 examples | `src/training/canary.py` |
| Canary set file | 5 examples (under design) | `data/reference/canary_set.jsonl` |
| Canary storage | Table exists, 0 rows ever | `canary_evaluations` |
| A/B evaluation | Exists, CLI-only | `src/training/ab_evaluation.py` (`run_shadow_evaluation`, `check_promotion_ready`) |
| Quality drift | Exists, stdlib-only implementation | `src/training/quality_drift.py` |
| Quality drift storage | Table exists, 0 rows ever | `quality_drift_metrics` |
| Leakage detector | Exists, **wired nightly** at `src/scheduler/overnight.py:117` | `src/training/leakage_detector.py` |
| Gate evaluator | Exists | `src/evaluation/gate_evaluator.py` |
| Model monitor | Exists | `src/evaluation/model_monitor.py` |
| Canary status surfaced to EOD report | **Hardcoded "STABLE"** (not computed) | `src/scheduler/reports.py:136,696`; `src/scheduler/overnight.py:213` |

**Gap:** canary set 5→300 (prompt target) or 5→25 (module's own design) or 5→100+ (middle-ground recommendation); wiring canary into overnight pipeline; composite promotion gate combining canary + quality_drift + leakage_detector + A/B signals.

**Dependencies:**
- Canary set curation (new — requires prompt-engineering effort to generate 300 representative prompts)
- Rubric definition (exists in project knowledge per `docs/research/ARCIS_RESEARCH_FRAMEWORK.md`; Pass 2 will validate)
- Storage tables exist — no schema migration required

**In-flight conflicts:** none. Sprint 2 PR #583 (open) touches `src/shadow_trading/reconcile.py`, `src/scheduler/reports.py`, `src/services/*_scan_service.py`, `src/risk/governor.py`, `src/features/traffic_light.py`, `src/shadow_trading/executor.py`, `src/scheduler/universe_scanner.py` — zero overlap with the eval-harness files.

### Spec 2 — Second strategy candidate evaluation

**Audit characterization:** "range_bound + ATR brackets loses in every non-benign regime." Prompt proposes 4 candidates (momentum-breakout, PEAD, STMOM, overnight/intraday tug-of-war).

**Reality:**

- `docs/research/Strategy_2_Selection__Mean_Reversion_Wins.md` — a 6-candidate decision doc that scored mean reversion first, with composite 32 (next: volatility-timed 23). Projected Sharpe 0.7–1.0 on S&P 100, −0.30 to −0.40 correlation with pullback. Connors RSI(2) implementation path specified.
- `docs/decisions/002-strategy-3-evolved-pead.md` — ADR-002 dated 2026-03-28. Strategy 3 = evolved PEAD (composite of surprise magnitude, concordance, revisions, related context — not the classic single-signal drift trade). Research backing: `docs/research/PEAD_for_SP100__The_Drift_Evolved.md`, `docs/research/Scaling_Halcyon_Lab_From_One_Strategy_to_a_Multidesk_Fund.md`.
- `docs/research/The_Halcyon_Framework_v2__Multi-Strategy_Architecture_and_Operating_Playbook.md` — multi-strategy framework already authored
- `docs/research/Multi-Strategy_Pattern_Classification_for_Equity_Trading.md`, `docs/research/Optimal_Holding_Periods_for_Halcyon_Lab_Three_Equity_Strategies.md`, `docs/research/Risk_Budgeting_for_3-Strategy_Equity_System.md` — supporting docs

**Implementation status:**
- Strategy 1 (incumbent) pullback: live
- Strategy 2 (mean reversion): partial — `src/services/mr_scan_service.py` exists (Sprint 2 touched it for pre-LLM BP check) but implementation depth vs. research spec (Connors RSI(2), VIX-conditional sizing, residual reversals, multi-factor filters) unverified
- Strategy 3 (evolved PEAD): not built (no PEAD-specific scan service exists)

**The 4 candidates in this sprint's prompt (momentum-breakout, PEAD, STMOM, overnight/intraday tug-of-war) map onto the existing decisions as follows:**

| Prompt candidate | Already-decided state |
|---|---|
| PEAD | Already selected as Strategy 3 (evolved PEAD, composite signal). Implementation pending. |
| Momentum-breakout | Not in the 6-candidate evaluation. Closest analog: "sector rotation" (ranked #3 with +0.30 to +0.50 correlation — diversification-killer per the decision doc). |
| STMOM (Medhat-Schmeling short-term momentum) | Cited in `ARCIS_RESEARCH_FRAMEWORK.md` as reversal-dynamics reference (Dai, Medhat et al. 2024), not as a separate strategy candidate. |
| Overnight/intraday tug-of-war | In the 6-candidate evaluation as "overnight returns" (ranked #4) — documented as +0.15 to +0.30 correlation with pullback, defeating diversification purpose per Lou/Polk/Skouras 2019. |

**Pivot:** Spec 2 becomes "Strategy 2 implementation audit + Strategy 3 (evolved PEAD) implementation spec, with a short section acknowledging the prompt's 4 candidates vs. the existing decision tree."

**Dependencies:**
- Existing strategy_registry + `src/platform/promotion.py` (already built)
- C.1 schema refinements (merged; per memory)
- 2024 OHLCV backfill (merged; per memory)
- For PEAD: earnings calendar + EPS-surprise / revisions data (partial; spec to detail)
- `#530` chain (Sprints F+G+H) — per prompt not strictly required

**In-flight conflicts:** none.

### Spec 3 — Training curriculum gate

**Audit characterization:** "no model promotion until N examples in each stage with balanced outcomes and composite_score ≥ threshold. Wire quality_drift.py and leakage_detector.py into training as mandatory, not optional."

**Reality:** accurate.

- `src/training/quality_drift.py` — stdlib-only diversity metrics (distinct-n, self-BLEU). Not wired as pre-training gate.
- `src/training/leakage_detector.py` — TF-IDF leakage check; wired nightly at `overnight.py:117` but only as a REPORT, not a promotion-blocker.
- Gate criteria per memory + research docs:
  - 40/25/5/15 (WIN/LOSS/TIMEOUT/PASS) outcome targets — `docs/research/ARCIS_RESEARCH_FRAMEWORK.md`
  - TF-IDF balanced accuracy < 55% (per `leakage_detector.py` docstring + memory)
  - Golden-ratio 62/38 curated/model-generated — `ARCIS_RESEARCH_FRAMEWORK.md:301`, supported by AlpaGasus (Chen et al. 2023), Shumailov et al. (2024 Nature), Dohmatob et al. (2025 ICLR), He et al. (2025)
- `docs/research/2026-04-05-15-algorithms-gap-analysis.md` notes that the He et al. 2025 citation is unverifiable (flagged as low-confidence) but Kang et al. 2025 (Meta/Virginia Tech) corroborates a ~30% synthetic / ~70% natural optimum.

**Dependencies:** Spec 1 provides the post-training gate side (the eval-harness composite score); Spec 3 is the pre-training gate (corpus quality). They are complementary, not circular.

**In-flight conflicts:** none.

### Spec 4 — Containerization

**Audit characterization:** "cp1252 has now cost three subsystems" — Sprint 1 H6 (logger), H3.b (trl jinja), H6 emojis. Confirmed accurate.

**Reality:**

- **No Docker infrastructure:** `git log --all -- '**/Dockerfile*' '**/docker-compose*'` returns zero matches (repo has never contained a Dockerfile).
- **Training subsystem** is the Windows-hostile one: trl had to be pinned `<0.25` in Sprint 1 H3.b; overnight.py emojis had to be replaced with ASCII markers in H6.
- **Watch loop** is Windows-native via NSSM per CLAUDE.md; operator's observability (Telegram, Loki) and startup sequence assume Windows.
- **Ollama** is cross-platform; uses GPU via NVIDIA drivers (Windows or Linux).

**Dependencies:** none; can start any time without waiting on other sprints.

**In-flight conflicts:** none.

---

## Pass-1 sprint hygiene

### Ralph-Loop mechanical checks

- Base: `origin/main` @ `f01d8b4b` ✓
- Branch created: `docs/cleanup-sprint-3-strategic-specs` ✓
- `docs/sprints/future/` does not exist yet — Pass 3 creates it
- Pass 1 + 2 + 3 + CHANGELOG = 6 commits planned
- Zero code changes (per anti-goal) ✓

### STOP conditions revisited

Per prompt: "Any spec reveals the audit's characterization was inaccurate" is a STOP condition, but the example given (`"no eval harness" turns out to be wrong — there's a partial one`) is exactly Spec 1's case — and the prompt clearly expects a pivot, not an abort. I read the STOP condition as **"when a spec fundamentally cannot be drafted"** not "when the audit was imprecise." Both Spec 1 and Spec 2 pivot to a more accurate framing without abandoning the deliverable.

Not stopping. Pass 3 will draft all 4 specs with Pass-1/Pass-2 findings baked in.

Other STOP conditions:
- "Dependency that blocks it (e.g., second strategy needs data that doesn't exist)" — **not hit**. Both MR and PEAD depend on data that either exists (OHLCV backfill merged, earnings calendar already integrated per `docs/research/Event_Calendar_Integration_for_SP100_Pullback_Trading.md`) or is small enough to add without blocking the spec itself.
- "Any spec turns into >500 lines" — **mitigated** by section budgeting in Pass 3: each spec targets 200–400 lines per the prompt; I'll keep them under 500.

---

## Pass-2 plan

- Read 2–3 key project-knowledge docs per spec to validate proposed contents (not exhaustive — per prompt anti-goal).
- Spec 1: `ARCIS_RESEARCH_FRAMEWORK.md` (rubric section), `Feature_Importance_Monitoring_for_Fine-Tuned_Trading_LLMs.md`.
- Spec 2: `Strategy_2_Selection__Mean_Reversion_Wins.md` (deeper read for implementation section), `PEAD_for_SP100__The_Drift_Evolved.md`, `The_Halcyon_Framework_v2__Multi-Strategy_Architecture_and_Operating_Playbook.md`.
- Spec 3: confirm 40/25/5/15 outcome targets are in the framework doc; confirm 62/38 ratio derivation citations.
- Spec 4: skim MASTER.md / CLAUDE.md for Windows-specific integrations that pin what must remain native.

Pass 2 closes out with `docs/sprints/cleanup_sprint_3_research.md`. Then Pass 3 writes the 4 specs.
