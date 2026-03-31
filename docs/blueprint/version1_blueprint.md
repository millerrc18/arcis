> **DEPRECATION NOTICE**: This was the original v1 blueprint. See [docs/architecture.md](../architecture.md) for the current system architecture.

# Systematic Equity Research - Version 1 Blueprint (Historical)

## 1. Objective

Build a focused, always-on research workflow that monitors the S&P 100, identifies high-conviction short swing opportunities, generates institutional-style trade packets, emails those packets to Ryan's work email, logs every recommendation, and maintains a shadow paper-trading ledger so performance can be measured before live automation is considered.

Version 1 exists to answer one question:

**Can this system consistently surface useful trade ideas, package them well, and improve decision quality without hurting day-job performance?**

## 2. Scope

### In scope
- S&P 100 universe only
- Short swing focus
- Primary setup family: pullback in strong trend / relative strength continuation
- Flexible expected hold period, generally 2 to 10 trading days
- Morning watchlist, action packets, and end-of-day recap
- Quality-first idea selection with zero-forcing rule
- Email delivery to Ryan's work email
- Suggested position size framework based on $1,000 starting working capital
- Earnings-adjacent trades allowed with explicit event-risk labeling and more conservative sizing
- Shadow paper-trading ledger
- Central journal and post-trade review loop
- Local-first runtime with optional cloud backup later

### Out of scope for MVP
- Autonomous live order placement
- Intraday-first trading mode
- Options or other derivatives
- Margin-dependent strategies
- Broad multi-asset coverage
- Fine-tuning the LLM
- Heavy UI/dashboard work before the core loop is validated

## 3. Operating model

The assistant acts as an AI research analyst.

### Assistant responsibilities
- Scan the S&P 100 on a schedule
- Rank names by setup quality
- Generate a quick bullet brief plus deeper analysis only when a name clears a high threshold
- Send morning watchlist email with top candidates
- Send action packets only for packet-worthy setups
- Send end-of-day recap
- Log every recommendation whether Ryan acts on it or not
- Maintain a shadow paper trade for every qualified recommendation
- Learn from outcomes and post-trade feedback

### Ryan responsibilities
- Review packets
- Approve or pass
- Execute manually if desired
- Complete full post-trade review only for trades actually taken

## 4. Core design principles

1. Research first, execution later
2. Selective over busy
3. Structured output every time
4. Journal everything
5. Protect work performance
6. Build modularly for later scale

## 5. Universe and setup logic

### Universe
- S&P 100 only
- Prefer highly liquid names with clean execution characteristics

### Primary setup family
- Pullback in strong trend / relative strength continuation

### Plain-English interpretation
The assistant should look for stocks that are already acting strong relative to the market, have constructive medium-term trend structure, and then pull back into a zone where reward/risk becomes attractive for continuation.

## 6. Event-risk policy

### Current rule
Earnings-adjacent trades are allowed, but they are treated as a special case.

### Required packet treatment
- Show next earnings date
- State whether the expected hold window overlaps earnings
- Include elevated gap-risk warning
- State whether the thesis assumes exit before earnings or continued hold through the event
- Use more conservative sizing guidance than a normal trade

### Journal treatment
All earnings-adjacent trades should be tagged separately so they can be evaluated as a distinct risk class.

## 7. Position-sizing philosophy

Version 1 should include a suggested position-size framework based on $1,000 starting working capital.

### Default planned-risk framework
- Planned risk per trade: 0.5% to 1.0% of capital
- Approximate planned loss per trade: $5 to $10
- Max simultaneous positions: 2

### Packet sizing fields
- Suggested dollar allocation
- Percent of capital
- Estimated dollar risk to stop
- Flag if setup is not cleanly tradable at current account size

## 8. Daily cadence

### Morning
- Scan universe
- Produce 3 to 7 watchlist candidates
- Send morning watchlist email

### During market hours
- Re-evaluate candidates on a moderate schedule
- Generate action packet only when threshold clears
- Maintain shadow paper-trade entries for qualifying setups

### End of day
- Update open theses
- Summarize new recommendations
- Summarize shadow ledger status
- Record daily lessons and recap

## 9. Success metrics

### Process metrics
- Morning watchlist delivered reliably
- Action packets average roughly 3 to 5 per week when opportunity set supports it
- Zero packets acceptable in weak conditions
- Email workflow remains useful and non-disruptive
- Journal completeness on 100% of recommendations

### Performance metrics
- Shadow expectancy
- Win rate
- Average gain versus average loss
- Max drawdown
- Performance by confidence band
- Performance of earnings-adjacent trades versus normal trades

### Qualitative metrics
- Packet usefulness
- Defensibility of reasoning
- Reduction in missed opportunities
- Fit with workday demands

## 10. Technical architecture

### Core stack
- Python
- Alpaca paper trading
- vectorbt for fast idea testing
- LEAN as later promotion gate
- SQLite for MVP journal storage
- SMTP-based email delivery

### Functional modules
- Universe manager
- Market data ingestion
- Feature engine
- Opportunity ranker
- Packet generator
- Email notifier
- Shadow execution engine
- Journal store
- Evaluation engine

## 11. Promotion gates

The system should not gain more responsibility until it clears all of these:

1. Recommendation quality is consistently high
2. Shadow performance is acceptable
3. Workflow fits Ryan's real life
4. Journal is mature enough to support better ranking and future tuning

Only after that should the project consider:
- live approval-gated execution support
- expansion into intraday mode
- broader universes
- fine-tuning or additional model layers
