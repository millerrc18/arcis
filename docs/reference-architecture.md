# Autonomous AI Quant Trading: Reference Architecture

Research date: 2026-09-11

## Scope and conclusion

This design assumes a platform that autonomously initiates and manages buy and sell orders through broker or venue APIs. It does not assume that a probabilistic model is allowed to bypass risk controls. Autonomy means that no person approves each order; it does not mean unlimited authority. The precise operating model is **bounded autonomous trading**.

The first release must freeze one broker, account type, asset class, venue model, order-type subset, and holding-period range. Equities, options, futures, and crypto cannot safely share an initial generic control model because their margin, short-sale, expiration, session, market-data, and recovery semantics differ materially.

The recommended design is a hierarchical, constrained trading system, not an LLM with a brokerage tool and not a single end-to-end reinforcement-learning policy. Learned components estimate returns, risk, liquidity, and execution outcomes. A constrained portfolio policy determines target positions. An autonomous execution policy creates orders. A separate deterministic gateway enforces non-negotiable limits before any order leaves the platform.

This is engineering and model-risk guidance, not investment or legal advice. Requirements differ by asset class, jurisdiction, broker relationship, and whether the platform trades only owner capital or serves clients.

## Reference architecture

```text
Licensed market/fundamental/text data
                  |
        Point-in-time data plane
       lineage, quality, timestamps
                  |
       Feature and state service
                  |
       +----------+-----------+
       |                      |
 Alpha/risk ensemble    Isolated text extractor
 distributions + OOD   schema + provenance only
       |                      |
       +----------+-----------+
                  |
      Constrained portfolio policy
      target positions + abstention
                  |
       Autonomous execution policy
       side/qty/type/price/TIF/schedule
                  |
   Deterministic pre-trade policy shield
   limits, collars, throttles, reservations
                  |
        Event-sourced OMS/router
                  |
              Broker/venue
                  |
    Independent acknowledgements/drop copy
                  |
     Reconciliation and safety monitor
```

The model can autonomously call `submit_order`, but that operation accepts only a typed order intent and is mediated by the policy shield. The model has no direct network route to the broker, no access to credentials, and no permission to modify limits, code, models, or deployment configuration.

## The trading model

### 1. State and features

At decision time `t`, the state contains only information actually observable at `t`:

- Market state: prices, returns, spreads, depth, volume, volatility, halts, auction state, and synchronized timestamps.
- Portfolio state: broker-confirmed positions, cash, margin, open orders, fills, realized PnL, and reserved risk.
- Instrument state: corporate actions, borrow status, contract roll, tick/lot sizes, session calendar, and restrictions.
- Optional fundamentals and text-derived facts with publication, receipt, and processing timestamps.
- System state: feed age, broker connectivity, inference latency, reconciliation status, and active safety mode.

Any feature whose source time, availability time, or lineage is unknown is ineligible for live decisions or historical validation.

### 2. Distributional alpha and risk ensemble

The initial production ensemble should combine models with different failure modes:

- A regularized linear model as the interpretable baseline.
- Gradient-boosted trees for nonlinear interactions and missing-value robustness.
- A temporal neural model only when it produces repeatable net improvement after costs and multiple-testing correction.

For each instrument and horizon, output a distribution rather than a point forecast:

```text
expected excess return
downside and upside return quantiles
volatility and covariance contribution
probability of positive net return
expected spread, slippage, and fill probability
epistemic uncertainty / out-of-distribution score
```

Probabilities and quantiles require rolling out-of-sample calibration conditional on regime, forecast horizon, and liquidity bucket. High uncertainty or out-of-distribution state produces `ABSTAIN`, not a smaller invented confidence score. OOD detection is an additional no-trade signal, never a safety boundary; deterministic limits remain authoritative.

### 3. Portfolio policy

The policy selects target weights or target positions, not isolated trades. A representative objective is:

```text
maximize:
  expected_net_return
  - risk_penalty
  - expected_transaction_cost
  - uncertainty_penalty
  - concentration_penalty
  - turnover_penalty
  - tail_loss_penalty
```

Subject to hard cash, margin, gross, net, instrument, sector, liquidity, turnover, borrow, and exposure constraints. Derivatives require instrument-specific delta, gamma, vega, expiry, assignment, and stress-margin constraints. The optimizer must return an explicit infeasible result rather than silently relaxing hard limits.

### 4. Autonomous execution policy

The execution policy converts the delta between broker-confirmed and target positions into actual orders. It chooses side, quantity, order type, price, time-in-force, urgency, and child-order schedule. Start with deterministic execution algorithms informed by learned fill and slippage estimates. Offline RL may later optimize execution, but only within the same action schema and policy shield.

A valid order intent resembles:

```yaml
{
  decision_id: immutable-id,
  instrument: venue-qualified-symbol,
  side: BUY,
  target_position: 100,
  max_quantity: 20,
  order_type: LIMIT,
  limit_price: 101.25,
  time_in_force: DAY,
  urgency: 0.35,
  expires_at: timestamp,
  expected_net_alpha_bps: 8.2,
  downside_quantile_bps: -14.0,
  expected_cost_bps: 2.7,
  uncertainty: 0.18,
  model_version: signed-artifact-id
}
```

Free-form model text is never executable. Every field is schema-validated, range-checked, timestamped, and bound to a particular strategy and account.

## Policy shield and risk ownership

The deterministic gateway is a separate service and security boundary. Its atomic risk ledger includes broker-confirmed positions, open orders, pending submissions, partial fills, cancel-pending orders, buying power, locate reservations, and worst-case exposure. It reserves risk before transmission so concurrent strategies cannot each consume the same remaining limit, and releases reservations only after authoritative terminal states.

Every order is checked for:

- Data freshness, clock synchronization, venue session, halt, and instrument eligibility.
- Maximum order quantity/notional, fat-finger price collars, and limit-price distance.
- Broker-confirmed plus pending position, cash, margin, leverage, and concentration.
- Gross/net, factor, sector, correlated exposure, liquidity, and participation limits.
- Message-rate and cancel-rate throttles, duplicate intent, and self-trade prevention across strategies.
- Independent loss budgets using conservative marks, realized and unrealized PnL, pending-order exposure, accrued financing and borrow cost, and stale-price haircuts.
- Daily loss, drawdown, volatility, rejected-order, reconciliation, and connectivity circuit breakers.
- Restricted instruments, short/borrow rules, account permissions, and broker-specific constraints.

An intent-independent surveillance service must also detect spoofing/layering patterns, wash behavior across strategies or accounts, excessive cancellation, marking the open or close, momentum ignition, and feedback between the strategy and its own orders. Self-match prevention alone is insufficient.

Limits are configuration-controlled and cannot be changed by the AI. Critical limits should also be configured at the broker or venue when supported. A local control alone is not an adequate final barrier.

## Order and failure semantics

The order management system is event sourced and uses an explicit state machine, including `INTENT`, `RISK_RESERVED`, `SUBMITTING`, `ACKNOWLEDGED`, `PARTIALLY_FILLED`, `FILLED`, `CANCEL_PENDING`, `CANCELED`, `REJECTED`, and `UNKNOWN`.

Exactly-once network delivery cannot be assumed. Use unique client order IDs, durable intent recording before transmission, idempotent broker semantics where available, and reconciliation before retry. If submission times out, quarantine the affected symbol or account, reserve worst-case exposure, query by client order ID and account state, and never blindly resubmit.

An independent execution-report or drop-copy path reconciles internal state with the broker. Any unexplained position, open-order, cash, or fill mismatch blocks new risk. Recovery must prevent active/standby split brain.

The platform itself has a machine-tested safety state machine: `NORMAL`, `DEGRADED_DATA`, `CANCEL_ONLY`, `RECONCILING`, `BLOCK_NEW_RISK`, `LIQUIDATION`, and `HALTED`. Each state defines permitted actions, transition triggers, recovery evidence, and operator authority. Market-data handling includes sequence-gap detection, exchange timestamps, synchronized clocks, crossed/locked-market behavior, corporate-action normalization, trading-status and LULD feeds, independent price validation, and explicit behavior when sources disagree.

Safety responses are ordered:

1. Cancel working orders where cancellation state is known.
2. Block orders that add risk.
3. Preserve or reduce positions according to a separately tested safe-state policy.
4. Flatten only when the liquidation policy determines that immediate liquidation is safer than holding.

An unconditional market-order flatten can amplify losses during halts, crossed feeds, illiquidity, or a compromised broker connection, so it is not the universal response.

## LLM boundary

An LLM may extract cited facts from filings, earnings calls, or news and assist offline research. It must be isolated from the execution identity and broker network. External text is untrusted data, not instructions. The extractor returns a strict schema plus immutable source spans; unsupported or conflicting facts are rejected or marked unknown. The strategy must remain safe with all text features disabled, and text features initially receive zero or tightly capped risk allocation.

The live trading path should not depend on chain-of-thought, conversational memory, or an LLM deciding whether a risk rule applies. Prompt injection, model-version drift, provider outages, and nondeterminism make an LLM inappropriate as the final order authority.

## Validation program

### Statistical validity

- Use point-in-time, survivorship-free universes and preserve publication and revision history.
- Prevent leakage from normalization, feature selection, labels, overlapping horizons, and corporate-action processing.
- Use walk-forward evaluation; purge and embargo overlapping label intervals where applicable.
- Keep a final test period untouched by feature selection, tuning, model choice, and threshold setting.
- Record every meaningful trial. Correct for selection using the Deflated Sharpe Ratio, Probability of Backtest Overfitting, or an appropriate multiple-testing procedure.
- Evaluate the concatenated out-of-sample return stream after commissions, spread, slippage, borrow, financing, latency, partial fills, rejected orders, taxes where relevant, and market impact.
- Report uncertainty around performance, tail loss, turnover, capacity, and regime dependence. Do not approve based on a single Sharpe ratio.

There is no universal acceptable Sharpe, PBO, drawdown, drift threshold, or paper-trading duration. Acceptance criteria must be preregistered from the strategy horizon, number of independent observations, liquidity, capital at risk, and maximum tolerable loss.

### System and safety validity

- Exactly replay stored inputs, decisions, risk results, orders, and fills, and reproduce model reconstruction within declared tolerances. Bit-for-bit replay cannot be assumed for hosted models, nondeterministic hardware, or external broker state.
- Property-test that no generated action can violate hard risk invariants.
- Simulate stale/corrupt/missing data, extreme gaps, halts, splits, delistings, contract rolls, and negative prices.
- Inject latency, disconnects, duplicated/reordered messages, partial fills, lost acknowledgements, broker rejects, and process crashes.
- Test simultaneous strategies for race conditions, aggregate limit breaches, and self-matches.
- Red-team prompt injection, data poisoning, dependency/model compromise, secret leakage, and unauthorized tool calls.
- Verify cancel-on-disconnect, restart recovery, broker reconciliation, kill-switch operation, and safe-state behavior.

### Deployment gates

```text
research backtest
  -> locked out-of-sample evaluation
  -> historical exchange/broker replay
  -> broker sandbox
  -> live shadow decisions
  -> paper order routing
  -> bounded canary capital
  -> staged capital increases
```

Paper trading primarily validates plumbing; it does not establish fill realism or profitability. Canary capital is bounded by a worst-case loss the owner has explicitly accepted. Promotion requires enough independent decisions and market regimes to evaluate the preregistered criteria, not merely a fixed number of days.

Before testing begins, define measurable limits for constraint violations, reconciliation breaks, reject and cancel rates, slippage-model error, calibration error, exposure, loss, recovery time, and rollback time. Terms such as validated simulator, tiny capital, and successful canary are not gates until expressed as testable criteria.

## Monitoring and automatic intervention

Monitor four layers independently:

- Data: freshness, gaps, revisions, distribution shift, source disagreement, and lineage failures.
- Model: calibration, residuals, uncertainty, OOD rate, feature contribution drift, and challenger disagreement.
- Trading: exposure, turnover, limit usage, PnL attribution, implementation shortfall, fill/reject/cancel rates, and adverse selection.
- Platform: inference and order latency, queue lag, broker heartbeat, clock skew, error rate, reconciliation breaks, and unauthorized access.

Safety triggers should be deterministic, persistent across restart, and tested as carefully as entry logic. A model rollback does not undo positions, so rollback and position-management procedures are separate.

## Records and security

Store an append-only decision record with source timestamps, feature and data versions, signed model hash, model outputs, uncertainty, target positions, optimizer result, risk reservations, every rule result, client/broker order IDs, acknowledgements, state transitions, and fills.

Broker credentials live only in the gateway, use least privilege, exclude withdrawal authority, and are IP/network restricted where supported. The model process has no network route to the broker, no deployment permission, and no write access to risk configuration. Use separate identities and failure domains for model inference, execution, and administration; short-lived trade-only credentials where supported; signed configuration; and dual authorization for limit increases. Sign model artifacts, pin dependencies, maintain an AI/software bill of materials, and do not log secrets or unrestricted raw prompts.

Production behavior is immutable between approved releases: no online learning, autonomous retraining, prompt changes, feature-schema changes, or intraday model promotion. Every behavioral change creates a new signed artifact and repeats the applicable validation and canary gates.

## Governance and regulatory boundary

For a person trading only personal capital, broker terms and universal market-conduct rules remain relevant, but many cited supervisory rules directly bind brokers or registered firms rather than the individual trader. Selling the platform, managing outside capital, pooling money, providing personalized advice, liquidity-provision activity, trading commodity interests, entity structure, or operating across jurisdictions can trigger broker-dealer, investment-adviser, dealer, CTA/CPO, NFA, privacy, recordkeeping, and other obligations. Counsel should classify the actual business and trading model before broker connectivity is enabled.

SEC Rule 15c3-5 and FINRA guidance are used here as engineering benchmarks for pre-trade control, testing, supervision, and auditability. Federal Reserve SR 26-2 is a model-risk benchmark for banking organizations, not a rule for an independent trader. CFTC Staff Advisory 24-17 is non-binding guidance for CFTC-regulated entities. Do not misstate these as direct universal obligations.

## Approaches rejected for the initial release

- An LLM with direct broker credentials: prompt-injection and nondeterministic-action risk are unacceptable.
- Pure end-to-end RL from market observation to unrestricted orders: live distribution shift, simulator error, and off-policy extrapolation are not adequately controlled.
- A second probabilistic model as the only risk approver: correlated model failures can pass the same bad action.
- Automatic online learning with immediate deployment: it collapses validation and production into one uncontrolled experiment.
- Blind retry after an order timeout: it can duplicate exposure.
- Unconditional flatten-on-error: liquidation itself can be the highest-risk action.

## Minimum viable implementation

The first production candidate should trade one liquid asset class at one moderate decision horizon with one broker. Use a simple calibrated alpha ensemble, a deterministic constrained optimizer, and deterministic execution logic. Add learned execution only after live slippage and fill data establish a credible simulator. Add text-derived features only after the numeric trading path is stable. Expand assets, brokers, and autonomy one independently validated dimension at a time.

## Primary and original sources

### Market and model governance

- [NIST AI Risk Management Framework 1.0](https://doi.org/10.6028/NIST.AI.100-1), 2023.
- [NIST Generative AI Profile](https://doi.org/10.6028/NIST.AI.600-1), 2024.
- [IOSCO, Artificial Intelligence in Capital Markets](https://www.iosco.org/library/pubdocs/pdf/IOSCOPD788.pdf), consultation report, 2025.
- [Federal Reserve SR 26-2, Revised Guidance on Model Risk Management](https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm), 2026. Used as a benchmark, not as a direct rule for personal trading.

### Trading controls and supervision

- [SEC Rule 15c3-5, Market Access Rule](https://www.sec.gov/files/rules/final/2010/34-63241.pdf), 2010.
- [FINRA Regulatory Notice 15-09](https://www.finra.org/rules-guidance/notices/15-09), algorithmic-trading supervision and controls, 2015.
- [FINRA Regulatory Notice 24-09](https://www.finra.org/rules-guidance/notices/24-09), technology-neutral application of existing rules to GenAI, 2024.
- [CFTC Staff Advisory 24-17](https://www.cftc.gov/csl/24-17/download), non-binding AI advisory for regulated entities, 2024.
- [FIX Latest Specifications](https://www.fixtrading.org/standards/fix-latest/), order states and electronic order messaging.
- [CME Pre-Trade Risk Management](https://www.cmegroup.com/trading/pre-trade-risk-management.html), venue risk-control examples.
- [CME Self-Match Prevention](https://www.cmegroup.com/client-systems/cmeglobex-self-match-prevention.html), venue self-match controls.
- [EU Delegated Regulation 2017/589 (RTS 6)](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32017R0589), detailed algorithmic-trading systems and control requirements for in-scope EU firms.

### Statistical and learning research

- Bailey, Borwein, Lopez de Prado, and Zhu, [The Probability of Backtest Overfitting](https://doi.org/10.21314/JCF.2016.322).
- Bailey and Lopez de Prado, [The Deflated Sharpe Ratio](https://doi.org/10.3905/jpm.2014.40.5.094).
- Guo et al., [On Calibration of Modern Neural Networks](https://arxiv.org/abs/1706.04599), 2017.
- Achiam et al., [Constrained Policy Optimization](https://arxiv.org/abs/1705.10528), 2017.
- Kumar et al., [Conservative Q-Learning for Offline Reinforcement Learning](https://arxiv.org/abs/2006.04779), 2020.
- Garcia and Fernandez, [A Comprehensive Survey on Safe Reinforcement Learning](https://jmlr.org/papers/v16/garcia15a.html), 2015.
- Almgren and Chriss, [Optimal Execution of Portfolio Transactions](https://www.math.uchicago.edu/~almgren/papers/opt_exec.pdf), execution-cost and risk tradeoff.

### Adversarial AI security

- [MITRE ATLAS](https://atlas.mitre.org/), adversarial threats to AI systems.
- [OWASP Top 10 for Agentic Applications](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/), agent goal hijack, tool misuse, identity, memory, and supply-chain risks.

## Independent AI critic review

An independent high-reasoning AI critic reviewed the proposed architecture before publication. It agreed that the system satisfies autonomous order placement and recommended the term bounded autonomous trading. Its launch-blocker findings were incorporated above: frozen initial scope, atomic worst-case risk reservations, conditional uncertainty semantics, independent account-loss controls, market-manipulation surveillance, stronger market-data integrity, quarantine of ambiguous orders, an explicit platform safety-state machine, physical execution isolation, prohibition on production self-modification, measurable preregistered launch gates, and legal classification before connectivity.

The critic also rejected treating regulatory benchmarks as universal direct obligations, treating OOD detection as a safety guarantee, treating statistical backtest controls as certification of safety or profitability, or treating a kill switch as synonymous with forced liquidation. Offline RL execution, formal verification, multi-broker failover, and advanced robust optimization remain later-stage improvements rather than launch prerequisites.

## Research limitations

Public research contains many profitable-looking RL backtests but little reproducible evidence of unconstrained end-to-end agents operating safely through regime changes with realistic market impact. Venue and broker capabilities also differ materially. The final design therefore requires broker-specific API and control verification, asset-class-specific legal review, and empirical calibration from the intended market and decision horizon.
