# Domain Preset: Trading

## Description

Quantitative finance, algorithmic trading strategies, risk management, portfolio construction, market microstructure, and financial engineering. Covers both theoretical foundations (asset pricing, stochastic calculus) and practical implementation (backtesting, execution, transaction costs).

## Preferred Sources

1. **SSRN** — Working papers and preprints in finance and economics
2. **Journal of Financial Economics** — Top-tier academic finance research
3. **Quantitative Finance** (journal) — Focused on quant methods and strategies
4. **NBER Working Papers** — Economic research from leading academics
5. **Quant forums** — Quantopian archives, QuantConnect community, Wilmott forums
6. **Broker research** — Interactive Brokers, Goldman Sachs, JP Morgan research notes
7. **Federal Reserve publications** — FRED data, Fed working papers
8. **AQR Capital research** — Publicly available factor research
9. **Journal of Portfolio Management** — Applied portfolio construction
10. **Risk.net** — Risk management and derivatives

## Lateral Search Strategy

| Adjacent Field | Why Cross-Pollinate |
|---------------|-------------------|
| **Signal processing** | Filtering noise from signal in time series is directly analogous to DSP; Kalman filters, wavelet analysis |
| **Ecology / Population dynamics** | Predator-prey models map to market participant dynamics; regime changes parallel ecosystem shifts |
| **Physics** | Mean reversion (Ornstein-Uhlenbeck), momentum (inertia), statistical mechanics (agent-based models) |
| **Sports analytics / Betting markets** | Kelly criterion, odds-making, edge quantification, bankroll management are isomorphic problems |
| **Machine learning** | Feature engineering, overfitting detection, cross-validation — but beware p-hacking in finance |

## Temporal Emphasis

Bimodal distribution — both foundational and strongly current sources are valuable, with a gap in between.

- **Half-life**: 2 years (for strategy-specific research)
- **Foundational corpus** (always relevant):
  - Fama & French (factor models, EMH)
  - Sharpe (CAPM, Sharpe ratio)
  - Black-Scholes-Merton (options pricing)
  - Markowitz (mean-variance optimization)
  - Kelly (optimal bet sizing)
  - Mandelbrot (fat tails, fractal markets)
- **Current emphasis**: Market microstructure evolves rapidly. Strategies that worked 5 years ago may be fully arbitraged. Regulatory changes (Reg NMS, MiFID II) alter market structure. Always check if findings predate major structural changes.

## Output Template Tweaks

Add the following sections to the standard report template:

### Backtest Considerations

[Discuss lookback period, survivorship bias, look-ahead bias, data-snooping risk, out-of-sample validation, and whether the strategy has been published (and thus potentially arbitraged).]

### Regime Sensitivity

[Analyze how findings or strategies perform across different market regimes: trending, mean-reverting, high-volatility, low-volatility, rising rates, falling rates. Identify regime detection methods if applicable.]

### Transaction Cost Impact

[Estimate the impact of realistic transaction costs on the strategy or finding: spreads, commissions, slippage, market impact, borrowing costs (for shorts), and funding costs. Note the breakeven frequency/turnover.]

## Example Queries

1. "Does mean reversion work in current equity markets?"
2. "Optimal position sizing for momentum strategies"
3. "What is the evidence for or against trend-following in futures markets?"
