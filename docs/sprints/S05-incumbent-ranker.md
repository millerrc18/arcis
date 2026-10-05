# S05 — Incumbent Ranker, Cost Model, Metrics

| | |
|---|---|
| **Branch** | `feat/s05-incumbent-ranker` |
| **Repository** | `millerrc18/arcis` (public). Market data stays under the data root; only aggregate statistics are committed. |
| **Depends on** | S04 merged (data plane audited). `config/incumbent_v1.yaml` frozen. S01 snapshots available. |
| **Ledger row** | None. This sprint produces a package (`src/arcis/ranker/`), not a standalone tool. |
| **Invariants** | I-7 data outside the repo and sync folders · I-12 no blind exception handling · I-16 nothing private and no market data in a public repo |
| **Runs** | After S04 (SCOPE §5 Step 4); Step 5 and Step P depend on it |
| **Tasks** | 7 |

## Why this sprint exists

Step 5 (simulator, harness) and Step P (paper lane) both need the ranker. The incumbent is frozen as `config/incumbent_v1.yaml` (hash `524dd858…`), but there is no executable implementation. This sprint builds it as a clean-room reimplementation from the YAML spec — not a port of legacy code.

The cost model (R06) and metrics module are also Step 4 deliverables per SCOPE §5. The cost model implements the dated-fee specification from the research log; the metrics module provides the known-answer-tested calculations that Step 5's harness will use.

## Hard scope

**In:** ranker scoring bands from `incumbent_v1.yaml`; sector RS 60/40 blend; regime adjustments; technical feature computation (SMA, RSI, ATR, volume ratio, pullback depth); R06 cost model (dated SEC/FINRA fees, spread proxies, execution costs); metrics module; point-in-time membership via S01 snapshots; known-answer tests for all.

**Out:** bracket simulator (Step 5); walk-forward harness (Step 5); trial registry (Step 5); paper lane (Step P); any text scoring (Q2/Q3); loading legacy code; changing the frozen incumbent definition.

If a task appears to need anything from **Out**, stop and write it up in the sprint report.

## Ground rules

1. **YAML is the spec.** The ranker implements `config/incumbent_v1.yaml` exactly. Any ambiguity in the YAML is documented as UNRESOLVED, not guessed.
2. **No legacy code.** Clean-room reimplementation. Do not read the legacy ranker source.
3. **Known-answer tests.** Every scoring band, every fee calculation, every metric has a test with a hand-computed expected value.
4. **Point-in-time.** The ranker uses only data available at `t_d`. Membership comes from S01 snapshots, not the current constituent list.
5. **S&P 100 vs S&P 500.** The incumbent was tuned on S&P 100 (D-012). The ranker implements the S&P 100 thresholds as specified; S&P 500 re-examination is out of scope.

## Artifacts this sprint produces

| Path | What it is |
|---|---|
| `src/arcis/ranker/` | Ranker package: scoring, features, regime |
| `src/arcis/costs/` | Cost model package: R06 implementation |
| `src/arcis/metrics/` | Metrics package: known-answer-tested calculations |
| `tests/test_ranker.py` | Ranker known-answer tests |
| `tests/test_costs.py` | Cost model known-answer tests |
| `tests/test_metrics.py` | Metrics known-answer tests |

---

## Tasks

### T1 — Scoring bands

Implement the ranking bands from `incumbent_v1.yaml`:
- `trend_state`: strong_uptrend→30, uptrend→20, neutral→5
- `relative_strength_state`: strong_outperformer→25, outperformer→15
- `pullback_depth_pct`: [-8,-3]→25, [-12,-8]→10 (order-sensitive, exclusive upper)
- `dist_to_sma20_pct`: [-5,-1]→10
- `volume_ratio_20d`: [null,0.8]→15 (sentinel lower bound)
- `iv_rank`: [null,25]→3
- `iv_rank_put_call`: conditions → -3
- Clamp final score [0, 100]

First-match-wins per metric. Document any ambiguity as UNRESOLVED.

### T2 — Sector RS blend

Implement the 60/40 market/sector RS blend:
- `weighted_excess = 0.20 * excess_1m + 0.50 * excess_3m + 0.30 * excess_6m`
- Band to 25 / 15 / 5 / 0
- When sector RS unavailable, market RS receives full weight

### T3 — Regime adjustments

Implement cumulative regime adjustments, clamped to [-10, 10]:
- calm_uptrend + healthy breadth → +5
- calm_uptrend + narrowing breadth → +2
- transitional → -3
- calm_downtrend → -5
- volatile_downtrend → -10
- SPY RSI14 > 75 → -3
- SPY RSI14 < 30 → +3
- volatile_uptrend → +0 (explicit no-op)

### T4 — Technical features

Compute from daily bars:
- SMA20, distance to SMA20 (%)
- RSI14 (Wilder's)
- ATR14 (Wilder's)
- Volume ratio (20-day)
- Pullback depth (% from recent high)
- 1m/3m/6m excess returns (vs SPY)

All with known-answer tests against hand-computed values.

### T5 — R06 cost model

Implement from research log §R06:
- **Dated SEC Section 31 fee:** rate by effective date; 0.206 bp from 2026-04-04; zero 2025-05-14 to 2026-04-03
- **Dated FINRA TAF:** 0.000195/share (2026, cap $9.79); 0.000166 (2024-2025); 0.000075 (2004-2011); zero before 2002-10-01
- **CAT fee:** 0.000003/share (both sides); zero until verified schedule
- **Commissions:** zero (modern); $5/$10 per order (historical sensitivity)
- **Spread proxy:** Corwin-Schultz and Abdi-Ranaldo from OHLC; central = max(tick floor, median); conservative = max(tick floor, larger)
- **Execution:**
  - Passive entry/target: strict trade-through (no separate adverse selection)
  - Marketable exit: 0.5 × spread + 0.25 bp (central) / + 1.0 bp (conservative)
  - Stop non-gap: 0.5 × spread + 0.5 bp (central) / + 2.0 bp (conservative)
  - Stop gap: add stop-to-open shortfall
- **Round-trip priors:** 2-6 bp central, 6-15 bp conservative (model settings, not measured)

### T6 — Metrics module

Known-answer-tested calculations:
- Sharpe ratio (annualized)
- Maximum drawdown
- Hit rate
- Profit factor
- Average win / average loss

### T7 — Point-in-time membership

- Load S01 universe snapshots
- Ranker accepts a membership date; uses only that date's snapshot
- Test: membership on 2024-01-02 differs from 2026-10-04 (or appropriate dates)

---

## Acceptance criteria

1. `src/arcis/ranker/` implements all scoring bands from the YAML.
2. `src/arcis/costs/` implements R06 with dated fees.
3. `src/arcis/metrics/` has all five metrics.
4. Every band, fee, and metric has a known-answer test.
5. All tests pass; all checks green.
6. No legacy code read or ported (clean-room).
7. YAML ambiguities documented as UNRESOLVED (not guessed).
8. Sprint report written in this file.

## After merge (Ryan)

1. Review the UNRESOLVED list. Decide if any block Step 5.
2. Proceed to Step 5 (S06: bracket simulator).

## Sprint report

**Status:** Code-complete; PR #7 opened. Fixture test reproduces `incumbent_v1` scoring end to end (SCOPE §5 Step 4 done-means for the ranker). Production use remains blocked on the UNRESOLVED items below — all fail closed rather than silently corrupting results.

**T1 (Scoring bands):** ✅ All bands from `incumbent_v1.yaml` implemented in `src/arcis/strategy/scoring.py`. First-match-wins, clamped [0, 100].

**T2 (Sector RS blend):** ✅ 60/40 blend implemented. `score_sector_rs` implements Set A absolute thresholds (D-026, 2026-10-05): ≥+5pp → 25, 0–+5 → 15, −5–0 → 5, <−5 → 0.

**T3 (Regime adjustments):** ✅ Cumulative adjustments, clamped [-10, 10]. Volatile uptrend explicit no-op.

**T4 (Technical features):** ✅ SMA, RSI14 (Wilder's), ATR14 (Wilder's), volume ratio, pullback depth, distance to SMA20, excess returns. All with known-answer tests.

**T5 (R06 cost model):** ✅ `src/arcis/research/costs.py`. Dated SEC/FINRA fees, CAT, commissions (modern + historical sensitivity), Corwin-Schultz and Abdi-Ranaldo spread proxies, execution costs by exit type.

**T6 (Metrics):** ✅ `src/arcis/research/metrics.py`. Sharpe, max drawdown, hit rate, profit factor, avg win/loss. All with known-answer tests.

**T7 (Point-in-time membership):** ✅ `src/arcis/strategy/membership.py` loads S01 snapshots by date.

**Packages:** `src/arcis/strategy/` (ranker), `src/arcis/research/` (costs, metrics). Ledger rows activated via PR #8 (merged to main before this PR, per SCOPE §6.2).

**UNRESOLVED (need CEO decision):**
- ~~`score_sector_rs` band thresholds not in YAML. Raises `UnresolvedError`.~~ RESOLVED 2026-10-05 by D-026 (Set A absolute thresholds).
- Pullback depth `[-8,-3]` upper bound: YAML silent on -3.0 inclusivity. Exact -3.0 raises `UnresolvedError`.
- `dist_to_sma20` [-5,-1], `volume_ratio` [null,0.8], `iv_rank` [null,25] upper bounds: YAML has no bound notes. Exact -1.0 / 0.8 / 25 raise `UnresolvedError` (consistent with -3.0).
- `trend_state` / `relative_strength_state` classification rules and full label vocabulary: not in YAML. The code scores only the YAML's point-bearing labels; unknown labels raise.
- Historical SEC rates before 2025-05-14: not verified; raise `UnresolvedFeeError`.
- Historical FINRA TAF rates for 2002-2003, 2012-2023, and caps outside 2026: not verified; raise.
- `lookback=60` for pullback high; 1m/3m/6m day counts: not in YAML.

**Deviations:**
- Package layout: spec said `src/arcis/ranker/`, `src/arcis/costs/`, `src/arcis/metrics/` with "Ledger row: None". Used existing `strategy`/`research` rows (PR #8) instead.
- Fail-closed: unknown rates/labels/ambiguous boundaries raise instead of silent defaults.
- CAT fee: zero per R06 (no invented schedule).
- FINRA TAF: 2026 cap $9.79 applied per R06; caps for other periods unverified (raise).
- 21-session median smoothing: not implemented (deferred).
- `score_incumbent` takes an explicit `sector_weighted_excess` (None = sector RS unavailable → market RS at full weight, per the YAML fallback). `market_breadth`/`spy_rsi` are required arguments; None means unknown → no adjustment for that component.

**Tests:** 227 total, all passing, 0 skipped (includes T7 membership test, fail-closed tests, composed ranker tests, fixture reproduction test, Wilder 41-bar and CS/AR known-answer tests).

**Artifacts:**
- `src/arcis/strategy/` — scoring, features, membership
- `src/arcis/research/` — costs (R06), metrics
- `tests/test_ranker.py`, `tests/test_costs.py`, `tests/test_metrics.py`
- `docs/sprints/S05-incumbent-ranker.md` (this spec)
