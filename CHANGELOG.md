# Changelog

## [Unreleased]

### Added

- Sprint 6 Wave B T14 (SP-WF-014 + DA-1 + DA-5): production-gate walkforward composition in
  `_evaluate_production_gate` at `src/platform/promotion.py`. Sentinel guard mirroring T9:
  when `WALKFORWARD_GATE_ENABLED=false`, v0.35.0 bypass (DSR AND methodology only). When enabled
  (default): 3-gate AND-composition (DSR AND walkforward AND methodology). Strict no-row policy:
  no walkforward row → `passes=False` (no legacy fall-through). DA-1 freshness cap: sha-match +
  30-day window; on staleness `walkforward_stale=True` + `walkforward_stale_reason` set. Evidence
  symmetric with shadow_trading gate. DA-5 verified: `promote()` persists `walkforward_outcome_state`
  in `gate_result_json`. +8 tests. Spec refs: Sprint 6 plan T14, SP-WF-014, DA-1, DA-5.

- Sprint 6 Wave B T10 (SP-WF-004/SP-WF-010): CLI flag + HTTP read-route extensions.
  (A) CLI: added `--corpus-id <str>` flag to `scripts/backtest/run_walkforward.py` — passes
  through to `WalkForwardConfig.corpus_id` per SP-WF-010; default None preserves backward
  compat. Added `--excess-sharpe-min <float>` flag — passes through to
  `WalkForwardConfig.excess_sharpe_min` per SP-WF-004; default None = raw-Sharpe gate only.
  Both flags are additive (omitting them leaves existing behavior unchanged). (B) HTTP read-route:
  `GET /api/walkforward/runs/{run_id}` already uses `SELECT *` so the T4 columns
  (`gate_version`, `excess_sharpe_min_used`) are returned automatically. (C) +5 tests:
  `tests/scripts/test_run_walkforward_cli.py` (2 new CLI flag tests) and new file
  `tests/api/test_walkforward_route.py` (3 tests for gate_version + excess_sharpe_min_used
  payload inclusion). T8 wired persistence; this task is the read-path + CLI entry-point.

- Sprint 6 Wave B T9 (SP-WF-009): promotion-gate sentinel guard in `_evaluate_shadow_trading_gate`
  in `src/platform/promotion.py`. When `WALKFORWARD_GATE_ENABLED` resolves false, orchestrator
  short-circuits to 2-gate AND-composition (DSR AND methodology only), skipping `_evaluate_walkforward_gate`
  entirely. When enabled (default), full 3-gate composition (DSR AND walkforward AND methodology).
  Evidence dict carries `walkforward_gate_enabled: bool` in all code paths (error, disabled, enabled)
  so audit trail can surface "WF gate DISABLED during this run". +3 tests in
  `tests/platform/test_promotion.py` (wf_disabled_skips_wf, wf_enabled_calls_wf,
  evidence_carries_gate_enabled_flag). This task lands before T14 (production-gate symmetry, Wave 5).

- Sprint 6 Wave B T8 (SP-WF-007/SP-WF-010): runner integration wiring T5/T6 outputs into
  `walkforward_runner.py`. (A) Corpus binding gate: when `config.corpus_id is not None`,
  delegates to the canonical filesystem-based gate at
  `src.evaluation.walkforward._gate_corpus_or_raise(corpus_id, boundaries)` — loads
  `data/corpus/<corpus_id>/manifest.json`, validates `is_admissible()`, and verifies every
  fold's test window falls within the manifest's `walkforward_window`. Raises `RuntimeError`
  on failure (per audit `cutover-impact.md:24` corpora are filesystem-based; no DB table).
  Bypass path preserved when `corpus_id=None`. Captured `manifest_admissibility` and
  `parse_failure_count` surface in `WalkForwardRunResult.evidence`. (B) VIX coverage validator
  wired: `validate_vix_tier_coverage` called once per run over all pooled OOS trades; result
  stored in `evidence['vix_coverage']` (`distinct_tiers`, `passes`, `missing_tiers`).
  `vix_tier_coverage` in `walkforward_results` populated from the structured validator result.
  (C) Persistence of T4 gate-version columns: `gate_version='v2'` written when
  `config.excess_sharpe_min is not None` (raw+excess Sharpe gate active); `'v1'` otherwise
  (raw-Sharpe only, registry default). `excess_sharpe_min_used` populated from
  `config.excess_sharpe_min`. (D) `derived_from_backtest_id: str | None = None` kwarg threads
  through `run_walkforward` → `WalkForwardRunResult` → `persist_run_result` into the T4 column
  of the same name (None default for manual invocations; T13 auto-fire reconciler will populate
  with the source `backtest_results.id`). +6 tests in `tests/platform/rigor/test_walkforward_runner.py`.
  T8(a) `build_walkforward_windows` runner wiring deferred to a follow-up task: the plan
  description called for a `window_count`/anchor-driven invocation path; that requires either
  a new `WalkForwardConfig.window_count` field (T5 module ownership) or a runner-level
  anchor+count kwarg pair (design call on anchor derivation source). Builder remains
  callable directly from T5 callers; no orphan imports left in the runner.

- Sprint 6 Wave B T4 (PR #1092): 3 new columns added to `walkforward_results` table in
  `src/schema/registry.py`: `excess_sharpe_min_used REAL` (per-run rf-adjusted Sharpe threshold;
  null if raw-Sharpe gate only), `gate_version TEXT DEFAULT 'v1'` (framework version string —
  'v1' = raw-Sharpe gate only; 'v2' = raw+excess Sharpe gates active), `derived_from_backtest_id
  TEXT` (backtest_results.id that auto-fire used to spawn the run; null for manual invocations).
  All nullable/defaulted (additive, backward-compat). +3 schema tests.

- Sprint 6 Wave B T2 (PR #1089): `src/evaluation/walkforward.py` refactored to use canonical
  `subtract_trading_days` from `src/scheduler/holidays.py`; local `_subtract_trading_days`
  helper deleted. Behavior-preserving at the call site (anchor is pre-normalized via
  `_next_trading_day`).

- Sprint 6 Wave B T1 (PR #1090): `WALKFORWARD_GATE_ENABLED` env-flag sentinel added to
  `_evaluate_walkforward_gate` in `src/platform/promotion.py`. Default `'true'` (enabled,
  blocking). Recognized values: `'true'`, `'1'`, `'yes'` (case-insensitive) — any other value
  disables the gate (fail-safe semantics; documented in PR #1090 docstring fix-up).

- Sprint 6 Wave B T7 (SP-WF-001 through SP-WF-016): SQLite-side migration verified via
  `validate-schema --fix` against a fresh test DB (`ARCIS_DB_PATH` override, never production).
  Three T4 columns confirmed materialized: `excess_sharpe_min_used REAL`, `gate_version TEXT DEFAULT 'v1'`,
  `derived_from_backtest_id TEXT`. Zero drift confirmed on subsequent `validate-schema` (no-fix run, exit 0).
  All 3 T4 schema tests pass (`test_walkforward_results_has_excess_sharpe_min_used_column`,
  `test_walkforward_results_has_gate_version_column`, `test_walkforward_results_has_derived_from_backtest_id_column`).
  Postgres sync via `python scripts/render_migrate.py` is **operator-owned** — to be run manually after merge.

- Sprint 6 Wave B T5 (SP-WF-001/002/006/010): `corpus_id: str | None = None` field added to
  `WalkForwardConfig` (additive, default None preserves backward compat; T8 will wire the runner
  gate). `build_walkforward_windows(anchor, n_windows, is_trading_days, oos_trading_days,
  embargo_trading_days)` builder added to `walkforward_config.py` — generates non-overlapping
  IS/OOS window tuples using canonical `subtract_trading_days` arithmetic (no calendar-day
  approximation). Enforces `train_end < test_start` invariant. `DEFAULT_WINDOWS` unchanged.
  +4 tests in `tests/platform/rigor/test_walkforward_config.py`.
- Sprint 6 Wave B T6: `VixCoverageResult` dataclass + `validate_vix_tier_coverage` function
  added to `src/platform/rigor/walkforward_power.py`. Wrapper layer over
  `walkforward_metrics.vix_tier_of` that returns structured pass/fail evidence
  (`distinct_tiers`, `passes`, `missing_tiers`) for downstream persistence
  by T8 (runner integration). +4 tests in `tests/platform/rigor/test_walkforward_power.py`.

- Sprint 6 Wave B T3 (SP-WF-004): `excess_sharpe_min: float | None = None` field added to
  `WalkForwardConfig` (additive, default None preserves backward compat). When set, wired into
  `compute_window_metrics` as an additional rf-adjusted excess-Sharpe gate using
  `canonical_sharpe.rf_adjusted_excess_sharpe` as the source of truth. `WindowMetrics` gains
  three new default-None fields: `excess_sharpe`, `passes_excess_sharpe`, `excess_sharpe_fail_reason`.
  +3 tests in `tests/platform/rigor/test_walkforward_metrics.py`.

### Changed

- Sprint 6 Wave A — SP6 catch-all sweep (7 PR-review follow-ups from Sprint 5):
  - **WA1** (`_get_finnhub_key` extraction, #1082/#1083/#1084): extracted the
    12-line `_get_finnhub_key` helper from 6 collectors (institutional_ownership,
    filings_sentiment, press_releases, insider, short_interest, analyst) into
    `src/data_collection/_finnhub_shared.py`. Each collector now imports
    `get_finnhub_key as _get_finnhub_key` to preserve existing test patch targets.
    +1 test in `tests/data_collection/test_finnhub_shared.py` (env-precedence +
    YAML fallback + None-on-neither).
  - **WA2** (`price_target` matrix, #1085): added `"price_target"` to
    `_FEATURE_MATRIX['fundamental-1']` in `src/data_enrichment/finnhub_plan.py`.
    Activates the `analyst_collector.py:147` gate on paid plans (Finnhub
    fundamental-1 tier includes `/stock/price-target`). Removed `"price_target"`
    from `_REVERSE_INVARIANT_ALLOWLIST` in the T26 AST scanner test. +1 test.
  - **WA3** (PE quality thresholds, #1084): `_derive_quality_flag()` in
    `src/data_enrichment/financials.py` now reads PE bounds from
    `data_enrichment.fundamental_quality_thresholds.{pe_min,pe_max}` in
    `config/settings.example.yaml`, with fallback to hardcoded 2.0/200.0 defaults
    for backward-compat. +2 tests in `tests/data_enrichment/test_financials.py`.
  - **WA4** (env-pollution test fix, #1085): added
    `monkeypatch.delenv("FINNHUB_PLAN", raising=False)` to
    `test_feature_matrix_distinguishes_free_and_premium` in `tests/test_enrichment.py`
    so the test passes on machines with `FINNHUB_PLAN` set in `.env`. Moved the
    entry in `docs/audits/known-pre-existing-failures.md` to "Recently cleared".
  - **WA5** (Decision 27 lock test, #1083): new structural test
    `tests/data_collection/test_filings_sentiment_revision_semantics.py` locks the
    current `action='ignore'` behavior (second upsert of same PK with different
    score silently drops the revision). Test PASSES now; inverts if/when
    `action='replace'` is adopted.
  - **WA6** (migration utils extraction, #1067): created
    `scripts/_shared_migration_utils.py` with `topo_sort_tables` (uses
    `graphlib.TopologicalSorter`, Python 3.9+ stdlib), `redact_password`, and
    `confirm` helpers. Both migration scripts (`sqlite_to_pg_migrate.py`,
    `render_to_local_migrate.py`) import from the shared module. SQLite-to-PG
    migration now applies topo sort before migrating (was missing, PR #1067 fix).
    +6 tests in `tests/scripts/test_shared_migration_utils.py`.

## [v0.35.0] - 2026-05-13 — Sprint 5 close: cutover stabilization + notification policy + LLM packet enrichment + dual-GPU disposition

Sprint 5 delivered 15 named tasks across 6 waves (C cutover-stabilization,
C7a packet sections, C7b plan-gated Finnhub enrichment + AST scanner,
D notification policy/digest/silence, E dual-GPU disposition, F dev tooling)
plus 14 trackers (#54/#56/#69/#92/#93/#94/#101/#103/#108/#109/#110/#111/#115)
plus pre-T16 hardening (#1081). Final commits: `2b5e7cab` (T26 / Wave C7b
COMPLETE) → tag `v0.35.0` at this PR's squash-merge.

**Key architectural deliveries:**
- Phase-3-revised cutover from SQLite → local Postgres (localhost:5433/halcyon)
  with `_RowFactoryCursor` + `_scalar` + `engine_aware_upsert` + 82-site
  mechanical-replacement sweep; `ARCIS_PG_CUTOVER_ENABLED` env gate routes
  `connect_db()` to the right engine.
- 7th-generation AST-based structural guardrail (`test_finnhub_plan_runtime_coverage`,
  joining the M4 / wrapper / `_scalar` / fetchone-int / policy-purity /
  fetchall-listcomp / conflict-marker scanners).
- Wave D notification subsystem (policy gate → digest queue → safe_send
  verdict-dispatch → alert silence detector with engine-agnostic SQL).
- Wave C7a/C7b LLM packet enrichment (4 council sections + 4 plan-gated
  Tier-2 sections + DATA CONTEXT header for plan-gated-vs-data-gap disambiguation).
- Dual-GPU workload-separation deferred to first post-Sprint-5 maintenance
  window per Wave E disposition doc (RTX 3060 + RTX 3090 split design preserved).

### Added

- `tests/test_no_conflict_markers_in_repo.py` (#109): structural CI test that scans `src/`, `tests/`, `scripts/`, `docs/`, `config/`, `.github/` for git conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`) and fails if any are found outside the allowlist. Closes the marker-class that bit twice in 24h on 2026-05-12 (PR #1065 hotfix, PR #1069 hotfix) when Edit-tool silently failed on multi-line `old_string` matches during rebase conflict resolution. Also resolves a previously unknown stranded marker discovered at `docs/archive/quality/improvement_log.md:8` during this scan.
- `scripts/sqlite_to_pg_migrate.py` (#111): interactive YES-prompt confirmation gate added before wet-write phase. Symmetric to render_to_local_migrate.py's `_confirm()` helper added in #1067. Closes the safety gap surfaced 2026-05-12 when the script ran against a stale `DATABASE_URL` pointing at Render PG (instead of intended local PG) and shipped data in the wrong direction. The `--yes` CLI flag skips the prompt for scripted/CI use. Dry-run path unchanged (no confirmation needed for read-only).
- T13 (Wave D D4): `_html_escape` applied to `notify_regime_alert` (#93) and `notify_streak_alert` (#94) to prevent HTML injection in Telegram alerts. Pattern mirrors Sprint 4 T5 (notify_risk_alert / notify_exposure_alert).
- Pytest isolation conftest fixture sets `ARCIS_NOTIFICATION_SOURCE='pytest:<worktree>'`, monkeypatches `_send_single` to a `_null_router` stub, and clears `ARCIS_TELEGRAM_TOKEN` per-test — prevents tests from accidentally calling the real Telegram API (#101).
- 5 new tests in `tests/notifications/test_html_escape_siblings.py` including an AST guardrail that scans `notify_regime_alert` and `notify_streak_alert` for unescaped f-string interpolations.
- T14 (Wave D D5): `src/monitoring/alert_silence.py` — `check_alert_silence(now_et, threshold_minutes=60)` detects notification silence during market hours by reading UNION of notifications_sent (MAX sent_at), notifications_digest_queue (MAX flushed_at), AND notifications_digest_queue (MAX created_at — proves watch loop alive during digest-only quiet hours). Emits via `safe_send(event_type='alert_silence', severity='high')` + writes platform_events row for forensic trail. Wired as 5-min `tick_alert_silence` handler in WatchLoop.
- `src/scheduler/holidays.py::is_market_open(now_et)` — extracted from `WatchLoop._is_market_open` for re-use across monitoring code. WatchLoop method becomes a thin delegate. +3 unit tests in `tests/scheduler/test_holidays.py`. +5 tests in `tests/monitoring/test_alert_silence.py`.
- T14 fix-up (PR #1076 review, operator 2026-05-13): rewrote `_query_max_signal` SQL from `SELECT MAX(ts), source FROM (...)` (SQLite-only valid — PG rejects with `psycopg2.errors.GroupingError: column "source" must appear in the GROUP BY clause`) to `SELECT ts, source FROM (...) u ORDER BY ts DESC NULLS LAST LIMIT 1` (engine-agnostic; works on both SQLite and PostgreSQL). Original form would have caused silent infinite-retry loop in `tick_alert_silence` post-cutover (#1055/#1056). Added +3 tests in `tests/monitoring/test_alert_silence.py`: empty-tables → `(None, "none")`, most-recent-source selection, and PG-mode regression test `test_query_max_signal_works_on_pg` (skipped unless `DATABASE_URL=postgres://...` + `ARCIS_PG_CUTOVER_ENABLED=1`).
- `src/notifications/telegram.py::notify_alert_silence(last_seen, minutes_silent)` — dedicated Telegram formatter for alert silence events; replaces stub `notify_system_event` mapping in `_EVENT_MAP`.

### Changed

- T19 (Wave C7a.3): `=== RECENT ATTRIBUTION ===` section at index 15 (after T18's HISTORICAL CREDIBILITY). Enricher reads `attribution_trades` joined to `recommendations` over a configurable lookback window (default 30 days, overridable via `config['data_enrichment']['attribution_window_days']`). Computes setup-class W/L rate (closed trades only, filtered by `setup_class`), ticker-specific mean PnL, and similar-ticker (sector-match, excluding self) mean PnL. Closed trades only: filters on `llm_portfolio_pnl_pct IS NOT NULL`. No-recent-trades fallback: `(No attribution trades in window)`. Three private helpers (`_setup_class_win_rate`, `_ticker_mean_pnl`, `_similar_sector_mean_pnl`) keep the main function under the 60-line limit. Tests in `tests/llm/test_packet_recent_attribution.py` (+3).
- T20 (Wave C7a.4): `=== STRATEGY CONTEXT ===` header preamble (prepended BEFORE TECHNICAL DATA in the prompt — structurally different from indexed sections T17-T19). Enricher reads `strategy_registry` keyed by the `shadow_trades.strategy_id` FK (T2/#56). Populates `strategy_status` (current_status) and `strategy_parent_name` (display_name). NULL-strategy_id fallback `Strategy: (unassigned - legacy trade)` for legacy trades pre-dating the T2 FK wiring. T2 hard dependency verified — `shadow_trades.strategy_id` FK present in `src/schema/registry.py` (L320-L323, L336-L337 with `initially_deferred=True`). Tests in `tests/llm/test_packet_strategy_context.py` (+3). Wave C7a deliverables complete (PR #1077 T17+T18 plus this PR's T19+T20); closes part of #102.
- T15 (Wave E): Filed `docs/audits/2026-05-12-dual-gpu-ideation/disposition.md` — dual-GPU workload separation is deferred to first post-Sprint-5 maintenance window. Updated 4 stale-text references in the canonical spec inline: test-floor 3682→5400, Sprint 6→post-Sprint-5, Unsloth→Transformers+PEFT+TRL, NUM_PARALLEL=1→4 (per RTX 3090 swap, memory project_gpu_upgrade). Test-floor target corrected from initial 5350 to 5400 per PR #1073 review (operator flagged v2 vs v3 closeout plan target).
- T25 (Wave C7b.5): `analyst_collector` nightly cap is now plan-conditional. `fundamental-1` tier → 100 tickers/night (well within the 30 API calls/sec global rate-limit); free tier → 20 tickers/night (preserved current behavior). `_get_nightly_cap` uses `get_finnhub_plan(config)` directly rather than `finnhub_plan_supports()` because the cap is a tier-numeric property, not a binary feature gate (operator decision 2026-05-13 post-review of initial implementation). Rate-limit source: https://finnhub.io/docs/api/company-dps-estimates retrieved 2026-05-13 — "On top of all plan's limit, there is a 30 API calls/second limit." Closes part of #102 — Wave C7b.5 deliverable.
- Wave C7b Batch 1 (T21+T22): plan-gated Finnhub collectors for institutional ownership + filings sentiment, surfaced through two new packet sections.
  - T21 (C7b.1): `src/data_collection/institutional_ownership_collector.py` — plan-gated Finnhub `/stock/institutional-ownership` collector. Writes one aggregated row per ticker (total_shares, num_holders, top-5 concentration, qoq_delta) into the new `institutional_holdings` table. Gate at function entry on `finnhub_plan_supports('institutional_ownership', config)`; no API call on free-tier (Decision 30). New `=== INSTITUTIONAL FLOW ===` packet section at index 4.5 (between SECTOR RELATIVE and FUNDAMENTAL SNAPSHOT). Three render states: (a) plan supports + data present → full render with data age; (b) plan supports + no data → `(No data yet - collector pending)`; (c) plan does not support → section ABSENT. Nightly tick wired in `src/scheduler/overnight.py`. +5 tests in `tests/data_collection/test_institutional_ownership_collector.py`.
  - T22 (C7b.2): `src/data_collection/filings_sentiment_collector.py` — plan-gated Finnhub `/stock/filings-sentiment` collector. Writes one row per filing (filing_type, filed_at, sentiment_score, sentiment_label) into the new `filings_sentiment` table. Distinct retrieval cadence from `edgar_filings` (Decision 27 — separate tables, separate collectors). Gate at function entry on `finnhub_plan_supports('filings_sentiment', config)`; no API call on free-tier (Decision 30). New `=== MATERIAL EVENTS ===` packet section at index 7.5 (between RECENT NEWS and MACRO CONTEXT). Section is a composition wrapper around sub-blocks — T22 seeds with the filings_sentiment sub-block. Composition rule: section header omits entirely if no sub-block has plan-support. T23 adds the press_releases sub-block. Nightly tick wired in `src/scheduler/overnight.py`. +5 tests in `tests/data_collection/test_filings_sentiment_collector.py`.
  - T23 (C7b.3): `src/data_collection/press_releases_collector.py` — plan-gated Finnhub `/press-releases` collector. Writes one row per press release into the new `press_releases` table. Distinct catalyst category from RECENT NEWS pipeline (Decision 27). Gate on `finnhub_plan_supports('press_releases', config)`. Extends T22 MATERIAL EVENTS section with the second sub-block. Composition rule honored: section renders with only present sub-block when only one of {filings_sentiment, press_releases} has plan-support. Nightly tick wired in `src/scheduler/overnight.py`. +6 tests in `tests/data_collection/test_press_releases_collector.py`.
  - T24 (C7b.4): `src/data_enrichment/financials.py` (NEW) — runtime read-only enricher reading existing nightly-export sink `data/finnhub_fundamentals/<ticker>.json` (no Finnhub API call at runtime). Plan-gated on `stock_financials`. `enrich_stock_financials` sets `_stock_financials_plan_supports` (mirrors institutional/filings/press_releases sibling enrichers) so DATA CONTEXT can distinguish plan-gated absence from a transient sink-missing data-gap. Enriches FUNDAMENTAL SNAPSHOT in-place with live P/E, debt/equity, gross margin, ROIC, quality flag. Free-tier preserves existing last-known cached fallback. DATA CONTEXT header (spec 4.8.1): prepended at prompt top when at least one Tier-2 section (INSTITUTIONAL FLOW, MATERIAL EVENTS, FUNDAMENTAL SNAPSHOT live-enrichment) omits, distinguishing plan-gated absences from data gaps. `_collect_tier2_omissions` checks the plan flag (not data presence) for all three Tier-2 sections — closes the Decision 32 falsifiability gap operator flagged in PR #1084 review (2026-05-13). Stale-data ageing (spec 4.8.2) surfaces `*_age_days` when above threshold (default 7d, overridable via `data_enrichment.stale_data_threshold_days`). +4 tests in `tests/data_enrichment/test_financials.py` + 5 tests in NEW `tests/llm/test_data_context_header_trigger.py` (3 + 2 plan-vs-data-gap regression locks).
  - Closes #102 — Wave C7b complete pending T26 AST scanner.
- T26 (Wave C7b.6): `tests/test_finnhub_plan_runtime_coverage.py` (NEW) — two-way AST scanner enforcing runtime coverage of `_FEATURE_MATRIX`. Forward invariant: every fundamental-1 feature has at least one `finnhub_plan_supports(<feature>, ...)` call site in src/ (closes the "stuck on shelf" class — feature defined but no runtime caller). Reverse invariant: every `finnhub_plan_supports()` call site references a feature in `_FEATURE_MATRIX['fundamental-1'] ∪ ['free']` (closes the "gate calls unknown feature so always returns False" class). Both invariants tolerate narrow documented allowlists: `_UNWIRED_FORWARD_ALLOWLIST` (company_executive, filings, fund_ownership, stock_ownership — reserved-in-matrix-for-downgrade-ceremony but unwired) and `_REVERSE_INVARIANT_ALLOWLIST` (price_target — analyst_collector.py latent gate-off, deferred per operator decision 2026-05-13). Includes 4 self-tests that exercise the diff/scanner logic against synthetic source-tree fixtures, proving the test catches the failure modes it claims. To make the forward invariant pass, added defensive plan-gates at 6 free-tier call sites (no behavior change on current plans — company_news / insider_transactions / recommendation_trends / short_interest are in both `'free'` and `'fundamental-1'`, so gates are no-ops; guards against future plan-tier additions that might exclude these features): `src/data_enrichment/news.py::fetch_recent_news` + `fetch_historical_news` (company_news), `src/data_enrichment/insiders.py::fetch_insider_activity` (insider_transactions), `src/data_collection/insider_collector.py::collect_insider_transactions` (insider_transactions), `src/data_collection/short_interest_collector.py::collect_short_interest` (short_interest), `src/data_collection/analyst_collector.py::collect_analyst_estimates` (recommendation_trends). Test-has-teeth verified (revert→FAIL listing 4 missing features, re-apply→6/6 PASS). Updated `tests/test_data_collectors.py::test_collect_skips_price_target_when_plan_does_not_support_it` to differentiate the mock by feature (recommendation_trends=True, price_target=False) so it tests the price-target gate in isolation rather than the new aggregate behavior. Closes #102 — Wave C7b deliverables COMPLETE.

### Fixed

- `DigestQueue.pending_count` and `DigestQueue.abandoned_count` now use `_scalar(row)` from `src.utils.db` instead of `.fetchone()[0]` positional indexing — the positional form raises `KeyError(0)` on PG (post-cutover) because `PostgresConnectionWrapper` returns `RealDictCursor` rows. Pre-existing leak from PR #1072 merge caught by `test_no_fetchone_int_index_in_pg_unsafe_files` AST scanner during operator's PR #1076 review (2026-05-13).
- `scripts/sqlite_to_pg_migrate.py`: added `connect_timeout=30` to the wet-write `psycopg2.connect` at line 286 (symmetric with `render_to_local_migrate.py` lines 345-346 which already had it from PR #1070 hardening). Closes the hang-on-Render-outage failure mode operator flagged in PR #1080 review.

- `DigestQueue` now correctly round-trips dataclass payloads through enqueue→DB→flush→dispatch. Three coordinated fixes: (a) `enqueue` calls `dataclasses.asdict()` before `json.dumps` to support dataclass payloads; (b) `flush()` injects `event_type` and `severity` from DB columns into the dispatched dict (the dispatcher's contract — previously flush only selected `id, payload_json, flush_attempts`, so `_real_dispatcher` in watch.py got `event_type=""` and silently failed all digest dispatches); (c) `_do_dispatch` adds `_PAYLOAD_CLASS_MAP = {"trade_opened": TradeOpenedPayload, ...}` and reconstructs the dataclass from dict before invoking `notify_*` (which uses attribute access — previously `notify_trade_opened` would crash with `AttributeError: 'dict' object has no attribute 'ticker'` on the json.loads round-trip). Together these close the production bug where `safe_send(event_type, payload=TradeOpenedPayload(...))` during quiet hours would have crashed at flush time. Regression-locked by `test_full_roundtrip_trade_opened_dataclass_enqueue_to_dispatch`, `test_flush_injects_event_type_into_row_payload`, and `test_flush_injects_severity_into_row_payload`. Latent bug surfaced by operator's PR #1071 review (#115).

- T12 fix-up: patched 13 pre-existing tests in `tests/notifications/test_safe_send.py`, `test_safe_send_hooks.py`, and `test_telegram_payload_wiring.py` to patch `_load_config_for_safe_send` and `_now_et_for_safe_send` so policy gate returns `verdict=send`. Tests were written for the pre-T12 direct-dispatch contract; the new policy gate could route `trade_opened`/medium -> `digest` during quiet hours, triggering `TypeError: Object of type TradeOpenedPayload is not JSON serializable` in `DigestQueue.enqueue`. Underlying JSON-serialization gap tracked as #115 (Sprint 5 closeout). Per PR #1071 review (operator, 2026-05-13).

### SP5 Wave D T12 fix-up — Security (2 medium, 3 low) + QA (3 nits) from PR #1071 review

Addresses all 8 actionable findings from the combined Security (REQUEST_CHANGES) and QA (APPROVE with nits) review of T12 base commit `f2ce5f2`.

#### Security Medium 1 fixed — DB connection leak in digest path

`safe_send`'s digest branch now wraps `_get_digest_db_conn()` in a `with` context manager, ensuring the connection is always released after `DigestQueue.enqueue` — even on exception. Previously the connection leaked on every digest enqueue, creating burst-load DoS potential.

#### Security Medium 2 fixed — Sensitive payload exposure in escalated email

`_do_dispatch_escalated` now applies `_redact_token(repr(payload))[:1024]` before writing to the email body. The bare `f"Payload: {payload}"` format (which dumped raw kwargs including potential bot tokens into mail archives) is replaced with a redacted, truncated representation plus a forensic SQL query for audit trail. The exception log line also applies `_redact_token(str(e))`.

#### Security Low 3+QA Nit 2 fixed — force=True audit log + structural dedup

`safe_send`'s force=True path is now a single guard block (force-first) instead of the previous structurally-duplicated pattern (initial decision built on lines 1571–1582, then unconditionally overwritten on 1584–1591). The force-first block emits `logger.info("[NOTIFICATIONS] force_bypass: ...")` for audit visibility. The `config = None` initializer ensures the `config` name is always bound before the verdict-dispatch chain.

#### Security Low 4 fixed — Narrow exception in escalated-email path

`_do_dispatch_escalated`'s email branch now catches `(urllib3.exceptions.HTTPError, requests.exceptions.RequestException, socket.timeout, OSError)` matching `_do_dispatch`'s pattern. The previous bare `except Exception` suppressed `ImportError`, `NameError`, `AttributeError` — exactly the import-time bugs the module docstring says must propagate.

#### Security Low 5 fixed — `_EVENT_MAP` immutability

`_EVENT_MAP` is now `MappingProxyType(_EVENT_MAP_MUTABLE)`. Runtime code cannot mutate the event map. `MappingProxyType` supports `__getitem__` and `__contains__` so all existing lookup sites continue to work. `_KNOWN_EVENT_TYPES = frozenset(_EVENT_MAP)` is unchanged.

#### QA Nit 1 fixed — tick_digest_queue replaces inline NotificationsConfig with validated config

`tick_digest_queue` now calls `_load_config_for_safe_send()` (same path used by `safe_send`) instead of constructing `NotificationsConfig` inline from raw dict fields. This ensures config validation runs through the same `_load_notifications_config` validator and eliminates the maintenance hazard of keeping two parallel construction sites in sync. Function shrank from 62 to 51 lines (now under the 60-line limit; removed from known_violations.json oversized_functions).

#### QA Nit 3 fixed — Dead RuntimeError patch cleaned up

`test_safe_send_handles_dispatch_exception` now only patches `ConnectionError` (the actual network exception being tested). The dead outer `RuntimeError("boom")` patch that was immediately shadowed by the inner ConnectionError patch is removed.

#### Regression-lock tests added

- `test_safe_send_digest_path_closes_connection_after_enqueue` — verifies `__exit__` is called on the digest DB connection. Fails without `with` wrap.
- `test_escalated_email_body_redacts_bot_token_in_payload` — verifies bot token pattern is absent from escalated email body. Fails without `_redact_token`.
- `test_safe_send_propagates_non_network_exceptions` — verifies `RuntimeError` from dispatch code propagates uncaught (non-network exceptions must not be swallowed).

#### Files changed

- **`src/notifications/telegram.py`**: MappingProxyType wrap, _do_dispatch_escalated body redaction + narrow exception, safe_send force-first guard + digest with-wrap + audit log.
- **`src/scheduler/watch.py`**: tick_digest_queue replaced inline NotificationsConfig build with `_load_config_for_safe_send()`.
- **`tests/notifications/test_safe_send_wiring.py`**: 3 new regression-lock tests, dead RuntimeError patch removed.
- **`tests/notifications/test_safe_send_dual_rep_consolidated.py`**: updated isinstance check from `dict` to `Mapping` to accommodate MappingProxyType.
- **`config/known_violations.json`**: telegram.py line count updated (1625→1651), safe_send function line count updated (91→101), watch.py line count updated (2445→2432), tick_digest_queue removed from oversized_functions (now 51 lines, under limit).

### SP5 Wave D T12 — safe_send verdict-dispatch wiring + #110 security fold-in (D3)

Wires `safe_send` to consult T10's `should_dispatch` policy gate on every call; branches on `PolicyDecision.verdict` (send/digest/mute/escalate); replaces T11's stub dispatcher in `tick_digest_queue` with a real `_do_dispatch`-flavor dispatcher; consolidates the dual-representation tension between `_KNOWN_EVENT_TYPES` and the local `event_map` inside `safe_send` into a single `_EVENT_MAP` module-level dict. Also folds in tracker #110 — nested `bypass_severity` check + `routing_overrides.<event_type>.*` key allowlist.

#### Added

- **`src/notifications/telegram.py` — `_EVENT_MAP`**: module-level dict (single source of truth) mapping event_type strings to notify_* functions. `_KNOWN_EVENT_TYPES` is now derived as `frozenset(_EVENT_MAP)` — the two representations can never diverge.
- **`src/notifications/telegram.py` — `_check_nested_bypass_severity`**: recursive walk of the notifications config section; raises `NotificationsConfigError` with the offending key path if `bypass_severity` appears anywhere (including inside `routing_overrides` sub-dicts). Called once in `_load_notifications_config`.
- **`src/notifications/telegram.py` — `_ALLOWED_ROUTING_OVERRIDE_KEYS`**: frozenset `{'telegram', 'email', 'escalation_after_attempts'}`. Used to validate each routing override entry's dict keys; unknown keys raise `NotificationsConfigError` with the exact key and event_type path.
- **`src/notifications/telegram.py` — `_load_config_for_safe_send`, `_now_et_for_safe_send`, `_get_digest_db_conn`, `_resolve_source_tag`**: testability hooks replaceable by `patch()`. Production paths load config from `settings.yaml`, return `datetime.now(ET)`, open `DB_PATH` connection, and return `"safe_send"` respectively.
- **`src/notifications/telegram.py` — `_do_dispatch`**: dispatch helper for SEND verdict. Looks up the notify_fn via the module object (not the frozen dict reference) so test patches on notify_* take effect. Catches network exceptions, logs warning, calls `_record_send_failure`.
- **`src/notifications/telegram.py` — `_do_dispatch_escalated`**: dispatch helper for ESCALATE verdict. Calls telegram channel via `_do_dispatch`, then attempts email via `src.email.notifier.send_email`. Sequential (not parallel) — failure visibility is more important than throughput for escalated alerts. Returns True if any channel succeeds.
- **`src/notifications/telegram.py` — `safe_send` rewrite**: adds `force: bool = False` keyword arg; pops `severity` from kwargs (default `'normal'`); calls `_load_config_for_safe_send` + `_now_et_for_safe_send` to get routing context; delegates verdict-dispatch to `_do_dispatch`/`DigestQueue.enqueue`/log/`_do_dispatch_escalated`. KeyError on unknown event_type raised BEFORE policy gate.
- **`src/notifications/telegram.py` — module-level `should_dispatch` import**: imported from `policy` at module level so tests can patch `src.notifications.telegram.should_dispatch`.
- **`src/scheduler/watch.py` — `tick_digest_queue` dispatcher replacement**: replaces `_stub_dispatcher` with `_real_dispatcher` that calls `_do_dispatch(event_type, kwargs, severity, ["telegram"])` directly (bypasses safe_send → policy re-gating, since rows were policy-gated at enqueue time). Config now read from `self.config` instead of hard-coded defaults.
- **`tests/notifications/test_safe_send_wiring.py`**: 6 tests — send path, digest path, mute path, force bypass, dispatch exception, escalate path.
- **`tests/notifications/test_load_notifications_config_strict.py`**: 4 tests — nested bypass_severity raises, unknown routing override key raises with path, escalation_after_attempts accepted, string-not-dict raises.
- **`tests/notifications/test_safe_send_dual_rep_consolidated.py`**: 2 tests — `_EVENT_MAP` non-empty at import, `_KNOWN_EVENT_TYPES == frozenset(_EVENT_MAP.keys())`.

#### Changed

- **`src/notifications/telegram.py` — `_load_notifications_config`**: extended with `_check_nested_bypass_severity` call + routing_overrides key allowlist validation (type check + unknown key detection). Existing top-level `bypass_severity` check kept for clear error messaging.
- **`config/settings.example.yaml`**: updated `escalation_after_attempts` comment from "T12 D3 will use this" to a live description.
- **`docs/operator-guide.md`**: added safe_send verdict-dispatch matrix, updated Decision 20 note for recursive bypass_severity lockdown, added routing_overrides key allowlist section.
- **`config/known_violations.json`**: updated `src/notifications/telegram.py` line count and `safe_send` / `_load_notifications_config` function line counts to reflect T12 additions.

#### Design choices (DR-02 explicit uncertainty resolution)

- **escalate dispatch sequential vs parallel**: chose sequential. Escalated alerts are high-urgency; knowing which channel failed (vs which succeeded) is more operationally useful than saving 50ms. If telegram succeeds but email fails, the log clearly shows which channel needs investigation.
- **safe_send `severity` kwarg vs positional**: kept as a kwarg (`severity="high"`) to avoid changing all existing call sites. Call sites that don't pass `severity` default to `'normal'`.
- **_do_dispatch re-resolution via `sys.modules[__name__]`**: necessary because `_EVENT_MAP` stores function references frozen at import time; patching `notify_scan_complete` at the test level doesn't update the frozen reference. Re-resolving by name through the module respects patches. Production overhead is negligible (one dict lookup per dispatch).

### SP5 Wave D T11 — Notification digest queue (D2)

Implements the persistence layer for `PolicyDecision(verdict='digest')` outputs. The watch loop drains the queue every `digest_flush_minutes` minutes (default 60). T11 owns the queue mechanics, schema, and watch.py flush hook; T12 (D3) will wire `safe_send` to enqueue.

#### Added

- **`src/notifications/digest_queue.py`**: `DigestQueue` class with `enqueue`, `flush`, `mark_flush_failed`, `pending_count`, `abandoned_count` methods. `enqueue` validates `event_type` against `_KNOWN_EVENT_TYPES`. `flush` atomically transitions `pending` → `in_progress` → `sent|pending(retry)|abandoned`. `mark_flush_failed` sets `flush_status='abandoned'` with `flush_error` for operator forensic recovery. `FlushResult(successes, failures, abandoned)` returned from flush.
- **`src/schema/registry.py` — `notifications_digest_queue` TableDef**: 10-column table (`id`, `event_type`, `severity`, `payload_json`, `source_tag`, `created_at`, `flushed_at`, `flush_status`, `flush_attempts`, `flush_error`). Indexes on `flush_status` and `created_at`. `sync_to_postgres=True`, `sync_mode='incremental'`.
- **`src/scheduler/watch.py` — `tick_digest_queue`**: periodic flush hook. Cadence controlled by `notifications.digest_flush_minutes` (default 60). Stub dispatcher logs payload (T12 will wire real `safe_send`). Done-flag inside `try` per CLAUDE.md rule. Backoff keyed to `'digest_queue'`. Placed after `tick_drift_detector`, before T14's future tick.
- **`src/notifications/policy.py` — `NotificationsConfig.digest_flush_minutes`**: new field (default 60); consumed by watch.py tick cadence.
- **`src/notifications/telegram.py` — `_load_notifications_config`**: parses `digest_flush_minutes` with bounds `[5, 1440]`; raises `NotificationsConfigError` on out-of-range.
- **`config/settings.example.yaml`**: added `notifications.digest_flush_minutes: 60` with range comment.
- **`docs/operator-guide.md`**: added "Digest queue" subsection under "Notifications routing" with config knob, lifecycle docs, forensic query, and manual recovery SQL.
- **`tests/notifications/test_digest_queue.py`**: 10 tests covering enqueue/flush happy paths + boundary conditions.
- **`tests/notifications/test_digest_queue_atomicity.py`**: 4 tests covering `mark_flush_failed` + flush-then-fail recovery + abandoned-row persistence.

#### T11 Fix-up (Security + QA review responses — applied on top of 69fe912)

- **Security MEDIUM**: `_dispatch_one_row` and `mark_flush_failed` now apply `_redact_token()[:500]` before writing `flush_error`. Prevents Telegram bot token leakage via `/bot<TOKEN>/sendMessage` URLs in HTTP exception strings, which sync to Postgres via `sync_to_postgres=True`. `_redact_token` imported from `src.notifications.telegram` (project convention established 2026-04-24).
- **Security LOW**: `enqueue` now caps `source_tag` at 64 chars (`source_tag[:64]`) before INSERT. Defense-in-depth on tagging metadata.
- **QA nit 1**: `test_flush_then_fail_recovery` assertion tightened from `in ("pending", "abandoned", "sent")` to `== "pending"` with a failing dispatcher. The original accepted 3 of 4 possible states; the new assertion is specific to the crash-recovery-with-retries-remaining path.
- **QA nit 3**: `flush_error` ColumnDef description updated to reflect actual state machine (`abandoned` only, no `failed`) and document the redaction + cap discipline for future authors.
- **Regression-lock**: `test_flush_error_redacts_bot_token_in_exception_string` added to `tests/notifications/test_digest_queue.py`. Fails with "Bot token leaked into flush_error" if `_redact_token` is removed from `_dispatch_one_row`.

### SP5 Recovery — Render Postgres → local Postgres data migration script

Production incident 2026-05-12 ~18:15 ET: NSSM ArcisWatchLoop sent a "startup blocked" Telegram notification and entered a restart loop. Root cause: the prior recovery this session ran `scripts/sqlite_to_pg_migrate.py` with the operator's shell `DATABASE_URL` pointing at the **Render** Postgres URL (pre-cutover carryover), not the post-cutover-canonical local PG at `localhost:5433/halcyon`. 1.46M+ rows were silently copied to Render PG instead of local PG. Local PG stayed empty. The watch loop's `initialize_database()` crashed on `UPDATE shadow_trades` (UndefinedTable) and NSSM auto-restarted into a loop.

Recovery: built a new migration script with a YES-prompt guard, ran it, restarted NSSM cleanly. 2,196,965 rows / 71 tables migrated in 3:43, zero errors. Watch loop now holds lockfile, `[3/6] Schema: OK 71 tables, 0 drift`, 17 startup checks pass.

#### Added

- **`scripts/render_to_local_migrate.py`** (273 LOC): one-shot Render PG → local PG data migration tool. Reads `SOURCE_DATABASE_URL` (Render) and `DATABASE_URL` (local destination); validates both are postgres URLs and distinct; prints redacted URLs + per-side row counts; requires interactive `YES` (exact case) confirmation before any writes (or `--yes` flag for scripted use). Calls `create_all_tables` on destination from the registry, then copies row-by-row in chunks of 1000 via `execute_values` with `INSERT ... ON CONFLICT (pk) DO NOTHING` for PK-based dedup. Advances destination SERIAL/IDENTITY sequences to `MAX(pk)+1` post-bulk so subsequent INSERTs don't collide. Per-table reporting and total summary.

#### Follow-ups filed (post-merge clean-up)

- **#111**: backport the YES-prompt guard to `scripts/sqlite_to_pg_migrate.py` so the misdirection pattern can't recur on the original migration script.
- **#112**: investigate bidirectional row-count drift (some tables have SQLite > Render; those SQLite-only rows are missing from local PG post-recovery). Decide whether to top off from SQLite.
- **#113**: task #88 (Phase-3-revised cutover) was marked complete but writes to Render continued up to 2026-05-08; audit the cutover to identify the leak path that the cutover should have closed.
- **#114**: content-level dedup pass for different-PK same-content duplicates from pre-cutover dual-writes era (e.g., `options_chains` 1.5M rows on Render vs 755K on SQLite may include autoincrement-divergent duplicates).

### SP5 Wave D T10 — Notification routing policy gate (D1)

Implements the pure-function notification routing gate `should_dispatch(event_type, severity, now_et, config) -> PolicyDecision`. Decides whether a notification should be sent immediately, digested for batch delivery, or muted. First task of Wave D; T11 (D2) will implement the digest queue; T12 (D3) will wire safe_send to consult this policy.

#### Added

- **`src/notifications/policy.py`**: `should_dispatch` pure-function gate + `PolicyDecision` dataclass + `NotificationsConfig` dataclass. No I/O, no logging, `now_et` is injected. Decision rules (first match wins): (1) severity high/critical → SEND always [Decision 20 bypass]; (2) event_type in mute_event_types → MUTE; (3) now_et in quiet-hours window → DIGEST or MUTE; (4) severity=low + digest_low=True → DIGEST; (5) default routing → SEND.
- **`src/notifications/errors.py`**: `NotificationsError` base + `NotificationsConfigError` subclass; mirrors T3's `src/council/errors.py` and T4's `src/monitoring/errors.py` hierarchy.
- **`src/notifications/telegram.py` — `_KNOWN_EVENT_TYPES`**: module-level frozenset of all valid event_type strings for config validation.
- **`src/notifications/telegram.py` — `_load_notifications_config(yaml_path)`**: validates the `notifications:` YAML section and returns a `NotificationsConfig`. Raises `NotificationsConfigError` on: `bypass_severity` key present (Decision 20 lockdown), unknown event_type in routing_overrides/cadence, invalid HH:MM time strings, cadence out-of-range [1, 1440], retry.attempts out-of-range [1, 10], backoff_seconds length mismatch.
- **`src/main.py`**: calls `_load_notifications_config` at startup to fail-fast before the watch loop starts.
- **`config/settings.example.yaml`**: added `notifications:` section per spec §4.7.
- **`docs/operator-guide.md`**: added "Notifications routing" section documenting Decision 20, quiet hours, mute list, digest, channel routing, cadence, and retry knobs.
- **`tests/notifications/test_policy.py`**: 23 tests covering 14 truth-table cases + 7 validation rejection cases + 2 happy-path cases.
- **`tests/notifications/test_policy_purity.py`**: 2 AST guardrail tests — fails if policy.py imports I/O modules or makes logging calls.
- **`tests/notifications/test_event_map_load_order.py`**: 1 MIN7 integration test validating event_map is populated at module-import-time before the validator runs.

### SP5 Wave C — SQL-function DEFAULT rendering fix (Wave C schema fix-up)

Fixes a bug in `src/schema/postgres.py` and `src/schema/sqlite.py` where SQL function call defaults such as `CURRENT_TIMESTAMP`, `NOW()`, and `CURRENT_DATE` were emitted quoted (`DEFAULT 'CURRENT_TIMESTAMP'`). Postgres surfaces this as `psycopg2.errors.InvalidDatetimeFormat` at INSERT time; SQLite silently stores the literal string. The bug affected `platform_events.created_at` (the single in-registry usage of a SQL function default).

#### Fixed

- **`src/schema/postgres.py` — `_format_default` helper + 2 call sites**: SQL function call defaults (CURRENT_TIMESTAMP, CURRENT_DATE, CURRENT_TIME, LOCALTIMESTAMP, LOCALTIME, NOW(), NOW) are now emitted unquoted. String literals remain quoted. Non-string defaults (integers) are emitted as-is. Applied at both the CREATE TABLE column-def site (line ~87) and the ALTER TABLE ADD COLUMN site (line ~127).
- **`src/schema/sqlite.py` — `_format_default` helper + 2 call sites**: Same fix applied at the `_render_column` CREATE TABLE site and the `ensure_columns` ALTER TABLE site.

#### Added

- **`tests/schema/test_default_value_rendering.py`**: 6 regression tests covering Postgres and SQLite CREATE TABLE and ALTER TABLE paths for both SQL-function defaults (unquoted) and string literal defaults (quoted).

### SP5 Wave C T4 — Manual-intervention drift detector (#45)

Detects when the operator closes a paper position in the Alpaca dashboard but the local `shadow_trades` row still says active. Emits a Telegram notification (severity=high) and writes a forensic-trail row to `platform_events`. Runs every 30 minutes via a new `tick_drift_detector` method in the watch loop.

#### Added

- **`src/monitoring/manual_intervention_drift.py`**: `detect_drift(broker_positions, db_positions, threshold_minutes, *, state_path, conn)` — returns `list[DriftFinding]`. Detector does NOT call `safe_send` (recursion guard enforced by AST test). Writes `platform_events` rows with `event_type='drift_detected'`, `severity='high'`, `source='drift_detector'`.
- **`src/monitoring/errors.py`**: `MonitoringError` base + `MonitoringDataError` for broker/DB read failures; mirrors T3's `src/council/errors.py` hierarchy.
- **`src/notifications/telegram.py` — `notify_manual_intervention_drift`**: formats drift alert message. Registered in `event_map` at module-import-time so Wave D policy.py validator can discover it.
- **`src/scheduler/watch.py` — `tick_drift_detector`**: 30-minute cadence tick. Calls `detect_drift`, emits via `safe_send` for each finding. Done-flag inside try block per CLAUDE.md rule. Backoff keyed to `"drift_detector"` per-task.
- **`data/drift_detector_state.json`** (runtime): atomic-write state file tracking `first_seen_iso`, `last_alerted_iso`, `expected_state`, `actual_state` per ticker. 24h dedup window. T12 precursor (Decision 21).
- **`docs/operator-guide.md` — "Drift detection" section**: explains threshold, dedup, state file, silence procedure, forensic-trail query.
- **`tests/monitoring/test_manual_intervention_drift.py`**: 6 tests covering divergence detection, 29/31-min threshold boundaries, state persistence + 24h dedup, broker outage guard, `platform_events` row insert.
- **`tests/monitoring/test_drift_detector_no_recursion.py`**: AST guardrail — fails if `detect_drift` or `_handle`/`_emit` functions call `safe_send`.

#### T4 fix-up — Security REQUEST_CHANGES (commit after 727a42a)

- **`src/notifications/telegram.py` — `notify_manual_intervention_drift`**: applied `_html_escape()` to `ticker`, `expected_state`, `actual_state`, and `severity` fields before HTML interpolation. Fixes Medium security finding: without escaping, a malformed broker response containing `<`/`>`/`&` in a state string would cause Telegram's HTML parser to 400 the message, silently dropping the drift alert. Consistent with the module-wide `_html_escape` discipline enforced across ~30 other `notify_*` functions.
- **`src/monitoring/manual_intervention_drift.py` — `_atomic_write_json`**: changed temp filename from `path.with_suffix('.tmp')` (fixed) to `path.with_suffix(f'.tmp.{os.getpid()}')` (pid-suffixed). Defense-in-depth: prevents tmp-file collision if a secondary process writes state concurrently outside the `data/watch.lock` singleton (Low security finding).
- **`tests/notifications/test_telegram_send_path.py` — `test_notify_manual_intervention_drift_html_escapes_user_fields`**: regression-lock test. Passes `<script>` and `&` in payload fields; asserts `&lt;` and `&amp;` appear in the formatted message. Fails loudly if `_html_escape` is removed.

### SP5 Wave C T2 fix-up — revert platform_events to spec §3.1c (QA REQUEST_CHANGES)

QA reviewer flagged two spec deviations and one misleading test docstring introduced in the T2 base commit. All three reverted to spec-literal.

#### Changed

- **`src/schema/registry.py` — `platform_events.created_at`**: type reverted from `TEXT` to `TIMESTAMP` per spec §3.1c (design.md line 204). SQLite stores TIMESTAMP as TEXT internally; Postgres gets the proper TIMESTAMP type via render_migrate.py. The dev's `TEXT` choice was an undisclosed deviation.
- **`src/schema/registry.py` — `platform_events` indexes**: reverted from dev's composite `idx_platform_events_type_created (event_type, created_at)` + `idx_platform_events_severity` to spec-literal `idx_platform_events_created_at ([created_at])` + `idx_platform_events_event_type ([event_type])` per spec §3.1c (design.md lines 206-209). Severity index removed — not in spec.
- **`tests/test_schema.py` — `test_shadow_trades_strategy_id_fk_db_enforcement` docstring**: corrected misleading claim that FK is "verified at COMMIT time via PRAGMA defer_foreign_keys=ON". The test never sets that pragma; IntegrityError fires at INSERT. Docstring now accurately describes INSERT-time immediate enforcement and references #107 (deferred-semantics gap tracked against src/schema/sqlite.py).

#### Added

- **`tests/test_schema.py` — `test_platform_events_created_at_is_timestamp`**: asserts `created_at` type is `TIMESTAMP` per spec §3.1c.
- **`tests/test_schema.py` — `test_platform_events_has_proper_indexes`**: asserts spec-aligned index names (`idx_platform_events_created_at`, `idx_platform_events_event_type`) and absence of non-spec indexes.

### SP5 Wave C T2 — strategy_id FK + platform_events TableDef (closes #56, #96)

Adds `shadow_trades.strategy_id` forward-compat FK column for methodology gate filtering, and declares the `platform_events` table as a forensic-trail write target for Wave C/D monitoring modules.

#### Added

- **`src/schema/registry.py` — `shadow_trades.strategy_id`**: `TEXT nullable=True` column + `ForeignKeyDef('strategy_id', 'strategy_registry', 'strategy_id', initially_deferred=True)`. Legacy trades remain NULL; forward-compat for C7a.4 filter. PostgreSQL migration uses `NOT VALID` (Decision 24 — no AccessExclusiveLock; operator runs `VALIDATE CONSTRAINT` off-hours).
- **`src/schema/registry.py` — `platform_events` TableDef**: new table with `id` (INTEGER autoincrement PK), `event_type` (TEXT not null), `severity` (TEXT not null), `payload_json` (TEXT nullable), `source` (TEXT not null), `created_at` (TIMESTAMP default CURRENT_TIMESTAMP). Indexes: `idx_platform_events_created_at ([created_at])` + `idx_platform_events_event_type ([event_type])`. Write-sites are C4 drift detector + D5 alert_silence; this task declares only.
- **`src/schema/registry.py` — `ForeignKeyDef.initially_deferred`**: new boolean field (default False) on `ForeignKeyDef` dataclass. Consumed by `generate_fk_constraint_sql` to emit `NOT VALID` constraints in render_migrate.
- **`src/schema/postgres.py` — `generate_fk_constraint_sql`**: generates `ALTER TABLE ... ADD CONSTRAINT ... FOREIGN KEY ... NOT VALID;` per Decision 24.
- **`scripts/render_migrate.py` — `--dry-run` flag**: prints FK constraint SQL without connecting to Postgres; also shows `NOT VALID` constraints on live runs with operator VALIDATE reminder.

#### Changed

- **`src/api/cloud_routes/kpis_compute.py` — `_fetch_closed_trades`**: adds optional `strategy_id: str | None = None` parameter. When not None, filters rows by `strategy_id`. Default None preserves existing behavior.

#### Tests

- 6 new tests in `tests/test_schema.py`: `test_shadow_trades_strategy_id_column_present`, `test_platform_events_table_present_with_all_columns`, `test_shadow_trades_strategy_id_fk_db_enforcement`, `test_fetch_closed_trades_filters_by_strategy_id`, `test_fetch_closed_trades_strategy_id_none_returns_all`, `test_render_migrate_fk_emits_not_valid`.

#### Migration note

`VALIDATE CONSTRAINT shadow_trades_strategy_id_fkey` is operator-run off-hours (deferred per Decision 24). The `NOT VALID` constraint is active for new inserts immediately post-migration.

### SP5 Wave C #54 — Wire dates+directions to promotion_gate KPI

Fixes the silent MC-permutation abstention in the /api/kpis promotion_gate
response. Previously `get_kpis()` called `_compute_promotion_gate_kpi(n_trades,
returns)` without dates or directions, causing `_run_mc_perm` to abstain with
`reason='mc_permutation_requires_real_directions'` on every request.

#### Changed

- **`src/api/cloud_routes/kpis.py` — `get_kpis()`**: extracts `dates` (from
  `actual_entry_time` via `_parse_iso_date`) and `directions` (from `direction`
  field, mapped `"long"→1`, anything-else→-1) from the instrumented trades list
  and passes them as kwargs to `_compute_promotion_gate_kpi`. No signature
  changes to `kpis_compute.py` or `promotion_gate.py`.

#### Changed (performance fix-up)

- **`src/data_ingestion/risk_free_rate.py` — `_fetch_dtb3_observations()`**:
  FRED HTTP timeout reduced from 15 s to 5 s. With T1's dates+directions
  wire-up the rf-rate path now activates per `/api/kpis` request. A 15 s
  blocking call on a dashboard endpoint is unacceptable; the graceful fallback
  to `RF_PERIOD_CONSTANT` in `src/methods/_rf_vector.py:90-98` makes a shorter
  timeout safe.

#### Added

- **`tests/api/test_kpis.py` — `TestPromotionGateDatesDirectionsWired`**
  (3 tests): verifies dates and directions are forwarded as kwargs with correct
  length and type (int 1/-1), and that `_run_mc_perm` does not abstain when
  directions is non-None.
- **`tests/test_risk_free_rate_timeout.py`** (1 test): asserts
  `_fetch_dtb3_observations` passes `timeout=5` to `requests.get` — regression
  lock against future timeout creep.

### SP5 Wave C — Council typed exception hierarchy + agent_data.py refactor (#68)

Replaces 28 bare `except Exception` blocks in `src/council/agent_data.py` with typed catches, surfacing previously-swallowed SQLite errors.

**NOTE: Canary deploy required** — this may surface previously-swallowed code-level bugs (KeyError/TypeError); infrastructure errors (sqlite3) still gracefully degrade per Performance review T3 fix-up; canary deploy via watch-loop restart with eyes-on for 1h.

#### Added

- **`src/council/errors.py`** — typed hierarchy: `CouncilError(Exception)` base; `CouncilParseError`, `CouncilTimeoutError`, `CouncilAgentDataError`, `CouncilProviderError` subclasses. `CouncilUnavailableError` gains `CouncilError` as second base (back-compat: still `RuntimeError`).
- **`tests/council/test_typed_errors.py`** (15 tests): 5 instantiation tests, 7 hierarchy/IS-A tests, 1 AST-based enforcement test asserting zero bare `except Exception` remain in `agent_data.py`, +2 outer-guard resilience tests (T3 fix-up).
- **`_council_agent_data_failures`** module-level `collections.defaultdict(int)` counter in `agent_data.py` — keyed by function name; incremented on every outer-guard catch; readable by schedule_health metric path for operator's daily digest.

#### Changed

- **`src/council/agent_data.py`** — all 28 bare `except Exception` blocks converted to `except sqlite3.Error` (DB query sites) or `except (CouncilAgentDataError, ImportError, AttributeError, sqlite3.Error)` (compute_hshs site). Outer function guards broadened from `except CouncilAgentDataError` to `except (CouncilAgentDataError, sqlite3.Error)` — restores infrastructure-error degradation path (DB-lock returns fallback string instead of propagating to abort the 5-agent council session). Each outer guard now emits `logger.warning("[COUNCIL] <fn> caught <type>: <msg> — degrading to fallback")` and increments the failure counter. Code bugs (KeyError/TypeError/AttributeError) still propagate. Public function signatures unchanged.

### SP5 Wave A+B strategic fix — wrap `PostgresConnectionWrapper.execute()` cursor (closes #98)

Root-cause fix for the M4/2026-05-10 KeyError:0 bug class that drove the T1ext 82-site defensive-dispatch sweep and the subsequent `_scalar(row)` helper (PR #1059). `PostgresConnectionWrapper.execute()` previously returned a raw psycopg2 cursor whose `fetchone()` produced raw dicts — incompatible with `row[0]` access. `cursor().execute()` already wrapped via `_RowFactoryCursor` (CompatRow output). This PR closes that asymmetry by wrapping the inner cursor identically in `execute()` and `executemany()`.

Effect on existing call sites: the 82 `_scalar(row)` sites consolidated in PR #1059 continue to work unchanged (CompatRow supports `row[0]`, which is what the helper falls back to for non-dict shapes). The helper's `isinstance(row, dict)` branch is now unreachable in practice but remains as forward-compat protection if a future caller routes around the wrapper.

#### Changed

- **`src/utils/db.py` — `PostgresConnectionWrapper.execute()` + `executemany()`**: return value wrapped in `_RowFactoryCursor` (uniform with `cursor()`). Pre-existing `__getattr__` passthrough on `_RowFactoryCursor` preserves access to `.rowcount`, `.description`, etc., so caller surface is unchanged.

#### Added

- **`tests/test_pg_wrapper_execute_returns_compatrow.py`** (5 tests): regression-lock that asserts `wrapper.execute(sql)` and `wrapper.executemany(sql, params)` return `_RowFactoryCursor`, that `fetchone()` returns `CompatRow` (with both `row[0]` and `row['col']` working), that `fetchall()` returns list of CompatRow, and that pass-through attributes like `.rowcount` still work.

#### Follow-ups (post-merge cleanup, scoped separately)

- Mechanically remove the 82 `_scalar(row)` call sites added in PR #1059 — replace with direct `row[0]` access. Helper can then be deprecated. Tracked as next-tier follow-up.

### SP5 Wave A+B post-merge — `_scalar(row)` helper + 82-site dispatch consolidation

Operator review observation on PR #1058 surfaced T1ext idiom drift: 81 sites used a defensive cross-engine scalar-fetch dispatch pattern, but 1 site at `watch.py:1182` drifted to a brittle literal-key idiom (`row['count']`) that only works because psycopg2 auto-aliases `COUNT(*)` → `'count'`. Any SQL change to a different aggregate (MIN, AVG, subquery) would break it silently. This PR consolidates all 82 sites onto a single `_scalar(row)` helper.

#### Added

- **`_scalar(row)` helper at `src/utils/db.py`**: single function handles all four row shapes flowing out of `fetchone()` under the cross-engine wrapper architecture — `None`, `sqlite3.Row`, `CompatRow` (PG via `.cursor().execute()`), and raw `dict` (PG via `.execute()` — see follow-up #98). Replaces inline `row[0] if not isinstance(row, dict) else ...` dispatch at every call site.
- **`tests/test_scalar_helper_discipline.py`** (5 tests): AST-based structural guardrail that forbids future drift back to the inline dispatch idiom. Narrow matcher distinguishes scalar-fetch dispatch (`X[0] if not isinstance(X, dict) else list(X.values())[0]` or `X['key']`) from legitimate defensive `.get()` patterns. Joins `test_no_fetchone_int_index_in_pg_unsafe_files.py` (T1ext) and `test_no_sqlite_isms_in_pg_safe_files.py` (M4) as the third AST-based cross-engine guardrail.

#### Changed

- **82 dispatch sites consolidated onto `_scalar(...)`** across 14 files. Per-file count:
  - `src/scheduler/reports.py` (23 sites)
  - `src/evaluation/build_score.py` (16)
  - `src/evaluation/hshs_live.py` (15)
  - `src/scheduler/watch.py` (7 — includes the brittle Idiom B at line 1182)
  - `src/attribution/logger.py` (5)
  - `src/shadow_trading/executor.py` (4)
  - `src/scheduler/overnight.py` (3)
  - `src/notifications/telegram_commands.py` (2)
  - `src/services/system_service.py` (2)
  - `src/api/cloud_routes/broker_exceptions.py` (1 — Idiom C variant)
  - `src/config/overrides.py` (1)
  - `src/evaluation/system_validator.py` (1)
  - `src/features/traffic_light.py` (1)
  - `src/scheduler/premarket.py` (1)

#### Follow-ups filed (deeper hardening, NOT silently expanded into scope)

- **Task #98**: Wrap `PostgresConnectionWrapper.execute()`'s cursor in `_RowFactoryCursor` (`db.py:402-409`). Root cause of why the 82-site dispatch was needed — `wrapper.execute()` returns a raw psycopg2 cursor while `wrapper.cursor().execute()` returns the wrapped variant. Fixing this would make the dispatch entirely unnecessary at all 82 sites. Tactical fix in this PR (the helper) + strategic fix in #98 is the right sequence — lower-risk path that doesn't conflate concerns.

### SP5 Wave A+B T3 — known_violations.json render_sync.py stale entries

#### Fixed

- **SP5 Wave A+B T3 — render_sync.py known_violations.json cleanup** (`config/known_violations.json`): confirmed `src/sync/render_sync.py` is absent post-Phase-3-revised (PR #1055) and `config/known_violations.json` contains zero `render_sync` references — stale entries were removed as part of that PR's T7 deletion batch. Closes task #26. (T3, verification-only)

### SP5 Wave B T5 — Extend _html_escape to notify_risk_alert + notify_exposure_alert

#### Security

- **SP5 Wave B T5 — HTML-escape external strings in notify_risk_alert** (`src/notifications/telegram.py:notify_risk_alert`): `alert_type` and `detail` are now wrapped with `_html_escape()` before interpolation into the Telegram HTML-mode payload, preventing display corruption or HTTP 400 on malformed HTML from special chars like `<`, `>`, `&`. (task #65)
- **SP5 Wave B T5 — HTML-escape external strings in notify_exposure_alert** (`src/notifications/telegram.py:notify_exposure_alert`): `sector` (appears twice) and each ticker in the `tickers` list are now wrapped with `_html_escape()`. Same class as above. (task #65)

#### Tests

- **SP5 Wave B T5** (`tests/test_notifications_telegram.py`): 4 new tests covering escape coverage for both functions — special-char inputs produce escaped output, clean inputs round-trip unchanged.

#### Follow-ups filed (sibling-search results — NOT silently expanded into this PR)

Per the `feedback_review_sibling_search` discipline, the sibling-search step surfaced two additional notify_* functions with the same unescaped-HTML-interpolation gap class. These were NOT silently fixed inside T5's scope; they are tracked as durable follow-up tasks for Sprint 5 catch-all (SP6):

- **task #93** — Extend `_html_escape()` to `notify_regime_alert` (src/notifications/telegram.py:781-797): `regime_old`, `regime_new`, `risk_governor_status` interpolated raw.
- **task #94** — Extend `_html_escape()` to `notify_streak_alert` (src/notifications/telegram.py:810-822): ticker symbols + `risk_governor_status` interpolated raw.

### SP5 §J Cutover Rectification — post-2026-05-11 hardening (T1–T8 + T2-fix)

9 rectification items addressing the two P0 failure modes from the 2026-05-11T20:37Z cutover attempt (P0 #89: 59 PG tables disappeared with `log_statement=none`; P0 #90: NVDA shadow_trade bypassed the gate). Goal: the next cutover attempt has comprehensive instrumentation + hardened guardrails so failures either can't recur or leave a precise forensic trail. Spec: `docs/audits/2026-05-11-cutover-rectification/spec.md`.

#### Added

- **SP5 §J Cutover Rectification — schema drift audit** (`scripts/audit_schema_drift.py`): per-column NULL constraint detector comparing registry / SQLite / PG. Surfaced and reconciled `setup_signals.setup_type` NOT NULL drift that crashed the 2026-05-11 cutover. (T3, `02ce393`)
- **SP5 §J Cutover Rectification — PG roles setup** (`scripts/setup_pg_roles.py`): idempotent setup of `halcyon_app` (INSERT/SELECT/UPDATE/DELETE + USAGE on sequences, no superuser) and `halcyon_readonly` (SELECT only). Uses `psycopg2.sql.Literal` for safe password literal escaping; supports password rotation via interactive `\password`. (T2, `0c124fa`)
- **SP5 §J Cutover Rectification — startup fail-fast gate consistency** (`src/startup_checks.py:check_cutover_gate_consistency`): CRITICAL at process start if `ARCIS_PG_CUTOVER_ENABLED=1` but `DATABASE_URL` non-postgres. Pairs with T5 runtime WARN. (T7, `b068677`)
- **SP5 §J Cutover Rectification — pg_stat_activity capture** (`scripts/capture_pg_activity.ps1`): operator runbook tool for mid-smoke connection forensics. Loops every 30s during cutover smoke. (T8, `79f84ab`)
- **SP5 §J Cutover Rectification — wrapper-function discipline test** (`tests/test_connect_db_discipline.py::test_wrapper_functions_use_connect_db`): AST-scans `insert_*`/`log_*`/`record_*`/`save_*` functions in `src/`, asserts each uses `connect_db()`. Closes the structural gap that allowed the 2026-05-11 NVDA shadow_trade leak. (T6, `6a8cba5`)

#### Changed

- **SP5 §J Cutover Rectification — PG log_statement=all** (`docker-compose.yml`): halcyon-pg now runs with `-c log_statement=all -c log_line_prefix='%t [%p] %u@%d '` for DDL forensic trail. Foundation for diagnosing the next cutover attempt. (T1, `3c4f76d`)
- **SP5 §J Cutover Rectification — setup_signals.setup_type nullable** (`src/schema/registry.py`): changed from `nullable=False` to default-nullable to match SQLite reality + caller behavior (`setup_classifier.classify_setup` returns None when no rule matches). (T3, `02ce393`)

#### Fixed

- **SP5 §J Cutover Rectification — sequence advance after bulk INSERT** (`scripts/sqlite_to_pg_migrate.py:_advance_sequence_after_bulk`): post-migration `setval(<seq>, COALESCE(MAX(<pk>), 0) + 1, false)` for serial PKs, silently skipped for UUID/composite PKs. Closes the activity_log pkey=3 conflict that crashed the watch loop during the 2026-05-11 cutover. (T4, `dd1116e`)
- **SP5 §J Cutover Rectification — symmetric forensic WARN** (`src/utils/db.py:_warn_gate_on_no_pg_url_once`): one-time WARN at runtime when `ARCIS_PG_CUTOVER_ENABLED=1` but `DATABASE_URL` non-postgres. Sibling to existing SP-ONEDB-009 WARN; closes the silent-fallthrough class. (T5, `efcd232`)

#### Security

- **SP5 §J Cutover Rectification — CREATE ROLE SQL injection fix** (`scripts/setup_pg_roles.py`): password env vars now use `psycopg2.sql.Literal` instead of f-string interpolation into `CREATE ROLE ... PASSWORD '...'`. Closes the SQL injection vector identified by Security Reviewer (HIGH severity). Named `$halcyon$` dollar-quote tag adds defense-in-depth. Also added `ALTER DEFAULT PRIVILEGES ... GRANT USAGE ON SEQUENCES TO halcyon_app` for future SERIAL columns. (T2-fix, `0c124fa`)

#### Documentation

- **SP5 §J Cutover Rectification — operator-guide cutover-runbook updates** (`docs/operator-guide.md`): added Step 0.5 (pgAdmin isolation pre-flight check), Step 7.5 (mid-smoke pg_stat_activity capture), new "PG application roles (post-merge one-time setup)" section, and "Rotating role passwords" subsection. (T2 + T8)
- **SP5 §J Cutover Rectification — schema drift audit report** (`docs/audits/2026-05-11-cutover-rectification/drift-audit-results.md`): documents the NOT NULL drift findings + sibling-search of all 30+ setup_type callers in src/. (T3)
- **SP5 §J Cutover Rectification — spec** (`docs/audits/2026-05-11-cutover-rectification/spec.md`): 9-task rectification spec from the 2026-05-11 cutover failure. (Deliverable 0, `4b913cd`)

### SP5 §J5/§J6 Phase 3-revised — One-database cutover correction

Closes the PR #1054 cutover gap (which routed only ~5 of 336 call sites to PG). With this PR + the operator-led re-cutover runbook (see `docs/operator-guide.md` §"Postgres Cutover (SP5 §J5/§J6 Phase 3-revised — one-DB)"), `ARCIS_PG_CUTOVER_ENABLED=1` routes EVERY `connect_db()` call to Postgres regardless of how `db_path` was passed — closing the one-database invariant. Full design at `docs/audits/2026-05-11-modified-a-migration/spec-revised-one-db.md`.

**Code changes (T1-T6):**
- **`src/utils/db.py`** — `connect_db()` precedence rule inverted: gate ON + DATABASE_URL postgres now wins for ALL call sites, including explicit `db_path`. Adds `_warn_db_path_ignored_once` helper that emits a one-time WARN per distinct `db_path` override (SP-ONEDB-009). `connect_db_with_pg_retry()` mirrors the inversion. `_REPLACE_SEMANTICS` gets `'operator_view_state': 'in_place_update'`.
- **`src/schema/registry.py`** — 8 tables flipped to `sync_to_postgres=True` (daily_ib_health, model_evaluations, preference_pairs, config_overrides, bracket_health, data_freshness, system_metrics, operator_view_state). `sync_state` TableDef removed entirely (deprecated alongside render_sync.py). Total tables now 71 (was 72).
- **Writers converted to `engine_aware_upsert`:**
  - `src/training/ab_evaluation.py` (model_evaluations writer)
  - `src/training/dpo_pipeline.py` (preference_pairs writer)
  - `src/commands/executor.py` (command_results writer)
  - `src/config/overrides.py` (config_overrides writer)
  - `src/shadow_trading/bracket_monitor.py` (bracket_health writer)
  - `src/api/cloud_routes/system_index.py` (operator_view_state writers ×2)

**Deletions (T7):**
- `src/sync/render_sync.py` — deprecated; relied on `sync_state` table (removed)
- `src/sync/reconcile.py` — deprecated; no callers post-cutover
- `src/cli/commands.py:cmd_reset_live_prices_watermark` + `src/cli/main.py` subcommand registration
- `tests/test_render_sync*.py` files
- `config/known_violations.json` entries referencing the deleted files

**Tests added (~25 net new):**
- 12 truth-table tests in `tests/test_db_util.py` (8 rows × extras for warn-once + retry-parity)
- 2 schema regression locks in `tests/test_schema.py` (8-flip assertion + sync_state-absence)
- 6 cross-engine writer tests across `tests/test_writers_*.py` (one per writer)
- 3 deletion-regression-locks in `tests/test_render_sync_removed.py`

**Operator next steps:** see `docs/operator-guide.md` §"Postgres Cutover (SP5 §J5/§J6 Phase 3-revised — one-DB)" for the 8-step re-cutover runbook. Includes the SQLite-shows-zero-recent-writes assertion that would have caught PR #1054 in 30 seconds.

**Out of scope (cleanup backlog):**
- `cloud_routes/` manual `if database_url:` branches are now redundant under one-DB but each has independent quirks — cleanup is post-merge backlog (SP-ONEDB-011).
- The autouse `_REPLACE_SEMANTICS` monkeypatch fixtures in `tests/test_writers_operator_view_state.py` and `tests/api/conftest.py` become no-ops post-merge (T1+T6 together cover the entry); deletion is post-merge backlog.

### Sprint S1-CC Batch B — Walk-Forward Framework Scoping (3 docs-only tasks)

Closes the second half of Sprint S1-CC. Stage 1 corpus admissibility passed (Batch A landed via PR #1051); this batch lands the v1 spec + v1 plan for the walk-forward validation framework that gates Stage 2 OOS dispatch and v2 training. **Docs-only.** No src/, tests/, or config/ changes.

- **`docs/audits/2026-05-11-stage1-completion/walkforward-prior-art.md`** (NEW, 419 lines) — B1 prior-art review. Inventories WIRED vs SHELF across `src/methods/promotion_gate._decide`, `src/platform/promotion._evaluate_walkforward_gate`, `src/evaluation/walkforward.py` (Stage-1 anchored harness), and `src/platform/rigor/walkforward_*` (R1-R8 state-machine + `walkforward_results` persistence). Documents the composition pattern (walk-forward AND-composes with the 4-of-5 methodology voter at the orchestrator level, NOT as a 6th vote) and surfaces 12 open methodological questions (D1-D12) the spec must resolve.
- **`docs/audits/2026-05-11-stage1-completion/walkforward-spec-v1.md`** (NEW, 264 lines) — B2 v1 spec. Per operator-convention section flow (Revision History → Overview → Architecture → Data Model → API & Module Surface → Error Handling → Testing Strategy → Operational Notes → File Inventory → Known Considerations → Design Decisions Table → Do-Not-Do → Falsifiability Triggers). **12 design decisions captured** (SP-WF-001 through SP-WF-012). Key resolutions:
  - **SP-WF-008 (composition)** = Choice B — walk-forward stays AND-composed at `src/platform/promotion.py:_evaluate_backtested_to_shadow`, NOT a 6th vote into `_decide`. Preserves independent falsifiability of methodology voter vs regime-stability gate.
  - **SP-WF-009 (sentinel default)** = Choice A — `WALKFORWARD_GATE_ENABLED=true` by default. The gate is already wired and blocking in production (R1-R8 v1); `false` default would silently regress an enforced gate.
- **`docs/audits/2026-05-11-stage1-completion/walkforward-plan-v1.md`** (NEW, 325 lines) — B3 v1 plan. 12 tasks across 5 batches (parallel-eligible where independent). Sentinel: matches spec SP-WF-009 (default `true`). Schema additions: D7 Choice A (reuse existing `walkforward_results` table + add `gate_version TEXT DEFAULT 'v1'` column for forward-compat reads; new `excess_sharpe_min_used REAL` column for self-describing rows). Total estimated LOC budget: ~235 net new src/ + ~395 new test lines. T7 is procedure-only (`validate-schema --fix` + `render_migrate.py`).

**Cross-doc alignment verified:** B2 and B3 were drafted by parallel agents (worktree-isolated) and independently converged on the AND-composition pattern + sentinel `true` default. Independent convergence is a positive signal that the resolutions are grounded in the existing codebase, not artifact of any single agent's reasoning.

**Out of scope:** v2 training dispatch (still gated on walk-forward shipping + Stage 2 closure). Strategy specs (#511 Connors RSI(2) etc.) remain separate. No src/ or test changes in this batch — the impl sprint dispatches from the plan after operator review.

### SP5 §J5/§J6 Phase 3 T3.2 — connect_db precedence-flip gated behind ARCIS_PG_CUTOVER_ENABLED

The Phase 3 cutover gate. `src/utils/db.py:connect_db()` and `connect_db_with_pg_retry()` now route to Postgres ONLY when BOTH `DATABASE_URL` starts with `postgres` AND `ARCIS_PG_CUTOVER_ENABLED=1`. Without the gate, behavior on every machine with a stale `DATABASE_URL` env var is unchanged (SQLite path). Production cutover (Phase 3 T3.3) requires the operator to set BOTH env vars on the NSSM service via `nssm set ArcisWatchLoop AppEnvironmentExtra` (APPEND syntax). Rollback is a single env unset: `ARCIS_PG_CUTOVER_ENABLED=` → instant SQLite revert. Gate removed in Phase 4 T4.4 once cutover is stable.

- **`src/utils/db.py`** — `connect_db()` and `connect_db_with_pg_retry()` precedence rule gated. Docstring updated with the M2 mitigation rationale (2026-05-10 cutover attempt failed in 2 min from stale shell DATABASE_URL; gate makes T3.2 merge a no-op on dev boxes).
- **`tests/test_db_util.py`** — 3 new tests: gate-off+PG-url → SQLite, gate-on+PG-url → PG, gate-on+no-PG-url → SQLite. Plus updates to any existing PG-routing tests to set the gate explicitly.
- **`docs/audits/2026-05-11-modified-a-migration/t3.4-smoke-checklist.md`** (NEW, 284 lines) — operator-runnable 30-min smoke checklist for T3.4 post-cutover verification. §0 pre-smoke gates (7 checks including PG schema-mirror + data-migration spot checks); §1 write-path smoke (5 paths: system_metrics, shadow_trades, activity_log, notifications_dedup, scan_metrics — each cross-verified against SQLite max-timestamps to confirm writes are landing in PG); §2 read-path smoke (7 dashboard endpoints incl. the Phase 2.5 ET-tz fixes); §3 C1 LIKE regression coverage (the `executor.py:777` drawdown-alert LIKE site + 2 sibling sites — exercises the wrapper's `_rewrite_question_to_pct` quote-and-percent state machine); §4 log sweep with per-pattern decision matrix (relation/column-missing = CRITICAL, KeyError:0 = HIGH, OperationalError = MEDIUM); §5 explicit PASS/DEGRADED/FAIL criteria with the T3.5 rollback procedure (single env unset). Per CLAUDE.md governance — operator runbook updates ship with the PR that introduces them.

### SP5 §J5/§J6 Phase 2.5 — KNOWN_OFFENDERS date-function cleanup (12 sites, 6 files)

Phase 3 cutover prerequisite. Phase 2 T2.14 (AST-based SQLite-ism discipline scan) shipped with a `KNOWN_OFFENDERS` allowlist containing 12 `datetime('now', ...)` / `date('now', ...)` sites across 6 files — patterns that crash on Postgres because the SQLite negative-offset date literal has no PG equivalent. This phase migrates all 12 sites to Python-side `datetime.now(ET) - timedelta(days=N)` cutoffs bound as `?` parameters (the wrapper rewrites `?` → `%s` for psycopg2 post-cutover). After this phase, `KNOWN_OFFENDERS` is **Phase-3-cutover-ready**: zero remaining date-function offenders block the cutover (only the PRAGMA-guarded `system_validator.py:167` and the 34 dynamic-`?` wrapper-handled sites remain).

- **`src/evaluation/build_score.py`** (4 sites — lines was 151, 163, 408, 432) — `_score_data_asset_value` and `_build_data_detail` 30-day + 90-day cutoffs now `datetime.now(ET) - timedelta(days=N)` matching the production write convention at `src/training/data_collector.py:460`. Side benefit: closes a pre-existing 4-hour UTC/ET skew bug at the cutoff boundary (the old SQLite `datetime('now', ...)` returned UTC against ET-stored timestamps).
- **`src/evaluation/hshs_live.py`** (3 sites — lines was 218, 260, 266) — `_score_data_asset` 7-day freshness + `_score_flywheel_velocity` 7-day/14-day cohort comparison. Cohort comparison reworked to share a single `now_et` anchor across the two queries so the boundary is byte-stable.
- **`src/council/agent_data.py`** (2 sites — lines was 272, 451) — `gather_risk_data` 7-day llm failure-rate fallback + `gather_macro_data` 365-day high-yield average. 365-day site uses `.date().isoformat()` because `collected_date` is stored as YYYY-MM-DD date string (not full ISO timestamp); string-comparison-safe.
- **`src/council/context.py`** (1 site — line was 30) — `build_shared_context` 1-day recent-recommendations rollup. Same `datetime.now(ET) - timedelta(days=1)` pattern.
- **`src/api/routes/system.py`** (1 site — line was 694) — `monitoring_history` hours-parameterized cutoff. **Preserved pre-existing UTC behavior** (matches the SQLite `datetime('now', ? || ' hours')` UTC return); `system_metrics.timestamp` is written in ET so a 4-5h skew exists at the boundary. Statistically irrelevant for typical 24-hour windows but filed as a follow-up.
- **`src/api/routes/ib_status.py`** (1 site — line was 76) — `ib_status` 30-day uptime % cutoff. Uses tz-aware `datetime.datetime.now(ET)` matching the write-side convention at `src/trading/ib_shadow.py:78` (post-review fix per PR #1052 review).
- **`tests/test_build_score_date_now.py`** (NEW, 214 lines) — 4 tests + 2 cross-engine SQLite/PG parity tests
- **`tests/test_hshs_live_date_now.py`** (NEW, 240 lines) — 4 tests
- **`tests/test_agent_data_date_now.py`** (NEW, 383 lines) — 6 tests (risk + macro paths)
- **`tests/test_council_context_date_now.py`** (NEW, 269 lines) — 5 tests
- **`tests/test_api_routes_system_date_now.py`** (NEW, 211 lines) — 4 tests
- **`tests/test_ib_status_uptime_window.py`** (NEW, 192 lines) — 4 tests
- **`tests/test_no_sqlite_isms_in_pg_safe_files.py`** — removed all 12 date-function entries from `KNOWN_OFFENDERS`; added a summary comment block explaining the migration. All 15 AST-scan tests pass against the post-merge integration.

### Sprint S1-CC Batch A — Stage 1 corpus closeout

### Added

- Stage 1 corpus generation complete (67,528 entries, §B2 admissibility PASS, manifest pinned at SHA256 `43c2e3ed...0d93` per `data/corpus/stage1-001/MANIFEST.md`). Cold-read verdict PASS → proceed to walk-forward framework scoping (S1-CC Batch B).

### SP5 §J5/§J6 Phase 0 — Modified-A migration (T0.7)

- **`src/schema/registry.py`** — added `sync_conflict_col="event_type, dedup_key"` to the `notifications_dedup` TableDef. The PK `id` is autoincrement; uniqueness is enforced via the composite index on `(event_type, dedup_key)` at registry.py:2543 — that composite is the natural ON CONFLICT target. Prerequisite for the SP5 §J5 `engine_aware_upsert` migration at `src/notifications/platform_events.py:96` (tracked as T1.7 in Phase 1).
- **`tests/test_schema.py`** — added `test_notifications_dedup_sync_conflict_col_matches_composite_unique` asserting `TABLES['notifications_dedup'].sync_conflict_col == "event_type, dedup_key"`.

### Wave 5.1 — Training-readiness verification script (post-3090 trainer preflight)

- **`scripts/verify_training_readiness.py`** (NEW) — non-destructive, fail-fast diagnostic that proves the post-3090-upgrade trainer (`training_data/train.py`) is ready to run end-to-end. Five sequential checks with `[VERIFY-N]` prefixes and a final `READINESS: PASS|FAIL (X/5)` summary + non-zero exit on fail: (1) CUDA + 3090 detection with ≥20 GB free VRAM gate; (2) trainer dependency import sweep (transformers, peft, trl, bitsandbytes, datasets); (3) Stage 1/2/3 jsonl path + first-5-line JSON validity; (4) trainer dry-run capped at `max_steps=1` with tmpdir cleanup; (5) GGUF export artifact verification (≥1 MB). 329 lines, 9 functions ≤49 lines each.
- **`tests/test_verify_training_readiness.py`** (NEW) — 4 new tests; mock torch.cuda + tmp_path file fixtures. Real-code-path coverage (no tautological mocks).

### Wave 4.1 — `sqlite_to_pg_migrate.py` one-shot data migration script

- **`scripts/sqlite_to_pg_migrate.py`** (NEW) — copies all 63 sync-eligible registry tables from local SQLite to local Docker Postgres. Idempotent via `INSERT … ON CONFLICT DO NOTHING`; CLI flags `--tables`, `--dry-run`, `--vacuum-after`. Streaming SQLite read via `cursor.fetchmany(_CHUNK_SIZE)` keeps peak per-table RAM at ~100 KB regardless of table size. Bulk inserts via `psycopg2.extras.execute_values` (~5–10× faster than `executemany`). Single PG connection reused across the per-table loop with per-table commit/rollback boundaries. Per-table transactions; skips NULL-pk rows (matches sync_thread #243 fix). Dry-run on operator's actual data: 63 tables, 1,323,393 rows total — committed log at `docs/audits/2026-05-10-cloudflare-tunnel-cutover/migration-dry-run.log`.
- **`tests/test_sqlite_to_pg_migrate.py`** (NEW) — 6 tests with mocked psycopg2 (no live PG required): null-pk filtering, chunk boundaries, dry-run no-op, abort on missing/wrong DATABASE_URL, sync-skip filter.

### Wave 4.2 — `SYNC_THREAD_ENABLED` feature flag for `start_render_sync`

- **`src/sync/render_sync.py`** — added an env-var gate at the top of `start_render_sync()`: when `SYNC_THREAD_ENABLED=false` (case-insensitive), log INFO and return None early (matches existing `watch.py:1351-1355` None-handling contract). Default `'true'` preserves existing behavior. Surgical 4-line change placed before any config reads. Risk R5 mitigation per cutover spec §7 — without this flag, watch loop post-Render-decommission would log connection errors continuously when `RenderSyncThread` tries to push to a dead Render PG endpoint.
- **`tests/test_render_sync.py`** — 2 new tests added (existing 70 preserved): `test_start_render_sync_returns_none_when_sync_thread_enabled_false`, `test_start_render_sync_starts_when_sync_thread_enabled_true_or_unset`.

### Wave 3 — Cutover verification + Render decommission docs

- **`docs/audits/2026-05-10-cloudflare-tunnel-cutover/wave-3-smoke-test-checklist.md`** (NEW) — operator-actionable per-page table for browser smoke-testing all 6 pages on `halcyonlab.app` after tunnel cutover.
- **`docs/audits/2026-05-10-cloudflare-tunnel-cutover/wave-3-render-decommission-runbook.md`** (NEW) — pre-deletion checklist, Render-dashboard delete steps, DNS cleanup audit, post-deletion verification curl (with required Chrome User-Agent per `reference_cloudflare_bot_fight` memory), 7-day rollback window, and 2026-05-17 PG retention disposal reminder.
- **`docs/audits/2026-05-10-cloudflare-tunnel-cutover/wave-3-receipt.md`** (NEW) — template for operator-completed evidence (PM-prepped; operator fills + commits).

### Wave 2.1 — Engine-aware `connect_db` shim (dual-engine SQLite/Postgres)

- **`src/utils/db.py`** — `connect_db` refactored from a pure SQLite helper into an engine-aware shim. When called with no `db_path` argument and `DATABASE_URL` starts with `postgres`, returns a `PostgresConnectionWrapper` backed by psycopg2 (`RealDictCursor` for name-based result access). When `DATABASE_URL` is unset / empty (or any explicit `db_path` is passed), returns the existing `sqlite3.Connection` with `busy_timeout=30000` and `row_factory=sqlite3.Row` — default behavior is byte-for-byte identical to pre-change. New `PostgresConnectionWrapper` class exposes `cursor()`, `execute()`, `executemany()`, `commit()`, `rollback()`, `close()`, and `row_factory`. This is the foundational wedge for the Wave 4 watch-loop write-side flip — once `DATABASE_URL` is set in the NSSM service env, all 336 `connect_db` call sites route to PG transparently.
- **`tests/test_db_util.py`** — 4 new tests added; existing 3 tests preserved unchanged. New tests use monkeypatch + mocked psycopg2.connect (no real PG connection required): `test_connect_db_uses_sqlite_when_database_url_unset`, `test_connect_db_uses_postgres_when_database_url_postgres_scheme`, `test_connect_db_explicit_db_path_forces_sqlite`, `test_pg_wrapper_exposes_required_methods`.

### Cutover — Cloudflare Tunnel + Modified-A migration (Wave 1, 2026-05-10)

Infrastructure stand-up for the unified-DB switch. Today's exit state is **transitional Hybrid** (Postgres provisioned with mirrored schema but no live data; SQLite still primary). The data migration + watch-loop write-side flip + SQLite retirement are explicit tail items per `docs/audits/2026-05-10-cloudflare-tunnel-cutover/spec.md` §6.

- **`docker-compose.yml`** (NEW) — Postgres 16-alpine, container `halcyon-pg`, bound to `127.0.0.1:5433`. Port 5433 (not the default 5432) because the operator's machine has a Windows-installed PostgreSQL 18 service on 5432; 5433 sidesteps the conflict and preserves the local PG tool for ad-hoc analytic queries. Volume mounts to `C:/arcis/data/pg-data` (outside the git repo per CLAUDE.md "runtime data lives outside the repo" rule). Healthcheck via `pg_isready`; 2 GB memory cap.
- **`src/api/app.py`** — auth-gated for the post-cutover tunnel exposure. `verify_auth` lifted from `cloud_app.py:153-176` (same hash-or-plaintext bearer-token model the frontend already speaks). Every native router (system, scan, shadow, training, …) now requires bearer auth via `include_router(dependencies=[Depends(verify_auth)])`. 3 new cloud_routes wired in (`notifications`, `platform`, `walkforward`) — these were previously cloud_app-only; bringing them local is required for the tunnel cutover. Existing cloud_routes (kpis, broker_exceptions, preflight) + new ones use the `dependency_overrides` pattern from `cloud_app.py:316-340`. New unauthenticated `/healthz` endpoint for curl smoke tests + external monitoring. WebSocket `/ws/live` still UNAUTH'd as a follow-up (`#1100`). FastAPI title version bumped 0.17.1 → 0.34.0 to match latest release tag.
- **`training_data/train.py`** — switched from Unsloth single-stage trainer to multi-stage curriculum (STRUCTURE → EVIDENCE → DECISION) using HF Transformers + PEFT LoRA + TRL SFTTrainer + bitsandbytes nf4 4-bit quantization. Driven by the 2026-05-10 GPU upgrade (RTX 3060 12 GB → RTX 3090 24 GB) which removes the 12 GB VRAM ceiling that originally rejected Unsloth's standard path. GGUF export retains Unsloth as primary path with llama.cpp CPU conversion as fallback. `.gitignore` updated: `training_data/` → `training_data/*` so allowlist sibling rules can re-include `train.py` and `README.md` (parent-dir exclusion blocks child re-inclusion per gitignore spec).
- **Render PG snapshot** — `pg_dump` ran to `C:/arcis/data/render-pg-snapshot-2026-05-10.sql` (478 MB, 65 CREATE TABLE + 65 COPY blocks). Rollback artifact for the migration.
- **Local SQLite snapshot** — `cp` to `C:/arcis/data/ai_research_desk-2026-05-10-precutover.sqlite3` (507 MB). Rollback artifact for the data-migration phase.
- **Schema mirrored** to Docker PG via `scripts/render_migrate.py` — 63 tables, 862 columns, 70 indexes, 0 columns added (clean migration).
- **Frontend rebuild** — fresh `npm run build` produces `frontend/dist/` with new `VITE_API_SECRET` baked into the bundle. Local FastAPI's `StaticFiles` mount at `app.py:80` serves it at the same origin as `/api/*`, so no CORS in production.
- **NSSM `ArcisDashboard` service** — operator-installed wrapper for `python -m src.main dashboard --port 8000` (the FastAPI uvicorn host). Sibling to the existing `ArcisWatchLoop` service. Stdout/stderr logs at `C:/arcis/logs/dashboard-{stdout,stderr}.log`.
- **Cloudflare Zero Trust public hostname** — operator-configured rule routing `halcyonlab.app → http://localhost:8000` through tunnel `f6f41208-e674-43cf-bb9d-6ca5c4972eb3`.

Audits committed for history: SP3 visual-verify gate evidence (17 PNG before/after pairs from PR #1006), SP5 (terminal sprint) scope inventory (operator-confirmed Hybrid canon disposition).

Wave 2-5 are dispatched via `arcis:code` (coding-team skill) per operator policy on Sprint-1+ feature work.

## [v0.34.0] - 2026-05-08 — Sprint 4 Wave 1+2+3: cockpit followups + notifications observability + post-deploy hotfixes + sprint closeout

### Sprint 4 closeout summary

Sprint 4 delivered 22 of 23 planned tasks (T22 deferred to Sprint 5 as `#SP5-notifications-routing-policy`, tracked as task #69). Test floor: **4,798 tests passing** (baseline was 3,682 pre-Sprint-4; +1,116 net across all waves). Deferred to Sprint 5: `#SP5-notifications-routing-policy` (T22, task #69), `#SP5-notifications-CC6-prefixing`, `#SP5-notifications-dataclass-payloads-tail`, `#SP5-council-errors-consolidation` (task #68). Visual-verify gate: 11 priority pages + 2 new components all PASS post-deploy. WON'T FIX: `#SP4-settings-backend-float32-storage` (frontend clamp applied in T11; backend float32 storage retained).

### Sprint 4 Wave 2 deploy + 6 post-deploy hotfixes

This release cuts after Sprint 4 Wave 1+2+3 deploys to halcyonlab.app and 6 hotfixes shipped during the post-deploy visual-verify gate.

**Hotfixes shipped during the post-deploy gate (most recent first):**

### Hotfix — MR feature dict adds `current_price` key (true root cause of #52)

- **`src/features/mean_reversion.py:compute_mr_features`** now includes `current_price` (alongside the existing `last_close`) in its returned feature dict. Pre-fix, the dict had only `last_close` — but `build_packet_from_features` (`src/packets/template.py:170`) reads `features.get("current_price", 0.0)` as the canonical key. MR features were ALWAYS missing it, so packet builder ALWAYS got `0.0` and refused via #621. Pullback scan worked because `compute_all_features` (engine.py:173) already returns `current_price`. This is the TRUE root cause of the recurring BAC/CVX/DE/AMZN/AVGO MR-scan rejections — yfinance data was clean; the bug was a feature-dict key naming mismatch between the two scan paths. PR #1037 (yfinance trailing-zero sanitizer) and #1036 (None-guard at enhance_packet_with_llm) remain as defense-in-depth but didn't address the actual production symptom. New regression test `tests/test_mr_features_current_price_key.py` (5 tests) covers: MR features include current_price, current_price aliases last_close, end-to-end MR features → build_packet returns non-None packet, pullback features schema already includes current_price (sibling-lock).

### Hotfix — Operator-only kill switch (auto-halt removed)

- **`src/risk/governor.py`** introduces `_HALT_ALLOWED_SOURCES = frozenset({"cli", "dashboard", "api", "test"})` and a new `HaltSourceForbiddenError(ValueError)` exception. `_global_halt(True, source=...)` now raises if the source is not in the allowlist. Resume calls (`halt=False`) remain unrestricted (anyone can clear). This is the architectural lockdown — even if a future bug introduces a new auto-halt code path, the governor refuses it at the boundary.
- **`src/evaluation/auditor.py`** removes the `_global_halt(True, source="auditor", ...)` call in the production-mode CRITICAL branch. Auditor now escalates via `logger.critical` + email alert + appends `{"action": "operator_action_required", "severity": "critical", ...}` instead of `{"action": "halt_trading", ...}`. Email subject is now "[TRADE DESK] CRITICAL AUDIT FLAG — Operator Action Required" with body listing the 3 manual halt paths (CLI/dashboard/API). Bootcamp downgrade for non-`_NEVER_DOWNGRADE` categories still applies — alert text changes, severity tag may downgrade, but no auto-halt under any path.
- **Tests:** `tests/test_kill_switch_source_allowlist.py` (NEW, 17 tests) covers allowed sources, forbidden sources raise `HaltSourceForbiddenError`, resume-is-unrestricted, error message quality. `tests/test_auditor.py` 3 tests flipped from "must halt" to "must alert + no halt": `test_critical_flag_alerts_operator_no_auto_halt`, `test_risk_governor_breach_never_downgraded_in_bootcamp` (severity stays critical, no halt), `test_emergency_halt_bypass_alerts_operator_no_auto_halt`, `test_post_bootcamp_config_prevents_critical_downgrade` (severity preserved, no halt). `tests/test_kill_switch.py` and `tests/test_risk_governor.py` updated to pass `source="cli"` / `source="test"` instead of relying on default `source="unknown"` (now forbidden).
- **Operator policy 2026-05-08:** kill switch is operator-action-only. Triggered by 2 days of an auditor auto-halt over a debatable concentration call (35% / 6 sectors / BK 4.6%) that blocked all trading. Operator chose to remove the auditor's halt power entirely; alerts still flow.

### Hotfix — OHLCV trailing zero/NaN close sanitizer (root cause of #52)

- **`src/data_ingestion/market_data.py:_extract_batch_frames`** now calls a new `_trim_invalid_trailing_close` helper that drops trailing rows where `Close <= 0` or `Close == NaN` from the per-ticker DataFrame before returning it. yfinance batch downloads occasionally append a row with `Close == 0.0` or NaN for tickers whose data fetch partially failed (Open/High/Low/Volume populated, just Close=0/NaN). `df.dropna(how="all")` doesn't catch those rows, so they propagated to `engine.py:_compute_price_features` as `current_price = float(close.iloc[-1]) = 0`, triggering `template.py:177`'s #621 packet refusal — which until the #52 hot-fix crashed `enhance_packet_with_llm` with NoneType AttributeError. Affected tickers in production logs: AMZN+BAC×4 (2026-05-08), AVGO×5 (2026-05-07). Sanitizer logs a per-ticker WARNING with trimmed-row count when triggered. New test file `tests/data_ingestion/test_market_data_close_sanitize.py` (10 tests) covers: trailing zero, trailing NaN, multiple trailing invalid, valid data unchanged, interior zero preserved (only TRAILING is sanitized), all-invalid → empty, missing-Close-column defensive, warning emitted when trimmed, no-warning when clean.

### Hotfix — packet_writer None-guard (closes #52)

- **`src/llm/packet_writer.py:enhance_packet_with_llm`** now short-circuits when called with `packet=None`. `build_packet_from_features` (`src/packets/template.py:177`) legitimately returns None for tickers with `current_price <= 0` (#621 defensive — silent feature-fetch failure for ~14 tickers/day). Two callers — `src/services/mr_scan_service.py` (Mean Reversion scan) and `src/services/scan_service.py` (Pullback scan) — were missing the matching `if packet is None: continue` guard, crashing with `'NoneType' object has no attribute 'llm_conviction_parse_failed'` at packet_writer.py:729 every cycle. Today's `arcis.log` shows 4 fires today, ~30min cadence (332 historical occurrences since 2026-04-30). Watch loop's `_safe_run` caught each with 60s backoff so the loop survived, but **every MR scan attempt was lost**. Belt-and-suspenders fix: (1) `enhance_packet_with_llm` now returns None + logs WARNING when input packet is None, (2) `mr_scan_service.py` + `scan_service.py` add the missing caller-side `if packet is None: continue`. Sibling-search confirmed `universe_scanner.py:175`, `corpus_generator.py:274`, `backtester.py:204` already had the guard. New regression test `tests/llm/test_packet_writer_none_guard.py` (4 tests) locks the entry-guard behavior.

### Sprint 4 Wave 2 hotfix — MetricCard sign-aware prefix formatting (T18 sibling-fix)

- **`frontend/src/components/MetricCard.jsx`** rewrites `{prefix}{value}{suffix}` rendering through a new `_formatValue(prefix, value, suffix)` helper that moves a leading numeric sign before the prefix. Negative dollar amounts now render `-$6.55` (sign before prefix) instead of `$-6.55` (sign after). Visual-verify of the post-Wave-2 deploy on `halcyonlab.app` caught `AVG LOSS $-6.55` in the ShadowLedger Closed-tab summary card — a sibling site that T18's per-row fix didn't cover. Centralizing the fix at the component level closes 9 call sites in one edit (4 in ShadowLedger, 2 in ModelPerformance, 2 in LiveLedger, 1 in Dashboard). Regex guard `/^[-+]\d/` ensures non-numeric leading-dash values like `--` (no-data placeholder) pass through unchanged. New `frontend/src/components/MetricCard.test.jsx` (8 tests) locks: unsigned-value pass-through, negative-sign move, positive-sign move, `--` placeholder pass-through, zero, no-prefix bypass, suffix preservation, comma-separated negative.

### Sprint 4 Wave 1 hotfix — urllib3 + DATABASE_URL test fixture

- **urllib3 added to requirements-cloud.txt** (6th recurrence of cloud-deploy import drift bug class). Sprint 4 T3 added `import urllib3.exceptions` to `src/notifications/telegram.py` for the `safe_send` network-error catch list. T7 fast-lane AST walker correctly flagged this as reachable from `cloud_app` via `cloud_routes/platform.py → notifications/telegram.py` but missing from `requirements-cloud.txt`. urllib3 ships transitively via requests today; declaring explicitly per defensive policy. Walker package count: 53 → 54.
- **DATABASE_URL fixture in `_clean_env()`**: `tests/test_cloud_requirements_imports.py::TestSlowLaneVenvImport` strips env vars for hermeticity but `cloud_app` validates `DATABASE_URL`/`ARCIS_DB_PATH` at import time (`src/config/__init__.py:65`). Subprocess env now sets `DATABASE_URL=postgresql://fake:fake@localhost:5432/fake` so the slow-lane import-graph check works without exposing the underlying RuntimeError before pytest can observe `ModuleNotFoundError` failures (the actual test target). Both flagged by Sprint 4 PR #1020 review.

### Sprint 4 — Cockpit Followups + Notification Subsystem (sprint/cockpit-followups-2026-05-07/base)

<!-- T2  --> Fixed two stacked silent-swallow bugs in CUSUM alarm path: (a) renamed `detect_performance_change` → `check_performance_drift` at `src/scheduler/overnight.py:127-128` (ImportError was caught by outer try/except, never reached the inner Telegram code), (b) renamed `send_telegram_message` → `send_telegram` at `src/scheduler/overnight.py:134/149/304/311` (NameError caught by inner try/except). New regression test `tests/notifications/test_overnight_alarm_paths.py` (6 tests) locks both fixes. Without (a), T2's send_telegram fix would have shipped incomplete because the ImportError fires first.
<!-- T3  --> Added `safe_send(event_type, **kwargs)` central dispatcher to `src/notifications/telegram.py`. Catches ONLY network errors (urllib3.HTTPError, requests.RequestException, socket.timeout, OSError); ImportError/NameError/AttributeError propagate so code-level bugs surface at startup (not silently at runtime). Bot-token redaction applied at BOTH the warning log AND the `_record_send_failure` persistence path (defense-in-depth for T15's notifications_sent table). Re-exported from `src/notifications/__init__.py`. T15 will wire the `_record_send_failure` stub to the `notifications_sent` table; T4 will migrate the 25+ caller sites from try/except Exception to safe_send.
<!-- T4a --> Migrated try/except Exception caller pattern to safe_send wrapper at src/scheduler/{watch,reports,watch_handlers,overnight}.py. ImportError on notify_X functions now propagates to startup; only network errors are caught. Part of Group A.3 16-file migration (T4a scheduler track).
<!-- T4b --> Migrated 13 notification call sites across `src/services/scan_service.py` and `src/shadow_trading/executor.py` from the `try { import notify_X + is_telegram_enabled() check } except Exception` pattern to one-line `safe_send(event_type, **kwargs)`. scan_service.py: 1 site (`trade_opened` on shadow trade open). executor.py: 12 sites — `trade_closed`, `risk_alert` × 2 (live capital guard + daily loss limit), `trade_opened` (live trade), `milestone` × 7 (open/close/streak milestones in helper functions), `streak_alert`, `exposure_alert`. Redundant inline `send_telegram` imports at 8 executor.py sites eliminated (module-level import already present). `safe_send` also hoisted to module-level import in scan_service.py. Post-fix: 0 `try:.*from src.notifications` matches in all 4 scope files.
<!-- T4c --> Migrated 4 training+risk notify call sites to `safe_send`: `training/canary.py` (_send_alert → `model_event`), `training/ingestion_gate.py` (alert_training_halt → `system_event`), `training/trainer.py` (holdout-empty → `trainer_holdout_empty`), `risk/governor.py` (governor-disabled → `system_event`). Eliminates silent swallow of ImportError/NameError at each call site.
<!-- T4d --> Migrated remaining `try/except Exception` notification patterns to `safe_send`: `research_synthesizer.py` (1 site — `send_telegram` direct call → `safe_send("research_digest", ...)`), `cli/commands.py` (1 site — `_notify_startup_telegram` → `safe_send("startup_complete", ...)`), `cloud_routes/platform.py` (3 sites — outer `try/except Exception` wrappers removed from `notify_backtest_complete`, `notify_strategy_promoted`, `notify_strategy_demoted` calls; platform_events functions retain their own internal error handling). `auditor.py` confirmed 0 notification patterns via GREP (no-op).
<!-- T5  --> Fixed I10 — relocated lazy `from src.notifications import safe_send` imports from function bodies to module-level in `src/cli/commands.py`. ImportError now surfaces at process startup, not at first command-execution hit. New regression test `tests/cli/test_commands_imports.py` (NEW, +2 tests) AST-walks the module to lock no-lazy-imports invariant.
<!-- T6  --> Fixed I12: `check_action_reminders` at src/notifications/telegram_commands.py now uses per-check try/except (5 independent reminder checks). Previously a function-wide bare `except Exception` aborted all 5 if any raised — including operator-action-required reminders (API key rotation, phase-gate milestone, retrain-overdue alert). Fixed CC2: consolidated duplicate `_get_telegram_config` (telegram.py:104 + telegram_commands.py:32) into shared `src/notifications/_config.py` (NEW). Both modules import from the new module. Regression test `tests/notifications/test_check_action_reminders_isolation.py` (NEW) locks both fixes.
<!-- T7  --> Added cloud-req fast-lane AST guardrail (`tests/test_cloud_requirements_imports.py` + `scripts/check_cloud_deploy_imports.py`) preventing the recurring cloud-deploy import drift bug class (jsonschema -> numpy -> requests -> scipy — Sprint 3 #1007 was 4th recurrence). PR-time check; sub-second runtime; walks src/api/cloud_app.py import graph transitively through all of src/, validating each top-level package is stdlib or present in requirements-cloud.txt. Catches all 4 historical IMPORT-statement recurrences (jsonschema, numpy, requests, scipy) including deep-transitive ones (jsonschema lives at src/platform/capability_registry/schemas.py, two hops outside src/api/). Note: tzdata (5th recurrence, surfaced by T8 slow-lane) loads via `zoneinfo.ZoneInfo()` runtime string lookup — out of AST walker design scope; T8 slow-lane is the detection vector for that class. T8 slow-lane provides defense-in-depth via venv subprocess.
<!-- T8  --> Added cloud-req slow-lane venv subprocess test (`tests/test_cloud_requirements_imports.py` extension) + tzdata to requirements-cloud.txt (5th recurrence of cloud-deploy import drift bug class — `zoneinfo.ZoneInfo('America/New_York')` fails on Windows clean venv without OS tzdata; masked on Linux Render). T8 revision adds: subprocess child-kill on timeout (`_run_or_kill` helper), PyPI-offline skip guard (`has_pypi_network` fixture), configurable timeouts via env vars (`CLOUD_REQ_PIP_TIMEOUT`, `CLOUD_REQ_IMPORT_TIMEOUT`), and pytest slow-marker registration (`pytest.ini`). Marked `@pytest.mark.slow`; creates temp venv, installs ONLY requirements-cloud.txt, asserts `from src.api.cloud_app import app` succeeds. Synthetic regression-lock asserts missing scipy raises ModuleNotFoundError. Defense-in-depth complement to T7 fast-lane AST walker; informational/CI-only — does NOT block PR merge.
<!-- T9  --> Extended _desk_clause() helper at `src/api/cloud_routes/trades.py:42-60` from 2-tuple to 3-tuple (`(frag, params, cohort_id)`). For `desk='live'`: emits SQL fragment `source = %s` with param `'live'` AND `cohort_id='trades.live_only'`; other desks: `cohort_id='trades.all_closed'`. 5-endpoint blast radius — all 5 callers in `trades.py` (shadow_open, shadow_closed, sharpe_attribution, shadow_metrics, shadow_account) updated to consume new 3-tuple. shadow_metrics emits cohort from helper instead of hardcoded 'trades.all_closed'. Updated 5 helper unit-test unpacks at `tests/test_shadow_desk_filter.py` to match new tuple shape. New `tests/api/test_sharpe_attribution.py` (NEW file) + extended `tests/api/test_shadow_metrics.py` cover per-desk cohort behavior across 11 tests.
<!-- T10 --> Fixed cockpit-#2: `/api/status` `open_positions` SQL now includes `AND source = 'live'` predicate, aligning the query with its `_meta` cohort label `'trades.live_only'`. Pre-fix, the count included all open trades regardless of source (live + swing), making the label a lie. Sibling-search confirmed only one `WHERE status='open'` site in `core.py`. Added 2 regression-lock tests: `test_status_open_positions_cohort_aligned` (5-row fixture: 2 live + 3 swing → open_positions=2) and `test_open_positions_sql_filters_source_live` (SQL call_args assertion verifying `source` and `live` appear in the issued SQL).
<!-- T11a --> Added `compute_total_pnl_dollars(instrumented)` to `kpis_compute.py` (sum of `pnl_dollars` rounded to 2dp). Wired into `/api/kpis` response as top-level `total_pnl_dollars` field and `_meta.total_pnl_dollars` with `cohort='kpi.canonical'`, `n=n_trades`, `label=COHORT_LABELS['kpi.canonical']`. Zero-safe: returns `0.0` when no instrumented trades. +3 tests in `tests/api/test_kpis.py` (value+sum, meta cohort+n, empty-DB zero).
<!-- T11b --> Hardened email subsystem (Group B): (C5) `cc_addresses or []` guards against YAML omission returning None — eliminates TypeError on `[recipient] + cc_addresses`; (C4) removed YAML `password` fallback from `send_email` — `EMAIL_PASSWORD` env var now required, warning emitted at call-time if YAML key is non-empty (security: passwords must not live in YAML config); (C17) when `smtplib.sendmail` returns a non-empty failures dict, invoke `safe_send("system_event", ...)` as telegram fallback with subject + body truncated to 400 chars; (N1) re-exported `digest_builder` module from `src/email/__init__.py` so callers can `from src.email import digest_builder`. New `tests/email/test_notifier.py` (+8 tests) covers all four fixes plus envelope, TLS, and ConnectionRefused paths.
<!-- T12 --> Replaced PromotionGateCard (5th card) in `frontend/src/components/dashboard/KPIStrip.jsx` with new `TotalPnlDollarsCard` reading `safeKpis.total_pnl_dollars` + `_meta.total_pnl_dollars` envelope. Promotion-gate vote count surfaced via tooltip badge under `TrafficLightCard` (new `promotionKpi` prop) so the methodology-gate signal is preserved without consuming a primary card. Closes cockpit-#8b / #SP3-T12-pnl-card. New tests in `frontend/src/components/dashboard/KPIStrip.test.jsx` lock: dollar formatting `$X,XXX.XX`, meta badge `n=...` visible, `Promotion Gate` text absent, `4/5` vote count rendered in TrafficLight slot.
<!-- T13a --> Added `_html_escape(text)` helper (I6) escaping `&`, `<`, `>` for HTML parse_mode messages. Added chunked send to `send_telegram` (C15): messages >4000 chars are split at `_TELEGRAM_CHUNK_SIZE=4000` boundaries and sent as multiple messages with `[chunk N/M]` markers. Extraction of `_send_single` helper keeps the function body under the 60-line cap. New tests: `tests/notifications/test_html_escape.py` (6 tests) and `tests/notifications/test_telegram_chunked_send.py` (4 tests).
<!-- T13b --> C16: `notify_research_digest` now truncates `digest_summary` at 800 chars and appends `\n[truncated; see email digest]`. C7: `notify_overnight_complete` mirrors `notify_overnight_training_complete` dict-with-success pattern — dict values with `success=False` render ❌ with error text instead of silently showing ✅. I11: `notify_action_required` raises `ValueError` on unknown urgency (was silent default to "🔔"). I16: hardcoded `&amp;` in `notify_premarket_brief` ("S&amp;P") and `notify_weekly_digest` ("P&amp;L") replaced with `_html_escape()` calls — output identical but now uses canonical helper.
<!-- T13c --> I15: new `src/data_ingestion/finnhub.py` with `normalize_earnings_time(raw)` — maps "Pre-market"/"PRE"/"before market" → "BMO", "After hours"/"AMC"/"after market" → "AMC", None/"" → "TBD". Wired into `notify_position_earnings_warning` replacing inline ad-hoc string check that missed "Pre-market". Note: I11 urgency ValueError guard delivered in T13b per spec order.
<!-- T13-SECREV --> [SECURITY REVISION] applied `_html_escape` to 11 external-data interpolations across `src/notifications/telegram.py`: `last_error` (notify_collection_failure), `top_paper` (notify_research_papers), `digest_summary` (notify_research_digest), `model_name`/`event`/`detail` (notify_model_event), `exit_reason`/`ticker` (notify_trade_closed), `event`/`detail` (notify_system_event), `action`/`detail` (notify_action_required), `milestone`/`detail` (notify_milestone), `key`/`val`/`err` (notify_overnight_complete), `task`/`error` (notify_overnight_training_complete). Made `_html_escape` None-safe and str-coercing (prevents AttributeError when Optional[str] fields are None). Added plaintext fallback in `send_telegram` chunked path: if any HTML chunk returns 400 (Telegram tag-tearing error), all chunks are retried with `parse_mode=None` ensuring delivery. New static-analysis test `tests/test_safe_send_event_type_literal_guardrail.py` AST-walks all `safe_send()` call sites in `src/` and asserts the `event_type` argument is always a string literal — fails on any future PR that wires a dynamic value to event_type. Net +5 new tests (3 None/int-guard + 1 plaintext-fallback chunk + 2 AST-literal guardrail).
<!-- T14 --> Registered `notifications_sent` (id INTEGER PK + event_type, channel ['telegram'|'email'], recipient, sent_at, status ['ok'|'failed'|'dropped'|'heartbeat'], retry_count, error_msg + index on (event_type, sent_at DESC)) and `notifications_dedup` (id INTEGER PK + UNIQUE(event_type, dedup_key) + sent_at) tables in `src/schema/registry.py` per CLAUDE.md schema-rules-mandatory. Schema-only — T15 (Batch 4) wires the write hooks; retention policy deferred to Sprint 5 follow-up `#SP5-notifications-retention`. EXPECTED_TABLE_COUNT bumped 68→72 in `tests/test_schema.py`; +5 schema-shape tests covering column types, nullability, indexes, and UNIQUE constraint.
<!-- T15a --> Migrated `_DEDUP_CACHE` (in-memory dict) in `src/notifications/platform_events.py` to DB-backed dedup via `notifications_dedup` table. New `_already_notified_recently_db(event_type, dedup_key, conn=None, db_path=None)` reads/writes the table; expired rows (>24h) are updated in-place so the slot is reused. NSSM-restart-safe: dedup state survives watch-loop restarts because the DB persists across process boundaries. Added `write_heartbeat(conn=None)` writes a `status='heartbeat'` sentinel to `notifications_sent` for pipeline liveness checks. +5 tests in `tests/notifications/test_dedup_persistence.py`.
<!-- T15b --> Wired `_write_notification_sent(event_type, channel, status, error_msg, recipient, conn)` into `src/notifications/telegram.py` `safe_send` (success → `status='ok'`; network failure → `status='failed'` via `_record_send_failure`) and `src/email/notifier.py` `send_email` (SMTP success → `channel='email', status='ok'`; all failure paths → `channel='email', status='failed'`). New `src/api/cloud_routes/notifications.py` exposes `GET /api/notifications/health` returning last-24h `{success_rate, fail_count, dedup_hits, oldest_unack_alert}` from `notifications_sent` + `notifications_dedup`. Route registered in `src/api/cloud_app.py`. +4 tests in `tests/notifications/test_safe_send_hooks.py` + 4 tests in `tests/api/test_notifications_health.py`.
<!-- T15c --> New `frontend/src/components/dashboard/NotificationsHealthPanel.jsx` — bottom-of-page widget that reads `/api/notifications/health` via arrow-form `queryFn` (per Sprint 3/4 T16 ESLint rule). Displays success_rate badge (green ≥95%, amber ≥80%, red otherwise), fail_count, dedup_hits, and oldest_unack_alert. Added `getNotificationsHealth()` to `frontend/src/api.js`. Appended §"Notification dedup migration" to `docs/operator-guide.md` with NSSM restart warning about expected one-shot duplicate alerts + optional post-deploy dedup seed script.
<!-- T15-REV --> QA REJECT revision: (MF1) wired `_already_notified_recently_db` into both `notify_backtest_complete` and `notify_shadow_gate_ready` in `platform_events.py` — both now use DB-backed restart-safe dedup; `_already_notified_recently` (in-memory) retained with zero production callers for now (see module docstring). (MF2) Added `force_send: bool = False` kwarg to `notify_validation_summary` in `telegram.py` — `force_send=True` bypasses the silent-on-pass branch (spec C12). (MF3) Chose **Option A** for `/api/notifications/health` cloud architecture per operator review: flipped `sync_to_postgres=True` on both `notifications_sent` and `notifications_dedup` in `src/schema/registry.py` so render_sync.py mirrors them to Postgres, refactored the endpoint to dual-mode (SQLite local / Postgres on Render via `psycopg2`, mirroring `kpis_compute._fetch_closed_trades` pattern), and re-included the router in `src/api/cloud_app.py` with `verify_auth` dependency override (matching the kpis/broker_exceptions/preflight registration pattern). The cockpit `NotificationsHealthPanel` widget is now functional in both local dev and Render production. (SF4/auth) Resolved by re-including with `verify_auth` override. (SF5) End-to-end test for `safe_send` failure path now writes to a real tmp_path SQLite DB (no mock on `_write_notification_sent`). (SF6/heartbeat) Deferred: wiring `write_heartbeat` into `src/scheduler/watch.py` is out of T15 scope; tracked as follow-up.
<!-- T16 --> Extended `frontend/eslint-rules/no-bare-queryfn-with-args.js` to flag any `queryFn` value that is not an `ArrowFunctionExpression` or `FunctionExpression` (catches Identifier + CallExpression in addition to the Sprint 3 MemberExpression-only scope). Wrapped bare Identifier call sites: `StrategyResearch.jsx:41` and `PlatformStatusWidget.jsx:13` (`getPlatformStrategies` → `() => getPlatformStrategies()`). Also wrapped `BrokerExceptionsPanel.jsx:110` and `PreflightStatusCard.jsx:77` which were newly caught by the extended rule (zero-arg local helpers, safe in practice but now consistent). Created `frontend/eslint-rules/no-bare-queryfn-with-args.test.js` with 4 RuleTester cases: Identifier fires, ArrowFunctionExpression passes, FunctionExpression passes, CallExpression fires. `npm run lint:queryfn` exits 0; `tests/test_eslint_queryfn_guardrail.py` 2/2 pass.
<!-- T17a --> Migrated Calmar ratio at `src/evaluation/cto_report.py:738` and `src/simulation/engine.py:439` to canonical `calmar_ratio()` from `src.evaluation.statistics`. Both sites now import and call `calmar_ratio(annualized_return, max_dd)` instead of inline division. Removed both from `_ALLOWLIST` in `tests/test_calmar_canonical_only.py`. Behavioral equivalence: canonical returns `0.0` for zero drawdown; both call sites guard `max_dd > 0` or `max_dd != 0` before invoking so zero-drawdown behavior is unchanged. +6 new tests in `test_calmar_canonical_only.py` (T17a/T17b canonical-match assertions + allowlist-empty enforcement + compute_calmar zero-dd → 0.0).
<!-- T17b --> Migrated remaining 2 Calmar canonical-debt sites: `src/evaluation/backtester.py:343` (`round(ann_return / abs(max_dd_pct), 2)` → `round(calmar_ratio(ann_return, abs(max_dd_pct)), 2)`) and `src/platform/metrics.py:75` (`compute_calmar` body delegated to `calmar_ratio(total_return, max_drawdown)`). Behavioral change: `compute_calmar(x, 0.0)` now returns `0.0` (canonical) instead of `float('inf')`. INF-sentinel sibling-search across src/ found 0 callers that depend on the inf sentinel. Emptied both `_ALLOWLIST` and `_CALMAR_FUNC_ALLOWLIST` in `tests/test_calmar_canonical_only.py`. Updated `_scan_calmar_func_defs` guardrail to exempt thin-wrapper calmar-named functions whose body calls `calmar_ratio(` — allowing `compute_calmar` to retain its API-compatible name while the formula debt is resolved. All 4 canonical-debt Calmar sites now migrated; both allowlists are empty.
<!-- T18a --> Fixed negative-P&L sign formatting in `LiveLedger.jsx` `PnlValue` component (line 40): `Math.abs(value).toFixed(2)` without sign prefix stripped the minus sign from all losing trades, showing e.g. `$150.50` instead of `-$150.50`. Fixed with `{value > 0 ? '+' : value < 0 ? '-' : ''}` prefix. New test file `frontend/src/pages/__tests__/PnlSignFormatting.test.jsx` (T18a tests: negative → `-$150.50`, positive → `+$200.00`, zero → `$0.00`).
<!-- T18b --> Fixed negative-P&L sign formatting in `ShadowLedger.jsx` at 3 sites: `PnlValue` component (line 64, same pattern as T18a), open-cols inline render (line 568, dead code — open tab uses `OpenPositionCard` cards), and closed-cols inline render (line 592). All 3 sites now use `{val > 0 ? '+' : val < 0 ? '-' : ''}` ternary before `$`. `PnlSignFormatting.test.jsx` extended with 4 T18b assertions targeting the closed tab (where SummaryRow PnlValue + closedCols render). **Out-of-scope finding:** `OpenPositionCard.jsx:122` has the same bug for live open-trade P&L display; PM-tracked for T18d.
<!-- T18c --> Fixed negative-P&L sign formatting in `TradeHistory.jsx` `formatDollars` helper (lines 31-36): `sign = val >= 0 ? '+' : ''` produced no sign prefix for negative values. Fixed to `val > 0 ? '+' : val < 0 ? '-' : ''`. `PnlSignFormatting.test.jsx` extended with 2 T18c assertions (negative → `-$150.50`, positive → `+$200.00`). ActivityFeed regression-lock test confirms `ActivityFeed.jsx:57` remains correct (already uses raw signed value).
<!-- T18d --> fix(cockpit-#4): OpenPositionCard.jsx:122 — correct sign-dollar order for open-tab P&L (negative rendered $-150.50; now renders -$150.50); sibling-site fix for T18 5-site sweep
<!-- T18e --> Fixed cockpit-#4 sign-formatting bug at `frontend/src/components/ActivityFeed.jsx:57` (7th sibling site). The original `($${d.pnl_dollars >= 0 ? '+' : ''}${d.pnl_dollars.toFixed(2)})` placed the sign INSIDE the dollar sign, rendering `($-150.50)` for negative P&L. Replaced with native sign-preserving pattern `(${sign}$${Math.abs(value).toFixed(2)})`, matching the canonical form in LiveLedger/ShadowLedger/OpenPositionCard. Zero sign produces `($0.00)` (no prefix). The original T18 spec wrongly listed ActivityFeed as non-buggy; T18d agent caught it during sibling-search review.
<!-- T19 --> Extended reconciliation test coverage (Sprint 4 T19a/b/c): (a) `postgres_session` fixture added to `tests/conftest.py` (function-scoped, isolates per test per reviewer #12); `test_dashboard_reconciliation.py` parametrized against SQLite + Postgres backends — Postgres variant skipped when `TEST_DATABASE_URL` absent so test count stays stable across CI and local environments (`DATABASE_URL` is intentionally NOT honored — operator's `.env` points at production Render Postgres and CLAUDE.md forbids tests touching prod) (#SP4-render-pg-reconcile); (b) `test_kpis_meta_envelope_reconciliation` in `tests/api/test_status.py` regression-locks `_meta.rf_adjusted_excess_sharpe`, `_meta.win_rate`, and `_meta.total_pnl_dollars` all carrying `cohort='kpi.canonical'` and non-negative integer `n` fields, with full hermetic patch set (`_fetch_closed_trades` + `_fetch_spy_returns_for_trades` + `filter_fully_instrumented`) (#SP4-kpis-meta-reconciliation-test); (c) `test_status_open_positions_cohort_aligned_via_core_router` regression-locks `core.py:147-150` SQL includes `source='live'` and `_meta.open_positions.cohort='trades.live_only'` via `create_router` path (complementary to existing `cloud_app`-patched T10 tests) (#SP4-status-open-positions-cohort).
<!-- T20 --> *placeholder mid-W2 visual-verify checkpoint*
<!-- T21a --> Extended `tests/notifications/test_telegram_commands.py` with `TestCommandHandlerHappyPaths` (17 tests) and `TestCommandHandlerErrorPaths` (17 tests) covering all 17 `handle_command` routes (C13). New `tests/notifications/test_telegram_send_path.py` (+1 test) foundation send-path test: `send_telegram` → POST API mock → `True` return (CC5). Net +35 tests.
<!-- T21b --> Added 5 typed exception classes (`CostCapExceededError`, `AgentTimeoutError`, `LLMUnavailableError`, `NoQuorumError`, `InvalidQuestionError`) to `src/notifications/telegram_commands.py`. Extracted `run_council_command` wrapper for patchability. Replaced generic `except Exception` in `_cmd_council` with 5 typed except branches returning categorized diagnostic strings per C14 spec. Added `@dataclass` payload classes (`TradeOpenedPayload`, `TradeClosedPayload`, `EodReportPayload`, `WeeklyDigestPayload`) to `src/notifications/telegram.py` (CC3): missing required field → `TypeError` at construction. +13 tests.
<!-- T21c --> `docs/operator-guide.md`: added §12 "Notification Troubleshooting" covering bot-silent decision tree (health endpoint, NSSM restart, stale watch.lock), bot-token rotation procedure, email-digest failure diagnosis (SMTP config + `notifications_sent` table query), and subsystem health verification via `/api/notifications/health` (I13). `docs/telegram-commands.md`: added "CLI: send-test-email" section documenting the command, when to use it, and troubleshooting table (I14). TOC entry for §12 added to operator guide.
<!-- T21-REV --> Wired CC3 dataclass payloads into all 4 notify_* functions: `notify_trade_opened`, `notify_trade_closed`, `notify_eod_report`, `notify_weekly_digest` now accept typed payload objects only (Option A — breaking change). Updated `safe_send` to route payload events via `kwargs["payload"]`. Updated all 6 call sites: `scheduler/reports.py` (eod_report + weekly_digest), `scheduler/universe_scanner.py` (trade_opened), `shadow_trading/reconcile.py` ×2 (trade_closed), `shadow_trading/executor.py` (trade_closed via safe_send). Updated 7 test files to use payload API. New `tests/notifications/test_telegram_payload_wiring.py` (+21 tests) covering wiring + safe_send full chain.
<!-- T23 --> Sprint 4 closeout (T23): visual-verify gate (13 post-merge screenshots, all PASS), operator-guide enhancements (§1 GPU prerequisite, §5 corpus-not-progressing decision tree, §7 watchdog-timeout signs, §8 SD#NN glossary entry), WON'T-FIX paragraph for `#SP4-settings-backend-float32-storage`, test floor confirmed ≥4798 (T22 skipped → `#SP5-notifications-routing-policy` opened as #69), CHANGELOG T22 placeholder removed, `src/data_enrichment/news.py` 490-line violation disclosed in `config/known_violations.json`.

## [v0.33.0] - 2026-05-07 — Sprint 3 Cockpit Coherence

### Group E — Correctness bugs (5 fixes)

- **T1 (#987): E5 Calmar 1000x overshoot.** Replaced ad-hoc formula in analytics.py:568 with call to canonical src/evaluation/statistics.py calmar_ratio() helper. Added tests/api/test_calmar_unit_audit.py regression-lock + tests/test_calmar_canonical_only.py CI guardrail. 3 additional hand-rolled Calmar sites (cto_report.py, engine.py, backtester.py) allowlisted, tracked as #SP4-calmar-debt.
- **T2 (#988): E6 Attribution paired-overlap gate.** Replaced marginal-count gate with paired-overlap count. Updated Attribution.jsx label to paired_n/200 with subtitle. Fixed regression: old gate overstated statistical power when marginal counts exceeded paired overlap.
- **T3 (#990): E7 Monitoring 500/503 fix.** analytics.py:935-957 now returns {snapshots: [], note: 'system_metrics is local-only...'} on UndefinedTable/runtime errors. Updated Monitoring.jsx data-shape consumption. Backend + frontend handle local-only system_metrics gracefully on Render.
- **T4 (#988): E2 stop_loss sign + E4 profit_factor None sentinel.** E2: sign inversion is in display layer (tracked as #SP4-stop-loss-fallback). E4: engine.py:458 now emits Python None instead of 999.0 when profit_factor is inf. T4-followup made compute_verdict() + print_heatmap() None-safe via 'or 0' pattern.
- **T11 (#985): Settings float-precision clamp + Health IB-status feature flag.** Settings risk inputs no longer show float artifacts (0.0049999... to 0.005). Health IB-status card rendered conditionally behind feature flag.

### Group A — Cohort taxonomy (2 backend + 1 frontend)

- **T8 (#991): A1.A Backend _meta envelope helper + KPI/CTO/Status emission.** New src/api/cohort_meta.py with meta_entry(cohort_id, label, n) helper and 8-cohort closed taxonomy. Wired _meta onto /api/kpis, /api/cto-report, /api/status. All changes additive.
- **T9 (#993): A1.B _meta on remaining 7 endpoints.** Wired meta_entry() into /api/shadow/metrics (all desks → trades.all_closed; #SP4-shadow-metrics-live-cohort for true live filter), /api/attribution/stats, /api/strategy-detail, /api/model-performance, /api/build-score, /api/health/hshs, /api/stress-test/results, /api/simulation/results. T9-followup corrected trades.live_only cohort mapping at f42a095.
- **T12 (#997): A4 Dashboard/TradeHistory/Strategy meta consumption.** KPIStrip.jsx: rf-adjusted excess Sharpe + win rate cards wired to _meta cohort badges. TradeHistory.jsx: inline cohort badge below Excess Sharpe panel. Strategy.jsx: inline cohort badge from /api/strategy-detail._meta. T12-followup added missing tests + spec-drift resolution. total_pnl_dollars has no primary value card (#SP3-T12-pnl-card).
- **T5 (#986): A3 KPICard meta prop + cohort badge.** KPICard in KPIStrip.jsx accepts meta prop and renders cohort badge (n=N · last-segment). Foundation for T12 sub-card wiring.

### Group B — Header source-of-truth

- **T10 (#992): B1+B2 Layout.jsx /api/kpis with 3-state fallback.** Header TL indicator now reads stage_traffic_light from /api/kpis. Three fallback states: pending to TL: ..., loaded-but-null to TL: COMPUTING, errored to TL: ERR. Closes TL: NOT SET regression.
- **T16 (#999): B3 CI dashboard reconciliation test (cohort-aware, SQLite-only).** New tests/test_dashboard_reconciliation.py — 8 tests regression-locking _meta envelope across 5 endpoints. Cohort-aware: test_closed_count_reconciles checks cohort match BEFORE n equality. Postgres validation deferred to #SP4-render-pg-reconcile.

### Group C — Loading state

- **T6 (#983): C1 Shared LoadingState component (with retryDisabledFor cooldown).** New frontend/src/components/LoadingState.jsx. 3-state: loading to data/empty/error. retryDisabledFor={ms} cooldown. API: isLoading, isError, error, retry, retryDisabledFor, isEmpty, loadingMessage, emptyMessage, compact, children.
- **T13 (#996): C2 Migrated 4 widgets to LoadingState.** BrokerExceptionsPanel, DBSchema, Health, Monitoring — all use LoadingState instead of ad-hoc patterns. Closes E7 presentation bug: Monitoring 500/503 now renders explicit error card + retry button instead of infinite spinner.

### Group F — Operator-action ambiguity

- **T7 (#984): F1 Shared ActionButton (cliOnly + secure-context fallback).** New frontend/src/components/ActionButton.jsx. cliOnly=true renders disabled button + [CLI only] badge + tooltip with CLI command copy. Clipboard uses navigator.clipboard with window.isSecureContext check; falls back to pre with select-on-click hint. T7-followup added interactive prop to Tooltip with hover-bridge.
- **T14 (#998): F2 Migrated 4 pages to ActionButton.** LiveLedger (reconcile button to cliOnly), DiagnosticKickoffButtons (3 buttons), Simulation (2 run buttons), Council (Run Council Now + Ask Council). profit_factor null renders 'N/A (no losses)' in Simulation.
- **T15 (#995): F2.B Settings IB toggle migration to visually-disabled with whyDisabled tooltip.** live_trading.ib.shadow_mode and live_trading.ib.paper_routing toggles are visually disabled (cursor-not-allowed opacity-40). whyDisabled: 'Effect requires local IB Gateway connection' rendered inline, always visible. Click is a true no-op. Non-IB toggles unchanged (BC).

### TanStack v5 sweep + ESLint guardrail

- **T17 (#994): E1.A1 Bare-queryFn sweep (Layout, RevenueProjection, IBShadow, Notes).** 4 bare refs wrapped in arrow form.
- **T18 (#1003): E1.A2 Bare-queryFn sweep (Dashboard, ModelPerformance, StressTest, Training).** 11 bare refs wrapped.
- **T19 (#1002): E1.A3 Bare-queryFn sweep (Docs, Validation, TradeHistory).** 3 bare refs wrapped. Closes TradeHistory.jsx:238 getSharpeAttribution(desk) desk=[object Object] regression.
- **T20 (#1001): E1.B Bare-queryFn sweep (Attribution, Settings, Health, Monitoring).** 8 bare refs wrapped.
- **T21 (#1000): E1.B2 Bare-queryFn sweep (LiveLedger, Council, Simulation, ShadowLedger).** 6 bare refs wrapped. Closes ShadowLedger.jsx:476/478/481 primary desk=[object Object] regression sources.
- **T22 (#1004): E1.C ESLint custom rule + pytest fixture preventing future bare-queryFn regressions.** frontend/eslint-rules/no-bare-queryfn-with-args.js reports error on bare MemberExpression queryFn. Registered as local/no-bare-queryfn-with-args: error. lint:queryfn npm script. tests/test_eslint_queryfn_guardrail.py with 2 tests.

### Test floor

- Pre-Sprint-3: 4602 baseline (post-Sprint-2).
- Post-Sprint-3: **4702 passing** (actual run 2026-05-07 T23 closeout). Spec target was 4646 (44 new tests estimated); actual +100 net from pre-sprint baseline, likely due to parametrized tests expanding beyond estimates. 43 pre-existing failures unchanged (tracked in CI, not regressions).

### Sprint 3 CI guardrails added

- tests/test_calmar_canonical_only.py: any def *calmar* outside src/evaluation/statistics.py fails CI.
- tests/test_eslint_queryfn_guardrail.py: bare-queryFn refs in useQuery fail via ESLint rule.
- tests/test_dashboard_reconciliation.py: cohort-aware reconciliation across 5 endpoints.

### Sprint 4 follow-up issues (open items)

- #SP4-shadow-metrics-live-cohort: wire source='live' SQL filter for /api/shadow/metrics when desk='live'.
- #SP4-status-open-positions-cohort: align /api/status._meta.open_positions cohort label with SQL filter.
- #SP4-calmar-debt: migrate 3 hand-rolled Calmar sites (cto_report.py, simulation/engine.py, backtester.py) to canonical helper.
- #SP4-stop-loss-fallback: locate and fix downstream stop_loss display sign-inversion (T4 E2 downgrade).
- #SP4-render-pg-reconcile: extend T16 reconciliation test to Postgres (currently SQLite-only).
- #SP4-kpis-meta-reconciliation-test: regression-lock /api/kpis _meta envelope (T16 substituted stress-test/results due to fixture-isolation).
- #SP4-tanstack-strategyresearch-platformstatus: bare-ref queryFn at StrategyResearch.jsx:41 + PlatformStatusWidget.jsx:13 (pre-existing, surfaced by T22 ESLint investigation).
- #SP3-T12-pnl-card: no dollar P&L primary card in 5-card KPIStrip — design decision to add one or accept the gap.


## [v0.32.0] - 2026-04-29 — Sprint 1.C Phase 1 + Phase 2: attribution discipline + LLM-prompt PIT audit

### Release summary

Sprint 1.C kicked off with operator option C ("wire LLM-scoring into backtester first, then build deterministic-ranker shadow"). Phase 1 closed three measurement-quality bugs in attribution data surfaced by the §4 attribution_readout in PR #845. Phase 2 audited all 11 sections of the LLM prompt assembly path against PIT semantics — the binding finding that gates Phase 4 corpus generation. Pre-reg §3.1 Stage 1 start date may need revision from 2014 to ~2022 due to insider/news Finnhub coverage limits surfaced by the audit.

### Added

- **Attribution canonical action validator** (`src/attribution/logger.py`) — `_CANONICAL_LLM_ACTIONS` frozenset + `ValueError` on non-canonical input. Caller-side bugs surface immediately at write time. (#846 / PR #849)
- **`scripts/diagnostics/attribution_readout.py` band correctness** — bands rescaled from 0-49/50-69/70-84/85+ (modeled on ranker_score 0-100) to 1-3/4-6/7-8/9-10 matching the canonical 1-10 conviction scale. Surfaced 7-8 band as the cleanest signal currently available (avg pnl 1.56% on n=32, not contaminated by conviction=5 parse-failures). (#847 / PR #851)
- **Coverage-drop postmortem** — `audits/attribution-coverage-drop-postmortem-2026-04-29.md`. The audit's "117 H1 vs 3 H2" headline reframed: not a coverage break but a model-version transition (`halcyon-v1.0.0` → `arcis:v1.0.0`) on Apr 13 compounded with parse-failure pollution. (#848 / PR #852)
- **LLM-prompt PIT-cleanliness audit** — `docs/research/llm-prompt-pit-audit.md`. 11 prompt sections traced against PIT semantics. Sections 1-2 clean; 4/5/7/10/11 PIT-broken (HIGH severity); 6 wireable; 3 needs operator policy; 8/9 unclear. Six operator decisions surfaced. (#94 / PR #853)
- **8 PIT follow-up trackers filed** (#854-#861) for the must-fix sections + sub-investigations + sector-PIT-policy doc.
- **#850 follow-up tracker filed** for conviction=5 parse-failure pollution (gates Phase 4 corpus generation).

### Fixed

- **`src/services/scan_service.py:305`** wrote non-canonical `"buy"`/`"skip"` labels for 227 rows (80 + 147) silently excluded from §4 t-test. Canonicalized to mirror `universe_scanner.py:248-253` semantics: `taken` if rec_id+conviction, `conviction_none` if rec_id+no-conviction, `rejected` otherwise. (#846 / PR #849)

### Decisions

- **Sprint 1.C option C locked in** — wire LLM-scoring into backtester first, then build deterministic-ranker shadow. Pre-computed corpus strategy chosen over live-LLM-call.
- **Phase 1d added** — #850 parse-failure flag (option B: schema add, non-destructive) added as Phase 1d after #847 surfaced the parse-failure pollution. In flight at v0.32.0 cut.
- **Pre-reg §3.1 revision likely** — Stage 1 start date may need to advance from 2014 to ~2022 per audit findings (Finnhub coverage limits on Sections 5+6). Phase 3 addendum will lock the final decision.

## [v0.31.0] - 2026-04-28 — Sprint 1.B Wave A/B/C: walk-forward harness + methodology wiring

### Release summary

Sprint 1.B closed the gap between the methodology toolkit shelf (built across PR-690 / Track 1.5) and production wiring. Walk-forward harness, cost-model calibration, FRED-backed risk-free rate, promotion-gate post-train flow, subgroup-analysis harness all wired. Pre-registration document drafted (Stage 1 walk-forward validation discipline). Pre-push hook (#59) closed the stale-base hazard class after 5 incidents in 5 days.

### Added

- **Walk-forward harness** (`src/evaluation/walkforward.py`) — anchored expanding × 8 folds × 21-day embargo. Underpowered-fold flag (<15 trades) excludes from primary aggregate per pre-reg §3.5. (#78 / PR #831)
- **Cost-model calibration wiring** — backtester reads `data/calibration/cost_model.json`; per-trade `median_round_trip_cost_bps` deducted at entry. Falls back to zero cost with warning if absent. (#79 / PR #834)
- **FRED-backed risk-free rate** — `src/data_ingestion/risk_free_rate.py` wired into backtester via per-trade `get_rf_rate()` lookup. Replaces placeholder `rf=0.0001`. (#80 / PR #835)
- **Promotion-gate post-train flow** — `src/methods/promotion_gate.py` wired into training/post-train; ≥4-of-5 voting gate now runs on every promotion candidate. (#49 Sprint 1.B Wave B / PR #836)
- **Subgroup-analysis harness** (`src/evaluation/subgroup_analysis.py`) — pre-reg §6 exploratory subgroups (regime/year/sector/LLM-conviction) with per-partition metrics (trade_count, mean_return, win_rate, Sharpe via canonical raw_sharpe, max_drawdown_pct). 24 tests. (#81 / PR #845)
- **Pre-registration document** (`docs/research/pre-registration-stage1.md`) — binding methodology contract per §5.3 (forbids post-hoc fixes once Stage 1 begins). (#63 / PR #822)
- **Pre-push git hook** (`scripts/hooks/pre-push`) — refuses pushes from branches behind origin/main. Closes stale-base hazard class (5 incidents: #769, #816, #829, #840, #841). Bypass: `git push --no-verify`. (#59 / PR #842)
- **Backtester import smoke test** + **kill_switch test isolation** + **scan_metrics UNIQUE constraint** (#52, #62, #64 — bundled patches).

### Fixed

- **`src/evaluation/backtester.py` silent except** narrowed to `(ConnectionError, TimeoutError)` (#67 / PR #830).
- **`backtester.slice_to_date` import** restored (closes 0-trades mystery, #64 / PR #823).
- **Validator hardcoded snapshot-size cap** replaced with data-driven `max_observed × 1.05` (#65 / PR #837).
- **`diagnostic_runs` stale-job watchdog** at watch-loop startup (#56 / Tier 1.D / PR #840).
- **`docs/methodology-toolkit.md`** conflict markers shipped to main by #835 squash-merge — hotfix (PR #839).

### Decisions

- **Pre-registration § committed**: §1 deterministic-ranker shadow as secondary diagnostic; §3.5 underpowered-fold filter <15 trades; §6 four exploratory subgroups; §8.1 exploratory not pass/fail.
- **Per-trade allocation_pct=0.05** anchors the backtester equity curve; subgroup harness mirrors this for max-drawdown computation.

## [v0.30.0] - 2026-04-28 — Reconcile track + dashboard sprint (Tier 1.A-1.F)

### Release summary

Two parallel tracks closed: (1) Render Postgres delete-replication reconcile track (#68-#74) addressing 623,360 ghost rows accumulated across 25 tables from prior SQLite-archive cycles, and (2) dashboard sprint resolving operator's 2026-04-27 audit Tier 1.A-1.F findings (old-data display, empty registries, API failures + CORS, stuck training audit, "Clear stale" 404, "outcome data pending migration"). One-time manual reconcile (Pass 1 + 2 + 3) executed with operator approval.

### Added

- **Delete-replication reconcile module** (`src/sync/reconcile.py`) — `is_eligible()`, `topo_sort_reconcile_tables()`, `assert_no_ghost_rows()`, `reconcile_all()`. Snapshot-Postgres-first (race-window discipline). (#68-#74 series)
- **`TableDef.sync_reconcile: bool`** registry-driven allowlist (33 tables flagged). Pass 1+2+3 reconciled tables + "Clean (no diff)" eligibles. (#73 / PR #829)
- **Periodic reconcile in `RenderSyncThread`** — `_maybe_run_reconcile()` helper with `reconcile_every_n_cycles=30` default; integrated into `run_sync_cycle` end-of-cycle. (#72 / PR #832)
- **`src/schema/sync_config._topo_sort_tables()`** — Kahn's BFS with cycle detection via `len(result) != len(names)`; dual-source FK lookup (TableDef.foreign_keys or fallback to TABLES registry). (#76 / PR #826)
- **Dashboard cloud routes wired** — kpis, broker_exceptions, preflight orphan route imports added to `src/api/cloud_app.py`. CORS env-var documented. (Tier 1.C / PR #833)
- **Dashboard `/api/commands/expire-stale`** + **COALESCE outcome query** — closes Tier 1.E ("Clear stale" 404) + Tier 1.F (training outcome data pending migration). (PR #827)
- **Dashboard registry imports** in `cloud_app.py` to populate runtime registries on startup. (Tier 1.D / PR #816)

### Fixed

- **One-time manual reconcile** — 623,360 ghost rows deleted across 25 tables in three passes, with per-table verification protocol (BEFORE snapshot → execute → AFTER snapshot → verify Postgres delta == expected, SQLite unchanged, no remaining ghosts). pg_dump backups taken before each pass.
- **FK violation on `council_sessions`** during reconcile resolved by reordering deletes (children first).
- **Group B (~938K rows in `mode=latest_only` tables)** identified and **deferred to #75** for reconcile.py extension.
- **`fix(p0)` connect_db imports** missing across multiple sites (#767, #783 / PR #793).

### Deferred / follow-ups

- **#75** — extend reconcile.py to handle `mode=latest_only` + composite-key delete-replication (Group B cleanup).
- **#85** — split `RenderSyncThread.run()` (60-line cap follow-up).
- **#86** — integration test for periodic reconcile gating.
- **#87** — Cloud Postgres equivalents for broker_exceptions / preflight / kpis (currently SQLite-only via `connect_db()` — won't work on Render cloud).

## [v0.29.0] - 2026-04-27 — Sprint 1.A.x: point-in-time SP100 universe discipline

### Release summary

The single biggest training-data quality lift since v0.27.1. Migrated backtest, simulation, and training-backfill sites from "current S&P 100 membership" to point-in-time-correct historical universe lookups. Wikipedia-sourced JSON membership table with curated corp-action history (Tier A: PCLN→BKNG, KRFT→KHC, UTX+RTN→RTX, EMC removal, YHOO removal). Tier B (CELG, S, FB→META) added immediately after Tier A. T10 survivorship migration enforced by lint test.

### Added

- **`data/reference/sp100_history.json`** — Wikipedia-scraped historical SP100 membership snapshots back to ~2015. Loaded by `src/universe/pit.py::load_sp100_membership_table()`. (Sprint 1.A.0 / PR #802)
- **`src/universe/pit.py`** — canonical PIT lookup module: `get_sp100_at(as_of, membership_table=None)`, `get_data_range()`, `get_all_historical_tickers()`. `UniverseDataMissing` raised for out-of-range or missing JSON. (Sprint 1.A.0 / PR #802)
- **`scripts/build_sp100_history.py`** — regenerates the JSON via Wikipedia scraper + curated changes. (Sprint 1.A.0 / PR #802)
- **T10 survivorship migration** — backtest/sim/training-backfill sites now use `get_sp100_at(<as_of>)`; text-masking sites use `get_all_historical_tickers()`. Live-runtime callers (scheduler/services/cli/api/llm/platform/commands/training-bootstrap) intentionally retain `get_sp100_universe()`. (Sprint 1.A.1 / PR #813)
- **Tier A corp-action handling** — PCLN→BKNG, KRFT→KHC, UTX+RTN→RTX, EMC removal, YHOO removal in `_CURATED_CHANGES`. (#803 / PR #818)
- **Tier B corp-action handling** — CELG, S, FB→META. (#803 follow-up / PR #821)
- **`tests/test_pit_universe_discipline.py`** — allowlist + lint test enforcing T10 migration.
- **Smoke backtest tool** (`scripts/smoke_backtest.py`) — operator-runnable PIT validation.
- **Test baseline** lifted from 3671 → 3682 (T10 regression-locks +11). CI floor bumped in `CLAUDE.md`.

### Fixed

- **Render Postgres compat** — `ARCIS_DB_PATH` made optional when `DATABASE_URL` is set (#768 / PR #782).
- **Schema-verify infinite loop** at watch-loop startup (#766 hotfix).
- **`src/api/cloud_app.py`** missing registry-populating imports (#807 / PR #816).

## [v0.28.0] - 2026-04-26 — Sprint 0 wave-system + 0.B-0.D consolidation

### Release summary

Post-Track-1.5 + post-PR-690 sweep. 14 wave-style PRs (Sprint 0 Wave 1a-5c) closed dashboard cockpit, status-constants, exit vocabulary lifecycle, watch-loop discipline, schema floor, local-auth surface, FRED rf wiring v2, walkforward KPIs SE, Sharpe consolidation, promotion-gate methodology, live-order verification, PIT features. Followed by Sprint 0.B-0.D triage closing ~30 silent-failure / code-hygiene / connect-db / size / method-violation findings from Round-7/7b technical audit. PM-autonomous parallel agent dispatch with worktree isolation discipline (formalized in this release after #690 N3 stash-pop incidents).

### Added

- **14 Sprint 0 Wave-X parallel-dispatch PRs** (#700-#724): frontend cockpit, status constants, shadow-trade lifecycle bugs, DB-stub paths, schema floor, watch-loop discipline, exit-vocabulary lifecycle, local-auth surface, docs+MIME+API-secret, FRED-rf-v2, Sharpe consolidation eval, promotion-gate methodology, live-order verification, PIT features. Each carried strict-rigor receipts; 5/5 stash-pop class incidents documented + recovered via `git fsck --lost-found`.
- **Worktree-per-agent dispatch pattern formalized** — `CLAUDE.md` "Parallel Agent Dispatch — Worktree Discipline" section + recovery patterns + `.env`/untracked-files limitations doc. Closes #699. (PR #734)
- **Sprint 0.B-0.D batches**: silent-failure cleanup (B2.1), code-hygiene (B2.2), connect-db wiring (B2.3 + C.1), size refactors (B2.4 + C.2 alpaca-split), method-violation fixes (B2.5), test-triage (B2.6 + C.3 + D.2), schema-infra (C.6 sync_state in-flight), code-bugs (C.5), process+versioning audit trail (C.4), connect_db hotfixes (#793).
- **`src/version.py`** — single source of truth for app version; `get_app_version()` cleanup. (#660 closure / Sprint 0.C C.4)

### Fixed

- **Render-sync `mode=full` tables** — never strip `id` column (closes #797 / PR #800).
- **PR #690 in-PR review-finding sweep continuation** — additional N3 / O-tier findings landed via the wave system.
- **Coding-skill discipline** — Planner maxTurns 6→12 + stale-base check before PR-create (#53 follow-up / PR #817). Lessons-learned baked into anti-fallacy playbook (#749).

### Decisions

- **`feedback_strict_rigor_no_handwave.md`** — operator stated "rather take a full day than hand wave" (2026-04-26). Encoded as PM memory.
- **`feedback_autopilot_origin_check.md`** — every wakeup: `git fetch origin` + `gh pr list` BEFORE dispatching, to avoid racing operator on parallel work.
- **`feedback_worktree_env_drift.md`** — agent worktrees don't carry `.env`; tests with env-var-driven deps may pass in worktree but break post-merge.

## [v0.27.1] - 2026-04-26 — PR #690 review-finding sweep + Sprint 0 Wave 1a kickoff

### Release summary

PR #690 (Track 1.5 instrumentation) merged with 27 review findings landed as in-PR fixes (5 Blockers + 8 Important + 14 Observations). Sprint 0 Wave 1a kicked off post-merge to clear the dashboard cockpit issues that survived the PR-690 sweep — F-AUTH (Rules of Hooks compliance) + F-CHANGELOG (this entry; WhatsNewPanel was still advertising v0.25.0 as latest).

### Fixed

- **F-CHANGELOG (Sprint 0 Wave 1a / PR #690 review B3):** `frontend/src/components/system/WhatsNewPanel.jsx` was still listing v0.25.0 (2026-04-18) as the most recent entry, missing the entire Track 1.5 + Round 10 + PR #690 review-sweep work. RECENT_ENTRIES refreshed to mirror the canonical CHANGELOG (this file). Regression test added: `frontend/src/components/system/WhatsNewPanel.test.jsx` asserts the top entry is current and that the rendered date reflects the latest release. `src/version.py` bumped from v0.27.0 → v0.27.1.

- **PR #690 in-PR review-finding sweep** (full list in PR #690 commit history, summarized):
  - **B1–B5 Blockers:** exit_reconciliation direction-aware semantics + named tolerance constant (O2/O3); analytics monitor route raises 500 instead of silent empty array (O8); replaced `setdefault(key, dict.get(key))` no-op with explicit assignment (O10); publicized `compute_timeout_status` + `shadow_trades.quarantined NOT NULL` migration + integration negative-path tests (O4/O7/O9); 3 services routed `[BROKER_EXCEPTION]` → `log_and_persist` (O1-redo).
  - **I1–I8 Important:** wired FRED DTB3 rf adapter into kpis + stage1 baseline (I1); promotion-gate exception logging + distinct caption (I2); Lo (2002) autocorrelation-corrected Sharpe SE (I3); split `n_spy` and `n_total` in KPI response (I4); regenerated sprint_F engine fixtures + dropped `--ignore` (I5); labeled TradeHistory rolling Sharpe as diagnostic + used Alpaca equity for projections drawdown baseline (O11/I6); Round-8.F backtick template-literal stripping anti-regression test (I7); KPI threshold pinning (I8) with decision-matrix thresholds aligned to audit-spec §3.1 (B3-A).
  - **O1–O14 Observations:** packet_writer Key Risk regex semantics + truncation marker budget (O13); _find_latest_transcript sorts by mtime not lexicographic (O6); replaced projections.py non-canonical Sharpe with `canonical_sharpe.raw_sharpe` (B5); MR_VIX_LOOKUP_FAILED warning instead of bare pass on VIX swallow (O5); route-parity value-validation tests for kpis + projections (O14); 7 test failures from post-rewrite sweep resolved.

### Decisions

- **Decision 6 — KPI traffic-light thresholds anchored to audit-spec §3.1.** Pinning tests added in `tests/api/test_kpis.py` so Stage-1/Stage-2 boundaries cannot drift silently. Rationale + thresholds documented in PR #690 B3-A commit.

## [v0.27.0] - 2026-04-25 — Track 1.5 instrumentation gap closure (post-audit, PM-autonomous dispatch)

### Release summary

Post-audit instrumentation-gap-closure track dispatched autonomously by the PM after the 2026-04-27 Trading-Readiness Audit (v0.26.0 / v0.27.0) completed. 14 rounds + 4 plugin/infra fixes across ~16 commits. All Critical + Important findings from both audit passes cleared. ~250 new tests added.

Full design decisions, hard truths, and deferred items: [`docs/audits/2026-04-27-trading-readiness/track-1.5-DECISIONS.md`](docs/audits/2026-04-27-trading-readiness/track-1.5-DECISIONS.md)

### Added

- **Track 1.5 instrumentation deliverables (B1–B9):**
  - B1: `signal_exit_price` + `exit_slippage_bps` persisted at close (`executor.py` update path)
  - B2.A: `broker_exceptions` schema table + 4 silent-swallow upgraded to writes
  - B2.B: Structured logging for 15 broker partial-swallow sites in `executor.py`
  - B2.C: Bounded retry + qty-mismatch detection (CVS regression closure)
  - B3: `exit_reason` canonical taxonomy + nightly reconciliation script
  - B4 + B8: `key_risk_assessment` + LLM-set `expected_holding_period_days` persisted at open
  - B5 + B8: Schema + executor open-path stamping for `instrumentation_version` INTEGER sentinel + `timeout_days`; `INSTRUMENTATION_VERSION_CURRENT = 3` constant; `filter_to_version` helper (`src/analytics/instrumentation.py`)
  - B6: End-to-end integration test for full instrumentation pipeline
  - B9: `llm_timeout_days` surfaced in dashboard trade ledgers

- **5-KPI hero strip** (`frontend/src/components/dashboard/KPIStrip.jsx` + `src/api/cloud_routes/kpis.py`): rf-adjusted excess Sharpe, SPY-relative Sharpe + p-value + CI, win rate, Stage-1/2 traffic light, promotion-gate vote count. Replaces Dashboard hero MetricCards.

- **`broker_exceptions` panel** (`frontend/src/components/dashboard/BrokerExceptionsPanel.jsx` + `/api/broker-exceptions` endpoint): live-trade observability for all broker partial-swallows and exception writes. Critical gap from Round 7b G1 finding.

- **Preflight gate UI echo** (Round 8 / S4): `scripts/preflight_monday.py` output now written back to Dashboard via a preflight result card. Prior state: output written to disk only, never read back.

- **Vitest infra** (`frontend/src/` test harness) + `arcis-pulse` keyframe animation (B9 cleanup).

- **`docs/instrumentation_versions.md`** (NEW): v0/v1/v2/v3 version-to-feature matrix per B5 design. Rationale for the INTEGER sentinel, analytics filter rules, cross-references to B5 design doc + executor stamping point + `filter_to_version` helper.

- **3 new sprints queued** (post-Track-1.5): (1) v0.26.3 `sections_json` widening, (2) System Index visibility audit, (3) Council impact analysis. Cohort 3 strategy redesign (T2.14b/T2.14c/T2.16b) also queued as Sprint 4.

### Changed

- **Dashboard hero replaced with canonical KPIStrip** (R1 resolved): three incompatible Sharpe formulas across four surfaces collapsed to a single canonical strip. Dashboard hero and CTOReport previously used uncanonical `mean/stdev`; only TradeHistory attribution panel used T1.03. Now the strip is the single source of truth.

- **Win-rate silent fallback removed** (R2 fixed): `Dashboard.jsx:469` previously fell back to Alpaca account API value when `shadow_service` returned null — different denominator, no quarantine filter, misleading number. Fallback removed; null → `"—"` displayed.

- **P&L source labels added** (R3 fixed): Shadow Equity and cumulative P&L chart now carry explicit source annotations so operator can see when values come from different count bases.

### Fixed

- **5 Critical findings from Round 7 technical audit** (Round 8.A):
  - C1 Monitoring history shape mismatch — backend `{snapshots: [...]}` vs frontend array expectation
  - C2/C3/C4 Local-route parity — `/ib-shadow/*`, `/strategy-detail/{type}`, `/system/index` mirrored to local FastAPI
  - C5 `RevenueProjection` live route added

- **3 deferred audit items closed in Round 8.F** (cosmetic + Important-tier findings): SPY data source label, double-prefix bug, and remaining Important catch-all items from Round 7 + 7b.

### Decisions

- **Fix-everything-technically-before-trading principle** adopted as SD#46 (2026-04-25). Supersedes Mon $100 deploy from SD#41 REVISED until Cohort 3 redesign produces a strategy with positive expected alpha. Full reasoning in `track-1.5-DECISIONS.md` Decision 1. Memory artifact: `feedback_fix_before_trade.md`.

- **5-KPI strip layout approved** with documented color rules per §3.1 Decision Matrix thresholds.

- **Mon $100 live deploy DEFERRED** until post-Cohort-3 strategy redesign. Mon AM preflight still runs as system-health check, not deploy gate. Next deploy decision happens after Cohort 3 redesign (T2.14b/T2.14c/T2.16b) produces a strategy with reason to believe in its alpha signal.

Full reasoning for all decisions: [`docs/audits/2026-04-27-trading-readiness/track-1.5-DECISIONS.md`](docs/audits/2026-04-27-trading-readiness/track-1.5-DECISIONS.md)

## [v0.26.0] - 2026-04-23 — v0.26.0 chain complete + triage bundle + overshoot root cause

### Release summary

Tag cut pre-Friday bootcamp archive (SD#42) to anchor code state for the DB cutover. Scope since v0.25.0 is too large for a patch release — this is a minor bump.

**Trading safety (critical):**
- Exit-overshoot cancel-race fix (#608/#609/#610, PR #636): `_handle_pre_exit_cancel` routes to `_close_from_broker_fill` when cancel races a fill instead of submitting another SELL. Addresses C 4/21 + AMD 4/22 root cause that survived #595.
- CVS retry loop + phantom exits (PR #595): D2 reconcile 3rd branch + D3 executor qty sync + _strip_enum enum.value normalization.
- Council fail-closed (#612, PR #636): ClaudeAuthError + CouncilUnavailableError replace silent fake 5-0 consensus from failed stubs.

**Training data:**
- Silent-failure detection (#615, PR #636): CollectionResult dataclass + Telegram alert when is_silent_failure=True. Closes 11-day blind-spot pattern 4/13-4/23.
- Missing recommendation fallback (PR #606): LEFT JOIN + COALESCE + _build_feature_input_from_trade fallback builder + skip-instead-of-degenerate-example guard.

**v0.26.0 chain (closes #530):**
- Sprint F (PR #585): spec-driven ranker + features/enrichment port with 20 byte-identity fixtures
- Sprint G/H (commit 413fd39): spec-driven packet builder + scan plumbing

**Triage bundle (PR #636 — 29 issues closed across 4 tiers):**
- Tier 3 dep-health 13-pack: #527, #544-546, #572, #587-590, #599-601, #605, #608-610, #612, #615, #616, #630
- Tier 1 observability: #613, #614, #618, #623
- Tier 2 safety one-liners: #438, #440
- Tier 4 scoped feature work: #576, #598, #622, #624

**Dashboard (PR #637, #638):**
- src/version.py single source of truth (#631-15)
- Trade open/close websocket refresh events
- 10 other UX polish items from #631


### Fixed (Sprint fix/paper-exit-qty-asymmetry — CVS retry loop + phantom exits)

Closes #591 (D2 reconcile 3rd branch) and #592 (D3 paper exit qty sync).

Three interlocking bugs surfaced by the 2026-04-21 investigation
(`docs/audit/root_cause_investigation_2026-04-21.md`) collapsed into a
single root cause: `_strip_enum` at `src/shadow_trading/alpaca_adapter.py:38`
returned UPPERCASE names instead of lowercase values from alpaca-py's
regular-Enum `OrderStatus`. Downstream executor checks at
`executor.py:1375` and `:1383` compare against lowercase sets and
silently missed every filled bracket leg. Fallback stop/target/timeout
path then dispatched `_submit_exit_order(planned_shares)` against a
position already closed server-side → phantom sell-to-open → overshoot.

CVS on 2026-04-21 added a second failure mode: a partial fill left
4 residual shares against `planned_shares=130`. Reconcile's stuck-trade
resolution only had two branches (qty<=0 or qty>0); missing branch for
`0 < qty < planned` reverted to `open` every cycle → 17+ failed sell
attempts before operator manual quarantine.

- **D2 fix (`src/shadow_trading/reconcile.py:655-700`):** added the
  `0 < alpaca_qty < planned_shares` branch. Marks
  `status='needs_manual_review'`, `exit_reason='qty_mismatch_partial_fill'`.
  Distinct reason separates qty-mismatch residuals from directional
  overshoots for cleanup tooling.
- **D3 fix (`src/shadow_trading/executor.py`):** new helper
  `_sync_exit_qty(ticker, requested_shares, broker_positions)` reuses
  the `get_all_positions` result already fetched at `:1174` (now a
  `dict[str, float]` keyed by ticker) to clip or skip exits against
  actual broker qty. Threads `broker_positions` through `_retry_exit`.
  Phantom exits (`broker_qty <= 0`) are marked `exit_pending` with
  `position_already_closed` for reconcile to finalize — no sell ever
  submitted against a closed position.
- **Upstream fix (`src/shadow_trading/alpaca_adapter.py:38-70`):**
  `_strip_enum` now returns `val.value` for `enum.Enum` instances.
  Callsite audit documented in commit 6 message — no other callers
  needed changes beyond the existing `.lower()` patterns they already
  applied (`bracket_monitor.py:75`, `_is_filled_status`, `_is_pending_status`).
- **9 new tests + 3 test updates** covering partial-fill mismatch,
  phantom-exit prevention, race with reconcile, `_strip_enum`
  normalization, and bracket leg-fill detection case-insensitivity.
  Three existing tests (`test_retry_exit_called_for_exit_failed`,
  `test_bad_timestamp_forces_timeout`, `test_exception_marks_exit_failed_not_open`)
  updated to mock broker positions so they exercise their intended paths
  rather than hitting D3's new skip branch.
- **`scripts/cleanup_overshoot_zombies_2026_04_21.py`** for operator to
  run post-deploy to close the 13 accumulated zombies (dry-run default;
  `--apply` required; idempotent; read-only Alpaca calls).

Sprint artifacts:
- Pass 1 evaluation: `docs/sprints/fix_paper_exit_qty_asymmetry_evaluation.md`
- Pass 2 research: `docs/sprints/fix_paper_exit_qty_asymmetry_research.md`

Pre-existing failures on main, NOT introduced or fixed by this sprint:
2 Sprint F byte-identity tests; `ranker.py` > 400 lines (not in
`config/known_violations.json`).

### Added (Cleanup Sprint 3 — 4 strategic-sprint spec drafts)

Four draftable-tonight specs surfaced by the 2026-04-20 audit's
"Strategic" items 1–4, landed in `docs/sprints/future/`. Zero code
changes; future-CC can Ralph-Loop each spec into its own sprint.

- **`docs/sprints/future/eval_harness_spec.md`** — wire the existing
  canary / A/B / quality-drift / leakage-detector infrastructure into
  a nightly harness that gates model promotions (300-prompt canary,
  6-dim rubric judge, composite gate, `eval_results` table). 2–3
  sprints to deliver; dependencies none.
- **`docs/sprints/future/second_strategy_evaluation_spec.md`** —
  pivoted from the prompt's 4-candidate selection to "implement the
  already-selected Strategy 2 (mean reversion) and Strategy 3
  (evolved PEAD)" because existing decision docs
  (`Strategy_2_Selection__Mean_Reversion_Wins.md`, ADR-002) already
  made the selection. Track A: Strategy 2 implementation audit.
  Track B: Strategy 3 ground-up build (4-way PEAD composite).
- **`docs/sprints/future/training_curriculum_gate_spec.md`** —
  10-criteria pre-training gate blocking training runs with
  unbalanced outcome mix (40/25/5/15) or ratio drift from the 62/38
  curated/generated target. Chains with the eval harness spec
  (post-training gate) without circular dependency. 1–2 sprints.
- **`docs/sprints/future/containerization_spec.md`** — move training
  subsystem to WSL2 (alone first, Docker later) to eliminate cp1252
  issues that cost three subsystems tonight. Watch loop stays
  Windows-native per NSSM integration. 1–2 sprints.

Pass-1 evaluation + Pass-2 research docs in
`docs/sprints/cleanup_sprint_3_evaluation.md` and
`cleanup_sprint_3_research.md` record the scope pivots for Spec 1
(infra exists, not greenfield) and Spec 2 (decisions already made).

---

### Added (Cleanup Sprint 2 — Track A DB reconciliation script)

`scripts/reconcile_2026_04_20.py` — one-shot DB reconciliation for the
19 broken-state shadow_trades rows + 1 stale model_versions row
surfaced by the 2026-04-20 live-state analysis. Author-only in this
PR; the operator runs it after Alpaca fills confirm zero-short state.

- 12 trades (9 CLOSE_AT_OPEN incl GS + 3 NEEDS_OPERATOR_JUDGMENT) →
  `status='closed'`, `exit_reason='manual_reconcile'`.
- 7 trades (4 stale exit_failed + 3 open-row phantoms) →
  `status='exit_abandoned'`, `exit_reason='phantom_row_cleanup'`.
- TGT #12 broker-tag corrected `ib → alpaca` (position was on Alpaca).
- `model_versions.arcis:v1.0.0` → `status='active'` after three-way
  reconciliation (Ollama + config agree it is operational).

Safeguards: kill-switch pre-flight (exit 2), Alpaca pre-flight for
zero shorts (exit 3), single atomic transaction, post-update count
verification with rollback (exit 4), idempotent re-runs skip resolved
rows. Structured audit log appended to
`docs/audit/reconcile_2026_04_20_execution.log`. 5 regression tests
(`tests/scripts/test_reconcile_2026_04_20.py`).

### Changed (Cleanup Sprint 2 — `bootcamp.max_packets_per_scan` 20 → 8)

`config/settings.local.yaml:103` (gitignored — operator-local value).
Post-reconciliation BP (~$100-200K) comfortably fits 8 × ~$15.5K = $124K.
20-cap produced 11 BP-rejections 2026-04-20 because 20 × $15.5K =
$310K exceeded the $6,982 BP. Matches `settings.example.yaml:455`
default. **Operator must manually verify their local
`config/settings.local.yaml` contains `max_packets_per_scan: 8`** —
gitignored file cannot be committed.

### Fixed (Cleanup Sprint 2 — 7 medium-risk code fixes: L, K, C2-partial, H4, H5, H7, L5)

Seven independent code fixes from the 2026-04-20 post-market audit.
Kill-switch engaged throughout; no order submissions, no live-state
mutations. See `docs/sprints/cleanup_sprint_2_evaluation.md` (Pass-1)
and `cleanup_sprint_2_research.md` (Pass-2) for per-item rationale.

- **L — `_scan_cycle_committed` reset on every scan entry.**
  The module-level BP-committed counter persisted across scan cycles
  because `reset_scan_cycle_committed()` was called only from
  `src/services/scan_service.py:37`. The production watch path
  (`src/scheduler/universe_scanner.py`) and the MR path
  (`src/services/mr_scan_service.py`) skipped the reset, producing
  `committed $37,942` persistence across 11 scans today. Fix: add
  `reset_scan_cycle_committed()` at the top of both scan entries.
  4 regression tests including a static guard that fails CI if any
  scan-entry module loses the reset call.
- **K — pre-LLM BP check in scan entry paths.**
  New helpers `_check_paper_buying_power_allocation(allocation)` and
  `_record_bp_rejection_pre_llm(packet)` in executor.py. Wired at
  `universe_scanner.py:202`, `scan_service.py:169`, and
  `mr_scan_service.py:117` — before `enhance_packet_with_llm`. Saves
  ~17s of Ollama compute per un-fundable ticker (11 AVGO retries
  today = ~3 min wasted). Fail-closed on account-fetch errors. Does
  not increment `_scan_cycle_committed` (authoritative gate stays at
  `executor.py:598`). 7 regression tests.
- **C2-partial — cancel dangling orders before orphan backfill.**
  `reconcile.py:498` orphan-backfill loop now calls
  `cancel_orders_for_ticker` before `insert_shadow_trade`, matching
  the existing stale-close path at `:546` (fix #356). Prevents
  stale bracket legs from firing a duplicate sell after backfill
  (the exit-overshoot pattern behind today's 12 shorts). 2
  regression tests.
- **H4 — governor-disabled critical alert.**
  `risk/governor.py` — when `enabled=False`, `check_trade` now fires
  one `logger.critical` + one Telegram alert per process lifetime
  (module-level sentinel prevents per-check spam). Alert message
  names the config key to edit (`risk_governor.enabled`). Prevents a
  silent governance bypass from a config flip. 5 regression tests.
- **H5 — traffic-light credit classifier `int+str` TypeError.**
  `macro_snapshots.value` is stored as SQLite TEXT (SQLite type
  affinity allows str INSERTs into REAL columns). `sum(values)` of
  str raised `TypeError` (26 warnings today, silently disabling the
  credit-spread regime input). Fix: parse each value via `float()`
  with try/except skip; require 20 parseable values post-filter.
  5 regression tests.
- **H7 — bare `sqlite3.connect()` → `connect_db()` in reconcile.py.**
  7 call sites swapped. Promotes `busy_timeout` from the 5-second
  default to the canonical 30 seconds and adds `row_factory=Row`.
  Matches CLAUDE.md rule for all SQLite connections. connect_db does
  **not** apply `PRAGMA foreign_keys` or WAL (Pass-2 research
  correction) — FK enforcement remains a separate follow-up. 4
  regression tests including an integration test that a second
  writer waits rather than failing immediately.
- **L5 — EOD report format-string `Unknown format code 'f'` crash.**
  `reports.py:399-407` now casts `pnl_dollars` and `pnl_pct` to
  `float()` before passing into `notify_eod_report`'s `{:+.2f}`
  f-strings. Fixes the 4 EOD failures observed on 04-14/04-15/04-16/04-17.
  3 regression tests. Upstream writer storing TEXT remains a separate
  data-layer bug.

### Deferred to dedicated sprints

- **H8** — `activity_log.id` needs `PRIMARY KEY AUTOINCREMENT` —
  schema migration tracked in issue #580.
- **AAPL 24-day stop=0/target=0** — backfill-default root cause
  investigation tracked in issue #581.
- **Model registry archaeology** — `arcis:v1.0.0` rollback audit
  tracked in issue #582.

---

### Fixed (Cleanup Sprint 1 — critical-path code fixes: C3, H6, H3.b)

Three independent zero-live-state fixes surfaced by the 2026-04-20 log
audit (see `docs/sprints/cleanup_sprint_1_evaluation.md` and
`cleanup_sprint_1_research.md`). Kill-switch stayed engaged throughout;
no trading-path, governor, or model-registry changes.

- **C3 — reconcile dispatch `db_path=None` TypeError.**
  `src/scheduler/watch.py:694` calls `reconcile_all_paper_trades()` with
  no `db_path` kwarg; the `None` default propagated through
  `get_strategies_by_status` to `sqlite3.connect(None)` and raised
  TypeError. Intra-day reconciliation failed 13× today and has been
  silently failing every 30-min scan cycle. Added None-guards at both
  call sites (`src/shadow_trading/reconcile_dispatch.py`,
  `src/platform/promotion.py:489`) that resolve `None` to the config
  `DB_PATH`. 5 regression tests in
  `tests/shadow_trading/test_reconcile_dispatch_db_path.py`.
- **H6 — cp1252 Unicode crash in overnight reconciliation log.**
  Windows StreamHandler could not encode `❌` (U+274C) when emitted via
  `logger.info("[WATCH] %s", msg)` on line 67 (source on line 65);
  10 logger crashes today. Replaced `❌`/`✅`/`—` in logger/print/msg
  paths with `[FAIL]`/`[OK]`/`--`. Preserved emojis in Telegram-only
  paths (Telegram renders UTF-8 natively). Preserved em dashes in
  docstrings and comments (never reach an emittable stream). 5
  regression tests in `tests/scheduler/test_overnight_encoding.py`
  including a cp1252 round-trip and a static scan that fails if any
  logger/print/msg line contains cp1252-incompatible bytes.
- **H3.b — `trl` version pin.** Pinned `trl>=0.12,<0.25` in
  `requirements-training.txt`. Unbounded upper resolved to trl 1.1.0
  which ships `chat_templates/gptoss.jinja` read via `Path.read_text()`
  without an explicit encoding; on Windows that raised
  UnicodeDecodeError, killing `SFTTrainer` import and silently breaking
  overnight fine-tune for approximately one week. Pin is compatible
  with co-pinned `transformers>=4.46` and `accelerate>=1.0`.

Operator follow-up (not in sprint scope):
- Add `PYTHONUTF8=1` to the watch-loop NSSM service environment.
- `pip install -r requirements-training.txt` on the training host to
  downgrade `trl` to the 0.12–0.24 window.
- Investigate what caused remote `main` to be fast-forwarded to this
  sprint's tip without a PR (see `audit/2026-04-21` branch for the
  automated audit commit preserved from the incident).

---

### Added (2024 OHLCV backfill for Sprint F byte-identity fuzz)

Closes #570. Unblocks Sprint F (#564) byte-identity fuzz. Populates
`data/simulation_cache/` with 2023-01-01..2024-12-31 daily OHLCV for
the S&P 100 universe + SPY + ^VIX = **104 tickers, 501 trading days
each**. All 11 Sprint F fuzz/primary dates (2024-01-16 through
2024-11-19, primary 2024-03-26) have exact-match data.

**Date range is 24 months, not calendar-year 2024**, because
`compute_features` requires SMA200 (200 trading days) and RS-6m
(126 trading days) of lookback before the earliest fuzz date. A
calendar-year-2024 fetch would have broken feature computation on
the first 7 of 11 fuzz dates — confusing `SMA200 NaN` failures
attributable to data setup rather than the port. The extra 6 months
of 2023 data costs ~2 MB and ~1 minute of runtime.

**SPY is included** (not just "S&P 100 universe + ^VIX"): `rank_universe`
uses SPY for `_classify_relative_strength` (the 1m/3m/6m RS calculations
that feed `relative_strength_state`). SPY is a functional prerequisite
for the scan pipeline, not universe expansion. `^VIX` is required by
`compute_market_regime` for the `vix_proxy` volatility classification.

**New script:** `scripts/backfill_2024_ohlcv.py` (throwaway; kept
committed for re-runnability). Reuses `src/simulation/cache.py::fetch_cached_ohlcv`
— no new fetch abstractions (prompt anti-goal). Per-call parquet save
(crash-safe), cache-hit skip on re-run (idempotent).

**Results:**
- 104 of 104 tickers succeeded (0 failures)
- Runtime 83.1 seconds (under the 3-minute Pass 1 estimate)
- 4 Pass-1-flagged tickers (PYPL, F, GM, KHC) all fetched cleanly —
  none are delisted; S&P 100 membership-staleness remains an open
  observation but no new issue filed per operator direction (only
  file if >1 actually fails, which they didn't)
- 8 pre-existing scenario-partial parquets (different cache keys)
  preserved untouched as designed
- BRK.B → `BRK_B_...` filename translation verified via
  `to_yfinance_ticker()`; hyphen/dot handling clean

**Re-run:** `python scripts/backfill_2024_ohlcv.py` is idempotent —
skips cached files, re-fetches only missing ones. If any parquet is
known-bad, delete it before re-running.

---

### Fixed (Sprint C.1 — schema refinement: scoring shape gaps)

Closes #569, #567, #568 — slot 6-a in the #530 Sprint chain (chain count
revised 8→9; F/G/H shift to slots 7/8/9). Sprint F Pass 1 (see
`docs/sprints/sprint_F_evaluation.md` on `feat/port-ranker-to-spec`,
parked at `53dee07`) surfaced 9 schema shape gaps blocking byte-identity
port of the ranker; Sprint C.1 closes them before Sprint F resumes.

**9 items:**

1. **Categorical bands** — `ranking.bands` accepts `category: <str>` as
   an alternative to `range: [lo, hi]`. Mutual exclusion. Covers
   `trend_state` / `relative_strength_state` in `_score_ticker`.
2. **Compound AND conditions** — band entries may use `conditions:
   [{metric, operator, threshold}, ...]` instead of a top-level metric.
   Covers `iv_rank > 75 AND pc_vol > 1.2`. Operator enum
   `{>, >=, <, <=, ==, !=}`.
3. **Weighted blend groups** — bands accept optional `weight: float
   [0,1]` + `blend_group: <str>` for weighted sums across tagged bands.
   Covers the 0.6/0.4 market-vs-sector RS blend. Weights within a group
   should sum to 1.0 (warn if not).
4. **`ranking.adjustments` block** — new block with same grammar as
   `ranking.bands` plus `clamp: [lo, hi]`. Covers `_regime_adjustment`
   (ranker.py:72-102).
5. **`ranking.derived_metrics` block** — declarative feature derivations.
   Ops: `subtract`, `weighted_sum`. DAG cycle check. Covers
   `_compute_sector_rs` (ranker.py:105-147).
6. **#567 — `packet_worthy` → `min_score` hard-rename.** Schema validator
   previously asserted bool; runtime stored int threshold. Field is now
   `min_score: int` in `[0, 100]`. No legacy alias.
7. **#568 — `KNOWN_POST_SCAN_HELPERS` contents + strict flip.** Set
   aligned to runtime dispatch names `{traffic_light, event_risk}`;
   `post_scan.chain` flipped to `strict=True`.
8. **`KNOWN_SCORING_METRICS` registry.** 10-metric seed for
   `_validate_bands` / `_validate_band_condition`. Effective set at
   validation = seed ∪ derived-metric names from Item 5.
9. **Event-risk casing docstring (Item 9).** Schema comment codifies the
   lowercase_with_underscores convention. No runtime edits — Option 9A
   per operator resolution 2026-04-20.

**Registry additions:**

- `KNOWN_REGIME_LABELS` — 5-label set from `compute_market_regime()`
  (regime.py:161-170). Intentionally separate from `KNOWN_REGIME_KEYS`
  (7-label, threshold dispatch). Documented with comment explaining
  the split.
- `KNOWN_SCORING_METRICS` — 10-metric seed from `_score_ticker` +
  `_regime_adjustment`. Additions require a refinement sprint
  (C.1-style) — silent edits risk schema/runtime scoring drift.
- `ALLOWED_BAND_OPERATORS`, `ALLOWED_DERIVED_OPS` — operator enums.

**Structure:**

- Ranking validators extracted to `src/platform/_strategy_spec_ranking.py`
  (341 LOC) to keep `strategy_spec.py` focused and under guardrail. Main
  module re-exports the constants for public API stability.
- `strategy_spec.py`: 393 → 388 lines (under 650 guardrail).
- `tests/platform/specs/test_schema_c1_refinements.py`: 28 tests covering
  all 9 items + backward compat + registry seeds.

**Known Sprint F divergence (operator resolution 2026-04-20):** the
sector_rs None-fallback in `_score_ticker:182-187` (market gets weight
1.0 when sector data absent) is NOT expressible in pure weighted-blend
schema. Sprint F will observe byte-identity fuzz failure → STOP → file
issue for a follow-on sprint (C.2-style) if the fallback matters.

**Follow-up candidates for Sprint F or C.2:** symmetric categorical-value
validation for non-regime metrics (`trend_state`, `relative_strength_state`,
`market_breadth_label`) — each ~10 LOC. Deferred because immediate scope
is `regime_label` per operator. Sprint F may surface additional gaps
that get bundled.

**Sprint F unblocks:** once #569 merges AND #570 (2024 OHLCV data gap)
resolves, `feat/port-ranker-to-spec` (parked at `53dee07`) resumes as
Sprint F at slot 7 of 9.

---

### Added (Sprint E — hooks, enrichment, post-scan, event-risk, bootcamp schema)

Closes #551 — fifth of 8 prerequisite sprints in the #530 Sprint chain
(Sprints A #494, B #493, C #549, D #550 merged earlier). **Sprint E
completes the v0.26.0 schema surface**; the next two sprints (F, G) port
the runtime (`compute_all_features`, `rank_universe`, bracket engine) to
consume the declared spec instead of hardcoded logic.

`src/platform/strategy_spec.py::validate_spec` now validates five
additive optional top-level blocks:

```yaml
hooks:                           # attribution logger refs (strict)
  attribution:
    - log_before_llm
    - log_after_llm

enrichment:                      # ordered enricher chain (warn)
  chain:
    - technicals
    - insider
    - macro
    - news
    - sector

post_scan:                       # ordered post-ranking helpers (warn)
  chain:
    - classifier
    - filter_duplicates

event_risk:                      # category-based quarantine gate (warn)
  quarantine_categories:
    - earnings_imminent
    - fomc

bootcamp:                        # strategy-level bootcamp overrides (strict)
  qualification_threshold: 55
  watchlist_threshold: 30
  max_positions: 20
  traffic_light_floor: 0.5
```

Per-block policy — strict-vs-warn chosen by registry maturity
(documented in `docs/sprints/schema_final_blocks_evaluation.md §2`):

| Block | Policy | Registry source | Reason |
|-------|--------|-----------------|--------|
| `hooks.attribution` | **strict** | `src/attribution/logger.py` (2 stable functions) | Typo silently disables attribution — 2-year-old code, capability-registry-registered. |
| `enrichment.chain` | warn | no formal registry yet | Sprint prompt names aspirational; Sprint F wires the registry. |
| `post_scan.chain` | warn | no registry exists | Same; runtime binding deferred. |
| `event_risk.quarantine_categories` | warn | fragmented (`MACRO_EVENT_TYPES` + `KNOWN_EVENTS` labels) | 20-seed-entry union of current category sources; sprint-prompt earnings names aren't in code yet. |
| `bootcamp` | **strict** | `config/settings.example.yaml:435-457` | 4 keys load-bearing at 7 runtime sites; typo silently reverts to hardcoded default. |

Validation rules (strict blocks):

- **`hooks.attribution`** — list of string refs; each must be in
  `KNOWN_ATTRIBUTION_HOOKS = {log_before_llm, log_after_llm}`.
- **`bootcamp`** — dict; allowed keys are
  `{qualification_threshold, watchlist_threshold, max_positions,
  traffic_light_floor}`. Per-key type check: thresholds are int in
  `[0, 100]`, `max_positions` is a positive int (bool excluded),
  `traffic_light_floor` is a number in `[0.0, 1.0]`.

Validation rules (warn blocks): unknown refs emit
`logger.warning("[PLATFORM] %s[%d]: unknown ref %r (known: ...)")` but
do not block the spec load. Matches the Sprint C/D precedent
(ranking.bands overlap, regime-key unknowns).

Added constants and helpers in `strategy_spec.py`:

- `KNOWN_ATTRIBUTION_HOOKS`, `KNOWN_ENRICHERS`,
  `KNOWN_POST_SCAN_HELPERS`, `KNOWN_EVENT_RISK_CATEGORIES` (20 entries),
  `KNOWN_BOOTCAMP_KEYS` (all module-level frozensets).
- `_LIST_BLOCKS` dispatch tuple — single loop handles the 4
  list-of-refs blocks (hooks, enrichment, post_scan, event_risk).
- `_validate_known_ref_list(items, known, path, errors, *, strict)` —
  shared helper factoring the common shape out of four dispatch sites.
- `_validate_bootcamp_overrides(block, errors)` + `_BOOTCAMP_RULES`
  table-driven per-key type checks.

Guardrails:

- **Schema-only.** `StrategySpec` dataclass unchanged; new blocks land
  in `.raw`. Downstream consumers pick them up from `.raw` without
  modification. Reproducibility hash at `backtest_engine.py:187`
  captures the new blocks (intentional; same precedent as Sprint C/D).
- **Zero top-level key collision.** `{hooks, enrichment, post_scan,
  event_risk, bootcamp}` appear in neither `lazy_prices_v1.yaml` nor
  `post_audit_ruleset_v1.yaml`; existing `attribution` top-level key
  is in a separate namespace from `hooks.attribution`.
- **File-size budget preserved.** `strategy_spec.py` grew from 298 to
  393 lines — under the 400-line cap set by the sprint prompt.

Tests — `tests/platform/specs/test_schema_final_blocks.py` (25 tests):

- 2 tests per block × 5 blocks = 10 (prompt minimum).
- +5 combined / backward-compat (all-5-simultaneously, lazy_prices_v1,
  post_audit_ruleset_v1, none-declared, non-dict outer ignored).
- +5 edge cases (empty list, not-a-list, non-string entry, bootcamp
  not-a-dict, all-outer-dicts-empty).
- +5 bootcamp-specific (threshold range, bool-is-int trap, floor
  range, floor valid, watchlist valid).

Platform test count: 447 → 470 (23 new + 2 new skipped = 25 additive).

Documentation:

- `docs/sprints/schema_final_blocks_evaluation.md` — Pass 1 per-block
  registry-source discovery, strict-vs-warn decision matrix, test plan.
- `docs/sprints/schema_final_blocks_research.md` — Pass 2 verification
  of the 7 Pass-1 assumptions (attribution module location, bootcamp
  consumers, top-level key collisions, spec.raw consumers, event-risk
  seed byte-match, file-size budget, test count floor).

Next: Sprint F (ranker port — `compute_all_features` + `rank_universe`
consume spec instead of hardcoded logic).

### Added (Sprint D — multi-target brackets + regime-adaptive sizing schema)

Closes #550 — fourth of 8 prerequisite sprints in the #530 Sprint chain
(Sprints A #494, B #493, C #549 merged earlier).

`src/platform/strategy_spec.py::validate_spec` now validates two additive
schema blocks — a list-form `exit.targets[]` alternative to the legacy
singular `exit.target`, and a `position_sizing.method: regime_adaptive`
option alongside the existing `fixed_pct_equity`.

Accepted shapes:

```yaml
exit:
  kind: mechanical
  timeout_days: 21
  stop:
    atr_multiple: 2.0                # required when using targets[]
  targets:                           # list-form; alternative to exit.target
    - name: target_1
      atr_multiple: 1.5
    - name: target_2
      atr_multiple: 3.0

position_sizing:
  method: regime_adaptive
  regimes:
    BULL_LOW_VOL:     {packet_worthy: true,  position_pct: 0.05}
    CRISIS:           {packet_worthy: false, position_pct: 0.0}
```

Validation rules:

- **Brackets XOR.** When `exit.kind == "mechanical"`, exactly one of
  `exit.target` (legacy singular) or `exit.targets` (new plural) is
  required. Both is rejected; neither is rejected. `exit.kind ==
  "python_plugin"` passes through without either (plugin owns brackets).
- **`exit.targets[]` interior.** Non-empty list; each entry has a
  non-empty string `name` (unique across the list) plus a numeric
  `atr_multiple > 0`. Bool values rejected (isinstance-True-is-int trap).
- **`exit.stop.atr_multiple`.** Required when `exit.targets` is used;
  legacy `exit.target` path leaves `exit.stop` uninspected (rich
  `{method, atr_period, multiplier, floor_pct, cap_pct}` shape passes
  through unchanged).
- **`position_sizing.method`.** Restricted to `fixed_pct_equity` or
  `regime_adaptive`. `fixed_pct_equity` interior (`pct`,
  `max_concurrent`) passes through unvalidated.
- **`regime_adaptive.regimes`.** Non-empty dict. Each entry requires
  `packet_worthy: bool` + `position_pct: float` in [0.0, 1.0]. Unknown
  regime keys warn via `logger.warning` but do not reject — the known
  set is the incumbent 7-label `classify_regime`/`REGIME_THRESHOLDS`
  codomain (`BULL_LOW_VOL`, `BULL_HIGH_VOL`, `TRANSITION`, `CORRECTION`,
  `BEAR_EARLY`, `BEAR_ESTABLISHED`, `CRISIS`).

**Schema-only sprint — no runtime consumption.** Sprints F (ranker
port) and G (exit/bracket port) consume these blocks. `strategy_spec.py`
grew from 195 → 298 lines (under the 300-line C+D combined budget). New
tests: `tests/platform/specs/test_schema_brackets_sizing.py` (29 tests)
cover every rejection path, unknown-regime-key warn semantics, duplicate
target names, bool/negative/zero `atr_multiple`, and backward compat on
both shipping specs (`lazy_prices_v1` + `post_audit_ruleset_v1`).

**Backward compat.** Zero production YAML changes — both
`src/platform/specs/*.yaml` use the legacy `exit.target` +
`fixed_pct_equity` shapes (2/2 each, grep-verified in Pass 2). Three
test-helper fixtures that used bare `exit: {kind: mechanical}` without
targets were updated to `exit: {kind: python_plugin}` (tests don't
exercise brackets); commented inline.

**Housekeeping.** `config/known_violations.json` grandfathers
`src/platform/signal_eval.py` (450 lines) — grew past the 400-line cap
in Sprint B (#556) but wasn't added to the oversized list at merge;
surfaced by `tests/test_repo_structure.py::test_no_file_over_400_lines`
after pulling main into the sprint branch.

### Added (Sprint C — scoring-DSL schema block)

Closes #549 — third of 8 prerequisite sprints in the #530 Sprint chain
(Sprints A #494 and B #493 merged earlier).

`src/platform/strategy_spec.py::validate_spec` now validates an optional
`ranking.bands` block — a declarative scoring DSL that the Sprint F ranker
port will consume in place of the hardcoded bands in
`src/ranking/ranker.py::_score_ticker`.

Accepted shape:

```yaml
ranking:
  bands:
    - metric: pullback_depth_pct   # non-empty str
      range: [-8, -3]              # 2-element numeric list, lower < upper
      score: 25                    # int or float
```

Validation rules:

- `ranking` is an optional top-level key; specs without it load unchanged
  (`lazy_prices_v1` and `post_audit_ruleset_v1` regression-tested).
- `ranking.bands` is optional inside `ranking`; other sub-keys (e.g.
  hypothetical `ranking.weights`) pass through unchecked.
- Each band must provide a non-empty string `metric`, a 2-element numeric
  `range` with `range[0] < range[1]`, and a numeric `score`. Bool values
  are explicitly rejected (Python's `isinstance(True, int)` trap).
- Multiple bands per metric are allowed. Overlapping ranges on the same
  metric emit a `[PLATFORM] ranking.bands overlap: ...` warning via
  `logger.warning` — the spec still validates successfully. `validate_spec`'s
  `(ok, errors)` return signature is preserved; no callers break.

**Schema-only sprint — no runtime consumption.** Sprint F ports the ranker
to consume this block. `strategy_spec.py` grew from 131 → 195 lines (under
the 250-line sprint cap). New tests:
`tests/platform/specs/test_schema_scoring_dsl.py` (23 tests) cover every
rejection path, overlap-warn semantics, backward compat on both shipping
specs, and the `ranking.weights` pass-through case.

### Validated (v0.25.6 — lazy_prices_v1 walk-forward rerun on real EDGAR)

Closes #547. First walk-forward rerun after three upstream capabilities landed
(v0.25.4 VIX enrichment #535, v0.25.4 INCONCLUSIVE_DURATION sub-state #538,
v0.25.5 sections_json parser backfill #537). Spec, seed, and universe
unchanged from the v0.25.3 baseline (`docs/validation/lazy-prices-v1-walkforward-real-2026-04-19.md`).

**Run identity**

- `run_id`: `7a8a96b6-3d3d-4cc3-9e6f-34573547cc72`
- `spec_hash`: `ea78fed32a6ff7b3169e1657988392075677885280a22e800dfadd07c62b9e15` (identical to v0.25.3)
- `code_git_sha`: `638ef96912fa6338d88fd380b6d2328377a06d83`
- `random_seed`: `42`
- Exit code: 3 (INCONCLUSIVE)

**Outcome delta (v0.25.3 → v0.25.6)**

| metric | v0.25.3 | v0.25.6 |
|---|---|---|
| outcome_state | INCONCLUSIVE | INCONCLUSIVE |
| Windows (PASS/FAIL/INC_DATA/INC_POWER/INC_DURATION) | 0/0/5/0/— | 0/0/4/0/**1** |
| vix_tier_coverage | 0 | **3** |
| OOS trades with vix_at_entry non-NULL | 0/20 | 21/21 |
| Total OOS trades | 20 | 21 |
| Pooled Sharpe | 3.5280 | 3.8976 |
| Pooled MDE | 10.5448 | 10.2932 |

**Confirmations closed**

- **#535 (VIX enrichment):** `vix_at_entry` populated on 100% of OOS trades
  across 3 tiers (low/medium/high). `lookup_vix_at_entry` wired end-to-end
  via `_build_trade()`. Closes v0.25.3 §Follow-ups #1.
- **#538 (window-duration sub-state):** Window 4 (273 days < 365 threshold)
  correctly flips to `INCONCLUSIVE_DURATION` regardless of trade count.
  Persisted `n_windows_inconclusive_duration = 1`. Closes v0.25.3 §Follow-ups #3.

**Parser backfill impact observation**

v0.25.5's lift from 28% → 71% useful `sections_json` coverage produced **+1
new OOS trade** (PG 2024-08-06 in Window 4). Windows 0-3 trade counts
identical to v0.25.3. Pre-registered rule R3 predicted 2-6× lift; observed
delta is well below that. Candidate reasons (not in scope): #552 fetcher issue
still produces `'{}'` on 1,424 rows; prior-year reference filings pre-2019
are not in the corpus; 8-K filings (69% of the v0.25.5 backlog) don't trigger
`lazy_prices` signals. Captured, not interpreted — the framework reports the
number it got.

**Framework-bug triggers**

Inert. All triggers are PASS-conditional; outcome was INCONCLUSIVE. No
framework-bug issue filed.

**Minor follow-up flagged (not filed)**

`scripts/backtest/run_walkforward.py::main()` JSON summary omits
`n_windows_inconclusive_duration` — the persisted DB row carries it but the
CLI stdout doesn't. One-line fix in the `summary` dict. Not bundled into this
PR per the sprint's anti-goal (no spec/runner modification during validation).

**Docs**

- Pass 1 evaluation: `docs/sprints/v0.25.6_evaluation.md` (commit `638ef96`)
- Pass 2 raw capture: `docs/sprints/lazy_prices_v1_rerun_raw.md` (commit `2ca4b36`)
- Pass 3 validation: `docs/validation/lazy-prices-v1-walkforward-real-rerun-2026-04-20.md` (this PR)
### Fixed (Sprint B — python_plugin find_candidates_for_date wiring)

Closes #493, #548 — second of 8 prerequisite sprints in the #530 Sprint
chain (Sprint A, #494 scheduled-kind, merged earlier in this chain).

`src/platform/signal_eval.py::find_candidates_for_date` previously raised
`NotImplementedError` for `entry.kind: python_plugin`, blocking any strategy
declaring itself via the `StrategyPlugin` ABC from running through the live
scan pipeline. The new `_find_candidates_python_plugin` branch:

- resolves universe via `_resolve_universe`; applies `spec.universe.sector_filter`
  (identical plumbing to Sprint A's scheduled path);
- applies `entry.event_exclusion.categories` on the as_of date — short-circuits
  BEFORE dispatching to the plugin, so the plugin isn't needlessly invoked on
  excluded days;
- looks up the plugin via `plugin_registry.get_plugin(entry.plugin_ref or spec.strategy_id)`.
  `entry.plugin_ref` is a new **optional** dict key (NO schema change — not
  validated in `strategy_spec.py`); when absent, the plugin key defaults to
  the spec's own `strategy_id`;
- passes `{"db_path": live_db, "strategy_id": spec.strategy_id}` as the plugin
  `context` arg per the existing `StrategyPlugin.find_candidates` signature;
- translates returned `Candidate` dataclass objects into the shadow_harness
  dict shape, augmenting metadata with `strategy_spec_hash`, `trigger`
  (`"python_plugin"`), `signal_direction`, `plugin_ref`. Plugin-supplied
  metadata keys are preserved;
- dedupes against open `shadow_trades` on desk `research_<strategy_id>`.

Error handling (no new exception classes per sprint guardrail):

- Missing plugin → `KeyError` with `plugin_ref` + hint to check `@register_plugin`.
- Plugin's `find_candidates` raises → `RuntimeError` wrapping original via
  `raise ... from exc`; plugin name in the message.
- Plugin returns non-list → `TypeError` with the actual type.
- Plugin returns non-`Candidate` items → `TypeError` per-item with the actual
  type. All three are caught by `shadow_harness._find_candidates`' broad
  `except Exception`; tick degrades to 0 candidates.

New tests in `tests/platform/test_signal_eval_python_plugin.py` (13 tests)
cover: dispatch on spec.strategy_id, `entry.plugin_ref` override, missing
plugin / raising plugin / bad return type / wrong item type, dedup, sector
filter narrowing the universe received by the plugin, event_exclusion
short-circuit (plugin NOT called), empty universe short-circuit (plugin NOT
called), plugin context delivery, walk-forward path still raises
`NotImplementedError` (backtest_engine untouched), scheduled + event_driven
branches still dispatch correctly.

`backtest_engine._run_backtest` still raises `NotImplementedError` for
`python_plugin` kind — historical replay for plugin strategies is explicitly
out of this sprint's scope (tracked in the #530 chain). Walk-forward runner,
which routes scheduled/event_driven/python_plugin through `run_backtest`,
is untouched.

`src/platform/signal_eval.py` grew from 399 → 450 lines; at the sprint's
450-line cap.

### Executed (v0.25.5 — sections_json parser backfill for EDGAR)

Closes #537. Runs the existing section parser over the 3,743 `edgar_filings`
rows that had `full_text` populated by the 2026-04-19 fulltext backfill but
`sections_json` still NULL. Pure execution sprint — no parser logic changes,
no schema changes.

**Coverage delta**

- Useful (`sections_json` non-empty): 1,518 / 5,393 = 28.1% → 3,837 / 5,393 = **71.1%**
- Attempted (`sections_json IS NOT NULL`): 28.1% → **97.6%**

Remaining 132 NULL rows are all `full_text IS NULL` (ineligible).

**Execution**

3,743 rows processed in 6.1 s total wall-clock (plan budgeted 2 h). Batch
commits every 100 rows, zero exceptions, zero baseline drift against a
5-row spot-check of pre-parsed rows.

- 2,319 rows produced non-empty `sections_json`
- 1,424 rows produced `'{}'` (mark-attempted semantic — see #552)
- 0 exceptions

**Code changes**

- `_parse_sections` → public `parse_sections` in
  `src/data_collection/edgar_collector.py`. Callsites updated in
  `scripts/backfill_edgar_historical.py` and `tests/test_data_collectors.py`.
  No behavioral change.
- New `scripts/backfill_sections_json.py` (205 lines, all functions ≤ 48 lines,
  well under the 60-line guardrail). Flags: `--dry-run`, `--limit`,
  `--batch-size`, `--db-path`. Built-in `capture_baseline`/`verify_baseline`
  defense-in-depth against WHERE-clause drift.
- Storage semantic: empty parser dict stored as `'{}'` literal JSON, NOT NULL.
  One-way divergence from `edgar_collector.py:351` (inline collector path).
  Chosen for idempotency on re-run and diagnostic value for #552.

**Follow-up filed (#552)**

1,424 of the 3,743 rows (~38%) produced empty `sections_json`. Diagnosed
via spot-inspection: `_lookup_primary_document` is resolving some filings
to iXBRL / SGML submission-header documents instead of the narrative HTML.
Parser correctly returns `{}` on these — no narrative sections exist to
extract. Filed as **#552** for a later sprint; out of scope for v0.25.5.

**Docs**

- Pass 1 evaluation: `docs/sprints/v0.25.5_evaluation.md` (commit `c495530`)
- Pass 2 research: `docs/sprints/v0.25.5_research.md` (commit `6a8f290`)
- Pass 3 validation: `docs/sprints/v0.25.5_validation.md` (this PR)
### Fixed (Sprint A — scheduled-kind find_candidates_for_date wiring)

Closes #494 — first of 8 prerequisite sprints in the #530 Sprint A chain
unblocking v0.26.0 incumbent YAML extraction (#523).

`src/platform/signal_eval.py::find_candidates_for_date` previously warned
and returned `[]` for `entry.kind: scheduled`, blocking any scheduled
strategy spec from running through the live scan pipeline. The new
`_find_candidates_scheduled` branch:

- resolves the universe via `_resolve_universe` (honors string aliases like
  `"sp100"`, unlike `backtest_engine._run_scheduled` which short-circuits on
  non-list inputs);
- applies `spec.universe.sector_filter` (v0.26.2-scoped) via `SECTOR_MAP`;
- fires when `_matches_scheduled_trigger(as_of, entry)` is True
  (shared with the backtest path — no behavior fork);
- applies `entry.event_exclusion.categories` (v0.26.2-scoped) on the as_of
  date via `is_excluded_event_date`;
- dedupes against open `shadow_trades` on desk `research_<strategy_id>`;
- emits one candidate dict per qualifying ticker with
  `metadata.trigger == "scheduled"`.

`entry.signal` is intentionally ignored for the scheduled MVP path —
scheduled specs express timing via `day_of_week` today. A cron/interval DSL
is tracked for a later sprint in the #530 chain.

New tests in `tests/platform/test_signal_eval_scheduled.py` (10 tests)
cover: trigger-match emission on a fixed historical Monday (2023-11-06),
empty-filter path returning full universe, sector_filter + event_exclusion
composition, day_of_week mismatch, dedup against open positions, unknown
operator regression guard (no exception), unknown-kind ValueError, and
walk-forward-path-untouched confirmation. Two stale assertions in
`tests/platform/test_find_candidates.py` (which pinned the previous
warn-and-return-`[]` contract) were updated to the new behavior.

`src/platform/signal_eval.py` grew from 370 → 399 lines; under the sprint's
400-line file-size budget. `backtest_engine._run_scheduled` (walk-forward
path) is untouched — Pass 2 research
`docs/sprints/scheduled_kind_wiring_research.md` §3 confirms the two paths
are independent siblings sharing only the stateless `_matches_scheduled_trigger`
helper.

### Added (v0.25.4 Part A — VIX enrichment in walk-forward trades)

Closes #535 (and the umbrella #542). Plugs the gap diagnosed in
`docs/validation/lazy-prices-v1-walkforward-real-2026-04-19.md` where 20/20
OOS trades carried `vix_at_entry = NULL` because `BacktestTrade` had no such
field. The runner's `getattr(t, "vix_at_entry", None)` always returned None
and downstream tier bucketing degenerated to `vix_tier_coverage = 0`.

- New module `src/platform/vix_lookup.py` (~70 lines) with single function
  `lookup_vix_at_entry(entry_iso) -> float | None` that delegates to
  `fetch_cached_ohlcv("^VIX", ...)` and returns the most-recent Close on or
  before `entry_iso`. Returns None on cache miss, empty frame, or no eligible
  bar (graceful degradation, never raises).
- Add `vix_at_entry: float | None = None` field to `BacktestTrade` dataclass.
  Defaulted so existing constructors stay backwards-compatible.
- Wire `lookup_vix_at_entry` into `_build_trade()` — single call site reached
  by both `_run_scheduled` and `_run_event_driven` paths.

The runner picks up the new field automatically; `_assign_vix_tier` correctly
buckets into `low` (<15), `medium` (15–25), `high` (>25). Pass 1 source
decision: yfinance `^VIX` over FRED VIXCLS / `vix_term_structure` table /
non-existent `daily_bars` — the only source with full 2019-2024 daily
coverage (verified 12/12 month-starts in Pass 2) plus already wired through
the existing OHLCV cache path.

11 new tests in `tests/platform/rigor/test_vix_enrichment.py` cover helper
behavior + `BacktestTrade` shape + `_build_trade` integration via mocked
OHLCV/VIX path + end-to-end persistence through `walkforward_runner`.

### Added (v0.25.4 Part B — Window-duration surfacing)

Closes #538 (and the umbrella #542). Adds an `INCONCLUSIVE_WINDOW_DURATION`
sub-state so operators can distinguish "strategy didn't signal"
(`INCONCLUSIVE_DATA`) from "the OOS window was too short to deliver
meaningful coverage" (the new sub-state).

- New constant `WINDOW_INCONCLUSIVE_DURATION` in `walkforward_outcome.py`.
- New `n_windows_inconclusive_duration` field on `OutcomeResult` and matching
  `INTEGER DEFAULT 0` column on `walkforward_results`.
- New per-run config knob `min_window_duration_days: int = 365` on
  `WalkForwardConfig` + module-level `MIN_WINDOW_DURATION_DAYS = 365`. Round-
  trips through `as_json_dict()`. Override-able for power-testing or backport.
- `count_power_states` extended with `windows` + `min_window_duration_days`
  kwargs (both default-no-op so legacy callers stay unchanged). Per-window
  precedence: DURATION > DATA > POWER > PASS > FAIL.
- Run-level reducer: `INCONCLUSIVE_WINDOW_DURATION` ≥ inconclusive_window_threshold
  → outcome `INCONCLUSIVE / duration_inconclusive`, prepended ahead of the
  existing `coverage_inconclusive` and `power_inconclusive` checks.
- `cloud_routes/walkforward.py` SELECT extended to surface the new counter
  to API consumers. Dashboard chip surfacing is a follow-up; backwards-compat
  preserved (existing UI ignores the new column).

Pass 1 chose Option 1 (sub-state) over Option 2 (new `walkforward_windows`
table) because: (a) the `walkforward_windows` table doesn't exist — Option 2
would require creating it, vs Option 1's +1 INTEGER column; (b) sub-state
surfaces the distinction in every consumer (validation docs, promotion gate,
JSON outputs) for free; (c) Option 2 would require every consumer to apply
the threshold itself — drift waiting to happen.

Threshold = 365 days. v0.25.3 default windows are four 15-month (~456-day)
windows + one 9-month (273-day) tail window — the threshold cleanly flags
the tail without affecting the standard four. 1 calendar year is the minimum
needed to span ~1 cycle of seasonal effects.

15 new tests in `tests/platform/rigor/test_window_duration.py` cover reducer
+ classifier + config + persistence + a v0.25.3 retrofit asserting the new
sub-state fires on Window 4 while leaving the run-level outcome's
`coverage_inconclusive` reason intact (1 short window < threshold of 2).

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
