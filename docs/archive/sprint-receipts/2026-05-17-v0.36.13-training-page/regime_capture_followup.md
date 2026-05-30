# Regime capture followup — `shadow_trades.regime_at_entry` NULL class

**Date:** 2026-05-17
**Author:** coding-team developer (Path B escalation per Task 4 brief)
**Scope:** Investigation of `regime_at_entry` NULL for 13/18 currently-OPEN trades
**Status:** Forensic logging landed; cross-subsystem root cause requires next-sprint scope

---

## Symptom

Live PostgreSQL shows 13 of 18 currently-OPEN `shadow_trades` with
`regime_at_entry=NULL`. The remaining 5 of 18 have `regime_at_entry='GREEN'`.
All 18 were opened by scans on the same Friday trading session (2026-05-15).

The split is intermittent across the same session, ruling out a constant code
bug. Something in the scan -> feature pipeline produces a missing regime field
for some tickers but not others within the same scan-or-overnight invocation
window.

---

## Trace summary

The path from `compute_market_regime()` to `shadow_trades.regime_at_entry`
crosses three subsystems:

1. **`src/features/regime.py:79`** — `compute_market_regime()` returns a dict
   with key `regime_label` (values: `calm_uptrend`, `volatile_uptrend`,
   `calm_downtrend`, `volatile_downtrend`, `transitional`). This is the
   5-label *descriptive* regime for the LLM prompt.
2. **`src/features/traffic_light.py:155`** — `compute_traffic_light()` returns
   a dict ALSO keyed `regime_label` but with values `GREEN`, `YELLOW`, `RED`.
   This is the 3-label *sizing* regime. The two functions share the same key
   name but emit incompatible vocabularies.
3. **`src/features/enrichment.py:_apply_traffic_light` (lines 89-122)** —
   on success, sets `feat["traffic_light"]` (full dict) AND
   `feat.setdefault("regime_label", ...)`. On failure, catches broadly and
   sets only `feat.setdefault("traffic_light_multiplier", 1.0)` — `traffic_light`
   nested dict is NOT set, `regime_label` is NOT set.
4. **`src/shadow_trading/executor.py:1116`** — DB writer reads
   `features.get("traffic_light", {}).get("regime_label", "")`. If
   `feat["traffic_light"]` is missing (enrichment failed), this returns `""`,
   which PG stores as the empty string but the dashboards/queries that
   coalesce `''` -> NULL surface as NULL.
5. **`src/services/scan_service.py:370`** — Telegram-side notification reads
   `feat.get("regime") or feat.get("market_regime")`. NEITHER key is ever set
   by the enricher (the enricher sets `regime_label` and the nested
   `traffic_light` dict). This line has been ineffective from day one — its
   `regime_at_entry` payload to the Telegram packet has been NULL even on
   *successful* enrichment runs. The DB persistence path at step 4 is the
   one that actually populates `shadow_trades.regime_at_entry`.

---

## Hypotheses

### (a) Regime fetch intermittently 4xx/5xx
**Evidence:** `compute_market_regime` does not make network calls — operates
on already-fetched `spy` and `ohlcv_data`. `compute_traffic_light` makes a
SQLite query for HY credit spread but does not call external APIs.
**Verdict:** UNLIKELY at the regime layer itself, but the *upstream* SPY
benchmark fetch (`fetch_spy_benchmark` at scan_service.py:70) does make a
network call and could explain why `compute_traffic_light(spy=...)` then
sees an empty `spy` DataFrame, returns `trend_score=1` (default yellow on
missing data — `traffic_light.py:69`), and ultimately still produces a
regime_label. **Does not explain the NULL pattern.**

### (b) Regime depends on a feature that wasn't computed for some tickers
**Evidence:** `attach_post_scan_features` mutates ALL tickers' feature dicts
in one shot via `for feat in features.values(): feat["traffic_light"] = tl`
(enrichment.py:111-114). The traffic_light dict is the SAME object for every
ticker in a single scan invocation. So if the post-scan enrichment runs, ALL
tickers get the regime; if it raises mid-loop somehow, NONE get the regime.
**Verdict:** Does NOT explain the 5-GREEN / 13-NULL within-session split.
The only way some tickers get GREEN and others NULL in the same scan is if
they came from *different scan invocations* (e.g. one from the pullback
scanner, one from the MR scanner, one from the universe_scanner) where one
invocation's enrichment succeeded and another's failed. **THIS IS PLAUSIBLE.**

### (c) Ternary `feat.get("regime") or feat.get("market_regime")` treats empty string as falsy
**Evidence:** YES, but this only affects the Telegram-side path at
scan_service.py:370 — not the DB persistence at executor.py:1116. The
ternary is irrelevant to the NULL-in-PG symptom. **Sub-bug but not the
load-bearing one.**

### (d) Concurrent scans race on shared regime cache
**Evidence:** `traffic_light_state` is a singleton row keyed `id=1`. Two
concurrent scans calling `compute_traffic_light()` will both
`SELECT current_regime` and both `UPDATE` — last-write-wins. SQLite's
default isolation could allow one scan to read a stale row, but the
`final_regime` value computed in-process is the one returned to the caller,
not the value re-read from the DB. **Race exists but does not cause a missing
regime_label — only causes inconsistent persistence_applied.**

### (e) The enrichment step ran BEFORE the trade-open for some tickers and AFTER for others
**Evidence:** scan_service.py:109-123 calls `attach_post_scan_features` once
per scan run, BEFORE the candidate loop at line 201. So within a single
`run_scan()` invocation, all tickers see the same `feat["traffic_light"]`
state. **Unless** a different code path (mr_scan_service, universe_scanner)
opened the 13 NULL trades — each scanner runs enrichment independently.

### (f) Multiple scanner sources with divergent enrichment success
**Evidence:** `src/services/scan_service.py` (pullback), `src/services/mr_scan_service.py`
(mean reversion), `src/scheduler/sentiment_scanner.py`, and the universe_scanner
all independently call `attach_post_scan_features`. If the overnight
schedule ran all four on 2026-05-15 and ONE of them failed the traffic_light
step (caught at enrichment.py:119), trades opened by THAT scanner would
have `regime_at_entry=NULL` while trades opened by the OTHER scanners would
have `regime_at_entry=GREEN`. **THIS IS THE STRONGEST HYPOTHESIS.**
The 5/13 split is consistent with one scanner-path's enrichment chain
short-circuiting (`compute_traffic_light` raised) while the other paths'
succeeded.

---

## Evidence cross-references

| File:Line | Role |
|-----------|------|
| `src/features/regime.py:79-185` | `compute_market_regime()` returns `regime_label` (5-label) |
| `src/features/traffic_light.py:155-265` | `compute_traffic_light()` returns `regime_label` (GREEN/YELLOW/RED) |
| `src/features/enrichment.py:89-122` | `_apply_traffic_light()` writes `feat["traffic_light"]` and `feat["regime_label"]` |
| `src/services/scan_service.py:109-123` | scan_service calls enrichment helper |
| `src/services/mr_scan_service.py:71-102` | mr_scan_service ALSO calls enrichment helper |
| `src/scheduler/sentiment_scanner.py:53-72` | sentiment_scanner runs its own `compute_market_regime` |
| `src/shadow_trading/executor.py:1116` | DB writer reads `feat["traffic_light"]["regime_label"]`, defaults `""` |
| `src/services/scan_service.py:370` | Telegram notification reads `feat.get("regime")` (key NEVER set) |
| `src/journal/store.py:181` | recommendations.market_regime reads `features.get("regime_label")` |

---

## Why escalated

The trace touches **four subsystems** with subtle vocabulary mismatches:

1. **`regime.py`** owns the `regime_label` key (5-label vocabulary).
2. **`traffic_light.py`** owns a DIFFERENT `regime_label` key (3-label vocabulary).
3. **`enrichment.py`** is the only place that bridges them; it explicitly
   chooses the traffic_light `regime_label` (GREEN/YELLOW/RED) for downstream
   readers — so the executor's DB write expects GREEN/YELLOW/RED.
4. The **scan_service:370 Telegram reader** uses keys that don't exist in
   either vocabulary (`regime`, `market_regime`). This is a separate, smaller
   bug — fixing it does not address the DB NULL issue.

A speculative fix at any one site risks regressing the others. For example,
"fixing" scan_service.py:370 to read `feat["traffic_light"]["regime_label"]`
would *also* return `""` when enrichment fails, but would not address the
root cause (enrichment intermittently fails). And refactoring the dict
shape would touch every consumer of `feat["traffic_light"]`.

Per operator's strict-rigor rule (`feedback_strict_rigor_no_handwave` —
"no skip/weaken/bypass"), the responsible move is forensic logging + audit
escalation rather than a speculative fix.

---

## Recommended next-sprint scope

### Wave 1: confirm root cause (1-2 days, no code change)

1. **Watch the forensic log** at `src/services/scan_service.py:370` (this PR)
   for one full overnight cycle. The WARNING line includes the sorted feat
   keys — if `traffic_light_multiplier` is present but `traffic_light` (nested
   dict) is absent, that confirms enrichment.py:119's exception handler ran.
2. **Grep `C:\arcis\logs\` for `[ENRICH] Traffic Light failed`** —
   enrichment.py:120 already emits a WARNING on failure. Cross-reference
   timestamps against the 13 NULL trades' `created_at`.
3. **Identify which scanner opened each of the 13 NULL trades**:
   `SELECT trade_id, ticker, source, strategy_type FROM shadow_trades
    WHERE regime_at_entry IS NULL OR regime_at_entry = '' ORDER BY created_at;`
   If they cluster by `strategy_type` (e.g. all mean_reversion) — hypothesis (f).

### Wave 2: targeted fix (1 day)

Depending on root cause:

- **If traffic_light persistence DB write races** (hypothesis d-adjacent):
  add `connect_db` retry wrapper at `_ensure_state_table` and
  `compute_traffic_light`.
- **If SPY OHLCV intermittently empty**: surface a hard fail-loud at
  `_apply_traffic_light` instead of swallowing — let the scan skip
  rather than persist NULL regimes.
- **If one scanner's enrichment path is broken**: fix that scanner's
  invocation site (mr_scan_service.py:98 or sentiment_scanner.py:63).
- **Sub-bug at scan_service.py:370**: change ternary to read
  `feat.get("traffic_light", {}).get("regime_label")` to match the DB
  writer. Low-risk follow-up regardless of root cause.

### Wave 3: vocabulary unification (2-3 days)

The dual-`regime_label` vocabulary (5-label in regime.py, 3-label in
traffic_light.py, both written to the same `feat` dict key) is a foot-gun.
Either rename one key, or document the intentional shadowing in a module
docstring. The fact that this trace requires a 60-line markdown to explain
which key wins is itself a code smell.

---

## Risk if left unfixed

- **Training-data quality**: `regime_at_entry` is one of the features in
  `src/training/data_collector.py:163` that gates "useful trade" inclusion.
  13/18 OPEN trades currently failing this gate -> 72% of the operator's
  live signal is unattributable to regime.
- **Attribution analysis**: the CTO report's regime-conditional P&L slice
  (`src/evaluation/cto_report.py:378-379`) gracefully degrades to
  "unknown" but it means we cannot evaluate how the pullback strategy
  performs in GREEN vs YELLOW vs RED regimes on the live tape — that's a
  Stage-3 gating criterion blind spot.
- **Operator confidence in dashboards**: per memory `feedback_dashboard_strategic_lens`,
  the dashboard is the operator's cockpit. A NULL regime column reads as
  "data plumbing broken" and erodes trust in the rest of the cockpit.
- **5 of 18 trades DO have the correct GREEN**, so the regime engine itself
  is functional. The intermittent NULL pattern points at scanner-path
  enrichment failures (hypothesis f) rather than a fundamental engine bug.

---

## Out of scope (operator hard non-goals)

Per Task 4 brief:
- NO new `regime_snapshots` table
- NO regime engine rebuild
- NO touch of live trading or risk governor code paths
- NO touch of shadow_trades schema
- NO mass-backfill of closed trades' regime_at_entry (Task 5 owns that)
- NO version bump or CHANGELOG edit (Task 7 owns)

This PR ships:
- Forensic logging at `src/services/scan_service.py:370`
- Regression test at `tests/test_scan_service_regime_logging.py`
- This audit document

The next-sprint scope above is the natural follow-up after the forensic
log has produced one cycle of evidence.
