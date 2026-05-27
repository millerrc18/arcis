# Rigor Stack Integration

Reference for the `/arcis:strategy` skill: how `backtest` and `analyze`
verbs compose with the canonical rigor stack at `src/platform/rigor/`.
Read-only prose; cited from `commands/strategy.md` (Phase B2 R8 preflight,
B4 "Show me the rigor stack reference" branch, B9 "Rigor guarantees by
construction" line, AN5 outcome-state interpretation).

## 1. R8 firewall — what it enforces

Per `src/platform/rigor/walkforward_firewall.py` (FA9), R8 is a multi-part
contract. The skill leans on three of the clauses:

- **R8(a)** — `validate_derived_from(spec_raw)`
  (`walkforward_firewall.py:81-135`). `derived_from` is REQUIRED on every
  spec. Value may be `None` (literature-derived; no in-house provenance)
  OR a dict with `source_type ∈ {forensic_audit_ruleset, bootcamp_backtest,
  shadow_trading_cohort, other}` (`ALLOWED_SOURCE_TYPES` frozenset at
  `walkforward_firewall.py:52-55`), `source_run_id` (regex
  `[A-Za-z0-9_.\-]+` per `walkforward_firewall.py:57`),
  `source_date_range {start, end}` (ISO `yyyy-mm-dd`), optional
  `source_trade_ids` (list[str]). Anything else raises `R8ViolationError`
  (`walkforward_firewall.py:48-49`) — partial results are NEVER written.

- **R8(b)** — `assert_no_overlap(derived_from, windows)`
  (`walkforward_firewall.py:143-162`). For each `source_date_range`, ZERO
  overlap with ANY OOS window. No-op when `derived_from is None`. Raises
  `R8ViolationError` on overlap with the offending window in the message.

- **R8(d)** — `ensure_bootcamp_off(bootcamp_override)`
  (`walkforward_firewall.py:165-175`). Refuses when
  `WalkForwardConfig.bootcamp_override=True`. Belt-and-suspenders to the
  config-level guard.

The skill does NOT preflight R8(b) or R8(d). R8(b) needs the full window
set (constructed inside the runner). R8(d) is config-bound and already
raises in `WalkForwardConfig.__post_init__`. Both fire at runner entry; the
runner's raise reaches the operator through the same `R8ViolationError`
envelope.

## 2. Skill-layer R8 preflight (rationale)

Phase B2 runs `validate_derived_from(spec.raw)` BEFORE invoking
`run_walkforward()`. The runner repeats the check at entry, so the
skill-layer call is redundant for correctness — it exists for operator
friendliness (the DA-revision pass: "B2 friendly remediation before runner
enforces"):

1. A newly-authored spec that forgot `derived_from:` is the most common
   R8(a) violation. Catching it at the skill layer surfaces a clean REFUSE
   envelope with a resolution hint ("add `derived_from: null` to
   `src/platform/specs/<id>.yaml` and re-run") instead of an
   `R8ViolationError` 10+ minutes into the per-window engine loop.
2. The skill writes `arcis_strategy.backtest.r8_violation` with the
   verbatim message, making the failure forensically queryable.
3. **`--quick` skips B2** — the in-sample path does NOT invoke
   `run_walkforward()`, so R8 is moot. Phase B9's `--quick` banner notes
   this explicitly.

## 3. Purging + embargo (R2) — López de Prado guarantees

Per `src/platform/rigor/walkforward_purging.py` (FA8):

- `purge_is_trades(is_trades, oos_start, oos_end)`
  (`walkforward_purging.py:82-114`) — drops every IS trade whose
  `[entry_date, exit_date]` interval overlaps `[oos_start, oos_end]`. A
  trade with `exit_date is None` is treated as still-open through the end
  of time and conservatively purged when `entry <= oos_end`.
- `embargo_oos_trades(oos_trades, oos_start, oos_end, embargo_days=5)`
  (`walkforward_purging.py:117-149`) — drops OOS trades whose entry falls
  within `embargo_days` trading days (Mon–Fri arithmetic per
  `_add_trading_days` at `walkforward_purging.py:68-79`; NOT
  NYSE-holiday-aware) of `oos_start`. Default `embargo_days=5`.
- Citation: López de Prado 2018 §7.4, noted inline at
  `walkforward_purging.py:129-130`.

Both run INSIDE `walkforward_runner.process_window()` at
`walkforward_runner.py:169-175` (purge 169-171; embargo 172-175). The
skill does NOT invoke them directly — they are GUARANTEED-applied when
`run_walkforward()` is called. Phase B9's "Rigor guarantees by
construction" block surfaces this with literal "yes" / "5 trading days"
values, never paraphrased.

## 4. Point-in-time universe — survivorship-bias-free semantics

Per `src/platform/rigor/walkforward_universe.py` (FA10):

- `resolve_universe_as_of(as_of_date, db_path)`
  (`walkforward_universe.py:96-129`) returns sorted S&P 100 tickers
  membership-active on `as_of_date`. Membership semantics
  (`walkforward_universe.py:103-105`):

  ```
  added_date <= as_of_date AND
  (removed_date IS NULL OR as_of_date < removed_date)
  ```

  Source of truth: `data/reference/sp100_historical.csv` (curated from
  S&P Dow Jones Indices press releases + Wikipedia index-change tables;
  `walkforward_universe.py:9-12`). Loaded into
  `sp100_historical_constituents` via `populate_constituents_table()`
  (`walkforward_universe.py:71-93`); resolver is offline-deterministic.

The skill passes the resolved size via `effective_universe_size` to
`run_walkforward()` (Phase B7); B9 surfaces it as `point-in-time S&P 100
at first OOS start, per FA10`. No look-ahead — composition is what was
tradeable on the OOS-start date, not today's roster.

## 5. Three-state outcome reducer

Per `walkforward_runner.reduce_outcome` call at
`walkforward_runner.py:304-314`: `outcome_state ∈ {PASS, FAIL,
INCONCLUSIVE}` plus textual `reason` and window-breakdown counts
(`n_windows_pass`, `n_windows_fail`,
`n_windows_inconclusive_{data,power,duration}`).

The skill PRESERVES the literal `outcome_state` verbatim through:

- `arcis_strategy.backtest.completed` audit event params (Phase B9).
- Phase B9 operator-facing report's `OUTCOME_STATE:` line.
- The `walkforward_results.outcome_state` DB column (written by
  `persist_run_result()`; surfaced at `walkforward_runner.py:372`).
- `arcis_strategy.analyze.completed` audit event params.
- Phase AN5 operator-facing report.

NEVER collapsed to a boolean. NEVER summarized as "passed" / "failed"
without the literal three-state token. `INCONCLUSIVE` is a first-class
outcome — its sub-reason (`data | power | duration`) is surfaced with the
actionable interpretation ("re-run with more universe history / longer
windows / larger position sizing where appropriate").
