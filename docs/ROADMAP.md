# ARCIS Roadmap

**Last updated:** 2026-10-05
**Status:** S04 merged. Step 4 (ranker) is next.

This is the build sequence from here to the $2,000 canary. Steps reference
SCOPE.md §5. Sprint numbers are sequential (S05, S06, …). The forward test
clocks (Q1/Q2/Q3) run in parallel from `prereg-v1` (2026-10-04).

---

## Where we are

| Sprint | Step | Status |
|---|---|---|
| S01 — News recorder | 1 | ✅ Merged |
| S02 — Carry-forward inventory | 2 | ✅ Merged; incumbent frozen (`524dd858…`) |
| S03 — Pre-tag power | 2m | ✅ Merged; `prereg-v1` tagged |
| S04 — Data plane audit | 3 | ✅ Merged (partial; T2/T4/T7 UNRESOLVED) |

**In flight:** Q1/Q2/Q3 forward test clocks (from `prereg-v1`).

---

## Build sequence

### S05 — Incumbent ranker, cost model, metrics (Step 4)
**Depends on:** S04 (done)
**Delivers:**
- Ranker reproduces `incumbent_v1` on fixtures (known-answer tests)
- Cost model implementing R06 with dated fees
- Metrics module with known-answer tests
- Point-in-time membership handling (uses S01 snapshots; resolves S04 T5 deferral)

**Why next:** Everything downstream (simulator, harness, paper lane) needs the ranker.

### S06 — Bracket simulator + candidate-day ledger (Step 5a)
**Depends on:** S05
**Delivers:**
- Bracket simulator implementing the preregistered rules (§1.1, §1.2)
- Ambiguity rate reporting
- Candidate-day ledger (every universe stock-day carries a label)
- Known-answer tests on synthetic data

**Maps to spec:** #4 Bracket simulator, #6 Attribution ledger (partial)

### S07 — Walk-forward harness + trial registry (Step 5b)
**Depends on:** S06
**Delivers:**
- Walk-forward harness implementing R1–R8
- Trial registry with Deflated Sharpe Ratio
- Sequential boundaries generated and archived
- End-to-end run on synthetic dataset with known answer

**Maps to spec:** #1 Walk-forward R1–R8, #2 Trials registry + DSR

### S08 — CPCV leakage detector (Step 5c)
**Depends on:** S07
**Delivers:**
- Combinatorial purged cross-validation implementation
- Leakage detection on the walk-forward harness
- Report on leakage risk in the current design

**Maps to spec:** #3 CPCV leakage detector

### S09 — Cost calibration + regime scenario engine (Step 5d)
**Depends on:** S07 (can parallel S08)
**Delivers:**
- Cost model calibrated against paper-lane fills (or historical estimates)
- Regime scenario engine for stress-testing
- Attribution ledger completion (if not done in S06)

**Maps to spec:** #5 Cost calibration, #7 Regime scenario engine, #6 Attribution ledger (remainder)

### S10 — Paper-only live lane (Step P)
**Depends on:** S05 (ranker); runs alongside S06–S09
**Delivers:**
- `sizing`, `execution`, `shield`, `oms`, `recon`, `records`
- Places each day's paper orders after `t_d`
- I-1, I-2, I-10, I-12 enforced; paper keys only
- Fills are Stage B evidence; never enter the §2.1 test series

**Why after S05:** Orders need the frozen ranker. Can start as soon as S05 merges.

---

## Parallel track: forward tests

| Test | Clock start | 12-month look | 24-month efficacy |
|---|---|---|---|
| Q1 — Incumbent | 2026-10-04 (`prereg-v1`) | ~2027-10 | ~2028-10 |
| Q2 — Text (Stage A) | 2026-10-04 | ~2027-10 | ~2028-10 |
| Q3 — Text (Stage B) | After Stage A | — | — |

The build sequence (S05–S10) runs while these clocks run. Nothing in the build
touches the forward test series.

---

## Gates

| Gate | Condition | Unlocks |
|---|---|---|
| Stage A passes | Q2 information test significant at 24-month look | $2,000 live canary |
| Paper plumbing check | S10 fills reconcile; no order errors for 60 sessions | Canary execution |
| Canary fill-quality | Fill quality within cost model bounds | $5,000 stage |
| §2.3 kill rule | Drawdown or failure triggers | Halt (any stage) |

**Capital progression:** $2,000 canary → 60 closed trades → $5,000 → doubling per 150 closed trades → $40,000 cap. (SCOPE §5; D-021, D-022.)

---

## Open items (not blocking the build)

- **S04 T2/T7:** Survivorship bias magnitude unquantified (no membership source). Proposed fix documented in `docs/research/data-plane-audit.md`.
- **S04 T4:** Corporate actions documented from Alpaca docs, not verified against data.
- **S04 T5:** Alpaca bar publication latency not measured. Must verify before the 12-month forward look (~2027-10).
- **S02:** 8 truly unpushed commits are infra-only (documented, not blocking).

---

## How this stays current

When a sprint merges, update this file: move the sprint to "Where we are," advance the next sprint's status, and adjust any dates. The SCOPE.md §5 step table is the authority; this file is the readable view.
