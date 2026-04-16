# Arcis Phase 6 intraday desk — feasibility study

**Intraday trading is feasible for Arcis at retail scale, but only via a narrow path: documented-edge strategies (ORB with stocks-in-play filter, intraday momentum, VWAP trend) on minute-bar cadence, with the LLM kept out of the hot path.** The literature supports realistic net Sharpe of 0.8–1.3 for disciplined, filter-gated strategies on S&P 100 names using Alpaca. Anything requiring sub-second decisions, Level 2 data, or LLM reasoning inside the order loop will not work at retail scale. The most promising minimum viable version is a single-strategy ORB desk trading 5–10 S&P 100 names/day, flat by 15:55 ET, with Qwen3 used pre-market for regime context only. The critical Phase 1 decision is **to begin storing 1-minute bars now** and to restructure today's 60-second poll loop around asyncio handlers — both preserve intraday optionality at near-zero cost. Phase 6 is realistically 9–12 months of calendar work from current state; total incremental capex is under $1,500 and monthly data costs stay under $200.

## Executive summary: what works, what doesn't, what to build first

The honest verdict: intraday desk is feasible as a **filter-gated, minute-bar-cadence system** — not as a scalping or microstructure desk. Three strategies have credible post-2020 academic support on liquid US equities: Zarattini-Barbon-Aziz (2024) **5-min ORB with "Stocks in Play" filter** (Sharpe 2.81 gross, ~1.2–1.8 net), Zarattini-Aziz-Barbon (2024) **SPY noise-boundary intraday momentum** (Sharpe 1.33 net), and Zarattini-Aziz (2023) **VWAP trend** (Sharpe 2.1 gross on QQQ, ~1.0–1.5 net). These are all compatible with 100ms+ latency and with a 2–4 second LLM inference budget, provided the LLM sits outside the execution path. Anything faster — scalping, Level-1 order flow imbalance, pure 5-min RSI/Bollinger mean reversion on liquid large-caps — has been arbitraged away or requires infrastructure Arcis cannot afford.

The **minimum viable version** is a single-desk ORB system trading 5–10 S&P 100 names with a daily relative-volume + news filter, one entry per name within the first 30 minutes, trailing ATR stop, and mandatory flatten at 15:55 ET. Qwen3-8B runs once pre-market to produce a structured JSON regime/sentiment/watchlist object the mechanical engine consumes. No LLM calls happen during the session. Data is **Alpaca Algo Trader Plus at $99/month** (full SIP, WebSocket, bundled with the brokerage), storage is **TimescaleDB** added alongside the existing Postgres, and execution is via **alpaca-py directly** with a thin asyncio event loop — not a third-party framework.

## Phase 1 architecture decisions to make now

Five decisions cost near-zero today and preserve every door; making the wrong choice here forces a painful rewrite later. **First, restructure the 60-second poll loop as an asyncio event loop with handler functions** (`on_daily_bar`, `on_fill`, `on_signal`) rather than top-down procedures. FastAPI is already async; the cost is one refactor, the benefit is that Phase 6 reuses the same process model. **Second, migrate from `alpaca-trade-api` to the modern `alpaca-py` SDK now** — its `TradingStream` and `StockDataStream` classes are the canonical intraday primitives and the legacy SDK is deprecated. **Third, begin storing 1-minute OHLCV bars for the S&P 100 universe starting now**, even if unused by current swing strategies; historical data costs money and forward-fill starts accumulating the moment you turn it on. At roughly 100 tickers × 390 bars/day × ~60 bytes, that's about 2.3 MB/day, 50 MB/month, 600 MB/year — trivial on local disk. **Fourth, add TimescaleDB as a sibling to Postgres rather than migrating SQLite** — it's a Postgres extension, not a replacement, and benchmarks show it delivers ~3.4× Postgres query speed on time-series with native compression giving 90%+ reduction after chunk aging. **Fifth, wrap all Alpaca calls behind a thin `BrokerClient` interface** (`submit_order`, `close_all_positions`, `stream_bars`) so the desk can later swap to Lumibot or nautilus_trader without touching strategy code.

Explicitly do **not** install nautilus_trader, QuantConnect LEAN, Kafka, Redis, or Kubernetes in Phase 1. asyncio.Queue handles 100-ticker fan-out fine at this scale; any message-broker infrastructure adds operational burden without proportional benefit until empirically justified by a concrete latency bottleneck.

## Strategy landscape for S&P 100 intraday at retail

| Strategy | Primary citation | Sharpe gross | Sharpe net (retail) | Holding period | Data required | Retail feasibility (1–5) |
|---|---|---|---|---|---|---|
| ORB 5-min, filtered (Stocks in Play) | Zarattini, Barbon, Aziz 2024 (SSRN 4729284) | 2.81 | 1.2–1.8 | Mins–hours; EOD flat | 1-min OHLCV + relative volume + news | **4** |
| Intraday momentum (SPY noise-boundary) | Zarattini, Aziz, Barbon 2024 (SSRN 4824172) | 1.50–1.80 | 0.8–1.1 | Intraday, trailing stop | 1-min OHLCV, 14-day ADR | **5** |
| VWAP trend (QQQ/SPY) | Zarattini & Aziz 2023 (SSRN 4631351) | 2.1 | 1.0–1.5 | Minutes–hours | 1-min OHLCV + cumulative volume | **4** |
| Market intraday momentum (first 30m → last 30m) | Gao, Han, Li, Zhou, *JFE* 2018 | CER ≈ 6%/yr | 0.5–0.8 | 30 minutes | 30-min returns | **5** |
| ORB 5-min, unfiltered universe | Zarattini, Barbon, Aziz 2024 | 0.48 | 0.3–0.5 | Mins–hours | 1-min OHLCV | **3** |
| OFI / microstructure without Level 2 | Cont-Kukanov-Stoikov 2014; Ha-Hu 2017 | 0.5–1.0 (w/ L2) | 0.2–0.5 | Seconds–1 min | Trade tape; ideally L2 | **2** |
| RSI / Bollinger mean reversion (5-min) | Vu & Bhattacharyya 2024; Heston et al. *JoF* 2010 | ~0.5 | 0.0–0.4 | 5–30 min | 5-min OHLCV | **2** |

Three structural insights emerge from this literature. **The filter is the edge, not the breakout** — Zarattini's 2024 paper shows indiscriminate 5-min ORB across all 7,000 US stocks yields Sharpe 0.48, while the top-20 Stocks-in-Play subset delivers 2.81. Arcis's pre-market LLM pass is well-suited to producing this filter. **Scalping is dead for Arcis** regardless of model size — LLM inference at 2–4 seconds plus ~300ms Alpaca REST round-trip means any strategy with a signal half-life under 60 seconds is structurally incompatible. **HFT has arbitraged the obvious patterns** but left residual alpha in the 1-minute-plus regime where institutional flows, gamma hedging, and news-driven volume persistence dominate. Time-of-day effects are real: concentrate capital at the open (ORB) and power hour (last-hour momentum continuation); avoid 11:30–14:00 midday where HFT dominates and absolute moves shrink.

Validation timeline is a planning constraint. Credible statistical inference needs 150–385 trades minimum (Cochran 95% CI); at 3 trades/day that's 10 weeks, at 10 trades/day it's 3 weeks — but **regime diversity matters more than raw count**. Plan 6–12 months of paper trading before committing real capital, crossing at minimum one volatility regime shift.

## Streaming data sources for S&P 100 (2026 pricing)

| Source | Cost/month | Latency (retail) | Data types | Free tier | S&P 100 coverage | Historical included |
|---|---|---|---|---|---|---|
| **Alpaca Algo Trader Plus** | **$99** | 100–1,200 ms | Full SIP L1, WebSocket, trades/quotes/bars | Basic: IEX-only (~2% volume) | 100% | ~7 yrs 1-min |
| Alpaca Basic (free) | $0 | Same | IEX-only L1, SIP 15-min delayed | Yes | 100% of IEX subset | ~2 yrs |
| Polygon.io Advanced (now "Massive") | $199 | Real-time | SIP, trades+quotes+financials | Basic tier, EOD only | 100% | 20+ yrs |
| Polygon.io Starter | $29 | **15-min delayed** | Minute/sec aggregates, WebSocket | — | 100% | 5 yrs |
| Databento Standard | $199 | 590μs (internet 90p) | Unlimited live + L2 depth | $125 signup credit | 100% | 7 yrs OHLCV, 1mo L2 |
| Finnhub (paid ~$60–100) | $12–100 | ~real-time | L1 quotes, news, fundamentals | 60 rpm, 50-symbol WS | 100% | Limited |
| IB TWS | $0–10 | 250ms+ | L1/L2 via subs | 100-line default | 100% | Pay-per-sub |
| FirstRate Data | $299 one-time | — | Historical 1-min OHLCV, S&P 500 2000–pres | — | — | 25+ yrs bulk |

**Alpaca Algo Trader Plus at $99/month is the right answer for Arcis.** It bundles full-SIP real-time data with the brokerage Arcis already uses, stays well under the $500/month ceiling, and eliminates a second vendor's failure mode. The one architectural gotcha: Alpaca enforces **one WebSocket connection per account**, so multi-strategy fan-out must happen inside Arcis's process via asyncio.Queue (or the community `alpaca-proxy-agent`). For historical backtest depth beyond what Alpaca provides, **FirstRate Data's one-time $299 S&P 500 1-minute bundle** covering 2000–present is far cheaper than a monthly Polygon subscription and perfectly adequate for backtesting. IEX Cloud is gone (retired Aug 31, 2024) — ignore older blog posts recommending it. Polygon has rebranded to "Massive" but is the same product and the same pricing; Polygon Starter at $29 is 15-minute delayed and unsuitable for live intraday.

**Level 1 is sufficient** for every strategy in the recommended shortlist. Level 2/order-book depth is only necessary for order flow imbalance and microstructure strategies, which the research rules out for retail. **1-minute bars are the minimum useful frequency**; 5-second bars add complexity without alpha at Arcis's latency budget. **Storage stays modest**: 100 tickers × 390 bars/day × ~60 bytes ≈ 2.3 MB/day raw, meaning a full year of 1-min S&P 100 data fits in ~600 MB uncompressed; with TimescaleDB compression policies applied after 7 days, long-term storage is <100 MB/year.

## Architecture recommendation: hybrid async, no framework lock-in

The defensible pattern is **a separate asyncio intraday process that shares Postgres with the existing swing loop, not a unified event loop and not a heavyweight framework**. Unifying loops creates a single point where a blocking call (pandas, LLM, synchronous DB query) starves the hot path. Full process isolation is cleanest but Alpaca's one-connection-per-account limit forces a shared WebSocket layer anyway. The hybrid preserves Phase 1 code unchanged while letting Phase 6 add a new process that reads the same tagged Postgres tables.

| Framework | Language | Intraday support | Alpaca integration | Maintenance (2025–26) | Learning curve | Verdict |
|---|---|---|---|---|---|---|
| **alpaca-py + custom asyncio** | Python | Full | Native (it is Alpaca) | Active, official | Low | **Recommended primary** |
| **Lumibot** | Python | Polling-based, minute+ | Native (stocks/options/crypto, bracket/OCO/OTO) | Active, MIT, commercial support | Low | **Recommended fallback** |
| nautilus_trader | Rust + Python | Excellent, event-driven | **Open RFC, no Alpaca adapter yet** | Very active (v1.221 Oct 2025) | Steep | Watch-list; re-evaluate in 6–12mo |
| QuantConnect LEAN | C# + Python | Excellent | Official plugin | Active | Steep | Over-engineered for solo operator |
| zipline-reloaded | Python | Minute bars | None native | v3.1.1 July 2025, slow issue triage | Medium | Research only; not live |
| backtrader | Python | Yes | Third-party only | **Effectively abandoned** | Medium | Ignore |
| VectorBT (OSS) | Python + Numba | Vectorized, not live | None | Active | Medium | Research/backtest only |
| QSTrader | Python | Schedule-driven | None | Slow, v0.2.6 | Low | Ignore |
| Freqtrade | Python | Crypto-only | N/A | Active | Low | Wrong asset class |

The realistic **end-to-end latency budget on Windows consumer hardware** lands at 250–800ms typical from bar-close to order-ack, with 1–2s worst case: ~100–1,200ms WebSocket delivery, 1–5ms message parse, 5–50ms indicator update, 100–400ms Alpaca REST order submission, 20–100ms TradingStream acknowledgement. Alpaca's internal OMS is ~1.5ms (post-Redpanda upgrade). **Alpaca does not accept order submission over WebSocket** — it's HTTPS POST only, a long-standing design choice and feature-request gap. None of this approaches HFT territory, but every number comfortably clears the 100ms-plus viability line.

Handling the 2–4 second LLM inference correctly is the architectural lynchpin. Use **pre-compute + async advisory** as a combination: Qwen3-8B runs on schedule pre-market and at optional midday/2pm checkpoints, writing structured JSON advisories (regime, per-ticker bias, earnings flags, volatility tier) to Postgres; the intraday hot path reads these rows in under 5ms. Any additional LLM evaluations go to a fire-and-forget job queue that a separate `llm_worker` process drains. **The LLM is never in synchronous decision latency.** One cheap infrastructure win worth doing regardless: switch Qwen3-8B from Ollama to **vLLM or llama.cpp directly**. Red Hat's benchmark measured P99 TTFT of 80ms on vLLM versus 673ms on Ollama for the same model — potentially cutting Arcis's observed 2–4s to 0.5–1.5s without changing models.

For end-of-day flatten, treat it as a belt-and-suspenders problem. Run a dedicated asyncio supervisor task that calls `trading_client.close_all_positions(cancel_orders=True)` at 15:55 ET, **and** schedule a Windows Task Scheduler job running a standalone flatten script as backup — this survives a crashed Python process. Do not rely on `time_in_force="day"`; day orders cancel at close but positions persist overnight.

## LLM role: Option A + Option D, not B or C

Four options were evaluated; the evidence strongly favors **Option A (pre-market context only) layered with Option D (offline training-signal generation)**. Option B (batched hourly setup evaluation) is worth prototyping as a shadow system — logging would-be vetoes without execution — but only after A+D proves measurable alpha. Option C (tiny sub-second model in hot path) is not supported by any published evidence; at sub-second cadence an XGBoost or gradient-boosted classifier on engineered features will outperform an LLM and avoid the stochasticity tax.

The published academic record is thin and mostly adjacent to Arcis's use case. **Trading-R1 (Xiao et al., arXiv:2509.11420, Sep 2025)** explicitly scopes to ~1-week holding periods and states that HFT is out-of-scope due to LLM inference latency. **QuantAgent (Xu et al., arXiv:2509.09995, Sep 2025)** confirms accuracy drops on 1–15 minute candles where noise dominates. **FinRL-DeepSeek (Benhenda, arXiv:2502.07393, Feb 2025)** found LLM sentiment signals helped only in bear-market regimes and actually hurt PPO in bull markets. **FINSABER (Wang et al., arXiv:2505.07078, May 2025)** is the honest counterpoint: extended to 2004–2024, buy-and-hold matches or beats the published LLM-trading claims. No peer-reviewed evidence exists for LLM alpha on sub-minute intraday at retail scale. There is evidence — inconsistent, regime-dependent — that LLM signals added to mechanical systems help at daily horizons. This aligns with using Qwen3 for pre-market context and offline label generation, not live execution.

### VRAM and inference speed on RTX 3090 24GB

| Model | VRAM fp16 | VRAM Q4_K_M | Tokens/sec (llama.cpp) | TTFT short prompt | Sub-second viable? |
|---|---|---|---|---|---|
| Qwen3 0.6B | 1.3 GB | 0.5 GB | 180–250 t/s | 30–60 ms | Yes |
| Qwen3 1.7B | 3.5 GB | 1.2 GB | 120–180 t/s | 50–100 ms | Yes (short outputs) |
| Qwen3 4B | 8 GB | 2.5–3 GB | 80–120 t/s | 80–150 ms | Yes (short outputs) |
| **Qwen3 8B (current)** | **16 GB** | **5–6 GB** | **55–75 t/s** | **150–300 ms** | Borderline (≤20 tok out) |
| Phi-3.5-mini 3.8B | 7.5 GB | 2.3 GB | 90–130 t/s | 80–150 ms | Yes |
| Llama 3.2 3B | 6 GB | 2 GB | 100–150 t/s | 60–120 ms | Yes |

Training data strategy: **the existing 1,782 daily examples do not transfer directly to intraday** — the reasoning surface is structurally different (opening ranges, VWAP interactions, liquidity sweeps versus weekly/daily context). Target **2,000–5,000 curated intraday examples** with regime diversity (trend days, chop, gaps, FOMC, earnings), generated via **reverse-reasoning distillation** (Trading-R1 method): compute forward volatility-adjusted returns on historical 1-min bars, feed (state, outcome) to a frontier model to synthesize expert reasoning, then fine-tune locally. Budget ~$50–200 in API costs for synthetic data generation.

**Kill criterion for LLM-in-intraday**: in a ≥3-month paper trading test, LLM-gated trades must show ΔSharpe ≥ 0.3 or ≥20% max-drawdown reduction versus mechanical-only baseline; if not, LLM stays offline-only permanently.

## Risk controls, PDT, transaction costs

The PDT landscape is actively shifting. On April 14, 2026, FINRA's proposal (Federal Register 2026-00519) to replace Rule 4210's pattern-day-trader framework with an intraday margin-deficit regime received SEC approval per Yahoo Finance reporting, though per-broker implementation dates remain uncertain and Alpaca has not yet published transition guidance. At $100K equity Arcis clears the $25K legacy minimum comfortably regardless, so this is a watching-brief item rather than a blocker.

**Recommended intraday risk control thresholds** (distilled from FIA Best Practices, Nasdaq Rule 6130 kill-switch requirements, and Knight Capital post-mortem literature): maximum session loss 1.5–2% of equity as hard kill; maximum per-hour loss 0.75% as soft throttle halting new entries 30 minutes; three consecutive losing trades stops the strategy for the day; maximum 10 round-trips per day per strategy; single-name intraday concentration capped at 20% of equity; correlated exposure (5-min return correlation >0.7) capped at 40%; no new positions after 15:30 ET with mandatory flatten by 15:55 ET; VIX tiers — under 20 normal sizing, 20–30 half size, 30–40 A-setups only, over 40 flat. Price-band checks reject orders more than 5% from last or 2× ATR; order rate throttles at 60/minute per strategy; cancel-on-disconnect auto-flattens within 30 seconds of heartbeat failure. A master kill switch must run in an independent process with authority to call Alpaca's DELETE /v2/orders and /v2/positions endpoints, with manual re-enable required.

### Transaction cost model on Alpaca PFOF

From Alpaca's Q3 2025 Rule 606 filing (fetched directly), routing flows to Citadel (39–51%), Virtu (16–43%), Jane Street (8–17%), and GTS (added Sept 2025). PFOF rebate is 12% of spread capped at 5¢/share on marketable orders — **the rebate goes to Alpaca, not the customer**. Price improvement and PFOF are substitutes from the wholesaler's economics, and Alpaca's help documentation concedes disclosed averages "tell you nothing about the amount of price improvement you will receive for any given order."

| Trades/day | Round-trips/yr | Slippage bps (RT) | Annual cost % at $100K | Break-even annual alpha | Break-even Sharpe (15% vol) |
|---|---|---|---|---|---|
| 3 | 756 | 3 (S&P 100) | 0.23% | 0.23% | 0.015 |
| 5 | 1,260 | 3 | 0.38% | 0.38% | 0.025 |
| 10 | 2,520 | 3 | 0.76% | 0.76% | 0.050 |
| 20 | 5,040 | 3 | 1.51% | 1.51% | 0.101 |
| 20 | 5,040 | 5 (mid-cap) | 2.52% | 2.52% | 0.168 |
| 20 | 5,040 | 10 (small-cap) | 5.04% | 5.04% | 0.336 |

For liquid S&P 100 names at $25K notional per trade, **3 bps round-trip is a defensible estimate**; this triangulates AQR's institutional 4.50 bps VWAP-deviation average (Frazzini-Israel-Moskowitz) with the minimal size-impact of $25K against L1 depth that routinely exceeds $100K on mega-caps. The **strong execution recommendation is marketable limit orders** (limit set at bid+spread or ask-spread with a 1–2 tick cushion), which caps worst-case fills while still executing in liquid names ~99% of the time. Avoid market orders outside core session, never use market-on-close routing, and periodically request Alpaca's Rule 606(b) customer-specific six-month report to audit fill quality versus NBBO.

**Desk isolation on a single Alpaca account** (Alpaca enforces one live account per SSN for retail, no native sub-accounts): tag every order with a structured `client_order_id` like `MOMO_INTRADAY_OPEN_<uuid>`, store the mapping in a Postgres table keyed on that ID, and maintain a shadow ledger of per-strategy virtual positions since Alpaca nets everything at the account level. P&L attribution joins fills on `client_order_id`; there is no server-side "close all positions tagged X" primitive — build it.

**Section 475(f) MTM election is strongly advisable for Arcis once intraday is live**, primarily because it eliminates wash-sale rule (§1091) application — otherwise every intraday loser re-bought within 30 days becomes a wash sale on the 1099-B, creating a potential year-end disaster if losing positions straddle the year boundary. The election requires Trader Tax Status (≥720 transactions/year, trading ~75% of days, avg holding <31 days, ≥4 hrs/day) which Arcis easily clears once intraday is active. Election must be filed by **April 15** of the election year; late elections are essentially never granted (PLR 202325003). Form 3115 accompanies the first 475 return. Revocation requires IRS consent and a 5-year re-election prohibition, so treat it as a one-way door.

## Timeline, cost, and kill criteria

**Calendar from current state to paper-trading intraday desk: 9–12 months, assuming Phase 2–5 deliverables land on their current schedules.** The incremental work decomposes into: Phase 1 refactor to asyncio handler pattern and 1-min bar storage (~3–4 weeks, near-zero cost); intraday backtest harness and historical data ingestion (~6–8 weeks, $299 FirstRate one-time); ORB strategy implementation and 6-month historical backtest (~4 weeks); shadow-execution paper trading including the LLM pre-market pipeline (~3–4 months minimum to cross one regime and accumulate 150+ trades); risk harness, kill switch, and EOD flatten hardening (~2–3 weeks overlapped with above). Total incremental direct cost through paper-trading go-live: roughly **$1,400** ($99/mo × 12 months Alpaca Algo Trader Plus + $299 FirstRate + ~$200 synthetic training data + buffer). The RTX 3090 upgrade is already planned and unrelated. No additional compute, cloud, or enterprise software is required.

**Kill criteria that would indicate intraday is not feasible at this scale:**

Realized slippage on S&P 100 market orders at $25K notional consistently exceeding 8 bps round-trip in measured fills over a month would invalidate the cost model — at that drag, the required alpha becomes implausible. Paper-trading net Sharpe below 0.5 over a rolling 3-month window with 150+ trades would indicate no durable edge exists in Arcis's strategy implementation. Inability to achieve sub-1-second total decision latency (bar close to order submission) on Arcis's Windows hardware would kill anything beyond 5-minute bar strategies. Alpaca WebSocket reliability below 99% session uptime — measured as delivered-bars-versus-expected-bars over a trading day — would make the broker unsuitable and force an IB reconsideration. Failure of Qwen3-8B (or even a smaller model via vLLM) to produce statistically significant lift in backtest on stocks-in-play filtering would downgrade the LLM to pure offline training-signal duty, which is still viable but removes one of Arcis's differentiators. Any single loss event exceeding 5% of equity in a session that traces to an infrastructure failure (missed WebSocket reconnect, stuck order, LLM hallucination causing size explosion) without being caught by the kill switch would require a full architectural post-mortem before resuming.

## What this study changes about Phase 1

The practical takeaway is narrower than it looks. **Three changes should happen in the next month**: migrate to `alpaca-py`, wrap the poll loop in asyncio handler functions, and begin 1-minute bar collection for the S&P 100. Everything else — TimescaleDB, Lumibot evaluation, FirstRate purchase, 475(f) consideration, intraday training dataset generation — can wait for Phase 6 without closing any doors, because the first three changes are what actually preserve optionality. The rest of this research becomes an implementation checklist when Phase 6 arrives, not a backlog item today.

The deeper insight is that the intraday feasibility question was never about the strategies or the data — both exist in accessible, documented form. The real constraint is **discipline about what the LLM is and is not good for**. Arcis's architectural temptation will be to put Qwen3 everywhere; the evidence says to keep it in its lane (pre-market context, offline labeling) and let mechanical rules carry the execution path. Teams that ignore this fail not because intraday trading is infeasible at retail, but because they build systems where the LLM's stochasticity and latency silently corrode edge the mechanical component had generated.