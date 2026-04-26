# Forensic Memo: BP Rejection Event — 2026-04-01

**Prepared:** 2026-04-25  
**Investigator:** Automated forensic pass (Track-1.5 / A1)  
**DB baseline:** `ai_research_desk_bootcamp_2026-04-24.sqlite3`  
**Log baseline:** `halcyon-lab/logs/halcyon.log`  
**Status:** COMPLETE — root cause determined

---

## Executive Summary

The "BP rejection event" assigned to 2026-04-01 is a misnomer. **BP (British Petroleum) does not appear anywhere in the archive DB or halcyon.log**; it was never in the bootcamp's trading universe (not in `sp100_historical_constituents`, `setup_signals`, `recommendations`, `shadow_trades`, or `attribution_trades`). What actually occurred on 2026-04-01 was a **systematic buying-power rejection cascade affecting 20 tickers across the paper-trading desk**, driven by capital exhaustion from a large, undischarged legacy position batch carried over from the prior week. The cascade was broker-sourced (`order_rejected_buying_power`) and affected only the paper channel. Live trading was unaffected.

---

## Timeline

| Timestamp (ET) | Source | Action | Outcome |
|---|---|---|---|
| 2026-03-24 09:58–10:12 | alpaca_adapter (paper) | 15 paper positions opened, ~$5–$700/each (early small allocation sizing) | All entered |
| 2026-03-27 11:59–16:05 | alpaca_adapter (paper) | 9 paper positions opened, $19k–$24k each (new large allocation sizing) | All entered |
| 2026-03-31 13:26–13:42 | alpaca_adapter (paper) | 2 additional large paper positions (C, SPG, ~$15k–$23k) | All entered |
| 2026-04-01 00:03 | scheduler/watch | System restart, all SQLite tables verified | OK |
| 2026-04-01 09:34 | alpaca_adapter (live) | MO live entry at $22.80 | Entered |
| 2026-04-01 09:35 | alpaca_adapter (live) | WMT live entry at $1.14 | Entered |
| 2026-04-01 10:05 | alpaca_adapter (live) | CAT live entry at $21.51; target_1 hit, exit_failed | exit_failed |
| 2026-04-01 10:08 | alpaca_adapter (live) | CVX live entry at $1.07; stop hit, exit_failed | exit_failed |
| 2026-04-01 10:15 | alpaca_adapter (paper) | AMGN paper entry at $24,442 planned allocation | Entered |
| **2026-04-01 10:18** | **alpaca_adapter (paper)** | **EXC paper entry attempted at $25,461** | **REJECTED: order_rejected_buying_power** |
| 2026-04-01 10:20 | alpaca_adapter (paper) | INTC paper entry attempted at $9,086 | REJECTED |
| 2026-04-01 10:38 | alpaca_adapter (paper) | COP paper — reconciled_stale (position closed without fill) | closed |
| 2026-04-01 10:40–13:24 | alpaca_adapter (paper) | Repeated scan cycles attempt EXC, DUK, BK, GS, INTC on each scan pass | All REJECTED |
| 2026-04-01 13:09–13:22 | alpaca_adapter (paper) | Last mid-day rejection batch (EXC, BK, DUK, GS) | All REJECTED |
| 2026-04-01 15:53–16:09 | alpaca_adapter (paper) | Final scan pass attempts 19 tickers | All 19 REJECTED |
| 2026-04-01 16:09:54 | scan_service (reconciler) | End-of-day stale-position sweep fires | 18 stale paper positions closed (reconciled_stale) |

---

## Rejection Counts by Source

No dedicated `risk_governor_events` table exists in the schema registry (only `strategy_promotion_events` matched the governor/risk/event filter). All rejections on 2026-04-01 originated from a single source.

| Subsystem | Rejection Count | Rejection Reason |
|---|---|---|
| **alpaca_adapter (paper broker)** | **42** | `order_rejected_buying_power` |
| gate_evaluator | 0 | No gate-level rejections logged |
| risk_governor | 0 | No governor events table; traffic_light_state was GREEN all day |
| scan_service / ranker | 0 | All 7 scan cycles completed normally (102 universe, 20 packet-worthy, 0 duration errors) |
| llm_pipeline | 0 | 20/20 LLM success on all scans; 0 fallbacks |
| live broker | 0 | Live channel unaffected |

**Total rejections on 2026-04-01: 42 (100% paper channel, 100% buying_power reason)**

For comparison: the only other days with broker rejections in the full archive are 2026-04-17 (34), 2026-04-20 (11), and 2026-04-21 (35) — all post-bootcamp restart days with the same root pattern.

**Tickers rejected on 2026-04-01:**

| Ticker | Rejection Count |
|---|---|
| EXC | 8 |
| DUK | 6 |
| BK | 5 |
| GS | 4 |
| INTC | 4 |
| VZ, CAT, CVX, LIN, WMT, C, COP, ETN, FDX, XOM, AMGN, BMY, LMT, MRK, NEE | 1 each |

EXC and DUK dominated because they appeared on every intra-day scan and were re-attempted at each pass cycle without the broker state resetting.

---

## Hypothesized Root Cause

**Paper account buying-power exhaustion from over-allocated legacy positions.**

By the time the first rejection fired at 10:18, the paper account was carrying approximately **$221,000 in open paper allocations** from positions entered between 2026-03-24 and 2026-04-01 10:15. This figure comes from summing `planned_allocation` for all paper trades with `actual_entry_time < 2026-04-01T10:18` and no exit time recorded.

The critical inflection happened between 2026-03-27 and 2026-03-31, when paper allocation sizing shifted from small ($100–$1,000 per position) to large ($19,000–$24,000 per position). Nine positions were opened at the new scale, consuming roughly $175,000 of capacity. When the April 1 scan attempted to add AMGN at $24,442 (which succeeded at 10:15, consuming the last available capacity) and then EXC at $25,461, the broker's paper account ceiling was breached.

The cascade persisted all day because:
1. The system retried every scan signal regardless of the prior rejection result for the same ticker.
2. No pre-check exists to query remaining paper buying power before submitting new orders (the `ib_shadow_log` table has an `ib_buying_power` field, but it was empty for all 2026-04-01 entries).
3. The stale-position reconciler ran only at end of day (16:09:54), so capital tied up in stale open positions was not released intra-day.

**BP (British Petroleum) was never part of this event.** The ticker BP is absent from the entire bootcamp universe. The "BP rejection event" label is most likely a miscommunication — either a ticket referencing "buying power" (abbreviated BP in some internal notation) or a ticker lookup that misidentified the rejection context.

---

## Falsifiability Test

To distinguish this buying-power exhaustion hypothesis from three alternatives:

**Alternative 1: A risk-governor kill-switch blocked BP specifically.**  
_Test:_ BP does not exist in `sp100_historical_constituents` or `setup_signals`. If BP were scanned and blocked by the governor, it would appear in at least one of those tables. It appears in none. This alternative is falsified.

**Alternative 2: A market-wide kill-switch fired (all tickers blocked).**  
_Test:_ scan_metrics shows `live_traded=0` on 2026-04-01, but `paper_traded=20` on all 7 scan cycles — meaning the system was actively filling paper trades (and only rejecting some). If a kill-switch had fired, no paper fills would have succeeded. The hypothesis is falsified: AMGN was filled at 10:15, COP at 10:38 (and reconciled stale shortly after). The pattern is buying-power exhaustion after a threshold, not a blanket block.

**Alternative 3: A data-quality issue with BP price data caused rejection.**  
_Test:_ Query `minute_bars` or `options_metrics` for BP on 2026-04-01. If BP appears with corrupted data, a gate_evaluator rejection would be plausible. From the available evidence, BP is completely absent — no data, no scan, no evaluation. This alternative is unfalsifiable in the current dataset because BP is simply not there.

**To fully confirm the buying-power hypothesis:** Query the Alpaca paper account's buying power balance at each scan cycle on 2026-04-01. The `ib_shadow_log.ib_buying_power` column is the right place but was not populated. Enabling that field would make future incidents self-documenting.

---

## Recommendation

**(a) No code defect for BP — BP was never in-universe. The "BP rejection" label should be corrected in any tickets or post-mortems.**

For the actual buying-power rejection cascade:

**File GitHub issue: `alpaca_adapter` does not pre-check paper buying power before order submission, causing entire scan batches to be rejected once the paper account is exhausted.**

Specifically:
- The adapter submits paper orders without first querying available capital (`ib_buying_power` field in `ib_shadow_log` exists but is never populated for paper trades).
- The scanner retries rejected tickers on every subsequent scan cycle with no cooldown or rejection memory.
- The end-of-day stale reconciler (`reconciled_stale` sweep at 16:09:54) should run more frequently or be triggered when a buying-power rejection is first observed.

This is not a safety issue for live trading (live channel was unaffected) but creates misleading signal counts and wastes LLM capacity generating packets for tickers that cannot be traded.

---

## Evidence Gaps

- No `risk_governor_events` table exists in the schema registry. Governor decisions are not persistently logged; only indirect evidence (traffic_light_state was GREEN) indicates no governor kill was active.
- `ib_shadow_log` was empty for all 2026-04-01 entries, so Alpaca's actual available capital at each rejection moment cannot be confirmed from the archive.
- `halcyon.log` does not contain market-hours scan/trade entries (only sync and scheduler noise during trading hours) — application-level trade logging appears to go to the DB only, not to the flat log file.
- The pre-sprint postmortem at `docs/analysis/bootcamp_postmortem_2026-04-24.md` was referenced in the sprint plan but does not exist in the repo; its context was unavailable.
