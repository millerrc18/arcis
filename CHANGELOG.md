# Changelog

## [Unreleased]

### Added (v0.26.2-scoped — Schema extension: sector_filter + event_exclusion)

Closes #539. Two additive optional fields on the strategy spec, both read-only
filters applied at candidate-selection time (pre-ranking). Minimal and
declarative per the v0.26.2-preflight (PR #536) Path B scope.

- **`universe.sector_filter: list[str]`** — if present, filters the candidate
  ticker set to those whose `SECTOR_MAP[ticker]` (GICS name) matches any
  listed value. Applied in `src/platform/signal_eval.py:_query_event_rows`
  between universe resolution and the SQL `IN(...)` clause.
- **`entry.event_exclusion.categories: list[str]`** — if present, skips any
  entry whose resolved entry date (`filing_date + next trading day`) matches
  a v0.25.1 `KNOWN_EVENTS` row whose category is in the listed set.
  Applied in `src/platform/backtest_engine.py:_run_event_driven`.

Both fields are optional and validated in
`src/platform/strategy_spec.py:validate_spec`. Type rules: non-empty
`list[str]`; nested `entry.event_exclusion` must be a dict if present.

Preserves the v0.25.3 framework baseline and does not modify
`lazy_prices_v1.yaml`. Regression test
`test_lazy_prices_still_loads_without_new_fields` confirms.

### Added (v0.26.2-scoped — post_audit_ruleset_v1.yaml)

First non-null `derived_from` strategy on main. `source_type =
forensic_audit_ruleset`, source date range 2026-04-01 → 2026-04-18,
`source_trade_ids` key intentionally omitted per Pass 2 finding (the R8
firewall at `walkforward_firewall.py:129-135` accepts key-absence but
rejects `null`).

- `universe.sector_filter: [Consumer Staples, Utilities, Health Care]`
  (28 tickers, 28% of current S&P 100 by GICS membership)
- `entry.event_exclusion.categories: [Trade Policy]` (excludes entries on
  any of the 9 2019-2024 Trade Policy dates from v0.25.1 backfill)
- Otherwise mirrors `lazy_prices_v1.yaml` — same cosine-similarity signals
  on 10-K/10-Q sections, same ATR-based brackets, same fixed-pct sizing

### Validated (v0.26.2-scoped — Walk-forward run on real EDGAR data)

First walk-forward run of a non-null-`derived_from` spec.

- **Outcome:** `INCONCLUSIVE / coverage_inconclusive` — matches Pass 1
  hypothesis; trade count collapses to 3 (all Consumer Staples, windows
  0/2/3 one each; windows 1/4 empty).
- **Run:** `run_id=f266e097-0e19-4360-ac4a-ca1c388dda02`,
  `spec_hash=463853b5...`, `code_git_sha=6b887927...`, `seed=42`.
- **Pooled Sharpe:** +1.019 (vs v0.25.3 baseline +3.528)
- **Pooled MDE:** 47.197 (vs 10.545 baseline; ~4.5× scales as 1/√N)
- **Heavy-tail flag:** 0 (N=1 windows degenerate to MDE=inf before the
  bootstrap heuristic activates — correct behavior)
- **R8(a) persisted:** `derived_from_source_type=forensic_audit_ruleset`,
  `derived_from_source_run_id=april-2026-forensic-audit`
- **R8(b):** overlap-assertion trivially cleared (2026-04 vs 2019-2024)
- **Filter bypass trigger (new):** did NOT fire — 3 trades ≤ 20 baseline

**Schema + filters both VALIDATED.** No framework-bug investigation filed.

Per-trade ledger:
- Window 0: PM (Consumer Staples) 2020-02-10, 13d, -5.79% (stop)
- Window 2: COST (Consumer Staples) 2021-10-07, 20d, +12.84% (timeout)
- Window 3: MO (Consumer Staples) 2023-02-28, 17d, -5.00% (stop)

Validation doc:
`docs/validation/post-audit-v1-scoped-walkforward-2026-04-20.md`.
Cycle summary: `docs/validation/v0.26-cycle-summary.md`. Ralph Loop:
`docs/sprints/post_audit_v1_scoped_{evaluation,research}.md`.

**Morning-only filter (the third forensic-audit refinement)** remains
deferred to #540. Pending intraday OHLCV data layer.

**Secondary finding (non-blocking):** `vix_at_entry` / `vix_tier` NULL
on 3/3 OOS trades. Same upstream data-enrichment gap documented in the
v0.25.3 validation doc. Primary `min_trades_per_window=10` gate already
binding.
### Blocked (v0.26.0 — Incumbent YAML extraction)

Closes #523 as **BLOCKED**. See #530 for prerequisite dependency chain.

- **Pass 1 + Pass 2 findings:** 7 of 8 pre-registered blockers hold. Incumbent cannot cleanly extract to YAML without schema extensions + close of #494 + scan pipeline refactor.
- **Deliverable:** `docs/sprints/incumbent_v1_yaml_evaluation.md` (309 lines) + `docs/sprints/incumbent_v1_yaml_research.md` (261 lines).
- **Docs-only ship** per prompt's explicit STOP path.

### Added (v0.26.2-preflight — post-audit ruleset feasibility diagnostic)

Closes #533. Pass 1 only — docs-only sprint, no implementation, no spec,
no schema changes.

- **Outcome: Path B (partial block, scoped sprint).** v0.26.2 does NOT
  inherit the full #530 dependency chain. Walk-forward is insulated
  from the `signal_eval.py:180` `NotImplementedError` (#494 / #530
  Sprint A) because it runs through `backtest_engine._run_scheduled`,
  not the live-flow candidate resolver.
- **Per-filter verdict:** Defensive (hard-filter, disjoint from #530),
  Tariff (schema-only, uses v0.25.1 `is_known_event` substrate),
  Morning-only (deferred to #540 behind intraday OHLCV data layer).
- **R8(a) finding:** `source_trade_ids: null` fails
  `validate_derived_from` at `walkforward_firewall.py:129-135` —
  recommend omitting the key entirely.
- **Deliverable:** `docs/sprints/post_audit_v1_preflight.md` (343 lines).

### Validated (v0.25.3 — Walk-forward framework end-to-end on real EDGAR data)

Closes #532. First real-data run of the walk-forward v1 framework (shipped
in v0.25.0 / PR #520) against `src/platform/specs/lazy_prices_v1.yaml`
using the operator's local EDGAR corpus.

- **Outcome:** `INCONCLUSIVE / coverage_inconclusive` — matches the Pass 1
  pre-registered hypothesis (NOT PASS expected; forensic audit established
  lazy-prices underpowered at 2019-2024 trade density).
- **Run:** `run_id=88fd926e-1789-46f0-aee4-501addbb7256`,
  `spec_hash=ea78fed3...`, `code_git_sha=0f5e7178...`, `random_seed=42`.
- **Windows:** 5/5 `INCONCLUSIVE_DATA`. 20 OOS trades across 2019-2024
  (4/7/4/4/1 per window). Zero purged, zero embargoed.
- **Heavy-tail override:** fired on 4/5 windows, correctly driving MDE
  values to capture small-N pathology (Window 0: 4-trade, Sharpe −142,
  MDE 8.37e15). Not a bug — truthful reflection of small-N instability.
- **R8(a):** `derived_from: null` correctly propagated through to
  `walkforward_results.derived_from_source_type = NULL`.
- **Framework-bug trigger:** did NOT fire (would have required
  `outcome_state = PASS`).
- **Synthetic vs real comparison:** outcome state, reason, window-state
  distribution, heavy-tail count, and pooled MDE all match the synthetic
  INCONCLUSIVE baseline (`docs/validation/lazy-prices-v1-walkforward-2026-04-19.md`).
- **Validation doc:**
  `docs/validation/lazy-prices-v1-walkforward-real-2026-04-19.md`
- **Ralph Loop docs:**
  `docs/sprints/lazy_prices_v1_real_evaluation.md` (Pass 1),
  `docs/sprints/lazy_prices_v1_real_raw.md` (Pass 2).

**Secondary finding (non-blocking for this sprint):**
`vix_at_entry` and `vix_tier` are NULL for 20/20 OOS trades, driving
`vix_tier_coverage = 0`. Data-enrichment gap upstream of the framework;
filed as follow-up in the validation doc. Does not affect this run's
INCONCLUSIVE verdict (primary `min_trades_per_window = 10` gate already
binding).

### Changed (v0.25.2 — Roadmap completeness audit)

Closes #526. Additions-only sprint — no new code, `frontend/src/pages/Roadmap.jsx`
data extensions only.

- **New Phase 1 subphase "Parked / deferred"** — 15 items captured that memory
  and open GitHub issues reference but that were missing from the roadmap UI:
  1 surprise-shipped (HSHS dashboard, flipped to `done` with reference to
  `Health.jsx:247-289`) + 14 pending items across issue-referenced tech debt
  (#367 WatchLoop, #432 position-cap consolidation, #451 residual shorts,
  #478 SQLite repository pattern, #479 executor.py mega-functions, #480
  shadow_trading test suite, #491/#492 Tier 7 correlation work, #493/#494
  v0.24.1 wiring gaps, #497 forensic refactor) and memory-only deferred items
  (AI Council 5→7 expansion, Alpaca MCP integration, IB log-only broker).
- **Phase 2 Month 3** — 1 item appended: UPS purchase (CyberPower
  CP1500PFCLCD) — complements the existing Dedicated Arcis machine row that
  only mentions UPS in its specs blurb.
- **Phase 3 new subphase "Second strategy candidate (v0.27.x)"** — 1 item:
  second-strategy candidate spec gated on v0.26 cycle outcome.
- **Phase 5 Fund formation** — 3 items appended: CPCV upgrade, live
  walk-forward (rolling OOS extension), and v1.0.0 release gate
  (fund-formation readiness) with explicit prerequisite list.
- **Skipped** — "Research Analyst setup" per guardrail #3 (don't invent items
  when memory is vague). Roadmap.jsx:161 already explicitly supersedes the
  concept: "Supersedes the stale 'Research Analyst desk (relaxed thresholds)'
  concept — platform evaluates genuinely uncorrelated strategies, not relaxed
  variants of swing."
- **Ralph Loop docs** — `docs/sprints/roadmap_completeness_evaluation.md`
  (Pass 1) + `docs/sprints/roadmap_completeness_research.md` (Pass 2).

Total Roadmap.jsx delta: +20 items across 4 insertion sites (1 new Phase 1
subphase with 15 items, 1 Phase 2 append, 1 new Phase 3 subphase with 1 item,
3 Phase 5 appends). Zero existing items modified. No MASTER.md changes.

### Added (v0.25.1 — known_events 2019-2024 backfill + is_known_event helper)

Load-bearing prerequisite for v0.26.2's post-audit ruleset tariff-exclusion
rule. Before this sprint, `src/diagnostics/known_events.py` only carried
March-April 2026 forward-planning dates, meaning any tariff-exclusion rule
applied to walk-forward v1 OOS windows (2019-01-01 → 2024-09-30 per
`walkforward_config.py` R1) would match zero historical dates and be
effectively a no-op.

- **9 new events** added to `KNOWN_EVENTS` covering the 2019-09-30 →
  2024-09-30 window, each verified against a primary source
  (treasury.gov/OFAC, USTR, White House EO, BIS, DOD, Maersk). See
  `docs/sprints/known_events_and_drift_repair_research.md` §1.1 for
  per-event market-move verdict and source URL.
- **5 new category labels** — `SANCTIONS_INITIAL`, `SANCTIONS_ESCALATION`,
  `EXPORT_CONTROLS`, `INDUSTRIAL_POLICY`, `TRADE_DISRUPTION` — all roll
  up to existing `"Trade Policy"` category for consumer uniformity
  (`src/diagnostics/analyses.py:_match_events` unchanged).
- **`EVENT_METADATA: dict[str, EventMeta]`** — new parallel dict keyed on
  the same dates as `KNOWN_EVENTS`. Carries per-event description,
  affected-sector list (empty = broad-market), primary-source URL, and
  market-impact note. Invariant enforced by test:
  `set(KNOWN_EVENTS) == set(EVENT_METADATA)`.
- **`is_known_event(date_str, category=None)`** helper — returns True
  iff the date is keyed in `KNOWN_EVENTS` and (if category given) the
  category matches. Pure function, no side effects.
- **Backward compatibility** — `KNOWN_EVENTS` and `EVENT_CATEGORIES`
  dict shapes unchanged; existing consumer at `analyses.py:210-213`
  reads the same API.
- **Coverage floor** — regression test requires ≥ 8 events in the
  2019-09-30 → 2024-09-30 window; hard fails if count drops.
- **File size** — `known_events.py` at 327 lines, within the 400-line
  guardrail; no split required.
- **13 new tests** in `tests/diagnostics/test_known_events.py` covering
  schema invariants, category closure, coverage floor, metadata parity,
  primary-source format, helper lookup, and new-label category routing.

### Fixed (v0.25.1 — MASTER.md Section 2 + CLAUDE.md drift repair)

Today's 11-PR session shipped without mid-sprint `MASTER.md` updates;
`scripts/verify_docs.py` was failing with 5/5 warnings. Repaired:

- `Tests` row: 2,141 → 2,507 (+366 tests across platform-foundation/rigor/
  safety/shadow sprints + dashboard v1 + walk-forward v1 + training-data
  audit + hygiene bundle + known_events backfill). Test files: 181 → 227.
- `Python files` row: 214 → 303 (+89 modules across the same sprint
  cluster).
- `Dashboard pages` row: 25 → 28 (Walkforward Results added v0.25.0).
- `Research docs` row: 107 → 92 (-15; doc pruning since last update).
- `Schema tables` row: 61 → 67 registry, 58 synced to Postgres (9
  local-only enumerated in the annotation).
- `Closed trades` row: 85 → 88 (live count per latest shadow-status).
- `GitHub issues` row: 0 → 40 (actual open issue count via `gh issue list`).
- `Training data` row reformatted to concise
  `1,782 examples total; 76 quarantined (75 format_drift + 1 v1_citation);
  1,706 clean corpus` per updated-prompt copy.
- Component rows in §2 updated to match: `Dashboard (Arcis)`
  (26 → 28 pages), `Schema registry` (63 → 67 tables), `Render sync`
  (44/51 → 58/67 tables).
- **Four new Deployed Components rows** added: WalkforwardResults
  dashboard page (v0.25.0), Walk-forward v1 promotion gate (v0.25.0,
  soft migration live), Capability registry + `/api/system/index`
  (v0.25.0), Training audit pipeline + quarantine (v0.26.0 — 1,706
  clean / 76 quarantined).
- `CLAUDE.md` line 14 table count: 64 → 67. Authoritative-count
  one-liner preserved.
- `scripts/verify_docs.py` now exits 0 with 5/5 passes.

**Deferred follow-up:** `frontend/public/architecture.html` (880 lines,
zero `walkforward` references after PR #520) is stale but outside the
`verify_docs.py` check set. Issue to file for a subsequent sprint.

### Changed (v0.25.1 — RELEASES.md session addendum + Roadmap.jsx retroactive updates)

- `RELEASES.md` v1.0.0 criteria table: Phase 1 gate trade count
  `18 trades (36%)` → `88 trades (target reached — validate
  WR/Sharpe/PF/DD next)`. Count only; WR/Sharpe/PF/DD gate metrics
  not yet computed (next validation sprint).
- `RELEASES.md` — added "v0.25.0 Session addendum (2026-04-19)"
  entry documenting PRs #506, #509, #512-#519, #521 with the
  patch-level rationale for each. Not tagged as its own release
  because it's the same opening-bell session as v0.25.0 (walk-forward
  v1 already tagged) and v0.26.0 (training-data audit still
  [Unreleased]).
- `frontend/src/pages/Roadmap.jsx`:
  - `lastUpdated`: 2026-04-17 → 2026-04-19.
  - **Weeks 8-12 subphase:** 4 items flipped `pending` → `done`
    (Earnings 7-day exclusion SD#33, 3-regime classifier v2 SD#35,
    Monthly retraining cadence SD#34, TCA logging SD#38). Each item's
    `d` field updated with shipping evidence.
  - **Strategy Research Platform subphase:** 13 items flipped
    `pending` → `done` (backtest harness, strategy spec YAML + plugin,
    DSR gate, CSCV/PBO + walk-forward, survivorship bias / point-in-time
    universe, Task 0 EDGAR fetch, per-desk Alpaca clients, shadow-trading
    harness, promotion pipeline, correlation monitoring, hard exposure
    limits, defensive dashboard desk filter, Strategy Research dashboard
    page). Lazy Prices strategy flipped `pending` → `in-progress`
    (spec + synthetic smoke done; real-data walk-forward pending).
  - **New subphase `'v0.25.0 — Rigor + hygiene bundle (April 19, 2026)'`**
    with 11 `done` entries (capability registry v1, training-data audit,
    walk-forward framework, command-queue TTL, DB busy_timeout, SQLite
    TEXT coercion, composite PK fix, command-execution hygiene,
    dependency hygiene, GitHub Actions disabled, SD#42 strategy
    evaluation).
- Frontend build verified after edits (`npm run build` ✓ 526ms,
  2,765 modules transformed).

### Chore (v0.25.1 — grandfathered violations from 2026-04-19 merges)

`config/known_violations.json` — added 1 file + 4 functions that
slipped past `test_repo_structure.py` because GitHub Actions was
disabled mid-session. All pre-existing, not caused by this sprint:

- `src/platform/promotion.py` (525 lines) — PR #520 walk-forward
  gate evaluator.
- `src/platform/promotion.py:_evaluate_shadow_trading_gate` (69 lines)
  — same PR.
- `src/platform/rigor/walkforward_runner.py:persist_run_result` (93)
  — PR #520.
- `src/platform/rigor/walkforward_runner.py:run_walkforward` (103) —
  PR #520.
- `src/sync/render_sync.py:run_sync_cycle` (68 lines) — PR #516
  (expire_stale_commands + heartbeat additions).

Follow-up issue to file: "split platform/promotion.py + rigor/
walkforward_runner.py + sync/render_sync.py:run_sync_cycle for a
dedicated cleanup sprint".

### Fixed (v0.25.1 — test_render_sync mock for expire_stale_commands)

`tests/test_render_sync.py::test_healthy_connection_reused_without_reconnect`
patched `pull_commands` but not the new `expire_stale_commands` orphan-
sweep (added in PR #516 same day). The sweep opens its own psycopg2
connection, breaking the test's `connect.call_count == 1` assertion.
Added `patch("src.sync.render_sync.expire_stale_commands", return_value=0)`
to the mock stack. Test-only change; runtime behavior unaffected.

### Changed (2026-04-19 — GitHub Actions disabled)

- Deleted `.github/workflows/ci.yml` and `.github/workflows/daily-repo-audit.yml` to conserve Actions spend until walk-forward validation proves live edge (per April 2026 pivot).
- Added `scripts/run_ci_locally.ps1` — runs the same checks (repo structure guardrails, full pytest with `-x --timeout=60`, test count floor, frontend build, doc drift). Flags: `-SkipFrontend`, `-SkipSlow`.
- Re-enable path: restore workflows from git history after walk-forward v1 real-data run shows excess-Sharpe ≥ 0.5 at t ≥ 2.0 over 150 OOS trades (SD#25).

### Added (v0.25.0 — Walk-Forward Validation Framework v1)

Load-bearing multi-year infrastructure. Every future strategy must pass
walk-forward v1 before promotion to `shadow_trading` or real capital.
Closes three regime traps identified in the April 18 forensic audit:
regime-averaged false positives, underpowered Sharpe reporting, and
bootcamp-derivation circularity.

- **Three-state outcome framework** (PASS / FAIL / INCONCLUSIVE) — never
  collapsed to boolean anywhere in the stack. Schema enforces
  `outcome_state` NOT NULL; `check_promotion_gate` evidence carries
  `walkforward_outcome_state` + `walkforward_reason` fields end-to-end.
- **R1 — Five non-overlapping OOS windows** 2019-01-01 → 2024-09-30,
  each with a 2-calendar-year IS flank
  (`src/platform/rigor/walkforward_config.py`).
- **R2 — Purge + embargo** (`walkforward_purging.py`) runs at every
  IS/OOS boundary to prevent leakage.
- **R3 — Point-in-time S&P 100 universe** — no survivorship bias.
  `data/reference/sp100_historical.csv` sourced from S&P DJI press
  releases + Wikipedia index-change tables. Resolver in
  `walkforward_universe.py`.
- **R4 — Transaction costs** (0.5 bp per side, 1.0 bp round-trip)
  applied uniformly in `walkforward_costs.py`.
- **R5 — Determinism** via `WalkForwardConfig.random_seed`; spec hash
  + git SHA recorded per run.
- **R6 — MDE gate** using annualized-scale Lo (2002) formula with
  Newey-West N_effective correction; heavy-tail bootstrap SE override
  at `bootstrap_SE > 1.5 × parametric_SE` (10k resamples).
- **R7 — Full reproducibility columns** on every `walkforward_results`
  row: spec_hash, code_git_sha, random_seed, config_json.
- **R8 — Strategy identity firewall** (`walkforward_firewall.py`):
  (a) `derived_from` required field on every spec, (b) overlap
  assertion before any window runs, (c) no inherited credit,
  (d) bootcamp forced False, (e) PR body declaration (honor-system).
  Non-blocking runtime heuristic emits WARNING when spec first-commit
  is within 30 days of a matching forensic audit AND derived_from=null.
- **Schema** — `walkforward_results`, `walkforward_trades`, and
  `sp100_historical_constituents` added to `src/schema/registry.py`.
  Table count 64 → 67.
- **CLI wrapper** `scripts/backtest/run_walkforward.py` — exit codes
  0/1/2/3 map PASS/FAIL/args-error/INCONCLUSIVE so CI can distinguish
  underpowered from failed.
- **Lazy Prices v1** spec updated with `derived_from: null`
  (literature-derived from Cohen-Malloy-Nguyen 2020 JF).
- **Dashboard** `/walkforward-results` React page with three-state
  color coding (PASS green, FAIL red, INCONCLUSIVE amber) +
  INCONCLUSIVE_POWER / INSUFFICIENT_DATA sub-badges +
  per-window/per-trade drill-down.
- **Backend route** `src/api/cloud_routes/walkforward.py` — runs list,
  run detail, window aggregation, trade drill-down.
- **Promotion gate** `check_promotion_gate` — walk-forward v1 takes
  precedence when a row exists; three-state result preserved in
  evidence dict. Soft migration: legacy DSR + PBO + OOS_efficiency path
  still runs when no walkforward_results row exists.
- **Synthetic smoke test** — `scripts/backtest/lazy_prices_smoke_test.py`
  exercises all three outcome paths. Cloud fallback: report marked
  SYNTHETIC FALLBACK when real EDGAR data not accessible. Operator
  re-runs locally after PR review.
- **131 new tests** across 9 new test modules in
  `tests/platform/rigor/`, `tests/scripts/`, `tests/api/`, and
  `tests/platform/test_promotion_walkforward.py`.

### Added (v0.26.0 — Training Data v1-Citation Audit)

- `src/training/audit/` package — three-pass audit for the 1,782-row
  `training_examples` corpus:
  - Pass A (`pass_a_citation.py`) — quarantines rows whose narrative
    cites the v1-buggy outcome and contradicts the v2-corrected
    outcome. Ground truth lives in `attribution_trades`
    (`ranker_only_outcome_v1 != ranker_only_outcome`). Lexicon-based
    win/loss direction classifier with word-boundary regex
    (`successful` fires; `unsuccessful` does not).
  - Pass B (`pass_b_format.py`) — XML tag integrity on `output_text`
    (`<why_now>`, `<analysis>` at 95% prevalence) + plain-text label
    schema on `input_text` (`Ticker:`, `Current Price:`, `Trend State:`
    — all 100% prevalence per commit-12 calibration).
  - Pass C (`pass_c_leakage.py`) — TF-IDF + LogReg probe with
    StratifiedKFold CV + balanced-accuracy scoring on the labeled
    subset (`blinded_win/loss`, `outcome_win/loss`). Masks ticker +
    company names. Report-only; never auto-quarantines in v1.
- `@register_action(name="training_data_audit", ...)` — capability
  registered at import time per Sprint 1B. Appears in
  `/api/system/index` and as a third kickoff button on `/diagnostics`.
- `POST /api/diagnostic-runs/training-audit` + 409 CONFLICT dedup
  (same pattern as regime + forensic).
- `run-training-audit` command dispatched through
  `src/commands/diagnostic_handlers.py` →
  `dashboard_runner.run_diagnostic` →
  `scripts/audits/training_data_v1_audit.py`.
- Frontend: third `<div>` in `DiagnosticKickoffButtons.jsx`
  (grid-cols-3); `DiagnosticRunTable.parseDecision()` recognizes
  `{quarantined_total, total_audited}` summary_json shape.
- Schema: `training_examples.quarantined INTEGER DEFAULT 0` +
  `training_examples.quarantine_reason TEXT` columns (additive via
  registry). `diagnostic_runs.diagnostic_type` description widened
  to `'regime' | 'forensic' | 'training_audit'`.
- Fixed quarantine-reason taxonomy (`src/training/audit/taxonomy.py`):
  `v1_attribution_contradicts_narrative` |
  `format_drift_missing_section` | `format_drift_deprecated_marker` |
  `format_drift_malformed` | `leakage_ngram_suspect`. Free-form
  strings are not accepted (R3).

### Audit results (2026-04-19 production run)

- Total audited: 1,782; quarantined 76 (4.3%); clean corpus 1,706.
- Pass A: 1 quarantine (CSCO, `blinded_win`, narrative cited v1="loss"
  contradicting v2="win"); 7 preserved outcome-neutral.
- Pass B: 75 missing `<why_now>` or `<analysis>` XML tags.
- Pass C: balanced accuracy 0.500, majority baseline 0.721 — NOT
  LEAKING. Probe confirms the narrative does not encode the outcome
  beyond class-imbalance baseline.
- Full report: `docs/audits/training-audit-2026-04-19.md`.

### Tests added (v0.26.0)

- `tests/training/test_pass_a.py` (14 tests)
- `tests/training/test_pass_b.py` (12 tests)
- `tests/training/test_pass_c.py` (7 tests)
- `tests/training/test_audit_integration.py` (12 tests)
- `tests/audits/test_training_audit_cli.py` (6 tests)
- `tests/test_diagnostic_handlers.py` (+3 tests)
- `tests/api/test_diagnostic_routes.py` (+5 tests)
- `tests/test_schema.py` (+2 tests)

### Added (v0.25.0 — Capability Registry, Sprint 1B)

- `src/platform/capability_registry/` — four in-process registries
  (ACTIONS, STATES, SYSTEMS, DECISIONS) populated at import time via
  decorators, mirroring `src/platform/plugin_registry.py:19`. Pydantic
  v2 validation rejects partial metadata at decorator time; deprecated
  entries must specify `deprecated_replacement`. ActionEntry
  input/output schemas validated as Draft-7 JSON Schema (MCP-compatible).
- `GET /api/system/index` + `POST /api/system/index/{name}/mark-reviewed`
  (`src/api/cloud_routes/system_index.py`). State queries and system
  health checks run in a shared ThreadPoolExecutor with a 2s per-call
  timeout. One bad query cannot cascade-break the endpoint (R5).
- `operator_view_state` table (`src/schema/registry.py`) tracks per-
  operator last-viewed baseline + delta for each entry, plus local
  Mark Reviewed override. `sync_to_postgres=False` — local state only
  until v1.1's source-file automation.
- 18 retroactive capability registrations across the platform:
  - Actions: `regime_diagnostic`, `forensic_trade_audit`,
    `strategy_backtest`, `edgar_historical_backfill`
  - States: `shadow_trade_cohort`, `strategy_registry_state`,
    `training_corpus`, `bootcamp_mode`, `alpaca_account`, `ollama_model`
  - Systems: `watch_loop`, `reconcile_trades`, `attribution_resolver`,
    `nightly_audit_agent`
  - Decisions: `bootcamp_still_active`, `pullback_strategy_contaminated`,
    `lazy_prices_deprecated_on_sp100`,
    `no_new_strategy_specs_until_walkforward_ships`
- Dashboard panels: `QuickStatsPanel`, `SystemIndexPanel`,
  `WhatsNewPanel`, `CapabilityDetailModal` (with Mark Reviewed flow).
  Wired into `frontend/src/pages/Dashboard.jsx`; 60s refetch interval.
  No new npm deps.
- CI enforcement: `tests/test_capability_registry_metadata.py` (10
  tests) + `tests/test_capability_registry_integration.py` (5 tests).
  Stale entries (>180d) emit warnings, not failures.
- `jsonschema>=4.0` promoted from transitive to first-class dependency.
- `docs/capability_registry.md` spec + how-to.
- Ralph Loop artifacts: Pass 1 evaluation + Pass 2 research findings
  committed as `docs/sprints/capability_registry_v1_evaluation.md` and
  `docs/sprints/capability_registry_v1_research_findings.md`.

### Tests (Sprint 1B totals)

- 15 schema tests (`tests/platform/test_capability_registry_schemas.py`)
- 14 registry mechanics tests (`tests/platform/test_capability_registry.py`)
- 10 CI metadata tests (`tests/test_capability_registry_metadata.py`)
- 12 API endpoint tests (`tests/api/test_system_index.py`)
- 5 integration tests (`tests/test_capability_registry_integration.py`)
- 56 new tests total, all green.

### Added (v0.25.0 — Diagnostic Dashboard)

- New `/diagnostics` dashboard page with kickoff buttons for regime and forensic diagnostic runs, inline markdown report rendering (react-markdown + remark-gfm), and inline base64 plot display. Polls 5s while active, 30s otherwise.
- `diagnostic_runs` + `diagnostic_run_plots` tables (schema registry `src/schema/registry.py`) — sibling layout with base64-encoded PNGs so plots reach the Render dashboard through existing table-only sync.
- Six new REST endpoints under `/api/diagnostic-runs/*` (cloud): POST regime/forensic (202 with queued run_id), GET list (filterable by type+status), GET single, GET report markdown, GET plots.
- Two new executor handlers in `src/commands/executor.py`: `run-regime-diagnostic`, `run-forensic-audit`. Both delegate to the new `src/diagnostics/dashboard_runner.py` orchestration helper (subprocess, report parse, plot encode, SQLite transaction).
- `src/diagnostics/summary_extractor.py` — regex parser for `## Executive Summary` sections of both report formats, with raw-text fallback when fields can't be extracted.
- Deps: `react-markdown@^9`, `remark-gfm@^4` (operator-approved).
- 26 new tests: 6 summary-extractor, 3 dashboard_runner, 6 handler, 9 API route, 2 end-to-end smoke.

### Refactor (post-Sprint-3 tech debt — closes #471)

- Extract 4 Sprint-2-grandfathered size-guardrail violations into named helpers with zero behavior change:
  - `src/platform/backtest_engine.py` (432 → 396 lines): split `_inject_cosine_scores` into new `src/platform/backtest_attribution.py` module. Pattern mirrors Sprint 1's `signal_eval.py` extraction.
  - `src/platform/promotion.py::check_promotion_gate` (97 → 25 lines): dispatcher delegates to `_evaluate_shadow_trading_gate` / `_evaluate_production_gate` per-target helpers.
  - `src/platform/rigor/walkforward.py::run_walkforward` (83 → 58 lines): extract `_run_one_fold(strategy_spec, fold_spec)` + `_compute_efficiency` helper.
  - `src/platform/features/cosine_similarity.py::_parse_section_from_fulltext` (68 → 32 lines): extract `_is_substantive_match(body)` predicate + `_SECTION_PATTERNS` module-level dict.
- `config/known_violations.json` — 4 entries removed. No new grandfatherings added.

### Added (post-Sprint-3 feature completion — closes #475)

- `backtest_results` schema — 2 new NULL-defaulting columns: `pbo` (Probability of Backtest Overfitting from CSCV) and `oos_efficiency` (walk-forward OOS_SR / IS_SR). Populated by Sprint 4's param-sweep driver (PBO) and by new `--with-walkforward` CLI flag (OOS efficiency).
- `scripts/run_backtest.py --with-walkforward` — invokes `run_walkforward` against the strategy spec + date range and persists `oos_efficiency` to the `backtest_results` row.
- `src/platform/promotion.py::_evaluate_shadow_trading_gate` now enforces the full three-gate check per spec line 1127-1135:
  - DSR ≥ 0.95 (was already live via Task 5-carryover)
  - **PBO ≤ 0.50** (new — fails with clear message if NULL)
  - **OOS_efficiency ≥ 0.30** (new — fails with clear message if NULL)
  Evidence dict now carries all three values; historical gate decisions are fully reproducible from `strategy_promotion_events.gate_result_json`.

### Tests

- 5 new tests in `tests/platform/test_promotion.py` covering each new failure mode (PBO NULL, OOS NULL, PBO over threshold, OOS under threshold) plus the all-pass case.
- `--with-cscv` CLI flag deferred to Sprint 4's param-sweep driver where it semantically belongs (a single-config backtest can't produce meaningful PBO).

### Fixed

- deps: add missing `beautifulsoup4` to `requirements.txt` — `fed_collector` and clean-deploy importability depended on a transitive install; now declared as a first-class dependency. (#455)
- deps: add missing `numpy` and `scipy` to `requirements.txt` — analytics modules (evaluation, features/regime, simulation/monte_carlo) import both but neither was declared; clean deploys crashed on first analytics import. (#460)
- deps: add missing `pyarrow` to `requirements.txt` — `src/simulation/cache.py` uses `pd.read_parquet` / `to_parquet`; pandas requires pyarrow for parquet IO. Simulation cache crashed on clean deploy. (#462)

## v0.24.0 (Strategy Research Platform — Final)

Final release of the Strategy Research Platform (v0.24.0 arc). Merges Sprint 4 continuation: visibility layer + functional signal integration.

### Added
- **`_find_candidates` integration** (highest-value task): `src/platform/signal_eval.py::find_candidates_for_date` — event-driven single-date candidate generation reusing backtest_engine._run_event_driven. ShadowHarness._find_candidates now calls it. Platform is functional — any promoted strategy with event-driven entry can generate real research-desk trades. Dedup against open shadow_trades for the strategy's desk.
- **`/api/platform/*` endpoints** (Task 12b): 5 GET (strategies, detail, backtest-results, backtest-trades, promotion-events) + 3 POST (backtests async kickoff, promotions with 40-char justification + two-step 24h delay for production, demotions with 20-char reason).
- **`/research-platform` dashboard page** (Task 12a): 4 sections — strategy registry table with status badges, expandable detail with YAML spec + backtest history grid + promotion events log, equity curve modal using BacktestEquityChart (Recharts LineChart). Empty state renders cleanly.
- **`PlatformStatusWidget` on home dashboard** (Task 12d): compact status card with strategy counts per state, "ready for approval" nudge, last backtest timestamp. Returns null when no strategies exist.
- **Telegram platform events** (Task 12e): `notify_backtest_complete`, `notify_shadow_gate_ready` (dedup per strategy within 24h), `notify_strategy_promoted`, `notify_strategy_demoted`. All prefixed `[RESEARCH]`. Send failures logged, never raised.
- **Python plugin strategy interface** (Task 2): `src/platform/strategy_plugin.py` (StrategyPlugin ABC + Candidate dataclass) + `src/platform/plugin_registry.py` (register/get/list). Interface-only; plugin execution wiring is v0.24.1.
- **`docs/platform/activation-guide.md`** (Task 13): operator walkthrough from YAML spec to production promotion.

### Deferred to v0.24.1
- **Tier 7 correlation monitoring**: `correlation.py` (Spearman/Pearson/exceedance), `factor_decomp.py` (Carhart 4 + QMJ), `change_detection.py` (PELT), `alerting.py` (tiered). Only relevant once ≥2 concurrent strategies run concurrently. Filed as separate issues.
- **Python plugin execution wiring**: interface defined in v0.24.0 but backtest_engine + shadow_harness python_plugin path is v0.24.1 scope.
- **Historical EDGAR backfill 2019-2023** (issue #469): blocks first Lazy Prices promotion.
- **Scheduled-kind `find_candidates_for_date`**: event-driven path lives; scheduled returns [] with warning.

### Tests
- 22 new tests across Sprint 4 continuation.
- Full suite post-v0.24.0: ~2,141 passed + ~5 skipped + 1 pre-existing failure (`test_open_trades_excluded`).

### Non-negotiable gates — all green
- `_find_candidates` returns non-empty list when signal criteria met (test_find_candidates_returns_nonempty_on_signal_match)
- ShadowHarness.run_one_tick places bracket order via research client on real candidate (test_harness_run_one_tick_places_order_when_candidate_passes_limits)
- POST /api/platform/promotions rejects justification_note < 40 chars (test_promotion_rejects_short_justification)
- POST /api/platform/demotions rejects reason < 20 chars (test_demotion_rejects_short_reason)
- /research-platform renders empty state + populated state cleanly
- npm run build succeeds with no new warnings

## v0.24.0-alpha4 (Sprint 4 Tier 5 — Live Deployment Foundation)

### Added
- **Task 7a** — `src/shadow_trading/alpaca_clients.py`: per-desk `TradingClient` factory via `get_client(desk)`. Cached with double-checked locking. `verify_accounts_distinct()` raises if swing and research resolve to the same Alpaca account_number — catches silent cross-contamination at startup. Config via `desks.{desk}.alpaca_key_env` in `config/settings.example.yaml` (operator populates `settings.local.yaml` with real credentials).
- **Task 7b** — 17 public API functions in `src/shadow_trading/alpaca_adapter.py` accept `desk: str = "swing"` kwarg. `_get_trading_client(desk=...)` and `_get_data_client(desk=...)` dispatch to `alpaca_clients.get_client(desk)` when `desk != "swing"`. `place_live_entry` raises `ValueError` if `desk != "swing"` (live trading is swing-only compliance guardrail).
- **Task 7c (CRITICAL)** — `reconcile_paper_trades(desk=...)` and `reconcile_live_trades(desk=...)` filter `shadow_trades` by desk and route Alpaca queries through the per-desk client. Fixes the silent-404 risk when reconcile polls research positions on the swing Alpaca account. `reconcile_live_trades` raises `ValueError` on research desks.
- **Task 7d** — New `src/shadow_trading/reconcile_dispatch.py` with `reconcile_all_paper_trades()` — single source of truth for the "swing + every active research desk" loop. Used by `overnight.py`, `position_monitor.py`, `watch.py`. Per-desk failure isolation. `cli/commands.py:408` passes `desk="swing"` explicitly.
- **Task 7e** — `src/platform/shadow_harness.py` with `ShadowHarness` class. Per-strategy instance. `__init__` invokes `verify_accounts_distinct`. `run_one_tick(as_of)` does reconcile → candidates → pre-trade-limits → bracket placement → `shadow_trades` write with `desk='research_<strategy_id>'`. `halt()` closes only this strategy's positions. `get_open_positions()` filters by desk. `_find_candidates` is an MVP placeholder (v0.24.1 follow-up).
- **Task 7f** — `ShadowHarness._is_within_hard_limits` delegates to Sprint 3's `check_pre_trade_limits`. NAV from research Alpaca (fallback $100K). Positions desk-filtered. Blocked candidates skip `place_bracket_order`.
- **Task 9** — `WatchLoop._run_platform_shadow_tick` dispatches every strategy in `shadow_trading` state on its own `shadow_cadence_seconds` (default 600s). Interval-gating pattern (not inline). Failure isolation — one strategy's crash does not kill swing. `_last_platform_tick` dict in `__init__`; cleared on `_reset_daily_state`. Outer loop calls `_safe_run("platform shadow tick", ...)` once per cycle.
- **Task CC** — `src/platform/cost_calibration.py` with `calibrate_from_swing_history()`. Computes median `entry_slippage_bps` / `exit_slippage_bps` from closed swing trades. Falls back to hardcoded 3 bps when sample < 10. Non-negotiable gate: calibrated value within 30% of the hardcoded default.

### Tests
- 35 new tests across 7 test files. Non-negotiable gates all pass:
  - `test_harness_reconcile_uses_research_client`
  - `test_harness_bracket_monitor_uses_research_client`
  - `test_verify_accounts_distinct_raises_on_same_account`
  - `test_harness_halt_closes_only_this_strategy_positions`
- Full suite post-Sprint-4-Tier-5: ~2,095 passed + ~4 skipped. Pre-existing failures unchanged.

### Platform stays inert at merge
- Zero strategies in `shadow_trading` state at merge time. No live behavior change until the operator promotes a strategy.
- `SELECT COUNT(*) FROM shadow_trades WHERE desk != 'swing'` returns 0 before and after merge.
- `_find_candidates` stub logs `[HARNESS <id>] _find_candidates: returning []` — platform is correctly inert.

### Deferred to `v0.24.0-alpha5` / `v0.24.1`
- Tier 6 (dashboard `/research-platform` page, action buttons, PlatformStatusWidget, Telegram events) — visibility layer; not load-bearing
- Tier 7 (correlation measurement, Carhart+QMJ factor decomp, PELT change detection, tiered alerting) — only relevant once ≥2 research strategies run concurrently
- Tier 8 (Python plugin strategy interface, final docs sweep + activation-guide.md) — CUT-CANDIDATE per spec
- `_find_candidates` full integration (expose `signal_eval.find_candidates_for_date`) — required before any real shadow trades can be placed

### Operator prerequisites before activating any research strategy
1. Create a SECOND Alpaca paper account with distinct credentials
2. Export `ALPACA_RESEARCH_API_KEY` / `ALPACA_RESEARCH_API_SECRET` in the NSSM service env (via `nssm set ArcisWatchLoop AppEnvironmentExtra ALPACA_RESEARCH_API_KEY=... ALPACA_RESEARCH_API_SECRET=...`)
3. Flip `desks.research.enabled: true` in `config/settings.local.yaml`
4. Restart watch loop → `verify_accounts_distinct()` runs at first ShadowHarness init and fails-fast if mis-configured
5. Wait for `_find_candidates` full integration in v0.24.1 before promoting any strategy to `shadow_trading`

## v0.24.0-alpha3 (Sprint 3 of 4 — Defensive Dashboard + Hard Exposure Limits)

### Added
- **Task 12c — Defensive desk filtering.** `/api/shadow/*` endpoints (`open`, `closed`, `sharpe-attribution`, `metrics`, `account`) accept optional `?desk=` query param: absent/`swing` → swing-only (backward compat), `all` → aggregate, `research_*` → SQL LIKE wildcard, exact match otherwise. `Dashboard.jsx` gets a desk-filter dropdown populated at render time from the new `GET /api/shadow/desks` endpoint (returns distinct desks currently in `shadow_trades`).
- **Task 11b.1 — Correlation schema.** Two new tables registered: `correlation_matrices` (long-form daily Spearman/Pearson/neg_exceedance snapshots) and `factor_loadings` (rolling Carhart 4 + QMJ regression outputs). Both `sync_to_postgres=True`, `sync_mode='incremental'`. No writes this sprint — Sprint 4 correlation monitor populates.
- **Task 11b.4 — Hard exposure limits.** New `src/platform/risk/exposure_limits.py` with `check_pre_trade_limits(ticker, shares, price, positions, nav, db_path) -> (allowed, reason)`. HARD_LIMITS: 6% single-name / 25% sector / 1.5× gross / 8% book drawdown circuit breaker. Book drawdown computed live from `shadow_trades` cumulative pnl_pct — no persistent breach flag needed; "no auto-reset" enforced by the math itself. SOFT_LIMITS stubbed for Sprint 4 (correlation + factor + vol ratio). `get_soft_limit_breaches()` returns empty until Sprint 4 wires correlation data.

### Tests
- 37 new tests across `tests/platform/risk/test_exposure_limits.py` (13), `tests/test_correlation_schema.py` (9), `tests/test_shadow_desk_filter.py` (15). Non-negotiable gates all pass: single-name / sector / drawdown blocks, 4 desk-param semantics on `/api/shadow/sharpe-attribution`, correlation tables sync-to-postgres incremental.

### Notes
- `check_pre_trade_limits` is NOT yet wired into `src/shadow_trading/executor.py` — that's Sprint 4 (per spec line 230). This sprint ships the pure function + tests; integration path follows.
- Sector-concentration test uses NVDA instead of GOOGL because Alphabet was reclassified from Technology to Communication Services in GICS September 2018.
- Two post-sprint follow-ups tracked as GitHub issues: #475 (wire PBO + OOS_efficiency into `check_promotion_gate` evidence) and the existing #471 (v0.24.2 refactor sprint for 4 grandfathered violations).

## v0.24.0-alpha2 (Sprint 2 of 4 — CSCV + Walk-Forward + Promotion Pipeline)

### Added
- `src/platform/rigor/cscv.py` — Combinatorially Symmetric Cross-Validation / Probability of Backtest Overfitting (S=16 default; Bailey-Borwein-López de Prado-Zhu 2014).
- `src/platform/rigor/walkforward.py` — rolling walk-forward (Pardo 2008; default 3y train / 1y test; OOS_efficiency = OOS_SR / IS_SR; flags overfit if < 0.30).
- `src/platform/rigor/trials.py` — global trials registry with N_eff counter + empirical V[SR] estimator (fallback to 0.02/250 when <20 trials).
- `src/platform/promotion.py` — 5-state lifecycle (proposed → backtested → shadow_trading → production, plus deprecated) with DSR + PBO + OOS_efficiency gates, promote/demote/pause, ≥40-char justification enforcement on manual promotions, ≥20-char reason enforcement on demotion.
- Three new SQLite tables: `strategy_registry`, `strategy_promotion_events`, `trials_registry`.
- Three new `shadow_trades` columns: `desk` (default 'swing'), `research_thesis`, `strategy_spec_hash` + `idx_shadow_trades_desk` index. Migration backfills all 85 existing rows to `desk='swing'` via DEFAULT.

### Fixed (v0.24.0-alpha2.1 hotfix — commits 6055952 + bbf0a71 + 86a46fc)
- `src/platform/signal_eval.py` — `_query_event_rows` rejected the spec's `universe.tickers: "sp100"` string alias; `_resolve_universe` now dispatches string aliases via `_UNIVERSE_ALIASES`. Fixes Lazy Prices returning 0 trades on the production DB (H2).
- `src/platform/features/cosine_similarity.py` — `cosine_similarity_yoy` now falls back to parsing sections from `full_text` when `sections_json` is NULL (the EDGAR backfill populated `full_text` but never derived sections). Fixes cosine=None for every event (H1).
- `src/platform/signal_eval.py` — `_evaluate_event_signal` was hardcoded to AND logic; now honors `combinator` parameter so `combinator: any` fires on OR logic as spec declares. Fixes SBUX-style suppression when one-of-two filters passes (H4).
- `src/config/__init__.py` — DB_PATH was relative (`"ai_research_desk.sqlite3"`); now anchored to `Path(__file__).resolve().parent.parent.parent / "ai_research_desk.sqlite3"` with optional `ARCIS_DB_PATH` env override. Prevents CWD-dependent DB resolution that masked the H1/H2/H4 bugs during Sprint 1 review.
- `src/platform/promotion.py::check_promotion_gate` — now reads real N_eff + V from `trials_registry` rather than the stored (null-fallback-computed) `deflated_sharpe` column. Adds `RuntimeError` guard if V is None so null fallback can't silently fire in production.

### Tests
- 55+ new tests across `tests/platform/rigor/` + `tests/platform/` + `tests/test_schema_desk_columns.py` + `tests/test_config_db_path.py`. Non-negotiable gates pass: PBO rejects overfit (PBO>0.8), PBO accepts stable (<0.2), walk-forward OOS efficiency computed + flags overfit, shadow_trades 85-row backfill, justification-note enforcement, trials_sr_variance plumbing (no null fallback), trials_registry counts every backtest.

### Known issues
- EDGAR data is 2024-only (collector wired late 2025). Lazy Prices e2e test pins on `n_trades >= 1` rather than `>= 50`. Historical 2019-2023 backfill tracked in GitHub issue #469 (v0.24.x; blocks first Lazy Prices promotion to shadow_trading but non-blocking for Sprints 3/4).
- DSR paper-example test split into two V-values (V=0.5/250 for DSR=0.9004, V=0.046/250 for SR*₀_ann=0.5429) because the paper's two claimed outputs are mutually inconsistent under any single V (documented in `src/platform/rigor/dsr.py` docstring; source PDF password-protected — v0.25 followup).

## [Unreleased] → v0.24.0-alpha1 (Sprint 1 of 4 — Platform Foundation + DSR Gate)

### Added

- `src/platform/` package: strategy spec loader (Task 1), OHLCV data adapter (Task 3), basic metrics + survivorship haircut (Task 5a), Deflated Sharpe Ratio (Task 5b), strategy-agnostic backtest engine + signal_eval (Task 4), backtest CLI + SQLite persistence (Task 6), Lazy Prices feature providers (Task 11).
- First YAML strategy spec: `lazy_prices_v1` (Cohen-Malloy-Nguyen 2020) at `src/platform/specs/lazy_prices_v1.yaml`.
- Two new SQLite tables via schema registry: `backtest_results`, `backtest_trades` (registry now at 56 tables total).
- `scripts/run_backtest.py` CLI runner — invocable as `python scripts/run_backtest.py --strategy lazy_prices_v1 --start YYYY-MM-DD --end YYYY-MM-DD --output-format pretty`.
- `scripts/backfill_edgar_fulltext.py` backfill script (operator runs ~20-37 min SEC fetch; do not automate).

### Fixed

- `src/data_collection/edgar_collector.py::_fetch_filing_text` — corrected URL base to `www.sec.gov/Archives/...` (was `data.sec.gov/Archives/...` which 404s), replaced directory-scraping regex with submissions-API `primaryDocument` lookup. Root cause of 0/3362 EDGAR coverage (Task 0).

### Tests

- 44 new tests across 7 new test files (`test_dsr.py`, `test_backtest_engine.py`, `test_backtest_persistence.py`, `test_data_loader.py`, `test_lazy_prices.py`, `test_metrics.py`, `test_strategy_spec.py`). DSR paper-example reproduction gate PASSES. Two hand-computed backtest validation tests PASS (scheduled + event-driven modes).

### Notes

- `docs/research/deep-research/backtest-rigor-retrofit-plan.pdf` is password-protected; the DSR paper example was split into two independent assertions (one using V=0.5/250 for DSR=0.9004; one using V=0.046/250 for SR*_0_ann=0.5429) because the paper's stated outputs are mutually inconsistent under any single V. See `src/platform/rigor/dsr.py` module docstring and Plan Issue B.
- `src/data_collection/edgar_collector.py` now 413 lines (exceeded 400-line guardrail; Task 0 repair added ~27 lines). `_fetch_filing_text` is 68 lines (exceeded 60-line cap). Both are NEW violations introduced by Sprint 1 Task 0 — grandfathering or a follow-up split is needed before merging to main.

## [v0.23.4] - 2026-04-16 — Telegram Refresh: richer trade pings + periodic stats pulses

Long overdue operator-experience pass on the notification layer. The
`notify_trade_opened` / `notify_trade_closed` pings now carry sector,
regime, VIX, conviction, R:R, MFE/MAE, excess vs SPY, and slippage —
everything an operator needs to evaluate a fill without opening the
dashboard. Three new stats pulses (7:45, 12:00, 16:05 ET) give
trade-count + win rate + PnL + excess-Sharpe across today / 7d / 30d /
all-time, so performance is visible throughout the day. Coverage gaps
from today's new work (1-min bar collection, attribution resolver,
stress test) are filled with dedicated notifications.

### Added

- **`notify_trading_stats_update(stats, label)`** — formatted 4-window
  summary sent 3× per weekday (pre-market, midday, post-close). Silent
  on empty DB.
- **`src/journal/stats.py`** — `compute_window_stats` / `compute_all_window_stats`
  helpers that aggregate closed `shadow_trades` (excluding open +
  quarantined) across `today` / `7d` / `30d` / `all_time`. Excess-Sharpe
  shown only once ≥10 closed trades in a window.
- **`notify_1min_bar_collection`** — nightly confirmation from the
  Phase B overnight handler (bars, tickers, empty %, storage MB).
- **`notify_attribution_resolve_complete`** — resolved count + pending
  remaining, posted after the 4:30 PM ET resolver job.
- **`notify_stress_test_complete`** — scenario pass/fail summary, posted
  after the model-version-triggered 7 PM re-run.
- **`maybe_stats_pulse`** — new DAYTIME handler registered via
  `_register_default_handlers` alongside the 14 overnight handlers. Three
  done-flags (`_stats_{premarket,midday,postclose}_done`) reset daily.

### Changed

- **`notify_trade_opened`** — extended with optional `sector`,
  `regime_at_entry`, `vix_at_entry`, `concurrent_positions`,
  `llm_conviction` kwargs. Existing callers unchanged (all kwargs
  default to None; rendering is graceful when fields missing).
  `scan_service.py` caller now passes the enriched fields it already
  has from the feature row + current open-position count.
- **`notify_trade_closed`** — extended with optional `sector`, regime
  transition, `mfe_pct`, `mae_pct`, `excess_return`,
  `spy_return_over_hold`, `drawdown_from_mfe`, `entry_slippage_bps`,
  `exit_slippage_bps`. `executor.py` caller passes the full
  `shadow_trades` row so all fields render. Extracted
  `_format_closed_extras` helper to keep `notify_trade_closed`
  under the 60-line cap.
- **`src/scheduler/watch_handlers.py`** — added `DAYTIME_HANDLERS` list
  + `ALL_HANDLERS = OVERNIGHT_HANDLERS + DAYTIME_HANDLERS`.
  `_register_default_handlers` now registers all 15.
- **`src/scheduler/overnight.py`** — `run_1min_bar_collection` fires
  the new notification; new `run_attribution_resolution_and_notify`
  wrapper calls the resolver + posts the summary. `run_stress_test`
  now posts the pass/fail summary at the end.
- **`src/scheduler/watch.py`** — attribution-resolve branch delegates
  to `run_attribution_resolution_and_notify`; new stats-pulse done-flags
  initialized in `__init__` and reset in `_reset_daily_state`.

### Added (tests)

- **`tests/test_journal_stats.py`** — 9 tests covering empty DB,
  open-trade exclusion, quarantined exclusion, window boundaries
  (today / 7d / 30d / all_time), win rate math, excess-Sharpe minimum
  threshold, NULL excess_return handling, + 2 smoke tests for the
  notification formatter.
- **`tests/test_watch_handlers.py`** +6 `maybe_stats_pulse` tests: skip
  on weekend, fire at 7:45 / 12:00 / 16:05, idempotent per window,
  no-op between windows.

### Verified

- 85 tests pass across the relevant suites (registry, handlers, bootstrap,
  resilience, import, journal stats, repo structure).
- Frontend builds clean.
- `notify_trade_closed` now 37 lines — helper extraction brings it well
  under the 60-line cap.

## [v0.23.3] - 2026-04-16 — Hotfix: resolve_pending_outcomes future-window filter

Fourth bug from the Task 1 operational sweep — the `reresolve_attribution.py`
hotfix correctly skipped future-window rows during the *reset* step, but
the downstream `resolve_pending_outcomes()` function itself had no date
filter, so it still picked up every `pending` row including those whose
7-day outcome window is in the future. Each one caused a noisy
`YFPricesMissingError` in the logs and wasted ~0.5s on a dead yfinance call.

Observed on 2026-04-16 running `scripts/reresolve_attribution.py`: 180
fresh `pending` rows from today generated ~180 sequential yfinance error
logs. No data corruption — rows stay `pending` — but the watch loop's
nightly 4:30 PM ET resolution job would have reproduced the same error
storm indefinitely until all rows aged past their 8-day window.

### Fixed

- **`src/attribution/logger.py::resolve_pending_outcomes`** — added
  `AND DATE(scan_timestamp, '+8 days') <= DATE('now')` to the SELECT so
  rows whose outcome window is still in the future are skipped. Matches
  the same filter already present in `scripts/reresolve_attribution.py`.

### Added

- **`tests/attribution/test_resolver.py::test_resolve_pending_outcomes_skips_future_window_rows`**
  — regression test seeding 3 rows (old-resolvable / fresh-future /
  boundary-edge at exactly 8 days ago) and asserting the SELECT filter
  passes only the 2 elapsed-window rows to `_resolve_one_row`. Uses
  `patch()` on `_resolve_one_row` so no yfinance calls are made — the
  test isolates the SELECT filter contract.

### Authority

Error storm observed live during the `scripts/reresolve_attribution.py`
run on 2026-04-16; root-caused as a 4th operational bug that slipped
past the Task 1 audit.

## [v0.23.2] - 2026-04-16 — Asyncio Refactor Phase B (overnight extraction) + Phase C (tests)

First wave of `_run_sync_body` decomposition: the 14 overnight-schedule
tasks now live in a new module and run via the handler dispatch path.
Zero behavior change — done-flag semantics preserved, handler firing
times match the pre-refactor `elif` chain. `_run_sync_body` shrank from
740 → 631 lines; watch.py dropped from 2,041 → 1,941 lines (below the
pre-refactor baseline of 2,039).

### Added

- **`src/scheduler/watch_handlers.py`** (229 lines) — 14 module-level
  `maybe_<name>(watch, now)` handlers extracted from the
  `elif self.overnight and not self._is_market_open(now):` branch of
  `_run_sync_body`. Each checks its time window + done-flag and calls
  `watch._safe_run(...)`. `OVERNIGHT_HANDLERS` list exports them in
  registration order.
- **`HandlerRegistryMixin._dispatch_sync`** — sync-context dispatch so
  the `_run_sync_body` worker thread can fire handlers without crossing
  event-loop boundaries. Coroutine handlers get wrapped in `asyncio.run`;
  sync handlers run inline. Same exception contract as `_dispatch`.
- **`WatchLoop._register_default_handlers`** — single entry point called
  once at startup (between `_check_row_counts()` and the IB cold-storage
  banner) that `functools.partial(handler, self)`-binds each handler in
  `OVERNIGHT_HANDLERS` and registers on `on_tick`.
- **`tests/test_watch_handlers.py`** (25 tests) — per-handler unit tests
  (time window, done-flag respect, weekday gating, chained calls) plus
  integration tests: `_register_default_handlers` binds all 14 in the
  correct order, `_dispatch_sync` fires each handler at the right tick,
  and double-dispatch at the same tick is idempotent.
- **`tests/test_watch_handler_registry.py`** gains 4 `_dispatch_sync`
  tests (sync-handler inline execution, async-handler asyncio.run wrap,
  exception swallowing, registration-order preservation).

### Changed

- **`src/scheduler/watch.py::_run_sync_body`** now calls
  `self._dispatch_sync("on_tick", now)` once per tick, right after the
  midnight daily-state reset. The entire `elif self.overnight and not
  self._is_market_open(now):` branch (lines 1502-1627, 116 lines) is
  removed — its work is now done by the 14 registered handlers. The
  "overnight mode" heartbeat log line is omitted (the watchdog file
  heartbeat already covers the liveness signal).
- **`config/known_violations.json`** — `_run_sync_body` grandfather
  entry updated from 740 → 631 lines to reflect the size reduction.

### Verified

- All 13 existing `test_watch_*` tests pass unchanged.
- 16 handler-registry tests pass (12 Phase A + 4 new `_dispatch_sync`).
- 25 watch_handlers tests pass.
- 15 `test_repo_structure` tests pass.
- Frontend builds clean in 603ms.
- `WatchLoop(...).run()` signature preserved — NSSM / `src/cli/commands.py`
  callers unchanged.

### Not in this branch (queued for follow-up Phase B-continuation)

~20 remaining inline blocks in `_run_sync_body` — market-hours scans
(Tier 1-4), EOD recap cluster, digest schedule (4 windows),
Ollama/council/fundamentals, Saturday/Sunday reports, IB health
check, Telegram polling, earnings warning, action reminders. The
pattern is proven; extracting them is mechanical.

### Authority

`docs/sprints/sprint-asyncio-handler-refactor.md` Phase B (14 of 30+
extractions) + Phase C (mock-clock integration test for the extracted
subset).

## [v0.23.1] - 2026-04-16 — Asyncio Handler Refactor Phase A

Structural refactor of `src/scheduler/watch.py` — introduces an asyncio
event loop + handler registry without changing any observable behavior.
Foundation for Phase 6 intraday streaming (TradingStream, StockDataStream).

### Added

- **`src/scheduler/handler_registry.py`** (new, 69 lines) — `HandlerRegistryMixin`
  providing `run()` / `run_async()` / `on(event)` / `_dispatch(event, ...)`.
  Sync handlers are wrapped in `asyncio.to_thread` so they never block
  the event loop; coroutine handlers are awaited directly. Handler
  exceptions are logged and swallowed to match the `_safe_run` contract.
- **`tests/test_watch_handler_registry.py`** (new, 12 tests) — unit
  coverage for the registry: empty-start, decorator/direct-call
  registration, registration-order preservation, sync + async handler
  dispatch, exception isolation, unknown-event no-op, args/kwargs
  passthrough, `run()`→`run_async()`→`_run_sync_body()` delegation.
- **`docs/research/async-watch-loop-handler-pattern.md`** — handler
  pattern documentation as a public API for future developers, with
  canonical event names (`on_tick`, `on_fill`, `on_minute_bar`, etc.)
  and the Phase B / C / Phase 6 roadmap.

### Changed

- **`src/scheduler/watch.py::WatchLoop`** now inherits
  `HandlerRegistryMixin`. The pre-refactor `run()` method is renamed to
  `_run_sync_body()` and unchanged — Phase B will carve its 740 lines
  of time-window `if/elif` blocks into `_maybe_*` handlers registered
  on `on_tick`. Net +2 lines on `watch.py` (2,039 → 2,041) — the
  mixin keeps infrastructure out of the already-bloated host file.
- **`config/known_violations.json`** — grandfather entry updated from
  `run` (454 lines) to `_run_sync_body` (740 lines) to reflect the
  rename. Pre-existing debt carried forward, not worsened.

### Verified

- All 13 existing `test_watch_*` tests pass unchanged (zero behavior
  change).
- 12 new registry tests pass.
- 15 `test_repo_structure.py` tests pass (docstring, importability,
  60-line cap, 400-line cap, no-legacy-alpaca-SDK).
- NSSM / `src/cli/commands.py` callers unchanged — `WatchLoop(...).run()`
  signature preserved.

### Not in this sprint (explicit out-of-scope per spec)

- Phase B — extracting the 30+ time-window blocks from `_run_sync_body`
  into `_maybe_*` handlers registered on `on_tick`. Queued as
  `refactor/asyncio-phase-b-handler-extraction`.
- Phase C — mock-clock integration test that advances a WatchLoop
  through 24h and asserts every existing task fires at the right ET
  time. Queued as `refactor/asyncio-phase-c-mock-clock-integration`.
- Converting existing `_run_*` methods to `async def`. They stay sync,
  wrapped via `asyncio.to_thread` at dispatch time.
- Any streaming subscription (`TradingStream`, `StockDataStream`) —
  that is Phase 6.

### Authority

`docs/sprints/sprint-asyncio-handler-refactor.md`, drafted on
`docs/asyncio-refactor-spec` branch. This sprint executes Task 1 of
the spec's 5-task plan; Tasks 2-5 (extraction, dispatch switch, mock-clock
tests, docs) are follow-up branches.

## [v0.23.0] - 2026-04-16 — 1-Minute Bar Collection (Phase 6 Foundation)

Lays the data foundation for Phase 6 intraday-desk feasibility work per
`docs/research/deep-research/intraday-desk-feasibility-prompt.md`.
yfinance only exposes ~7 trading days of 1-minute history, so we begin
storing bars now to study historical microstructure when the time comes.

### Added

- **`minute_bars` table** (schema registry) — composite PK `(ticker, timestamp)`;
  OHLCV (REAL) + volume/trade_count (INTEGER); synced to Postgres
  incrementally via `sync_time_column="timestamp"`. ~2.3 MB/day / ~600 MB/yr.
- **`scripts/collect_1min_bars.py`** — yfinance-backed nightly collector
  for S&P 100. Rate-limited at 0.3s/ticker (≈31s wall time). CLI flags:
  `--date YYYY-MM-DD`, `--days N` (backfill up to 7d), `--dry-run`.
  Idempotent via `INSERT OR REPLACE` on the composite PK. Flattens
  yfinance MultiIndex columns (same fix pattern as SD#41 D2) and coerces
  NaN prices/volumes to NULL.
- **Overnight schedule wire-up** (`src/scheduler/watch.py`) — new
  `_1min_bar_collection_done` flag, reset daily, fires at hour 23 minute
  ≥30 ET (after enrichment precache, before the midnight flag reset).
  7-days/week like the other network-only collectors; empty weekend
  responses handled gracefully.
- **`tests/test_collect_1min_bars.py`** — 8 tests covering schema
  registration, MultiIndex flatten, NaN coercion, empty-response path,
  idempotent upsert, dry-run semantics, rate-limiting, and the
  previous-trading-day walker.

### Changed

- **`src/sync/render_sync.py`** — added `open`, `high`, `low`, `close`
  to `_REAL_COLUMNS` and `volume`, `trade_count` to `_INTEGER_COLUMNS`
  so `minute_bars` rows coerce cleanly on the Postgres side.

### Authority

Phase 1 decision #3 of `docs/research/deep-research/intraday-desk-feasibility-report.md` — begin storing 1-min bars now.

## [v0.22.1] - 2026-04-16 — alpaca-py Canonicalization (audit + guardrail)

Verification sprint — the `alpaca-py` migration was already complete; this
sprint documents the audit, tightens the version pin, and adds a CI
guardrail to prevent accidental reintroduction of the deprecated
`alpaca_trade_api` SDK. No runtime behavior changes.

### Changed

- **`requirements.txt`** — floor raised `alpaca-py>=0.30` → `alpaca-py>=0.43`
  to match the locally-installed/tested version and narrow the window
  for CI/dev drift.

### Added

- **`tests/test_repo_structure.py::test_no_legacy_alpaca_trade_api_imports`**
  — AST-walking guardrail over `src/` and `tests/` that fails if any
  `import alpaca_trade_api` or `from alpaca_trade_api ...` appears.
- **`docs/research/alpaca-py-current-best-practices-audit.md`** — per-call-site
  audit of `alpaca_adapter.py` (10 imports) and `executor.py` (3 imports)
  against the modern SDK idioms. Verdict: zero bugs; two improvements
  flagged as follow-up tickets (typed `APIError` handling, `client_order_id`
  for idempotency).
- **`docs/research/alpaca-py-intraday-streaming-gap.md`** — Phase 6 pre-work
  mapping `TradingStream` / `StockDataStream` integration points into the
  post-asyncio-refactor watch loop. No code; reference doc for the
  Phase 6 sprint.

### Verified

- Zero `alpaca_trade_api` references across `src/`, `tests/`, and all
  `requirements*.txt`.
- Zero streaming usage (`TradingStream` / `StockDataStream`) in `src/`
  — Phase 6 surface is intentionally empty.
- Installed `alpaca.__version__ == 0.43.2`.

### Authority

`docs/sprints/sprint-alpaca-py-migration.md`, drafted on the
`docs/alpaca-py-migration-spec` branch.

## [v0.22.0] - 2026-04-16 — Attribution Resolver MultiIndex Fix + Doc Sweep (SD#41 REVISED / D2 follow-up)

Ships the D2 follow-up fix (yfinance MultiIndex bug that corrupted 1,600
attribution resolutions) plus a comprehensive documentation sweep to
reflect the 4 merges from 2026-04-16 (v0.18.0 IB cold storage, v0.19.0
SPY excess instrumentation, v0.20.0 regime/sector diagnostic, v0.21.0
earnings filter hard block).

### Fixed — Part 1: Attribution resolver

- **`src/attribution/logger.py::resolve_pending_outcomes`** — flatten
  yfinance MultiIndex columns before building the OHLCV dict list.
  Before: `bar.get("Low", ...)` missed the tuple-keyed column, returned
  default `0`, and tripped the stop-first branch on day 1 of every
  resolution. After: `data.columns = data.columns.get_level_values(0)`
  normalizes to string keys so `bar.get("Low")` resolves correctly.
  `simulate_mechanical_outcome` itself is unchanged (kept pure-logic).

### Added — Part 1

- **3 new columns on `attribution_trades`:**
  - `resolution_version` (TEXT, indexed) — version tag for resolution
    logic. `'v1_multiindex_bug'` marks the buggy pre-fix rows;
    `'v2_fixed'` marks post-fix re-resolutions.
  - `ranker_only_outcome_v1` (TEXT) — archive of pre-fix outcome.
  - `ranker_only_pnl_pct_v1` (TEXT) — archive of pre-fix pnl_pct.
- **`scripts/reresolve_attribution.py`** — idempotent re-resolution
  script. Snapshots v1 values, resets bug-tagged rows to 'pending',
  calls the fixed resolver, tags newly-resolved rows as 'v2_fixed'.
  `--dry-run` flag snapshots only (no writes beyond the archive).
- **`tests/attribution/test_resolver.py`** — 6 regression tests covering
  the simulator (flat columns, timeout, loss) and the resolver
  data-shape contract (MultiIndex flatten, empty yfinance response,
  flat-columns compat).

### Re-resolution

1,600 `v1_multiindex_bug` rows were re-resolved under `v2_fixed`. V1
values preserved in archive columns for forensic comparison. The stop-
distance fingerprint that was universal in v1 is now absent in v2 (aside
from a small legitimate-stop minority). Outcome distribution shows real
`win` / `loss` / `timeout` spread, consistent with bull-market yfinance
paths over 7-day windows.

### Changed — Part 2: Doc Sweep

- **`MASTER.md` Section 1**: release line now v0.22.0; tech-stack trading
  line notes IB dormant per SD#41.
- **`MASTER.md` Section 2**: closed-trade count 18 → 85; test count 1,801
  → 1,852; dashboard pages 24 → 25; research docs 91 → 107; sprint docs
  43 → 57; PEAD entry removed (SD#3 eliminated); new "Attribution
  resolver FIXED" line.
- **`MASTER.md` Section 2 (new subsections)**: Forensic Analysis Status
  (D1/D2/D3 progress, Stage 1/2 OOS gates) and Permanent Methodology
  Guardrails (SD#41 REVISED).
- **`MASTER.md` Section 2 Diagnostic D2 Status**: CLOSED — citation
  freeze LIFTED for `resolution_version='v2_fixed'` rows.
- **`MASTER.md` Section 5**: heading "40 confirmed" → "41 confirmed";
  SD#3 marked ELIMINATED (PEAD dead); SD#17 marked COMPROMISED and then
  FIXED v0.22.0; SD#36 phase gate redefined; new SD#41 REVISED entry
  supersedes prior SD#41 trade-lifecycle synthesis.
- **`MASTER.md` Section 6**: Phase 1→2 gate redefined — excess-Sharpe
  ≥ 0.5 at t ≥ 2.0 over 150 OOS trades (raw Sharpe gate deprecated).
- **`MASTER.md` Section 8**: Revenue milestones shifted 6-12 months per
  SD#41 REVISED. Intraday desk feasibility research flagged.
- **`MASTER.md` Section 11**: Active Queue rewritten as SD#41 REVISED
  diagnostic-first plan. Prior queue moved to "Completed Sprints
  (historical)" subsection. New Research Queue subsection added.
- **`frontend/src/pages/Roadmap.jsx`** — Phase 1 gate metrics use
  excess-Sharpe + t-stat; IB activation row updated to reference cold
  storage + new gate.
- **`README.md`** — version badge v0.22.0; phase badge "diagnostic";
  test-count badge 1,852; Current Status reflects 85 closed + D1/D2/D3
  status + new Phase 1→2 gate.
- **`RELEASES.md`** — v0.22.0 entry with before/after + re-resolution
  stats.

### Authority

- Sprint spec: `docs/sprints/sprint-attribution-resolver-fix.md` (Part 1)
  + inlined doc sweep (Part 2 per user request)
- D2 audit: `docs/research/attribution-resolver-audit.md`
- Plan: `docs/research/SD-41-REVISED-diagnostic-first-plan.md`

## [v0.20.0] - 2026-04-16 — Regime & Sector Classifier Diagnostic (SD#41 REVISED / Sprint D3)

Closes the regime-NULL and sector-coverage gaps flagged in the forensic
report. No production code change — the enrichment bypass that caused
the 67% NULL `market_regime` was already fixed on 2026-04-14; this
sprint verifies coverage, adds regression tests so it can't silently
regress, backfills `realized_sector` to 100%, and clears up the label
vocabulary confusion between the regime classifier and the traffic
light.

### Diagnosed

- **`recommendations.market_regime` NULL anomaly** — classified as
  hypothesis (c) schema-recent scanner bypass. Per-day NULL rate cuts
  over cleanly at 2026-04-09 (100% -> 0%), matching the
  `attach_post_scan_features` deployment. 1,076 pre-2026-04-09 rows
  left as `NULL` accurately; they legitimately predate the fix.
- **Label-vocabulary confusion** — the codebase carries three distinct
  label systems: 5-state `compute_market_regime` (stored in
  `recommendations.market_regime`), 7-state `classify_regime`
  (canonical going forward), 3-state `traffic_light` (stored in
  `shadow_trades.regime_at_entry` despite the misleading column name).
  All three mapped in `docs/research/regime-classifier-audit.md`.
- **`recommendations.sector_context` 100% NULL** — documented as
  deprecated. Use `shadow_trades.realized_sector` or ticker-lookup via
  `data/reference/sp100-gics-lookup.csv` instead.

### Added

- **`tests/features/test_enrichment_coverage.py`** — 4 regression tests
  that grep the three scanner files for the `attach_post_scan_features`
  literal, plus a behavior test asserting `classify_regime` returns a
  label from the canonical 7-state set for representative inputs.
- **`docs/research/regime-classifier-audit.md`** — 243-line audit
  with label-source map, per-day cut-over evidence, sector backfill
  status, canonical vocabulary policy, and regression-protection summary.

### Changed

- **`data/shadow_trades.realized_sector` coverage now 100%** (226/226
  rows, zero NULL). D1 had backfilled the 85 closed rows; this sprint
  extended the backfill to the remaining 143 open/failed/pending rows
  (all S&P 100 tickers; GICS lookup had no gaps).

### Unchanged production code

No `src/` changes. The `attach_post_scan_features` call is present in
all three scanner paths in current main (`scheduler/universe_scanner.py`,
`services/scan_service.py`, `services/mr_scan_service.py`) and the bug
described in `src/features/enrichment.py:8-14` was remediated
2026-04-14.

### Deferred (out of scope)

- Regime classifier v2 / 7-state DB migration (SD#35, separate sprint).
- Renaming `shadow_trades.regime_at_entry` to `traffic_light_at_entry`
  (schema rename; requires data migration plan).
- Retroactively filling the 1,076 pre-2026-04-09 NULL rows (they
  accurately signal "enrichment not yet deployed").

### Authority

- Sprint spec: `docs/sprints/sprint-D3-regime-sector-diagnostic.md`
- Audit doc: `docs/research/regime-classifier-audit.md`
- Plan: `docs/research/SD-41-REVISED-diagnostic-first-plan.md`

## [v0.21.0] - 2026-04-16 — Earnings Filter Hard Block (SD#33 / Sprint H1)

Narrow scoring fix so trades are hard-blocked when earnings are scheduled
within ~7 trading days, regardless of the market-wide event risk score.
The earnings pipeline (scraper, lookup, scoring hook, risk governor, executor
tagging, dashboard field) was already fully built; the gap was a scoring-scale
mismatch. One-line threshold-override in `compute_event_risk_score` closes it.

### Fixed

- **`src/features/event_risk_score.py::compute_event_risk_score`** — earnings
  within 10 calendar days (~7 trading days, bounded by two weekends) now set
  `earnings_proximity = block_threshold` and floor `total_score` at
  `block_threshold`, guaranteeing `sizing_multiplier = 0.0` and triggering
  the existing `risk/governor.py:430` "Event risk hard block" reject path.
- `components["earnings_forces_block"]` (bool) is always present for
  downstream consumers, not just when earnings exist.

### The bug

Earnings <=2 days out added only +4 on a scale where hard-block threshold is
8. On calm market days (total_score < 4 before earnings), an earnings-imminent
ticker never crossed the threshold, and gap risk was unpriced. Per forensic
analysis, a non-trivial share of closed trades likely caught earnings
surprises mid-hold. Gap risk cannot be managed by stops, vol targeting, or
exits — only by not being in the position when earnings prints.

### Added

- **`tests/features/test_event_risk_earnings.py`** — 9 regression tests
  (core scenarios + parametric boundary at days_until=0/10/11 +
  earnings_forces_block key consistency when no earnings).
- **`tests/features/__init__.py`** — new test subdir.

### Changed

- **`tests/test_event_risk_score.py::test_compute_event_risk_score_adds_earnings_and_blocks`**
  updated to the new contract: `earnings_proximity = block_threshold` rather
  than the previous sliding +4/+2 schedule.

### Unchanged infrastructure (confirmed working — no rebuild)

- Nightly earnings scraper (`scripts/fetch_earnings_calendar.py`)
- Earnings lookup with yfinance fallback (`src/features/earnings.py`)
- Risk governor hard-block path (`src/risk/governor.py:430`)
- Executor earnings_adjacent flag (`src/shadow_trading/executor.py:570, 1934`)
- Schema `shadow_trades.earnings_adjacent` (INTEGER, default 0)

### Authority

- Sprint spec: `docs/sprints/sprint-H1-earnings-filter.md`
- Strategy Decision #33: MASTER.md Section 5, entry 33 (earnings 7-day
  exclusion zone; entry-exclusion layer now IMPLEMENTED, force-exit and
  post-earnings cooldown layers deferred)

## [v0.19.0] - 2026-04-16 — SPY-Matched Excess Instrumentation (SD#41 REVISED / Sprint D1)

Foundational alpha-vs-beta measurement. Every Sharpe metric can now
answer "real alpha, or just SPY drift?" Adds three columns to
`shadow_trades`, a SPY-benchmark utility, an idempotent backfill, a
dedicated API endpoint, and a Trade History lead panel. Redefines the
IB live-trading gate from raw Sharpe (trivially passed by bull-market
beta) to excess-return Sharpe.

### Added

- **3 columns on `shadow_trades`** (via `src/schema/registry.py`):
  - `spy_return_over_hold` (REAL) — SPY total return over the exact
    entry-to-exit date range, close-to-close, auto-adjusted
  - `excess_return` (REAL) — `pnl_pct - (spy_return * 100)`; positive
    means beat SPY over the same period
  - `realized_sector` (TEXT) — GICS sector from
    `data/reference/sp100-gics-lookup.csv`
- **`src/analytics/spy_benchmark.py`** — SPY return fetch via
  yfinance with fail-open semantics (`spy_return_over_range`,
  `excess_return`, `get_sector`)
- **`data/reference/sp100-gics-lookup.csv`** — 102 tickers mapped to
  11 GICS sectors; zero "Unknown" entries
- **`scripts/backfill_spy_excess.py`** — idempotent backfill for
  existing closed trades; `--dry-run` and `--force` flags
- **`/api/shadow/sharpe-attribution`** — primary metric endpoint
  with raw + excess Sharpe, 95% CIs, t-statistic, hit rate, and a
  verdict interpretation key (alpha_significant / alpha_suggestive /
  negative_alpha_* / alpha_not_demonstrated)
- **Trade History "Primary Metric" panel** — excess-Sharpe leads
  above the Today/Yesterday/7d/30d recency cards; raw Sharpe visible
  but demoted to footnote
- **`tests/analytics/test_spy_benchmark.py`** — 7 regression tests
  (pure-logic + mocked yfinance + sector lookup)

### Changed

- **IB live trading gate redefined:** excess-return Sharpe >= 0.5 at
  t >= 2.0 over 150 OOS trades. (Was raw Sharpe >= 1.0, trivially
  passed by SPY beta during a bull run.)
- **`src/journal/store.py::close_shadow_trade`** now centrally writes
  the three SPY fields on every exit (covers 5 executor call sites +
  3 reconcile call sites in one place). Fail-open: SPY yfinance
  exceptions never block trade close.
- **`src/sync/render_sync.py::_REAL_COLUMNS`** adds the two new REAL
  columns so the Postgres sync coerces them to float, not TEXT.

### Backfill

Live DB: 85/85 closed trades backfilled with SPY-matched excess
data, zero "Unknown" sectors. Second run of the backfill script
confirms idempotency (`updated=0, skipped_existing=85`).

### Rationale

Forensic analysis of 78 closed trades showed per-trade Sharpe 3.38
was mostly SPY beta during a bull run. Excess vs SPY = +0.039%,
t = 0.098 over 75 matched periods. Without this instrumentation we
cannot distinguish alpha from beta — every optimization decision
becomes directional noise chasing.

### Authority

- `docs/research/SD-41-REVISED-diagnostic-first-plan.md`
- Sprint spec: `docs/sprints/sprint-D1-spy-excess-instrumentation.md`
- Methodology: `docs/research/sharpe-attribution-methodology.md` (new)

## [v0.18.0] - 2026-04-16 — IB Cold Storage (SD#41)

Disable Interactive Brokers integration through Phase 1 while preserving
every line of IB code for fast reactivation. The entire change is gated by
a single `trading.ib_enabled` flag. Default Alpaca-only operation; flipping
the flag to `true` and restarting the watch loop restores prior behavior.

### Added

- **Top-level `trading.ib_enabled` flag** (default `false`) in
  `config/settings.example.yaml` and `config/settings.local.yaml`. Cross-cutting
  feature flag, distinct from `live_trading.broker` (which selects between
  brokers but no longer overrides the gate).
- **3 regression tests** (`tests/test_ib_cold_storage.py`) covering the
  fallback path, the explicit-opt-in escape hatch, and the default-config
  invariant.
- **Settings page Broker Status panel** — shows "Alpaca · Active" and
  "IB · Dormant (SD#41)" with a one-line note about reactivation.

### Changed

- **`broker_factory.get_live_broker`** falls back to Alpaca with a `[BROKER]`
  warning when `broker=ib` but `trading.ib_enabled=false`. IB
  instantiation code path is preserved verbatim, just gated.
- **`executor._select_paper_broker`** skips IB paper-routing entirely when
  cold-stored, so high-score paper trades stay on Alpaca.
- **`executor.open_shadow_trade` / `place_paper_exit`** skip IB shadow-log
  writes (entry + exit call sites) when cold-stored.
- **`reconcile.reconcile_paper_trades`** defers the IB position fetch when
  cold-stored. Tracked IB-broker positions (TGT, etc.) get a single
  `[RECONCILE]` info log per cycle indicating brackets resolve naturally.
- **`scheduler.watch.WatchLoop.run`** logs `[WATCH] IB integration dormant
  per SD#41. Alpaca-only mode.` once at startup, and short-circuits the
  IB Gateway health-check loop.
- **6 existing IB tests** now opt-in to the IB code path via
  `trading.ib_enabled=true` in their config dicts.

### Preserved (not deleted)

- `src/trading/ib_broker.py`, `src/trading/ib_shadow.py`
- `src/api/cloud_routes/ib_shadow.py`, `src/api/routes/ib_status.py`
- `ib_shadow_log` database table (queryable, just stops growing)
- `ib_async` dependency in `requirements.txt`
- All `live_trading.ib.*` config keys (host, port, paper_routing, shadow_mode)
- IBShadow.jsx component file (no route changes)

### Authority

- `docs/research/SD-41-defer-ib-integration.md`
- Sprint spec: `docs/sprints/sprint-ib-cold-storage.md`

## [v0.17.2] - 2026-04-15 — Hotfix: Grafana Cloud Loki MVP (SD#40) + NSSM service installer

Centralized log aggregation and 24/7 Windows service management, plus a
fix for the startup hang when Render Postgres is unreachable.

### Added

- **Grafana Cloud Loki integration** (SD#40). Raw HTTP handler
  `src/observability/loki_handler.py` ships logs to Grafana Cloud with zero
  new dependencies — uses `requests` only. QueueHandler+QueueListener
  non-blocking dispatch so the trading thread never waits on HTTP.
- **DedupFilter** attached to the Loki handler. Suppresses duplicate log
  messages within a 60s window to keep noisy repeats (e.g. `[SCHEMA]
  Created/verified 53 tables`) from consuming Grafana Cloud quota. File
  and console logging are unaffected.
- **Structured `ctx` → Loki labels.** `event` and `ticker` from the existing
  `extra={"ctx": {...}}` dict are promoted to Loki stream labels; all other
  ctx data rides along in the log-line text via `StructuredFormatter`.
- **New `ctx` tags** on two previously unstructured log lines:
  `shadow_trading.executor` trade-open (`event=trade_open`) and
  `shadow_trading.reconcile` stale-close (`event=stale_close`).
- **Cloud-side shipping.** `src/api/cloud_app.py` wires the Loki handler at
  startup using env vars (`GRAFANA_LOKI_TOKEN`, `GRAFANA_LOKI_URL`,
  `GRAFANA_LOKI_USER`) so the Render-deployed FastAPI also ships logs.
- **NSSM Windows service installer** at `scripts/install_service.ps1` —
  install / uninstall / restart / status commands. Configures AppDirectory,
  log rotation, AppExit Restart, and a 10s `AppRestartDelay` so the PID
  lockfile atexit hook can release before the next watch-loop launch.
- **Config scaffolding.** `config/settings.example.yaml` gains an
  `observability.grafana` section; `.env.example` gains a
  `GRAFANA_LOKI_TOKEN` placeholder.
- **5 new tests** in `tests/test_loki_handler.py` — disabled config,
  missing observability section, missing env-var token, DedupFilter
  suppression, DedupFilter window expiry. No network calls.

### Fixed

- **Startup hang on unreachable Render Postgres.** `psycopg2.connect()` had
  no `connect_timeout`, so libpq retried SYN indefinitely when the Render
  DB was paused. `create_all_tables` / `ensure_columns` gain an optional
  `connect_timeout` kwarg (default `None` preserves manual-migration
  behavior); the three startup-path call sites now pass
  `connect_timeout=5` so an unreachable DB becomes a warning instead of a
  hang.
- **Stale test baselines.** `tests/test_coerce_to_schema.py` targeted
  `planned_shares` (which flipped INTEGER→REAL in v0.17.1 for fractional
  shares) — retargeted onto the still-INTEGER `duration_days`.
  `tests/test_executor_event_risk_resolve.py` filtered caplog at ERROR
  but the function logs at WARNING — lifted to WARNING across three tests.

## [v0.17.1] - 2026-04-13 — Hotfix: test baseline + fractional shares

Post-v0.17.0 hotfix clearing 12 of 19 pre-existing test failures on main and
a latent fractional-shares source bug. Net: test baseline moves from 1738/1757
passing to 1750/1757 passing (7 structural/environment failures remain, tracked
as separate issues for targeted cleanup sprints).

### Schema

- **fix:** `training_examples` gains `updated_at` (TEXT) column. `GuardedScorer`
  issued `UPDATE training_examples SET quality_score_auto = ?, updated_at = ?`
  but the column was never defined in `src/schema/registry.py` — every
  between-scan rescore raised `sqlite3.OperationalError`. Column added,
  migration applied via `validate-schema --fix`. Fixes `test_scorer.py` × 3.
- **fix:** `shadow_trades.planned_shares` and `.actual_shares` changed from
  INTEGER to REAL. Alpaca fractional share counts (e.g. 0.30) were silently
  truncated to 0, then the positive-shares guard in `journal.store` rejected
  the backfill.

### Source

- **fix:** `BrokerPosition.quantity`, `BrokerOrder.quantity`, and
  `BrokerOrder.filled_qty` changed from `int` to `float` in
  `trading.broker_interface`. `alpaca_broker.py` stops wrapping share counts in
  `int(float(...))` — fractional quantities now survive the reconcile path
  end-to-end. Fixes `test_reconcile.py` × 2 (`backfills_orphaned`,
  `ignores_paper_trades`).

### Tests

- **fix:** `test_env_secrets.py::test_env_var_referenced_in_source` (× 6
  parametrized) rewrote from `subprocess.run(["grep", ...])` to pure Python
  `pathlib.rglob + read_text`. Windows subprocess can't pass the embedded
  double-quote in the search pattern, giving false negatives that bash
  execution didn't show.
- **fix:** `test_watch_resilience.py::test_heartbeat_command_callable` —
  import path updated from `src.notifications.telegram` to
  `src.notifications.telegram_commands` after the notifications split.
- **fix:** `test_ingestion.py` × 2 — replaced live `yfinance.download()` calls
  with `patch` + deterministic OHLCV stubs. Complies with CLAUDE.md's
  no-network-in-tests rule.
- **fix:** `test_news.py::test_historical_news_date_bounds` — patches
  `_load_cached` to None and strips `FINNHUB_API_KEY` from the env so the test
  actually exercises the "no API key" branch rather than returning stale cache
  data from a previous run.
- **fix:** `test_render_sync.py::test_healthy_connection_reused_without_reconnect`
  — patches `create_all_tables` and `ensure_columns` so schema-helper internal
  `psycopg2.connect` calls don't inflate the expected count from 1 → 3.

### API

- **chore:** Bump `app.version` in `src.api.app` and `src.api.cloud_app` from
  `1.0.0` to `0.17.1` to match release tagging.

### Deferred (tracked as issues)

- `test_vram_manager::test_handoff_to_training_unload_fails` — needs
  `_wait_for_vram_clear` mock to exercise the no-nvidia-smi unload-failure
  branch correctly.
- `test_repo_structure.py` × 2 — 2 files over 400-line limit
  (`src/api/cloud_routes/trades.py` 427, `src/email/digest_builder.py` 405)
  and 15 functions over 60-line limit — refactor per the lint contract.

## [v0.17.0] - 2026-04-12 — IB Integration Complete + Dashboard Overhaul + Training Backfill

Consolidates seven IB integration sprints (IB-1 through IB-7), four dashboard
sprints (DB-1, DB-2a, DB-2b, DB-3), one final cleanup sprint (DB-FINAL),
a capital-velocity instrumentation drop, and a 703-row regime-diverse training
backfill into a single tagged release. Sub-sections below keep the sprint-level
notes that previously lived under `[Unreleased]` so the ship history stays
traceable.

### DB-FINAL — Dashboard cleanup

- **fix:** `shadow_trades` gains `time_to_mfe_days` (INTEGER) and `mfe_timestamp`
  (TEXT) columns. Executor's `check_and_manage_open_trades` now updates both on
  every MFE high; flat and adverse cycles preserve the peak. 3 new tests cover
  the rise/flat/close paths (Strategy Decision #32 instrumentation).
- **fix:** Attribution logger warnings are visible (`logger.warning` instead of
  `logger.debug` in `scheduler/universe_scanner.py`) and a defensive
  `_parse_price` check skips attribution entirely when entry/stop/target parse
  to 0/None rather than writing corrupt zero-priced ranker-only pairs.
  `attribution_trades` already carries `sync_to_postgres=True`; integration test
  added.
- **feat:** Mobile sidebar collapse in `Layout.jsx` (hamburger + overlay backdrop,
  status bar hidden below md breakpoint), `min-h-[44px]` touch targets on nav
  links, `p-3 md:p-6 lg:p-8` main-content padding.
- **fix:** `Architecture.jsx` and `DBSchema.jsx` set `nodesDraggable={false}` +
  `nodesConnectable={false}`, `<MiniMap>` removed (bottom-right glitch).
  Architecture subtitle no longer advertises drag.
- **chore:** ~15 `data-testid` attributes on Health (hshs-radar, hshs-composite,
  build-score-card, ib-status-card, model-history), Validation
  (validation-category-{name}), Monitoring (resource-chart, ollama-status,
  disk-status, log-table) for the upcoming System Health consolidation.
- **refactor:** `space-y-4 md:space-y-6` roots across 14 dashboard pages.

### DB-3 — Responsive + polish

- **feat:** Architecture diagram shows IB Gateway infrastructure node + a
  `broker_router` → (`live_alpaca` | `live_ib`) execution split reflecting the
  score-gated dual-broker routing.
- **feat:** Simulation page gains a regime dropdown that highlights one equity
  curve and dims the rest (opacity 0.15).
- **feat:** `scripts/stress_test.py` adds 4 historical scenarios — 2018 Q4
  selloff, 2011 debt ceiling, 2015 China deval, 2024 yen unwind.
- **feat:** IB section on Settings page (shadow_mode, paper_routing, routing
  threshold, Gateway port, client_id).
- **feat:** New `/velocity` dashboard page renders hold-period distribution,
  time-to-MFE scatter (falls back to duration until the new column fills),
  MFE capture efficiency. Gated behind a 50-trade banner until statistically
  useful.

### DB-2b — Feature additions

- **feat:** `IB Shadow` → `Broker Comparison`; nav item moved from System to
  Trading. CTO report exposes a by-broker breakdown (win rate, avg/total P&L).
- **feat:** Logs page "Export errors" downloads ERROR+CRITICAL+WARNING entries
  (last 24h) as markdown; "Clear stale" resolves pending/claimed commands
  older than 1 hour.
- **feat:** `get_training_status` returns `outcome_counts` + `source_counts`
  so the Outcome Distribution card renders real data.
- **feat:** 9 additional IB research + ops docs indexed on the Docs page.
- **feat:** `run_data_collection` emits a per-collector success/failure line
  after the 12-step block.

### DB-2a — Bug fixes

- **fix:** Packets page strips everything before the first recognized XML tag
  so the analysis pane shows LLM output only.
- **fix:** `/live/trades` + `/api/live/trades` enrich open rows with
  `current_price` + unrealized `pnl_dollars` / `pnl_pct` (graceful fallback when
  `setup_signals` is missing).
- **feat:** `OpenPositionCard` — rich per-position monitor card (stop/entry/target
  progress gauge, MFE/MAE, bracket status, conviction, days held/timeout).
  Shadow Ledger open tab uses a card grid.
- **feat:** Ledger source toggle (All / Paper / Live) + broker filter (Alpaca /
  IB) + broker column on closed-trades table.
- **feat:** Strategy page Drawdown chart is now a ComposedChart with green/red
  per-trade bars overlaid on the drawdown area.
- **fix:** Stress Test groups runs by scenario; only the latest per scenario
  renders, rest collapse into a "Previous Runs" archive.
- **fix:** Monitoring page crash — `Array.isArray(history) ? history : []`.

### DB-1 — Data integrity + quarantine sync

- **fix:** `scripts/sync_quarantine_to_postgres.py` one-time migration pushes
  locally-quarantined `shadow_trades.quarantined=1` rows to Render Postgres.
  The incremental sync uses `updated_at > last_synced_at` as its cursor — prior
  quarantine UPDATEs didn't touch the column, so ~17 issues were served
  compromised rows even though `COALESCE(quarantined, 0) = 0` was correctly
  applied in every cloud route.
- **fix:** `scripts/quarantine_april10.py` bumps `updated_at` on every UPDATE so
  future runs sync automatically.
- **fix:** `scripts/backfill_model_version.py` backfills
  `recommendations.model_version = 'halcyon-v1.0.0'` for NULL rows, unblocking
  Model Performance attribution.
- **fix:** `get_active_model_name()` falls back to Ollama `/api/ps` then
  `llm.model` when `model_versions` has no active row; new
  `src.llm.client.get_loaded_model_name` helper.
- **fix:** Header version resolves from `ARCIS_VERSION` env →  `VERSION` file →
  `git describe --tags --abbrev=0` → hardcoded fallback (`lru_cache`'d).
- **fix:** DB Schema page renders live table count + cluster-config domain
  count instead of hardcoded "40 tables across 6 domains".
- **fix:** Settings page — `shadow_trading.timeout_days` + `strategies.pullback.timeout_days`
  resolve to actual keys; Min Conviction Score renders "Disabled" at 0/null;
  System Health shows "CLOUD (local status unavailable)" on cloud mode.
- **fix:** HSHS Flywheel Velocity anchors on completed train-deploy cycles
  (`version_count - 1`); scores zero with one deployed model. Data growth and
  recent-volume signals scale by a spin factor.
- **fix:** `council/value_tracker.py` track-record join adds
  `COALESCE(st.quarantined, 0) = 0`.
- **feat:** `council.auto_apply_parameters` config flag (default **false**).
  Advisory-only mode logs recommendations but does NOT rewrite live config.
  Session meta carries `advisory_only` for the dashboard.

### Training backfill

- **data:** 703 regime-diverse training examples imported — broadens v2 dataset
  from 1,019 to 1,722 examples spanning every market regime in the backfill
  sample. Conviction recalibrated (range 1-8, down from 5-9). Leakage check
  passed (59.8%). Halcyon-v2.0.0 retrain pipeline in progress.

## [Unreleased] — Dashboard Data Integrity (Sprint DB-1)

### Data fixes
- **fix:** `scripts/sync_quarantine_to_postgres.py` — one-time migration that pushes
  locally-quarantined `shadow_trades.quarantined=1` flags to Render Postgres. The
  normal sync is incremental on `updated_at`; quarantine UPDATEs run by
  `scripts/quarantine_april10.py` never touched that column, so 17+ issues across
  the dashboard were reading compromised rows despite every cloud route filtering
  on `COALESCE(quarantined, 0) = 0`. The filter was correct; the data wasn't.
- **fix:** `scripts/quarantine_april10.py` now also bumps `updated_at` on every
  UPDATE so future runs sync automatically without a dedicated migration.
- **fix:** `scripts/backfill_model_version.py` — one-time backfill of
  `recommendations.model_version = 'halcyon-v1.0.0'` for NULL rows, unblocking
  Model Performance dashboard attribution.

### Detection + display
- **fix:** `get_active_model_name()` now falls back to Ollama (`/api/ps`) then the
  config `llm.model` value when `model_versions` is empty. Cloud deployments with
  an unpopulated table no longer report a misleading "base".
- **feat:** `src.llm.client.get_loaded_model_name()` — non-recursive helper used by
  the versioning fallback.
- **fix:** Header bar version string is now resolved from `ARCIS_VERSION` env var
  → `VERSION` file → `git describe --tags --abbrev=0` → hardcoded fallback, with
  `lru_cache` so each request is cheap.
- **fix:** DB Schema page reads the live table count from `/system/table-counts`
  and the domain count from the cluster config instead of hardcoding
  "40 tables across 6 domains".
- **fix:** Settings page — `shadow_trading.timeout_days` and
  `strategies.pullback.timeout_days` now resolve to actual config keys; Min
  Conviction Score renders a "Disabled" pill when the value is 0 or null.
- **fix:** System Health indicators display "CLOUD" (title: "local status
  unavailable") instead of "Off" when running against the cloud API, which
  cannot reach local services like Ollama.

### Metrics
- **fix:** HSHS Flywheel Velocity anchors on completed train-deploy cycles
  (`version_count - 1`); scores zero with only one deployed model. Data growth
  and recent volume are scaled by a spin factor that's zero until the first
  cycle, so mere data accumulation no longer inflates the score.
- **fix:** Council agent track-record query in `value_tracker.py` now applies
  `COALESCE(st.quarantined, 0) = 0` to the `shadow_trades` join.

### Safety
- **feat:** `council.auto_apply_parameters` config flag (default **false**).
  While false, the council logs recommended parameter changes for counterfactual
  attribution but does NOT rewrite live config. Enforces the FINSABER Phase 1
  authority boundary. Session result JSON now carries
  `session_meta.advisory_only` so the dashboard can label sessions as advisory.

### Tests
- **test:** `test_versioning.py` — new `monkeypatch`-based test for the Ollama
  fallback path of `get_active_model_name`.

## [Unreleased] — IB Integration Validation (Sprint IB-7)

### Integration Tests (16 tests)
- **test:** End-to-end IB + Alpaca trade lifecycle with broker field tracking
- **test:** Cross-broker position counting — governor, reconciler, executor all agree
- **test:** Config progression matrix — shadow → routing → live transitions
- **test:** Failure/recovery simulation — fallback, resume, mixed broker state
- **test:** Multi-broker API responses — schema columns, status mapping

### Operational Tooling
- **feat:** `scripts/validate_ib_integration.py` — data completeness checker across
  shadow_trades, ib_shadow_log, daily_ib_health, schema columns
- **docs:** `docs/operations/ib-smoke-test.md` — 6-phase manual validation checklist
  (shadow mode → dual routing → bracket monitoring → failure recovery → dashboard → scripts)

## [Unreleased] — IB Paper Trading Activation (Sprint IB-6)

### Validation & Monitoring
- **feat:** `scripts/validate_ib_gateway.py` — validates paper account setup, qualifies 10
  S&P 100 contracts, checks buying power, tests market data. REFUSES port 4001 (live).
- **feat:** `daily_ib_health` schema table — tracks uptime_pct, trade_count, error_count,
  reconnect_count. 30-day gate: >95% market-hours uptime.
- **feat:** IB Gateway status card on Health page — connection status, shadow mode, trade
  count, uptime, last connection timestamp
- **feat:** IB section in EOD digest — connection uptime %, IB vs Alpaca routing breakdown,
  errors/fallbacks (conditional on shadow_mode or paper_routing enabled)

### Operations
- **docs:** `docs/operations/ib-gateway-setup.md` — IBC config, Windows hardening, TDR fix,
  Java heap, Sunday 2FA procedure, troubleshooting

### Tests
- 5 tests: validation script live port refusal, daily_ib_health schema + SQLite creation,
  digest section conditional logic

## [Unreleased] — IB Production Hardening (Sprint IB-5)

### Connection Resilience
- **fix:** `_ensure_connected()` with exponential backoff (3 retries: 1s, 2s, 4s)
- **feat:** `_verify_bracket_integrity()` checks all positions have active stops after reconnect
- **feat:** Connect/disconnect pattern — fresh connection each poll cycle, rebuild state from server

### Order Safety
- **fix:** `outsideRth=True` on ALL orders — protective orders execute outside regular hours
- **fix:** `ocaType=3` on bracket children — block/overfill protection prevents dual fills
- **feat:** `permId` stored for cross-session tracking (survives Gateway restarts)
- **feat:** Partial fill detection with warning log

### Status Normalization
- **feat:** `IB_STATUS_MAP` normalizes IB statuses (PreSubmitted→pending, Inactive→rejected, etc.)
- **feat:** `_handle_ib_error()` classifies common IB error codes (110, 135, 200, 201, 202)

### Schema
- **schema:** Added `ib_perm_id` column to `shadow_trades` for cross-session order tracking
- **schema:** Added `perm_id` field to `BrokerOrder` dataclass

### Tests
- **test:** 16 tests for reconnection, bracket verification, status mapping, partial fills,
  outsideRth/ocaType, error codes, permId

## [Unreleased] — IB Dual-Execution Routing (Sprint IB-4)

### Score-Based Paper Broker Routing

- **feat:** `_select_paper_broker()` routes paper trades to IB when score >= threshold
  (default 80) and `live_trading.ib.paper_routing: true`. Falls back to Alpaca with
  warning if IB Gateway is down.
- **feat:** `open_shadow_trade()` uses the router — IB paper bracket orders placed via
  broker abstraction, Alpaca path unchanged for below-threshold trades.
- **feat:** `reconcile_paper_trades()` checks correct broker per trade — IB trades
  validate against IB positions, Alpaca trades against Alpaca positions.
- **config:** `live_trading.ib.paper_routing` (bool) + `paper_routing_threshold` (int)
- **test:** 12 tests — routing logic, fallback, cross-broker counting, Alpaca regression

## [Unreleased] — IB Shadow Dashboard + API Routes

### IB Shadow Dashboard

- **schema:** Enabled Postgres sync for `ib_shadow_log` (incremental, keyed on `shadow_id`)
- **feat:** 3 cloud API routes (`/api/ib-shadow/summary`, `/api/ib-shadow/log`, `/api/ib-shadow/health`)
- **feat:** IB Shadow dashboard page with KPI cards (shadow count, gateway uptime, contract valid, BP acceptance), trade log table, and error log
- **feat:** Navigation entry in System section (GitCompare icon)
- **feat:** Empty state with setup instructions when no shadow data exists

## [Unreleased] — IB Structural Fixes (Sprint IB-2)

### Critical Runtime Bug Fixes

- **fix:** `get_live_broker()` called without config arg — TypeError on live path
- **fix:** `get_positions()` → `get_all_positions()` + `p["symbol"]` → `p.ticker`
- **fix:** IB bracket child order IDs now stored (enables bracket health monitoring)
- **fix:** Bracket exit monitoring routes through broker factory for live trades
- **fix:** `_retry_exit` cancel uses broker factory for live/IB trades
- **fix:** Risk governor uses IB account equity when `broker=ib`
- **fix:** Live reconciler cancels IB orders before closing stale trades
- **fix:** IB `get_position` fetches current price via market data snapshot
- **fix:** Startup check validates `ib_async` availability when IB configured

### Schema

- Added `ib_child_order_ids` column to `shadow_trades`
- Added `broker_order_id` alias column (prep for `alpaca_order_id` migration)

## [Unreleased] — IB Test Coverage + Shadow Mode (#368)

### IB Broker Unit Tests (24 tests)

- **test:** Full unit test coverage for all 10 `BrokerAdapter` methods on `IBBroker`
  via mock factories (no ib_async dependency required). Covers happy paths (10),
  error handling (8), and edge cases (6) — connection lifecycle, bracket orders,
  market orders, exits, cancellations, positions, price snapshots.
- **test:** Mock factory helpers in `tests/conftest_ib.py` for all 6 ib_async
  object types (AccountValue, Trade, Position, Order, Stock, Ticker).

### IB Shadow Mode

- **feat:** `IBShadowLogger` class (`src/trading/ib_shadow.py`) — validates IB
  Gateway connectivity, contract validity, and buying power for each Alpaca
  trade WITHOUT submitting orders. Stores comparison data in `ib_shadow_log`.
- **schema:** Added `ib_shadow_log` table (17 columns, sync_to_postgres=False).
- **feat:** Executor hooks in `open_shadow_trade()` and `open_live_trade()` —
  non-blocking, wrapped in try/except, only fires when `ib.shadow_mode: true`.
- **test:** 6 shadow logger tests + 2 executor integration tests.

## [v0.16.12] - 2026-04-11

### Trading safety + security batch (#361, #363, #369, #370, #380)

**Trading safety (#369, #370):**
- **fix:** Replaced 6 `except Exception: pass` blocks in `executor.py` with
  `logger.warning()` — critical trading notifications (buying-power crisis,
  unprotected positions, exit circuit breaker) were silently swallowed
- **fix:** Added argument validation to `test_retry_exit_called_for_exit_failed`
  (`assert_called_once_with` instead of `assert_called_once`)
- **fix:** Added explicit assertion to `test_missing_table_does_not_raise`

**Security (#361, #363, #380):**
- **fix:** Added column allowlist in `attribution/logger.py` — dynamic SQL
  SET clause now validates columns against `_ALLOWED_ATTRIBUTION_COLUMNS`
- **fix:** Replaced `.format()` SQL in `value_tracker.py` with parameterized
  `?` placeholders for the `IN` clause
- **fix:** Replaced raw `str(exc)` in 5 command executor error responses with
  generic error categories — full details logged server-side only

## [v0.16.11] - 2026-04-11

### Fix: Test regressions — buying power mock + training gate assertion (#239, #371, #372)

- **fix:** Added `get_account_info` mock to `TestPaperSourceTagging` and
  `TestDualExecution` — tests failed because `_check_paper_buying_power()`
  returns $1 with placeholder API keys (#371, #239)
- **fix:** Updated `test_markdown_bold_heading_rejected` to use a standalone
  bold heading line (`**Market context:**\n`) instead of inline bold-then-text.
  The regex was intentionally narrowed in #334 to allow inline emphasis; the
  test wasn't updated (#372)
- **fix:** Fixed `test_daily_loss_guard_halts_trading` — the daily loss guard
  queries the DB directly, not `get_open_shadow_trades`. Test now inserts a
  losing live trade into tmp_db so the guard finds it.
- **fix:** Fixed `test_generate_create_sql_basic` — SQLite generator inlines
  `PRIMARY KEY` on single INTEGER columns (ROWID alias). Test was asserting
  the separate `PRIMARY KEY (id)` constraint form.

## [v0.16.10] - 2026-04-11

### P2 batch: research feeds, CBOE scraper, buying power race condition (#389-392)

- **fix:** Research feeds (#389): Removed dead Anthropic `/feed.xml` (404) and
  OpenAI `/blog/rss/` (403) URLs. Replaced Anthropic with `/research/rss.xml`.
  Added `Accept` header to SSRN request. Increased arXiv timeout to 60s.
- **fix:** CBOE scraper (#390): Demoted regex-failure log from `warning` to
  `debug` — the SPY proxy and FRED fallbacks already produce reliable data.
  The regex breaks every time CBOE changes their HTML.
- **note:** NULL ids (#391): Investigated and confirmed already resolved —
  SQLite `INTEGER PRIMARY KEY` auto-assigns ROWIDs. Current state: 459K rows,
  0 NULL ids. The auto-repair messages in logs were from a one-time migration.
- **fix:** Buying power race condition (#392): Added per-scan-cycle committed
  capital tracker in executor. Previously N trades each passed the buying power
  check individually but together exhausted capital. Now
  `_scan_cycle_committed` subtracts capital from earlier orders in the same
  batch before checking. Reset at scan start via `reset_scan_cycle_committed()`.

## [v0.16.9] - 2026-04-11

### Root cause gap closures for #383, #386, #388

- **fix:** Added `_coerce_to_schema` to `update_recommendation()` — was unprotected
- **fix:** Refactored direct SQL UPDATE in `executor.py:650` to use
  `update_shadow_trade()` — was bypassing the coercion write boundary
- **fix:** Council dynamic weights: aggregate net PnL per day before joining
  to votes, preventing many-to-many inflation where 1 vote × 5 trades = 5
  data points. Added `session_type` filter to the query.
- **fix:** Applied circuit breaker to `generate_structured()` — was unprotected
  against Ollama outages, burning 180s timeouts independently of `generate()`

## [v0.16.8] - 2026-04-11

### Hotfix: Ollama timeout resilience — circuit breaker + auto-restart (#388)

- **fix:** Added consecutive failure tracking (circuit breaker) to `generate()` —
  after 3 failures, skips immediately instead of burning 180s timeouts per call.
  Previously 15 consecutive timeouts wasted 45 minutes on Apr 10 evening.
- **fix:** Auto-restart mechanism: when circuit breaker trips, attempts to restart
  Ollama via `ollama serve` before giving up
- **fix:** 2-second cooldown between inference calls to prevent Ollama overload
  during batch processing (10-20 tickers per scan cycle)

## [v0.16.7] - 2026-04-11

### Hotfix: Training pipeline — em-dash SyntaxError + GGUF fallback + Modelfile path (#387)

- **fix:** Replaced Unicode em-dash with ASCII `--` in `training_data/train.py:78`
  — Windows cp1252 subprocess could not parse the UTF-8 character, blocking
  the entire training script from loading
- **fix:** Added CPU-based GGUF conversion fallback via llama.cpp when Unsloth
  GPU export fails due to insufficient VRAM (RTX 3060 12GB)
- **fix:** Modelfile path now uses `.as_posix()` for forward slashes — was
  writing Windows backslashes into the `FROM` directive

## [v0.16.6] - 2026-04-11

### Hotfix: Council dynamic weights query — fix broken join (#386)

- **fix:** Replaced broken `JOIN shadow_trades st ON cs.session_id = st.session_id`
  (column never existed) with date-based join `ON date(cs.created_at) = date(st.created_at)`.
  Council sessions are market-level, not per-trade — votes are matched to trades
  opened on the same day.
- **fix:** Added `float()` cast on `pnl_dollars` comparison (defense-in-depth for #383)

## [v0.16.5] - 2026-04-11

### Hotfix: Auto-fix Postgres schema drift during startup (#385)

- **fix:** Startup sequence now runs `create_all_tables()` + `ensure_columns()`
  against Render Postgres automatically, matching the SQLite auto-fix pattern.
  Previously only warned about drift (filed 8 times as #184, #285, #307, #331,
  #332, #338). Missing tables and columns are now created on every startup.

## [v0.16.4] - 2026-04-11

### Hotfix: LLM output quality — repeat penalty + output validation (#384)

- **fix:** Added `repeat_penalty: 1.15` to Ollama API calls in `src/llm/client.py`
  to suppress degenerate repetition loops (52 debug log files showed `===` or
  data fields repeated 10-82 times)
- **fix:** Added `_validate_llm_output()` pre-parser in `src/llm/packet_writer.py`
  that rejects responses containing prompt leakage (37% of debug logs), template
  stubs (10%), and repetition loops (14%) before they reach the XML parser
- **test:** 10 tests for `_validate_llm_output` covering all rejection categories

## [v0.16.3] - 2026-04-11

### Hotfix: Write-boundary type coercion for shadow_trades (#383)

- **fix:** Added `_coerce_to_schema()` to `src/journal/store.py` — coerces dict
  values to match schema registry column types (REAL→float, INTEGER→int) before
  INSERT/UPDATE. Applied to `insert_shadow_trade()`, `update_shadow_trade()`,
  and `log_recommendation()`. This is the systemic root cause behind 10+ prior
  issues where `pnl_dollars`, `entry_price`, `price_at_recommendation` etc.
  were stored as strings, causing TypeErrors in 8+ downstream subsystems.
- **test:** 13 tests for `_coerce_to_schema` covering string→float, None
  preservation, unknown tables/columns, invalid values, and multi-column
  coercion.

## [Unreleased] — Manual Backfill Pipeline

### Historical Backfill: Manual Generation Workflow

**New modules:**
- `src/training/regime_sampler.py` — regime-targeted date selection, stratified sampling, FRED macro formatting, and dataset balancing helpers (moved from backfill.py)
- `scripts/export_backfill_prompts.py` — exports regime-targeted prompt files with real FRED macro context for manual generation via Claude/ChatGPT
- `scripts/import_backfill_results.py` — validates XML, pairs with sealed outcomes, inserts into training_examples (idempotent)
- `scripts/backfill_progress.py` — visual per-regime progress tracker

**Enhancements:**
- `src/training/historical_data.py` — FRED historical series fetch (`fetch_fred_history`) + point-in-time lookup (`get_fred_value_as_of`)
- `src/training/historical_scanner.py` — FRED macro enrichment in scan pipeline, PASS example generation (score 45-69), `generate_backfill_example()` handles outcome=None
- `src/llm/prompts.py` — `PASS_ANALYSIS_PROMPT` for below-threshold setups (conviction 1-4, NEUTRAL direction)

**Refactors:**
- `src/training/backfill.py` — 445→343 lines; `_balance_dataset`, `_deduplicate_candidates`, `_cap_and_diversify` moved to `regime_sampler.py`

**Tests:** 16 new tests (6 FRED history + 10 regime sampler); all 40 pass

## [v0.16.2] - 2026-04-11

### Hotfix: MR scan broken import (#382)

- **fix:** Corrected import path `src.journal.recommendation_logger` →
  `src.journal.store` — the `recommendation_logger` module never existed;
  `log_recommendation()` lives in `store.py`. Mean-reversion scanning has been
  fully disabled since April 9.

## [v0.16.1] - 2026-04-10

### Hotfix: pandas 3.0 import deadlock on Windows

- **fix:** Pin `pandas>=2.2,<3.0` in requirements.txt — pandas 3.0.1 C extensions
  deadlock on import under Python 3.13 + Windows (DLL loading hang in
  `pandas._libs.pandas_parser`)
- **fix:** Recreate venv with pandas 2.2.3 to restore `startup` / watch loop

## [v0.16.0] - 2026-04-10

### Trade Reconciliation Hardening & Data Quarantine

**Security (#348, #349):**
- **fix:** Local API binds to 127.0.0.1 (was 0.0.0.0)
- **fix:** Cloud API raises RuntimeError when API_SECRET is empty

**Order Submission (#352, #353, #359, #360):**
- **feat:** Post-submission order verification via `verify_order_accepted()`
- **fix:** Typed exception handling — ConnectionError/TimeoutError, APIError, Exception
- **feat:** Entry retry with ghost position check on network errors
- **feat:** exit_order_id stored immediately after exit submission

**Reconciler (#354, #356, #357, #358):**
- **fix:** Backfilled orphans get 5% stop/target defaults (was zero)
- **feat:** `cancel_orders_for_ticker()` called before closing stale positions
- **fix:** Alpaca position check before entry prevents duplicate ghost positions
- **feat:** Telegram alert after 3+ consecutive buying power failures
- **feat:** `submission_uncertain` trades resolved by reconciler

**Status Model (#355):**
- **feat:** TERMINAL_STATUSES / ACTIVE_STATUSES constants in models.py
- **fix:** Buying power rejections use status='rejected' (was 'failed')

**Data Quarantine:**
- **feat:** `quarantined` column added to shadow_trades
- 77 compromised records flagged (42 rejected, 34 stale, 1 orphan WMT)
- 18 verified trades preserved ($603.96 P&L, 83.3% win rate)
- All shadow_trades queries filtered on quarantine column
- **fix:** TEXT-to-REAL type casting in shadow_service (TypeError)

**Infrastructure (#328, #350, #351):**
- **fix:** latest_collection date format truncated to date-only
- **fix:** Watch loop done-flags moved inside try blocks
- **test:** Executor entry path coverage added

## [v0.15.3] - 2026-04-08

### Production Sweep — 14 issues closed in 3 phases

**Phase 1 — CRITICAL (v0.15.1):**
- **fix:** Stop-price > 0 guard before bracket order placements (#326)
- **fix:** Fractional share tolerance — alpaca adapter returns float qty (#325)
- **fix:** Conviction extraction stages 7-8 + parse rate logging (#329)
- **fix:** safe_numeric for quality_score_auto, int() cast on config thresholds (#330)
- **fix:** Overnight training script import path verified (#335)

**Phase 2 — HIGH (v0.15.2):**
- **fix:** Postgres create_all_tables + ensure_columns at sync startup (#331)
- **fix:** macro_snapshots sync_conflict_col for duplicate key prevention (#332)
- **fix:** DDL guardrail verified clean (#327)
- **fix:** Data collection stats COALESCE for column compatibility (#328)

**Phase 3 — MEDIUM (v0.15.3):**
- **fix:** NULL PK inline PRIMARY KEY root cause verified (#302)
- **fix:** Research source caching + 30s timeout + retry with backoff (#303)
- **fix:** VRAM handoff 3-retry logic with Telegram alert (#304, #333)
- **fix:** Ingestion gate narrowed for inline bold emphasis (#334)

## [Unreleased — pending v0.15.0]

### Gap Assessment (merged 2026-04-07)
- **feat:** Embedding-based semantic leakage detection — Ollama + LogisticRegression classifier (#295)
- **feat:** Dynamic Bayesian agent weighting for AI Council — Beta posterior, feature flag, 12-week window (#296)
- **feat:** Two-tier relative strength — 60% vs SPY + 40% vs sector ETF, 11 sector ETFs mapped (#297)
- **test:** 7 ranker tests (two-tier RS, pullback bounds, volume weight, backward compat, score cap)
- **test:** 6 council aggregation tests (dynamic weights, floor enforcement, normalization, fallback)
- **test:** 6 embedding leakage tests (mock Ollama, graceful fallback, threshold, class balance)

### Pending merge
- feat/simulation-engine: 13-scenario engine, Monte Carlo, TL validation, dashboard page
- feat/model-performance: per-model metrics, regression alerts, dashboard page
- feat/ui-bloomberg: Bloomberg Terminal aesthetic on all 18 pages

## [v0.14.2] - 2026-04-06

### Hotfix merge sprint — 6 critical production bugs + codex fixes + dependencies

**Critical fixes (PR #313):**
- **fix:** Shadow trade exit cascade — `exit_failed` status + circuit breaker + `cancel-all-pending` CLI (#310)
- **fix:** Type-safety gaps — `safe_numeric` utility for traffic_light, VIX alerts, EOD report (#311)
- **fix:** LLM conviction parsing — Stage 6 catch-all regex + debug file logging (#309, #312)
- **fix:** Risk governor TypeError — `safe_numeric` coercion at `check_trade` entry (#308)
- **fix:** Postgres schema drift — startup drift check + broker column (#307)

**Codex fixes (PR #305):**
- **fix:** Ingestion gate markdown detection narrowed to line-leading headings (#299)
- **fix:** Type-safety in notifications/digests (#300)
- **fix:** Fundamentals refresh import drift (#301)

**Other:**
- **feat:** Structured logging with `|ctx:{}` for AI agent review (#314)
- **fix:** load_dotenv() in config loader — .env works from any entry point (#317)
- **build:** 9 Dependabot PRs (CI actions, npm bumps, yfinance range)
- **chore:** 33+ stale branches deleted

## [v0.14.1] - 2026-04-05

### Log Audit Hotfix (14 production issues)

Full audit of 15K-line arcis.log identified and fixed 14 issues across 8 modules.

**Critical:**
- #279: Bracket monitor strips Alpaca enum prefix from leg statuses + adds `accepted` to ACTIVE_LEG_STATUSES (was reporting 0/N protected)
- #280: Earnings signals column names corrected to schema registry (actual/estimate/metric)

**High:**
- #281: Overnight training script imports fixed (was referencing wrong module paths)
- #282: Position monitor casts timeout_days from SQLite TEXT to int
- #283: Regime refresh passes ohlcv_data argument to sentiment_scanner
- #284: HSHS performance sub-score casts SQLite TEXT to float before abs()
- #285: Training data_collector casts to float before %.2f format string

**Medium:**
- #286: Postgres sync null ID guard + duplicate primary key handling
- Stress test VIX symbol handling fixed
- EOD recap format string type safety

**Audit report:** `docs/audits/log-audit-2026-04-04.md`

---

## [v0.14.0] - 2026-04-05

### Interactive Brokers Integration — Broker Abstraction Layer

5 new files, 19 new tests. Multi-broker architecture deployed.

**New modules:**
- `src/trading/broker_interface.py` — Abstract BrokerAdapter (10 methods) + normalized dataclasses
- `src/trading/broker_factory.py` — Singleton factory, config-driven routing (`"ib" | "alpaca"`)
- `src/trading/ib_broker.py` — IB adapter via ib_async, lazy connection, GTC bracket orders
- `src/trading/alpaca_broker.py` — Thin wrapper over existing alpaca_adapter.py
- `tests/test_broker_interface.py` — 19 tests (interface compliance, factory routing, dataclasses)

**Architecture changes:**
- Live trading routes through broker factory: `get_live_broker(config)` instead of direct Alpaca
- Schema: `broker` column added to `shadow_trades` (default "alpaca")
- Config: `settings.example.yaml` updated with IB settings (host, port, client_id)
- Paper trading unchanged (Alpaca direct, no abstraction needed)

---

## [v0.13.0] - 2026-04-04

### Gap Analysis Rectification — 23 Issues Resolved in 3 Tiers

19 files changed, +414 -157. 0 open issues.

**Tier 1 — CRITICAL (6 issues, money at risk + training data):**
- #272: Live trading now enforces RiskGovernor + LLM validator (was bypassed entirely)
- #274: Bracket fallback places standalone stop-loss (was naked market entry)
- #275: Daily loss guard uses today's realized P&L (was all-time unrealized)
- #277: Feature sanitization BEFORE LLM generation (self-blinding leak fixed)
- #273: Empty-output templates excluded from training dataset
- #278: Partial fills tracked correctly (was recording as full close)

**Tier 2 — HIGH (7 issues, reliability):**
- #271: MR exit passes all required args to close_shadow_trade
- #276: Duplicate position check + insert in same transaction (race fixed)
- #267: Traffic light defaults to 0.5 (conservative) when missing
- #257: _safe_run only sets done-flag on success (failed tasks retry)
- #259: pull_commands only claims successfully inserted commands
- #269: _notify_exit_trade call sites pass all required params
- #264: open_shadow_trade returns None consistently on failure

**Tier 3 — MEDIUM (9 issues, polish):**
- #256: Options metrics query column names fixed
- #260: options_chains retention rule added (30 days)
- #261: Options flow in training documented as future enhancement
- #262: earnings_signals logs errors instead of swallowing
- #263: Duplicate bracket order log removed
- #265: Stub endpoints return not_implemented status
- #266: shadow_account queries unified
- #268: Dead canary_score import removed
- #270: NYSE 2026 holiday calendar added

---

## [v0.12.0] - 2026-04-04

### Codebase Documentation + Issue Resolution + Gap Analysis

116 files changed, +3,757 lines. 0 pre-existing issues remaining.

**Issue resolution (11 closed: #222, #239, #247-#255):**
- #248: Bracket monitor false alarms — Alpaca enum prefix stripped
- #249: System validator reads env vars, not YAML
- #250: Dark mode chart visibility — CSS variables defined
- #251: Packet commentary — raw template headers stripped
- #253: Open positions unrealized P&L computed
- #254: Max consecutive losses wired from cto_report
- #247: Metric cards centered
- #252: Stress test Run button via command queue
- #255: React Flow diagram polish
- #239: Daily audit baseline updated
- #222: Telegram pairing documented

**Codebase documentation:**
- WHY-focused inline comments on all 200+ Python files
- 30 closed issues cross-referenced in code at fix locations
- Strategy decisions (#1-#24) cited at implementation points

**Gap analysis (15 new issues filed: #256-#270):**
- Options pipeline dead (#256), _safe_run done-flags (#257), busy_timeout bypass (#258)
- pull_commands claim bug (#259), options_chains unbounded growth (#260)
- Unused options flow (#261), earnings_signals swallowing (#262), duplicate log (#263)
- open_shadow_trade return type (#264), stub endpoints (#265), wrong columns (#266)
- Traffic light default (#267), broken import (#268), missing params (#269), no holidays (#270)

---

## [Unreleased] - 2026-04-03

### Bug Fixes (PRs #200, #201, #204)

- Cast `pnl_dollars` to float before comparison in shadow trade close logic (#195, PR #200)
- Fix exit order cancel race condition — cancel completes before status update (#196, PR #201)
- Harden VRAM handoff escalation — retry with exponential backoff (#198, PR #201)
- Add Postgres sync reconnection on transient connection drops (#199, PR #201)
- Fix 8 RCCA bugs from 4/3 log audit: SQLite TEXT→numeric casts (4 bugs), VIX `.item()`, regime missing arg, Telegram undefined var, Postgres duplicate keys (PR #204)

### Sprint Gap Closures (PR #204)

- Wire `resolve_pending_outcomes()` into 4:30 PM post-close job (S3)
- Add `tests/test_attribution.py` — 12 tests covering all 5 attribution functions (S3)
- Add `strategy_type` dropdown filter on Shadow Ledger + API response (S4)
- Extract universe scanner from `watch.py` into stateless `universe_scanner.py` (S5)
- VIX-regime ATR-based brackets in stress test (2.0x/2.5x/3.0x by regime) (S7)
- Schedule stress test Sunday 9 PM + re-run on model version change (S7)

### Halcyon-Audit Plugin (PR #204)

- 8 domain agents + 1 synthesis agent for automated codebase auditing
- `/audit` skill with scheduling, quality gate, baseline management
- Idempotent GitHub issue filing with severity/domain labels

### Local API Parity (PR #202)

- 22 missing routes added to local FastAPI server to match cloud endpoints

### Sprints A through 7: Dashboard, Attribution, MR, Multi-Cadence, Training, Stress Testing

**Sprint A — Dashboard Polish + Documentation Consolidation:**
- Redesigned audit banner as compact expandable chip (green/yellow/red/stale states)
- Fixed build score empty state (shows "not yet computed" instead of 0.0)
- Added `cto-report` command handler; fixed action endpoint mappings
- Fixed activity feed "task: ?" entries for overnight_task and default cases
- Created MASTER.md (822 lines, 13 sections) consolidating 5 governance docs
- Archived 11 docs to docs/archive/governance/ and docs/archive/reference/
- Enriched watch loop: startup banner with portfolio stats, 60-min heartbeat, scan summary line

**Sprint 3 — Alpha Attribution Experiment:**
- Added `attribution_trades` table (49 tables total in registry)
- Two-phase attribution logging in watch.py (before/after LLM)
- Mechanical outcome simulator for post-close evaluation
- Historical backtest script (`scripts/alpha_attribution_backtest.py`)
- Dashboard Attribution page with win rate comparison and statistical power

**Sprint 4 — Mean Reversion Paper Trading:**
- Mean reversion feature engine (RSI(2), 200 EMA, Bollinger, volume spike)
- Shared `compute_rsi()` utility in `src/features/indicators.py`
- Strategy config with `paper_only` enforcement
- Strategy-aware exit dispatcher (RSI(2) > 70 exit, ATR stop, MR timeout)

**Sprint 5 — Multi-Cadence Scanning:**
- Extracted 4 modules: position_monitor (15 min), universe_scanner (30 min), sentiment_scanner (60 min), fundamentals_refresh (daily)
- 4-tier timing orchestrator wired into watch.py main loop
- Staleness detection with per-ticker per-source tracking (`data_freshness` table)

**Sprint 6 — Outcome-Conditioned Training Pipeline:**
- Outcome classifier (WIN/LOSS/TIMEOUT from exit_reason + P&L)
- 4 outcome-conditioned + 2 contrastive prompt templates (all self-blinding)
- Data collector now generates 3-5 examples per closed trade (up from 1)
- 8 outcome metadata columns added to shadow_trades

**Sprint 7 — Historical Stress Testing:**
- Stress test script for 2008, 2020, 2022 crisis periods
- Survivorship bias mitigation (filter + note limitation)
- Extended backtester metrics (calmar, monthly returns, drawdown duration)
- Dashboard StressTest page with equity curves
- Results stored in `stress_test_results` table

## [Previous] - 2026-03-31

### Sprint 8: Comprehensive Cleanup — All Remaining Issues

**Training Pipeline Safety (Task 1):**
- Sanitize feature snapshots: remove outcome-correlated fields before storage (#110)
- Exclude canary example IDs from exported training data (#111)
- Leakage detector returns INSUFFICIENT_DATA when <30 examples per class (#113)
- Temporal split applied BEFORE quality filter to prevent future leakage (#114)
- Dynamic gradient accumulation prevents crash on small datasets (#115)
- Partial close detection: label as PARTIAL and exclude from training (#116)

**Council Fixes (Task 2):**
- Exponential backoff retry on Anthropic rate limit errors (#117)
- Filter unparseable votes from consensus tally (#118)
- Dynamic majority threshold (len//2+1) instead of hardcoded 3 (#119)
- Cost cap check before Round 2 with configurable max_session_cost (#120)
- Type-validate confidence values — non-numeric defaults to 0.5 (#121)
- Auto-create value tracker tables on first access (#122)

**LLM Pipeline Hardening (Task 3):**
- Configurable LLM timeout via llm.inference_timeout_seconds (#153)
- Context window overflow protection with enrichment truncation (#154)
- Prompt injection sanitization for news/filing enrichment data (#156)
- Universe lookup failure rejects trade (fail closed) (#162)
- Grammar client VRAM leak fix on model version change (#163)
- Daily packets list capped at 200 and cleared after EOD digest (#164)
- VRAM threshold increased from 500MB to 1500MB (#166)
- Empty string LLM responses treated as failure (#167)
- Conviction None defaults to 5 with warning (#168)
- Out-of-range conviction logged as hallucination before clamping (#169)

**Data Pipeline Robustness (Task 4):**
- Nightly retention policy: prunes old rows from 7 tables (#123)
- Options collector validates underlying_price (reject NaN/None/0) (#125)
- EDGAR accession numbers normalized to dashed format (#126)
- EDGAR NLP UPDATE checks columns exist via PRAGMA (#127)
- CBOE collector returns None on regex failure (#128)
- Short interest collector uses cursor.rowcount (#129)
- Sync timezone handling verified (#131)
- Enricher rate limiting: Finnhub 1s, SEC 0.1s intervals (#133)

**Trading Logic Fixes (Task 5):**
- Atomic duplicate position check with BEGIN IMMEDIATE (#99)
- Alpaca API failure counter with Telegram alert at >50% failure rate (#102)
- Partial fill detection on bracket legs (#104)
- Backfilled positions flagged with zero stop/target (#107)
- Stale record closure attempts yfinance P&L, falls back to reconciled_stale (#108)
- Daily loss limit uses realized (closed) trades only (#109)
- Traffic light persistence debounce (5-minute cooldown) (#144)
- Sector exposure uses current market price (#145)

**Frontend Bug Fixes (Task 6):**
- Verified all fetchApi() calls match backend routes, added getBuildScore (#81, #134)
- Per-page ErrorBoundary wrapping all routes (#135)
- ShadowLedger reads starting capital from API (#138)
- CTOReport uses optional chaining on all data fields (#139)
- Council page invalidates queries after askStrategic mutation (#140)
- Training page derives outcome types dynamically (#142)

**Frontend Security & UX (Task 7):**
- AuthGate hashes password with SHA-256, 24h expiry (#137)
- Docs page sanitizes HTML to prevent XSS (#136)
- .env.example clarifies VITE_API_SECRET is dashboard-only (#148)
- formatTimestamp utility with Intl.DateTimeFormat (#141)
- Text labels alongside color-coded status indicators (#143)

**Sprint 6 Visibility (Task 8):**
- All 6 Sprint 6 tasks were already implemented; refactored Training.jsx (450→315 lines)

**Config, Performance & Tech Debt (Task 9):**
- Central DB_PATH constant in src/config (#83)
- Added missing env vars to .env.example (#84)
- Added 10+ minimal import tests for untested modules (#85)
- Updated AGENTS.md route count (55→124) (#86)
- Added indexes on shadow_trades.status and recommendations.created_at (#92, #97)
- Replaced all var(--slate-*) with var(--arcis-*) (#93)
- Moved config_overrides.py to src/config/overrides.py (#95)
- Added comprehensive comments to settings.example.yaml (#98)
- Research collector logs fallback to keyword scoring (#146)
- NYSE holiday awareness for 2026 (#149)
- Sleep/crash recovery detection with gap alerting (#152)
- reload_config() clears cache on demand (#165)

**Tests:** +78 new tests (1225 total, up from 1147) across 16 new test files
**Files:** 173 Python modules, 101 test files

**Issues closed:** #81, #83, #84, #85, #86, #92, #93, #95, #97, #98, #99, #102, #104, #107, #108, #109, #110, #111, #113, #114, #115, #116, #117, #118, #119, #120, #121, #122, #123, #125, #126, #127, #128, #129, #131, #133, #134, #135, #136, #137, #138, #139, #140, #141, #142, #143, #144, #145, #146, #148, #149, #152, #153, #154, #156, #162, #163, #164, #165, #166, #167, #168, #169

---

### Sprint 7: Reliability & Critical Bug Fixes

**P0 fixes (trading risk / system crash):**
- Watch loop crash protection: top-level exception handler with Telegram CRITICAL alert, graceful SIGTERM handling, exponential backoff (10s/30s/60s cap) replacing fixed 5-min cooldown, hourly instability alerts (#159, #155, #157)
- Bracket orders changed from DAY to GTC time-in-force — positions now protected overnight/weekends (#101)
- Exit-failed recovery: failed exits marked `exit_failed` and retried next scan cycle with Telegram alert (#100)
- Timestamp parse failure now defaults to days_open=999 (force timeout) instead of 0 (disable timeout) (#105)
- Stop-loss vs take-profit bracket leg identification in exit_reason field (#103)
- Traffic Light API: replaced UNKNOWN stub with live DB query (#89)
- Render sync crash detection: Telegram alert on error, mutex to prevent overlapping cycles (#161, #130)
- load_dotenv added to watch.py for standalone execution (#90)

**P1 fixes (will cause problems soon):**
- Heartbeat: writes timestamp to data/watchdog.txt every 60s, /heartbeat Telegram command (#150)
- Scan overlap prevention: _scan_in_progress flag prevents concurrent scans (#151)
- SQLite busy_timeout: new `src/utils/db.py` helper with PRAGMA busy_timeout=5000; migrated executor, bracket_monitor, reconcile (#160)
- Missing API key alerts: one-time Telegram alert per missing key (FINNHUB, FRED) (#124)

**Cosmetic:**
- Renamed "HALCYON LAB" to "ARCIS" in watch banner and startup notification (#94)
- Updated build_score.py docstring from "Halcyon Lab" to "Arcis" (#96)
- Replaced hardcoded Render URL with RENDER_API_URL env var (#91)

**Tests:** +18 new tests (1168 total) across 3 new test files: test_watch_resilience.py, test_bracket_safety.py, test_db_util.py

**Issues closed:** #89, #90, #91, #94, #96, #100, #101, #103, #105, #124, #130, #150, #151, #155, #157, #159, #160, #161

### Automated Daily Reconciliation (#170)

#### Paper Trade Reconciliation
- Added: `reconcile_paper_trades()` in `src/shadow_trading/reconcile.py` — compares Alpaca paper positions with local `shadow_trades` (source='paper')
- Added: Orphaned position backfill with `order_type='reconciled'`, stale trade detection (alert-only, no auto-close), qty discrepancy reporting
- Added: `_run_postclose_reconciliation()` in watch loop — runs daily at 4:30 PM ET postclose, sends Telegram summary
- Added: 4 tests in `tests/test_reconcile.py` (all-matched, orphaned backfill, stale no-auto-close, qty discrepancy)

---

### Sprint 6: Data Pipeline Visibility

#### API Wiring (Task 1)
- Added: `getDataCollectionStats`, `getTrainingHistory`, `getScanMetrics` methods to frontend api.js

#### Data Collectors Grid (Task 2)
- Added: 12-card collector grid on Training page with freshness indicators (green/yellow/red)
- Added: row counts, relative dates ("2h ago", "yesterday"), and ticker coverage per collector
- Added: responsive grid (3 cols desktop, 2 tablet, 1 mobile)

#### Training Pipeline Status (Task 3)
- Added: pipeline status section on Training page with active model card and status badge
- Added: format compliance display (XML vs plain_text counts)
- Added: leakage test indicator with OK/Marginal/Leaking thresholds
- Added: quadrant distribution 2x2 grid (good/bad process x good/bad outcome)

#### Model History (Task 4)
- Added: model history timeline on Health page with version, status badge, example count, holdout score
- Added: graceful single-model state ("First model — no comparisons yet")

#### Scan Metrics Trend (Task 5)
- Added: scan metrics section on Dashboard with today's summary (scans, packets, LLM success rate)
- Added: 7-day trend sparkline using Recharts LineChart
- Added: LLM success rate color coding (green >90%, yellow 70-90%, red <70%)

#### Card Contrast Fix (Task 6)
- Added: `.arcis-card` CSS class in index.css (elevated bg, border, shadow, hover state)
- Changed: all card elements across Dashboard, Health, Training, Settings, CTOReport to use `.arcis-card`
- Changed: MetricCard component migrated from inline styles to `.arcis-card`
- Changed: Dashboard cards migrated from `--slate-*` to `--arcis-*` design tokens
- Added: light mode shadow variant for `.arcis-card`

#### .env Secret Migration (Task 7)
- Added: `os.environ.get()` with YAML fallback to 10 modules (telegram, claude_client, 3 Finnhub collectors, macro collector, email notifier, insiders enrichment, news enrichment)
- Added: `TELEGRAM_CHAT_ID` to `.env.example`
- Added: `tests/test_env_secrets.py` with 11 tests covering env precedence, YAML fallback, missing keys, and placeholder detection
- Pattern: `.env` (via `load_dotenv`) takes precedence; YAML config is backward-compatible fallback

#### Documentation (Task 8)
- Updated: CHANGELOG.md with Sprint 6 entry
- Updated: AGENTS.md counts
- Verified: test baseline maintained, frontend builds successfully

---

### Sprint 5: Dashboard Polish & UX

#### Shadow Ledger (Task 1)
- Added: summary row (total positions, unrealized P&L, avg days held)
- Added: P&L values with colorblind-accessible arrows (▲/▼) + `financial-data` class
- Added: alternating row shading via `var(--arcis-bg-elevated)`
- Added: mobile-responsive columns (hide IS bps, strategy on <768px)
- Added: default sort by P&L% descending (best performers at top)
- Fixed: all `var(--slate-*)` references migrated to `var(--arcis-*)` design tokens

#### Validation Page (Task 2)
- Added: `validate-system` command to executor (command queue integration)
- Added: error state display when watch loop offline
- Enhanced: fallback from direct API to command queue for validation runs

#### Training Page (Task 3)
- Added: hero section with large total examples count, weekly count, avg quality
- Added: outcome distribution horizontal stacked bar (WIN/LOSS/TIMEOUT/PASS)
- Added: v2 spec targets vs actual comparison grid
- Added: source breakdown bar chart (historical_backfill, blinded_win, etc.)
- Added: ticker coverage progress bar and regime coverage display
- Added: recent examples table (last 10 with ticker, source, outcome, quality, date)
- Added: graceful handling when outcome_type data pending migration

#### CTO Report (Task 4)
- Added: Phase 1 gate progress bar (X/50 trades)
- Added: minimum-data notices ("Requires N+ closed trades" instead of N/A)
- Added: early win rate callout (100% on <10 trades note)
- Changed: fund metrics only shown when 20+ trades available
- Changed: confidence calibration section shows data requirements when <10 trades

#### Docs Page (Task 5)
- Added: sticky mobile back button ("← Back to documents") always visible on mobile
- Added: two-column desktop layout (300px sidebar + content viewer)
- Added: single-column mobile navigation (list → detail → back)
- Added: document viewer max-width 720px for comfortable reading
- Added: file icon indicators and sidebar card styling

#### Notes Page (Task 6)
- Added: tag filter pills at top for quick category filtering
- Added: pinned-first + reverse chronological default sort
- Added: relative date formatting (e.g., "2h ago", "Mar 15")
- Added: empty state with icon ("No notes yet — add your first note above")
- Changed: textarea placeholder to "Add a note..." for cleaner UX

#### Logs Page (Task 7)
- Added: expandable log rows (click to show details_json as formatted JSON)
- Added: "Run Command" dropdown with common commands (scan, council, collect-data, validate)
- Added: command auto-refresh at 10s (faster than logs at 30s)
- Added: empty state messages for both logs and commands
- Added: CRITICAL level background highlighting (red tint)
- Fixed: all `var(--slate-*)` references migrated to `var(--arcis-*)` design tokens

#### Settings Page (Task 8)
- Added: section icons (Settings2, Shield, Brain, Clock) from lucide-react
- Added: setting descriptions below each label
- Added: "Saved ✓" animation feedback on setting changes
- Added: reset confirmation dialog (two-step: click → confirm)
- Added: system health items in card-style background tiles
- Fixed: all `var(--slate-*)` references migrated to `var(--arcis-*)` design tokens

#### Backend
- Added: `validate-system` command handler in executor.py
- Test count: 1,110 (unchanged)

### Sprint 4E: Post-Review Cleanup & Production Hardening

#### Database Schema
- Added: `strategy_type` column to shadow_trades (DEFAULT 'pullback')
- Added: `outcome_type` and `regime` columns to training_examples
- Added: `level` column to activity_log (DEFAULT 'INFO')
- Added: `build_score_history` CREATE TABLE to create_missing_tables.py
- Added: scripts/migrate_production_db.py (safe, idempotent migration)
- Backfilled: outcome_type on 969/972 training examples from trade outcomes

#### Watch Loop Fixes
- Fixed: Traffic Light now computed during watch loop scans (was only in scan_service)
- Fixed: VIX read from vix_term_structure DB table instead of relying on vix_proxy feature
- Fixed: scan_metrics now recorded for every scan cycle (success, empty, or failed)
- Fixed: Council failure sends Telegram notification (was silent on error)

#### Robustness
- Fixed: weekly_review.py checks column existence via PRAGMA before querying
- Added: schema health section to weekly review (expected vs actual columns)
- Updated: README.md rewritten for Arcis (75 lines, private-repo focused)

#### Tests
- Added: tests/test_db_migration.py (4 tests: idempotent, adds columns, preserves data, creates tables)
- Added: test_vix_30_6_produces_red_vix_component in test_traffic_light.py
- Test count: 1,105 -> 1,110

### Sprint 4C: Dashboard as Control Plane

#### Command Queue System
- Added: pull-based command queue pattern (pending_commands, command_results, config_overrides, log_entries tables)
- Added: bidirectional sync — cloud pulls commands to local, local pushes results to cloud
- Added: command executor with 10 command types (scan, council, collect-data, halt-trading, etc.)
- Added: 5-minute command expiry, 10/min rate limiting, 10KB result truncation
- Added: DBLogHandler that writes WARNING+ to log_entries table (last 500 entries)

#### Config Override System
- Added: dashboard-editable settings with whitelisted keys only
- Added: config overrides merge with YAML defaults (overrides win for whitelisted keys)
- Added: blocked prefixes for API keys, DB paths, and secrets (never editable remotely)
- Added: "Reset to YAML" to clear all dashboard overrides

#### Cloud API Overhaul
- Changed: all stub action endpoints now submit commands via queue instead of returning "must be done locally"
- Added: POST /api/commands/submit, GET /api/commands/{id}/status, GET /api/commands/recent
- Added: GET /api/logs/recent with level and source filtering
- Added: DELETE /api/settings/overrides to clear all overrides
- Changed: POST /api/settings now submits config_change commands via queue

#### Frontend
- Added: editable Settings page with toggle/number inputs and source badges (yaml default vs dashboard override)
- Added: Logs page with filterable log table and recent commands history
- Added: command pending indicator on Dashboard (blue pulsing badge)
- Added: 14th dashboard page (Logs) to navigation

#### Documentation
- Added: ADR 012 — Pull-based command queue architecture decision
- Updated: AGENTS.md counts (169 Python files, 77 test files, 40 DB tables, 55 API routes)
- Added: 15 tests in test_command_queue.py (submission, expiry, whitelist, rate limiting, round-trip)

## [Unreleased] - 2026-03-27/29

### Weekend Mega Sprint (4 sprints: Stabilize + Hotfix + Build + Document)

#### Critical Safety Fixes
- Fixed: safety checks fail closed on errors, not open (#42)
- Fixed: journal closes after broker confirmation, not before (#41)
- Fixed: LLM validator accepts the real `TradePacket` schema (#40)
- Fixed: paper trades are logged as `failed` on submission failure instead of phantom opens (#46)
- Fixed: `/shadow/close` now requires broker exit semantics for Alpaca-backed trades (#45)
- Fixed: council data gatherers query the correct live column names (#44)
- Fixed: Telegram trade notifications use the real packet fields and source labels (#48)
- Fixed: kill-switch tests and training-ingestion tests now run deterministically against the hardened runtime behavior

#### New Features
- Added: event calendar 0-10 continuous risk scoring with sizing multipliers and Telegram alerts
- Added: bracket order health monitor with intraday, pre-market, and post-close verification
- Added: optional GBNF grammar enforcement path for XML commentary generation
- Added: data quality ingestion gates with duplicate detection and batch halt alerts
- Added: Notes page plus cloud CRUD API for pinned, tagged operator notes
- Added: Council.jsx v2 with new agent identities, consensus labels, strategic prompt input, and parameter adjustment history
- Added: HSHS radar chart and live phase-weight display on the Health page

#### Infrastructure
- Added: `scripts/verify_counts.py` for AGENTS.md count verification
- Added: `scripts/schema_report.py` for canonical SQLite schema reporting
- Added: `scripts/generate_dependency_graph.py` and generated `docs/dependency-graph.md`
- Added: `scripts/render_architecture_doc.py` to regenerate the architecture inventory from live code
- Added: strategy-specific pullback timeout support (15 -> 7 days)
- Added: Render sync coverage for the new notes data path
- Added: `bracket_health` and `user_notes` tables to the working schema
- Fixed: SQLite connection handling in earnings enrichment (#52)
- Fixed: kill-switch path handling so safety remains configurable without leaking ambient state into tests (#47)
- Removed: stale council v1 compatibility wrappers from active code paths

#### Documentation
- Added: 11 architecture decision records under `docs/decisions/`
- Rewrote: `docs/architecture.md` from the live module, route, and schema inventories
- Rewrote: `docs/roadmap.md` to consolidate the confirmed March 28-29, 2026 decisions
- Added: `docs/observation-log-template.md` for the Monday-through-Sunday operating rhythm
- Updated: Framework v2.1 research integration notes for risk budgeting, EDGAR fundamentals, operating cadence, and fund-path deferrals
- Documented: council prompt caching was evaluated and intentionally not enabled because the current agent prompts do not share a reusable long prefix

---

## 2026-03-28 — Reliability Sprint + Research-Informed Features

### Critical Safety Fixes
- Risk governor REJECTS trades on exception (was: approve anyway)
- Drawdown returns 15% conservative estimate on error (was: 0%)
- `train-pipeline` CLI runs full 5-step pipeline (was: empty stub)
- LLM validator REJECTS trades on exception (was: continue)
- Bracket order checks child/leg statuses (was: parent only)

### Wiring & Integration
- `data_integrity.py` → scan pipeline (feature validation pre-ranking)
- `canary.py` → trainer (post-retrain evaluation gate)
- `metrics.py` → CTO report (shared calculations)
- All 12 Telegram notifications wired into watch.py
- 44+ bare `except: pass` → logged at WARNING+
- `overnight.py` consolidated (deleted), `broker.py` deleted

### New Features
- **Traffic Light regime:** VIX(20/30) + 200-DMA(3%) + credit spread(0.5σ/1.5σ) → sizing multiplier. 5-day persistence filter.
- **PEAD enrichment:** 5 earnings signals in pullback prompt (conditional on proximity ≤30 days)
- **Implementation Shortfall:** Signal price capture, IS computation on fill, rolling 20-trade alert
- **HSHS live:** 5-dimension health score from database, wired into CTO report + council + API
- **System validator:** 50+ checks, Validation dashboard page
- Independent live trade monitoring (source_filter parameter)

### Research & Architecture
- 6 new research documents (35 total), all strategy decisions confirmed
- Master blueprint v2, Halcyon Framework v2 updated
- Council redesign architecture finalized (vote-first, value tracking)
- 24 deep research prompts generated

---

## 2026-03-27 — Test Gap Closure (Priority 1 — Critical Money Path)

### New Test Files (6)
- **test_statistics.py** (56 tests) — All 11 statistical functions: Sharpe, PSR, bootstrap CI, profit factor, max drawdown, Sortino, Calmar, win rate test, expectancy test, MinTRL
- **test_gate_evaluator.py** (32 tests) — Gate decision logic (PROCEED/EXTEND/REVISION/ROOT CAUSE), metric thresholds, statistical outputs, format_gate_report, boundary conditions
- **test_change_detector.py** (12 tests) — CUSUM symmetric filter, threshold sensitivity, drift detection, performance drift with real SQLite
- **test_llm_validator.py** (18 tests) — All 6 validation checks: ticker universe, entry price deviation, stop below entry, stop distance bounds, position size cap, conviction range
- **test_filing_nlp.py** (17 tests) — Loughran-McDonald sentiment scoring, cautionary phrase detection, filing delta computation, tech-fundamental divergence
- **test_broker.py** (11 tests) — Broker abstraction, AlpacaAdapter methods, factory function, abstract interface

### Full Test Gap Closure (Priority 2-3)
- **test_backtester.py** (7 tests) — Walk-forward backtest with mocked market data, compare_models winner selection
- **test_services.py** (39 tests) — All 7 service modules: scan, shadow, system, training, review, recap, watchlist
- **test_docs_collector.py** (12 tests) — File scanning, title extraction, category assignment, table population
- **test_data_integrity.py** (21 tests) — Feature validation, trade entry validation, universe validation
- **test_activity_logger.py** (8 tests) — Activity log insertion, metadata, missing table handling
- **test_packet_builders.py** (16 tests) — Template packet builder, watchlist builder, EOD recap builder
- **test_llm_writers.py** (10 tests) — Postmortem writer, watchlist narrative generator
- **test_local_api_routes.py** (24 tests) — Packets, training, scan, review route endpoints
- **test_websocket.py** (7 tests) — ConnectionManager connect/disconnect/broadcast

### Coverage Impact
- Tests: 1,035 (up from 657 baseline, +378 new tests)
- All critical money-path, service layer, utility, and API route modules now tested
- Test files: 69 (up from 52)

---

## 2026-03-27 — Dashboard Hardening + Email Digests

### Error Visibility (Part A)
- Every `except Exception` block in cloud_app.py now has `logger.error()` with endpoint name and exc_info
- Every error response now includes an `"error"` key with the exception message
- New `/api/diagnostics` endpoint tests all 23 dashboard tables and reports pass/fail per table

### Test Coverage (Part B)
- Added 29 new cloud API tests covering all previously untested endpoints
- Coverage: activity feed, live trades/summary, council session detail, health score dimensions, settings, market overview, data asset growth, journal, signal zoo, macro dashboard, research papers/digest, training quality, scan metrics, projections, diagnostics, reconcile, CTO report shape
- Total cloud API tests: 67 (up from 38)

### Email Digests (Part C)
- New `src/email/digest_builder.py` — 4 fund-manager-style digests: pre-market (7:30), midday (12:00), EOD (4:15), evening (8:00)
- New `email_mode: digest` — sends exactly 4 emails per day at configured times
- Digest schedule wired into watch.py main tick loop with daily flag resets
- Per-trade and per-scan emails suppressed in digest mode
- Risk alerts still send immediately regardless of mode
- 15 new tests for all 4 digest builders (empty DB, populated, format)

### Telegram (Part D)
- Trade open/close and risk alerts remain immediate
- Per-scan email spam suppressed in digest mode (Telegram notifications unchanged)

---

## 2026-03-27 — Live Trade Reconciliation

### New Features
- **`reconcile-live` CLI Command** — Detects orphaned Alpaca positions (on broker but not in DB) and stale DB records (in DB but not on broker); backfills or marks closed with `--dry-run` option
- **Live Ledger Reconcile Button** — Disabled button with tooltip showing CLI command for local execution

### Fixes
- **Fractional Shares** — `get_live_positions()`, `get_all_positions()`, `get_position()` in alpaca_adapter now use `float(qty)` instead of `int(qty)` to support fractional share positions

### Backend
- New `POST /api/live/reconcile` endpoint (returns cloud_mode error — local CLI only)
- New `src/shadow_trading/reconcile.py` module with `reconcile_live_trades()` function

### Tests
- 5 new tests: dry-run safety, orphan backfill, stale marking, no-discrepancy, paper-trade isolation

---

## 2026-03-27 — Dashboard Polish Sprint

### New Features
- **Research Docs on Cloud** — 35+ markdown docs served via `research_docs` Postgres table with category sidebar and search
- **Council Session Detail View** — Expandable session rows with full agent vote cards, vote distribution chart, dissent highlighting
- **Activity Feed Cloud Polling** — Polling fallback for cloud mode (60s) with event-type icons
- **Live Trade Ledger** — New page for $100 Alpaca live account with equity curve, open/closed tables, header metrics
- **Shadow Ledger Enhancements** — Metrics strip (equity, PF, DD), expandable trade detail rows, 4 viz tabs (equity curve, distribution, sector heatmap, calendar)
- **Hardware Roadmap** — Phase 2 and Phase 4 build specs with costs and unlock descriptions
- **Monthly Cost Timeline** — Visual bar chart of per-phase monthly costs

### Fixes
- **Audit Banner** — Parses raw JSON/code fences from audit summary, shows clean text
- **Shadow Equity** — Uses `shadow/account` endpoint (starting_capital + closed_pnl) instead of potentially wrong `alpaca_equity`
- **KPI Thresholds** — Sharpe/Win Rate show with >= 2 trades (was >= 5)
- **Confidence Calibration** — Shows "< X/50 trades" instead of "--"
- **Rubric Score** — Shows "Not scored yet" with tooltip instead of "n/a"
- **Health Score Dimensions** — All 5 dimensions (Performance, Model Quality, Data Asset, Flywheel, Defensibility) now computed from real data with metric breakdowns
- **Review Tab Removed** — Replaced with Live Ledger in sidebar navigation

### Backend
- 8 new cloud API endpoints: `/api/council/session/{id}`, `/api/activity/feed`, `/api/live/trades`, `/api/live/summary`, `/api/settings` (GET/POST), updated `/api/docs`, `/api/health/score`
- `research_docs` table added to sync pipeline
- Research synthesis wired to Sunday 6 PM schedule
- Daily metric snapshots at 4 PM EOD (not just Saturday)
- Nightly Telegram notification for new research papers

### Components
- New `Tooltip.jsx` — Hover tooltip with 300ms delay
- New `LiveLedger.jsx` — Full live trading ledger page
- Updated `ActivityFeed.jsx` — Cloud polling fallback + event icons
- Updated `Council.jsx` — Expandable session rows
- Updated `ShadowLedger.jsx` — Enhanced with viz tabs + trade expansion

### Roadmap
- Updated to 6 phases (added Phase 6 — Multi-Desk Expansion)
- Phase costs updated: $64 → $125 → $155 → $220 → $500+
- Hardware roadmap section added
