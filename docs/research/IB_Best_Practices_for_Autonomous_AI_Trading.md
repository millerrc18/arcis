# Interactive Brokers Best Practices for Autonomous AI Trading Systems — Deep Research Report

**Date:** 2026-04-05 | **Depth:** Deep | **Domain:** Algorithmic Trading
**Query:** IB best practices for Arcis — autonomous AI equity trading system migrating from Alpaca to IB for GIPS-verified track record and fund formation
**Classification:** PUBLIC

---

## Executive Summary

The research consensus — confirmed through 7 parallel search agents, 2 refinement passes, and a 5-agent council debate — is that **Interactive Brokers is the correct long-term platform for Arcis's fund formation goals, but migration engineering should not begin yet.** At 18 paper trades, the strategy lacks statistical validation, and every hour spent on IB infrastructure is an hour not spent proving the strategy generates alpha. The council unanimously converged on a validation-first approach: continue trading on Alpaca until 60+ independent trades demonstrate a rolling Sharpe > 1.0, while running a zero-cost 30-day IB Gateway stability test and beginning long-lead administrative work (RIA paperwork, GIPS verifier consultation, market data classification).

The most dangerous finding is not technical — it's sequential. Building institutional plumbing for an unvalidated strategy is premature optimization. The $5-10K "low-risk parallel path" that seems obvious actually creates a GIPS composite construction trap that could produce a track record that actively harms fund formation credibility.

**Overall Confidence:** HIGH — The directional recommendation (IB is correct, but not yet) achieved unanimous council agreement after structured debate with genuine concessions from dissenting members.

---

## Key Findings

### What the Evidence Says (Thesis)

**IB is the institutional standard for algorithmic fund formation.** No serious alternative exists for GIPS-compliant institutional track records with the depth of audit trail, execution quality, and regulatory infrastructure that IB provides. The platform supports:

- **Server-side GTC order persistence** — bracket orders (parent + take-profit + stop-loss via OCA groups) survive client disconnections and Gateway restarts. Orders live on IB's servers, not the client.
- **IBC (IB Controller)** — the community-standard tool for unattended IB Gateway operation. Handles auto-restart after daily shutdown (~11:45 PM ET), 2FA bypass via IBKR Mobile, and automated login recovery. Actively maintained on GitHub.
- **ib_async** — the maintained fork of ib_insync (by Ewald de Wit), providing async Python access to the TWS API. Handles connection management, order submission, market data, and account queries.
- **Market data at reasonable cost** — US Securities Snapshot & Futures Value Bundle (~$10/mo for non-professional classification) covers S&P 100 equities. Snapshot mode (`reqMktData` with `snapshot=True`) avoids the 100-concurrent-streaming-line limit.
- **PortfolioAnalyst** — built-in performance reporting. Combined with Flex Queries and Activity Statements, provides the audit trail for GIPS verification.
- **Account upgrade path** — Individual -> Friends & Family (free, up to 15 accounts) -> Advisor (requires registration) -> Institutional/Fund structure.

**IB Gateway Operations (Section 1):**
- Gateway requires daily restart, typically configured for 11:45 PM ET (outside market hours)
- IBC handles the restart cycle: detect shutdown -> wait -> restart Gateway -> auto-login -> confirm API connection
- Memory footprint: Gateway ~512MB-1GB Java heap; significantly lighter than full TWS
- On Windows, NSSM (Non-Sucking Service Manager) wraps IBC as a Windows service for watchdog functionality
- 2FA handled via IBKR Mobile app confirmation (one-time device registration)

**Order Management (Section 2):**
- Bracket orders are 3 linked orders via OCA (One-Cancels-All) groups
- GTC orders persist server-side through Gateway restarts — order IDs do not change
- IB's pacing limit: 50 messages/second. Scanning 100 symbols every 30 minutes is well within limits if requests are batched (2-3 per second is safe)
- Partial fill handling: if 50/100 shares fill on the parent, stop/target quantities are NOT automatically adjusted. The system must detect partial fills and modify child order quantities manually.

**Data and Market Data (Section 3):**
- Non-professional US equity snapshot bundle: ~$10/month (2025 pricing)
- Snapshot mode avoids streaming line limits entirely — request price data on demand
- IB historical data (reqHistoricalData) provides OHLCV comparable to yfinance, with the advantage of being from the same source as execution data (no data/execution mismatch)
- Real-time P&L: `reqPnL` and `reqPnLSingle` provide account and position-level P&L updates

**Reconciliation (Section 4):**
- `ib.positions()` returns: (account, contract, position, avgCost) — lightweight, for position counting
- `ib.portfolio()` returns: (account, contract, position, marketPrice, marketValue, averageCost, unrealizedPNL, realizedPNL) — richer, for P&L tracking
- During daily Gateway restart: position data is briefly unavailable (~5-15 minutes)
- Professional reconciliation pattern: compare local SQLite state against `reqPositions` + `reqOpenOrders` on every reconnect, not just at scheduled intervals

**Risk and Safety (Section 6):**
- Critical error codes requiring immediate action:
  - **1100**: Connectivity between IB and TWS has been lost (stop trading)
  - **1102**: Connectivity restored, data lost (full state reconciliation required)
  - **2110**: Connectivity restored, data maintained (resume with caution)
  - **10147**: OrderId already in use (duplicate order risk)
  - **201**: Order rejected (check rejection reason)
  - **202**: Order cancelled (check if system-initiated or IB-initiated)
- Kill switch implementation: `reqGlobalCancel()` cancels all open orders. Follow with market sell orders for all positions. Write HALTED flag to prevent further order submission.
- IB's built-in risk controls: Daily P&L limit, max order size, max position size — configurable as a second layer behind Arcis's risk governor.

**Technical Implementation (Section 8):**
- ib_async uses a single-threaded asyncio event loop. Any blocking call during a scan creates a window where order acknowledgments queue up.
- Client IDs: each component connecting to IB Gateway needs a unique client ID (0-999). Typical pattern: ID 0 for primary order management, ID 1 for market data, ID 2 for monitoring/reconciliation.
- Event-driven is preferred over polling for fill detection: subscribe to `ib.orderStatusEvent` and `ib.execDetailsEvent` rather than polling `reqOpenOrders`.
- Connection pooling: multiple components CAN share one IB connection via the same `IB()` instance, but separate client IDs provide isolation and independent reconnection.

### What Challenges This (Antithesis)

**The engineering tax is real and substantial:**
- Forum reports consistently describe 3-6 months of infrastructure work for stable IB automation — and this is from operators who *succeeded*. Failed or abandoned migrations are invisible (survivorship bias). For a solo developer on Windows with additional constraints (Ollama GPU contention, NVIDIA driver instability), the realistic estimate is **6-12 months**.
- IB Gateway stability complaints are frequent on practitioner forums (2023-2025), particularly around Java updates and forced Gateway version upgrades that break IBC configurations.
- The daily restart window (11:45 PM ET) creates a 5-15 minute blind spot where position data is unavailable and GTC bracket orders can fill without the system knowing. This is a structural vulnerability in any autonomous IB system.

**The Windows + Ollama + Gateway stack is fragile:**
- This specific hardware profile (Z690 + RTX 3060 12GB) has documented BSOD history from NVIDIA driver conflicts (0x13A crashes from NVIDIA 591.86 + KB777778). Adding IB Gateway's JVM to this environment creates correlated failure modes — a driver crash takes down Ollama, Gateway, AND the trading system simultaneously.
- ib_async's event loop is single-threaded. During Ollama inference (which can spike GPU/CPU usage), order acknowledgment processing may be delayed 200-800ms. On volatile trading days, this delay means the system processes stale state during stop-loss triggers.

**GIPS and fund formation complexities:**
- GIPS 2020 requires minimum 1 year of live compliant performance before marketing. Paper trading history has zero composite value.
- Professional vs non-professional market data classification: FINRA Rule 2040 and exchange subscriber agreements define "professional" broadly. An operator pursuing fund formation under an LLC may be required to take professional-tier data subscriptions ($100+/month), not the $10/month non-professional rate. IB compliance representatives have given inconsistent guidance on this.
- The $5-10K seed account creates a **composite construction trap**: a 37-position bracket-order system on $5-10K has materially different execution characteristics (fill rates, slippage, position sizing of ~$135-270 per position) than the same strategy at $100K+. If this sub-scale account becomes the founding GIPS composite, it may produce a technically verified but non-representative track record — a liability for fund formation.
- IB Advisor account transition requires more than an account upgrade: depending on AUM and client count, it may trigger RIA registration (state-level under $100M), Form ADV filing, written compliance program, and annual compliance costs of $2-5K+ minimum. This is a 3-6 month regulatory process on top of the track record timeline.

**Bracket order failure modes:**
- Known: parent order fills but child orders (stop/target) fail to submit due to network interruption during the bracket submission sequence. The system has an entry position with no protection.
- Known: partial fills do not auto-adjust child order quantities. 50/100 shares filled means the stop/target are still sized for 100 shares — over-protected, but also creating a mismatch if position is later scaled.
- Known: during Gateway restart, if an OCA group triggers (stop fills), the system won't receive the notification until reconnection. The local state diverges from exchange state during the blind spot.

**Contrarian evidence: IB may not be necessary yet:**
- GIPS verification firms (ACA Group, Ashland Partners, etc.) can verify track records from any broker, not just IB. The GIPS infrastructure argument should be decoupled from the broker choice.
- Alpaca's execution quality for S&P 100 large-caps is adequate at current scale. The marginal improvement from IB is measured in cents per share — immaterial at a 37-position, sub-$100K portfolio.
- Some solo algo traders report spending 3-6 months on IB infrastructure engineering that did not improve their trading performance — pure engineering overhead with zero alpha generation benefit.

### The Deeper Insight (Synthesis)

**The timing question dominates the platform question.** IB is the correct destination, but 18 paper trades provides zero statistical evidence that the strategy generates alpha. Every council member — including those who initially advocated for immediate migration — converged on this point through structured debate. The Synthesizer conceded: "The Contrarian and Arbiter were more right than I gave them credit for."

**The correct mental model is optionality preservation, not commitment.**

The operator has a working system generating signals. The highest-value use of the next 3-6 months is:
1. **Prove the strategy works** by accumulating statistically significant live trades on Alpaca (the platform that's already working)
2. **Cheaply test assumptions** about IB platform stability (30-day Gateway test, zero engineering)
3. **Remove long-lead blockers** that don't compete for engineering time (RIA paperwork, GIPS consultation, market data classification)

This preserves the option to migrate to IB with validated strategy confidence, proper composite construction methodology, and known platform stability — while avoiding the trap of building institutional infrastructure for an unvalidated strategy.

**The most important non-obvious finding:** The $5-10K "low-risk parallel path" that appears prudent actually creates hidden risk. A sub-scale account trading 37 positions with bracket orders produces a track record with different execution characteristics than the intended scale. If that account becomes the founding GIPS composite without proper construction methodology, it may need to be discarded entirely — wasting the track record time it was meant to generate.

---

## How Thinking Has Evolved

**2010-2018: IB API as the only serious option.** TWS API was the dominant choice for retail algo traders. ib_insync (created by Ewald de Wit) simplified the notoriously complex TWS socket API into a Pythonic interface. IBC (originally IBController) emerged as the community solution for unattended operation.

**2019-2022: Alpaca, Tradier, and API-first brokers emerge.** Commission-free trading and clean REST APIs lowered the barrier to algorithmic trading. Solo developers who would have spent months fighting IB's API could now go live in days. The "IB or nothing" consensus weakened for equity-only strategies.

**2023-2025: ib_insync forks to ib_async.** The library moved to full async/await support. IB Gateway stability complaints increased (Java updates, forced version upgrades). Meanwhile, GIPS 2020 standards clarified requirements for smaller managers, and the path from solo trader to fund manager became more documented (if not simpler).

**Current state (2025-2026):** IB remains the institutional standard for fund formation, but the engineering tax for autonomous operation is better understood — and higher than casual estimates suggest. The emergence of broker abstraction layers (like Arcis's v0.14.0) reflects the industry recognizing that broker coupling is a risk, not just an implementation detail.

---

## Cross-Domain Connections

### SCADA / Industrial Automation Patterns

IB Gateway on Windows with daily restarts is structurally identical to an industrial SCADA control system with mandatory maintenance windows. Transferable patterns:

1. **Supervisor process hierarchy**: In SCADA, the watchdog process is itself monitored by the OS service manager. Applied to Arcis: NSSM watches IBC, IBC watches Gateway, Windows Service Control Manager watches NSSM. Three layers of supervision.

2. **State journaling**: SCADA systems write state to durable storage (SQLite, flat files) before every state change. Applied to Arcis: write order state to SQLite before submission, write fill state before updating position tracking. If the system crashes between write and acknowledgment, the journal provides recovery state.

3. **Heartbeat with 2x interval**: SCADA heartbeat intervals are set at 2x the expected response time. Applied to Arcis: if Gateway typically responds to API calls within 500ms, set the disconnection detection threshold at 1000ms, not 5000ms. Faster detection = faster recovery.

4. **Graceful degradation during communication loss**: SCADA systems maintain last-known-good state and refuse to actuate during communication gaps. Applied to Arcis: if Gateway connection is lost, the system should NOT place new orders but SHOULD trust that existing GTC brackets are alive server-side. Resume only after full reconciliation.

### Institutional EMS/OMS Reconciliation Patterns

Professional execution management systems solve the exact bracket integrity problem Arcis faces:

1. **Order state machine**: PENDING -> SUBMITTED -> ACKNOWLEDGED -> PARTIAL_FILL -> FILLED -> CANCELLED. Each transition is logged. Stuck transitions (SUBMITTED but never ACKNOWLEDGED) trigger alerts after timeout.

2. **Fill reconciliation loop**: Every N seconds, compare local order state against exchange-reported state. Any divergence triggers an immediate reconciliation pass, not just logging.

3. **Position truth = exchange always wins**: When local state diverges from IB's reported positions, IB's state is authoritative. The local database must be corrected, not the exchange.

4. **Orphaned leg detection**: For multi-leg orders (brackets), verify that all legs are live on every reconciliation pass. If entry is filled but stop/target are not found in open orders, this is a critical alert — the position is unprotected.

---

## Counter-Evidence & Risks

### Top 10 Risks for Arcis IB Migration (ranked by severity)

1. **Strategy has no alpha** (CRITICAL) — 18 trades cannot distinguish skill from luck. All downstream infrastructure is wasted if the strategy doesn't work.

2. **Correlated hardware failure** (HIGH) — NVIDIA driver update crashes Gateway + Ollama + Python simultaneously. Documented BSOD history (0x13A) on this exact hardware.

3. **GIPS composite construction error** (HIGH) — Sub-scale account produces non-representative track record. If not properly constructed from day 1, the composite must be discarded.

4. **Professional data classification** (HIGH) — Fund formation aspirations may disqualify non-professional market data rates. Cost increase from $10/mo to $100+/mo.

5. **Bracket order orphaning** (HIGH) — Entry fills, network drops, stop/target never submitted. Position is live with no protection.

6. **Daily restart blind spot** (MEDIUM) — 5-15 minutes during Gateway restart where fills are invisible to the system. OCA triggers during this window cause state divergence.

7. **Partial fill management** (MEDIUM) — IB does not auto-adjust bracket child quantities on partial fills. System must detect and modify manually.

8. **RIA registration timeline** (MEDIUM) — 3-6 month regulatory process not accounted for in the 12-18 month fund formation estimate.

9. **IBC config breakage** (MEDIUM) — IB's forced Gateway updates periodically break IBC login configurations. Requires manual intervention.

10. **Event loop latency** (LOW-MEDIUM) — ib_async single-threaded event loop delays order processing during Ollama inference. Manifests on volatile days when timing matters most.

---

## Decision Implications

### The Action Plan (Council-Validated)

```
Phase 1: VALIDATE (Months 1-6)
  Primary: Continue strategy on Alpaca, target 60+ live trades
  Measure: Rolling 30-trade Sharpe > 1.0 at p < 0.05
  Parallel: Open IB account, 30-day Gateway stability test
  Admin: Begin RIA paperwork, consult GIPS verifier, get written
         market data classification from IB

Phase 2: BUILD (Months 6-12, only if Phase 1 gates pass)
  Primary: IB adapter engineering (kill switch first, then orders,
           then reconciliation, then market data)
  Measure: 30 days of IB paper trading without manual intervention
  Gate: Kill switch tested and operational before any live capital

Phase 3: LIVE (Months 12-18)
  Primary: IB live trading with small capital, proper composite
           construction methodology from GIPS verifier
  Parallel: Continue Alpaca as fallback
  Gate: 3 months of live IB trading before decommissioning Alpaca

Phase 4: SCALE (Months 18-30)
  Primary: Scale IB capital, complete RIA registration
  Transition: Individual -> Friends & Family -> Advisor
  Gate: 12+ months of GIPS-compliant live track record before
        any fund marketing
```

### Immediate Actions (This Week)

| # | Action | Cost | Engineering Time | Lead Time |
|---|--------|------|-----------------|-----------|
| 1 | Open IB Individual account | $0 | 0 | 2-4 weeks |
| 2 | Install IB Gateway + IBC on Windows | $0 | 2 hours | Same day |
| 3 | Run 15-day idle + 15-day loaded stability test | $0 | 0 (passive monitoring) | 30 days |
| 4 | Write validation gate into MASTER.md | $0 | 10 minutes | Immediate |
| 5 | Email GIPS verifier for initial consultation | $500-2K | 0 | 2-4 weeks response |
| 6 | Request written market data classification from IB | $0 | 0 | 2-4 weeks |
| 7 | Identify securities attorney for RIA registration | $0 | 0 | Research phase |

### What NOT To Do

- Do NOT write IB adapter code until strategy validation gate is passed
- Do NOT fund an IB live account until GIPS composite methodology is confirmed
- Do NOT assume non-professional market data classification without written confirmation
- Do NOT decommission Alpaca until IB has run 90+ days in production
- Do NOT start the GIPS track record clock on a sub-scale ($5-10K) account without verifier guidance

---

## Council Debate

### BLUF (Bottom Line Up Front)

Do not write a single line of IB adapter code. Continue strategy validation on Alpaca until you reach 60+ live trades with rolling 30-trade Sharpe > 1.0 (p < 0.05). In parallel, open an IB account today and run a 30-day Gateway stability test (15 days idle, 15 days with Ollama under realistic inference load). Begin RIA paperwork and GIPS verifier consultation immediately — these are long-lead, zero-engineering tasks.

**Confidence: HIGH** — Unanimous convergence after structured debate.

### Consensus Findings

- IB is the correct long-term platform for fund formation; this is not in dispute
- Strategy validation must precede IB engineering — 18 trades provides zero statistical evidence of alpha
- A 30-day IB Gateway stability test is free and empirically resolves platform reliability questions
- Kill switch and risk governor must be day-1 requirements when live capital eventually touches IB
- GIPS-compliant track record requires live trades; paper trading history has no composite value
- Market data pro/non-pro classification is a real regulatory risk requiring written IB confirmation
- The $5-10K composite construction trap is real — small-account live IB trading at 18 trades creates a track record that may actively harm fund formation credibility

### Key Debate Points

**1. Start IB now vs validate strategy first**
- *Initial split:* 2 for immediate start (Synthesizer, Practitioner) vs 3 for validation first (Skeptic, Contrarian, Arbiter)
- *Resolution:* **Full convergence to validation-first.** The Synthesizer conceded: "The Contrarian and Arbiter were more right than I gave them credit for." The Practitioner revised to "60 live trades before touching IB."
- *Crux:* At N=18, confidence intervals on Sharpe are too wide to distinguish alpha from luck. Infrastructure for an unvalidated strategy is premature optimization.

**2. Validation gate threshold: 60 vs 100+ trades**
- *Practitioner position:* 60 trades with rolling 30-trade Sharpe > 1.0 is sufficient (SE ~0.13 at n=60)
- *Contrarian position:* 100+ trades needed if autocorrelation is present
- *Resolution:* **Run autocorrelation analysis on existing trades first.** If trades are independent, 60 suffices. If clustered, raise to 100.

**3. Idle vs loaded Gateway stability test**
- *Majority:* Idle 30-day test is sufficient
- *Skeptic minority:* Must test under realistic Ollama inference load
- *Resolution:* **Skeptic prevailed.** Split test: 15 days idle + 15 days loaded. This costs nothing extra and directly addresses the known VRAM contention risk.

**4. $5-10K composite construction trap**
- *Synthesizer:* Sub-scale account creates non-representative track record that harms fund formation
- *Contrarian:* Agrees; $5-10K live trading is premature at 18 trades
- *Arbiter:* Low-regret deposit acceptable, but no live trading until GIPS methodology is confirmed
- *Resolution:* **Deposit accepted; live trading deferred until GIPS verifier approves composite construction methodology.**

### Actionable Recommendations (from Council)

1. **Continue Alpaca validation** — 60+ independent trades, Sharpe > 1.0 rolling (HIGH confidence)
2. **Open IB account + 30-day stability test** — 15 idle + 15 loaded (HIGH confidence)
3. **Begin RIA paperwork and GIPS consultation** — long-lead administrative items (HIGH confidence)
4. **Get written IB market data classification** — pro/non-pro determination (MODERATE confidence)
5. **Write validation gate into MASTER.md** — cognitive momentum mitigation (HIGH confidence)

### Critical Uncertainties

1. Whether Arcis's strategy actually produces alpha (the elephant in the room)
2. Whether IB Gateway remains stable under concurrent Ollama VRAM load on this specific hardware
3. Whether IB will classify an AI trading system aspiring to fund formation as a professional subscriber
4. The Alpaca-to-IB migration engineering scope (adapter rewrite, order type mapping, position sync)

### Assumptions

1. The operator's goal is fund formation with external capital, not personal trading
2. The current Alpaca infrastructure can produce the additional trades needed for validation
3. The Windows single-box architecture is the deployment target (if Linux VPS is adopted, stability test results don't transfer)
4. Trade-level autocorrelation is low enough that 60 trades provides adequate statistical power
5. The operator will enforce the validation gate and not begin IB engineering prematurely

### Debate Transcript

<details>
<summary>Full council debate transcript</summary>

#### Round 1: Independent Assessments

**Synthesizer (Confidence: 3/5 MODERATE)**
Top findings: (1) Failure modes in this stack are correlated, not independent — BSOD history means 3-6 month estimate is likely 6-9 months. (2) GIPS clock argument is weaker than presented — clock starts with first live trade on ANY broker. (3) $5-10K creates a composite construction trap — sub-scale account may produce non-representative track record.

**Skeptic (Confidence: 2/5 LOW)**
Evidence quality assessment: Most claims WEAK to MODERATE. Key concerns: (1) 3-6 month estimate suffers from survivorship bias. (2) Non-professional market data classification is a legal trap — FINRA Rule 2040 may classify fund-aspiring traders as professional. (3) IBC + ib_async stability claims rest on forum consensus with heavy survivorship bias. (4) Bracket order "seamless persistence" conflates order survival with client reconnection.

**Practitioner (Confidence: 3/5 MODERATE)**
Key concerns: (1) ib_async adapter "already started" is the most dangerous phrase — order state management across reconnects is months of correctness work. (2) Kill switch must be day 1, not iterative. (3) Advisor account path is gated on RIA registration (3-6 months), not just track record. (4) $5-10K at 37 positions = ~$135-270/position — commission friction eats returns.

**Contrarian (Confidence: 3/5 MODERATE on timing)**
Counter-thesis: At N=18, confidence intervals on Sharpe are too wide to distinguish alpha from luck. Building institutional infrastructure for an unvalidated strategy inverts the priority stack. GIPS framing is premature — paper contributes nothing to certification. Windows is the wrong platform given documented BSOD history. 3-6 months of IB engineering is 3-6 months not spent proving the strategy works.

**Arbiter (Confidence: MODERATE)**
BLUF: Validate strategy with 3-6 months of real-money Alpaca trading before investing in IB infrastructure. This is an optionality-preservation problem. Opening IB account is low-regret; engineering commitment is high-regret if strategy fails.

#### Round 1.5: Divergence Detection
6 consensus items identified. 4 divergence points flagged: (1) timing, (2) composite trap, (3) market data classification, (4) Windows vs Linux.

#### Round 2: Structured Debate

**Synthesizer conceded timing:** "The Contrarian and Arbiter were more right than I gave them credit for. Validate strategy FIRST. Revised sequencing: (1) Alpaca validation to 100+ trades, (2) IB account application + FINRA 2040 legal opinion, (3) IB engineering only after strategy validation clears."

**Skeptic moved to 3/5 conditional:** "The test protocol resolves the infrastructure question IF the test is done correctly (under realistic load, not idle). It does not resolve the regulatory question or the strategy alpha question."

**Practitioner revised minimum N:** "60 live trades with rolling 30-trade Sharpe above 1.0. Not 18. Not 100. Do not write a single line of adapter code until 60 live trades clear."

**Contrarian accepted idle test:** "I was arguing against a strawman. Accept the idle test unconditionally. Withdraw platform stability objection. Maintain: no engineering hours on IB until 100+ validated trades."

#### Round 3: Arbiter Final Synthesis
See main Council Debate section above.

</details>

---

## Research Notes & Next Steps

### Process Notes
- 7 parallel research agents dispatched (3 direct, 2 lateral, 1 contrarian, 1 tracer)
- Deep-research MCP tools had context issues; agents fell back to nimble/web search
- Practitioner forums (Elite Trader, QuantConnect, GitHub issues) provided more actionable detail than official IB documentation
- GIPS 2020 algorithmic strategy specifics were the hardest to find — most sources discuss traditional asset management
- IB market data pricing documentation is notoriously confusing; multiple sources gave different numbers
- The council debate produced genuine convergence (not false consensus) — the Synthesizer's willingness to concede was the strongest signal of intellectual honesty

### Recommended Next Steps

1. **Run autocorrelation analysis** on existing 18 trades to determine if 60 or 100 is the correct validation threshold
2. **Power analysis**: calculate minimum N required to reject null hypothesis at 95% confidence for observed Sharpe
3. **Deep dive on IBC configuration**: once Gateway stability test begins, document exact config.ini settings that work on Windows 11
4. **ib_async bracket order code patterns**: before writing adapter code, build a standalone test harness that submits brackets to IB paper and verifies integrity across restarts
5. **GIPS verifier shortlist**: identify 2-3 GIPS verification firms experienced with quantitative/algorithmic strategies
6. **RIA registration research**: determine whether state or SEC registration is appropriate, identify a securities attorney
7. **Linux VPS evaluation**: if Gateway stability test fails under load, evaluate dedicated Linux VPS for IB Gateway (separate from Windows ML box)

---

## Sources

### Authoritative (>= 0.8)

- **Interactive Brokers TWS API Documentation** — Official API reference including error codes, order types, market data functions. interactivebrokers.com
- **GIPS 2020 Standards** — CFA Institute Global Investment Performance Standards. The authoritative reference for track record requirements.
- **IBC GitHub Repository** — Community-maintained IB Controller for unattended Gateway operation. Primary source for configuration patterns.
- **ib_async / ib_insync Documentation** — Official library documentation and API reference. readthedocs.io

### Expert (0.6-0.79)

- **Elite Trader Forums** — Practitioner discussions on IB automation, Gateway stability, bracket order behavior. elitetrader.com
- **QuantConnect Community** — Algorithm developer discussions on IB integration patterns and failure modes. quantconnect.com
- **IB API Users Group (groups.io/g/insync)** — ib_insync/ib_async community support and issue tracking
- **IB GitHub Issues** — Bug reports and workarounds for ib_async edge cases

### Professional (0.4-0.59)

- **NerdWallet / Investopedia IB Reviews** — Consumer-oriented IB comparisons, market data pricing overviews
- **Blog Posts on IB Automation** — Various practitioner guides on IBC setup, Gateway stability, Windows automation
- **Reddit r/algotrading** — Community discussions on IB vs alternatives, fund formation paths

### Other (< 0.4)

- **Stack Overflow IB API Questions** — Scattered Q&A on specific API calls, error handling
- **Medium Articles on Algo Trading** — General-purpose guides, varying quality

---

## Research Metadata

- **Query:** Interactive Brokers best practices for autonomous AI trading systems (8 sections, 50+ sub-questions)
- **Depth:** Deep
- **Domain:** Algorithmic Trading
- **Duration:** ~45 minutes
- **Sub-questions:** 6 (3 direct clusters + 2 lateral + 1 contrarian)
- **Agents dispatched:** 16 total (1 planner + 3 direct searchers + 2 lateral searchers + 1 contrarian searcher + 1 tracer + 1 synthesizer + 2 refiners + 5 council members)
- **Refinement iterations:** 2 (stopped at deep depth max)
- **Council:** Yes (5-agent, 3 rounds — full convergence on primary recommendation)
- **Gaps remaining:** 4 (autocorrelation analysis, IBC config specifics, ib_async bracket code patterns, Linux VPS evaluation)
