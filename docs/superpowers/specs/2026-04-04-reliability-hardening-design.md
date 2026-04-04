# Reliability Hardening — Design Spec

**Date:** 2026-04-04
**Status:** Implemented and merged
**Issues resolved:** #223–#235 (13 bugs)

## Problem

A comprehensive audit identified 14 bugs across 4 subsystems, all centered
on **silent failures** — the system appeared healthy while data was missing,
queries were broken, and scheduling was skipping work.

## Solution — 4 PRs

### PR #236: Stats Endpoint (Critical)
- Fix `cboe_ratios` query referencing non-existent `ratio_type` column
- Isolate per-query try/except to prevent cascading failure
- Add `test_stats_queries_reference_valid_columns` guardrail

### PR #237: Watch Loop Scheduling (Critical)
- Remove weekday-only gate from overnight elif — run data collection 7 days/week
- `_safe_run` returns `bool`; done-flags conditional on success
- Per-task backoff dict replaces shared counter
- Reset `_collector_failures` and backoff daily

### PR #238: Collector Reliability (High)
- `CollectorConfigError` for missing API keys (analyst, insider, short_interest, macro)
- `CollectorPartialFailureError` for >50% batch failure rate
- Fix insider date filter `<=` → `<`
- Fix analyst `num_analysts` from `len(recs)` → recommendation breakdown sum
- Fix CBOE collector inserting NULLs as success

### PR #240: Render Sync Safety (High)
- `health_status()` method + `/health/sync` endpoint
- Consecutive error tracking, heartbeat logging
- INSERT-then-DELETE pattern for `latest_only` sync mode

## Prevention Measures

1. **`test_stats_queries_reference_valid_columns`** — CI guardrail catches column drift
2. **CLAUDE.md data collection rules** — documents conventions for future contributors
3. **Exception-based failure surfacing** — `CollectorConfigError` and `CollectorPartialFailureError` make failures impossible to miss at the watch loop level
4. **Per-task backoff** — structural isolation prevents cross-task interference
