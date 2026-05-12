# Dual-GPU Workload Separation — Wave E Disposition

**Date:** 2026-05-12
**Decision:** Design-only. Implementation deferred to the first post-Sprint-5 maintenance window.
**Decision authority:** Operator (Sprint 5 closeout plan, Decision 1 / §2.3).

---

## Decision

Sprint 5 is the final sprint (`feedback_sprint_5_is_final`). No Sprint 6 exists. The dual-GPU Strategy A implementation is complete at the **spec level** and is deferred entirely. The decision to defer is grounded in three factors:

1. **Scope mass.** Implementation requires ~15 source-file edits, one new NSSM Windows service (`ArcisOllamaWatchdog`), 22+ new tests (net-replacing 21 vram_manager deletions), NSSM env read-merge-write procedure, and an operator-guide section insertion. Estimated 1.5 development-days.

2. **Sprint 5 deadline pressure.** Sprint 5 already carries Waves C, D, F, C7, and a Sprint Close PR. Adding the full dual-GPU implementation mid-sprint would create scope risk against committed deliverables.

3. **No production incident blocking it.** GPU isolation is a quality-of-life and VRAM-safety improvement, not a fix for an active failure. The existing single-GPU mutual-exclusion contract (`vram_manager.py`) continues to work correctly on the 3090 alone until the strategy is implemented.

---

## Canonical Spec

The authoritative design artifact is:

```
docs/audits/2026-05-12-dual-gpu-ideation/specs/2026-05-12-dual-gpu-workload-separation-design.md
```

This spec (v3, 2026-05-12) is complete and ready for implementation. It covers:
- Strategy A justification with strict-rigor analysis (§1–§4)
- All six `CUDA_VISIBLE_DEVICES` + `CUDA_DEVICE_ORDER` boundary points (§5)
- Six implementation change cards (§6)
- Verification plan extending `scripts/verify_training_readiness.py` (§7)
- Test plan with named functions and test-count delta against 5050 floor (§13)
- NSSM read-merge-write procedure protecting post-cutover production vars (§5.2 B1)
- Risk register with 19 risks including R16 (destructive NSSM env overwrite) and R17 (NUM_PARALLEL=4 thin cushion on 3060)
- Known considerations (§21) capturing 4 acknowledged minor caveats
- Non-normative Appendix D with reference PowerShell/Python snippets

Companion artifacts in the same directory:
- `docs/audits/2026-05-12-dual-gpu-ideation/operator-guide-insert.md` — ready-to-paste operator guide section (insert before `### "Ollama crashes / corpus producing template fallbacks"`)
- `docs/audits/2026-05-12-dual-gpu-ideation/brief.md` — original task #91 brief
- `docs/audits/2026-05-12-dual-gpu-ideation/spec-architect-draft.md` — Architect draft (pre-v3; superseded by canonical spec)

---

## Stale-Text Fixes Applied in This PR

Per Decision MIN5 from the devil's advocate review of the Sprint 5 closeout plan, 4 categories of stale text were corrected inline in the canonical spec as part of this Wave E PR:

| Fix | Location | Before | After |
|-----|----------|--------|-------|
| 1 — Sprint 6 removal | Line 4 (Status) | `Implementation deferred to Sprint 6.` | `Implementation deferred to the first post-Sprint-5 maintenance window (Sprint 6 does not exist…)` |
| 2 — Executive Summary SP6 refs | Lines 20+22+28 | `Sprint 6 catch-all bucket`, `SP6 implementation`, `Sprint 6 follow-up` | `post-Sprint-5` equivalents |
| 3 — Test floor 3682→5050 | Lines 25, 64, 125 | `3682 test floor`, `Test count floor: 3682`, `Test floor 3682.` | `5050` (pg-tests.yml EXPECTED=5050 is the current CI floor as of Sprint 5 Phase 2) |
| 4a — Training pipeline (Unsloth) | Line 55 (Out of Scope table) | CURRICULUM_TRAIN_SCRIPT described as still requiring Unsloth | Updated to note CURRICULUM path rewritten to Transformers+PEFT+TRL per `project_gpu_upgrade` (2026-05-10 RTX 3090 swap); DPO path still requires Unsloth |
| 4b — NUM_PARALLEL on 3090 | Line 765 (Rollback) | `NUM_PARALLEL on 3090 should stay at 2` | Corrected: NUM_PARALLEL=4 is viable on 3090 (24 GB VRAM); headroom concern is specific to 3060 |

Note: Additional `3682` occurrences remain in the spec at lines 44, 191, and 883 (section headers and test-plan body). These are in the interior of the detailed test plan section. They are acknowledged stale and were not modified in this PR due to the 4-hunk scope constraint; a future implementer sweeping the spec before execution should update them alongside the test-count delta accounting in §13.

---

## For the Future Implementer

Before executing this spec, the implementer must:

1. **Re-read §15** (SP6 Implementation Read-List) — `scripts/overnight_train.py` and `scripts/start_ollama_watchdog.bat` were NOT read during the spec-writing pass. Read both before implementing to check for env-stripping anti-patterns.

2. **Run `nssm get ArcisWatchLoop AppEnvironmentExtra > pre-change-env.txt`** BEFORE touching any NSSM config. The captured block must be included in the PR description (§13.7 requirement).

3. **Verify test count** by running `pytest tests/ -q --timeout=60` at implementation start. The floor at that time may exceed 5050.

4. **Check `docs/roadmap.md`** (created by the Sprint 5 Sprint Close PR) for any updated cross-references.

5. **Consult `docs/audits/2026-05-12-dual-gpu-ideation/operator-guide-insert.md`** for the ready-to-paste operator guide section before writing implementation PR description.

---

## Cross-References

- Sprint 5 closeout plan §2.3: `docs/audits/2026-05-12-sprint-5-closeout-plan/specs/2026-05-12-sprint-5-closeout-plan-design.md`
- Operator memory establishing deferral rationale: `feedback_sprint_5_is_final`
- Hardware context: `project_gpu_upgrade` (RTX 3090 24 GB swap, 2026-05-10)
- NSSM env protection: `reference_watch_loop_management` + PR #1056
- `docs/roadmap.md` — post-Sprint-5 roadmap (created in Sprint Close PR; links here when available)
