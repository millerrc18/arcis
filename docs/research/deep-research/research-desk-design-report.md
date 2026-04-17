# Arcis Phase 2 Research Desk — Design and Weekend Build Spec

The Research Desk should trade **filing-anchored earnings drift** on 14–28-day holds, driven by LLM-extracted year-over-year changes in 10-K/10-Q text combined with a multi-quarter ML earnings-surprise signal. This captures alpha that the swing desk provably does not — not another flavor of mean reversion, but a slow fundamental drift that rides post-announcement information diffusion. The swing desk's +0.039% per-trade excess over SPY with t=0.098 is a direct diagnosis: 3–8 day holds of high-beta names produced SPY beta, not alpha. The research desk attacks a different market inefficiency with a 3–5× longer holding window, a separate Alpaca paper account for clean attribution, and an 8B LLM doing structured extraction — the one thing an 8B model actually does well. Build target for the April 19–20 weekend: the skinniest functional path that can route one desk-tagged trade to the second paper account with a real SPY-excess number attached.

## 1. What the Research Desk is and why it is different

**Alpha source: "Lazy Prices" drift plus revived PEAD in large-caps.** The research desk captures two overlapping, well-evidenced post-2020 effects:

- **Cohen, Malloy, and Nguyen, "Lazy Prices" (Journal of Finance, 2020)** — year-over-year changes in 10-K and 10-Q language, especially in Risk Factors and MD&A, produce a Fama-French 5-factor alpha of **~188 bps/month (t = 2.76)** on a long-non-changers / short-changers portfolio. The paper documents **no announcement-day effect**; returns accrue slowly over weeks as subsequent earnings and news confirm the textual change. This drift window is a near-exact match for a 14–28 day hold.
- **Kaczmarek and Zaremba, "Beyond the Last Surprise" (Finance Research Letters, 2025, DOI 10.1016/j.frl.2025.108751)** — machine-learning use of SUE from the prior 12 quarters nearly **doubles Sharpe ratios** vs one-quarter SUE, and the alpha **is strongest in large-cap stocks where recent surprises are priced quickly but older ones are ignored**. This reverses Martineau 2022's "Rest in Peace PEAD" obituary for the specific regime we're trading.
- **Supporting: Meursault et al. 2023 SUE.txt** — text-based PEAD from earnings call language that is "considerable even in recent years when classic PEAD is close to 0."

**Why this is uncorrelated with the swing desk.** Pullback-in-uptrend is a price-based mean-reversion trade where returns correlate tightly with short-horizon market beta. Lazy Prices + ML-SUE are **event-driven fundamental drift**: the signal originates in a filing or earnings event, not in price action, and the hold window is deliberately long enough for fundamental information to diffuse rather than for market beta to dominate. Any remaining SPY beta is neutralized in attribution by computing per-trade excess over a matched-window SPY return.

**Why not the alternatives.** Connors RSI(2) is rejected outright — it is mean reversion with a different entry filter but the same underlying alpha source as swing, so it would cannibalize allocation rather than diversify it. Pure cross-sectional value requires 6–18 month holds; at 1–2 trades/week the system would never accumulate enough independent observations. Sector rotation is mostly price-based momentum — the LLM adds little and SPY beta dominates. Pure Quality/QMJ (Asness-Frazzini-Pedersen) still shows long-run alpha in large-caps, but **2024–2025 was a poor period for quality** (AQR's own data, confirmed in Oakmark's Q4-2025 commentary), and momentum loadings overlap with swing. Event-driven insider buying is viable but narrower — Huang-Lin-Zheng 2022 show only **opportunistic** (non-routine, Cohen et al. 2012 classification) insider buys predict returns in recent data, at +0.57% per σ — worth carrying as a secondary filter, not as the core strategy.

## 2. Recommended strategy with specific parameters

**Entry signal — two independent triggers, either fires:**

1. **Filing-change trigger (primary).** On any 10-K/10-Q filing, compute cosine similarity of Risk Factors and MD&A sections vs the prior-year filing. Stocks in the **bottom quartile of similarity** (largest text change) on a **bearish** direction classifier flag SHORT; **top quartile non-changers** after a positive earnings surprise flag LONG. (Cohen-Malloy-Nguyen found both directions work; long-non-changers is the cleaner leg for a long-biased paper account.)
2. **ML-SUE trigger (secondary).** Within 5 trading days of an earnings announcement, if the Kaczmarek-Zaremba-style elastic-net over the last 12 quarters of SUE places the stock in the **top decile of predicted 63-day forward return** AND the current-quarter SUE is positive, flag LONG. Use a simple elastic-net on 12 quarters of standardized SUE + the last 3 quarters of revenue surprise + analyst revision net-up ratio — this is buildable in an afternoon with scikit-learn on historical Compustat/FMP data.

Either trigger passes if mechanical; **the LLM is required to produce a non-disqualifying research note before the order fires** (schema in section 3). If the LLM flags `disqualifiers: ["numerical_unverified"]` or fails the quote-grounding audit, the trade is skipped and logged.

**Universe: S&P 500**, not S&P 100. Rationale: at S&P 100 the system will see only ~5–8 qualifying signals per month; expanding to S&P 500 quadruples opportunity flow without exceeding FMP's 250 req/day cap if fundamentals are cached daily and the scanner only re-pulls filings on event days. Avoid Russell 1000 for now — microcap noise contaminates PEAD evidence (the entire Martineau vs Subrahmanyam debate turns on microcap inclusion).

**Hold period: 14–28 days, target 21.** Cohen-Malloy-Nguyen's drift runs over weeks, not days. Garfinkel-Hribar-Hsiao 2024 find the CNN-based PEAD effect accrues over a 63-day post-announcement window. 21 trading days is the sweet spot — long enough to escape the swing desk's SPY-beta trap, short enough that signal doesn't decay and that 1–2 trades/week yields enough independent observations per year.

**Position sizing and brackets (ATR-based, matches Section 4 of the attribution analysis):**

| Parameter | Value |
|---|---|
| Position size | 10–15% of research desk equity, max 5 concurrent |
| Stop-loss | entry − 3.0 × ATR(14d), floor 5%, cap 12% |
| Profit target | entry + 6.0 × ATR(14d), floor 10%, cap 25% |
| Timeout | force-close day 25 regardless of P&L |
| Trailing | activate at +4 × ATR, chandelier at high − 2.5 × ATR |
| ATR%/price filter | accept only if 1.0% ≤ ATR/price ≤ 6.0% |

**Exit logic to escape the SPY-beta trap.** Every trade logs `excess_spy_bps = (exit_px/entry_px − spy_exit/spy_entry) × 10_000` using SPY total-return closes matched to the exact holding window. The desk's success metric is **annualized excess-Sharpe**, not raw Sharpe. A trade that made money because SPY ripped is explicitly counted as zero alpha.

**Honest Sharpe target.** Post-cost retail realization of Lazy Prices is typically 40–60% of the paper alpha — call that 0.5–0.8 annualized excess-Sharpe after slippage. ML-SUE adds ~0.1–0.2 in the large-cap regime Kaczmarek-Zaremba document. **Target: annualized excess-Sharpe of 0.6–1.0.** Anything above 1.5 would be extraordinary and almost certainly overfit.

## 3. LLM role and output format

**The LLM does one job well: structured extraction and classification of SEC filings and earnings-call text, anchored to quotable evidence.** Every "creative" task — target prices, multi-document synthesis, competitive analysis — is rejected as theater at the 8B scale. Kang & Liu (arXiv 2311.15548, 2023) and FinanceBench document 20–41% hallucination rates on numerical finance queries from small-to-medium LLMs. Lopez-Lira and Tang's result that GPT-4 news-forecasting ability rises with model size is a direct warning: treat Qwen3 8B as a disciplined paralegal, not an analyst.

**Three tasks, in order of evidentiary strength:**

1. **10-K/10-Q YoY diff extraction** (Lazy Prices, high confidence). The cosine similarity is mechanical; the LLM's job is classifying *what* changed (supply-chain, litigation, regulatory, competition, guidance language) and *severity* (hi/med/lo), with a verbatim quote ≤140 chars.
2. **Earnings-call tone shift vs prior call** (medium confidence). Not absolute sentiment — that's a solved FinBERT problem. Classify only whether guidance softened, held, or raised, with one verbatim quote. Mosbach et al. (*ACM TMIS* 2024) show Llama-3-8B class of models match or beat FinBERT on exactly this kind of short-context classification after minimal tuning.
3. **News synthesis to 14-day directional bias** (medium, decaying confidence). Aggregate Finnhub news from last 14 days into bullish / bearish / mixed / thin. Short context, schema-constrained output.

**Output format — strict JSON, never prose:**

```json
{
  "ticker": "AAPL", "as_of": "2026-04-19T18:00:00Z",
  "filing_anchor": {"form":"10-Q","accession":"...","filed":"2026-04-18"},
  "thesis_direction": "long|short|neutral",
  "conviction": 0.0-1.0,
  "horizon_days": 21,
  "yoy_diff": {"risk_factors_changed": true,
               "risk_delta_topics": ["supply_chain"],
               "mdna_tone_shift": "negative|neutral|positive",
               "cosine_sim_to_prior": 0.87},
  "earnings_tone_shift": {"vs_prior_call":"softer_guide|in_line|raised",
                          "evidence_quote":"≤140 chars verbatim"},
  "news_bias_14d": "bullish|bearish|mixed|thin",
  "thesis_justification": "≤400 chars, must quote filing_anchor",
  "disqualifiers": []
}
```

**Non-negotiable guardrails:** no target prices, no bull/bear probability distributions, and every `thesis_justification` must contain a substring that exists verbatim in the anchored filing (automatic substring check rejects notes that don't). Permutation sanity test: feed a scrambled filing and confirm conviction drops — if it doesn't, the model is hallucinating from priors and the note is binned.

**Training data plan, phased.** Do not reuse the 1,782 pullback examples — task distribution is wrong and Kalajdzievski 2024 confirms small LLMs forget proportional to fine-tune steps. Phase 0 (launch): **base Qwen3-8B-Instruct with no fine-tune, strict JSON-mode with grammar-constrained decoding**, validated against 50 hand-labeled 10-K diffs. Phase 1 (weeks 2–6): **150–250 synthetic examples** generated by Claude/GPT-4 from real 2018–2023 10-Ks with known forward returns, with 100% human review. Train a LoRA adapter separate from the swing adapter — load by desk tag, never merge weights. Phase 2 (weeks 6–12): 500–800 real examples from live operation.

**Proving the LLM adds alpha, not theater.** Run a three-arm A/B: Arm A = mechanical Lazy-Prices cosine + Loughran-McDonald baseline; Arm B = mechanical plus LLM conviction sizing; Arm C = LLM fed with filing snippets redacted. Success = Arm B Sharpe exceeds Arm A by ≥0.3 with t > 2 over 60 trades, **and** Arm C Sharpe ≈ 0 (proves signal comes from the document, not LLM priors). Track the information coefficient of `conviction` vs realized 21-day returns; IC below 0.03 is theater.

## 4. Weekend MVP spec — 10-task plan, ~14 hours

**Code reuse verdict** for each component: scanner PARAMETERIZE, executor PARAMETERIZE, risk governor PARAMETERIZE (instantiate twice), journal PARAMETERIZE (ADD COLUMN `desk`), dashboard PARAMETERIZE (?desk= filter), config PARAMETERIZE (nested `desks.{swing,research}`), training data NEW dir, LLM prompt NEW template.

Alpaca confirmed: **up to 3 paper accounts per user**, distinct key pairs, identical base URL `https://paper-api.alpaca.markets`. Routing is purely by API key pair — create a `TradingClient` per desk and keep them in a dict keyed by desk tag.

| # | Task | File(s) | Signature / schema | Tests | Hrs |
|---|------|---------|--------------------|-------|-----|
| T1 | Config loader extension | `config.yaml`, `config_loader.py` | `load_desk_config(desk) -> DeskConfig` pydantic; keys `desks.{swing,research}.{alpaca_key_env, alpaca_secret_env, max_position_usd, max_hold_days, stop_atr_mult, benchmark}` | `test_config_loads_both_desks`, `test_missing_desk_raises` | 1.0 |
| T2 | SQLite migration | `migrations/001_add_desk.py` | `ALTER TABLE shadow_trades ADD COLUMN desk TEXT NOT NULL DEFAULT 'swing'; excess_spy_bps REAL; research_thesis TEXT; benchmark_price_at_entry REAL; benchmark_price_at_exit REAL` | `test_migration_idempotent`, `test_existing_85_tagged_swing` | 0.5 |
| T3 | Alpaca dual-client factory | `brokers/alpaca_clients.py` | `get_client(desk) -> TradingClient` module-level cache, reads env vars `APCA_SWING_KEY_ID/SECRET`, `APCA_RESEARCH_KEY_ID/SECRET`; each client has `desk_tag` attr | `test_client_per_desk_isolated`, `test_paper_base_url_enforced`, `test_missing_env_raises` | 1.0 |
| T4 | Scanner parameterization + research filter + ATR | `scan_service.py`, `scanners/research_filter.py`, `utils/indicators.py` | `scan(desk, cfg) -> list[Candidate]`, registry `SCANNERS={"swing":…, "research":…}`; research filter = filing event within 5 days AND cosine(10-K diff) below q25 OR ML-SUE decile ≥ 9; `atr(df, n=14)` helper | `test_scan_dispatches_by_desk`, `test_atr_matches_pandas_ta`, `test_research_rejects_outside_event_window` | 2.5 |
| T5 | Risk governor per-desk | `risk_governor.py` | `RiskGovernor(desk, cfg)`; registry `GOVERNORS={d: RiskGovernor(d, cfg.desks[d].risk) for d in desks}`; enforces per-desk caps + shared portfolio kill switch | `test_research_cap_half_of_swing`, `test_shared_kill_halts_both`, `test_ticker_crossdesk_conflict_rejected` | 1.0 |
| T6 | Executor desk routing + excess-SPY attribution | `executor.py`, `attribution/excess_spy.py` | `submit(order, desk) -> ExecReport` asserts `order.desk == client.desk_tag`; on fill records `benchmark_price_at_entry`; on close computes `excess_spy_bps`; `trade_excess(trade, spy_bars) -> (xr_bps, hold_days)` | `test_swing_never_hits_research_client`, `test_excess_spy_matches_manual_calc`, `test_overlapping_holds_not_double_counted` | 2.0 |
| T7 | Journal desk-aware writes | `journal/store.py` | `record_trade(desk, **fields)`, `query_by_desk(desk) -> list[Trade]`; INSERT covers new columns | `test_swing_defaults_desk_column`, `test_research_persists_thesis`, `test_query_by_desk_isolation` | 1.0 |
| T8 | LLM research commentary + Ollama caller | `prompts/research_commentary.j2`, `llm/ollama_client.py` | `generate_research_note(signal, desk, timeout_s=6) -> dict`; Qwen3-8B base, grammar-constrained JSON; substring-grounding check rejects notes whose `thesis_justification` quote is not in filing text | `test_prompt_renders`, `test_ollama_timeout_fallback`, `test_hallucinated_quote_rejected`, `test_schema_valid_json` | 2.0 |
| T9 | Async dual-desk scheduler | `main.py`, `scheduler.py` | `async def run_desk(desk)`; `asyncio.gather(run_desk('swing'), run_desk('research'), return_exceptions=True)`; swing ticks 60s, research ticks 600s staggered; per-tick heartbeat log | `test_both_tick_within_window`, `test_research_crash_swing_survives`, `test_staggered_intervals` | 1.5 |
| T10 | Dashboard filter + Telegram prefix | `dashboard/routes.py`, `dashboard/templates/index.html`, `notifications/telegram.py` | `GET /dashboard?desk=research\|swing\|None`; SQL `WHERE (:desk IS NULL OR desk = :desk)`; Telegram messages prefixed `[RESEARCH]` when `desk=='research'` | `test_default_shows_both`, `test_research_filter_hides_swing`, `test_telegram_prefix_only_research` | 1.5 |

Buffer: 1.0h for Alpaca auth surprises or migration issues. Total 14 hours.

**Day split.** Saturday AM (4h, foundation, must not touch live swing): T1 → T2 on db copy → T3 with live `get_account()` verification on research key → T5. Saturday PM (4.5h): T4 scanner + ATR + research filter → T8 LLM prompt + round-trip. Sunday AM (3.5h): T7 journal → T6 executor + attribution → T9 scheduler. Sunday PM (2.5h): T10 dashboard + Telegram → 3× end-to-end dry runs → go/no-go.

**Explicit deferrals (stub only):** fine-tuned research LoRA (use base Qwen3, collect data from live); custom research training examples (empty `data/training/research/` with README); dedicated `/dashboard/research` route (use `?desk=` for now); real-time cross-desk correlation monitor (log only, Jupyter notebook post-launch); separate Telegram channel (prefix only); backfill excess-SPY on the 85 historical swing trades (columns nullable, stay NULL).

**Sunday evening go/no-go:** (1) `get_client('research').get_account().status == "ACTIVE"` against the second paper account, with account number distinct from swing; (2) at least one trade in `shadow_trades` with `desk='research'`, non-null `excess_spy_bps`, and a non-empty `research_thesis`; (3) `SELECT COUNT(*) FROM shadow_trades WHERE desk='swing'` still equals 85 plus any Sunday swing trades (no regression); (4) `/dashboard?desk=research` hides swing rows and vice versa; (5) 3× dry runs where injected exception in research task does **not** stop swing; (6) pytest all green; (7) Telegram `[RESEARCH]` prefix works. Fail any of 1/2/3/5 → revert to Friday HEAD and retry next weekend.

**Top weekend risks.** (a) Alpaca client silently picks up env `APCA_API_KEY_ID` and mis-routes — mitigated by passing keys **explicitly** to `TradingClient(key, secret, paper=True)` and asserting `client.get_account().account_number` differs per desk before first order. (b) SQLite migration on live data — mitigated by running on `cp journal.db journal.db.bak`, idempotent script checking `PRAGMA table_info`, and using a constant `DEFAULT 'swing'` which makes the ALTER metadata-only. (c) Ollama cold-start spikes to 15s and blocks the 60s loop — `asyncio.wait_for(generate_research_note, timeout=6)`, persist `research_thesis="[LLM_TIMEOUT]"` on timeout, commentary is narrative not gating. (d) Desk tag leaks across clients — executor asserts `order.desk == client.desk_tag`, unit test is required-green in go/no-go.

## 5. Phase 2 gate — when the research desk has proven itself

Using Lo (2002) / Lopez de Prado's minimum track record length formula `SE(SR) ≈ sqrt((1 + SR²/2)/N)` per period, and translating annualized targets to per-trade Sharpe via `SR_per = SR_ann / sqrt(trades_per_year)` at 1.5 trades/week ≈ 75/year (sqrt ≈ 8.66):

| Target annualized excess-Sharpe | Per-trade SR | N for t > 2 | Calendar at 1.5/week |
|---|---|---|---|
| 0.5 | 0.058 | ≈1,190 | 15+ years (infeasible) |
| 0.75 | 0.087 | ≈530 | 6.8 years |
| **1.0** | **0.115** | **≈305** | **~3.9 years** |
| 1.5 | 0.173 | ≈135 | 1.7 years |
| 2.0 | 0.231 | ≈75 | ~1 year |

**Practical Phase-2 graduation gate:** N ≥ 30 trades **AND** per-trade t ≥ 1.65 (one-sided 95%) **AND** annualized excess-Sharpe point estimate ≥ 1.0. At 1.5 trades/week that's roughly **5–7 months of paper trading**. A "promote to live capital" gate demands N ≥ 60 trades and t > 2.0 — roughly **9–12 months**. Anyone promising statistical significance in under 6 months at this trade cadence is either lying or targeting an implausible Sharpe. Add a 30% N buffer if realized returns show visible skew/kurtosis (Mertens correction).

**Cross-desk correlation policy: soft-with-caps.** Per-ticker hard cap (one open position per ticker across both desks; second desk logs a blocked attempt), combined GICS sector cap of 35% of total equity, and a rolling 60-day desk P&L correlation check run nightly — if |ρ| > 0.6 for 10 consecutive days, halve the smaller desk's allocation until correlation drops. This mirrors pod-shop alpha-cannibalization guards without the bureaucratic overhead of hard no-overlap.

## 6. First-30-days monitoring plan

**Weekly metrics** (Sunday evening snapshot): trade count by desk; per-trade and annualized excess-Sharpe by desk with Newey-West-adjusted t-stat; average hold days; win rate and profit factor; **LLM contribution** = difference between Arm A (mechanical) and Arm B (LLM-gated) Sharpe on paper parallel arms; LLM disqualifier rate; LLM quote-grounding failure rate; FMP daily request utilization (must stay below 230/250).

**Daily automated checks** (run in the 09:00 ET pre-market loop): both Alpaca accounts return `ACTIVE`; research desk positions are all within their ATR-based stops (no hand-set stops drifted); no ticker is open on both desks simultaneously; kill-switch file state reconciles with DB.

**Failure modes and intervention triggers.** First, **LLM theater** — if after 20 trades the Arm B − Arm A Sharpe differential is negative or the conviction-vs-realized-return IC is below 0.03, strip the LLM gating, run mechanical-only, and treat the LLM as narrative color until the training corpus grows past 200 real examples. Second, **SPY-beta contamination** — if the per-trade excess-Sharpe is still hovering near zero after 30 trades and raw Sharpe is positive, it means 21-day holds are still exposing us to market beta on high-beta names; cap portfolio ex-ante beta at 1.0 and add a volatility filter rejecting names with 60-day beta > 1.4. Third, **correlation leak** — if 60-day desk correlation crosses 0.5, manually inspect whether the research desk is effectively long the same tech megacaps the swing desk is pulling back in; if so, exclude any ticker that had a swing signal in the prior 20 days. Fourth, **filing-scanner drift** — if the scanner is firing on >3 signals/day the Lazy Prices filter has probably gone too loose (the original paper's hedge portfolio is decile-based and therefore sparse); tighten cosine quartile from q25 to q10 and re-measure. Fifth, **Alpaca data inconsistency** — if SPY entry/exit prices logged by the executor diverge from yfinance adjusted closes by more than a few basis points, switch the attribution benchmark to yfinance adjusted close only and recompute.

**Month-1 reality check.** At 1.5 trades/week the research desk will produce roughly 6–8 completed trades in 30 days. That is not enough for statistical significance of any Sharpe estimate — don't try to declare victory or defeat on the number. What should be true at day 30: clean SPY-excess attribution on every closed trade, zero cross-desk tag leaks, LLM schema compliance above 98%, and the three-arm A/B producing a coherent first signal on whether the LLM is helping. Statistical judgment day is month 5–7.

## Bottom line

The Research Desk is a **filing-anchored earnings-drift strategy on 21-day holds**, riding Lazy Prices and revived ML-SUE evidence that specifically targets the large-cap regime the swing desk operates in without overlapping its alpha source. The **8B LLM earns its keep by doing structured YoY-diff extraction and tone classification with mandatory quote grounding** — not by writing narrative. The **weekend build is a skinny parameterization sweep**: same scanner, same executor, same risk governor, same journal — just with a `desk` column, a second Alpaca client, an ATR-based bracket set, and one new prompt template. **Excess-Sharpe vs SPY is instrumented from the first trade**, because the swing desk's t=0.098 is a standing reminder that raw returns on 3-to-30-day holds of US equities measure SPY beta by default. Statistical verdict arrives in month 5–7; anything earlier is storytelling.