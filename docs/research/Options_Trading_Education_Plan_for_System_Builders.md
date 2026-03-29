# Options Trading Education Plan for System Builders

**Audience:** Software developer with strong Python/ML/statistics, limited options experience
**Goal:** Build knowledge to design and operate an automated options system focused on credit spreads, iron condors, and calendar spreads on large-cap US equities and SPX/XSP
**Duration:** 24 weeks, ~8-10 hours/week reading + exercises

---

## SECTION 1 — 24-WEEK READING PLAN

### Notation Key
- **NAT** = Natenberg, *Option Volatility & Pricing* (2nd ed)
- **SIN-VT** = Sinclair, *Volatility Trading* (2nd ed)
- **SIN-POT** = Sinclair, *Positional Option Trading*
- **PAS** = Passarelli, *Trading Option Greeks*
- **BEN** = Bennett, *Trading Volatility* (Santander PDF)

---

### PHASE 1: FOUNDATIONS (Weeks 1–8)

#### Week 1 — Options Mechanics & Payoff Diagrams
**Read:** NAT Ch 1–2 (The Language of Options, Elementary Strategies)
**Key Concepts:**
1. Call/put as directional contracts with asymmetric payoff
2. Intrinsic vs extrinsic (time) value decomposition
3. Moneyness spectrum: ITM, ATM, OTM and why it matters for premium pricing
4. Long vs short risk profiles — the seller collects premium but absorbs tail risk
5. Expiration payoff diagrams as piecewise-linear functions

**Python Exercise:** Pull a live options chain for AAPL via `yfinance`, plot expiration payoff diagrams for a long call, short put, and a bull put credit spread. Overlay the current stock price and annotate breakeven, max profit, and max loss.

**System Design Mapping:** This informs the **trade constructor** — the module that takes a strategy type + parameters (strikes, expiration) and outputs the full payoff profile, margin requirement, and risk metrics.

---

#### Week 2 — Put-Call Parity & Arbitrage Boundaries
**Read:** NAT Ch 3–4 (Introduction to Theoretical Pricing Models, Volatility)
**Key Concepts:**
1. Put-call parity: C - P = S - K·e^(-rT) — the fundamental identity
2. Dividends break parity: why American options on dividend-paying stocks need adjustments
3. Early exercise economics — when it's rational (deep ITM calls before ex-div, deep ITM puts)
4. Forward price vs spot price — the no-arbitrage link

**Python Exercise:** Fetch call and put prices for the same AAPL strike/expiry, verify put-call parity holds within the bid-ask spread. Plot the deviation from parity across all strikes for one expiration — deviations signal either dividends, early exercise premium, or stale quotes.

**System Design Mapping:** This drives the **data quality validator** — parity violations beyond expected thresholds indicate bad data. Also informs the **pricing sanity check** that rejects model outputs that violate no-arbitrage bounds.

---

#### Week 3 — Black-Scholes and Its Assumptions
**Read:** NAT Ch 5–6 (Using an Option Theoretical Pricing Model, Option Values and Changing Market Conditions)
**Key Concepts:**
1. The five BSM inputs: S, K, T, r, σ — and which ones are observable vs estimated
2. Risk-neutral pricing: why we discount at the risk-free rate regardless of actual drift
3. Log-normal assumption — prices can't go negative, but returns can be any magnitude
4. BSM as the "wrong model everyone uses" — it's the shared language, not the truth
5. Model price vs market price — the gap IS implied volatility's information content

**Python Exercise:** Implement Black-Scholes from scratch (call + put). Price 20 options across different strikes for one expiration. Compare to market mid-prices. Plot the residual (model - market) and observe the systematic pattern — this IS the volatility smile.

**System Design Mapping:** The BS pricer is the foundation of the **pricing engine**. Every subsequent module (Greeks, IV solver, surface fitter) builds on top of it. This is the most reused function in the entire system.

---

#### Week 4 — The Greeks: Delta, Gamma, Theta, Vega
**Read:** NAT Ch 7–8 (Risk Measurement I & II); PAS Ch 1–4 (Greek Overview, Delta, Gamma, Theta)
**Key Concepts:**
1. Delta as hedge ratio, probability proxy, and P&L sensitivity (three interpretations)
2. Gamma as the rate of delta change — why it accelerates near ATM and near expiration
3. Theta as the "rent" short sellers collect — theta/gamma tradeoff is the core tension
4. Vega as sensitivity to IV change — why it matters more than theta for 30-45 DTE trades
5. The theta-gamma seesaw: you cannot collect theta without absorbing gamma risk

**Python Exercise:** Compute analytical Greeks for a grid of (strike, DTE) pairs. Create heatmaps showing how delta, gamma, theta, and vega vary across the strike/time surface. Identify the "sweet spot" for credit spread sellers: where theta is high relative to gamma.

**System Design Mapping:** Greeks calculations power the **risk monitor** — the real-time module that tracks portfolio-level delta, gamma, theta, vega exposure and triggers alerts or adjustments when limits are breached.

---

#### Week 5 — Higher-Order Greeks & Portfolio-Level Risk
**Read:** PAS Ch 5–8 (Vega, advanced Greeks, position management); NAT Ch 9 (Risk Measurement III)
**Key Concepts:**
1. Charm (delta decay): delta changes as time passes — critical for managing near-expiration positions
2. Vanna (delta sensitivity to IV): delta shifts when IV moves — explains why hedges drift
3. Volga/vomma (vega convexity): vega itself changes with IV — why vol-of-vol matters for iron condors
4. Portfolio Greeks as sums — individual position Greeks aggregate linearly
5. The difference between local Greeks (instantaneous) and scenario Greeks (finite shock)

**Python Exercise:** Build a portfolio of 3 positions (a credit spread, an iron condor, a calendar spread). Compute portfolio-level Greeks. Then simulate a -2% move in the underlying + 5-point IV spike — compare the P&L predicted by first-order Greeks alone vs second-order (including gamma + vanna corrections). The gap is the hedging error.

**System Design Mapping:** Higher-order Greeks drive the **scenario engine** — the module that stress-tests the portfolio under combined price/vol/time moves rather than relying on instantaneous Greek approximations.

---

#### Week 6 — Implied Volatility: Extraction and Interpretation
**Read:** NAT Ch 10–11 (Introduction to Spreading, Volatility Spreads); SIN-VT Ch 1–2 (Volatility Measurement, Forecasting)
**Key Concepts:**
1. IV as the market's consensus forecast of future realized volatility (sort of — it includes a risk premium)
2. Newton-Raphson IV solver: invert BS numerically since there's no closed-form
3. IV rank and IV percentile — contextualizing current IV against its own history
4. The volatility risk premium (VRP): IV systematically overstates realized vol — this is WHY selling premium works
5. IV as a surface, not a number — each (strike, expiry) has its own IV

**Python Exercise:** Write a Newton-Raphson IV solver. Extract IV for every option in the SPY chain. Compute IV rank (current IV's position in 1-year high/low range) and IV percentile (% of days in the past year with lower IV). Plot the time series of 30-day ATM IV vs subsequent 30-day realized vol for SPY — visualize the VRP.

**System Design Mapping:** The IV solver is the core of the **implied volatility engine**. IV rank and IV percentile drive the **entry filter** — you only sell premium when IV is elevated (rank > 50th percentile), because the VRP is widest in high-IV environments.

---

#### Week 7 — The Volatility Surface: Skew, Smile, and Term Structure
**Read:** NAT Ch 12–14 (Bull and Bear Spreads, Risk Considerations, Synthetics); BEN Ch 1–3 (How to Measure Volatility, Volatility Term Structure, Skew)
**Key Concepts:**
1. Skew: OTM puts cost more than OTM calls (in IV terms) — the market prices crash protection
2. Term structure: near-term IV vs long-term IV — contango (normal) vs backwardation (fear)
3. Smile: U-shaped IV across strikes, more common in FX and commodities
4. The surface is the product: market makers trade the surface, not individual options
5. Skew as information: steep skew = institutional hedging demand; flat skew = complacency

**Python Exercise:** For SPX, pull options chains across 5 expirations (1W, 1M, 2M, 3M, 6M). Plot IV vs delta (not strike — delta normalizes across expirations) for each expiry on the same chart. Then plot the ATM IV term structure. Identify whether the market is currently in contango or backwardation.

**System Design Mapping:** This drives the **IV surface module** — the system stores and interpolates the surface for pricing, Greeks computation, and trade scoring. Skew and term structure regime also feed the **regime classifier** (backwardation = elevated fear = different strategy parameters).

---

#### Week 8 — Volatility Trading Fundamentals & the VRP
**Read:** SIN-VT Ch 3–5 (Collecting and Using Data, The Volatility Risk Premium, Variance Swaps)
**Key Concepts:**
1. Close-to-close realized vol: standard deviation of log returns, annualized
2. Parkinson (high-low) estimator: uses intraday range for more efficient vol estimation
3. Variance swap rate: the theoretical fair value of realized variance — connects VIX to tradeable products
4. VRP decomposition: IV = E[RV] + risk premium — the risk premium averages 2-4 vol points for SPX
5. When VRP fails: during vol regime changes, the premium inverts and selling premium gets crushed

**Python Exercise:** Compute 20-day close-to-close and Parkinson realized vol for SPY over 5 years. Plot both alongside VIX. Compute the rolling VRP (VIX minus subsequent 20-day realized vol). Show the VRP distribution — it's positive ~85% of the time, but the negative tail is brutal.

**System Design Mapping:** The VRP calculation is the **strategy alpha signal** — the entire premise of selling credit spreads rests on systematically harvesting the gap between implied and realized volatility. The VRP time series also feeds the **risk governor** — when VRP inverts (IV < RV), the system should reduce or halt premium selling.

---

### PHASE 2: STRATEGY MECHANICS (Weeks 9–14)

#### Week 9 — Credit Spreads: Bull Put and Bear Call
**Read:** NAT Ch 15–16 (Spread Strategies, Ratio and Complex Strategies); SIN-POT Ch 1–3 (Introduction, Volatility Estimation, The Variance Risk Premium)
**Key Concepts:**
1. Bull put spread: sell higher-strike put, buy lower-strike put — defined risk, credit received
2. Bear call spread: sell lower-strike call, buy higher-strike call — same structure, opposite direction
3. Max profit = net credit; max loss = width - credit; breakeven = short strike ± credit
4. Strike selection by delta: 16-delta short strike ≈ 1 standard deviation OTM ≈ ~84% P(profit) at expiration
5. Width selection: wider = more credit but more max loss; narrower = less risk but worse reward/risk ratio

**Python Exercise:** Build a credit spread analyzer: given underlying, short strike delta target, width, and DTE, it selects strikes from the chain, computes max profit, max loss, breakeven, probability of profit (using the BSM delta approximation and a lognormal distribution), and expected value. Compare theoretical P(profit) to what a simple historical backtest suggests.

**System Design Mapping:** This IS the **trade constructor** for the primary strategy. The strike selection logic (delta-based, not fixed-strike) and the P(profit) calculator are core components of the **signal scorer** that ranks potential trades.

---

#### Week 10 — Iron Condors: Construction and Management
**Read:** SIN-POT Ch 4–6 (Hedging, Expiration Trading, Greeks in Practice); PAS Ch 9–12 (Spreads and Greeks)
**Key Concepts:**
1. Iron condor = bull put spread + bear call spread on the same underlying and expiration
2. Net delta ≈ 0 at initiation — profit if the underlying stays within a range
3. The "tent" payoff: flat profit in the middle, losses accelerate past breakevens
4. Adjustment triggers: when one side goes ITM, roll the untested side closer or close the breached side
5. The 50% profit target: academic and practitioner evidence both support closing at 50% of max profit rather than holding to expiration — better risk-adjusted returns due to gamma risk reduction

**Python Exercise:** Build an iron condor constructor that takes a delta target for each side (e.g., 16-delta puts, 16-delta calls) and a wing width. Compute combined Greeks, max profit, max loss, both breakevens, and P(profit). Simulate the P&L over a 45-day period using geometric Brownian motion (1000 paths) to estimate expected profit, probability of hitting the 50% profit target, and probability of max loss.

**System Design Mapping:** This validates the **Monte Carlo engine** and the **exit manager** logic. The simulation framework becomes reusable for all defined-risk strategies. The 50% profit target rule is a concrete exit manager parameter.

---

#### Week 11 — Calendar Spreads and Diagonals
**Read:** NAT Ch 17–18 (Calendar and Time Spreads, Diagonal Spreads); SIN-POT Ch 7–8 (Calendar Spreads, Diagonal Spreads)
**Key Concepts:**
1. Calendar spread: sell near-term, buy far-term at the same strike — profit from differential theta decay
2. The vega play: calendars are long vega — they profit when IV rises (opposite of credit spreads)
3. Term structure bet: calendars profit when the term structure steepens (back month IV rises relative to front)
4. Diagonal = calendar with different strikes — combines directional bias with time decay
5. Risk: if vol collapses or the underlying moves far from the strike, both legs lose value

**Python Exercise:** Build a calendar spread analyzer. For a given ATM strike, find the nearest monthly and next monthly expiration. Compute the net debit, Greeks (especially net vega and net theta), and max profit zone. Simulate P&L across a grid of (underlying price, IV change) scenarios at 50% of the front-month DTE to create a 2D profit surface.

**System Design Mapping:** The 2D profit surface visualization drives the **scenario engine** for non-linear strategies. Calendar spreads also require the system to handle **multi-expiration positions**, which complicates the risk aggregation module (different time-to-expiry for each leg).

---

#### Week 12 — Position Sizing and Kelly Criterion
**Read:** SIN-VT Ch 6–8 (Money Management, Psychology, Implementation); SIN-POT Ch 9–10 (Portfolio Management, Position Sizing)
**Key Concepts:**
1. Kelly criterion: f* = (bp - q) / b, where b = payoff ratio, p = win probability, q = 1-p
2. Half-Kelly: use f*/2 for safety — Kelly is optimal only if your probability estimates are perfect
3. For credit spreads: b = credit / (width - credit), p = estimated P(profit)
4. Portfolio heat: total capital at risk across all positions — cap at 30-50% to survive correlated losses
5. Correlation matters: 10 iron condors on 10 correlated stocks ≠ 10 independent bets

**Python Exercise:** Implement the Kelly criterion for credit spreads. Given a portfolio of potential trades (each with its own P(profit) and payoff ratio), compute the Kelly allocation for each. Then apply a half-Kelly scaler and a total portfolio heat cap. Show how position sizes change as P(profit) estimates shift by ±5% — this reveals sensitivity to estimation error.

**System Design Mapping:** This is the **position sizer** — one of the most critical modules. It sits between the signal scorer (which ranks trades) and the order generator (which submits). The portfolio heat cap is enforced by the **risk governor**.

---

#### Week 13 — Trade Management and Exit Rules
**Read:** SIN-POT Ch 11–13 (Trade Management, Closing Trades, Adjustment Strategies); PAS Ch 13–16 (Advanced Position Management)
**Key Concepts:**
1. Profit targets: 50% of max credit for iron condors, 25-75% for credit spreads depending on DTE
2. Stop losses: 2x the credit received, or when the position reaches 200% of initial credit
3. Time exit: close at 21 DTE regardless of P&L — gamma risk accelerates and the remaining theta isn't worth the risk
4. Delta stop: close when short strike delta exceeds 0.30 (position has moved against you)
5. Rolling: closing the current position and opening a new one at a later expiration — extends duration, not a magic fix

**Python Exercise:** Backtest a rules-based exit manager on SPY iron condors (2019-2024). Compare four strategies: (a) hold to expiration, (b) close at 50% profit, (c) close at 50% profit OR 200% loss OR 21 DTE, (d) close at 50% profit OR delta stop at 0.30 OR 21 DTE. Track win rate, average P&L, max drawdown, and Sharpe ratio for each. The composite exit (c or d) should dominate.

**System Design Mapping:** This IS the **exit manager** — the module that monitors open positions and triggers closes based on a priority-ordered rule set. The backtest framework validates the rules before deployment.

---

#### Week 14 — SPX/XSP Specifics and Index Options
**Read:** BEN Ch 4–6 (Skew Trading, Term Structure Trading, Variance and Volatility); NAT Ch 19–21 (Arbitrage Strategies, Early Exercise, Cash Settlement)
**Key Concepts:**
1. European vs American exercise: SPX options are European (cash-settled, no early assignment), XSP is the mini version
2. Section 1256 tax treatment: 60% long-term / 40% short-term capital gains regardless of holding period
3. AM vs PM settlement: SPX AM-settled (Friday open) vs PM-settled (Friday close) — PM is simpler
4. No pin risk or assignment risk on SPX — a massive operational advantage over equity options
5. SPX skew is steeper than single stocks — institutional hedging demand concentrates in index puts

**Python Exercise:** Compare the IV skew of SPX vs AAPL vs QQQ for the same DTE. Normalize by plotting IV vs delta (not strike). Compute the 25-delta put vs 25-delta call IV differential (the "risk reversal") for each. SPX should show the steepest skew. Also compute the tax advantage: for a $10,000 annual short-term gain, compare the tax liability under standard short-term rates vs Section 1256 60/40 treatment.

**System Design Mapping:** SPX/XSP specifics require the **trade constructor** and **risk monitor** to handle European-style, cash-settled instruments differently. The tax module needs a separate calculation path for 1256 contracts. The absence of assignment risk simplifies the **position monitor** significantly for index trades.

---

### PHASE 3: QUANTITATIVE VOLATILITY (Weeks 15–20)

#### Week 15 — Volatility Forecasting
**Read:** SIN-VT Ch 9–11 (Forecasting Volatility, Volatility Models, GARCH)
**Key Concepts:**
1. EWMA (exponentially weighted moving average): simple, robust vol estimator with decay factor λ ≈ 0.94
2. GARCH(1,1): the workhorse mean-reverting vol model — σ²(t+1) = ω + α·r²(t) + β·σ²(t)
3. Vol clustering: high-vol days cluster together — GARCH captures this, simple historical vol doesn't
4. Forecast evaluation: use Mincer-Zarnowitz regression (RV = a + b·forecast + ε) — good forecasts have a≈0, b≈1
5. Combining forecasts: simple average of GARCH + EWMA + implied vol often beats any individual forecast

**Python Exercise:** Fit GARCH(1,1) to SPY daily returns using the `arch` library. Generate a 30-day forward vol forecast. Compare to VIX and to 20-day historical vol. Compute the Mincer-Zarnowitz regression for each forecaster over a 3-year out-of-sample period. Build an ensemble (equal-weight average) and show it has lower forecast error.

**System Design Mapping:** The vol forecaster powers the **trade entry filter** — compare your forecast to IV. If IV >> forecast (large VRP), conditions favor selling premium. If IV << forecast, stay out. The ensemble approach mirrors best practices in ML model stacking.

---

#### Week 16 — The VIX Complex and Term Structure Trading
**Read:** BEN Ch 7–9 (VIX and Volatility Futures, VIX Options, Correlation); SIN-VT Ch 12–13 (VIX, Variance Swaps and Futures)
**Key Concepts:**
1. VIX calculation: the square root of the 30-day model-free implied variance from SPX options
2. VIX futures term structure: contango (normal, futures > spot) vs backwardation (fear, futures < spot)
3. VIX9D, VIX, VIX3M, VIX6M: the term structure shape encodes the market's volatility expectations across horizons
4. Contango as tailwind: when the term structure is in contango, short vol strategies benefit from the roll yield
5. VVIX: the volatility of VIX — high VVIX means vol itself is volatile, increasing gamma risk for sellers

**Python Exercise:** Download VIX, VIX3M, VIX9D from FRED/CBOE. Plot the term structure ratio (VIX/VIX3M) over 5 years. Mark periods of backwardation. Overlay SPY drawdowns — they should cluster during backwardation. Compute the conditional probability: P(SPY drops >3% in next 30 days | VIX/VIX3M > 1.0) vs P(SPY drops >3% | VIX/VIX3M < 0.85).

**System Design Mapping:** The VIX term structure ratio is a top-level input to the **regime classifier**. Backwardation triggers defensive posture (reduce position sizes, widen strikes, avoid new entries). This is one of the most impactful risk signals in the entire system.

---

#### Week 17 — Surface Fitting: SVI and SABR
**Read:** BEN Ch 10–12 (Advanced Skew, Sticky Strike vs Sticky Delta, Local vs Stochastic Vol); SIN-VT Ch 14–15 (Stochastic Volatility, Local Volatility)
**Key Concepts:**
1. SVI (Stochastic Volatility Inspired): w(k) = a + b·(ρ·(k-m) + √((k-m)² + σ²)) — 5 params to fit the smile
2. SABR: stochastic-alpha-beta-rho model — the market standard for swaptions and increasingly for equity options
3. Sticky strike vs sticky delta: two models for how the surface moves when the underlying moves
4. Arbitrage-free constraints: the fitted surface must not allow butterfly or calendar arbitrage
5. Why fitting matters: mid-market prices for illiquid strikes come from interpolation on the fitted surface

**Python Exercise:** Fit an SVI curve to one SPX expiration. Extract the 5 parameters (a, b, ρ, m, σ). Plot the fit vs market IV across all strikes. Compute the residual and check for butterfly arbitrage (d²C/dK² ≥ 0 everywhere). Then fit SVI to 5 expirations and create a heatmap of the full surface.

**System Design Mapping:** The SVI fitter is the **IV surface module** — it provides smooth, arbitrage-free IV for any (strike, expiry) pair, even where no liquid options trade. This is essential for consistent Greeks computation and for pricing complex/illiquid strikes.

---

#### Week 18 — Realized Volatility Estimators and Measurement
**Read:** SIN-VT Ch 2 (Forecasting Realized Volatility, revisited in depth); SIN-POT Ch 14–16 (Measuring and Using Realized Volatility)
**Key Concepts:**
1. Close-to-close: standard, but misses intraday information and is biased by overnight gaps
2. Parkinson (high-low): ~5x more efficient than close-to-close — uses the intraday range
3. Garman-Klass: uses open, high, low, close — even more efficient than Parkinson
4. Yang-Zhang: the "best" estimator for equities — handles overnight gaps and opening jumps
5. Realized vol window matters: 10-day for recent regime, 20-day standard, 60-day for context

**Python Exercise:** Implement all four estimators (close-to-close, Parkinson, Garman-Klass, Yang-Zhang) for SPY. Compute rolling 20-day realized vol using each. Plot all four on the same chart with VIX overlaid. Compute the VRP using each estimator — Yang-Zhang should give the tightest (most accurate) VRP estimate, meaning the most reliable entry signal.

**System Design Mapping:** The realized vol engine feeds the **VRP calculator**, which is the primary alpha signal. Using Yang-Zhang instead of naive close-to-close reduces noise in the VRP estimate, leading to fewer false signals. This is a low-effort, high-impact improvement.

---

#### Week 19 — Correlation, Dispersion, and Portfolio Volatility
**Read:** BEN Ch 13–14 (Correlation and Dispersion, Portfolio Volatility); SIN-VT Ch 16–17 (Correlation Trading, Portfolio Volatility)
**Key Concepts:**
1. Implied correlation: index IV vs component IVs — when implied corr is high, index options are expensive relative to components
2. Dispersion: short index vol, long component vol — profits when correlation drops
3. Portfolio volatility ≠ sum of position volatilities — correlation reduces portfolio vol
4. Correlation spikes in crashes: the diversification benefit disappears exactly when you need it
5. Cross-Greeks: how correlated underlyings create hidden portfolio-level exposures

**Python Exercise:** Compute the rolling 60-day realized correlation matrix for 10 large-cap stocks. Compute portfolio volatility for equal-weight allocation vs vol-weighted allocation. Show that vol-weighted has lower realized portfolio vol. Then compute implied correlation from SPY option IV vs the vol-weighted component IVs — this is the correlation risk premium.

**System Design Mapping:** Correlation awareness drives the **risk governor's concentration limits**. If you have 5 open iron condors and the pairwise correlations spike, your effective diversification has collapsed and the portfolio heat is understated. The system must dynamically adjust position limits based on realized correlation.

---

#### Week 20 — Backtesting Options Strategies Properly
**Read:** SIN-POT Ch 17–19 (Backtesting, Common Pitfalls, Implementation); SIN-VT Ch 18 (Execution)
**Key Concepts:**
1. Options backtesting is harder than equity backtesting — you need full chains, not just prices
2. Survivorship bias: using current option chains ignores expired/delisted options
3. Bid-ask cost: backtests that use mid-price overstate returns — assume you lose half the spread on each leg
4. Fill assumption: for a 4-leg iron condor, assuming simultaneous mid-fill is unrealistic
5. Data sources: CBOE DataShop (paid, gold standard), OptionsDX (affordable), historical chains via tastytrade/ORATS

**Python Exercise:** Using OptionsDX or similar data, backtest SPY 45-DTE iron condors from 2018-2024. Critical: use natural width (bid for sells, ask for buys), not mid-price. Compare results with mid-price fills vs natural fills — the gap is your "backtesting optimism" penalty. Report annualized return, Sharpe, max drawdown, win rate, and average DIT (days in trade).

**System Design Mapping:** This validates the **backtesting framework** — the module that simulates historical strategy performance. The bid-ask adjustment is a required parameter, not optional. Every backtest result the system produces must include a sensitivity analysis to fill assumptions.

---

### PHASE 4: ADVANCED TOPICS (Weeks 21–24)

#### Week 21 — Assignment, Pin Risk, and American Option Nuances
**Read:** NAT Ch 22–24 (American Options, Dividends, Early Exercise Strategy); PAS Ch 17–19 (Assignment Risk, Dividend Strategies)
**Key Concepts:**
1. Assignment risk: short American options can be exercised at any time — usually only happens deep ITM near expiration or before ex-dividend
2. Pin risk: when the underlying closes near a short strike at expiration, you don't know if you'll be assigned
3. Ex-dividend early exercise: if the extrinsic value of a short ITM call < upcoming dividend, expect assignment
4. After-hours risk: options exercise decisions are made until 5:30 PM ET, but the underlying can move after the close
5. SPX eliminates these problems: European exercise, cash settlement, no dividends to worry about

**Python Exercise:** For 100 AAPL options across strikes and expirations, compute the extrinsic value of each option. Flag any short ITM calls where extrinsic < next dividend — these are early exercise candidates. Build an alert module that scans all open positions for assignment risk before each ex-dividend date and before expiration Friday.

**System Design Mapping:** This drives the **assignment risk monitor** — a module that runs daily and before each expiration/ex-div event. For equity options, it checks whether any short legs are at risk and triggers early closure if assignment would create undesirable exposure. For SPX/XSP, this module is largely a no-op.

---

#### Week 22 — Execution: Getting Filled Efficiently
**Read:** SIN-VT Ch 18 (Implementation, revisited in depth); SIN-POT Ch 20 (Execution and Transaction Costs)
**Key Concepts:**
1. Market makers widen spreads in volatile conditions — your execution cost is state-dependent
2. Complex orders (the whole spread as one order) vs legging in — complex orders eliminate leg risk
3. Mid-price is a starting point, not a target — start at mid, then walk toward the natural price in $0.01-$0.05 increments
4. Time-of-day effects: spreads are tightest 10:00-11:30 AM ET and 1:30-3:00 PM ET
5. Penny pilot stocks/ETFs have $0.01 increments; non-penny have $0.05 — affects achievable fill quality

**Python Exercise:** Record bid-ask spreads for SPY options at 5-minute intervals throughout a trading day. Compute the spread as % of mid-price across strikes and times. Identify the optimal execution windows. Build a fill simulator that models the expected fill price as mid + f(spread_width, urgency_parameter), where urgency 0 = patient (fill at mid) and urgency 1 = immediate (fill at natural).

**System Design Mapping:** This drives the **order execution engine** — the module that takes a desired trade and determines when and how to submit it. The fill simulator is used in backtesting to produce realistic results, and in live trading to estimate execution cost before committing.

---

#### Week 23 — Tax Treatment for Options
**Read:** Review IRS Publication 550 (sections on options); search for "Section 1256 contracts," "wash sale options," "straddle rules"
**Key Concepts:**
1. Section 1256 (SPX, XSP, VIX options): marked-to-market at year-end, 60% LTCG / 40% STCG regardless of holding period
2. Equity options (AAPL, SPY): standard short-term/long-term capital gains based on holding period
3. Wash sale rules for options: closing a losing put spread and opening a "substantially identical" spread within 30 days can trigger a wash sale
4. Straddle rules: offsetting positions on the same underlying can defer losses
5. Constructive sale: certain positions can be treated as if you sold the underlying

**Python Exercise:** Build a tax estimator module. Given a list of closed trades (with dates, P&L, and whether 1256 or equity), compute: total tax liability under standard rates vs 1256 treatment, wash sale adjustments, and the annual tax drag as a percentage of gross P&L. For a sample portfolio of $50K annual gross profit, compute the Section 1256 tax savings assuming a 32% marginal income tax rate.

**System Design Mapping:** The **tax module** informs strategy selection — the 1256 advantage is large enough to tilt the system toward SPX/XSP over SPY when all else is equal. The wash sale detector must run pre-trade to prevent inadvertent violations.

---

#### Week 24 — Putting It All Together: System Architecture Review
**Read:** Re-read SIN-POT Ch 1–3 and SIN-VT Ch 1–3 with fresh eyes. Review BEN Ch 14–15 (Putting It Together).
**Key Concepts:**
1. The full pipeline: data → IV surface → VRP → regime → signal → position sizing → entry → monitoring → exit
2. Fail-safe design: every module should have a "do nothing" safe default — if the IV surface fails to fit, don't trade
3. Logging everything: every decision point, every Greek calculation, every skipped trade — you need this for debugging and for future training data
4. Paper trading validation: run the full system on paper for at least 50 trade cycles before committing real capital
5. Continuous improvement loop: realized outcomes feed back into the VRP model, the vol forecaster, and the exit rules

**Python Exercise:** Write the system architecture specification as a class diagram. Define the interfaces between all modules identified in weeks 1-23: DataFeed → IVSurface → VolForecaster → VRPCalculator → RegimeClassifier → SignalScorer → PositionSizer → RiskGovernor → OrderExecutor → PositionMonitor → ExitManager → Logger. Implement a skeleton (interfaces only, no logic) and verify the data flow compiles and the module boundaries make sense.

**System Design Mapping:** This IS the system. The architecture spec is the most important deliverable of the entire 24-week program.

---
---

## SECTION 2 — CONCEPT GLOSSARY (60+ Terms)

### Greeks (First-Order)

**Delta (Δ)**
The rate of change of option price with respect to a $1 move in the underlying. For calls: 0 to +1; for puts: -1 to 0. A 0.30 delta call gains ~$0.30 if the stock rises $1. Also approximates the probability that the option expires ITM under risk-neutral assumptions.
*System design note:* Delta is the primary input to the **position monitor** and **hedging module**. Portfolio delta is the sum of all individual deltas × contract multiplier. The system tracks net portfolio delta and can trigger hedging when it exceeds a configurable threshold.

**Gamma (Γ)**
The rate of change of delta with respect to a $1 move in the underlying — i.e., the second derivative of option price with respect to the underlying price. Highest for ATM options near expiration. Gamma is what makes short option positions dangerous: as the stock moves against you, your delta exposure accelerates.
*System design note:* Portfolio gamma drives the **risk monitor's** P&L-at-risk calculation. A position with -50 gamma will lose an additional $50 of delta exposure for each $1 the stock moves against it. The exit manager may trigger a close when gamma exposure exceeds a threshold (the "gamma stop").

**Theta (Θ)**
The rate of change of option price with respect to one day passing, holding all else constant. Expressed as a negative number for long options (they lose value daily) and positive for short positions (premium sellers collect theta daily). Theta accelerates as expiration approaches — most decay occurs in the final 30 days.
*System design note:* Theta is the "revenue" of premium selling strategies. The **portfolio dashboard** displays daily theta collected across all positions. The trade scorer uses theta/risk ratios to rank potential entries. The system also monitors the theta/gamma ratio — when gamma risk grows faster than theta income, it's time to close.

**Vega (ν)**
The rate of change of option price with respect to a 1-percentage-point change in implied volatility. A vega of 0.15 means the option price changes $0.15 for each 1-point IV move. Vega is highest for ATM, long-dated options. Credit spreads have negative vega (they profit when IV decreases).
*System design note:* Portfolio vega drives the **volatility exposure monitor**. A surprise IV spike can turn a profitable iron condor position into a loser faster than an underlying price move. The system caps total portfolio vega exposure and alerts when approaching the limit.

**Rho (ρ)**
The rate of change of option price with respect to a 1% change in the risk-free interest rate. Minimal impact for short-dated options on equities. More relevant for LEAPS (long-dated options) and in high-rate environments. Calls have positive rho (higher rates increase call value); puts have negative rho.
*System design note:* Rho is typically the lowest-priority Greek in the **risk monitor**. However, the system should still update the risk-free rate input (from FRED's fed funds rate or Treasury yields) daily to avoid drift in BSM calculations.

### Greeks (Higher-Order)

**Charm (Delta Decay / DdeltaDtime)**
The rate of change of delta with respect to time. Delta drifts even if the underlying doesn't move — a 0.30-delta position might become 0.25-delta tomorrow purely from time decay. This effect accelerates near expiration.
*System design note:* Charm matters for the **hedging module** — delta hedges become stale overnight. The system can pre-compute tomorrow's expected delta and adjust accordingly, rather than reacting after the fact.

**Vanna (DdeltaDvol)**
The rate of change of delta with respect to a change in IV, or equivalently, the rate of change of vega with respect to the underlying price. Vanna is why your delta exposure shifts when vol spikes — even if the stock hasn't moved.
*System design note:* Vanna drives the **scenario engine's** cross-sensitivity calculation. During a vol spike (e.g., VIX jumps 5 points), the system needs to re-estimate portfolio delta accounting for vanna, not just use the pre-spike delta.

**Volga (Vomma / DvegaDvol)**
The rate of change of vega with respect to IV — the convexity of option price in volatility space. Options with high volga gain more from vol spikes than they lose from vol drops of equal magnitude. OTM options have the highest volga, which is why skew exists (market makers charge extra for volga).
*System design note:* Volga affects the **pricing engine's** accuracy during extreme vol moves. When fitting the IV surface, volga is related to the curvature parameters of SVI. The risk monitor uses volga to estimate P&L in a "vol-of-vol" scenario.

### Volatility Concepts

**Implied Volatility (IV)**
The volatility value that, when plugged into the Black-Scholes model, produces the market's observed option price. It's "implied" because you solve for it backwards from the price. IV is not a forecast — it's a price translated into volatility units. It includes the true expected volatility PLUS a risk premium.
*System design note:* IV is extracted by the **IV solver module** (Newton-Raphson inversion of BSM). Every option in the system's chain has an associated IV. The IV feeds the surface fitter, the VRP calculator, and the Greeks engine.

**Realized Volatility (RV) / Historical Volatility (HV)**
The actual volatility of the underlying's returns over a past period, measured from observed prices. Standard computation: annualized standard deviation of daily log returns over a trailing window (typically 20 or 30 trading days). Unlike IV, this is a backward-looking measurement of what already happened.
*System design note:* RV is computed by the **volatility measurement module** using multiple estimators (close-to-close, Parkinson, Yang-Zhang). The primary use is computing VRP = IV - RV, which drives the entry filter.

**IV Rank**
Where current IV sits in its range over a lookback period (usually 1 year). Formula: (current IV - 52wk low IV) / (52wk high IV - 52wk low IV) × 100. An IV rank of 80 means current IV is near the top of its annual range — premium is expensive relative to recent history.
*System design note:* IV rank is a core input to the **entry filter**. Most premium-selling systems require IV rank > 30-50 before entering trades. Stored as a daily metric in the database for each underlying.

**IV Percentile**
The percentage of trading days in the lookback period where IV was lower than today. An IV percentile of 90 means IV was below today's level on 90% of days in the past year. More robust than IV rank because a single outlier day doesn't distort it.
*System design note:* IV percentile often replaces IV rank in the **entry filter** because it's less sensitive to single-day spikes. Both are computed; the system can use either or both as configurable threshold parameters.

**Volatility Risk Premium (VRP)**
The systematic difference between implied volatility and subsequent realized volatility. IV overstates future RV on average by ~2-4 vol points for SPX. This positive VRP is WHY selling options is profitable on average — you're being paid to provide insurance. The VRP varies over time and can invert during crises.
*System design note:* VRP is the **alpha signal** of the entire system. Computed as VRP = ATM IV - forecast RV (using the vol forecaster). When VRP is large and positive, conditions favor selling premium. When VRP inverts, the risk governor halts new entries.

**Variance Swap Rate**
The fair price of a variance swap — a contract that pays the difference between realized variance and a fixed strike. The VIX is closely related: VIX² ≈ the 30-day variance swap rate × 100. Variance swap rates are model-free (derived directly from option prices across all strikes) and provide a cleaner measure of expected variance than ATM IV alone.
*System design note:* The variance swap rate provides a model-free volatility input for the **VRP calculator** that avoids reliance on BSM. Computing it requires integrating across the full option chain, which the IV surface module already supplies.

**VIX**
The CBOE Volatility Index — a model-free estimate of 30-day expected volatility of the S&P 500, derived from SPX option prices. Often called the "fear gauge." VIX is not a direct average of IVs — it's computed from a weighted strip of OTM put and call prices. VIX is quoted in annualized percentage points: VIX = 20 means the market expects ~20% annualized vol.
*System design note:* VIX is a primary input to the **regime classifier** (VIX < 15 = low vol, 15-25 = normal, 25-35 = elevated, 35+ = crisis). The system pulls VIX and its term structure (VIX9D, VIX3M, VIX6M) from CBOE data or FRED.

**Volatility Term Structure**
The pattern of ATM implied volatility across different expirations. In "normal" markets (contango), longer-dated IV is higher than shorter-dated (reflecting uncertainty over longer horizons). In fearful markets (backwardation), near-term IV exceeds far-term IV because the market is pricing imminent risk.
*System design note:* Term structure shape drives the **strategy selector** — calendars benefit from steep contango (sell expensive front month, buy cheaper back month). It also feeds the regime classifier: backwardation = danger.

**Volatility Skew**
The pattern of IV across strikes for a single expiration. For equities and indices, OTM puts have higher IV than OTM calls (the "smirk" or "skew"). This reflects demand for downside protection. Quantified as the difference in IV between a 25-delta put and 25-delta call.
*System design note:* Skew feeds the **strike selector** — steeper skew means OTM puts are relatively expensive, which increases the credit collected on bull put spreads. Skew also feeds the **IV surface module** as a shape parameter.

**Volatility Smile**
A U-shaped IV pattern across strikes where both OTM puts AND OTM calls have higher IV than ATM. More common in FX and commodities than equities. When equity markets show a smile (rather than a skew), it often signals expected large moves in either direction (e.g., pre-earnings).
*System design note:* The surface fitter must handle both smile and skew shapes. Pre-earnings options chains often show a smile, which the system should detect and flag — earnings risk may require special handling or avoidance.

**Volatility Surface**
The complete 3D landscape of IV across both strike and expiration dimensions. Each (strike, expiry) pair has its own IV. The surface is the full picture that subsumes skew (one expiry, many strikes) and term structure (one strike, many expiries). It is the most complete representation of market-implied volatility.
*System design note:* The **IV surface module** is a core component — it fits a smooth function (SVI or SABR) to observed IVs, interpolates for illiquid points, enforces no-arbitrage constraints, and serves as the foundation for all Greeks and pricing calculations.

**SABR Model**
Stochastic Alpha Beta Rho — a stochastic volatility model that describes the dynamics of the forward price and its volatility. Has 4 parameters (α = vol level, β = elasticity, ρ = correlation between forward and vol, ν = vol-of-vol). It's the market standard for interest rate options and increasingly used for equity options.
*System design note:* SABR is an alternative to SVI for the **IV surface module**. SABR has a stronger theoretical foundation (it models dynamics, not just a static snapshot) but is harder to fit and can produce arbitrage in the wings. Most equity options systems start with SVI and add SABR if more sophisticated surface modeling is needed.

**SVI (Stochastic Volatility Inspired)**
A parametric model for the implied variance smile as a function of log-moneyness. Formula: w(k) = a + b(ρ(k-m) + √((k-m)² + σ²)), where w = total implied variance (IV² × T). Five parameters: a (variance level), b (angle of wings), ρ (rotation/asymmetry), m (shift), σ (curvature). SVI is popular because it's easy to fit (linear in some parameters) and can satisfy no-arbitrage constraints.
*System design note:* SVI is the recommended starting point for the **IV surface module**. Fit independently per expiration, then interpolate across expirations for the full surface. Store fitted parameters in the database for each scan — this creates a time series of surface evolution.

### Strategy Types

**Credit Spread (Bull Put / Bear Call)**
A two-leg strategy where you sell a closer-to-the-money option and buy a farther-OTM option of the same type and expiration. The "bull put" sells a put and buys a lower-strike put (bullish). The "bear call" sells a call and buys a higher-strike call (bearish). You receive a net credit upfront; max loss = width minus credit.
*System design note:* This is the **primary strategy module**. The trade constructor takes inputs (underlying, direction, delta target for short strike, width, DTE) and outputs the full position with all risk metrics.

**Iron Condor**
A bull put spread plus a bear call spread on the same underlying and expiration. Net delta ≈ 0. Profits when the underlying stays within a range defined by the two short strikes. Max profit = total credit; max loss = wider wing width minus total credit. Essentially a bet that realized vol will be less than IV.
*System design note:* The iron condor constructor calls the credit spread module twice (once for each side) and aggregates the risk metrics. The exit manager needs to handle partial closes (closing just the tested side) in addition to full-position exits.

**Calendar Spread (Time Spread)**
Sell a near-term option and buy a same-strike, farther-dated option. Profits from the faster time decay of the near-term leg. Net long vega (benefits from IV increases). Maximum profit occurs when the underlying sits at the shared strike at front-month expiration.
*System design note:* Calendars require the system to handle **multi-expiration positions**, which complicates Greeks aggregation (different T for each leg). The P&L model needs the full IV surface, not just a single IV input.

**Diagonal Spread**
Like a calendar but with different strikes for each leg. Combines a directional view (from the strike difference) with a time decay view (from the expiration difference). More flexible than pure calendars but harder to analyze because both moneyness and time interact.
*System design note:* Diagonals use the calendar spread module with an additional strike-offset parameter. The scenario engine needs to model both price and time simultaneously.

**Straddle**
Buy (or sell) a call and a put at the same strike and expiration. Long straddle = bet on a big move in either direction. Short straddle = bet on low realized vol. Undefined risk on the short side. Not a primary strategy for this system but useful for understanding vol trading.
*System design note:* Short straddles are too risky for an automated system without sophisticated hedging. However, straddle pricing is used in the **VRP calculator** — the ATM straddle price directly reflects the market's expected move.

**Strangle**
Buy (or sell) an OTM call and OTM put at different strikes, same expiration. The short strangle is a wider version of the short straddle — more room for the stock to move before losses begin, but less premium collected. Undefined risk on the short side.
*System design note:* Short strangles are the predecessors of iron condors (add protective wings → defined risk). The system should support strangles for analysis and comparison but default to iron condors (defined risk) for automated execution.

**Butterfly**
A three-strike strategy: buy 1 lower, sell 2 middle, buy 1 upper (for a long call butterfly). Max profit at the middle strike at expiration. Very defined risk (cost = net debit). Used as a precision bet on where the underlying will be at expiration.
*System design note:* Butterflies are useful for the **strategy comparison module** — when the system identifies a specific expected price target, a butterfly may have better expected value than a credit spread. Lower priority for initial implementation.

**PMCC (Poor Man's Covered Call)**
Buy a deep ITM LEAPS call (high delta, acts as stock substitute), sell a near-term OTM call against it. Mimics covered call economics with less capital. The LEAPS has ~0.80 delta, so it tracks the stock, while the short call collects premium.
*System design note:* PMCCs are a capital-efficient alternative to covered calls. The system tracks them as multi-expiration positions (similar to calendars). Not a primary strategy for this system's focus on credit spreads.

**Ratio Spread**
Selling more options than you buy at different strikes. Example: buy 1 ATM call, sell 2 OTM calls. Creates a position with capped upside, unlimited downside beyond a point, and a "sweet spot" profit zone. The extra short leg increases credit but introduces undefined risk.
*System design note:* Ratio spreads should be flagged by the **risk governor** as undefined-risk unless fully covered. The system may support them for analysis but should not auto-execute without explicit authorization.

**Collar**
Long stock + long OTM put + short OTM call. The put provides downside protection; the short call finances it. Net effect: capped upside and downside. Common for hedging existing equity positions.
*System design note:* Not a primary strategy for this system. Useful in the **portfolio hedging module** if the system eventually manages equity positions alongside options.

### Risk Concepts

**Max Loss**
The worst-case outcome for a position, assuming the underlying goes maximally against you. For a credit spread: width of strikes minus credit received. For an iron condor: the wider wing width minus total credit. For undefined-risk positions: theoretically unlimited.
*System design note:* Max loss is computed by the **trade constructor** for every position and is the primary input to the **position sizer** (Kelly formula uses max loss as the "cost of a loss"). The risk governor enforces a cap on total max loss across all positions.

**Max Profit**
The best-case outcome. For credit spreads and iron condors: the net credit received at entry. This occurs when all short options expire OTM. For debit strategies (calendars, butterflies): computed by the pricing model at the optimal outcome.
*System design note:* Max profit is stored with each position and used by the **exit manager** — the 50% profit target is literally 0.5 × max profit.

**Breakeven**
The underlying price(s) at expiration where the position's P&L is exactly zero. Bull put spread breakeven = short put strike - credit received. Iron condors have two breakevens (one per side). Breakevens assume holding to expiration — intra-trade breakeven shifts as Greeks evolve.
*System design note:* Breakevens are displayed in the **portfolio dashboard** and used by the **alert system** to notify when the underlying approaches a breakeven level.

**Probability of Profit (P(profit))**
The estimated probability that the position will be profitable at expiration. Approximated by BSM delta of the short strike (for credit spreads: 1 - |delta_short|). More accurate estimation uses the full probability distribution from the IV surface, not just BSM assumptions.
*System design note:* P(profit) is a primary metric in the **signal scorer**. The system computes it using both the BSM approximation and a Monte Carlo simulation — significant divergence between the two indicates the BSM assumptions (lognormal, constant vol) may be unreliable for that trade.

**Expected Value (EV)**
The probability-weighted average P&L: EV = P(profit) × max_profit + P(loss) × avg_loss. A positive EV trade is one where the expected gain outweighs the expected loss. Note: a trade can have a high win rate but negative EV if the average loss is much larger than the average win.
*System design note:* EV is the most important single metric in the **signal scorer**. The system ranks candidate trades by EV and only enters trades with EV > a configurable threshold (e.g., > $0 after transaction costs).

**Assignment Risk**
The risk that the holder of an American-style option exercises it, obligating the seller to buy (put assignment) or sell (call assignment) 100 shares at the strike price. Most common for deep ITM options near expiration or before ex-dividend dates.
*System design note:* The **assignment risk monitor** scans all short equity option legs daily. When a short leg goes deep ITM (extrinsic < $0.10) or an ex-div date approaches, the system alerts for manual review or auto-closes.

**Pin Risk**
The uncertainty when the underlying closes very near a short strike at expiration. You don't know if you'll be assigned until after the close, and the stock can move after hours. This creates an unhedgeable overnight risk that can result in unexpected equity positions.
*System design note:* The **expiration manager** module closes any position where the underlying is within X% of a short strike on expiration day morning. This eliminates pin risk at the cost of occasionally leaving small profit on the table.

**Early Exercise**
The exercise of an American option before expiration. Rational for deep ITM calls just before an ex-dividend date (capture the dividend), and for deep ITM puts when the interest on the proceeds exceeds remaining time value. European options (SPX) cannot be early-exercised.
*System design note:* The **assignment risk monitor** computes the early exercise threshold: for short calls, exercise is rational when time value < next dividend. The system should pre-emptively close or roll such positions.

### Market Structure

**Options Chain**
The complete list of all available options for an underlying, organized by expiration date and strike price. Each entry includes bid, ask, last price, volume, open interest, IV, and Greeks. The chain is the raw data the system ingests.
*System design note:* The **data feed module** pulls the chain at regular intervals (every 1-5 minutes during market hours). Chain data is stored in the database with timestamps, enabling historical analysis and backtest data construction.

**Strike Price**
The price at which the option contract can be exercised. For SPX, strikes are typically spaced $5 apart near ATM, widening to $25+ for far OTM. Strike selection is the most impactful decision in credit spread construction — too close = too much risk, too far = too little premium.
*System design note:* The **strike selector** uses delta-based targeting rather than fixed-dollar-width, because delta adapts to the current IV environment. In high IV, a 16-delta strike is farther OTM (in dollar terms) than in low IV.

**Expiration Date**
The date on which the option contract expires. Standard monthly options expire on the third Friday. Weeklies expire every Friday (for liquid underlyings). Quarterly options exist for SPX. DTE (days to expiration) is a core input to every pricing and risk calculation.
*System design note:* The **DTE calculator** handles business days vs calendar days (BSM uses calendar days / 365). The system tracks expiration dates and manages the calendar for roll decisions and time-based exits.

**Moneyness**
The relationship between the underlying price and the strike: ITM (intrinsic value > 0), ATM (strike ≈ underlying), OTM (no intrinsic value). Often expressed as log(K/F) where K = strike, F = forward price — this normalized measure allows comparisons across different underlyings and price levels.
*System design note:* Moneyness is the x-axis for IV surface fitting (SVI uses log-moneyness). The **IV surface module** converts all strikes to moneyness before fitting and converts back for display.

**Open Interest**
The total number of outstanding (not yet closed or exercised) contracts for a specific option. High OI indicates liquidity and institutional interest. Changes in OI reveal whether money is flowing into or out of an option. Unlike volume, OI doesn't reset daily.
*System design note:* OI is a **liquidity filter** — the system avoids strikes with OI < a threshold (e.g., < 100 contracts) because bid-ask spreads will be wide and fills will be poor. OI changes also feed into options flow analysis.

**Volume**
The number of contracts traded during the current session. High volume relative to OI indicates new activity. Volume/OI ratio > 2-3x is often flagged as "unusual activity" — a potential signal of informed trading.
*System design note:* Volume feeds the **options flow analyzer** and the **liquidity filter**. The system may also track volume as a signal input (unusually high volume on a specific strike may indicate institutional positioning).

**Bid-Ask Spread**
The difference between the highest price a buyer will pay (bid) and the lowest a seller will accept (ask). Wide spreads = illiquid options = higher execution costs. For SPY ATM options, spreads are $0.01-0.03; for less liquid equities, spreads can be $0.10-0.50+. The spread is the market maker's compensation for providing liquidity.
*System design note:* Bid-ask spread is a critical input to the **execution cost estimator** and the **backtesting engine**. The system computes execution cost as: (ask - bid) × 0.5 × number_of_legs × contracts. Any backtest that ignores this overestimates returns.

**Penny Pilot**
An SEC program allowing certain options to trade in $0.01 increments (vs the standard $0.05). SPY, QQQ, AAPL, and most high-volume names are penny pilot. Non-penny options have wider minimum spreads, increasing execution costs.
*System design note:* The **liquidity filter** checks whether each underlying is in the penny pilot program. Non-penny pilot underlyings receive a higher execution cost estimate and may be excluded from the trade universe.

**Market Maker**
A firm that provides continuous bid and ask quotes, earning the spread as compensation for taking the other side of trades. Market makers hedge their exposure, so they are volatility traders, not directional traders. Understanding their incentives helps predict how option prices respond to supply/demand.
*System design note:* Market maker behavior affects the **execution engine's** fill model. During low-vol periods, MMs tighten spreads (cheaper execution). During stress, they widen dramatically. The system should adjust fill assumptions based on current VIX level.

### Execution Concepts

**Fill Quality**
How close to the mid-price your order gets executed. A fill at mid-price is ideal; a fill at the natural (bid for sells, ask for buys) is worst-case. Fill quality depends on spread width, underlying liquidity, time of day, and order type.
*System design note:* The **execution engine** logs every fill price and computes fill quality = (fill - natural) / (mid - natural). This metric tracks execution performance over time and calibrates the fill model used in backtesting.

**Slippage**
The difference between the expected fill price (typically mid) and the actual fill price. Slippage is higher for large orders, illiquid options, multi-leg orders, and during volatile markets. It's the "hidden cost" that backtests underestimate.
*System design note:* The **backtesting engine** adds a configurable slippage factor to each simulated fill. The live system logs actual slippage per trade and compares to the backtest assumption — persistent divergence means the backtest model needs recalibration.

**Mid-Price**
The average of bid and ask: (bid + ask) / 2. Used as the "fair value" reference for evaluating fills. Note: mid-price is NOT the true fair value — it's offset toward the market maker's inventory needs. For credit spreads, the true fair value is typically between mid and the natural.
*System design note:* Mid-price is the starting point for the **order execution engine's** limit price. The system starts at mid and walks toward the natural in $0.01-0.05 increments every N seconds until filled or until a maximum deviation is reached.

**Natural vs Improvement**
"Natural" = bid for sells, ask for buys (worst case). "Improvement" = any fill better than natural. For a credit spread, the natural fill is: sell short leg at bid, buy long leg at ask. An improved fill would be anywhere between natural and mid. The execution engine's job is to maximize improvement.
*System design note:* The **execution engine** reports improvement per trade. A fill at mid = 100% improvement; at natural = 0%. Target: >50% average improvement for liquid underlyings.

**Complex Order**
Submitting a multi-leg options order as a single unit (e.g., the entire iron condor as one order). The exchange matches it atomically — you either get all legs filled or none. This eliminates "leg risk" (getting filled on the short leg but not the protective long leg).
*System design note:* The **order generator** always submits multi-leg strategies as complex orders. The system never legs into positions — the operational risk is not worth the potential $0.01-0.02 improvement.

**Leg Risk**
The risk of being partially filled when entering a multi-leg trade one leg at a time. If you sell the put spread and fail to execute the call spread, you have an unintended directional position. Avoided by using complex orders.
*System design note:* The **risk governor** enforces that all multi-leg strategies are submitted as complex orders. If a complex order is not supported (rare for standard strategies on major exchanges), the system alerts for manual execution.

### Tax Concepts

**Section 1256 Contracts (60/40 Rule)**
IRS code applying to certain derivatives including broad-based index options (SPX, XSP, VIX options). Gains and losses are marked-to-market at year-end and taxed as 60% long-term capital gains / 40% short-term capital gains regardless of actual holding period. This provides a significant tax advantage for active traders since the blended rate is lower than ordinary short-term rates.
*System design note:* The **tax module** classifies each position as 1256-eligible or not. At year-end, it computes the MTM gain/loss for all 1256 positions and calculates the blended tax rate. SPX preference over SPY (which is NOT 1256) is a configurable system parameter.

**Wash Sale Rule for Options**
IRS rule disallowing the deduction of a loss when you sell a security at a loss and buy a "substantially identical" security within 30 days before or after. For options, "substantially identical" is ambiguous — the IRS has not clearly defined when two options are similar enough to trigger a wash sale. Conservative approach: options on the same underlying with similar strike and expiration are substantially identical.
*System design note:* The **pre-trade compliance checker** maintains a 30-day rolling window of closed losses. Before entering a new trade, it checks for wash sale exposure. If a potential wash sale is detected, it either blocks the trade or flags it for manual review.

**Straddle Rules (IRS Section 1092)**
When you hold offsetting positions (positions that reduce risk), the IRS may defer recognition of losses until you close the offsetting gain position. This can apply to options positions like iron condors where one side has a loss and the other has a gain.
*System design note:* The **tax module** tracks potentially offsetting positions and computes whether straddle rules apply. This affects year-end tax optimization (which positions to close for tax-loss harvesting).

**Constructive Sale (Section 1259)**
If you enter a position that effectively eliminates substantially all risk of loss and opportunity for gain on an existing position, the IRS treats it as a sale. Most relevant for collars and deep ITM covered calls. Rarely triggered by credit spread strategies.
*System design note:* The **compliance checker** flags any position that might trigger a constructive sale — primarily relevant if the system ever manages equity positions alongside options.

---
---

## SECTION 3 — 10 PRACTICE EXERCISES

### Exercise 1: Pull and Visualize an Options Chain IV Smile
**Description:** Retrieve the full options chain for AAPL using `yfinance`. Extract calls and puts for the nearest monthly expiration. Compute IV for each strike (yfinance provides IV, but verify by re-computing with your own BS solver). Plot IV vs strike price (the "smile" or "skew").

**Expected Output:** A chart showing IV (y-axis) vs strike (x-axis) with a characteristic downward-sloping "smirk" — OTM puts have higher IV than OTM calls. Annotate the ATM strike and the 25-delta put/call IV levels.

**Libraries:** `yfinance`, `numpy`, `scipy.optimize` (for IV solver), `matplotlib`

**Approximate Time:** 2-3 hours

**System Component Validated:** The **data feed ingestion** pipeline and the **IV solver**. This confirms you can pull live data, parse the chain structure, and extract IV — the first step in any options system.

---

### Exercise 2: Compute the Volatility Risk Premium for SPY
**Description:** Download 5 years of SPY daily OHLC data and VIX closing prices. Compute 20-day trailing realized vol (close-to-close, annualized). Compute the VRP as: VIX(today) - subsequent 20-day realized vol. Plot the VRP time series. Compute statistics: mean, median, % of days positive, and the 5th/95th percentile.

**Expected Output:** A time series chart showing VRP oscillating around +2 to +4 vol points, with sharp negative spikes during market stress (2020, 2022). Summary statistics showing VRP is positive ~80-85% of the time but the negative tail reaches -15 to -20 vol points.

**Libraries:** `yfinance`, `pandas`, `numpy`, `matplotlib`

**Approximate Time:** 3-4 hours

**System Component Validated:** The **VRP calculator** — the core alpha signal. If VRP is persistently positive, the strategy premise (selling overpriced insurance) is valid. The distribution analysis reveals the risk of ruin during VRP inversion.

---

### Exercise 3: Paper Trade a Bull Put Credit Spread
**Description:** Select a bull put credit spread on SPY: sell a 30-DTE put at the 16-delta strike, buy a put $5 below. Record the entry credit, compute max profit, max loss, breakeven, and P(profit) using the BSM delta approximation. Track the position daily for the full 30 days (or close at 50% profit). Log each day: underlying price, position P&L, Greeks.

**Expected Output:** A trade journal with daily P&L tracking, a P&L curve over time, and final outcome. Comparison of actual P&L to the initial theoretical max profit and P(profit).

**Libraries:** `yfinance`, `numpy`, `scipy`, `pandas`, `matplotlib`

**Approximate Time:** 4-5 hours (including the 30-day monitoring period at ~10 min/day)

**System Component Validated:** The **trade constructor**, **position monitor**, and **exit manager** for credit spreads. This is a manual walkthrough of what the system will automate.

---

### Exercise 4: Build a Black-Scholes Pricer and Compare to Market
**Description:** Implement BSM call and put pricing from scratch. Fetch current market data for 10 AAPL options (mix of ITM, ATM, OTM across two expirations). For each, compute the BSM theoretical price using the option's IV. Compare model price to market mid-price.

**Expected Output:** A table showing each option's strike, expiry, type, market mid, BSM price, and residual. Residuals should be near zero (< $0.05) for liquid ATM options and slightly larger for OTM options where the model's lognormal assumption breaks down.

**Libraries:** `numpy`, `scipy.stats`, `yfinance`, `pandas`

**Approximate Time:** 2-3 hours

**System Component Validated:** The **pricing engine** — the most fundamental module. If your BSM implementation doesn't match market prices when fed market IV, there's a bug. This is a critical sanity check.

---

### Exercise 5: Plot the VIX Term Structure Over Time
**Description:** Download VIX, VIX3M (3-month VIX), and VIX9D (9-day VIX) from FRED or CBOE. Plot all three on the same chart over 2-5 years. Compute the ratio VIX/VIX3M and mark periods of backwardation (ratio > 1.0). Overlay major SPX drawdowns (> 5%) on the chart.

**Expected Output:** A multi-panel chart showing: (top) the three VIX measures over time, (bottom) the VIX/VIX3M ratio with a horizontal line at 1.0 and shaded regions for backwardation. Drawdown events should cluster in backwardation periods.

**Libraries:** `pandas_datareader` or `fredapi`, `yfinance`, `matplotlib`

**Approximate Time:** 3-4 hours

**System Component Validated:** The **regime classifier**. This exercise proves the concept that term structure shape is a reliable leading indicator of market stress. The VIX/VIX3M ratio becomes a configurable input to the risk governor.

---

### Exercise 6: Backtest Iron Condors on SPY
**Description:** Using historical options data (OptionsDX, CBOE DataShop, or synthetic chains generated from historical SPY data), backtest the following strategy on SPY from 2019-2024: enter a 45-DTE iron condor with 16-delta short strikes and $5 wings. Close at 50% profit, 200% loss, or 21 DTE, whichever comes first. Use bid-ask midpoint minus a $0.10 slippage penalty per leg.

**Expected Output:** Performance report: total return, annualized return, Sharpe ratio, max drawdown, win rate, average days in trade, average P&L per trade, largest winner, largest loser. Equity curve with drawdown plot. Comparison to buy-and-hold SPY.

**Libraries:** `pandas`, `numpy`, `matplotlib`, `scipy` (optional historical options data source)

**Approximate Time:** 8-12 hours (including data procurement and debugging)

**System Component Validated:** The **backtesting framework** end-to-end. This is the single most important exercise — it validates the data pipeline, strategy constructor, exit logic, and performance reporting all together.

---

### Exercise 7: Fit SVI to an SPX Expiration
**Description:** Pull the full SPX options chain for one expiration (choose one with 30-45 DTE). Convert strikes to log-moneyness k = ln(K/F). Convert IV to total implied variance w = IV² × T. Fit the SVI formula w(k) = a + b(ρ(k-m) + √((k-m)² + σ²)) using `scipy.optimize.minimize`. Extract the 5 parameters and plot the fit vs market data.

**Expected Output:** A chart showing market total variance points (dots) vs the SVI fit (smooth curve). Report the 5 fitted parameters with interpretation: a = base variance level, b = wing slope, ρ = skew direction and magnitude, m = horizontal shift, σ = smile curvature. Residual plot showing fit quality.

**Libraries:** `numpy`, `scipy.optimize`, `yfinance` or CBOE data, `matplotlib`

**Approximate Time:** 5-7 hours

**System Component Validated:** The **IV surface fitting module**. SVI is the core parametric model for the surface. Getting a good fit with reasonable parameters is the foundation for accurate pricing of illiquid strikes and consistent Greeks computation.

---

### Exercise 8: Half-Kelly Position Sizer for Credit Spreads
**Description:** Implement the Kelly criterion adapted for credit spreads: f* = (b × p - q) / b, where b = credit / (width - credit), p = P(profit), q = 1 - p. Apply half-Kelly: allocate = f* / 2 × account equity. Add constraints: max 5% of equity per trade, max 30% total portfolio heat. Test with 20 candidate trades of varying P(profit) and credit/width ratios.

**Expected Output:** A table showing each candidate trade, its full Kelly allocation, half-Kelly allocation, and the constrained allocation after applying per-trade and portfolio caps. A sensitivity analysis showing how allocation changes as P(profit) varies by ±5% — this reveals the danger of overconfident probability estimates.

**Libraries:** `numpy`, `pandas`, `matplotlib`

**Approximate Time:** 3-4 hours

**System Component Validated:** The **position sizer** — the module that converts a signal score into an actual dollar commitment. The sensitivity analysis is critical: it shows that small errors in P(profit) estimation translate to large changes in position size, justifying the use of half-Kelly.

---

### Exercise 9: Portfolio Greeks Dashboard
**Description:** Build a real-time dashboard that displays portfolio-level Greeks for a multi-position portfolio. Seed it with 3 open positions: 1 SPY iron condor, 1 AAPL bull put spread, 1 QQQ calendar spread. Compute and display: net delta, gamma, theta, vega for each position and the portfolio total. Add a stress test panel: show P&L impact of (-2%, -1%, 0%, +1%, +2%) underlying moves combined with (-3, 0, +3) IV shocks.

**Expected Output:** A dashboard (Streamlit, Dash, or React) showing a Greeks summary table, a theta decay projection chart, and a stress test heatmap (9 cells: 3 price scenarios × 3 vol scenarios). Update every 60 seconds during market hours.

**Libraries:** `streamlit` or `dash`, `yfinance`, `numpy`, `scipy`, `pandas`

**Approximate Time:** 8-10 hours

**System Component Validated:** The **portfolio dashboard** and **scenario engine**. This is the operator's primary interface for monitoring the system. The stress test grid is the most actionable view — it tells you your worst-case P&L under realistic adverse scenarios.

---

### Exercise 10: Rules-Based Exit Manager
**Description:** Implement a complete exit manager that monitors open positions and triggers closes based on a priority-ordered rule set. Rules (checked in order): (1) profit target — close if unrealized P&L ≥ 50% of max profit; (2) stop loss — close if unrealized loss ≥ 200% of initial credit; (3) time exit — close if DTE ≤ 21; (4) delta stop — close if any short leg delta > 0.30; (5) IV exit — close if underlying IV rank drops below 20 (the VRP has likely collapsed). Run this against 1 year of paper or backtested trades.

**Expected Output:** For each trade, log which exit rule triggered, the DIT (days in trade), and the realized P&L. Aggregate statistics by exit type: "profit target exits averaged +$X, stop loss exits averaged -$Y, time exits averaged +$Z." Determine which rules add value and which are redundant.

**Libraries:** `pandas`, `numpy`, `yfinance`, `matplotlib`

**Approximate Time:** 6-8 hours

**System Component Validated:** The **exit manager** — the module that converts open positions into closed positions with realized P&L. The rule priority ordering and the per-rule performance attribution are critical for tuning the system. This is where most of the post-entry alpha comes from.

---
---

## SECTION 4 — KEY FORMULAS WITH PYTHON

### Black-Scholes Pricing (Call + Put)

```python
import numpy as np
from scipy.stats import norm

def black_scholes(S: float, K: float, T: float, r: float, sigma: float, 
                  option_type: str = 'call') -> float:
    """
    Black-Scholes option pricing.
    
    Parameters:
        S: Current underlying price
        K: Strike price
        T: Time to expiration in years (e.g., 30/365 for 30 calendar days)
        r: Risk-free interest rate (annualized, e.g., 0.05 for 5%)
        sigma: Volatility (annualized, e.g., 0.20 for 20%)
        option_type: 'call' or 'put'
    
    Returns:
        Theoretical option price
    """
    if T <= 0:
        # At expiration: intrinsic value only
        if option_type == 'call':
            return max(S - K, 0.0)
        return max(K - S, 0.0)
    
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    
    if option_type == 'call':
        return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    else:
        return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


# Example usage
price = black_scholes(S=450, K=440, T=30/365, r=0.05, sigma=0.18, option_type='put')
print(f"Put price: ${price:.2f}")
```

---

### Analytical Greeks

```python
def greeks(S: float, K: float, T: float, r: float, sigma: float, 
           option_type: str = 'call') -> dict:
    """
    Compute analytical Greeks for a European option.
    
    Returns dict with: delta, gamma, theta (per day), vega (per 1% IV move), rho
    """
    if T <= 0:
        intrinsic = max(S - K, 0) if option_type == 'call' else max(K - S, 0)
        itm = intrinsic > 0
        return {
            'delta': (1.0 if itm else 0.0) * (1 if option_type == 'call' else -1),
            'gamma': 0.0, 'theta': 0.0, 'vega': 0.0, 'rho': 0.0
        }
    
    sqrt_T = np.sqrt(T)
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    
    # Gamma and Vega are the same for calls and puts
    gamma = norm.pdf(d1) / (S * sigma * sqrt_T)
    vega = S * norm.pdf(d1) * sqrt_T / 100  # per 1% IV move (divide by 100)
    
    if option_type == 'call':
        delta = norm.cdf(d1)
        theta = ((-S * norm.pdf(d1) * sigma / (2 * sqrt_T))
                 - r * K * np.exp(-r * T) * norm.cdf(d2)) / 365  # per calendar day
        rho = K * T * np.exp(-r * T) * norm.cdf(d2) / 100  # per 1% rate move
    else:
        delta = norm.cdf(d1) - 1  # negative for puts
        theta = ((-S * norm.pdf(d1) * sigma / (2 * sqrt_T))
                 + r * K * np.exp(-r * T) * norm.cdf(-d2)) / 365
        rho = -K * T * np.exp(-r * T) * norm.cdf(-d2) / 100
    
    return {
        'delta': delta,
        'gamma': gamma,
        'theta': theta,   # P&L per calendar day from time decay
        'vega': vega,      # P&L per 1 percentage point IV increase
        'rho': rho         # P&L per 1 percentage point rate increase
    }


# Example: ATM put on SPY
g = greeks(S=450, K=450, T=45/365, r=0.05, sigma=0.18, option_type='put')
for name, val in g.items():
    print(f"  {name:>6s}: {val:+.4f}")
```

---

### Implied Volatility Solver (Newton-Raphson)

```python
def implied_volatility(market_price: float, S: float, K: float, T: float, 
                       r: float, option_type: str = 'call',
                       tol: float = 1e-6, max_iter: int = 100) -> float:
    """
    Solve for implied volatility using Newton-Raphson.
    
    Uses vega as the derivative for fast convergence.
    Returns annualized IV (e.g., 0.20 = 20%).
    """
    # Initial guess: Brenner-Subrahmanyam approximation
    sigma = np.sqrt(2 * np.pi / T) * market_price / S
    sigma = max(sigma, 0.01)  # floor at 1%
    
    for i in range(max_iter):
        price = black_scholes(S, K, T, r, sigma, option_type)
        diff = price - market_price
        
        if abs(diff) < tol:
            return sigma
        
        # Vega (not divided by 100 here — we want d(price)/d(sigma))
        d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
        vega_raw = S * norm.pdf(d1) * np.sqrt(T)
        
        if vega_raw < 1e-12:
            break  # Vega too small, can't converge
        
        sigma -= diff / vega_raw
        sigma = max(sigma, 0.001)  # Keep positive
    
    return sigma  # Return best estimate even if not fully converged


# Example: solve for IV given a market price
iv = implied_volatility(market_price=8.50, S=450, K=440, T=30/365, 
                        r=0.05, option_type='put')
print(f"Implied Volatility: {iv*100:.2f}%")
```

---

### IV Rank and IV Percentile

```python
def iv_rank(current_iv: float, iv_series: np.ndarray) -> float:
    """
    IV Rank: where current IV sits in its high-low range.
    
    Formula: (current - 52wk_low) / (52wk_high - 52wk_low) * 100
    Returns 0-100. High = IV is near its annual high.
    """
    iv_high = np.max(iv_series)
    iv_low = np.min(iv_series)
    if iv_high == iv_low:
        return 50.0  # No range, return midpoint
    return (current_iv - iv_low) / (iv_high - iv_low) * 100


def iv_percentile(current_iv: float, iv_series: np.ndarray) -> float:
    """
    IV Percentile: % of days in the lookback where IV was lower than today.
    
    More robust than IV rank (not distorted by a single spike day).
    Returns 0-100. High = IV is higher than usual.
    """
    return np.mean(iv_series < current_iv) * 100


# Example: 1-year IV history
np.random.seed(42)
iv_history = np.random.normal(0.18, 0.04, 252)  # Simulated 1-year IV
iv_history = np.clip(iv_history, 0.08, 0.50)
current = 0.25

print(f"Current IV: {current*100:.1f}%")
print(f"IV Rank: {iv_rank(current, iv_history):.1f}")
print(f"IV Percentile: {iv_percentile(current, iv_history):.1f}")
```

---

### Probability of Profit for Credit Spreads

```python
def credit_spread_probability_of_profit(
    S: float, short_strike: float, T: float, r: float, sigma: float,
    spread_type: str = 'bull_put'
) -> float:
    """
    Estimate P(profit) for a credit spread at expiration.
    
    Uses the BSM lognormal distribution (risk-neutral).
    For a bull put spread: P(profit) = P(S > short_strike at expiry)
    For a bear call spread: P(profit) = P(S < short_strike at expiry)
    
    Note: This is a risk-neutral probability. Real-world probability is 
    slightly higher for OTM options due to the equity risk premium.
    """
    d2 = (np.log(S / short_strike) + (r - 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    
    if spread_type == 'bull_put':
        return norm.cdf(d2)  # P(S_T > K)
    elif spread_type == 'bear_call':
        return norm.cdf(-d2)  # P(S_T < K)
    else:
        raise ValueError("spread_type must be 'bull_put' or 'bear_call'")


def credit_spread_metrics(
    S: float, short_strike: float, long_strike: float, 
    credit: float, T: float, r: float, sigma: float,
    spread_type: str = 'bull_put'
) -> dict:
    """
    Complete credit spread analysis.
    """
    width = abs(short_strike - long_strike)
    max_profit = credit
    max_loss = width - credit
    
    if spread_type == 'bull_put':
        breakeven = short_strike - credit
    else:
        breakeven = short_strike + credit
    
    p_profit = credit_spread_probability_of_profit(S, short_strike, T, r, sigma, spread_type)
    expected_value = p_profit * max_profit - (1 - p_profit) * max_loss
    
    return {
        'max_profit': max_profit,
        'max_loss': max_loss,
        'breakeven': breakeven,
        'width': width,
        'p_profit': p_profit,
        'expected_value': expected_value,
        'reward_risk_ratio': max_profit / max_loss,
    }


# Example: SPY bull put spread
metrics = credit_spread_metrics(
    S=450, short_strike=435, long_strike=430,
    credit=1.25, T=45/365, r=0.05, sigma=0.18,
    spread_type='bull_put'
)
for k, v in metrics.items():
    if isinstance(v, float):
        print(f"  {k}: {v:.4f}")
```

---

### Kelly Criterion for Defined-Risk Strategies

```python
def kelly_credit_spread(
    p_profit: float, credit: float, width: float, 
    fraction: float = 0.5
) -> float:
    """
    Kelly criterion adapted for credit spreads.
    
    Parameters:
        p_profit: Estimated probability of profit (0-1)
        credit: Net credit received per spread
        width: Strike width (max_loss + credit)
        fraction: Kelly fraction (0.5 = half-Kelly, recommended)
    
    Returns:
        Fraction of equity to allocate to this trade (0-1)
    """
    max_loss = width - credit
    b = credit / max_loss  # Payoff ratio (profit / loss)
    q = 1 - p_profit
    
    # Full Kelly
    f_star = (b * p_profit - q) / b
    
    # Apply fraction and floor at 0
    return max(f_star * fraction, 0.0)


def position_size(
    equity: float, kelly_fraction: float, width: float,
    max_per_trade: float = 0.05, max_portfolio_heat: float = 0.30,
    current_heat: float = 0.0
) -> int:
    """
    Convert Kelly fraction to actual number of contracts.
    
    Parameters:
        equity: Total account equity
        kelly_fraction: Output of kelly_credit_spread()
        width: Strike width in dollars
        max_per_trade: Maximum % of equity risked per trade
        max_portfolio_heat: Maximum total % of equity at risk
        current_heat: Current portfolio heat (sum of all open max losses / equity)
    
    Returns:
        Number of contracts to trade
    """
    # Dollar amount Kelly says to risk
    kelly_dollars = equity * kelly_fraction
    
    # Cap at per-trade maximum
    per_trade_cap = equity * max_per_trade
    capped_dollars = min(kelly_dollars, per_trade_cap)
    
    # Cap at remaining portfolio heat budget
    remaining_heat = max(0, equity * max_portfolio_heat - equity * current_heat)
    capped_dollars = min(capped_dollars, remaining_heat)
    
    # Convert dollars at risk to contracts
    risk_per_contract = width * 100  # Each contract = 100 shares
    contracts = int(capped_dollars / risk_per_contract)
    
    return max(contracts, 0)


# Example
equity = 100_000
kelly_f = kelly_credit_spread(p_profit=0.82, credit=1.25, width=5.0, fraction=0.5)
contracts = position_size(equity, kelly_f, width=5.0, current_heat=0.15)
print(f"Half-Kelly fraction: {kelly_f:.4f}")
print(f"Contracts to trade: {contracts}")
print(f"Capital at risk: ${contracts * 5 * 100:,.0f} ({contracts * 5 * 100 / equity:.1%} of equity)")
```

---

### Realized Volatility Estimators

```python
def realized_vol_close_to_close(prices: np.ndarray, window: int = 20, 
                                  annualize: int = 252) -> np.ndarray:
    """
    Standard close-to-close realized volatility.
    Annualized standard deviation of log returns.
    """
    log_returns = np.log(prices[1:] / prices[:-1])
    rv = np.full(len(prices), np.nan)
    for i in range(window, len(log_returns) + 1):
        rv[i] = np.std(log_returns[i-window:i], ddof=1) * np.sqrt(annualize)
    return rv


def realized_vol_parkinson(high: np.ndarray, low: np.ndarray, 
                           window: int = 20, annualize: int = 252) -> np.ndarray:
    """
    Parkinson (1980) high-low range estimator.
    ~5x more efficient than close-to-close (uses intraday range info).
    
    Formula: sigma^2 = (1 / 4*ln(2)) * mean(ln(H/L)^2)
    """
    log_hl = np.log(high / low)
    rv = np.full(len(high), np.nan)
    factor = 1.0 / (4.0 * np.log(2.0))
    for i in range(window, len(log_hl)):
        variance = factor * np.mean(log_hl[i-window:i]**2)
        rv[i] = np.sqrt(variance * annualize)
    return rv


def realized_vol_garman_klass(open_: np.ndarray, high: np.ndarray, 
                               low: np.ndarray, close: np.ndarray,
                               window: int = 20, annualize: int = 252) -> np.ndarray:
    """
    Garman-Klass (1980) OHLC estimator.
    Uses open, high, low, close for maximum efficiency.
    """
    log_hl = np.log(high / low)
    log_co = np.log(close / open_)
    
    rv = np.full(len(close), np.nan)
    for i in range(window, len(close)):
        hl = log_hl[i-window:i]
        co = log_co[i-window:i]
        variance = np.mean(0.5 * hl**2 - (2*np.log(2) - 1) * co**2)
        rv[i] = np.sqrt(max(variance, 0) * annualize)
    return rv


def realized_vol_yang_zhang(open_: np.ndarray, high: np.ndarray,
                            low: np.ndarray, close: np.ndarray,
                            window: int = 20, annualize: int = 252) -> np.ndarray:
    """
    Yang-Zhang (2000) estimator.
    Handles overnight gaps and opening jumps. Best overall estimator for equities.
    
    Combines overnight (close-to-open), open-to-close, and Rogers-Satchell components.
    """
    n = len(close)
    rv = np.full(n, np.nan)
    
    for i in range(window + 1, n):
        idx = slice(i - window, i)
        
        # Overnight returns: log(open_t / close_{t-1})
        log_oc = np.log(open_[idx][1:] / close[idx][:-1])  # need offset
        # Use simpler indexing
        o = open_[i-window:i]
        h = high[i-window:i]
        l = low[i-window:i]
        c = close[i-window:i]
        c_prev = close[i-window-1:i-1]
        
        log_overnight = np.log(o / c_prev)
        log_open_close = np.log(c / o)
        
        # Rogers-Satchell component
        log_ho = np.log(h / o)
        log_lo = np.log(l / o)
        log_hc = np.log(h / c)
        log_lc = np.log(l / c)
        rs = np.mean(log_ho * log_hc + log_lo * log_lc)
        
        k = 0.34 / (1.34 + (window + 1) / (window - 1))
        
        sigma_overnight = np.var(log_overnight, ddof=1)
        sigma_open_close = np.var(log_open_close, ddof=1)
        
        variance = sigma_overnight + k * sigma_open_close + (1 - k) * rs
        rv[i] = np.sqrt(max(variance, 0) * annualize)
    
    return rv


# Example usage with synthetic data
np.random.seed(42)
n_days = 300
prices = 450 * np.exp(np.cumsum(np.random.normal(0.0003, 0.01, n_days)))
# Simulate OHLC
opens = prices * np.exp(np.random.normal(0, 0.002, n_days))
highs = np.maximum(prices, opens) * np.exp(np.abs(np.random.normal(0, 0.005, n_days)))
lows = np.minimum(prices, opens) * np.exp(-np.abs(np.random.normal(0, 0.005, n_days)))
closes = prices

rv_cc = realized_vol_close_to_close(closes)
rv_pk = realized_vol_parkinson(highs, lows)
rv_gk = realized_vol_garman_klass(opens, highs, lows, closes)
rv_yz = realized_vol_yang_zhang(opens, highs, lows, closes)

# Compare at the last data point
idx = -1
print(f"Close-to-Close: {rv_cc[idx]*100:.2f}%")
print(f"Parkinson:      {rv_pk[idx]*100:.2f}%")
print(f"Garman-Klass:   {rv_gk[idx]*100:.2f}%")
print(f"Yang-Zhang:     {rv_yz[idx]*100:.2f}%")
```

---

### Quick Reference: System Module → Formula Mapping

| System Module | Primary Formula | Section |
|---|---|---|
| Pricing Engine | Black-Scholes (call + put) | BSM Pricing |
| IV Solver | Newton-Raphson on BSM | IV Solver |
| Greeks Engine | Analytical delta, gamma, theta, vega | Greeks |
| Risk Monitor | Portfolio Greeks aggregation + scenario shocks | Greeks |
| VRP Calculator | IV - Realized Vol (Yang-Zhang) | RV Estimators |
| Entry Filter | IV Rank > threshold AND VRP > threshold | IV Rank/Percentile |
| Signal Scorer | Expected Value = P(profit) × max_profit - P(loss) × max_loss | P(profit) |
| Position Sizer | Half-Kelly × constraint caps | Kelly Criterion |
| IV Surface | SVI fit (see Exercise 7) | Week 17 |
| Regime Classifier | VIX/VIX3M ratio + GARCH forecast | Week 15-16 |
| Exit Manager | Rule-based (profit %, loss %, DTE, delta) | Exercise 10 |
| Backtest Engine | All of the above + slippage model | Week 20 |
| Tax Module | Section 1256 60/40 blended rate | Week 23 |

---

*Document prepared for system builders. Every concept maps to code. Build the modules, connect the interfaces, validate with backtests, then deploy on paper.*
