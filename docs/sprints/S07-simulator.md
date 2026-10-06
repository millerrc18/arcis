# S07-simulator — Step 5: bracket simulator, candidate-day ledger, walk-forward harness, trial registry

Branch: `feat/s07-simulator`. Follows S06 (PR #10, merged at `66eaeda`).

Status: in progress.

## Goal

Build the Step 5 machinery (SCOPE §5): a bracket simulator implementing the
preregistered execution rules (PREREG §1.1, R05, D-020), a candidate-day
ledger recording every simulated decision, a walk-forward harness with
purge/embargo, and a trial registry. Done when: the simulator implements
the preregistered rules and reports ambiguity rates; the harness runs end
to end on a synthetic dataset with a known answer; sequential boundaries
are generated and archived.

## CEO decisions feeding this sprint

- **D-029 (PENDING):** Entry limit price rule. Not in the frozen YAML, not in
  the Sprint F doc, not recoverable from the legacy simulation/trading code;
  S02 left it UNRESOLVED. Recommended default: **limit = the signal day's
  close** (the most literal reading of the prereg's "a limit price based on
  that close"). The simulator takes the limit as an explicit input; the
  default applies at the signal-generation layer.
- **Universe:** point-in-time S&P 500 (SCOPE D-012); S&P 100 as benchmark
  subset. The YAML's `tickers: sp100` is the legacy tuning context, not the
  research universe.
- **Cost model:** R06 **conservative** is primary; central is a sensitivity
  (SCOPE D-009, I-15).
- **Sizing:** not preregistered (no max positions, no caps). The simulator
  is per-trade; portfolio assembly takes sizing as an explicit parameter
  (default: fixed notional per trade). No caps are invented.

## What is preregistered and implementable (no decisions needed)

Per-trade mechanics (PREREG §1.1 + R05 + D-020):
- Signal on day t's final close; one buy-limit for t+1; nothing fills on
  the signal bar; all-or-none; no extended-hours fills.
- Open > limit: fill only if low strictly < limit, at the limit.
- Open ≤ limit: fill at open + adverse buffer, never above the limit (D-020).
- Target: fill only if high strictly > target, at target; open > target →
  fill at target.
- Stop-market: trigger on low ≤ stop; fill at stop − buffer; open < stop →
  fill at open − buffer. Stop-limit legs never assumed filled.
- Entry day: low ≤ stop → stop-out (entry traversed first); no target fill
  on entry day without minute-bar proof of post-fill reach.
- Later days: stop and target both reachable → stop fills first (lower
  bound); minute bars don't order same-minute events.
- 15th session: cancel confirmed legs, separate MOC order before cutoff;
  else next executable price + flag.
- Sessions = exchange calendar (SPY bar = session proxy); 15 sessions max.
- Corporate actions: no dividend adjustment (Alpaca DNR); splits →
  cancel/reissue + flag; suppress entries around special events; ex-div
  sessions excluded or separately analyzed.
- Earnings: no new entry from 1 session before through 1 after an earnings
  date with unknown release timing.
- Record every decision: timestamps, raw prices, fill rule, ambiguity/gap/
  corporate-action/minute-data flags (R05 rule 25).

Costs (PREREG §1.2, R06 conservative):
- Exact dated SEC/TAF schedules (S06); CAT zero until verified.
- Commissions: zero (modern counterfactual); $5/$10 per order as historical
  sensitivities.
- Spread proxy: larger of Corwin-Schultz / Abdi-Ranaldo, **21-session
  trailing median**, tick floor, R06 time-of-day multipliers. (The trailing
  median is currently unimplemented in costs.py — S07 implements it.)
- No generic adverse-selection charge on top of strict passive fills.
- Cost formula: commission_buy + commission_sell + CAT both sides +
  SEC_sell + TAF_sell + execution_entry + execution_exit + gap_shortfall;
  bp vs entry notional only.

Walk-forward (PREREG §4; López de Prado):
- Label intervals [t_start, t_end]; purge training rows overlapping any
  validation label interval; 15-session embargo (16 if both endpoints);
  date-grouped folds; expanding window with 15-session gap.

Trial registry (PREREG §0 rules 3, 5):
- Every evaluation logged with timestamp, code hash, data hash. Unlogged =
  protocol breach.

## Tasks (≤10 per SCOPE §6.5)

1. Panel loader + SPY session calendar in `research/panel.py`: parquet
   bars → session-indexed panel; T+1 charge-date derivation for the cost
   model; fail-closed on missing sessions.
2. Bracket simulator in `research/simulator.py`: R05/D-020/PREREG §1.1
   rules, per-trade event loop (entry → bracket → time exit), ambiguity
   accounting (ambiguous-bar rate, touch-only rate, gap-stop rate).
3. Candidate-day ledger in `research/ledger.py`: per PREREG §1.1 — signal
   row per candidate-day with next-open counterfactual, filled/unfilled,
   fill rate inputs, MAE/MFE, time to exit, all flags.
4. Cost wiring: conservative primary; 21-session trailing-median spread
   smoothing; charge_date = T+1 session from the calendar.
5. Walk-forward harness in `research/walkforward.py`: purge, embargo,
   date-grouped folds, expanding window; runs on any ledger.
6. Trial registry in `research/registry.py`: timestamp + code hash + data
   hash per evaluation; breach detection for unlogged runs.
7. Sequential boundaries: Lan-DeMets O'Brien-Fleming generator + archival
   (PREREG §0 rule 6; version-pinned, inputs/outputs archived pre-look).
8. Synthetic dataset with known answer: hand-constructed bars where every
   fill rule fires deterministically (gap entry, strict trade-through,
   stop-first ambiguity, 15th-session exit); harness runs end to end.
9. Metrics wiring: `research/metrics.py` over the ledger (Sharpe, max DD,
   hit rate, profit factor) + ambiguity-rate report.
10. Full checks green; commit/push once; open PR; independent review;
    Claude Code review. Merge only on explicit CEO approval.

## Deviations

- D-029 pending at sprint start; the simulator is built limit-agnostic and
  the default lands when the CEO decides.

## Acceptance

- Every R05/D-020/PREREG §1.1 rule has a code path and a test; ambiguity
  rates are reported, not just computed.
- Synthetic known-answer dataset: harness output matches hand-computed
  expectations exactly.
- No invented sizing caps, no invented limit rule, no invented classifier
  labels — all fail closed or parameterized.
- Frozen `config/incumbent_v1.yaml` untouched (hash verified in checks).

## Out of scope

- Step P paper lane.
- Trend/RS classifier definitions (still deferred; unknown labels raise).
- The §2.4 historical check run itself (Q1 work; S07 builds the machinery).
- Sector-ETF panel ingestion (scorer takes `sector_weighted_excess` as
  input; the S05 validation data stays outside the repo).
- Live sizing/caps (unpreregistered; parameterized only).

## Results

- `research/panel.py`: session-indexed bar panel (plain-Python `Bar`; SPY
  bar dates = session calendar; T+1 charge-date derivation; fail-closed).
  Parquet read uses a lazy pandas import (research extra).
- `research/simulator.py`: per-trade bracket event loop implementing
  PREREG §1.1 / R05 / D-020 — strict trade-through entries, D-020
  open+buffer fills, stop/target bracket, stop-first ambiguity (flagged),
  entry-day stop-out, no entry-day target fill, 15-session MOC time exit,
  halted-session skipping, corporate-action event hooks. Fill prices embed
  the R05 adverse buffer; R06 mechanical execution loss (+2.0 bp stops,
  0.5·spread+1.0 bp time exits, conservative primary) is an explicit
  add-on — no double-count.
- `research/ledger.py`: candidate-day ledger per PREREG §1.1
  (next-open counterfactual, MAE/MFE, time to exit, all flags) +
  `ambiguity_report` (SCOPE §5 done-means) + `ledger_metrics` wiring
  `research/metrics.py`.
- `research/walkforward.py`: purge (label-interval overlap) + 15-session
  embargo, date-grouped expanding folds.
- `research/registry.py`: append-only JSON-lines trial registry
  (timestamp, code hash, data hash per PREREG §0 rules 3/5).
- `research/boundaries.py`: Lan-DeMets O'Brien-Fleming one-sided 2.5%
  boundaries via grid recursion (verified against classic OBF values:
  2-look [2.774, 1.981]) + dated archival.
- Tests: 42 new (20 simulator known-answer, 10 walkforward/registry/
  boundaries, 11 panel, 1 ledger-metrics); 283 total passing.
- D-029 (entry limit rule) still pending CEO decision; the simulator
  takes the limit as an explicit input, default documented as signal
  close.
