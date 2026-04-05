# Deep Research: Interactive Brokers Best Practices for Autonomous AI Trading Systems

## Context

Arcis is a solo-operated, autonomous AI equity trading system running 24/7 on Windows with an RTX 3060. We just implemented a broker abstraction layer (v0.14.0) with an IB adapter via `ib_async`. The system:

- Scans S&P 100 every 30 minutes during market hours
- Places bracket orders (entry + stop + target) via GTC
- Holds trades 1-15 days (swing trading, pullback-in-uptrend strategy)
- Also runs mean reversion (RSI(2), 1-5 day holds)
- 37 open positions at any given time
- Paper trading on Alpaca ($100K), minimal live on Alpaca ($100)
- Goal: IB becomes primary live broker for GIPS-verified track record toward fund formation

## Questions to Answer

### 1. IB Gateway Operations
- What is the exact daily/weekly IB Gateway lifecycle? When does it disconnect, reconnect, go down for maintenance?
- What are the best practices for keeping IB Gateway running 24/7 on Windows? Auto-restart, session management, 2FA handling?
- How do most automated systems handle the daily reset (11:45 PM ET)? What about weekend downtime?
- Is there a headless/silent mode that doesn't require the desktop GUI?
- IBC (IB Controller) — is it still maintained? Is it the standard for unattended operation? How do you configure it?
- What are the memory/CPU requirements for IB Gateway vs TWS for our scale (~37 positions, S&P 100 scan)?

### 2. Order Management for Bracket Orders
- IB bracket orders are 3 linked OCA orders. What are the failure modes? Can the parent fill but children not submit?
- What happens to GTC bracket orders during the daily reset? Do they persist? Do order IDs change?
- How do most systems verify bracket integrity? (All 3 legs active, stop + target still live after entry fills)
- What's the best practice for modifying a bracket stop/target mid-trade? Cancel + replace vs modify?
- How do partial fills work with IB brackets? If 50/100 shares fill, what happens to the stop/target quantity?
- What's the IB pacing violation threshold exactly? How do you avoid it with 37 positions + 100-ticker scans?

### 3. Data and Market Data
- IB market data subscriptions: what do we need for S&P 100 equities? Cost? Free alternatives?
- Snapshot vs streaming: for a 15-minute poll cycle, is snapshot mode sufficient? What's the data line limit?
- Can we use IB for historical OHLCV instead of yfinance? Quality comparison?
- Real-time P&L: how do most IB automated systems compute unrealized P&L for a portfolio of 37 positions?

### 4. Reconciliation and Position Tracking
- IB's position reporting: how does `ib.positions()` vs `ib.portfolio()` differ? Which should we use?
- What happens to position data during the daily reset? Is there a gap where positions are unavailable?
- How do professional systems reconcile IB positions against their internal database?
- What's the standard for detecting orphaned orders (entry filled, but stop/target cancelled by IB)?

### 5. PortfolioAnalyst and Track Record
- How do you access PortfolioAnalyst data programmatically? Is there an API?
- What does GIPS verification require beyond PortfolioAnalyst?
- How early should we start building the track record? (We're at 18 trades on Alpaca paper)
- Can PortfolioAnalyst merge paper and live performance for presentation?

### 6. Risk and Safety
- What are the common failure modes for automated IB systems? (Top 10 causes of unexpected losses)
- How do most systems implement a kill switch with IB? Close all positions + cancel all orders?
- IB's built-in risk controls: can we use them as a second layer behind our governor?
- What happens if our system crashes mid-bracket? Does IB keep the stop/target active?
- TWS API error codes: which ones require immediate attention vs retry?

### 7. Fund Formation Considerations
- IB institutional accounts: when do we need to upgrade from individual to advisor/institutional?
- Compliance requirements: what does IB provide for regulatory reporting?
- Multiple sub-accounts: best practice for separating paper testing from live trading?
- API access levels: any restrictions on automated trading volume or order frequency?

### 8. Technical Implementation
- `ib_async` vs raw TWS API: are there edge cases where `ib_async` doesn't work well?
- Connection pooling: can multiple components share one IB connection, or do they need separate client IDs?
- Error handling patterns: what's the standard try/except pattern for IB operations?
- Order status events: should we poll or use event callbacks for fill detection?

## Deliverable

A comprehensive research document (~30-50 pages) covering all 8 sections with:
- Specific IB API code patterns (Python, using `ib_async`)
- Common pitfalls and how to avoid them
- Configuration recommendations for our specific setup (Windows, RTX 3060, 37 positions, swing trading)
- Cost analysis for market data subscriptions
- Timeline for when to activate each capability (paper first → live → GIPS)
