# Pass 1 — v0.26.2-scoped post-audit ruleset evaluation (#539)

**Branch:** `feat/post-audit-ruleset-v1-scoped`
**Date:** 2026-04-19
**Sprint type:** Schema extension + walk-forward execution. Two filters only (Defensive sector + Tariff exclusion). Morning-only deferred to #540.

## Scope reference

**Authoritative scope:** the sprint prompt's "Preflight findings" block (inline). The standalone preflight doc lives on PR #536, which is **OPEN / DIRTY** (CHANGELOG conflicts from v0.25.1/v0.25.2/v0.25.3 landing after the preflight branch was cut). Per operator instruction, I proceed using the prompt's inline summary as the authoritative scope reference rather than blocking on merging #536.

Inlined preflight findings I am treating as binding:

1. `backtest_engine._run_scheduled` is the walk-forward path. `signal_eval.py:180` NotImplementedError does **not** gate this sprint.
2. Defensive bias is expressed as a **hard filter** (chosen over soft bias to stay disjoint from #530 Sprint C's ranking-DSL work).
3. Tariff exclusion piggybacks the v0.25.1 `is_known_event(date, category='Trade Policy')` substrate.
4. R8(a): **omit** the `source_trade_ids` key entirely. `walkforward_firewall.validate_derived_from` at `walkforward_firewall.py:129-135` rejects a null value and accepts key-absence.

Verified on main (HEAD `7d61594`) during Pass 1:

| Preflight claim | Verified at | Result |
|---|---|---|
| `_run_scheduled` exists | `src/platform/backtest_engine.py:266` | ✓ |
| `_run_scheduled` is called by `run_backtest` | `src/platform/backtest_engine.py:376` (`trades = _run_scheduled(config)`) | ✓ |
| `is_known_event(date, category)` signature | `src/diagnostics/known_events.py:302` | ✓ |
| `EVENT_CATEGORIES` has 8 "Trade Policy" labels | `src/diagnostics/known_events.py:96-114` | ✓ (TARIFF_* / SANCTIONS_* / EXPORT_CONTROLS / INDUSTRIAL_POLICY / TRADE_DISRUPTION) |
| `source_trade_ids` optional in R8 firewall | `src/platform/rigor/walkforward_firewall.py:129-135` (`if "source_trade_ids" in df`) | ✓ omit-is-accepted |
| `SECTOR_MAP` source of truth | `src/universe/sectors.py:12+` (GICS names as values) | ✓ |

## Interpretation of "mirror lazy_prices_v1.yaml signal block shape"

The sprint prompt says:

> `signal:` — Mirror lazy_prices_v1.yaml signal block shape, adapted to pullback criteria (specifics per preflight doc — use existing schema surface)

`lazy_prices_v1.yaml` uses `entry.kind: event_driven` with cosine-similarity signals on EDGAR 10-K/10-Q sections. The backtest engine's `_run_scheduled` path has **no signal evaluation today** — it fires entries on `day_of_week` only (`signal_eval.py:31-37`), with `spec.entry.signal` unused. Building a "mirror with pullback criteria" inside the `scheduled` kind would require porting the pullback ranker — exactly the #530 work I already flagged as infeasible in v0.26.0.

**Resolution:** The post-audit ruleset is **layered on top of the existing lazy-prices signal substrate** — the same `event_driven` kind with cosine-similarity signals. The forensic-audit ruleset is a **filter on candidates**, not a replacement strategy. This is consistent with the prompt's "Both read-only filters applied at candidate-selection time, pre-ranking. No changes to ranking/bracket logic."

In practice:
- `post_audit_ruleset_v1.yaml` copies the lazy_prices_v1 spec body (same `entry.kind: event_driven`, same cosine signals, same brackets)
- Replaces `derived_from: null` with the forensic-audit R8(a) block (omitting `source_trade_ids`)
- Adds `universe.sector_filter: [Consumer Staples, Utilities, Health Care]`
- Adds `entry.event_exclusion.categories: ["Trade Policy"]`

This keeps the sprint additive: two new schema fields + one new spec file, no changes to existing logic or specs. It preserves the "framework validation, not strategy validation" framing inherited from v0.25.3.

**Decision: use GICS sector names (`Consumer Staples`, `Utilities`, `Health Care`) rather than ETF tickers (`XLP`, `XLU`, `XLV`) in the filter.** Rationale:
- `SECTOR_MAP` in `src/universe/sectors.py` stores GICS names as values
- Using ETF tickers would require an ETF→GICS mapping table (net +code, +chance of drift)
- Prompt's `[XLP, XLU, XLV]` is declared illustrative in the spec block comment

Filter semantics are identical either way — the 3 Defensive sectors in GICS are Consumer Staples (XLP), Utilities (XLU), Health Care (XLV).

## Schema extension (2 additive fields)

### Field 1: `universe.sector_filter: list[str] | None` (optional)

**Where:** `src/platform/strategy_spec.py` — `validate_spec()` checks type + non-empty-list when present.
**Where applied:** `_run_event_driven` / `_run_scheduled` — post-fetch ticker/row filter. Ticker rows whose `SECTOR_MAP[ticker]` is not in `sector_filter` list are dropped pre-signal-eval.
**Validation rules:**
- If present, must be `list[str]` of length ≥ 1
- Values are GICS sector names (not validated against SECTOR_MAP values — schema stays data-agnostic)
- Absent/None = no filter

### Field 2: `entry.event_exclusion.categories: list[str] | None` (optional)

**Where:** `src/platform/strategy_spec.py` — `validate_spec()` checks nested type.
**Where applied:** `_run_event_driven` — after the filing date is resolved to an entry date (filing_date + next trading day), if `is_known_event(entry_date, category=C)` returns True for any listed C, the trade is skipped.
**Validation rules:**
- If `entry.event_exclusion` block present, must be a dict
- `categories` sub-key must be `list[str]` of length ≥ 1
- Absent = no filter

### What the schema extension does NOT do

- **Does NOT add `daily_scan` entry kind.** The sprint prompt's illustrative spec used that name; the actual impl reuses `event_driven` per the interpretation above.
- **Does NOT change `ALLOWED_ENTRY_KINDS`.** Stays at `{"scheduled", "event_driven", "python_plugin"}`.
- **Does NOT touch ranker/bracket/position-sizing blocks.** Those remain whatever the base spec (lazy-prices-derived) declares.
- **Does NOT modify existing specs.** `lazy_prices_v1.yaml` untouched.

## Files to modify

| File | Change | Est. lines |
|---|---|---|
| `src/platform/strategy_spec.py` | Add 2 optional validators in `validate_spec()` | +~15 |
| `src/platform/signal_eval.py` | `_query_event_rows` filters by `universe.sector_filter`; new helper `_is_excluded_event_date` | +~25 |
| `src/platform/backtest_engine.py` | `_run_event_driven` calls `_is_excluded_event_date` before `_build_trade` | +~5 |
| `src/platform/specs/post_audit_ruleset_v1.yaml` | New spec file | +~50 |
| `tests/platform/specs/test_post_audit_ruleset_v1.py` | Spec loads + R8(a) parses + filters registered | +~40 |
| `tests/platform/test_sector_filter.py` | `_query_event_rows` filters non-Defensive | +~35 |
| `tests/platform/test_event_exclusion.py` | `_is_excluded_event_date` skips Trade Policy dates | +~30 |
| `tests/platform/test_r8_firewall_post_audit.py` | Loading with `bootcamp: true` is rejected | +~20 |
| `docs/validation/post-audit-v1-scoped-walkforward-2026-04-20.md` | Validation doc | +~150 |
| `docs/validation/v0.26-cycle-summary.md` | Cycle summary | +~80 |
| `CHANGELOG.md`, `MASTER.md`, `RELEASES.md` | v0.26.2-scoped entries | +~40 |

Total est.: ~490 lines across 11 files. No file exceeds the 400-line guardrail after edits.

## Test plan

### Unit — Schema validation (`test_post_audit_ruleset_v1.py`)

1. `test_loads_post_audit_ruleset_v1_spec()` — `load_spec("post_audit_ruleset_v1")` returns a StrategySpec with both filter fields populated
2. `test_r8a_parses_without_source_trade_ids()` — spec's `derived_from` validates through `walkforward_firewall.validate_derived_from` without source_trade_ids key
3. `test_sector_filter_required_type()` — if `universe.sector_filter` present, must be list[str]; other types rejected
4. `test_event_exclusion_categories_required_type()` — same for `entry.event_exclusion.categories`
5. `test_lazy_prices_still_loads_without_new_fields()` — regression: `load_spec("lazy_prices_v1")` still passes

### Unit — Sector filter (`test_sector_filter.py`)

1. `test_sector_filter_keeps_defensive_tickers()` — `_query_event_rows` result filtered to Consumer Staples / Utilities / Health Care GICS tickers only
2. `test_sector_filter_no_filter_returns_all()` — absence of `sector_filter` preserves full universe
3. `test_sector_filter_unknown_ticker_excluded()` — tickers missing from `SECTOR_MAP` are excluded (defensive default)

### Unit — Event exclusion (`test_event_exclusion.py`)

1. `test_event_exclusion_skips_trade_policy_date()` — `_is_excluded_event_date("2022-03-08", categories=["Trade Policy"])` is True (SANCTIONS_ESCALATION known-event date)
2. `test_event_exclusion_non_match_allows()` — `_is_excluded_event_date("2022-03-09", categories=["Trade Policy"])` is False
3. `test_event_exclusion_empty_list_is_noop()` — empty categories list = no exclusion
4. `test_event_exclusion_multiple_categories()` — matching on any listed category triggers skip

### Integration — R8 firewall regression (`test_r8_firewall_post_audit.py`)

1. `test_firewall_rejects_bootcamp_in_spec()` — loading a spec-dict with `bootcamp: true` raises via firewall
2. `test_firewall_accepts_forensic_audit_source_type()` — forensic_audit_ruleset is accepted

### Walk-forward — end-to-end

One real walk-forward run per the v0.25.3 pattern:

```
python -m scripts.backtest.run_walkforward --strategy post_audit_ruleset_v1 --json
```

Captures:
- `outcome_state` / `reason`
- `pooled_sharpe`, `pooled_mde`
- 5-window breakdown
- R7 fields (spec_hash, code_git_sha, random_seed, config_json)
- R8(a) declaration echo (`derived_from_source_type=forensic_audit_ruleset`)
- R8(b) overlap assertion cleared (source date range 2026-04 vs OOS windows 2019-2024 — no overlap trivially)

## Outcome hypothesis

**Predicted:** INCONCLUSIVE / `coverage_inconclusive` with ≤ lazy_prices trade count per window.

**Reasoning:**
- v0.25.3 baseline (lazy_prices on real data): 20 trades across 5 windows (4/7/4/4/1). All 5 → INCONCLUSIVE_DATA (`min_trades_per_window=10` gate not met on any window).
- Post-audit filter 1 (sector_filter → Defensive only): S&P 100 has roughly ~20 Defensive tickers (Consumer Staples + Utilities + Health Care ≈ 8 + 4 + 14 = ~26 currently, but point-in-time view varies). So filter 1 alone retains ~20-26% of the trade stream → ~4-5 trades across 5 windows.
- Post-audit filter 2 (tariff exclusion): v0.25.1 backfill added 9 Trade Policy dates in 2019-2024. Tariff exclusion removes any filing entry whose next-trading-day lands on one of those 9 dates. Expected removal: 0-1 trades.
- Combined: ~4-5 trades across 5 windows. Well below 10/window gate. 5/5 INCONCLUSIVE_DATA predicted.

**Expected relative to v0.25.3 baseline:**
- Outcome state: same (INCONCLUSIVE / coverage_inconclusive)
- Reason: same
- Trade count: smaller (~4-5 vs 20)
- MDE: larger on a per-window basis (fewer trades → less precise)
- Heavy-tail override: likely fires on ≥4/5 windows (same as baseline)

**Anti-hypothesis (would trigger framework-bug investigation):** PASS outcome. Same as v0.25.3 — underpowered data should not produce a passing result.

## Pre-registered framework-bug trigger rules

Same 6 triggers as v0.25.3 Pass 1:

1. State-machine miscount — sum(pass + fail + inc-data + inc-power) ≠ n_windows
2. MDE gate miscalibrated — pooled MDE computation permits PASS despite small-N
3. Bootstrap SE override not firing — `heavy_tail_flag=0` despite obvious heavy-tail windows
4. Data leakage through purge/embargo — non-zero purged/embargoed would indicate partial fix; zero with PASS + overlapping windows would indicate missing purge
5. VIX tier coverage miscount — reports >0 VIX tiers when no trade has vix_at_entry set (v0.25.3 finding: VIX enrichment gap upstream, separate from framework logic)
6. R8 overlap assertion bypass — R8(b) says "derived_from window 2026-04-01..18" overlaps OOS 2019-2024 windows = trivially False; if firewall disagrees, bypass present

**New trigger for this sprint:**

7. **Filter bypass** — if post_audit_ruleset_v1 produces MORE trades than lazy_prices_v1 against identical OOS windows, the filters aren't being applied (despite being in the spec). Target state: `post_audit_v1.n_trades ≤ lazy_prices_v1.n_trades` across all windows.

## Anti-goals (echoed)

- No morning-only filter work. #540.
- No modifications beyond the two filters. Incumbent logic unchanged.
- No tuning to produce PASS. Run exactly-as-specified.
- No collapsing INCONCLUSIVE to FAIL in cycle summary.
- No widening `source_date_range` to capture more evidence.
- No adding `daily_scan` entry kind (it's not needed; use `event_driven`).

## Pass 2 plan

- Confirm `SECTOR_MAP` coverage for the 3 Defensive sector names (count actual tickers)
- Verify `_run_event_driven` does not already short-circuit on empty candidate set (so the sector filter can reduce to zero without crash)
- Check whether `_query_event_rows` has an existing hook for ticker filtering (SQL WHERE IN vs post-fetch filter)
- Verify `is_known_event` date semantics (date string format, timezone) match `filing_date + next_trading_day` format
- Amend Pass 1 if any finding changes implementation plan
