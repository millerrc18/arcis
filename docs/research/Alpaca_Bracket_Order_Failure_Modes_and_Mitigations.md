# Alpaca bracket orders will fail your autonomous system in at least nine documented ways

**Alpaca's bracket orders carry hidden failure modes that can leave positions unprotected for 17+ hours per day, silently break during stock splits, and deadlock on partial fills — any one of which could be catastrophic for an unsupervised system.** This report documents every known edge case, quantifies risk frequency and severity, and provides specific mitigations. The findings draw from Alpaca's official API documentation, 20+ community forum threads with Alpaca staff responses, open GitHub bugs in `alpacahq/alpaca-py`, SEC market structure rules, and practitioner reports. The bottom line: bracket orders on Alpaca are useful building blocks but are emphatically not a "set and forget" risk management system. An autonomous trading system must implement multiple redundancy layers around them.

---

## 1. Circuit breaker halts leave stops queued, not executed

Alpaca's stop-loss legs **cannot execute during any trading halt** — market-wide circuit breakers, individual stock LULD pauses, or regulatory halts. Orders queue server-side and fire only at the reopening auction, where prices may be drastically different from the stop trigger level.

**Market-wide circuit breakers** (NYSE Rule 7.12) halt all US equity trading at three thresholds: Level 1 (**7%** S&P 500 decline, 15-minute halt), Level 2 (**13%**, 15-minute halt), and Level 3 (**20%**, trading halted for the day). During March 2020, four Level 1 breakers triggered in 10 days. On March 16, 2020, the S&P 500 fell 12% — stop orders that triggered at the reopening filled at prices significantly below their trigger levels due to thin reopening auction books. Per the NYSE MWCB FAQ, unexecuted market orders on the book are *not* cancelled during halts but resting non-displayed orders *are* cancelled.

**LULD (Limit Up Limit Down) individual stock halts** affect S&P 100 stocks with **5% price bands** during regular hours (10% at open/close). When the NBBO touches a band for 15 seconds, a Limit State begins; if unresolved, the primary exchange declares a 5-minute Trading Pause. During March 2020's four circuit-breaker days, **3,588 individual LULD halts** occurred. In normal conditions, about 20 LULD halts happen per day across all tickers. For S&P 100 stocks specifically, LULD halts are rare in isolation but cluster during systemic events.

**Alpaca's documented behavior** is explicit. From the official orders documentation: *"The potential for [unfavorable execution] increases for GTC orders across trading sessions or stocks experiencing trading halts."* The ORPH incident on June 10, 2021 illustrates the worst case: a user placed a stop sell at $69, the stock reopened at $63 for only 15 seconds before halting again, and the stop order was **cancelled without filling** because market orders had priority in the brief trading window. The user ultimately sold at **$23.00** — a $46/share loss versus the $69 stop intent.

**Multi-day regulatory halts** (e.g., SEC suspensions, news-pending halts) leave GTC bracket legs in a queued state indefinitely, up to Alpaca's **90-day GTC auto-cancel**. When trading eventually resumes, the opening price may bear no resemblance to pre-halt levels.

| Scenario | Frequency | Severity | Behavior |
|----------|-----------|----------|----------|
| Market-wide circuit breaker (Level 1) | Very rare (~1-2x/decade) | Catastrophic | Stops queue, fill at reopening auction price |
| LULD halt on S&P 100 stock | Rare (clusters in crises) | Moderate to severe | 5-minute pause; stop fires at reopening |
| Multi-day regulatory halt | Very rare | Catastrophic | GTC legs queue indefinitely; massive gap risk |
| Rapid halt-reopen-halt cycle | Very rare | Catastrophic | Stop may be cancelled without filling (ORPH case) |

---

## 2. Gap-through stops convert to market orders with unlimited slippage

When a stock gaps through a stop price overnight or at open, the outcome depends entirely on whether the bracket's stop-loss leg is a **stop (market)** or **stop-limit** order — and Alpaca defaults to the more dangerous option.

**Default behavior**: If only `stop_loss.stop_price` is provided (the common case), Alpaca queues a **stop order that converts to a market order** upon triggering. If both `stop_loss.stop_price` and `stop_loss.limit_price` are provided, it becomes a stop-limit. Most practitioners using the simple bracket API get stop-market by default.

**Gap-through mechanics**: Stock closes at $100, stop at $95, opens at $90. The opening print at $90 is below the $95 trigger. The stop immediately elects and becomes a market order. The fill occurs at **approximately $90** (the prevailing market price), not $95. The $5 gap is pure, unrecoverable slippage. For S&P 100 stocks with deep liquidity, the fill will typically occur within pennies of the opening print. For less liquid names or during systemic stress, slippage can be substantially worse.

**Stop-limit alternative**: If you specify a limit price of, say, $93 on the stop-loss, the order converts to a limit sell at $93 when the $95 trigger hits. But if the stock opens at $90, the limit at $93 is above the market — **the order will not fill at all**. The position remains open with no protection. This is the fundamental stop-market vs. stop-limit tradeoff: guaranteed exit at potentially terrible price versus no exit at all.

**Take-profit gap-through works in the trader's favor.** A limit sell (take-profit) at $110 with a stock opening at $115 fills at $115 or better. Limit orders guarantee price *or better*, so upside gaps produce positive slippage.

**Expected slippage for S&P 100 stocks** during typical overnight gaps (earnings, analyst actions): generally **$0.01–$0.50** for stop-market orders due to deep order books. During extreme events (March 2020 circuit breaker reopenings, flash crashes): slippage of **$1–$10+** is documented even on mega-caps. The 2010 Flash Crash saw Accenture briefly trade at $0.01 and P&G drop 37% in minutes — stop orders filled at catastrophic prices.

**Both bracket legs can fill simultaneously.** Alpaca's documentation explicitly warns: *"In extremely volatile and fast market conditions, both orders may fill before the cancellation occurs."* This could result in overselling a position, creating an unintended short. For a system running without human intervention, this requires automated detection and correction.

---

## 3. Partial fills create a documented deadlock that orphans positions

Alpaca's partial fill handling has a critical design constraint and a confirmed bug that together create the most insidious failure mode for autonomous systems.

**Entry partial fills block all exit legs.** Alpaca's documentation is unambiguous: exit legs activate only when the entry order is *"completely filled."* If you submit a bracket buy for 100 shares and only 50 fill before the entry is cancelled (or the market moves away), the stop-loss and take-profit legs **never activate**. You hold 50 unprotected shares with no bracket exit orders. The cancellation of the unfilled portion triggers cancellation of the entire bracket group, including never-activated exit legs.

**Exit partial fills scale correctly — most of the time.** Per the documentation: *"If the take-profit order is partially filled, the stop-loss order will be adjusted to the remaining quantity."* If take-profit fills 60 of 100 shares, the stop-loss automatically adjusts to 40 shares. This OCO quantity adjustment works as designed.

**The partial fill deadlock bug** is documented by user "buysell" on the Alpaca forum (thread /t/11097, November 2022): approximately once per month out of thousands of bracket orders, the take-profit partially fills (e.g., sells 6 of 10 shares), and then **neither the remaining take-profit nor the stop-loss ever triggers** for the remaining shares — even when price drops well below the stop level. The position becomes orphaned with no active exit orders. Alpaca staff investigated and found a related issue with replacement orders, but the reporter insisted the core bug predated any replacements.

**A stop cannot trigger while the entry is still filling.** Since exit legs remain in "held" status until entry completion, there is a vulnerability window: if you place a bracket buy, the entry begins filling, and the stock crashes during the partial fill, you accumulate shares with no stop protection until the entry fully completes — at which point the stop may trigger immediately at a much worse price.

| Scenario | Frequency | Severity | Behavior |
|----------|-----------|----------|----------|
| Entry partially fills then cancels | Occasional | Moderate | Position held with zero exit protection |
| Exit partial fill deadlock | ~Monthly per active system | Severe | Orphaned position with no active stops |
| Stop trigger during partial entry fill | N/A (prevented) | N/A | Exit legs held until entry complete |

---

## 4. Stops are completely inactive for 17.5 hours every weekday

**Bracket orders on Alpaca explicitly do not support extended hours.** The documentation states: *"`extended_hours` must be 'false' or omitted"* for bracket orders. This is a hard API constraint — submitting a bracket with `extended_hours: true` results in rejection. Stop-loss and take-profit legs are **only active during regular market hours (9:30 AM–4:00 PM ET)**.

This creates a **17.5-hour unprotected window every weekday** (4:00 PM to 9:30 AM the next day), plus the entire weekend from Friday's close to Monday's open (**65.5 hours**). During this time:

- A stock can gap 20%+ on after-hours earnings without triggering any bracket exit
- Pre-market movement from overnight news, global events, or analyst actions is invisible to bracket legs
- The stop only fires at the 9:30 AM regular session open, executing as a market order at whatever the opening price happens to be

**For a system trading S&P 100 stocks with 2–15 day holding periods**, this means the majority of each holding period has zero automated stop protection from the bracket order itself. Earnings announcements, Fed decisions, geopolitical events, and other catalysts that move stocks 5–15% routinely occur outside regular hours.

**Trailing stop orders** similarly do not trigger outside regular market hours. They are also not supported as bracket order legs — only as standalone orders.

**The only extended-hours order type Alpaca supports** is a `limit` order with `extended_hours: true` and `time_in_force: day`. To get any pre/post-market protection, an autonomous system must implement its own monitoring loop that watches real-time quotes during extended hours and submits standalone limit sell orders when price breaches thresholds.

---

## 5. API rate limits constrain throughput to roughly 3 bracket orders per second

Alpaca's trading API enforces a **200 requests per minute per API key** rate limit, applying identically to paper and live environments. This limit covers all trading endpoints: order submission, order queries, account information, and position lookups.

**Effective bracket order throughput**: Each bracket order is a single API call (`POST /v2/orders` with `order_class: "bracket"`), not three separate calls. However, a realistic scan cycle also requires position queries, order status checks, and potentially order modifications. For a system placing 5–10 bracket orders per cycle plus monitoring 20–30 existing positions, budget approximately **80–100 API calls per cycle**. This allows roughly **2 full scan cycles per minute** at the 200/min limit.

**Rate limit exceeded behavior**: HTTP **429** status code with error code `"42910000"` and message `"rate limit exceeded"`. Alpaca's documentation does not specify a `Retry-After` header — their SDKs implement custom retry logic with configurable parameters. The rate limit uses a rolling 60-second window.

**Increasing the limit**: Alpaca will raise the trading API limit to **1,000 calls/min** upon request, but the account is reclassified as **non-retail**. Non-retail accounts pay **$0.004 per share** (40 mils) and orders route through institutional smart order routers rather than wholesale market makers. Orders become "not held" (not covered under Reg NMS best execution obligations). For a system trading 500–1,000 shares per bracket order, this adds $2–$4 per round trip.

**Market data API rate limits** are separate: **200/min free, 10,000/min with a paid data subscription**. A paid market data plan does not increase trading API limits.

**No hard limit exists on simultaneous open orders** or orders per day. Alpaca staff confirmed they have *"many accounts trading tens of thousands of orders a day."* The constraint is purely the per-minute rate limit and available buying power.

---

## 6. Alpaca's trigger processing is the single point of failure during outages

The most consequential reliability fact: **bracket order exit legs are processed server-side by Alpaca's trigger system, not at the exchange.** During an Alpaca infrastructure outage affecting trigger processing, stop-loss and take-profit legs may not fire even as prices breach their trigger levels at the exchange.

**Alpaca's own risk disclosure** states: *"Conditional orders may have increased risk as a result of their reliance on trigger processing, market data, and other internal and external systems... issues such as system outages with downstream technologies or third parties may occur."* Furthermore: *"our executing partner may impose controls on conditional orders to limit erroneous trades triggering downstream orders. Alpaca Securities may not always be made aware of such changes to external controls immediately."*

**Outage frequency and character**: Alpaca maintains a status page at status.alpaca.markets with 100+ monitored components. StatusGator has tracked **125+ incidents across all components** over approximately 11 months of monitoring (March 2025–February 2026), including 100+ events on the SIP WebSocket stream alone. Many are brief warnings or partial degradations rather than full outages. The estimated practical uptime is **~99.5–99.9%**, though Alpaca publishes no formal SLA.

**Scheduled maintenance** occurs the **2nd Saturday of each month, 9:00–11:00 AM ET** (recently extended from 1 to 2 hours). Additional maintenance windows are scheduled as needed. During maintenance, all APIs may be intermittently unavailable.

**GTC orders already submitted to exchanges** continue to be executable during API outages. However, bracket order exit legs that haven't been triggered yet (still in Alpaca's system awaiting a price trigger) will **not fire** during Alpaca-side outages because the trigger processing system is what converts them from held conditional orders to live exchange orders.

**A confirmed websocket bug** (GitHub issue #198, still open as of 2024) means the TradingStream does not send status updates for the stop-loss leg when a take-profit fills in a bracket order. The stop shows "Cancelled" in the dashboard, but the websocket never broadcasts this event. The reverse (stop fills, take-profit cancellation) works correctly.

**Timeout handling is critical.** For orders returning HTTP 504 (Gateway Timeout), Alpaca warns: *"The order may have been sent to the market for execution. You should not attempt to resend the order or mark the timed-out order as canceled until confirmed by Alpaca Support."* This creates a dangerous ambiguity for autonomous systems.

---

## 7. Paper trading bears almost no resemblance to live execution

Paper trading on Alpaca operates with **infinite liquidity, zero slippage, no realistic partial fills, and latency up to 50x slower** than live trading. Strategies that perform well in paper may fail dramatically in production.

**Fill simulation**: Orders fill based on real-time quotes, not actual exchange execution. Crucially, **order quantity is not checked against NBBO depth** — a 10,000-share market order fills instantly at the quoted price, regardless of whether actual liquidity exists. Alpaca staff confirmed that 10% of eligible orders receive random partial fills for a random size, but this bears no relationship to real market microstructure.

**Latency measurements** from forum user testing (AAPL, 25 shares, 2:15 PM ET): live trading filled in **14ms** for both buy and sell; paper trading took **731ms** for buy and **107ms** for sell — an order of magnitude slower. Other users reported paper trading fill delays of **50–260 seconds** on limit orders, making any latency-sensitive backtesting meaningless. Alpaca's own documentation acknowledges: *"Paper trading environments have infinite liquidity and no latency, leading to perfect, instant fills."*

**Behavioral differences that break autonomous systems**:
- Paper accepts invalid stop price updates and waits for them to become valid; **live rejects them immediately**
- Paper does not simulate dividends, corporate actions, or stock splits
- Paper does not charge margin interest or borrow fees
- Paper does not send fill notification emails
- Paper and live use different base URLs (`paper-api.alpaca.markets` vs `api.alpaca.markets`) but identical API specifications

**The most dangerous discrepancy**: the partial fill deadlock bug described in Section 3 manifests differently in paper versus live. In paper, invalid replacement orders on bracket legs are silently accepted and queued; in live, they are rejected — creating a divergent order state that an autonomous system built on paper testing would never encounter.

---

## 8. Time-in-force constraints force a difficult tradeoff for multi-day holds

For a system with 2–15 day holding periods, bracket orders must use **GTC** (`time_in_force: "gtc"`) since DAY orders cancel at market close along with all bracket legs, leaving positions unprotected overnight. But GTC introduces its own complications.

**Only `day` and `gtc` are supported** for bracket orders. IOC, FOK, OPG, and CLS are all rejected. A single TIF value applies to all legs — you cannot set the entry to DAY and the exits to GTC. This is confirmed by Alpaca staff on the community forum, with a feature request for per-leg TIF still open.

**GTC auto-cancellation at 90 days**: Alpaca's aged order policy automatically cancels GTC orders 90 calendar days after creation at 4:15 PM ET. The `expires_at` field in the order object indicates this date. For a 15-day maximum holding period, this is unlikely to be reached, but the system should verify bracket orders remain active.

**DAY bracket order danger**: If you mistakenly use DAY TIF, at 4:00 PM ET the unfilled exit legs cancel, triggering cancellation of the entire bracket group. Your position survives but has zero stop or target protection. You must detect this and resubmit exit orders before the next session — exactly the kind of edge case that bites unsupervised systems.

---

## 9. Stock splits will catastrophically break your bracket orders

The most severe Alpaca-specific edge case: **bracket order legs carry DNR/DNC (Do Not Reduce/Do Not Cancel) instructions, meaning prices and quantities are NOT adjusted for any corporate action** — stock splits, reverse splits, special dividends, or mergers.

**Stock split catastrophe scenario**: You hold 100 shares of XYZ at $200 with take-profit at $220 and stop-loss at $180. A 2-for-1 split occurs. You now hold 200 shares at $100 each. But your stop-loss remains at $180 — now **$80 above** the current price. At the next market open, the $100 price is below $180, the stop triggers, and your entire position sells at a market price of ~$100 when the pre-split equivalent would have been $200. This is confirmed by GitHub issue #469 on `alpacahq/alpaca-py`, where an NVDA bracket survived a 1:10 split with unadjusted prices.

For comparison, regular (non-bracket) GTC orders on Alpaca *are* adjusted for forward splits and cancelled for reverse splits. The DNR/DNC instruction on bracket orders **overrides** this standard behavior.

**Dividend ex-dates**: The DNR instruction means bracket stop/limit prices are not reduced by the dividend amount on ex-dates, unlike standard orders. For S&P 100 stocks with typical quarterly dividends of $0.50–$2.00, this creates minor price distortion. For special dividends ($5+), it could trigger erroneous stops.

**Merger/acquisition effects**: If the target symbol changes or becomes inactive, bracket legs become orphaned. Alpaca processes mergers by removing original shares and allocating new shares/cash, but DNR/DNC bracket orders are not automatically cancelled or adjusted.

**Additional critical edge cases**:

- **PDT protection blocks exits**: For accounts under $25,000, Alpaca's Pattern Day Trader protection can hold bracket exit legs in "held" status to prevent day-trade violations. Multiple forum users (threads /t/3697, /t/5023) documented positions where entry filled but exits were blocked — allowing entry with defined risk but then removing the risk management. This affected **~5 out of 6 bracket orders** for one user.

- **Exit legs stuck in "held" status**: Even in accounts above the PDT threshold, multiple live-account users (not just paper) reported bracket exit legs remaining "held" after entry completion. This appears intermittently and is not fully explained.

- **Orders stuck in `pending_cancel`**: A documented issue where cancel requests leave orders in `pending_cancel` for minutes to hours, particularly during peak trading (9:45–10:15 AM ET). Multiple GitHub issues (#400, #111) confirm this.

- **`client_order_id` silently ignored**: Custom order IDs on bracket orders are overwritten by Alpaca's system, and child legs cannot have custom IDs at all (GitHub issues #186, #115). This complicates state synchronization for autonomous systems.

- **Bracket orders are entry-only**: Error code `40310000` ("bracket orders must be entry orders") means you cannot use brackets to close an existing position. Only OCO orders work for that purpose.

- **Fractional shares**: Not explicitly confirmed as supported for bracket orders in current documentation, despite general fractional trading support for other order types.

- **PFOF routing**: Alpaca receives payment for order flow from Virtu Americas ($0.12/spread per share, capped at $0.05/share) and Citadel Execution Services. Bracket order legs, being conditional "Not Held" orders, execute on a best-efforts basis through these venues.

- **Self-clearing since 2024**: Alpaca transitioned to self-clearing at DTCC, with additional OCC and FICC memberships in 2025. This reduces (but doesn't eliminate) counterparty risk compared to the previous arrangement through ETC/Velox.

---

## Risk matrix for autonomous bracket order systems

| Failure Mode | Frequency | Severity | Detection Difficulty | Mitigation |
|---|---|---|---|---|
| Overnight gap through stop (no extended hours) | **Weekly** for active portfolio | Moderate–Severe | Easy (check opening prices) | Independent pre-market monitoring + manual limit sells |
| Stock split breaks bracket prices (DNR/DNC) | **2–4x/year** for S&P 100 portfolio | **Catastrophic** | Moderate (monitor corporate action calendar) | Cancel/recreate brackets before split ex-dates |
| Partial fill deadlock on exit legs | **~Monthly** per active system | Severe | Hard (silent failure) | Periodic position-vs-order reconciliation loop |
| Entry partial fill leaves unprotected position | Occasional | Moderate | Easy (monitor fill status) | Timeout and cancel incomplete entries, submit standalone exits |
| Both bracket legs fill in volatile market | Very rare | Moderate | Easy (detect short position) | Monitor for unintended shorts, auto-close |
| Exit legs stuck in "held" status | Uncommon | Severe | Moderate (poll order status) | Fallback exit logic if legs not "new" within N seconds |
| Alpaca trigger system outage | **~Monthly** (some component) | Severe–Catastrophic | Easy (monitor status page) | Independent price monitoring + standalone emergency exits |
| PDT protection blocks exits (<$25K accounts) | Common for small accounts | Severe | Easy (check account equity) | Maintain >$25K equity or accept overnight exposure |
| Circuit breaker halt + reopening slippage | Very rare | Catastrophic | Easy (detect halt) | Accept as residual risk; size positions accordingly |
| 90-day GTC auto-cancel | Rare for 2–15 day holds | Moderate | Easy (check `expires_at`) | Monitor and refresh before expiry |
| Websocket miss on stop-loss cancellation (#198) | Every bracket completion | Moderate | Hard (silent bug) | Use REST polling as backup for order state |

## Conclusion: build defense-in-depth, not bracket-and-pray

The single most important architectural decision for an autonomous Alpaca trading system is recognizing that **bracket orders are a convenience layer, not a reliability layer.** They provide a clean API for the common case but fail silently in at least nine documented ways. The system must implement independent, redundant risk management: a separate monitoring process that tracks real-time prices (including extended hours via Alpaca's market data stream), maintains its own position and order state via REST polling (not just websockets), watches corporate action calendars to preemptively cancel and recreate brackets before splits, reconciles actual positions against expected bracket coverage every few minutes, and has the authority to submit standalone market sell orders when bracket protection has lapsed. The **17.5-hour daily window with zero stop protection** is not an edge case — it is the normal operating condition for every position held overnight. Size positions under the assumption that overnight gaps will occasionally blow through stops entirely, because on Alpaca's bracket order architecture, they will.