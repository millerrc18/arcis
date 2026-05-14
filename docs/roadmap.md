# Roadmap

This document tracks the sprint-history arc of arcis (halcyon-lab) and the
deferred-track items that did not land in any concluded sprint. It is
maintained at each sprint-close. See `CHANGELOG.md` for the full release
history; this file is the operator-facing summary.

Version anchor: see `src/version.py` (currently `v0.36.0`, tagged at the
Sprint 6 close PR — operator-led post-merge).

---

## Sprint history (Sprint 1.A.0 onward)

| Sprint | Closed | Tag | Highlight |
|---|---|---|---|
| **Sprint 1.A.0** | 2026-04-27 | v0.29.0 | Point-in-time SP100 universe (`src/universe/pit.py`); Wikipedia membership scraper; T10 migration of backtest/sim/training-backfill sites to `get_sp100_at()`. |
| **Sprint 1.A.1** | 2026-04-27 | v0.29.0 (rolled in) | Corp-action handling in PIT JSON (PCLN→BKNG, UTX+RTN→RTX, KRFT→KHC, EMC, YHOO); T2 union-helper tests + T3 backtester guard + T5a historical-data structural tests + T6 PIT discipline lint. |
| **Sprint 1.A.x** | 2026-04-28 | v0.30.0 | Reconcile track + dashboard sprint (Tier 1.A-1.F). Dashboard widgets + KPI strip + ledger pages. |
| **Sprint 1.B** | 2026-04-28 | v0.31.0 | Walk-forward harness + methodology wiring (`promotion_gate.py` + PBO + CPCV + block_bootstrap + mc_permutation + white_rc + PSR/DSR). Wired `get_calibrated_cost_model()` into `backtest_model()`. |
| **Sprint 1.C Phase 1+2** | 2026-04-29 | v0.32.0 | Attribution discipline + LLM-prompt PIT audit. |
| **Sprint S1-CC** | 2026-05-04 | v0.32.0 (rolled in) | Stage-1 corpus closeout (Batch A: 5 tasks) + walk-forward framework scoping (Batch B: 3 tasks, docs-only). |
| **Sprint 2** | 2026-05-05 | v0.32.0 (rolled in) | T1 `triggered_by` sentinels, T3 trainer model-version abstention fix, T7 gate-proposal KPI in dashboard, T8 cross-cutting integration tests (15 named), T9 operator runbook update + CHANGELOG sprint closeout. |
| **Sprint 3** | 2026-05-07 | v0.33.0 | Cockpit Coherence — 23 tasks across 8 batches. Dashboard rework, KPI strip negative-pnl handling, watch-loop heartbeat wiring. |
| **Sprint 4** | 2026-05-08 | v0.34.0 | Cockpit Followups + Notification Subsystem — 22 of 23 planned tasks (T22 deferred to Sprint 5 as `#SP5-notifications-routing-policy`). Visual-verify gate (11 pages + 2 components all PASS). |
| **Sprint 5** | 2026-05-13 | v0.35.0 | Cutover stabilization (Phases 0/1/2/2.5/3-revised) + notification policy/digest/silence (Wave D) + LLM packet enrichment (Wave C7a/C7b) + dual-GPU disposition (Wave E) + dev tooling (Wave F). |
| **Sprint 6** | **2026-05-14** | **v0.36.0** | **This release.** Walk-Forward Validation Framework v1 (Wave B: T1–T14) + SP6 catch-all sweep (Wave A: WA1–WA6). Production-gate AND-composition: shadow_trading → production requires PASS across walkforward + DSR + methodology gates. Sentinel guard (`WALKFORWARD_GATE_ENABLED`), DA-1 freshness cap (sha-match + 30-day window), T13 scheduler auto-fire (filelock + reconciler), Stage-1 corpus admissibility check. |

---

## Sprint 6 closeout summary (this release)

**Waves delivered:**

- **Wave A — SP6 catch-all sweep** (7 PR-review follow-ups from Sprint 5): WA1 `_get_finnhub_key` extraction into shared module; WA2 `price_target` matrix resolution; WA3 PE quality thresholds settings.yaml hook; WA4 env-pollution test fix; WA5 Decision 27 lock test; WA6 migration utils extraction + topo sort.
- **Wave B — Walk-Forward Validation Framework v1** (T1–T14, 14 tasks, PRs #1089–#1101):
  - T2: canonical `subtract_trading_days` refactor (no local helper)
  - T1: `WALKFORWARD_GATE_ENABLED` sentinel in `_evaluate_walkforward_gate`
  - T3: `excess_sharpe_min` per-window gate in `WalkForwardConfig`
  - T4: `walkforward_results` v2 columns (`excess_sharpe_min_used`, `gate_version`, `derived_from_backtest_id`)
  - T5+T6: window builder (`build_walkforward_windows`) + `corpus_id` field + VIX coverage validator
  - T7: schema migration verified (T4 columns materialized, zero drift)
  - T8: runner integration (corpus gate + VIX coverage + v2 column persistence)
  - T10: CLI `--corpus-id` / `--excess-sharpe-min` flags + HTTP read-route
  - T9: promotion-gate sentinel guard in `_evaluate_shadow_trading_gate`
  - T14: production-gate AND-composition + DA-1 freshness cap + DA-5 audit trail
  - T13: scheduler auto-fire (filelock, platform_events, reconciler) + `--backtest-result-id` / `--auto-fire` / `--force` CLI flags
  - T11: regression-lock test suite

**Tracker dispositions (Sprint 6 close 2026-05-14):**

| Tracker | Disposition | Outcome |
|---|---|---|
| WA1–WA6 | CLOSED-in-Sprint-6 | All 7 SP6 catch-all items from Sprint 5 PR reviews shipped in Wave A (PR #1088). |
| T13 retry-cap design | DEFERRED | Reconciler retry-cap covers `spawn_failed + skipped_no_corpus + timeout` but not `skipped_disabled`. Design call deferred — scope-fence was explicit. |
| T14 +85 LOC override | NOTED | T14 implementation ran ~85 LOC over the scope-fence estimate; `config/known_violations.json` updated at T14 close. Follow-up: determine if `_evaluate_production_gate` split is warranted. |
| `--strategy` / `--strategy-id` consolidation | DEFERRED | `run_walkforward.py` CLI uses `--strategy` but other scripts use `--strategy-id`; consolidation deferred to post-Sprint-6. |

---

## Deferred track — items NOT in v0.36.0

These items remain open at v0.36.0. Each carries a clear next-action note
and is operator-visible at the next sprint planning cycle.

### Engineering follow-ups (carried from Sprint 5)

- **`#97` — `alpaca_adapter.py` split** (425 lines on disk, exceeds the 400-line cap). Grandfathered via `config/known_violations.json`. Resolution: real refactor into `alpaca_adapter_core.py` + `alpaca_adapter_orders.py` + `alpaca_adapter_positions.py`. Estimated: ~1 sprint.
- **`#105` — `/api/kpis` performance** — cache `promotion_gate` results (currently re-computed per request) + vectorize `mc_permutation` (loop-based today). Estimated: ~1 day.
- **`#106` — `strategy_id` SQL filter pushdown** — current implementation filters in Python after fetch; push to SQL `WHERE` + add covering index. Estimated: ~half-day.
- **`#107` — `sqlite.py` deferrable FK** — does not honor `ColumnDef.initially_deferred=True`. Surfaced during T2 FK-creation work. Low blast radius (FK still created, just immediately-enforced). Estimated: ~1 day.
- **`#112` — Row-count drift investigation** — bidirectional drift between local SQLite and Render PG (pre-decommission snapshot). Forensic only; no production impact. Estimated: ~2 days.
- **`#114` — Content-level dedup** — local PG post-recovery contains different-PK same-content duplicates. Idempotent migration + dedup query. Estimated: ~half-day.

### Walk-forward follow-ups (new in Sprint 6)

- **T13 retry-cap design gap** — reconciler retry-cap covers `spawn_failed + skipped_no_corpus + timeout` events but does NOT cap `skipped_disabled` (WALKFORWARD_AUTOFIRE_ENABLED=false). A long AUTOFIRE-disabled window followed by re-enable could flood retries. Design decision: either extend cap to include skipped_disabled, or document the operator expectation that re-enabling AUTOFIRE clears the slate.
- **T14 `_evaluate_production_gate` size** — function grew ~85 LOC over the scope-fence estimate. Evaluate whether splitting into `_evaluate_production_gate_walkforward` + `_evaluate_production_gate_methodology` sub-functions improves readability without regression. Low urgency — function is well-tested.
- **`--strategy` vs `--strategy-id` CLI consolidation** — `run_walkforward.py` uses `--strategy` (value = strategy_id string) while `run_backtest.py` uses `--strategy-id`. Inconsistency surfaced in Sprint 6 T13 scope; deferred to avoid CLI-breaking-change mid-sprint.
- **SP-WF-017 sentinel-asymmetry warning** (DA-6) — startup WARN when `WALKFORWARD_GATE_ENABLED=true AND WALKFORWARD_AUTOFIRE_ENABLED=false`. Spec added the decision (DA-6) but was out of Sprint 6 scope. File as standalone task post-Sprint-6.
- **Dual-GPU workload-separation** (RTX 3060 + RTX 3090) — deferred from Sprint 5 Wave E; canonical design spec at `docs/audits/2026-05-12-dual-gpu-ideation/specs/2026-05-12-dual-gpu-workload-separation-design.md`. Largest standalone deliverable in the deferred queue.

---

## Sprint planning notes

- **Sprint 5 and Sprint 6 are closed** (v0.35.0 and v0.36.0). Future sprint cycles will assign fresh names and tracker IDs.
- The post-Sprint-6 deferred queue is dominated by Sprint 6 walk-forward follow-ups (T13 retry-cap design, T14 LOC override, SP-WF-017 DA-6) and the Sprint 5 carry-forwards (`#97` split, `#105`–`#107`).
- **SP-WF-016 falsifiability queries should be run weekly** during shadow→production promotion cycles. See `docs/operator-guide.md` §"Walk-Forward Validation Gate".

---

*Roadmap last updated: 2026-05-14 at Sprint 6 close (v0.36.0).*
