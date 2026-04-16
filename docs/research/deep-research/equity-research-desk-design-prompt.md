# Deep Research Prompt: Equity Research Desk Design (Phase 2)

## Classification
- **Type:** Category 1 (literature and industry research) + Category 2 (informed by our own system state)
- **Purpose:** Design the Equity Research Desk — the second trading desk in the Arcis multi-desk architecture. This desk runs alongside the existing Equity Swing Desk (Phase 1) on separate capital with independent attribution.
- **Timeline:** Implementation sprint this weekend (April 19-20, 2026). This research must produce an actionable design spec, not just a survey.
- **Output format:** Structured report ending with a concrete implementation spec that a coding agent can execute in a single weekend sprint.

---

## Context About Our System (Read First)

Arcis is a solo-operated AI-powered equity trading system. Current state as of April 16, 2026:

### Phase 1 — Equity Swing Desk (ACTIVE, under diagnostic review)
- **Strategy:** Pullback-in-uptrend mean reversion on S&P 100 with mechanical 2%/3%/7-day brackets
- **Status:** 85 closed trades. Forensic analysis revealed per-trade Sharpe 3.38 is mostly SPY beta during a bull run (excess vs SPY = +0.039%, t=0.098). Currently in "collect 30 OOS trades with SPY-matched excess" mode to determine if real alpha exists. No optimization work until Stage 1 OOS clears.
- **What works:** Execution pipeline, risk governor (8 checks), earnings filter (hard block within 10 calendar days), bracket orders via Alpaca, dashboard with 25 pages, Telegram alerts, overnight data collection (12 collectors), 1-minute bar collection, SPY-matched excess return instrumentation on every trade.
- **What's broken/uncertain:** Alpha vs SPY may be zero. Attribution resolver was bugged (fixed, re-resolution done). Regime classifier was NULL on 67% of trades (fixed, regression tests added).

### Architecture
- **Backend:** Python 3.12, FastAPI, SQLite (local) + Postgres (cloud sync every 120s)
- **Frontend:** React 19, Tailwind 4, 25 dashboard pages at halcyonlab.app
- **LLM:** Qwen3 8B fine-tuned (Q8_0 GGUF) via Ollama on RTX 3060 12GB. Inference ~2-4s. Used for trade commentary and conviction scoring.
- **Broker:** Alpaca (paper + minimal live). Bracket orders (OCO stop + target). IB cold-stored.
- **Data:** FMP (250 req/day), Finnhub, yfinance, SEC EDGAR, FRED. All daily-timeframe. 1-min bars now collecting nightly.
- **Config:** YAML-driven (`config/settings.local.yaml`). Feature flags for each desk.
- **Watch loop:** Polls every ~60s during market hours. 14 overnight handlers extracted into asyncio-ready handler registry.
- **Training:** PEFT + TRL 0.24 + BitsAndBytes on RTX 3060 12GB. 1,782 training examples.

### Multi-Desk Roadmap
1. Equity Swing (Phase 1) — ACTIVE, diagnostic review
2. **Equity Research (Phase 2)** — THIS IS WHAT WE'RE DESIGNING
3. Options Volatility (Phase 3-4) — vertical spreads at $15-25K
4. Equity Momentum (Phase 5) — breakout/trend
5. Intraday (Phase 6+) — ORB/VWAP, feasibility research complete
6. Event-Driven, Macro/Rates — scoped, not scheduled

### Key Constraints
- **Second Alpaca paper account** for the Research Desk (clean attribution). Ryan already has one paper account for Phase 1.
- **Same local machine** — both desks share the GPU, SQLite, watch loop, and overnight schedule. No additional hardware.
- **Same LLM** — Qwen3 8B serves both desks. Training data can be desk-tagged but model is shared.
- **Weekend implementation timeline** — the design must be implementable in 1-2 days by a coding agent (Claude Code).
- **Capital:** Separate $100K paper allocation. Independent P&L, independent Sharpe tracking, independent excess-return measurement.

---

## Research Area 1: What Should the Research Desk Actually Do?

The original MASTER.md description was vague: "same model, lower thresholds, separate paper account." That's basically "take more of the same trades." The forensic analysis showed the swing desk may not have alpha — so "more of the same" might just mean "more SPY beta."

### Core Questions

1. **What entry signals produce alpha that is UNCORRELATED with pullback-in-uptrend?** The swing desk buys pullbacks in uptrends (mean reversion). The research desk should ideally capture a different alpha source so the two desks aren't correlated. Candidates:
   - **Fundamental momentum:** Enter stocks with improving earnings revisions, revenue surprises, or margin expansion. Hold 2-4 weeks. Academic basis: Post-earnings revision drift (Bernard & Thomas 1989, updated findings post-2020?), SUE (Standardized Unexpected Earnings).
   - **Cross-sectional value:** Buy the cheapest quintile within each sector by EV/EBITDA or P/FCF, short or avoid the most expensive. Academic basis: Fama-French value factor, but is it dead for large-cap? (Arnott et al. 2021, Israel-Moskowitz 2013).
   - **Quality + momentum combination:** High-quality stocks (high ROE, low leverage, stable earnings) with positive 6-12 month momentum. Academic basis: Asness-Frazzini (2013) quality factor, Novy-Marx (2013) gross profitability.
   - **Event-driven:** Earnings date approach (pre-earnings drift), dividend capture, index rebalancing, insider buying signals. Academic basis: varies by event type.
   - **Sector rotation:** Overweight sectors with positive relative strength vs SPY over trailing 1-3 months. Academic basis: Moskowitz-Grinblatt (1999) industry momentum.
   - **Connors RSI(2) deep oversold:** The mean-reversion variant we identified as the top alternative if pullback-in-uptrend fails. Very short-term (2-5 day holds), different entry signal but similar alpha source (mean reversion).

2. **Which of these is most compatible with our existing infrastructure?** Consider:
   - Data availability (FMP gives fundamentals, Finnhub gives news/sentiment, yfinance gives price history, SEC EDGAR gives filings)
   - LLM utility (Qwen3 8B can read earnings transcripts, analyze filings, synthesize multi-source signals — this is where it should shine more than in the swing desk's "is this pullback real?" analysis)
   - Holding period compatibility (watch loop handles daily-timeframe well; anything requiring intraday monitoring uses the same infrastructure as the swing desk)
   - Risk governor compatibility (existing 8-check governor can be parameterized per desk)

3. **What holding period optimizes for alpha that's uncorrelated with SPY drift?** The swing desk holds 3-8 days, which turned out to be mostly correlated with SPY. Options:
   - 1-5 days (Connors RSI — similar to swing desk, may have same SPY beta problem)
   - 2-4 weeks (fundamental momentum — long enough for fundamental signals to play out, short enough to avoid quarterly earnings cycle)
   - 1-3 months (value/quality — deep fundamental, but low turnover means slow data accumulation)
   - Mixed (different hold periods for different signal types)

4. **What is the realistic excess-Sharpe for a research-style desk on S&P 100 at retail scale?** Be honest about:
   - Transaction costs at Alpaca (we know these: ~3 bps round-trip on S&P 100)
   - The fact that S&P 100 is the most researched, most efficient universe
   - Whether expanding to S&P 500 or Russell 1000 materially increases alpha opportunity
   - Published post-2020 results for each strategy type with effect sizes

5. **Should we expand the universe beyond S&P 100?** The swing desk uses S&P 100 for liquidity and narrow spreads. The research desk might benefit from:
   - S&P 500 (more names, more dispersion, slightly wider spreads)
   - Russell 1000 (even more dispersion, but data coverage from FMP may be thinner)
   - Staying at S&P 100 (simplest, reuses existing universe module, same GICS lookup)
   - Starting at S&P 100 and expanding later if alpha is found

### Output Format
- Comparison table: Strategy | Academic citation | Expected excess-Sharpe | Hold period | Correlation with pullback-in-uptrend | Data requirements | LLM utility (1-5) | Implementation complexity (1-5)
- Top 3 recommended strategies ranked by: (a) uncorrelated with swing desk, (b) LLM adds most value, (c) implementable in a weekend
- Recommended universe with justification
- Recommended hold period with justification

---

## Research Area 2: How Should the LLM's Role Differ?

The swing desk uses the LLM for trade commentary and conviction scoring on pullback setups. The research desk should use the LLM differently — this is where the "research" in "Research Desk" should mean something.

### Core Questions

1. **What research tasks can an 8B LLM perform that add alpha to a fundamental strategy?** Candidates:
   - Earnings transcript analysis (summarize key themes, detect management tone shift, flag guidance changes)
   - SEC filing analysis (10-K/10-Q risk factor changes, MD&A sentiment, insider transaction patterns)
   - News synthesis (aggregate and weight recent news for a ticker, produce a directional bias)
   - Multi-source signal integration (combine price action + fundamentals + news into a structured recommendation)
   - Competitive landscape analysis ("How does AAPL's margin trend compare to sector peers?")

2. **Should the LLM produce a different output format for the research desk?** The swing desk uses XML-tagged commentary with conviction scores. The research desk might benefit from:
   - Longer-form research notes (2-3 paragraphs vs 1 paragraph)
   - Explicit bull/bear/base case scenarios
   - Target price ranges with probability weights
   - Catalyst timeline (what events could move the stock in the next 2-4 weeks?)
   - Risk factor ranking

3. **Can we reuse the existing 1,782 training examples or do we need new ones?** The current training data is pullback-specific. Research desk training data would need to cover:
   - Fundamental analysis commentary
   - Multi-week hold thesis construction
   - Earnings-driven analysis
   - Sector-relative analysis

4. **How many training examples does the research desk need before going live?** Options:
   - Zero (use the base Qwen3 8B without fine-tuning for research tasks, fine-tune later)
   - 100-200 (minimal fine-tune on research-style commentary, using synthetic data from a frontier model)
   - 500+ (full fine-tune cycle, gated on accumulating real research-trade outcomes)

### Output Format
- Decision matrix: LLM task | Data source required | Expected signal quality | Implementation effort | Recommendation
- Recommended output format (XML template or similar)
- Training data strategy: how many examples, how to generate them, synthetic vs real, timeline

---

## Research Area 3: Execution and Risk Architecture

### Core Questions

1. **How do two desks share one watch loop?** The watch loop currently runs one scan cycle per iteration. Options:
   - Two scan cycles per iteration (swing scan + research scan, sequential)
   - Separate scan intervals (swing every 60s, research every 5 min or every hour)
   - Research desk runs on overnight schedule only (generate recommendations after hours, execute at open)
   - Separate watch loop process (heavier, but clean isolation)

2. **How do we isolate risk between desks?** Current risk governor has position limits, sector concentration, daily loss limits. With two desks:
   - Per-desk position limits (e.g., swing max 10, research max 5)
   - Per-desk capital allocation (e.g., $50K each, or $100K each since both are paper)
   - Shared or separate kill switches
   - Cross-desk correlation monitoring (don't hold AAPL on both desks)

3. **How does the second Alpaca paper account work?**
   - Alpaca allows multiple paper accounts? Or do we need a second email/login?
   - API key management (two sets of keys in config)
   - How to route orders to the correct account based on desk tag

4. **How do bracket parameters differ for the research desk?** If hold period is 2-4 weeks:
   - Wider stops (5-8% vs 3% for swing)
   - Wider targets (8-15% vs 2% for swing)
   - Longer timeout (20-30 days vs 7 days)
   - Or ATR-based dynamic brackets instead of fixed percentages

5. **SPY-matched excess return applies identically** — every research desk trade gets the same spy_return_over_hold, excess_return, realized_sector columns. No changes needed to the D1 instrumentation. Just confirm this works for longer hold periods.

### Output Format
- Architecture decision: shared watch loop vs separate process, with pros/cons
- Risk parameter table: parameter | swing desk value | research desk value | rationale
- Alpaca multi-account setup guide
- Bracket parameter recommendation for 2-4 week holds

---

## Research Area 4: Attribution and Performance Measurement

### Core Questions

1. **How do we measure the research desk independently?** It needs its own:
   - Excess-Sharpe (vs SPY over same hold period)
   - Win rate, profit factor, max drawdown
   - Attribution: does the LLM's research add alpha over a mechanical signal?

2. **What's the research desk's equivalent of the swing desk's Phase 1 gate?** Propose:
   - Minimum trade count for statistical significance at 2-4 week hold periods
   - Excess-Sharpe threshold
   - Timeline to reach the gate (at 1-2 new trades per week, 30 trades = 15-30 weeks)

3. **How do we prevent the two desks from being secretly correlated?** If both desks buy AAPL on the same day, they're not independent. Options:
   - Hard constraint: no ticker overlap between desks at any time
   - Soft constraint: overlapping positions flagged but allowed, with correlation measured
   - Sector-level diversification: if swing desk is heavy in Tech, research desk avoids Tech

4. **How does training data work across desks?** When a research desk trade closes:
   - Generate a training example tagged `desk=research`
   - Use a different prompt template (research-style vs pullback-style)
   - Separate training corpus or mixed?
   - If mixed: does research desk data help or hurt the swing desk's model performance?

### Output Format
- Performance measurement framework: metric | how to compute | threshold for success
- Gate definition: what constitutes Phase 2 validation
- Correlation management recommendation
- Training data isolation strategy

---

## Research Area 5: Weekend Implementation Scope

### Core Questions

1. **What is the minimum viable Research Desk that can be built in one weekend?** Must include:
   - New scanner (or modified existing scanner with different parameters)
   - Second Alpaca paper account wired into execution
   - Desk-tagged trades in shadow_trades (or separate table)
   - Dashboard visibility (even if minimal — just a filtered view of Trade History)
   - SPY excess instrumentation working from day 1
   - Basic attribution tracking

2. **What can be deferred to a follow-up sprint?** Candidates:
   - Full LLM research commentary (start mechanical, add LLM later)
   - Custom training examples (reuse base model initially)
   - Dedicated dashboard page (use existing Trade History with desk filter)
   - Advanced risk correlation monitoring
   - Separate Telegram notification channel

3. **What existing code can be reused vs what needs to be new?**
   - Scanner: fork existing scan_service.py or parameterize it?
   - Executor: same executor with desk-routing logic, or separate?
   - Risk governor: same governor with per-desk config, or separate instance?
   - Journal/store: same shadow_trades table with desk column, or separate table?
   - Dashboard: filter existing pages by desk, or new pages?

### Output Format
- MVP task list (max 10 tasks, implementable in 1-2 days by a coding agent)
- Deferred task list (follow-up sprint)
- Code reuse map: component | reuse strategy | new code needed

---

## Constraints

1. **Must produce excess-Sharpe, not raw Sharpe, from day 1.** We learned this lesson painfully. The research desk's primary metric is excess return vs SPY over the hold period, same as the swing desk.

2. **The research desk must be genuinely different from the swing desk.** "Same strategy with lower thresholds" is not a research desk — it's a parameter change. If the research indicates that a fundamentally different entry signal is needed, recommend it even if it's harder to build.

3. **LLM should add more value to the research desk than to the swing desk.** The swing desk's pullback signal is mostly mechanical — the LLM adds commentary but unclear alpha. The research desk should be designed so the LLM's analytical capabilities are the core differentiator, not an afterthought.

4. **Be honest about timeline to statistical significance.** At 1-2 trades per week, it takes 15-30 weeks to reach 30 trades. If the recommended strategy trades less frequently, say so and quantify the validation timeline.

5. **Don't over-engineer.** This is a weekend build on existing infrastructure. The first version should be functional and generating data, not architecturally perfect.

6. **Cite papers with dates.** Same standard as all Arcis research.

---

## Deliverable

A structured report covering all 5 research areas, ending with:

1. **Executive summary:** What the Research Desk should be, why it's different from the swing desk, and what alpha source it captures.

2. **Recommended strategy with parameters:** Entry signal, universe, hold period, bracket parameters, exit logic — specific enough to implement.

3. **LLM role and output format:** What the model does for the research desk, how it's different from swing desk usage.

4. **Weekend MVP spec:** 10-task implementation plan that a coding agent can execute in 1-2 days. Include file paths, function signatures, config keys, and test cases.

5. **Phase 2 gate definition:** What validates the research desk and how long it takes.

6. **What to monitor in the first 30 days:** Key metrics, failure modes, and when to intervene.
