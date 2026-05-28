# Test Audit — Phase 5 PR-E (#102)

**Date:** 2026-05-28
**Branch:** sprint/phase-5/pr-e
**Methodology:** DD-18 (AND-conjoined vacuity criteria) + DD-38 (empirical break-the-SUT) + DD-19 (6-seam boundary-touch) + DA8/DA10 (receipt-cited deletions, additions-minus-5 budget cap)
**Standard:** [docs/standards/boundary-touch-tests.md](../../standards/boundary-touch-tests.md)

The audit removes tests that lock no regression (vacuous) and adds tests that
drive the codebase's external seams with real artifacts (boundary-touch). It is
deliberately **delete-conservative**: a test is removed only when a
PASSED-while-broken experiment proves it cannot detect the regression it claims
to guard.

## Receipt contents

| File | What it is |
|------|------------|
| [pass-a-candidates.md](pass-a-candidates.md) | Pass A — 194 heuristic candidates across 4 detectors (H1 mock-only, H2 high @patch:assert ratio, H3 SUT self-patch, H4 no-assertion). **List only — no deletions.** |
| [pass-b-empirical.md](pass-b-empirical.md) | Pass B — break-the-SUT experiments on the top candidates; canonical `## DELETION_LIST`. Confirmed-vacuous = **2**. |
| README.md (this file) | Overview + deletion matrix + additions matrix. |

## Headline result

| Metric | Value |
|--------|-------|
| Pass A heuristic candidates | 194 |
| Top candidates empirically broken | 9 SUT experiments / 12 named + sibling clusters |
| **Confirmed vacuous (deleted)** | **2** |
| Non-vacuous (genuine guards, kept) | 7 experiments / ~30 candidates |
| Stale Pass-A entries (file:line no longer resolves) | 2 |
| Boundary-touch tests added (6 seams) | 23 |
| Net test count | 6,989 → 7,010 (SQLite floor 5,467 held) |

The dominant finding: T27's heuristics are **high-recall / low-precision**. Most
H1 (mock call-count) and H4 (does-not-raise) flags are genuine behavioral guards
in this codebase — breaking the SUT fails them. The only reliably-vacuous shape
is **"does-not-raise" over a log-only / best-effort-stub SUT** (no guard, no
return assertion), where a `return`-only no-op satisfies the assertion. The T27
pre-empirical estimate of 15–25 was an over-count; following the heuristics
blindly would have deleted ~28 genuine guards.

## Deletion matrix (2 — each cited to a Pass-B experiment)

| Test | Detector | Pass-B proof | Coverage retained by |
|------|----------|--------------|----------------------|
| `tests/test_watch_strategy_gate.py::test_notify_gate_proposal_does_not_raise` | H4 | EXP-1: `_notify_gate_proposal` no-op'd → test PASSED | sibling `test_notify_gate_proposal_helper_exists` |
| `tests/trading/test_ib_broker_helpers.py::test_handle_ib_error_does_not_raise` | H4 | EXP-2: `handle_ib_error` no-op'd → test PASSED | sibling `test_ib_broker_helpers_module_imports` |

Both were independently re-verified by the campaign coordinator (break-the-SUT
reproduced; reverts clean).

## Additions matrix (23 — DD-19 6-seam, boundary-complete)

| Seam | File | Tests | Real artifact driven | Sample non-vacuity break |
|------|------|-------|----------------------|--------------------------|
| DB | `tests/api/test_cloud_routes_db_seam.py` | 3 | real temp SQLite DB | `return []` in `get_closed_shadow_trades` → row count 0 |
| LLM | `tests/llm/test_ollama_shutdown_boundary.py` | 4 | real localhost HTTP server | flip `_is_healthy` return tuple |
| HTTP | `tests/safety/test_safe_op_http_boundary.py` | 3 | real `@safe_op` + real HTTP | drop dry-run short-circuit → request sent |
| NSSM | `tests/scheduler/test_healthprobe_nssm_filenames.py` | 5 | real `ArcisConfig` getters | wrong path/filename in getter lambda |
| ripgrep | `tests/tools/test_symbolfind_ripgrep_boundary.py` | 4 | real `rg` subprocess | `_parse_rg_json` → `[]` (verified: 3/4 fail) |
| Broker | `tests/trading/test_broker_adapter_boundary.py` | 4 | real dataclasses + guard path | rename dataclass field → TypeError |

## Coordinator close-out notes

The T29 implementation agent timed out before committing; the campaign
coordinator completed PM-side verification (per `feedback_strict_rigor_no_handwave`):

1. **Removed 1 vacuous addition.** The draft included a `BrokerOrder`
   fractional-quantity test asserting `quantity == 0.30`. `BrokerOrder` is a
   plain dataclass with no `__post_init__` coercion, so the `float` annotation is
   not enforced — proven vacuous by mutation (`quantity: float → int` left the
   test PASSING). Removed (additions 24 → 23).
2. **Hardened 1 addition.** The ripgrep `find(kind='use')` test passed vacuously
   on empty results (its loop body never ran). Added a `results-found` guard to
   close the blind spot.
3. **Pre-merge math check (DA8):** `collect-only 6989 → 7010 == 6989 + 23 − 2`.
   Floor held (7010 ≥ 5,467). All scratch `src/` mutations reverted.
