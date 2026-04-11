# Paper trading simulation realism: IB vs. Alpaca for bracket orders on large caps

**Interactive Brokers paper trading is significantly more realistic than Alpaca's for simulating bracket order execution on S&P 100 stocks**, though both platforms introduce biases that systematically overstate live performance. IB fills from the top of the real-time order book and applies conservative queue positioning for limit orders, producing results that practitioners describe as a "pessimistic lower bound." Alpaca fills at NBBO without any liquidity check — meaning a 100,000-share order on a thinly traded name fills instantly at the best quoted price — and suffers from chronic latency bugs that make paper fill timing unreliable. For Halcyon Lab's target universe (S&P 100, 2–15 day holds), expect live execution to degrade paper returns by roughly **3–15 basis points per round-trip trade**, driven primarily by spread costs, queue priority, and market impact that neither simulator models.

---

## How IB's paper trading simulator actually fills orders

IB's paper trading engine uses **real-time Level 1 market data** to simulate fills. Market orders execute at the current displayed bid (for sells) or ask (for buys) from the top of the order book — not at the midpoint or last traded price. When order quantity exceeds the displayed size at the best price, IB walks through simulated subsequent price levels, producing effective slippage on large orders. One practitioner measured slippage on 1,000-share AMZN paper trades averaging **~$0.80 per trade** ($0.14–$1.69 range), while SPY slippage was "pretty close to zero."

IB does **not** apply an artificial slippage model based on order size relative to average daily volume. The simulator also does not model market impact — your simulated orders never move the price. Partial fills are simulated, but with a notable quirk: IB's simulator **rejects the remainder of any exchange-directed market order that partially executes**, which is not how real exchanges behave and can cause unexpected order state in algorithmic systems.

For limit orders, IB's behavior is more conservative than most simulators. An experienced practitioner who conducted extensive analysis using IQFeed data found that **limit orders are placed at the end of the queue**, meaning a buy limit at $100 when the market is $100/$100.05 will not fill until the market trades through to $99.95/$100. This effectively requires a "trade-through" rather than a "touch," making IB's limit fill model pessimistic. No queue priority or time priority is modeled — the end-of-queue placement serves as a rough proxy. Limit orders fill at the limit price or better based on the simulated top-of-book quote.

Stop orders use configurable trigger methods documented in IB's API. **For US equities, the default trigger is the last traded price.** After triggering, a stop order converts to a market order and fills at the current top-of-book price, which tends to be more favorable than real execution during fast markets. IB applies data filtering that ignores last-sale prints outside the prevailing bid-ask, reducing false triggers from erroneous prints. Stop-limit orders convert to limit orders at the specified limit price after triggering and then follow the limit order simulation rules.

## Bracket orders and OCA groups behave differently in IB paper mode

Bracket orders and OCA (One Cancels All) groups function in IB paper trading but with documented behavioral differences from live accounts. The critical distinction: in paper trading, **all stops and complex order types are always IB-simulated**, whereas in live trading some are handled natively by exchanges. OCA cancellation happens within the simulator's processing cycle, but practitioners report timing differences versus live, particularly during fast markets where exchange-level OCA processing can be faster.

Several known issues affect bracket order reliability in IB paper trading. A documented error (code 10326, "OCA group revision is not allowed") prevents modification of stop-loss orders within bracket groups — a significant constraint for algorithmic systems that dynamically adjust bracket parameters. Users on NinjaTrader's forum report that when multiple OCA groups fire simultaneously, contingent stop and profit-taking orders can disappear entirely, requiring a platform restart. NinjaTrader's official position is blunt: **"We do not support paper trading account for sure due to inconsistent behaviour."** One user on IBKR Campus reported bracket orders filling with a **10-minute delay** in US futures paper trading, though this appears less common in equities.

## Alpaca's paper simulator prioritizes simplicity over realism

Alpaca's paper trading fills market orders at the **NBBO quote** — buy orders at the best ask, sell orders at the best bid. This is documented officially and confirmed by Alpaca staff on their forum. Unlike IB, Alpaca performs **no liquidity check whatsoever**: orders of any size fill at the best quoted price regardless of displayed depth. The official documentation states explicitly: "Your order quantity is not checked against the NBBO quantities. In other words, you can submit and receive a fill for an order that is much larger than the actual available liquidity." For a strategy trading meaningful position sizes, this creates a significant optimistic bias.

Alpaca does not model slippage, market impact, or price improvement. The platform simulates partial fills on a **random 10% of eligible orders** — not based on actual liquidity conditions but as a probabilistic mechanism designed to test algorithmic handling of partial fills. This random partial fill system creates a paradoxical problem: while fill pricing is too optimistic, fill timing is too pessimistic. Alpaca staff provided data showing most paper orders fill in **0–9 milliseconds**, but orders selected for partial fills create extreme latency tails. Users have documented market orders taking **5+ minutes to fill** — a problem so persistent from 2020 through April 2026 that multiple practitioners reported abandoning Alpaca paper trading entirely. One user measured paper trading latency at **731ms for a buy order** versus 14ms for the identical order on live. Alpaca staff acknowledged this as a known issue.

Limit orders on Alpaca fill when the NBBO quote crosses the limit price — a "touch" model rather than trade-through. Critically, **limit orders priced inside the spread do not fill**. A buy limit at $100.50 when bid = $100 and ask = $101 will not execute, despite being better than the best bid. In live trading, such orders routinely receive price improvement and fill. This creates a counterintuitive pessimistic bias for mid-price and aggressive limit strategies, while the absence of liquidity checks creates optimistic bias for large orders.

Stop orders trigger based on **trade prints on the consolidated tape**, not quotes. Alpaca staff confirmed that in paper trading, stops use simpler rules than live trading, where execution partners may require additional conditions (trades within NBBO, two consecutive trades). This means **paper trading may trigger stops more easily than live**, potentially showing more stop-outs than would actually occur.

Bracket orders (OTOCO structure) are fully supported. When one exit leg fills, the other is canceled. However, Alpaca's documentation includes an explicit race condition warning: "in extremely volatile and fast market conditions, both orders may fill before the cancellation occurs." Forum users have reported bracket exit orders stuck in "held" status and rare exit order failures occurring roughly once per month out of thousands of bracket executions. Trailing stops cannot be used as the stop-loss leg of bracket orders.

## Feature-by-feature comparison of both simulators

| Feature | Interactive Brokers | Alpaca |
|---|---|---|
| **Market order fill price** | Top-of-book bid/ask (real-time L1) | NBBO bid/ask |
| **Slippage simulation** | No explicit model; book-walking for large orders | None |
| **Liquidity check** | Partial — considers displayed size at L1 | None — unlimited fill at NBBO |
| **Market impact** | Not modeled | Not modeled |
| **Partial fills** | Yes, but remainder rejected (simulator artifact) | Random 10% of orders; not liquidity-based |
| **Limit order model** | End-of-queue (pessimistic/conservative) | Touch model (fill when NBBO crosses limit) |
| **Queue priority** | Implicit via end-of-queue placement | Not modeled |
| **Price improvement** | Not modeled | Not modeled; inside-spread limits won't fill |
| **Stop trigger (equities)** | Last traded price (default); configurable | Trade prints on consolidated tape |
| **Stop trigger filtering** | Ignores prints outside bid-ask | Simpler rules than live; may over-trigger |
| **Post-stop fill** | Market order at current top-of-book | Market order at NBBO |
| **Bracket/OCA support** | Yes — but all simulated, not exchange-native | Yes — OTOCO structure |
| **OCA cancellation** | Within simulator cycle; slight latency vs. live | Generally immediate; race condition documented |
| **Known bracket bugs** | OCA revision errors; occasional delays; order disappearance under load | Exit orders stuck in "held"; rare failures (~1/month) |
| **Fill latency** | Near-instantaneous (market data tick cycle) | 0–9ms typical, but **minutes** when partial fills trigger |
| **Data feed** | Real-time (same as live account) | Real-time NBBO (IEX default; SIP with subscription) |
| **Overall bias** | Conservative (understates performance) | Optimistic on pricing, unreliable on timing |

## Quantifying the paper-to-live performance gap

Academic evidence paints a sobering picture of paper trading fidelity. A landmark study by Wiecki et al. (2016) analyzing **888 algorithmic strategies** on Quantopian found that in-sample Sharpe ratio had essentially **zero predictive power** for out-of-sample performance (R² < 0.025). Annual returns showed a negative correlation between backtested and live results. The more backtesting a quant performed, the larger the discrepancy — direct empirical evidence of overfitting.

For execution-specific divergence (separate from overfitting), the numbers are more manageable for Halcyon Lab's target universe. Using the Almgren et al. (2005) market impact model calibrated on ~700,000 institutional equity trades, expected per-trade impact for S&P 100 stocks scales as follows: orders representing **0.1% of ADV** incur ~1–3 bps total impact; **1% of ADV** incurs ~5–10 bps; **5% of ADV** incurs ~15–30 bps. Bloomberg Intelligence data across 350 buy-side firms shows average arrival slippage of **-17 bps** in US equities, though this includes all cap tiers and urgency levels. AQR's analysis of $1.7 trillion in live executions found effective spread costs below **1.5 bps annualized** for patient limit-order strategies in large caps.

The 2–15 day holding period is **favorable** for minimizing paper-to-live divergence. Transaction costs are amortized over larger expected per-trade returns compared to intraday strategies. A strategy targeting **50–200 bps per trade** over multi-day holds loses only 5–15% of gross returns to execution costs, versus 30–60%+ for day-trading strategies. Permanent market impact from entry is largely independent of exit timing at these horizons, and temporary impact decays within minutes.

Practitioners converge on useful rules of thumb. An experienced IB algo trader applies a **20% performance buffer**: if a strategy is only marginally profitable in paper, it will lose money live. EBC Financial Group estimates a **20–50% reduction in performance** is common transitioning from backtest to live. For multi-factor strategies specifically, academic research suggests **20–30% Sharpe ratio decay** out-of-sample, while purely statistical pattern strategies suffer 50%+ decay.

## Practical implications for Halcyon Lab's transition to live

IB's paper trading is the better simulation environment for Halcyon Lab's use case. Its conservative limit-order queue model means strategies that show profitability on IB paper have already survived a pessimistic fill assumption. For S&P 100 bracket orders with 2–15 day holds, the dominant source of paper-to-live divergence will not be fill pricing — large-cap spreads are typically **0.5–3 bps** — but rather **queue priority on limit entries, stop trigger timing during gaps, and OCA cancellation latency during fast markets**.

Alpaca's paper trading is adequate for API integration testing and order-flow logic validation but should not be trusted for performance estimation. The absence of liquidity checks and the chronic latency issues make Alpaca paper P&L figures unreliable indicators of live performance. Multiple practitioners on Alpaca's own forum reported abandoning paper trading for small live trades ($10 positions) because "the lag in order fulfillment made any data from paper trading simply un-useable." Alpaca's own data shows **67.2% of Trading API users** who traded live between June 2024 and May 2025 started directly with live trading, bypassing paper entirely.

## Conclusion

Neither platform's paper trading should be treated as a reliable predictor of live P&L — both serve primarily as **integration smoke tests** rather than performance estimators. IB's simulator provides a conservative lower bound through its end-of-queue limit fill model and real-time book-walking, while Alpaca's simulator provides an optimistic upper bound through unlimited liquidity and NBBO-based instant fills. For S&P 100 bracket orders with multi-day holds, the execution-specific drag from paper to live should be modest (**3–15 bps per round-trip**), but this compounds meaningfully at higher trade frequencies. The most actionable approach for Halcyon Lab: validate order logic and bracket behavior on IB paper, then transition to live with **minimum viable position sizes** to capture real execution data, applying a 20% performance buffer before scaling. The real risk is not execution slippage on large caps — it's overfitting to in-sample patterns, which no paper trading environment can diagnose.