# Strategy Roadmap — Future-Sprint Spec

**Status:** draft spec (Cleanup Sprint 3 — not yet implemented)
**Author context:** 2026-04-20 audit strategic item #2
**Source docs:** `docs/sprints/cleanup_sprint_3_evaluation.md` §Spec-2, `docs/sprints/cleanup_sprint_3_research.md` §Spec-2, `docs/research/Strategy_2_Selection__Mean_Reversion_Wins.md`, `docs/research/PEAD_for_SP100__The_Drift_Evolved.md`, `docs/decisions/002-strategy-3-evolved-pead.md`, `docs/research/The_Halcyon_Framework_v2__Multi-Strategy_Architecture_and_Operating_Playbook.md`

## 0. TL;DR — scope pivot from the sprint prompt

The Cleanup Sprint 3 prompt framed this as "pick a second strategy from
{momentum-breakout, PEAD, STMOM, overnight/intraday tug-of-war}" but
the operator has **already made strategy decisions**:

- **Strategy 1** (incumbent, live): pullback-in-uptrend
- **Strategy 2** (selected 2026-03): short-term mean reversion
  (Connors RSI(2), VIX-conditional sizing) — ranked #1 of 6 candidates
  by composite score 32 in `Strategy_2_Selection__Mean_Reversion_Wins.md`.
  **Partial implementation exists** (`src/services/mr_scan_service.py`).
- **Strategy 3** (selected 2026-03-28 via ADR-002): evolved PEAD
  (composite earnings-information system, not classic single-signal
  drift). **Not yet implemented.**

This spec therefore has two tracks:

- **Track A — Strategy 2 implementation audit:** verify the existing
  mean-reversion scan matches the research spec, file gaps.
- **Track B — Strategy 3 (evolved PEAD) implementation spec:** ground-
  up design, ready for a future Ralph-Loop sprint.

A short **Track C** at the end notes the prompt's 4-candidate list
maps to a **Strategy #4** discussion that the operator can open
separately if desired.

## 1. Why this spec exists

2026-04-20 audit finding: "range_bound + ATR brackets loses in every
non-benign regime." Current live strategy (pullback) stress tests at
0% win rate across 2008 / 2011 / 2018Q4 / 2020 COVID / 2022 bear /
2015 China deval / 2024 yen unwind. A second uncorrelated strategy
reduces portfolio variance by ~50% (per the strategy-2 selection doc's
mathematical case vs. expanding from 100 → 325 tickers with the same
strategy, which reduces variance by only ~1.6%).

**Goal:** Strategy 2 implementation fully matches the research spec;
Strategy 3 (PEAD-evolved) is spec-ready for Ralph-Loop dispatch.

---

## 2. Track A — Strategy 2 (mean reversion) implementation audit

### 2.1 Canonical signal spec (from `Strategy_2_Selection__Mean_Reversion_Wins.md`)

Entry (all of Layer 1, Layer 2, and at least the recommended Layer 3 filters):

- **Layer 1** (required): RSI(2) < 5. Connors validated on hundreds of thousands of S&P 500 trades with >70% win rate.
- **Layer 2** (required, at least one of): Bollinger Band(20, 2) lower-band touch; Z-score of 5-day returns < −2.0; Connors RSI (3, 2, 100) < 10.
- **Layer 3** (quality filter, recommended):
  - **Exclude** stocks with: negative earnings surprise recent quarter (PEAD-filter), price > 15% below 200-day SMA (genuine breakdown), pending binary events (FDA / M&A), sector ETF below 50-day SMA.
  - **Include** stocks with: multi-quarter positive SUE trend (Kaczmarek-Zaremba filter), above-average institutional ownership, capitulation-signature volume (≥1.5× 20-day average volume on the down move).

Exit:

- **Primary:** close position when RSI(2) crosses above 65 **OR** price closes above 5-day SMA (Connors' validated optimal for large-caps).
- **Regime:** if VIX drops below 15 during hold, tighten to RSI(2) > 50 or first profitable close.
- **No percentage stop-losses** — Connors showed they damage mean-reversion performance (deeper oversold = higher expected return). Honor time-based stops only.

Sizing:

- **VIX > 25**: +25% MR allocation, funded by reducing pullback allocation.
- **VIX < 15**: −25% MR allocation.
- Supports Nagel (2012): reversal returns scale linearly with volatility.

Data additions on top of existing pipeline:

- RSI(2), Connors RSI (3, 2, 100), Bollinger Bands (20, 2), Z-score of 5-day returns — trivial additions to `src/features/`.
- Earnings SUE (Financial Modeling Prep or Alpha Vantage) — ~$30–50 / month API cost.

### 2.2 Implementation status

Known to exist (Sprint 2 touched `mr_scan_service.py` for pre-LLM BP check):

- `src/services/mr_scan_service.py` — entry path for MR
- `src/features/mean_reversion.py` — referenced by mr_scan_service (`scan_for_mr_candidates`)
- `config/settings.local.yaml` — MR config under `strategies.mean_reversion`

Not yet verified (this audit's job):

- Does `mean_reversion.py` compute RSI(2) < 5 with the exact Connors parameters?
- Does it apply Layer 2 confirmation (at least one of Bollinger / Z-score / Connors RSI)?
- Does it implement Layer 3 quality filters (PEAD-filter, 200-SMA threshold, capitulation volume, institutional ownership)?
- Does exit-management enforce the RSI(2)>65 / 5-day SMA exit with no percentage stop?
- Does sizing apply VIX-conditional allocation shifts between pullback and MR?

### 2.3 Audit sprint structure (proposed Sprint A)

Pass 1 (eval): read `src/features/mean_reversion.py` + `mr_scan_service.py` + related config; map each of the 5 questions above to "implemented / partial / missing / incorrect." Produce a gap report.

Pass 2 (research): decide for each gap whether it's a Sprint-level fix or a larger refactor. Confirm data-source availability (Finnhub for earnings surprise, existing collectors for Bollinger / RSI / Z-score).

Pass 3 (implementation): close each gap in a separate commit per guardrail. Add regression tests per feature signal.

### 2.4 Go/no-go gates for Track A completion

1. All 5 questions in §2.2 answered "implemented" with evidence.
2. Walk-forward backtest Sharpe > **0.5 net** on 2022-2024 holdout (Harvey-Liu-Zhu threshold).
3. Paper-trading realized correlation with pullback **< +0.20**.
4. Paper-trading drawdown **> −15%** over ≥ 30 trading days.

### 2.5 Estimated implementation

- If gaps are small (Layer 2 confirmation missing, Layer 3 filters incomplete): **1 sprint**.
- If gaps include the sizing logic or require Finnhub earnings-data integration: **2 sprints**.

---

## 3. Track B — Strategy 3 (evolved PEAD) implementation spec

### 3.1 Why classic PEAD is not the answer

Per `PEAD_for_SP100__The_Drift_Evolved.md`:

- **Martineau (2022, Critical Finance Review)**: large-cap PEAD non-existent since ~2006 (decimalization + Reg NMS eliminated arbitrage friction).
- **Subrahmanyam (2025, SSRN)**: earnings drift factor t-stat with all stocks = 2.18, but drops to 1.43 (insignificant) when excluding microcaps. Recent "PEAD is back" papers (Dickerson et al. 2025, Hirshleifer-Peng-Wang 2025 RFS) are **contaminated by microcaps** (3% of market cap but numerous).
- **Implication:** "PEAD on the EPS number" is dead for S&P 100. "PEAD on the information package" — historical earnings trajectories, text signals, revenue concordance, and guidance revisions — is alive.

### 3.2 Sub-signal architecture — 4-way composite

| Sub-signal | Expected contribution | Evidence |
|---|---|---|
| **12-quarter elastic-net SUE** | Sharpe 0.34 → 0.63 solo | Kaczmarek & Zaremba 2025, Finance Research Letters |
| **Text-based SUE.txt (earnings-call NLP)** | 8.01% drift / 63 days solo | Meursault, Liang, Routledge, Scanlon 2023, JFQA |
| **Revenue-EPS concordance** | +0.25% quarterly (concordant hedge portfolio) | Jegadeesh & Livnat 2006 |
| **Analyst revision velocity** (days 1–5 post-earnings) | incremental | Earnings-call rapid-response literature |
| **Multi-signal composite (recommended target)** | **Sharpe 0.9–1.3 est.** | Supported by multiple papers above |

### 3.3 Data needs

Existing:
- Finnhub `company_earnings()` endpoint → actual vs. estimate vs. surprise for S&P 100. Adequate given analyst-coverage convergence.
- Earnings calendar: already integrated per `docs/research/Event_Calendar_Integration_for_SP100_Pullback_Trading.md`.

New:
- Historical consensus snapshots (for backtest fidelity) — Finnhub lacks this. Workaround: point-in-time SUE from Financial Modeling Prep snapshots or I/B/E/S. **Open question:** does the operator have I/B/E/S access? If not, FMP is the backtest-feasible fallback.
- Earnings-call transcripts (for SUE.txt) — Finnhub provides transcripts; Koyfin and AlphaSense are paid alternatives.
- Analyst revision feed (for velocity signal) — Finnhub `company_revenue_estimates()` and adjacent endpoints.

Estimated incremental API cost: **$30–100 / month** on top of existing Finnhub spend.

### 3.4 Implementation path

New modules (spec-level):

- `src/features/pead_signals.py` — compute SUE composite, SUE.txt NLP scores, concordance, revision-velocity.
- `src/services/pead_scan_service.py` — parallel to `mr_scan_service.py` and `universe_scanner.py`; fires on earnings-adjacent windows (T−1 / T+1 / T+2 / T+5 post-earnings).
- `src/training/pead_elastic_net.py` — offline elastic-net training for 12-quarter SUE weights; re-fit quarterly.
- Schema additions: `pead_signals` (per-ticker time-series), `pead_scans` (per-earnings-event snapshots). Register via `src/schema/registry.py`.

Integration points:

- `strategy_registry` row with `strategy_id='pead_evolved'`.
- Promotion flow via `src/platform/promotion.py` (existing).
- Risk-governor wiring: Strategy 3 shares the global kill-switch + daily-loss + BP caps but gets its own `max_positions` and `max_position_pct` under `config.live_trading.strategies.pead_evolved`.

### 3.5 Go/no-go gates for Track B

1. Walk-forward Sharpe > **0.9** on 2022-2024 earnings-event holdout (per research doc's 0.9–1.3 target).
2. Correlation with Strategy 1 (pullback) **< +0.20** on overlapping trading days.
3. Correlation with Strategy 2 (MR) **< +0.25** on overlapping trading days.
4. Elastic-net out-of-sample R² **> 0.02** (per Kaczmarek-Zaremba baseline).
5. SUE.txt NLP component shows ≥ 3% drift on 2023–2024 earnings events (de-rating the paper's 8% to account for market adaptation).

### 3.6 Estimated implementation — 3 sprints

**Sprint B.1 — Data + signals** (~1 week): Finnhub integration for earnings transcripts + revisions; `pead_signals.py` with 12Q elastic net + concordance + revision velocity; SUE.txt NLP pipeline.

**Sprint B.2 — Scan service + backtest harness** (~1 week): `pead_scan_service.py`; walk-forward backtest (2022-2024); gate evaluation per §3.5.

**Sprint B.3 — Paper trading + promotion** (~1 week): strategy_registry row + promotion flow; paper trading for 30 days; post-paper gate review.

---

## 4. Track C — Strategy #4 candidate discussion (acknowledgement only)

The Cleanup Sprint 3 prompt listed 4 candidates under Spec 2:

| Prompt candidate | Mapping |
|---|---|
| Momentum-breakout | **Not in the 2026-03 6-candidate eval.** Closest analog "sector rotation" ranked #3 with +0.30–0.50 correlation with pullback — diversification-killer. Fresh candidate; may be the operator's new question. |
| PEAD | **Already selected as Strategy 3.** Covered by Track B. |
| STMOM (Medhat-Schmeling short-term momentum) | Cited in `ARCIS_RESEARCH_FRAMEWORK.md` as Dai-Medhat et al. 2024 reversal-dynamics reference — **not** as a separate strategy. Could be a fresh Strategy #4 candidate. |
| Overnight / intraday tug-of-war | In the 6-candidate eval as "overnight returns," ranked #4 / composite 20, flagged as +0.15 to +0.30 correlation with pullback (Lou-Polk-Skouras 2019 showed all momentum alpha is overnight). Already evaluated and deprioritized. |

**Recommendation for operator:** if Strategy #4 discussion is genuinely
open, file a separate evaluation doc (similar shape to
`Strategy_2_Selection__Mean_Reversion_Wins.md`) scoring candidates
across the same 5 dimensions (decorrelation, evidence, complexity,
data, training feasibility). Momentum-breakout and STMOM are the
novel entrants vs. the 2026-03 evaluation.

**This spec does not recommend starting Strategy #4 work until Strategy
3 (PEAD) is in paper trading.**

---

## 5. Schema fit — does it work in the current (post-C.1) schema?

Yes, with minor additions:

- `strategy_registry` exists and already supports multi-strategy.
- `shadow_trades.strategy_type` column exists — already used by `mr_scan_service` (writes `'mr_oversold'`) and pullback path.
- New: `pead_signals`, `pead_scans` tables to be added via `src/schema/registry.py`.
- New: `strategies.pead_evolved.*` config block under `config/settings.local.yaml`.
- No schema migrations of existing tables required.

---

## 6. Dependencies

- **Already satisfied:** C.1 schema refinements (merged), 2024 OHLCV backfill (merged), strategy_registry + `src/platform/promotion.py` (existing).
- **External API access:** Finnhub already integrated; SUE requires confirmation FMP or I/B/E/S access is available (open question for operator).
- **Future sprint chain:** does not block or get blocked by Sprint F/G/H (#530 chain).
- **Cross-spec:** Track A's backtest rigor matches the v0.25.x walk-forward framework (already in place).

## 7. Decision points for operator at sprint-dispatch time

1. **Track A vs Track B priority:** which ships first? Recommendation: **Track A first** — Strategy 2 is live in partial form; closing its spec gaps is lower-risk and establishes the "mr_scan_service matches its research spec" bar before building Strategy 3.
2. **Track B data strategy:** I/B/E/S (expensive, best fidelity) vs FMP snapshots (cheaper, good enough for 2022+ backtests). Operator decides based on cost tolerance.
3. **Strategy #4 scope:** defer (recommended) vs. open a Strategy #4 selection doc now. If opening, fresh candidates are momentum-breakout and STMOM (both absent from the 2026-03 6-way eval).
4. **Sizing rules:** the 6-candidate doc proposes "+25% MR when VIX > 25, funded from pullback." With Strategy 3 joining, operator needs a risk-budget policy across 3 strategies. `docs/research/Risk_Budgeting_for_3-Strategy_Equity_System.md` exists — spec'd but not implemented.

## 8. Out of scope — filed separately

- Risk-budget policy across N strategies — referenced research doc exists; spec separately.
- Dashboard multi-strategy UX — currently shows pullback trades primarily; multi-strategy view is a dashboard sprint not a trading sprint.
- Options overlay strategies — `docs/research/AI-Powered_Options_Trading__From_First_Principles_to_Production_Architecture.md` suggests this is a Phase 4+ topic, out of scope.

## 9. Success criteria

**Track A:**
- `mr_scan_service` and `mean_reversion.py` provably match each numbered item in §2.1.
- Paper trading Sharpe > 0.5 and correlation with pullback < 0.20 over 30 days.
- `strategy_registry` row for mean reversion shows `status='shadow_trading'` or better.

**Track B:**
- `pead_scan_service` produces trade signals on S&P 100 earnings events.
- Walk-forward Sharpe > 0.9 on 2022-2024 holdout.
- Correlation with Strategy 1 < 0.20 and with Strategy 2 < 0.25 on overlapping days.
- `strategy_registry` row for PEAD shows `status='shadow_trading'` after paper-trade gate pass.

## 10. Next CC sprint prompts (shape-only)

- **CC Sprint A:** "Audit `mr_scan_service.py` and `mean_reversion.py` against `Strategy_2_Selection__Mean_Reversion_Wins.md` §Entry/Exit/Sizing. Close gaps via separate commits; add regression tests per signal layer."
- **CC Sprint B.1:** "Build `src/features/pead_signals.py` implementing the 4-way PEAD composite per `PEAD_for_SP100__The_Drift_Evolved.md`. Data source Finnhub for transcripts + SUE; SUE.txt NLP via stdlib + existing text-processing helpers."
- **CC Sprint B.2:** "Build `src/services/pead_scan_service.py` and walk-forward backtest harness; gate per §3.5."
- **CC Sprint B.3:** "Register `pead_evolved` strategy in strategy_registry and route through `src/platform/promotion.py`; paper-trade 30 days; post-paper gate review."

Pass-3 spec file ends here.
