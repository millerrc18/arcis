# Training Curriculum Gate — Future-Sprint Spec

**Status:** draft spec (Cleanup Sprint 3 — not yet implemented)
**Author context:** 2026-04-20 audit strategic item #3
**Source docs:** `docs/sprints/cleanup_sprint_3_evaluation.md` §Spec-3, `docs/sprints/cleanup_sprint_3_research.md` §Spec-3, `docs/research/ARCIS_RESEARCH_FRAMEWORK.md`, `docs/research/Build_Score_Specification__Composite_KPI.md`, `docs/research/2026-04-05-15-algorithms-gap-analysis.md`

## 0. TL;DR

Wire `quality_drift.py` and `leakage_detector.py` as **mandatory
pre-training gates** instead of optional reports. Block a training run
if the corpus fails corpus-quality criteria (outcome mix, curated/
generated ratio, leakage, diversity). Pair with the Spec-1
evaluation harness which gates **post**-training promotion. Together:
pre-train corpus gate + post-train rubric gate = the "no model
promotion until the data and the model both pass" discipline
the 2026-04-20 audit asked for.

## 1. Why this spec exists

2026-04-20 audit: "83% structure, 17% evidence, 0% reasoning/rubric.
76 of 1,782 training examples quarantined. composite_score +
temporal_honesty + evidence_integration columns exist but ALL NULL."
Plus: no model promotion until N examples in each stage with balanced
outcomes and composite_score ≥ threshold.

**Root cause:** `quality_drift.py` and `leakage_detector.py` exist
and produce metrics, but neither blocks a training run. Today's
pipeline will happily fine-tune on a corpus that fails every single
quality metric. The audit correctly identified this as "quality gates
as reports, not gates."

**Goal:** `src/training/trainer.py` (or successor) refuses to start a
training run if the corpus fails any pre-training gate. Post-training,
Spec-1's eval harness refuses to promote the resulting model if it
fails the rubric + canary + A/B gates.

## 2. What already exists (Pass-1 inventory)

| Tool | Purpose | State |
|---|---|---|
| `src/training/quality_drift.py` | Diversity metrics (distinct-n, self-BLEU) | Exists; called from `canary.py` only; writes to `quality_drift_metrics` (0 rows ever) |
| `src/training/leakage_detector.py` | TF-IDF balanced-accuracy outcome-leakage check | Exists; **wired nightly** at `src/scheduler/overnight.py:117`; runs as report, not gate |
| `src/training/trainer.py` | Fine-tuning entry point | Exists; no corpus pre-check |
| `training_examples` table | Stores training corpus | Exists; 76/1,782 quarantined; `composite_score` + rubric columns all NULL |
| Schema registry | `quality_drift_metrics`, `canary_evaluations`, `model_evaluations` | Exist; zero rows ever |

## 3. Gate criteria

### 3.1 Pre-training gate (runs before a training job starts)

A corpus passes **all** of the following to start a training run:

| Criterion | Target | Tolerance | Source of truth |
|---|---|---|---|
| **Outcome mix: WIN** | 40% | ±5 pp | `training_examples.outcome` |
| **Outcome mix: LOSS** | 25% | ±5 pp | same |
| **Outcome mix: TIMEOUT** | 5% | ±3 pp | same |
| **Outcome mix: PASS** | 15% | ±5 pp | same |
| **Curated/generated ratio** | 62 / 38 | ±5 pp | `training_examples.source` |
| **Leakage detector balanced accuracy** | < 55% | hard threshold | `leakage_detector.check_outcome_leakage` |
| **Quality drift distinct-2 vs prior corpus** | drop ≤ 10% | hard threshold | `quality_drift.compute_all_metrics` |
| **Quality drift self-BLEU vs prior corpus** | rise ≤ 15% | hard threshold | same |
| **Minimum total size** | 1,500 examples (post-quarantine) | hard floor | `COUNT(*) WHERE quarantined=0` |
| **Per-stage minimum count** | WIN ≥ 600, LOSS ≥ 375, TIMEOUT ≥ 75, PASS ≥ 225 | hard floor (post-quarantine) | stage × outcome tallies |

Outcome-mix targets come from `docs/research/Build_Score_Specification__Composite_KPI.md:88` and `deep-research/red-team-interview.md:60` (v2 dataset target: 40% WIN, 25% LOSS, 5% TIMEOUT, 15% PASS, plus 400 DPO pairs and 75 anchors).

Curated/generated ratio comes from `ARCIS_RESEARCH_FRAMEWORK.md:301` (AlpaGasus — Chen et al. 2023). Kang et al. 2025 (Meta / Virginia Tech) corroborates a ~30 / 70 synthetic/natural optimum; 38% synthetic is slightly above but within the right range. The He et al. 2025 citation in the framework is **unverifiable** per `2026-04-05-15-algorithms-gap-analysis.md:268` — documented as low confidence but not invalidating.

Leakage threshold: TF-IDF balanced accuracy < 55% gives 5 percentage points of tolerance above the 50% random baseline. Balanced accuracy accounts for class imbalance. The 2–3× sensitivity upgrade to embedding-based leakage detection is flagged as **highest priority** in `docs/research/15_Algorithm_Gap_Assessment.md` but is out of scope for this gate spec.

### 3.2 Post-training gate (delegates to Spec 1)

The resulting model must pass Spec 1's harness:

| Criterion | Source |
|---|---|
| Rubric composite ≥ 65 | Spec 1 §3.2 |
| Canary perplexity rise < 5% vs incumbent | existing `canary.py` threshold |
| No failed jailbreak canary | Spec 1 §3.1 |
| A/B ≥ 50% tie-or-win rate vs incumbent | Spec 1 §3.3 |
| Quality drift ≤ 10% distinct-2 drop + ≤ 15% self-BLEU rise | `quality_drift.py` (same thresholds as pre-training) |
| Leakage TF-IDF < 55% on model outputs | `leakage_detector.py` (model-output leakage, post-hoc) |

Spec 3 provides the pre-training gate; Spec 1 provides the
post-training gate. Neither circularly depends on the other.

## 4. Integration design

### 4.1 New module — `src/training/corpus_gate.py`

Module-level entry: `check_corpus_gate(db_path) -> CorpusGateResult`.

```
@dataclass
class CorpusGateResult:
    passed: bool
    total_examples: int
    quarantined_count: int
    outcome_mix: dict[str, float]   # {"WIN": 0.41, "LOSS": 0.26, ...}
    curated_ratio: float            # 0.62 target
    leakage_balanced_accuracy: float
    quality_drift: dict[str, float] # {"distinct_2_drop": 0.03, "self_bleu_rise": 0.08}
    failing_criteria: list[str]     # human-readable reasons if not passed
    recommendation: str             # "proceed" / "block" / "block_and_alert"
```

Called by `trainer.py` entry point before any torch / transformers
imports; if `not result.passed`, emit Telegram alert +
`logger.critical` + exit non-zero. Run result written to new
`corpus_gate_results` table (schema proposal below).

### 4.2 Integration with existing overnight pipeline

Existing: `src/scheduler/overnight.py:117` runs `run_leakage_check`
nightly as a report. This spec re-uses the same call path but
**gates** the subsequent training job on it. Pseudocode:

```python
def run_overnight_training(config):
    from src.training.corpus_gate import check_corpus_gate
    gate = check_corpus_gate(DB_PATH)
    if not gate.passed:
        logger.critical(
            "[CORPUS-GATE] Training blocked: %s",
            ", ".join(gate.failing_criteria),
        )
        _telegram_alert_training_blocked(gate)
        return {"status": "gated", "gate": gate}
    # proceed to fine-tune
    return run_fine_tune(config, corpus_gate=gate)
```

### 4.3 Schema additions (additive)

New table via `src/schema/registry.py`:

```sql
CREATE TABLE corpus_gate_results (
    gate_id TEXT NOT NULL PRIMARY KEY,
    created_at TEXT NOT NULL,                -- UTC ISO
    db_path TEXT NOT NULL,                    -- which DB this gated
    total_examples INTEGER NOT NULL,
    quarantined_count INTEGER NOT NULL,
    outcome_mix_json TEXT NOT NULL,           -- JSON
    curated_ratio REAL NOT NULL,
    leakage_balanced_accuracy REAL,
    distinct_2_drop REAL,
    self_bleu_rise REAL,
    gate_passed INTEGER NOT NULL,             -- 0 / 1
    failing_criteria_json TEXT,               -- JSON list of strings
    recommendation TEXT NOT NULL,             -- "proceed" / "block" / "block_and_alert"
    blocked_training_run_id TEXT              -- FK to training_runs if a run was blocked
);
CREATE INDEX idx_corpus_gate_created ON corpus_gate_results(created_at DESC);
```

### 4.4 Dashboard integration

New panel on existing `/training` page (or a new `/corpus` page):

- Most recent gate result (pass / fail, per-criterion breakdown).
- 30-day trend: outcome mix over time, curated ratio over time, leakage accuracy over time.
- "Why was the last training run blocked?" detail view from `failing_criteria_json`.

API: `/api/corpus_gate/latest` + `/api/corpus_gate/history?limit=30`.

## 5. Interaction with Spec 1

| Phase | Gate | Spec |
|---|---|---|
| Before training run starts | corpus quality | **Spec 3 (this doc)** |
| After training run, before promoting model from `candidate` → `active` | model quality (rubric, canary, A/B, leakage on model outputs) | **Spec 1** |

Both gates write to structured tables (`corpus_gate_results`,
`eval_results`). Both emit Telegram alerts on failure. Neither
depends on the other's implementation — they can ship in either
order. A useful deployment sequence: ship Spec 3 first (pre-training
gate saves compute immediately by refusing to train on garbage
corpora) while Spec 1 is still in Sprint-A canary-curation phase.

## 6. Cost model

- Pre-training gate runtime: **minutes, not hours**. All metrics are
  existing light-weight computations over the existing
  `training_examples` table. Leakage detector already runs nightly in
  production.
- Storage: one row per training attempt in `corpus_gate_results` —
  trivial.
- Zero Ollama / Claude cost.
- Operator friction: **gate blocks a training run** means a night with
  no new model. Intentional. The alternative (training on broken
  corpora and silently degrading model quality) is what the audit is
  trying to stop.

## 7. Estimated implementation (1–2 sprints)

### Sprint A — gate module + schema + overnight wiring (~1 week)
- Add `corpus_gate_results` table via `src/schema/registry.py`.
- Build `src/training/corpus_gate.py` with the 10 criteria in §3.1.
- Wire into `src/scheduler/overnight.py` before `run_fine_tune`.
- Regression tests per criterion + one end-to-end test where a
  known-bad corpus is rejected.
- Telegram alert + logger.critical on block.

### Sprint B — dashboard + 30-day history UX (~0.5 sprint)
- `/corpus` or `/training` page panel with gate status + trend.
- API endpoints.
- Failing-criteria detail view.

## 8. Dependencies

- **None blocking.** All referenced tools (`quality_drift.py`, `leakage_detector.py`) exist; `training_examples` schema is live.
- **Chains with Spec 1** but neither requires the other.
- **Does not depend on Sprint F/G/H** (#530 chain).

## 9. Out of scope — filed separately

- **Embedding-based leakage detection** (`docs/research/15_Algorithm_Gap_Assessment.md` priority #6, "Highest") — 2–3× sensitivity upgrade over TF-IDF. Build a standalone sprint once this basic gate is live.
- **Rubric-score pre-filter** for training examples (rubric-as-corpus-filter, not rubric-as-model-judge) — `composite_score` column exists but is NULL; a separate sprint can backfill and add a gate criterion later.
- **DPO pairs / anchors** — per `red-team-interview.md:60`, the v2 target includes 400 DPO pairs + 75 anchors on top of the 40/25/5/15 outcome-labeled examples. Gating on DPO pair counts is a follow-up.
- **Golden-ratio evolution** based on Kang et al. 2025 30/70 finding — the framework's 62/38 may shift to 70/30 once empirically validated by the operator. Config-driven threshold makes this a one-line change later.

## 10. Success criteria

- Training runs with corpus violations (e.g., 80% WIN outcomes) are blocked, not silently executed.
- Telegram alert fires within 60 seconds of a gate block.
- Dashboard `/corpus` panel shows last 30 nights' gate decisions.
- `corpus_gate_results` accumulates ≥ 7 rows within first week of deployment.
- Zero false positives in the first 30 days (operator confirms each blocked run was correctly blocked).

## 11. Next CC sprint prompt (shape-only)

> "Build `src/training/corpus_gate.py` implementing the 10 pre-training
> gate criteria from `docs/sprints/future/training_curriculum_gate_spec.md`
> §3.1. Add `corpus_gate_results` table via `src/schema/registry.py`.
> Wire into `src/scheduler/overnight.py` before `run_fine_tune` with
> Telegram + logger.critical on block. Regression tests per criterion
> plus an end-to-end block-on-bad-corpus test."

Pass-3 spec file ends here.
