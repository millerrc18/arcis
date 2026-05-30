# Orphan-Source Investigation — Exhaustive Findings (2026-05-20)

**Trigger:** training corpus stuck at ~90 examples; `system_validator` `db_orphaned_fk`
reports **560 shadow_trades with invalid/NULL `recommendation_id`**. Task #75.

**Method:** four independent angles, triangulated — (1) code paths, (2) reconciler
matching logic, (3) DB forensics on the runtime Postgres, (4) Alpaca broker ground
truth. All queries run against the live Docker PG (cutover runtime DB).

---

## Executive summary

The "560 orphans" is **not one bug — it is three distinct phenomena** that the
validator's single FK check conflates:

| # | Phenomenon | Rows | In corpus? | Status |
|---|---|---|---|---|
| 1 | **Reconciler-backfill orphan cycle** | 71 (24 tickers) | yes (closed → UNMEASURED → skipped) | **largely fixed**; ~1/day residual |
| 2 | **Buying-power rejections** (`rejected_buying_power`) | 474 | no (status=`rejected`) | downstream of #1; ongoing |
| 3 | **Dangling-FK on rejected rows** (data integrity) | (the same 474) | no | cosmetic; inflates the 560 count |

**The true "orphan source" (phenomenon 1) is closes that don't clear the Alpaca
position** → the position lingers → the morning reconcile re-discovers it as an
"orphan" and backfills a duplicate NULL-`recommendation_id` row. This is the same
root as the v0.36.28 phantom-close and the `reconciled_stale` $0 closes (F-1).
**It is largely resolved**: the cycle peaked at 30/day on 2026-05-04/05, tapered to
~1/day, and **Alpaca's 19 live paper positions exactly match the 19 open
shadow_trades right now (zero live mismatch).**

---

## Phenomenon 1 — the reconciler-backfill orphan cycle (the real orphan source)

### Mechanism

`reconcile_paper_trades` (runs ~111×/day) matches Alpaca positions to shadow_trades
**by ticker only**, against a **status-narrowed** set:

```
tracked = SELECT ... FROM shadow_trades
          WHERE source='paper' AND status IN ('open','exit_failed','exit_pending')
orphaned = [ticker for ticker in alpaca_positions if ticker not in tracked]   # ticker-only
```
(`reconcile.py:604-635`)

Two structural weaknesses:
1. **Ticker-only matching** — no order-id / entry-time anchor. The reconciler cannot
   distinguish "a genuinely new position" from "a position whose shadow_trade left
   the tracked status set."
2. **Status-narrow** — only `open`/`exit_failed`/`exit_pending` count as "tracked."
   The comments (`reconcile.py:584-603`) document reactively patching this (the ETN
   incident → adding `exit_failed`/`exit_pending`) — classic whack-a-mole.

**The cycle:** a shadow_trade is marked `closed` while the Alpaca position persists
(phantom-close per v0.36.28 [bracket-parent fill recorded as exit with no real SELL];
or a `reconciled_stale` $0 close [F-1] that doesn't clear the position; or a sticky
Alpaca paper position). The ticker drops out of `tracked` → next 09:01 reconcile
flags it as an orphan → backfills a `reconciled` row with NULL `recommendation_id`
and no features → that orphan also `reconciled_stale`-closes (position still there) →
repeat.

### Evidence

- **COP timeline** (the smoking gun): legit `bracket` trades interleaved with
  `reconciled` orphan backfills clustered at **09:01** (the morning reconcile) —
  5 orphan rows 2026-05-04→05-08, each closing `reconciled_stale`/`unknown` while
  legit COP brackets continue.
- **Cluster at 09:01** = reconcile-driven, not entry-driven.
- **Decay curve:** reconciled orphan rows by day — 05-04: **30**, 05-05: **28**,
  05-08: 5, 05-11: 7, 05-18: 1, then ~0. The mid-May v0.36.28 phantom-close fix +
  Wave 5 anti-re-backfill guard + bracket fixes addressed the lingering-position
  cause.
- **Zero live mismatch:** Alpaca paper = 19 positions; open shadow_trades = the same
  19 tickers. The reconciler would find 0 orphans right now.

### Residual gap (the ~1/day still leaking)

The Wave 5 anti-re-backfill guard (`reconcile.py:728-768`) only skips re-backfill if
the ticker was closed `exit_reason='reconciled_stale'` **within the last 6 hours**.
A phantom-close with a *different* exit_reason (e.g. `timeout`, the v0.36.28 bug
class) or a re-discovery **after 6h** is not covered → a duplicate orphan is still
backfilled. 05-18 (6 orphans) / 05-19 / 05-20 (~1/day) are the residual.

### Corpus impact

`collect_training_examples_from_closed_trades_detailed` (`data_collector.py:359-413`)
**correctly skips** these orphans ("no feature data") and the `reconciled_stale`
closes ("UNMEASURED exit_reason"). Of 123 closed trades, 73 are orphans + 62 closed
`reconciled_stale` → only ~40-50 are corpus-eligible → corpus stuck at ~90.
**The training pipeline is working as designed; the bottleneck is upstream.**

---

## Phenomenon 2 — buying-power rejections (downstream of #1)

474 `rejected_buying_power` rows (status=`rejected`, never in corpus). Recorded
deliberately by `executor.py:241 _check_paper_buying_power` (#187 — dashboard
visibility of skipped trades). Clustered on crisis days: **109 on 04-27**, 71 on
05-11, 68 on 04-26.

**Causally linked to phenomenon 1.** `executor.py:280-285` documents: *"API blips
let trades through that exhausted buying power and created 15 orphaned positions."*
The crisis Telegram (`executor.py:271`) says *"Check for orphaned positions consuming
capital."* So **lingering orphan positions consume Alpaca paper buying power →
legit new trades get rejected.** Fixing #1 reduces #2.

---

## Phenomenon 3 — dangling FK on rejected rows (data integrity)

All 474 `rejected_buying_power` rows have a `recommendation_id` that is **not** in
`recommendations` (0 valid FK). Partly retention (rejected trades start 04-25;
`recommendations` starts 04-27 — the earliest are pruned), but mostly because the
reject path records a rec_id whose recommendation row is never persisted (a
recommendation row appears to be written only for *taken* trades, not rejected ones).
Low severity — these rows aren't in the corpus — but they **inflate the validator's
`db_orphaned_fk` count to 560**, masking the much smaller (71) real-orphan signal.

---

## Hypotheses tested and RULED OUT

- **Out-of-band entry path** (some code submits Alpaca orders without
  `open_shadow_trade`): **ruled out.** All 24 orphan tickers had a prior legit
  `bracket` trade — **zero** orphans for a never-before-traded ticker. No code is
  creating brand-new positions out of band.
- **Entry-time insert-race** (`submit_order` succeeds, `insert_shadow_trade` fails):
  **ruled out behaviorally.** An insert-race would scatter orphans across the day at
  entry time and would eventually orphan a never-traded ticker; instead orphans
  cluster at 09:01 reconcile and are always for previously-traded tickers. The entry
  path also runs validation→governor→BP-check before submit and uses post-submit
  verification (CLAUDE.md Shadow Trading Rule).

---

## Recommendations (prioritized)

1. **Reconciler matching hardening (highest leverage).** Match Alpaca positions to
   shadow_trades by **entry order id**, not ticker; and check against *all*
   non-terminal statuses (or, better, "has this ticker had ANY close in the last N
   hours" rather than the narrow 6h/`reconciled_stale` guard). Kills the structural
   fragility + closes the residual ~1/day. (`reconcile.py:604-635`, `728-768`.)
2. **Generalize the Wave 5 guard** beyond `reconciled_stale`-within-6h to any recent
   close of the ticker (any exit_reason; ≥24h window).
3. **De-inflate the validator count.** Exclude `order_type LIKE 'rejected_%'` from
   `db_orphaned_fk` (they aren't orphans), OR record rejected trades with NULL rec_id
   instead of a dangling one, OR persist a recommendation row for rejected trades.
   This makes the validator surface the real (71) signal, not 560.
4. **Buying power** — once #1 lands, the orphan-driven BP exhaustion should fall;
   re-measure the rejection rate after.
5. **Corpus / holdout (#2 from v0.36.39 report)** — with the orphan source largely
   fixed, the corpus grows only as fast as *clean* trades close (~40-50 to date).
   Either let it accumulate or adapt the temporal-holdout split for small corpora.

---

## Current state

- Orphan cycle **dormant** (0 live Alpaca/DB mismatch; ~1/day residual, decaying).
- Largest "orphan" contributor (474 `rejected_buying_power`) is a **different** issue
  (BP exhaustion + dangling FK), downstream of the orphan cycle.
- No active out-of-band or insert-race source.
- The fixes that worked: v0.36.28 phantom-close side-guard, Wave 5 anti-re-backfill
  guard, bracket-attach fixes (mid-May).
