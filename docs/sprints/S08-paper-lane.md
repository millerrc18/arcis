# S08-paper-lane — Step P: three-account paper execution experiment

Branch: `feat/s08-paper-lane`. Follows S07 (PR #11, merged at `4ba0f04`).

Status: in progress.

## Goal

Build the Step P paper trading lane (SCOPE §5, D-017): three Alpaca paper
accounts running the frozen incumbent's signals with identical selection
but different execution, to calibrate the slippage buffer and validate
D-020. Done when: all three accounts execute the same signals daily;
fills are recorded with quality metrics; the buffer calibration analysis
runs; D-020 validation report is generated.

## CEO decisions feeding this sprint

- **Three paper accounts APPROVED** (2026-10-05): same frozen selection,
  only execution varies. Value = slippage-buffer calibration + D-020
  validation, NOT edge discovery.
  - **A**: prereg baseline including D-020 (limit = signal close,
    open+buffer fills)
  - **B**: market-on-open entries (no limit, buy at open)
  - **C**: alternate adverse buffer (2x the R06 conservative buffer)
- **D-029 (PENDING):** Entry limit price rule. Recommended default:
  limit = signal-day close. Account A uses this default.
- **D-031 (ADOPTED 2026-10-06):** Recovered trend_state and
  relative_strength_state classifiers from the legacy archive. Full 5+5
  label vocabularies; unlisted labels score 0. Signal generation uses the
  complete incumbent scoring (was numeric-only).

## What is preregistered and implementable

Per PREREG §2.2 (Stage B):
- Paper P&L is visible to the operator but never a scheduled look.
- Execution fidelity is measured: fill rates, slippage vs. signal,
  buffer adequacy.
- D-020 validation: do open+buffer fills match the preregistered rule?

## Design

### Accounts
Three Alpaca paper accounts (separate API keys):
- `ARCIS_PAPER_A`: baseline (D-020)
- `ARCIS_PAPER_B`: market-on-open
- `ARCIS_PAPER_C`: 2x buffer

### Daily flow
1. **Signal generation** (pre-market): run frozen incumbent on prior
   close; emit candidate list (symbol, limit, stop, target, shares).
2. **Order placement** (market open): for each account, translate
   signals to orders per the account's execution rule.
3. **Fill monitoring** (intraday): poll for fills; record fill price,
   time, quantity vs. signal.
4. **EOD reconciliation**: compare fills across accounts; compute
   slippage metrics; update calibration analysis.

### Fill quality metrics
- Fill rate (% of signals filled)
- Slippage (fill price vs. signal price, in bp)
- Buffer adequacy (% of fills within buffer)
- D-020 compliance (% of open+buffer fills matching the rule)

## Out of scope

- Real money (no live keys, D-017).
- Edge discovery (selection is frozen; this is execution calibration).
- Live sizing (fixed notional per trade).

## Acceptance

- All three accounts place orders from the same signal list daily.
- Fill records include price, time, quantity, and slippage vs. signal.
- Buffer calibration report shows whether the R06 buffer is adequate.
- D-020 validation report shows compliance rate.
- No real-money API keys in the repo or logs.

## Results

(TBD)
