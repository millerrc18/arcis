# Roadmap

This document tracks the sprint-history arc of arcis (halcyon-lab) and the
deferred-track items that did not land in any concluded sprint. It is
maintained at each sprint-close. See `CHANGELOG.md` for the full release
history; this file is the operator-facing summary.

Version anchor: see `src/version.py` (currently `v0.35.0`, tagged at the
Sprint 5 close PR).

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
| **Sprint 5** | **2026-05-13** | **v0.35.0** | **This release.** Cutover stabilization (Phases 0/1/2/2.5/3-revised) + notification policy/digest/silence (Wave D) + LLM packet enrichment (Wave C7a/C7b) + dual-GPU disposition (Wave E) + dev tooling (Wave F). |

---

## Sprint 5 closeout summary (this release)

**Waves delivered:**

- **Wave A — Cutover preflight** (Phase 0/1/2/2.5): wrapper foundation (`_RowFactoryCursor`, `_scalar`, `engine_aware_upsert`); 82-site mechanical-replacement sweep; PRAGMA/introspection migration; date-function cleanup (12 sites / 6 files).
- **Wave B — Phase-3-revised cutover** (operator-led, one-DB): SQLite → local Postgres at `localhost:5433/halcyon` with `ARCIS_PG_CUTOVER_ENABLED` env gate routing `connect_db()` to the right engine.
- **Wave C — Data integrity hardening** (#54 `_compute_promotion_gate_kpi` wiring; #56 `strategy_id` FK on shadow_trades; #96 `platform_events` TableDef; #92 `_check_row_counts` cross-engine KeyError fix; #95 PG schema-completeness gap closure; #108 postgres.py default-value quoting bug).
- **Wave C7a — Council/walkforward/attribution/strategy packet sections** (T17 COUNCIL CONSENSUS; T18 HISTORICAL CREDIBILITY; T19 RECENT ATTRIBUTION; T20 STRATEGY CONTEXT header preamble).
- **Wave C7b — Plan-gated Finnhub fundamental-1 max-utilization** (T21 INSTITUTIONAL FLOW; T22 filings_sentiment + MATERIAL EVENTS seed; T23 press_releases sub-block; T24 stock_financials runtime + DATA CONTEXT header; T25 analyst_collector cap plan-conditional; T26 AST runtime-coverage scanner).
- **Wave D — Notification routing/digest/silence** (T10 policy gate / Decision 20 routing_overrides allowlist; T11 digest queue persistence; T12 safe_send verdict-dispatch; T13 `_html_escape` siblings + pytest isolation; T14 alert silence detector + `is_market_open` extraction).
- **Wave E — Dual-GPU disposition** (T15 dual-GPU workload-separation deferred to first post-Sprint-5 maintenance window; canonical-spec stale-text fixes — test-floor 3682→5400, Sprint 6→post-Sprint-5, Unsloth→Transformers+PEFT+TRL, NUM_PARALLEL=1→4).
- **Wave F — Dev tooling** (T7 stale-base check workflow; T8 conflict-marker scanner; T9 cutover finalization guard scaffolding).
- **Pre-T16 hardening** (#1081): `DigestQueue.pending_count`/`abandoned_count` use `_scalar()`; `sqlite_to_pg_migrate.py` `connect_timeout=30` symmetric with `render_to_local_migrate.py`.

**Tracker dispositions (operator triage 2026-05-13):**

| Tracker | Disposition | Outcome |
|---|---|---|
| `#26` | KILL | Closed without action — superseded by Wave D notification subsystem. |
| `#27` | CLOSE-as-resolved | Pre-existing `test_repo_structure.py` failures addressed via real refactor across Sprints 0-3. |
| `#96` | CLOSE-as-resolved | `platform_events` TableDef added in Wave C (#56 sibling deliverable). |
| `#97` | DEFERRED-post-Sprint-5 | `alpaca_adapter.py` 425-line file split — sentinel test deleted at T16 (#97 fold-in), grandfathered via `config/known_violations.json` until split is scoped. |
| `#104` | FOLDED-INTO-T16 | CompatRow indexing test added at T16 (cross-engine row-shape verification for `build_score.py:341` pattern). |
| `#105` | DEFERRED-post-Sprint-5 | Cache `/api/kpis` `promotion_gate` + vectorize `mc_permutation`. |
| `#106` | DEFERRED-post-Sprint-5 | Push strategy_id filter from Python to SQL + add index. |
| `#107` | DEFERRED-post-Sprint-5 | `sqlite.py` does not honor `ColumnDef.initially_deferred=True` — surfaced during T2 but low blast radius. |
| `#109` | FIX-NOW | `tests/test_no_conflict_markers_in_repo.py` shipped via PR #1079 (Wave F sibling). |
| `#111` | FIX-NOW | YES-prompt confirmation backport to `sqlite_to_pg_migrate.py` shipped via PR #1080. |
| `#112` | DEFERRED-post-Sprint-5 | Bidirectional row-count drift investigation between SQLite and Render PG. |
| `#113` | FOLDED-INTO-T16 | Phase-3 cutover finalization audit + checklist appended to operator-guide at T16. |
| `#114` | DEFERRED-post-Sprint-5 | Content-level dedup pass for local PG post-recovery (different-PK, same-content duplicates). |
| `#122` | FOLDED-INTO-T16 | "SP6" → "post-Sprint-5" shorthand rename across dual-GPU spec body (~25 sites). |

---

## Deferred track — items NOT in v0.35.0

These items remain open at v0.35.0. Each carries a clear next-action note
and is operator-visible at the next sprint planning cycle.

### Engineering follow-ups

- **`#97` — `alpaca_adapter.py` split** (425 lines on disk, exceeds the 400-line cap). Sentinel test deleted at T16; grandfathered via `config/known_violations.json`. Resolution: real refactor into `alpaca_adapter_core.py` + `alpaca_adapter_orders.py` + `alpaca_adapter_positions.py`. Estimated: ~1 sprint.
- **`#105` — `/api/kpis` performance** — cache `promotion_gate` results (currently re-computed per request) + vectorize `mc_permutation` (loop-based today). Estimated: ~1 day.
- **`#106` — `strategy_id` SQL filter pushdown** — current implementation filters in Python after fetch; push to SQL `WHERE` + add covering index. Estimated: ~half-day.
- **`#107` — `sqlite.py` deferrable FK** — does not honor `ColumnDef.initially_deferred=True`. Surfaced during T2 FK-creation work. Low blast radius (FK still created, just immediately-enforced). Estimated: ~1 day.
- **`#112` — Row-count drift investigation** — bidirectional drift between local SQLite and Render PG (pre-decommission snapshot). Forensic only; no production impact. Estimated: ~2 days.
- **`#114` — Content-level dedup** — local PG post-recovery contains different-PK same-content duplicates. Idempotent migration + dedup query. Estimated: ~half-day.

### SP6 catch-all items (aggregated from PR review feedback during Sprint 5)

- **`price_target` matrix resolution** (PR #1085 review) — `analyst_collector.py:146` calls `finnhub_plan_supports("price_target")` but `price_target` is NOT in `_FEATURE_MATRIX`. The gate is permanently False, dead code path. Resolution: either add `price_target` to `_FEATURE_MATRIX['fundamental-1']` (if Finnhub fundamental-1 plan provides it) OR remove the dead-code block from `analyst_collector.py:146-165`. Allowlisted in `tests/test_finnhub_plan_runtime_coverage.py::_REVERSE_INVARIANT_ALLOWLIST` until resolution.
- **`_get_finnhub_key` 3× duplication** (PRs #1082/#1083/#1084 reviews) — identical 12-line function across `institutional_ownership_collector.py`, `filings_sentiment_collector.py`, `press_releases_collector.py`. Extract to `src/data_collection/_finnhub_shared.py`. Saves ~30 LOC.
- **`_PE_REASONABLE_LO` / `_PE_REASONABLE_HI` settings.yaml hook** (PR #1084 review / T24) — hardcoded heuristics in `src/data_enrichment/financials.py` (`_PE_REASONABLE_LO = 2.0`, `_PE_REASONABLE_HI = 200.0`). Move to `config.data_enrichment.fundamental_quality_thresholds.{pe_min, pe_max}` for operator tuning.
- **`test_feature_matrix_distinguishes_free_and_premium` env-pollution** (PR #1085 review disclosure) — `tests/test_enrichment.py` fails on operator's local machine because `.env` sets `FINNHUB_PLAN` which `get_finnhub_plan()` prefers over the explicit config-dict arg per documented precedence. Fix: `monkeypatch.delenv("FINNHUB_PLAN")` in the test setup. CI passes (no `.env`).
- **Decision 27 footnote follow-up** (PR #1083 review) — `filings_sentiment` `action="ignore"` may silently drop legitimate Finnhub sentiment-model revisions. If model-revision drift becomes operationally significant, switch to `action="replace"` + add `filings_sentiment` to `_REPLACE_SEMANTICS` in `src/utils/db.py`.
- **Topological FK ordering for migration scripts** (PR #1067 review) — `sqlite_to_pg_migrate.py` and `render_to_local_migrate.py` both fire `INSERT`s in arbitrary table order. Works today because schema is FK-acyclic, but breaks under future FK cycles. Add topological sort on `TABLES` registry.
- **Extract `_redact_password` + `_confirm` to `scripts/_shared_migration_utils.py`** (PR #1067 review) — eliminates duplication between the two migration scripts (~40 LOC saved).

### Tracker placeholders preserved through Sprint 5

These trackers existed before Sprint 5, were touched but not closed, and
remain operator-visible:

- `#102` — Wave C7 LLM packet enrichment + Finnhub fundamental-1 max-util as on/off switch. **CLOSED by Wave C7a/C7b completion in this release.**

---

## Sprint planning notes

- **Sprint 5 was declared the final sprint** in operator memory (`feedback_sprint_5_is_final`). All deferred items above are scoped under "post-Sprint-5" — no `#SP6-*` tags should be created; new sprint cycles will assign fresh tracker IDs and named waves.
- The post-Sprint-5 dual-GPU workload-separation work (RTX 3060 + RTX 3090) is the largest standalone deliverable in the deferred queue; the canonical design spec is preserved at `docs/audits/2026-05-12-dual-gpu-ideation/specs/2026-05-12-dual-gpu-workload-separation-design.md`.

---

*Roadmap last updated: 2026-05-13 at Sprint 5 close (v0.35.0).*
