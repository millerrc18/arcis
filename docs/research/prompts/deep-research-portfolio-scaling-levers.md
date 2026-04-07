# Deep Research: Scaling a Small Equity Portfolio — Levers, Risk Tradeoffs, and Optimal Capital Growth Paths

**Date:** 2026-04-06
**Output:** Save to `docs/research/`
**Classification:** INTERNAL

---

## Research Objective

Arcis is an autonomous AI equity trading system currently running:
- $100K paper account (Alpaca, S&P 100 pullback-in-uptrend strategy)
- $100 live account (Alpaca, same strategy)
- 18 closed trades (12W/1L), 1-15 day holding period
- Max 5 concurrent positions at 2% risk per trade
- Mechanical ATR-based bracket orders (stop + target)

The goal: scale from $5K → $3M AUM over 5 years. That's 600× growth, or roughly 230% CAGR — impossible with unleveraged long-only swing trading alone. Something has to compound faster than just reinvesting profits.

**The core question:** What are ALL the levers available to accelerate capital growth from a small base ($5K-$25K) to institutional scale ($1M+), ranked by risk-adjusted effectiveness? For each lever, quantify the expected acceleration, the risk amplification, and the specific conditions under which it's appropriate for our strategy (pullback-in-uptrend, S&P 100, 1-15 day holds).

---

## Context: Our Strategy Profile

- **Universe:** S&P 100 large-cap equities (most liquid stocks in the world)
- **Strategy:** Buy pullbacks in uptrending stocks. Mechanical bracket exits (ATR-based stop + target).
- **Holding period:** 1-15 days (swing trading, not intraday)
- **Win rate target:** 45-55%
- **Profit factor target:** 1.3-2.0
- **Position sizing:** Currently 2% of capital per trade, max 5 positions
- **Leverage:** None currently. Alpaca offers 4:1 day-trade / 2:1 overnight for pattern day traders.
- **Capital path:** $5K → $25K → $100K → $500K → $3M (5-year target)
- **Operator:** Solo founder, full-time day job, AI system runs autonomously

---

## The Levers to Research

### Lever 1: Margin / Leverage

- How does Reg T margin (2:1 overnight) affect a swing trading strategy?
- What about portfolio margin (6.67:1 for diversified portfolios above $100K)?
- What's the Kelly Criterion optimal leverage for our strategy profile (55% WR, 1.5 PF)?
- How does leverage interact with drawdowns? (2× leverage turns a 15% DD into 30%)
- At what account size does margin become available and practical? ($25K PDT threshold?)
- What's the historical blowup rate for leveraged swing traders?
- How should leverage scale as the account grows? (Aggressive at $5K, conservative at $500K?)
- IB vs Alpaca margin rates and terms?

### Lever 2: Position Concentration

- We currently cap at 5 positions. What if we ran 10? 20? 1?
- Research on optimal position count vs account size for swing trading
- Concentrated portfolios (3-5 positions) vs diversified (15-20) — which compounds faster?
- Kelly fraction sizing vs equal weight vs volatility-targeted sizing
- At what point does concentration risk become unacceptable? (Factor: correlation between positions)

### Lever 3: Trade Frequency / Turnover

- We scan every 30 minutes but hold 1-15 days. What if we shortened the holding period?
- Mean reversion strategies (1-3 day holds) vs pullback (5-15 day holds) — which generates more opportunities?
- Compounding effect of higher turnover: 200 trades/year at 0.5% per trade vs 50 trades/year at 2% per trade
- Transaction cost impact at different turnover rates for S&P 100
- Research on optimal holding period for pullback strategies on large-cap equities

### Lever 4: Universe Expansion

- We trade S&P 100 (103 stocks). Phase 2 plans expansion to S&P 500 (~325 filtered).
- More stocks = more opportunities = faster compounding (if edge persists)
- Does our pullback edge exist in mid-caps (S&P 400)? Small-caps (Russell 2000)?
- Liquidity constraints at different account sizes and stock sizes
- Research on alpha decay as universe expands (does signal quality dilute?)

### Lever 5: Options Overlay

- We have passive options data collection running. Phase 3-4 plans vertical spreads at $15-25K.
- Can defined-risk options (vertical spreads, calendar spreads) accelerate returns without increasing max loss?
- Covered calls on existing positions — income generation vs capping upside
- Cash-secured puts as entry mechanism — get paid to wait for pullbacks
- How does options leverage (delta × contracts) compare to margin leverage for our strategy?
- What's the minimum account size for meaningful options income?

### Lever 6: Multiple Strategies / Desks

- We plan pullback + breakout + mean reversion + options desks
- Uncorrelated strategies compound faster than correlated ones (diversification of alpha)
- Research on strategy allocation: how much capital to each desk?
- Does running 3 uncorrelated strategies at 1/3 size each beat 1 strategy at full size?
- When does multi-strategy become operationally feasible for a solo operator?

### Lever 7: Reinvestment Rate / Compounding

- How does reinvestment of profits vs fixed dollar sizing affect long-term growth?
- Optimal reinvestment: 100% (maximum compounding) vs partial withdrawal (risk management)
- Dollar-cost-averaging into the strategy account from salary (external capital injection)
- Tax-efficient reinvestment: Section 475 MTM, tax-loss harvesting, retirement account trading

### Lever 8: External Capital / Fund Formation

- At what track record length and Sharpe does it become viable to raise outside capital?
- Friends & Family round ($100K-$500K) — when and how?
- Incubator programs (Emerging Manager Alliance, etc.)
- AUM growth from external capital vs organic compounding — which dominates?
- What's the minimum viable fund size? ($2M break-even per our research)

### Lever 9: Alternative Instruments

- Futures (ES, NQ) on the S&P 500 — higher leverage, tax advantages (60/40 split)
- ETF leveraged products (TQQQ, UPRO) as position substitutes
- Sector ETF options instead of individual stock options
- International markets — does our edge exist on non-US large-caps?

### Lever 10: Risk Management as a Growth Lever

- Counterintuitive: better risk management enables MORE aggressive sizing
- If max drawdown drops from 15% to 8%, you can safely double leverage
- How does our traffic light system enable/constrain growth?
- Research: firms that compound fastest tend to have the best drawdown control, not the best win rate

---

## Cross-Cutting Questions

1. **Which combination of levers produces the fastest path from $5K to $100K?** This is the hardest phase — too small for meaningful options, too small for portfolio margin, every dollar matters.

2. **Which combination produces the fastest path from $100K to $1M?** This is where portfolio margin, options, and external capital become available. Which levers to activate and in what order?

3. **Which combination produces the safest path to $3M?** Not fastest — safest. Minimize the probability of ruin at each stage.

4. **What's the expected timeline for each path?** Given our strategy profile (55% WR, 1.5 PF, 200 trades/year), model the compounding under different lever combinations.

5. **What are the regulatory/structural gates?** (PDT at $25K, portfolio margin at $100K, fund formation at $2M, etc.)

6. **What did successful solo traders actually do?** Case studies: how did Renaissance (Medallion Fund), Ed Thorp, Cliff Asness, Jim Simons start? What levers did they pull at $5K, $100K, $1M?

---

## Output Format

For each lever, provide:
```
## Lever N: [Name]

### How It Works
[Mechanics of this lever for our specific strategy]

### Expected Acceleration
[Quantified: how much faster does the portfolio grow?]

### Risk Amplification
[Quantified: how much worse do drawdowns get?]

### When to Activate
[Account size, trade count, Sharpe threshold, or other gate]

### When NOT to Use
[Specific conditions where this lever destroys value]

### Recommendation for Arcis
[ACTIVATE NOW / ACTIVATE AT $X / DEFER / AVOID]
```

Conclude with:
- Optimal lever stack by phase ($5K → $25K → $100K → $500K → $3M)
- Expected timeline under the recommended lever stack
- Risk of ruin calculation at each phase
- The 3 mistakes that blow up small accounts scaling to large ones
