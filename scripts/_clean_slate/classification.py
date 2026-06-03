"""Reviewed WIPE/KEEP partition for the clean-slate wipe (#95) — the spine.

Single human-reviewed source of truth for which of the 80 registered tables
are trade/learning state (TRUNCATE-d) vs market-data/operator-authored
(PRESERVED). Reviewed once against `src.schema.registry.TABLES` on 2026-06-03
(missing=[], extra=[], overlap=[]) and enforced by a CI completeness guard
(`assert_partition_complete`, mirroring src/utils/db.py:820-836's
`_require_classified_replace`).

Counts: WIPE=53, KEEP=27, sum=80 == len(registry.TABLES).

This module is PURE data + set algebra. It deliberately imports NO
DB-connection / TRUNCATE / information_schema logic — the live reconciliation
(the authoritative runtime gate) lives in `live_schema.py`. The registry guard
here is necessary but NOT sufficient (spec §3.4 / §3.7).

Tests: tests/scripts/test_clean_slate_classification.py
"""

from __future__ import annotations

from src.schema import registry

# Pinned count of the registered universe. A registry add/remove that happens
# to keep the partition valid still trips the guard via this count-pin.
EXPECTED_REGISTRY_COUNT = 80

# ── WIPE: trade/learning state — TRUNCATE ... RESTART IDENTITY CASCADE (53) ──
WIPE_TABLES: frozenset[str] = frozenset({
    # core trade + recommendation
    "recommendations", "shadow_trades", "ib_shadow_log", "attribution_trades",
    "bracket_health", "broker_exceptions", "preflight_runs", "setup_signals",
    # learning / model / training
    "validation_results", "model_versions", "training_examples", "model_evaluations",
    "preference_pairs", "canary_evaluations",
    # council (votes/sessions/calibration/logs/params)
    "council_sessions", "council_votes", "council_calibrations", "council_debug_log",
    "council_parameter_log", "council_parameter_state",
    # audit/metrics/costs/ops-logs (per-run derived)
    "audit_reports", "metric_snapshots", "api_costs", "scan_metrics",
    "schedule_metrics", "quality_drift_metrics", "build_score_history",
    "activity_log", "log_entries", "command_results",
    # backtest / strategy / research-quant outputs
    "stress_test_results", "simulation_results", "backtest_results", "backtest_trades",
    "strategy_registry", "strategy_promotion_events", "trials_registry",
    "correlation_matrices", "factor_loadings", "walkforward_results", "walkforward_trades",
    # notifications (per-run send state) + platform events
    "notifications_sent", "notifications_dedup", "notifications_digest_queue",
    "platform_events",
    # runtime quote cache (re-derives from collectors)
    "live_prices",
    # local IB-gateway infra-health telemetry (DD-IBHEALTH)
    "daily_ib_health",
    # AMBIGUOUS -> ruled WIPE (Decisions Log)
    "traffic_light_state", "data_freshness", "pending_commands",
    "diagnostic_runs", "diagnostic_run_plots", "system_metrics",
})

# ── KEEP: market-data / collector / operator-authored — PRESERVE (27) ──
KEEP_TABLES: frozenset[str] = frozenset({
    "edgar_filings", "insider_transactions", "short_interest", "short_volume_daily",
    "fed_communications", "analyst_estimates", "options_chains", "options_metrics",
    "cboe_ratios", "google_trends", "vix_term_structure", "macro_snapshots",
    "earnings_calendar", "research_papers", "research_digests", "research_docs",
    "minute_bars", "sp100_historical_constituents", "institutional_holdings",
    "filings_sentiment", "press_releases", "company_executives", "stock_financials",
    "price_targets",
    # AMBIGUOUS -> ruled KEEP (Decisions Log)
    "config_overrides", "user_notes", "operator_view_state",
})

# ── FK topology proving a single multi-table TRUNCATE is keep-safe (§3.5) ──
# The 6 expected edges, all wipe->wipe (none touch the keep-set), normalized to
# (child_table, child_col, parent_table). Asserted constant-vs-spec by the CI
# guard AND constant-vs-live by live_schema.reconcile_live_fk_edges (§3.7).
EXPECTED_FK_EDGES: frozenset[tuple[str, str, str]] = frozenset({
    ("shadow_trades", "recommendation_id", "recommendations"),
    ("shadow_trades", "strategy_id", "strategy_registry"),
    ("council_votes", "session_id", "council_sessions"),
    ("council_debug_log", "session_id", "council_sessions"),
    ("diagnostic_run_plots", "run_id", "diagnostic_runs"),
    ("attribution_trades", "recommendation_id", "recommendations"),
})

# ── Unregistered residue handled OUTSIDE the PG partition (so the guard does
# not flag it). `sync_state` is referenced by archive_bootcamp:188 but is NOT a
# registered TableDef and lives only in SQLite — captured by the SQLite-archive
# phase (§4.5). Render is inert post-cutover. ──
UNREGISTERED_NOTES: dict[str, str] = {
    "sync_state": (
        "render-sync cursor; SQLite-only, not a registered TableDef. Captured by "
        "the SQLite-archive phase, not the PG TRUNCATE. Render is inert post-cutover."
    ),
}


def assert_partition_complete() -> None:
    """Refuse on any drift of the WIPE/KEEP partition vs the registry.

    Mirrors src/utils/db.py:820-836's `_require_classified_replace`. Computes
    missing / extra / overlap against `set(registry.TABLES)` and raises
    AssertionError naming all three sets if the partition is not an exhaustive,
    disjoint cover. Also pins the registered count to EXPECTED_REGISTRY_COUNT so
    a registry add/remove that happens to keep the partition valid still trips.
    """
    universe = set(registry.TABLES)
    wipe, keep = set(WIPE_TABLES), set(KEEP_TABLES)
    missing = universe - (wipe | keep)
    extra = (wipe | keep) - universe
    overlap = wipe & keep
    if missing or extra or overlap:
        raise AssertionError(
            f"clean-slate partition drift: missing={sorted(missing)} "
            f"extra={sorted(extra)} overlap={sorted(overlap)} — "
            f"re-review classification.py against src/schema/registry.TABLES "
            f"(n={len(universe)})."
        )
    if len(universe) != EXPECTED_REGISTRY_COUNT:
        raise AssertionError(
            f"registry table count drift: len(registry.TABLES)={len(universe)} "
            f"!= EXPECTED_REGISTRY_COUNT={EXPECTED_REGISTRY_COUNT}. A table was "
            f"added/removed — re-review the WIPE/KEEP classification and update "
            f"the count-pin."
        )
