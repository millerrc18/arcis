# S07-simulator — Step 5: bracket simulator, candidate-day ledger, walk-forward harness, trial registry

Branch: `feat/s07-simulator`. Follows S06 (PR #10, merged at `66eaeda`).

Status: in progress — PR #11 open; Claude Code round-1 REJECT addressed
in round 2 (see Deviations).

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
- **Round 2 (Claude Code REJECT round 1, 2026-10-06):** six blocking
  findings, all addressed:
  1. mypy failed in CI (numpy import-not-found without research extras).
     Fixed by rewriting `boundaries.py` in pure Python (stdlib only) —
     no numpy/scipy anywhere, so the generator and its tests run in
     every environment.
  2. Wrong Lan-DeMets spending function. The correct one-sided form is
     α(t) = 2 − 2Φ(z_{1−α/2}/√t) (gsDesign sfLDOF; verified against the
     published docs). Boundaries are now [2.963, 1.969] (2-look),
     [3.710, 2.511, 1.989] (3-look).
  3. Task 4 cost wiring was stub-only. Now `build_ledger` derives
     per-trade spreads (21-session trailing median) and R06 buffers
     (with time-of-day multipliers: conservative 3.0/1.5/2.0), and the
     marketable-exit add-ons follow R06 exactly (+1.0 bp conservative).
  4. Missing bars were silently skipped. Now the Panel fails closed on
     undeclared gaps; only *declared* halts are skipped (not counted).
  5. Target filled on touch (`>=`). Fixed to strict `>` with a
     regression test (the fix was lost before the round-1 push because
     no test covered it — now it does).
  6. Registry had no breach detection. Now `TrialRegistry.logged_run`
     (complete/failed records) and `walkforward.run_evaluation`, which
     requires a registry.
  - Should-fix items also addressed: R05-22 entry blackouts (t−1
    through resolution via `expand_blackouts`), R05-20 split
    cancel/reissue (ratio-adjusted, flagged), R05-21 ex-div stop
    flagging, R05-18 late time-exit flag, walk-forward 15-session
    embargo made explicit and reachable, unfilled label_end = t+1,
    MAE/MFE measured post-entry (intraday timing unknowable),
    settlement-aware charge dates (T+3/T+2/T+1 per the prereg's
    "≈ settlement").
  - Earnings blackout: NOT a preregistered rule — it is R05 research
    question 7 ("does excluding earnings improve tail risk?"), so its
    absence from the simulator is correct.
- T+1 charge-date correction: the sprint originally prescribed T+1 for
  all history, but PREREG §1.2 says "≈ settlement" and settlement was
  T+3/T+2 before 2024-05-28. Implemented the historical regimes as a
  bug fix toward the preregistered intent (flagged for CEO awareness).

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

## Results (round 2)

- `research/panel.py`: session-indexed bar panel (plain-Python `Bar`;
  SPY bar dates = session calendar; settlement-aware charge dates
  T+3/T+2/T+1; declared halts + fail-closed gap validation).
  Parquet read uses a lazy pandas import (research extra).
- `research/simulator.py`: per-trade bracket event loop implementing
  PREREG §1.1 / R05 / D-020 — strict trade-through entries, D-020
  open+buffer fills, strict target (`high > target`), stop/target
  bracket, stop-first ambiguity (flagged), entry-day stop-out, no
  entry-day target fill, 15-session MOC time exit with late-exit flag,
  declared-halt skipping, R05-20 split reissue (flagged), R05-21 ex-div
  stop flagging, R05-22 entry blackouts. Fill prices embed the R05
  adverse buffer (R06 TOD multipliers); R06 marketable-exit loss
  (+1.0 bp conservative) is an explicit add-on — no double-count.
- `research/ledger.py`: candidate-day ledger per PREREG §1.1
  (next-open counterfactual, post-entry MAE/MFE, sessions held, all
  flags incl. late/exdiv/split) + `ambiguity_report` (SCOPE §5
  done-means) + `ledger_metrics` wiring `research/metrics.py`.
  Per-trade auto cost wiring (21-session trailing spread + R06 buffer).
- `research/walkforward.py`: explicit 15-session embargo gap in
  `make_folds`, reachable purge+embargo in `apply_purge_embargo`,
  date-grouped expanding folds, and `run_evaluation` (requires a
  registry).
- `research/registry.py`: append-only JSON-lines trial registry
  (timestamp, code hash, data hash per PREREG §0 rules 3/5) +
  `logged_run` (complete/failed breach evidence).
- `research/boundaries.py`: pure-Python Lan-DeMets O'Brien-Fleming
  one-sided 2.5% (spending α(t) = 2−2Φ(z_{1−α/2}/√t), gsDesign sfLDOF)
  via grid recursion + dated archival. Verified: 2-look [2.963,
  1.969], 3-look [3.710, 2.511, 1.989].
- Tests: 307 passing, 0 skipped (66 new/updated in round 2).
- D-029 (entry limit rule) still pending CEO decision; the simulator
  takes the limit as an explicit input, default documented as signal
  close.
