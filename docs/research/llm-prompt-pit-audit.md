# LLM-prompt PIT-cleanliness audit (Sprint 1.C Phase 2 / #94)

_Author: PM. Date: 2026-04-29. Methodology: trace prompt assembly chain → audit each context source against PIT semantics. PM-direct after dispatched agent terminated mid-investigation (~77s)._

## TL;DR

The runtime LLM prompt assembles **11 sections** in `src/llm/packet_writer.py:_build_feature_prompt`. Of these, **only sections 1-2 (technical data + market regime) are PIT-clean as built**. Sections 3-11 use enrichment data fetched without `as_of` semantics — **for backtest historical decision points, every one of those sources currently leaks "now" data into past dates**.

This is not a small fix. **5 of the 11 sections require new code paths before Phase 4 corpus generation can run**, and 1 section (sector classifications) requires an operator policy decision because PIT history isn't tracked.

The earliest viable Stage 1 walk-forward start date is gated by **whichever fix lands last**, not by data availability per se. Pre-reg §3.1 had assumed start = 2014 (post-yfinance reliable). Effective start may need to advance several years depending on which sources we accept as PIT-broken vs which we fix.

## Methodology

1. Identified prompt entry points: `src/llm/packet_writer.py` lines 150 (`_build_feature_prompt`), 301 (`_build_condensed_prompt`), 601 (`enhance_packet_with_llm`).
2. Walked the 11 prompt sections, traced each `features.get(...)` field back through `src/data_enrichment/enricher.py` to the source-fetch function.
3. For each fetch function, looked for `as_of` / `as_of_date` / `date` / `ts` parameters AND inspected the underlying data store for PIT cleanliness.
4. Cross-referenced `src/universe/pit.py` and `src/data_ingestion/risk_free_rate.py` as canonical PIT-clean exemplars.

## Findings — by prompt section

### Section 1: Technical Data — ✅ PIT-clean (gated on PIT-clean OHLCV)

Source: `src/features/engine.py::compute_all_features(ohlcv, spy)` consuming `src/data_ingestion/market_data.py::fetch_ohlcv`.

OHLCV fetched from yfinance with explicit `start`/`end` dates. The features (SMA50, ATR(14), RS vs SPY, pullback depth, volume ratio) are pure functions of OHLCV up to that bar.

**Caveat**: yfinance returns auto-adjusted prices (split + dividend adjusted). For a strict point-in-time backtest, "what would I have seen on date T" is the **unadjusted** close. Adjustments are applied retroactively when corp-actions occur, so a stock that splits 2:1 tomorrow has its prices retroactively halved across all history. This is conventionally accepted in backtesting (returns are unaffected) but worth flagging.

### Section 2: Market Regime — ✅ PIT-clean (gated on PIT-clean OHLCV)

Source: `compute_all_features` + `src/features/enrichment.py::attach_post_scan_features` for `regime_label` / `traffic_light`.

`regime_label` and `traffic_light` are functions of SPY price action only. PIT-clean.

`market_breadth_pct` ("% of universe above 50d MA") is a function of the universe's OHLCV up to date T — PIT-clean if computed on the historical universe (which `src/universe/pit.py::get_sp100_at(<as_of>)` provides).

### Section 3: Sector Relative — ⚠️ PIT-policy decision needed

Source: `src/universe/sectors.py::SECTOR_MAP` — a static Python dict mapping ticker → GICS sector.

**The dict has no PIT history.** Examples:
- Ticker `META` is mapped to "Communication Services" today, but pre-2018 it was "Information Technology" (then-Facebook reclassified in S&P's Sept 2018 GICS realignment).
- Ticker `BRK.B` is "Financials" today, was "Conglomerate" historically before GICS retired that sector.
- Ticker `BKNG` is "Consumer Discretionary" today; the predecessor ticker `PCLN` was "Information Technology" until 2014.

The PIT membership table at `data/reference/sp100_history.json` (loaded by `src/universe/pit.py`) tracks ticker membership but does **not** track sector classifications. Adding PIT sector history is a non-trivial data-engineering task (similar in shape to the corp-action curation #803).

**Operator decision**: choose one of:
1. **Accept stale sector data** for early history. Document as a known PIT impurity in pre-reg addendum. The error is bounded (most large-cap sector classifications are stable for years at a stretch).
2. **Build PIT sector history** as a Phase 1.5 prerequisite. Estimated 2-3 days of data engineering.
3. **Drop Section 3 from the prompt** for backtest-mode runs. Use a flag in the prompt builder. Trains the model to operate without sector context — but the LLM was trained WITH this context, so removing it changes the inference distribution.

### Section 4: Fundamental Snapshot — ❌ PIT-broken — MUST FIX

Source: `src/data_enrichment/fundamentals.py::fetch_fundamental_snapshot(ticker, cache_hours=24)`.

**Issues:**
1. **No `as_of` parameter.** Function signature: `fetch_fundamental_snapshot(ticker, cache_hours=24)`. Returns "latest fundamentals" with no temporal scoping.
2. **`_get_latest_value` and `_get_ttm_value` sort by `end` (period-end), not `filed`** (file lines 154, 213, 240). XBRL entries have BOTH `end` (e.g. 2026-03-31 for Q1) AND `filed` (e.g. 2026-05-01 — typically 30-45 days after end). For a historical lookup at date T, you need the latest entry with `filed <= T`, not the latest entry with `end <= T`. Current code retro-includes filings that didn't exist at T.

**Severity: high.** Fundamentals appear in Section 4 of the prompt. The LLM sees revenue YoY, EPS, gross margin, "Last filed: 10-Q (2026-03-31)" — all showing "future" data for any backtest decision point before the actual filing date.

**Suggested fix path:**
- Add `as_of: str | None = None` parameter to `fetch_fundamental_snapshot`, `_get_latest_value`, `_get_ttm_value`.
- Filter entries by `e.get("filed") <= as_of` BEFORE sorting.
- Sort by `filed` desc as the primary sort, `end` desc as secondary.
- Test: a function called with `as_of=2024-06-01` should never return an entry with `filed > 2024-06-01`.

### Section 5: Insider Activity — ❌ PIT-broken — MUST FIX

Source: `src/data_enrichment/insiders.py::fetch_insider_activity(ticker, lookback_days=90, finnhub_api_key, cache_hours)`.

**Issue:** No `as_of` parameter. Calls Finnhub directly without temporal anchor. The `lookback_days` parameter relative to "now" doesn't help — for a 2024-06-15 backtest decision, you'd want `[2024-03-17, 2024-06-15]` insider activity, but the function gives you the most recent 90 days from today.

**Severity: high.** The LLM sees insider sentiment, notable transactions, last transaction date — all present-day.

**Suggested fix path:**
- Add `as_of: str | None = None` parameter to `fetch_insider_activity`.
- Pass `from`/`to` to Finnhub API as `[as_of - lookback_days, as_of]`.
- Cache key must include `as_of` (otherwise stale "now" data overrides PIT request).
- **Coverage limit**: Finnhub's free-tier insider history goes back ~2-3 years. Stage 1 start dates beyond that need a different source OR section omission.

### Section 6: Recent News — ⚠️ PIT-clean alternative exists, NOT WIRED

Source for runtime: `src/data_enrichment/news.py::fetch_recent_news(ticker, lookback_days=7, ...)` — no `as_of`.

**Discovery:** The same module ALREADY has `fetch_historical_news(ticker, as_of_date, lookback_days=7, ...)` at line 200 with explicit "TEMPORAL COMPLIANCE: Only returns news published BEFORE as_of_date" logic. The cache also supports `as_of_date` keying.

**The PIT-clean function exists; the enricher just doesn't call it.** `src/data_enrichment/enricher.py:167-170` calls `fetch_recent_news` unconditionally.

**Severity: medium (low effort to fix).**

**Suggested fix path:**
- Add `as_of` parameter to `enrich_features()`.
- When `as_of` is None (runtime path), call `fetch_recent_news`.
- When `as_of` is set (backtest path), call `fetch_historical_news(as_of_date=as_of, ...)`.
- **Coverage limit**: Finnhub's news endpoint typically goes back 2-5 years. Earlier dates would need a different news source or omission.

### Section 7: Macro Context — ❌ PIT-broken — MUST FIX

Source: `src/data_enrichment/macro.py::fetch_macro_context(fred_api_key=None, cache_hours=24)`.

**Issue:** No `as_of` parameter. Fetches latest values for FEDFUNDS, DGS10, DGS2, CPI, UNRATE from FRED. Each `_fetch_series` call returns the most recent value.

**Severity: high.** The LLM sees Fed funds rate, yield curve, CPI, unemployment — all today's values. For a 2024-06-15 backtest, this is actual 2024-06-15+ data which a real trader couldn't have seen.

**Mitigating factor:** FRED is itself a PIT-clean data store — historical values are immutable. The infrastructure to PIT-correctly query is there (FRED API supports `observation_end` parameter); just not used.

**Suggested fix path:**
- Add `as_of: str | None = None` to `fetch_macro_context` and `_fetch_series`.
- When set, pass `observation_end=as_of` to the FRED API.
- Cache key must include `as_of`.
- The economic regime classifier (`_classify_economic_regime`) is a pure function of the inputs — no extra change needed.

### Section 8: Options Flow — ⚠️ Likely PIT-broken — INVESTIGATE

Source: features dict `atm_iv_30d`, `iv_rank`, `iv_skew_25d`, `put_call_vol_ratio`, etc.

I traced these to options data in `compute_all_features` but didn't find a clear historical source. **This audit didn't fully resolve where options flow data comes from in the runtime path.** It may be Finnhub, may be yfinance options chain, may be cached live data.

**Severity: unknown until source is confirmed.** If sourced from yfinance options (which only returns current chain), this is not just PIT-broken — it's PIT-impossible for backtest mode.

**Operator decision**: investigate or omit. Most quant pullback strategies don't depend on options flow for entry signal. If Section 8 is omittable, drop it from backtest prompts.

### Section 9: Event Calendar — ⚠️ Mixed

Source: features dict `days_to_earnings`, `days_to_fomc`, `days_to_opex`, `event_risk_score`.

- **`days_to_earnings`**: requires `earnings_calendar` SQLite table. Need to verify the table has the earnings dates AS OF the earnings date (not retroactively populated). If populated by polling APIs that return current calendar, then earnings ANNOUNCED at date T+5 would be visible at T.
- **`days_to_fomc`**: FOMC schedule is published a year in advance and immutable — likely PIT-clean if hardcoded calendar.
- **`days_to_opex`**: Third Friday of each month — pure date arithmetic. PIT-clean.
- **`event_risk_score`**: Aggregator of the above. PIT-cleanliness inherits from worst component.

**Severity: medium. Earnings calendar source needs investigation.**

### Section 10: Earnings Signals — ❌ PIT-broken — MUST FIX

Source: `src/data_enrichment/earnings_signals.py::compute_earnings_signals(ticker, db_path)`.

**Issues at file:line 65, 69, 80**:
- `WHERE earnings_date >= date('now')` — uses SQLite's `date('now')` literal. No `as_of`.
- `now = datetime.now(ET)` at line 59 — used for proximity calc.
- `analyst_estimates` queries return latest record without temporal filter (line 80 region).
- `analyst_revision_velocity_30d` uses "30 days from now," not "30 days from as_of."

**Severity: high.** Section 10 includes EPS surprise, revenue surprise, surprise streak, revision momentum — all temporal signals.

**Suggested fix path:**
- Add `as_of: datetime | None = None` parameter, default to `datetime.now(ET)`.
- Replace `date('now')` with `date(?)` and bind `as_of`.
- Replace `datetime.now(ET)` with `as_of`.
- Verify `analyst_estimates` table is itself PIT (i.e. revisions are timestamped, not overwritten).

### Section 11: Cross-Asset Context — ❌ PIT-broken — MUST FIX

Source: features dict `us_10y_yield`, `us_10y_change_1m`, `dxy_level`, `dxy_change_1m`, `vix_term_structure`, `hy_oas`, `gold_change_1m`.

These derive from various macro fetchers. Same root issue as Section 7 — no `as_of` plumbing.

**Severity: high.** Each cross-asset value is a snapshot; "1m change" is "current minus 1m ago" which is broken for historical decision points.

**Suggested fix path:** Same shape as Section 7 (FRED + yfinance for VIX/DXY/gold/HY spread, all support PIT queries).

## Findings summary table

| # | Section | Source module | PIT status | Severity | Notes |
|---|---|---|---|---|---|
| 1 | Technical Data | `features/engine.py` + `data_ingestion/market_data.py` | ✅ Clean | — | yfinance auto-adjust caveat noted |
| 2 | Market Regime | same + `features/enrichment.py` | ✅ Clean | — | Composes from PIT-clean OHLCV |
| 3 | Sector Relative | `universe/sectors.py::SECTOR_MAP` | ⚠️ Policy | Medium | No PIT history; operator decision |
| 4 | Fundamental Snapshot | `data_enrichment/fundamentals.py` | ❌ Broken | **High** | Sort by `end` not `filed`; no `as_of` |
| 5 | Insider Activity | `data_enrichment/insiders.py` | ❌ Broken | **High** | No `as_of`; Finnhub coverage limit |
| 6 | Recent News | `data_enrichment/news.py` | ⚠️ Wireable | Medium | `fetch_historical_news` exists, not wired |
| 7 | Macro Context | `data_enrichment/macro.py` | ❌ Broken | **High** | FRED supports PIT; not used |
| 8 | Options Flow | _unconfirmed_ | ⚠️ Unknown | Unknown | Source needs investigation |
| 9 | Event Calendar | `data_enrichment/earnings_signals.py` + DB | ⚠️ Mixed | Medium | FOMC/OPEX clean; earnings table PIT TBD |
| 10 | Earnings Signals | `data_enrichment/earnings_signals.py` | ❌ Broken | **High** | `date('now')` literals throughout |
| 11 | Cross-Asset Context | various macro fetchers | ❌ Broken | **High** | Same shape as Section 7 |

## Stage 1 start-date implications

Pre-registration §3.1 assumed Stage 1 walk-forward starts 2014. The PIT audit changes that calculus:

- **Sections 1, 2, 9 (FOMC/OPEX components)** — clean back as far as OHLCV reliability (yfinance ≈ 2010 for most large-caps).
- **Sections 4, 7, 11 (fundamentals + macro + cross-asset)** — once fixed, FRED + SEC EDGAR data go back to 1990s. No additional limit.
- **Section 5 (insiders)** — Finnhub free tier covers ~2-3 years. **Hard limit ~2022 unless paid tier or alternate source.**
- **Section 6 (news)** — Finnhub historical news covers ~2-5 years. Similar limit ~2020-2022.
- **Section 3 (sector)** — operator policy.
- **Section 10 (earnings_signals)** — depends on `earnings_calendar` and `analyst_estimates` table coverage. Both are PIT-questionable until investigated.

**Effective Stage 1 start = max(post-fix availability of each section)**. Without Section 5 + 6 fixes, the LLM-driven backtest is gated to **~2022 onward**, not 2014.

This is a major finding for pre-reg §3.1. Either:
- Accept ~2022 start with shorter walk-forward window.
- Drop Sections 5 + 6 from backtest prompts (changes inference distribution).
- Source insider/news data from a longer-history provider (cost + integration).

## Must-fix before Phase 4 corpus generation

In rough order of cost/value:

1. **Section 6 (news)** — cheapest fix. `fetch_historical_news` already exists; just wire enricher to route on `as_of`. ~2hr work.
2. **Section 7 (macro)** — well-understood. FRED API supports `observation_end`. ~half-day work.
3. **Section 11 (cross-asset)** — similar shape to Section 7. ~half-day work bundled with Section 7.
4. **Section 4 (fundamentals)** — needs `filed`-sort fix + `as_of` filter. ~half-day work plus tests.
5. **Section 10 (earnings_signals)** — needs `as_of` plumbing through ~7 SQL queries + verification of `analyst_estimates` table PIT. ~1 day.
6. **Section 5 (insiders)** — `as_of` fix + cache-key change + Finnhub `from`/`to` plumbing. ~half-day. Coverage limit gates Stage 1 start regardless.
7. **Section 8 (options)** — investigate first; likely cheapest to omit from backtest prompts.

**Estimated total: 3-5 days of focused PIT-fix work** before Phase 4 corpus generation can produce trustworthy LLM scores for any historical decision point.

## Operator decisions surfaced

1. **Section 3 sector PIT history**: accept stale, build PIT, or omit?
2. **Section 5 + 6 coverage limits**: accept ~2022 start, drop sections, or source from longer-history provider?
3. **Section 8 options flow**: investigate or omit from backtest prompts?
4. **Section 9 earnings calendar**: investigate `earnings_calendar` table for PIT discipline (audit-side task) or accept as best-effort?
5. **yfinance auto-adjust caveat for Section 1**: explicitly document in pre-reg addendum, or leave as conventional backtest assumption?
6. **Pre-reg §3.1 Stage 1 start date**: revise from 2014 to whatever the PIT-fix completion + coverage limits allow.

## What this audit did NOT cover

- **Did not run any tests.** Investigation only.
- **Did not trace Section 8 options data source** to its leaf — flagged for follow-up.
- **Did not audit `earnings_calendar` SQLite table for PIT discipline** — needs separate look.
- **Did not audit `analyst_estimates` SQLite table for revision-PIT** — needs separate look.
- **Did not audit company name lookups** (`get_company_name`) — assumed PIT-acceptable since names rarely change vs the ticker history (which IS tracked in `_CURATED_CHANGES`).
- **Did not check whether `fetch_recent_news` is the only news call site** — sibling-search to confirm enricher.py is the sole caller of `fetch_recent_news` would be wise.

## Strict-rigor receipts

- File:line citations for every claim
- Methodology: prompt-section-by-prompt-section, source-traced via grep+read
- Cross-referenced against `src/universe/pit.py` and `src/data_ingestion/risk_free_rate.py` as PIT-clean exemplars
- Investigation duration: ~1.5hr PM-direct after dispatched agent terminated at ~77s
- No code changes, no new dependencies, single doc deliverable
- Findings consistent with the seed clue from terminated agent (fundamentals `_get_latest_value`/`_get_ttm_value` sort by `end`)
