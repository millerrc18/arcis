# Halcyon Lab: comprehensive research compendium for autonomous AI equity trading

**Halcyon Lab operates at the intersection of open-source AI and systematic equity trading — a space where the basic technology stack is now fully commoditized but the execution discipline, overfitting controls, and operational reliability that separate survivors from casualties remain deeply non-trivial.** This compendium synthesizes academic research, practitioner evidence, and current-state competitive intelligence across 10 domains critical to the system's Phase 1 bootcamp and beyond. Every recommendation is calibrated for the specific constraints: solo operator, defense contractor day job, Windows 11/RTX 3060, Alpaca broker, ~$100K capital, $64/month cloud budget.

---

## Topic 1: Market microstructure favors the small

S&P 100 stocks are among the most liquid securities on Earth, and a **$10K trade on any constituent produces zero measurable market impact**. This is the single most important microstructure fact for Halcyon Lab: execution cost optimization, while intellectually interesting, yields marginal returns at this scale. The dominant cost is the bid-ask spread, not impact.

### Spreads by market cap quintile

Top-quintile mega-caps (AAPL, MSFT, NVDA, AMZN) trade with spreads locked at the minimum tick of **$0.01, approximately 0.5–1.0 basis points**. Second-quintile names (JPM, V, UNH) show **1–2 bps**, while bottom-quintile S&P 100 constituents run **3–10 bps**. The portfolio average across the full S&P 100 is approximately **3.7 bps** per Nasdaq's spread-coverage analysis. Spreads follow a well-documented U-shaped intraday pattern (Wood, McInish & Ord 1985; Andersen & Bollerslev 1997): **widest at open (30–50% above midday)**, tightest from 10:30 AM to 2:30 PM ET, and widening again into the close. During elevated VIX regimes (>25), mega-cap spreads widen approximately **2–3×** to 2–5 bps; lower-quintile names can reach 5–15 bps.

### Market impact is functionally zero at retail scale

Using the Almgren et al. (2005) square-root law (Impact ∝ σ × (Q/V)^0.5), a $10K trade on AAPL ($15B+ daily volume) represents 0.00007% of ADV, producing temporary impact of approximately **0.01 bps** — entirely within noise. Even the smallest S&P 100 stock (~$200M ADV) shows impact below 0.1 bps at $10K. Frazzini, Israel & Moskowitz (2018), analyzing **$1.7 trillion** of live AQR data, found actual institutional trading costs were "an order of magnitude smaller" than earlier academic estimates, with median impact of ~8 bps — for orders thousands of times larger than Halcyon's.

### Optimal entry window: 10:00–12:00 PM ET

Heston, Korajczyk & Sadka (2010, *Journal of Finance*) documented half-hour return periodicity and short-term reversal driven by liquidity imbalances — exactly the mechanism a pullback strategy exploits. Their key finding: "Timing trades can reduce execution costs by the equivalent of the effective spread." The evidence strongly supports **entering pullback trades between 10:00 AM and 12:00 PM ET**, after opening noise dissipates but while short-term reversals are materializing. Avoid the first 30 minutes (widest spreads, noisiest price action) and the final 30 minutes.

### Order type: aggressive limit orders, not VWAP

For $5K trades on mega-caps, **use limit orders at or slightly above the ask** (for buys). This provides near-certain fills with price protection against flash crashes. VWAP algorithms are designed for institutional orders representing significant fractions of ADV — completely irrelevant for retail-sized trades. Market-on-open orders execute at the worst possible time for a pullback strategy (widest spreads, highest volatility).

### Slippage budget and paper-to-live discount

**Backtest with 5 bps round-trip slippage** (entry + exit combined) as the base case. Stress-test at 3 bps (optimistic) and 10 bps (high-VIX). This is consistent with Double Finance's default, the QuantInsti practitioner range ($0.02–$0.10/share), and appropriate conservatism above the theoretical minimum. At 3 trades/day × 252 days × 5 bps × $5K average position = **~$1,900/year slippage drag** (~1.9% of $100K capital).

Alpaca paper trading fills at mid-price with infinite liquidity and **no slippage simulation**. Community reports show paper fill delays of 50–260 seconds for limit orders versus milliseconds live. **Discount paper P&L by 15–25%** when projecting live performance. Transition to live with minimum $1K positions after initial paper validation — real execution data is far more valuable than extended paper testing.

### Priority actions for Topic 1
1. **Now**: Set backtest slippage to 5 bps round-trip; stress-test at 10 bps
2. **Now**: Restrict trading universe to top-40 S&P 100 names by market cap for tightest spreads
3. **Now**: Configure entry window to 10:00 AM–12:00 PM ET in system rules
4. **Week 1**: Implement aggressive limit orders (at ask + $0.01); avoid market orders and VWAP
5. **Month 1**: Transition from paper to live with minimum position sizes ($1K) to build real slippage data

---

## Topic 2: The fund formation path is expensive and long

The legal pathway from solo trader to registered investment adviser spans **3–5 years and $100K+ in formation costs alone**, making it essential to build a live track record for 12–24 months before committing capital to fund infrastructure.

### Stage-by-stage costs and thresholds

**Stage 1 — LLC ($200–$500, 1–2 weeks)**: Form a management company LLC, preferably in Delaware. This provides liability protection and separates trading from personal assets.

**Stage 2 — Fund formation ($10,000–$50,000, 4–8 weeks)**: Requires three entities (Fund LP, General Partner LLC, Management Company LLC) plus legal documents (PPM, LPA, subscription docs, Form D). Budget options like Repool or flat-fee firms can deliver docs for **$5,000–$15,000**; traditional fund formation attorneys charge **$15,000–$30,000**; AmLaw 100 firms run **$30,000–$75,000+**.

**Stage 3 — Registration**: Under **$100M AUM, register with the state** securities regulator (not SEC). The Exempt Reporting Adviser (ERA) option is available for private fund advisers managing <$150M — it requires only abbreviated Form ADV filing and carries lighter compliance burden. Acting SEC Chairman Uyeda directed staff in April 2025 to evaluate raising the $100M threshold, but no formal proposal yet. State registration typically costs **$200–$500** in filing fees plus legal counsel.

### Track records and what allocators actually want

**66% of institutional allocators** require a minimum **3–5 year track record** (Preqin data), though **27% will consider under 3 years** — and these tend to be larger allocators averaging $32.5B AUM. **Paper trading does not count** for institutional allocators. Returns must be audited by an independent accounting firm and NAV reports must come from an independent fund administrator.

GIPS compliance is voluntary but increasingly expected — **75% of consultants** in the ACA/eVestment survey expect alternatives managers to comply. Cost: ~$50K/year for a small firm. For a sub-$5M fund, this is aspirational, not essential.

### Annual operating costs make small funds unviable

| Item | Annual cost |
|------|------------|
| Fund administrator | $24,000–$60,000 |
| Annual audit | $15,000–$30,000 |
| Legal counsel | $10,000–$25,000 |
| Insurance (D&O/E&O + cyber) | $14,000–$30,000 |
| Compliance/regulatory | $5,000–$10,000 |
| Technology | $5,000–$15,000 |
| **Total** | **$79,000–$180,000/year** |

At a **1.5% management fee on $2M AUM = $30,000/year revenue** — the fund is deeply unprofitable. Break-even requires approximately **$5–$10M AUM**. The fee structure that works for launch: **1.5% management / 20% performance** with 6% hard hurdle and high-water mark, with a founder class at **1% / 15%** with 3-year lock-up for early investors.

### The defense contractor complication

This is a **critical legal issue**. Federal conflict-of-interest statutes (18 U.S.C. § 208) and OGE guidance require that government employees and cleared contractors disclose outside business activities and potentially divest financial interests that create conflicts. **Obtain written ethics clearance from your employer before launching any fund.** Consider restricting the fund from trading defense-related stocks.

### Realistic capital raising timeline

$100K personal capital → 12–24 months live track record → friends & family capital ($250K–$1M) → family office allocations ($250K–$2M) → emerging manager programs (most require $50M+ AUM, far above initial scale). **Realistic timeline to $2M AUM: 12–24 months post-launch. To viability ($5–10M): 24–48 months.** The biggest constraint: being a full-time employee severely limits fundraising capacity, and allocators flag part-time fund managers as a red flag.

### Priority actions for Topic 2
1. **Now**: Form management company LLC ($200–$500)
2. **Now**: Resolve defense contractor ethics/employment disclosure requirements
3. **Month 1–24**: Build live, auditable track record with detailed performance attribution
4. **Year 2+**: Engage fund formation counsel; target ERA status initially
5. **Year 3+**: Launch fund only when live Sharpe >1.0 over 24+ months and personal capital reaches $250K+

---

## Topic 3: Regulatory risk is minimal for personal trading

A solo retail trader using an LLM-based autonomous system on their own $100K account faces **minimal direct regulatory burden**. The primary risks are market manipulation (applicable to all traders), inadvertent investment adviser status if sharing signals, and AI-washing liability if seeking capital.

### No FINRA registration required for personal algo trading

FINRA registration requirements for algorithmic trading (Rule 1032(f), Regulatory Notice 16-21) apply exclusively to **associated persons of FINRA member broker-dealers**, not retail customers trading their own capital. There are **no filing, registration, or disclosure requirements** for running an autonomous trading system on a personal brokerage account. The Pattern Day Trader rule ($25K minimum) is irrelevant for a $100K account, and FINRA's board approved amendments in September 2025 to eliminate the PDT classification entirely (pending SEC approval).

### SEC algo regulations target broker-dealers, not retail

Rule 15c3-5 (Market Access), Regulation SCI, and FINRA 15-09 all apply to broker-dealers and exchanges. **Confirmed: none apply to retail traders.** Your broker (Alpaca) maintains the required risk controls. The only universally applicable rules are anti-manipulation provisions — no spoofing, layering, or wash trading (Securities Exchange Act § 9(a)(2), Rule 10b-5).

### AI-washing enforcement targets false claims to investors

The SEC's first AI-washing cases (March 2024) fined **Delphia $225,000 and Global Predictions $175,000** for falsely claiming AI capabilities that didn't exist. Delphia never actually built the claimed algorithm. The SEC's Cyber and Emerging Technologies Unit (CETU, formed February 2025) has made AI-washing an immediate priority. The legal standard: Section 206(2) requires only **negligence, not intent to defraud**. Key principle: you can use terms like "AI-powered" if it's **true and substantiated** — but vague claims without specific technical explanations create enforcement risk when soliciting investors.

### Inadvertent investment adviser risk from public signals

Under the three-element test (compensation + business of advising + about securities), sharing trades on a public dashboard creates **low-to-medium risk** if you accept no compensation and keep content impersonal. The publisher's exclusion (Lowe v. SEC, 1985) protects impersonal, bona fide commentary on a regular schedule. **Never accept compensation for trade ideas** — this is the simplest way to avoid IA status. Retrospective trade disclosure (what you already did) is safer than forward-looking signals.

### Data collection and patent risk are very low

SEC EDGAR and FRED are public government data with no legal restrictions beyond rate limits (EDGAR: 10 req/sec). Finnhub access is governed by API terms of service. Post-hiQ v. LinkedIn (2022), scraping publicly accessible data does not violate the CFAA. **Patent risk for using Qwen3 (Apache 2.0) for personal trading is negligible** — the license includes an express patent grant, and no known patents specifically cover open-source LLM equity signal generation.

### Priority actions for Topic 3
1. **Now**: Ensure trading system cannot engage in spoofing, layering, or wash trading (anti-manipulation)
2. **Now**: Add disclaimers to any public dashboard ("not investment advice")
3. **Before seeking capital**: Engage securities attorney for AI capability claim review
4. **Before fund launch**: Complete SEC/state registration (ERA or state RIA)
5. **Ongoing**: Never share forward-looking signals for compensation without proper registration

---

## Topic 4: SQLite will serve you well for years

With proper indexing, SQLite in WAL mode handles **10–100 million rows** with excellent query performance. At 500K rows/year, Halcyon Lab has **10–20 years** before SQLite becomes a bottleneck. The dual-database architecture (SQLite local + Render Postgres for dashboard) is the right design.

### WAL mode configuration for trading workloads

SQLite WAL mode allows **one writer plus many concurrent readers** — adequate for 13 scans/day plus 12 overnight collectors if writes are serialized or batch-committed. Apply this PRAGMA configuration at connection initialization:

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;       -- Safe in WAL mode, major perf gain
PRAGMA busy_timeout = 5000;        -- 5s wait prevents 'database locked'
PRAGMA cache_size = -64000;        -- 64MB page cache
PRAGMA mmap_size = 268435456;      -- 256MB memory-mapped I/O
PRAGMA wal_autocheckpoint = 1000;  -- Default, adequate
PRAGMA optimize;                   -- Run before closing connections
```

### Fix unbounded SELECT * queries immediately

Unbounded `fetchall()` on a 2.5M-row table consumes **2.5–5 GB of RAM** (Python object overhead is 5–10×). Search the codebase with `grep -rn "fetchall()" --include="*.py"` and replace with paginated queries using `LIMIT`/`OFFSET` or `cursor.fetchmany(5000)` for batch processing. Every FastAPI endpoint serving table data must enforce `LIMIT` with a maximum of 1,000 rows per response.

### Safe backup during active writes

**Never copy the database file directly** — this risks corruption when WAL is active. Use Python's `connection.backup()` API, which handles WAL correctly:

```python
import sqlite3

def safe_backup(source_db: str, backup_path: str):
    source = sqlite3.connect(f"file:{source_db}?mode=ro", uri=True)
    dest = sqlite3.connect(backup_path)
    source.backup(dest, pages=100, sleep=0.01)  # 100 pages at a time
    dest.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    dest.close()
    source.close()
```

Schedule this daily at 2 AM via Windows Task Scheduler.

### Don't migrate to Postgres yet

The dual-database architecture is correct: SQLite handles local writes with zero latency; Render Postgres ($6/month Basic-256mb) serves the dashboard. Migration triggers that don't currently apply: `database is locked` errors >1/week, need for concurrent writers, database >10 GB. **Keep SQLite local indefinitely**; sync to Postgres on 5-minute intervals using a delta-sync script keyed on `last_modified` timestamps.

### Data archival preserves queryability

Archive `scan_metrics` older than 6 months, `recommendations` older than 1 year, and `options_chains` older than 2 years to separate SQLite files per year. Use `ATTACH DATABASE` to query across current and archived data:

```sql
ATTACH DATABASE 'trading_archive_2025.db' AS archive;
SELECT * FROM main.options_chains
UNION ALL SELECT * FROM archive.options_chains
WHERE underlying_symbol = 'SPY' ORDER BY quote_date DESC LIMIT 100;
```

### FTS5 for training examples: yes, implement it

Even at <100K rows, FTS5 provides **O(1) lookups with BM25 relevance ranking**, Boolean operators, prefix matching, and Porter stemming — far superior to `LIKE '%term%'` which scans every row. Storage overhead is ~1–2× but trivial at this scale. Create an external content FTS5 table with insert/update/delete triggers for automatic synchronization.

### Priority actions for Topic 4
1. **This week**: Apply PRAGMA configuration block; audit for unbounded SELECT * / fetchall()
2. **This week**: Add essential indexes on `options_chains(underlying_symbol, expiration_date, quote_date)`
3. **This week**: Implement `connection.backup()` daily backup script
4. **This month**: Enable incremental auto-vacuum; add pagination to all API endpoints
5. **Quarterly**: Run VACUUM INTO for defragmented backup; review EXPLAIN QUERY PLAN for slow queries
6. **Annually**: Archive data beyond retention thresholds to separate SQLite files

---

## Topic 5: Windows hardening for unattended trading

A 24/7 autonomous trading system on Windows 11 requires deliberate hardening against forced restarts, VRAM leaks, sleep states, and power failures. These are the five interventions that matter most.

### Prevent Windows Update restarts with registry keys

Set these via elevated PowerShell or `.reg` file:

```
HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU
  NoAutoUpdate = 1 (DWORD)
  AUOptions = 2 (DWORD) — "Notify for download"
  NoAutoRebootWithLoggedOnUsers = 1 (DWORD)

HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate
  ExcludeWUDriversInQualityUpdate = 1 (DWORD)
```

Set Active Hours to the maximum 18-hour window (4 AM to 10 PM). Schedule manual update checks for Saturday 3 AM using `usoclient StartScan` via Task Scheduler — review and install manually on weekends.

### Pin NVIDIA drivers and manage Ollama VRAM leaks

Block driver auto-updates using the `ExcludeWUDriversInQualityUpdate` registry key above, plus device-ID-specific restrictions via `HKLM\SOFTWARE\Policies\Microsoft\Windows\DeviceInstall\Restrictions\DenyDeviceIDs`. Uninstall GeForce Experience/NVIDIA App to prevent NVIDIA's own updater.

Ollama has **well-documented VRAM fragmentation** (GitHub issues #8283, #10114, #10132, #10372, #13235) that accumulates over 24+ hours of continuous use. The only reliable fix: **restart Ollama daily at 3 AM** via scheduled task, and run a VRAM watchdog that monitors with `pynvml` and triggers restart when VRAM exceeds 90% (10.8 GB of 12 GB). Set `OLLAMA_MAX_LOADED_MODELS=1` and `OLLAMA_KEEP_ALIVE=5m` as system environment variables to reduce fragmentation rate.

### NSSM for bulletproof process management

NSSM (Non-Sucking Service Manager) is the most reliable option for running Python trading systems as Windows services with auto-restart on crash:

```powershell
nssm install "TradingBot" "C:\TradingSystem\venv\Scripts\python.exe" "C:\TradingSystem\main.py"
nssm set "TradingBot" AppDirectory "C:\TradingSystem"
nssm set "TradingBot" AppExit Default Restart
nssm set "TradingBot" AppRestartDelay 10000
nssm set "TradingBot" AppRotateFiles 1
nssm set "TradingBot" AppRotateBytes 10485760
nssm set "TradingBot" Start SERVICE_DELAYED_AUTO_START
```

Install both the trading system and the VRAM watchdog as separate NSSM services.

### Prevent sleep with defense-in-depth

Apply all three layers: (1) `powercfg /X -standby-timeout-ac 0` plus `powercfg /hibernate off`; (2) Disable Modern Standby via registry (`PlatformAoAcOverride=0` and `CsEnabled=0` at `HKLM\SYSTEM\CurrentControlSet\Control\Power`); (3) Call `SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED)` in your Python process using ctypes at startup with an `atexit` handler to release.

### UPS graceful shutdown integration

Connect UPS via USB (Windows detects it as a battery via `Win32_Battery` WMI). Set critical battery action to Shutdown at 10% via `powercfg /setdcvalueindex SCHEME_CURRENT SUB_BATTERY BATACTIONCRIT 3`. Run a PowerShell UPS monitor script as a startup scheduled task that polls every 15 seconds — when battery drops below 20%, it stops the TradingBot service (allowing 30 seconds for state save/position close), stops Ollama, and initiates system shutdown.

### Priority actions for Topic 5
1. **Now**: Run the master setup PowerShell script (Update control + sleep prevention + power plan)
2. **Now**: Install NSSM; configure TradingBot and VRAMWatchdog as services
3. **Now**: Deploy VRAM watchdog with pynvml monitoring + Ollama auto-restart
4. **Now**: Schedule daily Ollama restart at 3 AM
5. **This week**: Configure UPS with graceful shutdown script
6. **Monthly**: Manually apply Windows updates during weekend maintenance windows

---

## Topic 6: Render costs can drop 78% to ~$13/month

The current ~$64/month Render spend can be reduced to approximately **$13–14/month** by moving the React frontend to a free static site and using the cheapest paid Postgres tier.

### Optimized architecture saves $50/month

| Service | Current | Optimized | Savings |
|---------|---------|-----------|---------|
| FastAPI backend | Starter ($7) | Starter ($7) | $0 |
| React frontend | Starter ($7) | **Static Site (free)** | **$7** |
| Postgres | ~$19 | **Basic-256mb ($6)** | **$13** |
| Workspace | Professional ($19)? | **Hobby (free)** | **$19** |
| **Total** | **~$52+** | **~$13** | **~$39+** |

**Render Static Sites are permanently free** with global CDN, automatic TLS, Brotli compression, and auto-deploy from Git. The only change required: configure CORS on the FastAPI backend to accept requests from `https://halcyonlab.app`, and set up the React build to call `api.halcyonlab.app` for API requests.

### Starter plan eliminates cold starts

Paid Render web services (Starter, $7/month) **do not spin down** — only Free instances auto-sleep after 15 minutes. Cold starts are not a concern on the Starter plan. The 0.5 CPU / 512 MB RAM is adequate for a single-user dashboard.

### In-memory caching eliminates Redis need

For a solo-operator dashboard, use `fastapi-cache2` with `InMemoryBackend` instead of Redis ($10/month saved). Cache portfolio summaries at 60s TTL, scan results at 300s, trade history at 600s. Invalidate on sync completion by calling a `/api/sync/complete` endpoint from the local sync script.

### 5-minute polling sync is sufficient

For a dashboard checked several times daily, 5-minute polling from local SQLite to Render Postgres via `psycopg2` with upsert (`ON CONFLICT DO UPDATE`) is the right approach. LISTEN/NOTIFY and CDC are overkill. Restrict Render Postgres external access to your home IP via CIDR in the Networking settings.

### Security hardening for financial dashboard

Render provides free TLS (Let's Encrypt + Google Trust Services) with automatic HTTP→HTTPS redirect. Add: API key authentication via `X-API-Key` header, in-memory rate limiting (60 req/min), security headers (HSTS, X-Frame-Options: DENY, CSP), and strict CORS allowing only `halcyonlab.app`.

### Priority actions for Topic 6
1. **This week**: Move React frontend to Render Static Site (free) — biggest single cost saving
2. **This week**: Switch Postgres to Basic-256mb ($6/month)
3. **This week**: Add API key authentication and security headers to FastAPI
4. **This month**: Implement in-memory caching with TTL per endpoint
5. **This month**: Restrict Postgres external access to home IP
6. **Evaluate**: Downgrade workspace to Hobby if not using Professional features

---

## Topic 7: Your 2–3 year backtest probably isn't long enough

The minimum backtest length formula (Bailey & López de Prado 2014) shows that with only 30 months of data, **a Sharpe ratio below 1.0 cannot be statistically validated** at 95% confidence. This is the most sobering quantitative finding in this compendium.

### Minimum backtest length by target Sharpe

| Annualized Sharpe | MinBTL (months) | MinBTL (years) |
|:-:|:-:|:-:|
| 0.7 | ~67 | **5.6** |
| 0.8 | ~52 | **4.3** |
| 0.9 | ~41 | **3.4** |
| 1.0 | ~34 | **2.8** |

Formula (Bailey & López de Prado 2014, *Journal of Portfolio Management*): MinTRL = 1 + [1 - γ₃·SR + (γ₄-1)/4·SR²] × (z_α/SR)². With fat tails (γ₄=5) and negative skew (γ₃=-0.5), these numbers increase by **20–40%**. The implication: 2–3 years of data can only validate strategies with Sharpe ≥ 1.0.

### Haircut Sharpe ratio: the multiple testing penalty

With 3 strategies × ~10 parameters ≈ **30 effective trials**, a backtest Sharpe of 1.2 over 30 months yields a Bonferroni-adjusted Sharpe of approximately **zero** — the result is not statistically significant after correcting for multiple testing. Even with the less conservative BHY correction, the haircut is **60–75%**, leaving an adjusted Sharpe of 0.3–0.5. Harvey & Liu (2015, *Journal of Portfolio Management*) developed the analytical framework showing haircuts are nonlinear — marginal strategies are effectively eliminated.

### Hansen's SPA test beats White's Reality Check

The `arch` Python library implements both in one class. **Use SPA exclusively** (set `studentize=True`) — it strictly dominates White's RC by studentizing the test statistic and using a sample-dependent null distribution. Monte Carlo evidence (Hansen 2005, *JBES*) shows SPA maintains ~80% power with 100 models versus ~50% for RC. Implementation is 5 lines:

```python
from arch.bootstrap import SPA
spa = SPA(benchmark_losses, strategy_losses, block_size=10,
          reps=1000, bootstrap='stationary', studentize=True)
spa.compute()
print(f"SPA consistent p-value: {spa.pvalues}")  # Reject H0 if < 0.05
```

### Probability of Backtest Overfitting (PBO) is your primary defense

Bailey, Borwein, López de Prado & Zhu (2017, *Journal of Computational Finance*) developed CSCV: split data into S equal subsets (S=16), evaluate all C(S, S/2) IS/OOS combinations, and compute what fraction of times the IS-optimal strategy underperforms the OOS median. **PBO < 0.20 = acceptable; PBO > 0.50 = severe overfitting.** For 30 strategy configurations with S=8, this produces 70 IS/OOS combinations — computationally feasible on consumer hardware. The `pypbo` library provides a pip-installable implementation.

### Synthetic data extends effective validation

Generate realistic S&P 100-like returns using a **2-regime HMM + GARCH(1,1) + Student-t(5df)** model. Calibrate to historical data using `hmmlearn.hmm.GaussianHMM` and the `arch` library for GARCH parameters. Run the pullback strategy on 100+ synthetic paths — if profitable on >60% with realistic parameters, this provides additional OOS evidence beyond the limited historical window.

### CPCV implementation for overlapping holds

For 1–15 day holding periods, set `purge_days = 15` (max holding period) and `embargo_days = 15` to prevent serial correlation leakage. With N=6 groups and k=2 test groups, CPCV generates C(6,2)=15 splits and 5 independent backtest paths. Use `skfolio.model_selection.CombinatorialPurgedCV` for a scikit-learn-compatible production implementation.

### Priority actions for Topic 7
1. **Now**: Calculate MinBTL for your target Sharpe — determine if you have enough data
2. **Now**: Run SPA test (5 lines with `arch`) — does ANY strategy beat buy-and-hold?
3. **Week 1**: Compute Haircut Sharpe for your best strategy with actual trial count
4. **Week 1**: Implement PBO with `pypbo` — target PBO < 0.20
5. **Month 1**: Generate 100 synthetic paths and validate strategy on synthetic data
6. **Month 2**: Implement CPCV for ongoing strategy evaluation

---

## Topic 8: Bayesian methods let you decide earlier with less data

With only 50–200 completed trades, frequentist methods lack statistical power. Bayesian estimation with informative priors from academic literature enables **earlier and more calibrated go/no-go decisions** through posterior probability statements.

### Bayesian Sharpe estimation with informative priors

Model daily returns as StudentT(ν, μ, σ) with priors grounded in the academic literature: μ ~ Normal(0.0004, 0.0006) centers on Sharpe 0.5 (skeptical but plausible) with 95% prior mass covering Sharpe -0.5 to 1.5. After sampling in PyMC, compute P(Sharpe > 0.5 | data) directly from the posterior. Key academic priors: equity long-short momentum Sharpe **0.40–0.60** (Jegadeesh & Titman 1993), value+momentum combined **1.0–1.45** (Asness, Moskowitz & Pedersen 2013), pullback/mean-reversion **0.40–0.80** (synthesized from reversal literature).

### Sequential phase gates enable earlier decisions

Define Bayesian stopping rules: **ADVANCE** if P(Sharpe > 0.5 | data) > 0.90; **STOP** if P(Sharpe < 0 | data) > 0.80; otherwise **CONTINUE** collecting data. Update after every batch of 10 trades. This maps directly to clinical trial early stopping methodology (Thall & Simon 1995). With informative priors, a go/no-go decision may be reachable at **50–80 trades** rather than the 200+ required by frequentist methods.

### Beta-Binomial for win rate assessment

Use Beta(6, 5) as a weakly informative prior (mean ≈ 0.545, effective sample size 11). This lets data dominate after ~11 trades. With 30 trades and 20 wins: posterior is Beta(26, 15), mean = 0.634, 95% CI = [0.48, 0.77], P(win_rate > 0.5) = 0.938. The key insight: **with Beta(6,5) prior, 30 trades of data substantially shift the posterior**, while with the more informative Beta(30,25), you'd need 55+ trades for data to dominate.

### Use PyMC v5 on Windows — skip NumPyro and Stan

**PyMC v5 is the clear winner** for this use case. Native Windows support via conda, excellent documentation, ArviZ integration for diagnostics. Install with `conda create -c conda-forge -n bayesian python=3.12 "pymc>=5" arviz`. GPU acceleration is irrelevant for 50–200 observations — CPU sampling completes in seconds. NumPyro requires JAX, which is Linux-only for CUDA. Stan works via CmdStanPy but adds installation complexity for no benefit at this scale.

### Decision framework for phase progression

| Phase | Trades | Method | Decision rule |
|---|---|---|---|
| Phase 0 | 0 | Prior elicitation | Set priors from literature |
| Phase 1 (paper) | 20–50 | Beta-Binomial + Sequential Sharpe | STOP if P(Sharpe<0) > 0.80 |
| Phase 2 (small live) | 50–100 | Bayesian Sharpe with informative priors | Scale up if P(Sharpe>0.5) > 0.85 |
| Phase 3 (full live) | 100–200 | ROPE comparison vs. benchmark | Full allocation if 89% HDI above ROPE |
| Ongoing | 200+ | Sequential updating + regime detection | Thompson sampling for strategy rotation |

### Priority actions for Topic 8
1. **Now**: Install PyMC v5 via conda on Windows
2. **Now**: Implement Beta-Binomial win rate tracker — update after every trade
3. **Week 1**: Build Bayesian Sharpe model with informative priors from literature
4. **Week 1**: Code sequential phase gate with ADVANCE/STOP/CONTINUE rules
5. **Month 1**: Implement ROPE-based strategy comparison between pullback variants
6. **Ongoing**: Update posteriors after every trade batch; log P(Sharpe>0.5) trajectory

---

## Topic 9: Your biggest risk is your own psychology

Academic research demonstrates that cognitive biases produce **20–45% anchor-driven distortion** (Tversky & Kahneman 1974), **2× loss aversion** (Prospect Theory), and systematic overconfidence that causes active traders to underperform by **2.65 percentage points annually** (Barber & Odean 2001). For a solo operator with no external accountability, pre-commitment rules are essential.

### Backtest anchoring: expect 50% degradation

Published anomalies deliver approximately **50% of in-sample Sharpe performance out-of-sample** (Falck, Rej & Thesmar 2021, *Quantitative Finance*; consistent with McLean & Pontiff 2016). Quantopian's analysis of hundreds of algorithms found in-sample Sharpe had **correlation below 0.05** with out-of-sample results. Pre-commit now: "My backtest Sharpe is X. My live expectation is X × 0.5. If live Sharpe falls below X × 0.3 after 6 months, the strategy has no edge."

### After 20 profitable trades, you know almost nothing

A 65% win rate over 20 trades has **p-value > 0.20** — over 20% probability this is pure noise. Minimum trades for meaningful confidence: **100 trades** for basic metric reliability, **200–500 trades** spanning multiple regimes for institutional-grade confidence (López de Prado). At 2–4 trades/month, 100 trades takes **2–4 years**. The protocol: after 20 trades, change nothing; after 50, change nothing; after 100+ spanning 12+ months, cautiously evaluate.

### Broken system versus bad regime: a diagnostic framework

When performance degrades, check three categories in order: (1) **Regime issue** — are other pullback strategies also struggling? Has VIX shifted above 25? Have sector correlations increased above 0.8? If yes, reduce position size but don't change parameters. (2) **System issue** — has fill rate degraded? Slippage increased >2× average? Data feed gaps? If yes, fix infrastructure. (3) **Alpha decay** — has the edge narrowed over 6+ months despite normal regime? This requires structural research, not parameter adjustment. Maven Securities research shows alpha decay costs **5.6% annually in US markets**, with mechanical momentum strategies showing approximately **10-month lifespans** before turning negative.

### LLM automation bias is real and documented

Parasuraman & Manzey (2010, *Human Factors*) found automation bias affects **both naive and expert users** and **cannot be overcome with simple practice**. Dratsch et al. (2023) showed erroneous AI suggestions caused pathology experts to overturn correct diagnoses in **7% of cases**. For Qwen3 8B, expect **15–30%+ error rates** on specific financial facts (significantly higher than frontier models at 2–13%). Rule: trading signals come from the quantitative system only. LLM commentary has **zero decision weight** — it's for journaling and narrative context, never for signal generation.

### 15 rules to write now for your future biased self

**Position sizing**: (1) Never increase position size >25% in a single adjustment. (2) Maximum 5% of portfolio per trade ($5K initial). (3) If drawdown exceeds 15%, automatically reduce all sizes by 50%. (4) Capital allocation changes require 7-day cooling period. (5) Never add capital within 30 days of a >10% drawdown.

**Strategy modification**: (6) Minimum 90 days live before ANY parameter change. (7) Quarterly reviews only (Apr 1, Jul 1, Oct 1, Jan 1). (8) Maximum one parameter changed per quarterly review. (9) Every change requires written quantitative justification 7 days before implementation. (10) If live Sharpe < 0.3 after 6 months (minimum 50 trades), kill strategy.

**Behavioral**: (11) Never override systematic signals based on LLM commentary or gut feeling. (12) After any single-day >3% loss, 24-hour waiting period before discretionary action. (13) Monthly journal entry is mandatory. (14) Review this ruleset on the 1st of every month. (15) Share monthly performance with at least one trusted external party.

**Emergency protocol**: If drawdown reaches 15%, reduce positions 50% immediately. If drawdown reaches 25%, halt all trading for 30 days.

### Priority actions for Topic 9
1. **Now**: Write the Strategy Identity Card and all 15 rules — sign and date them
2. **Now**: Print the emergency protocol and post near workstation
3. **Now**: Set up monthly decision journal template (before/after each review)
4. **Now**: Establish external accountability — identify one person to receive monthly reports
5. **Each trade**: Update Beta-Binomial win rate tracker (no conclusions until n>100)
6. **Monthly**: Complete journal entry including temptation log and emotional state

---

## Topic 10: The basic LLM trading pipeline is fully commoditized

As of March 2026, the combination of Alpaca's MCP Server + open-source LLMs means any developer can replicate the "LLM reads news → generates signal → executes via API" pipeline **in a weekend**. Halcyon Lab's sustainable advantage must come from proprietary data/training, unique signal combinations, and a verified live track record — not from the model or infrastructure.

### The open-source landscape is exploding

**TradingAgents** (TauricResearch) leads with **43,136 GitHub stars** — a multi-agent LLM framework supporting GPT-5, Gemini, Claude, Grok, and critically, **Ollama for local deployment**. Trading-R1 (331 stars) is the most directly comparable project: a reasoning-focused LLM for trading via supervised fine-tuning + RL with 3-stage curriculum learning. FinRL (~10K+ stars) continues as the dominant reinforcement learning framework, now with FinRL-DeepSeek integration. FinGPT demonstrates LoRA fine-tuning on financial data at **$300–$416 per fine-tune** versus BloombergGPT's $2.7M.

### AI hedge fund survivors and what they prove

The hedge fund industry hit **$5.16 trillion AUM** (record, early 2026) with **562 new launches** in 2025 — the highest since 2021. Among AI-focused funds, **Numerai** stands out: $60M → **$550M AUM in 3 years**, with 25.45% net return in 2024 (2.75 Sharpe). JPMorgan committed $500M capacity. **Minotaur Capital** (Sydney) returned **27.0% FY25** with zero human analysts — their proprietary "Taurient" LLM scans 5,000+ articles/day. Failures include Sentient Technologies (liquidated 2018 after $143M raised, <$100M AUM, couldn't produce consistent returns despite massive compute) and Quantopian (shut down 2020 — backtest performance had **correlation below 0.05** with live results).

### Institutional LLMs are co-pilots, not autonomous traders

Citadel's AI Assistant scans transcripts and summarizes research as part of daily workflow, but CTO Umesh Subramanian explicitly states: "We don't want PMs offloading their human investment judgment to AI." Ken Griffin: AI is "unlikely to produce market-beating returns" autonomously. Bridgewater's CEO is more bullish, stating AI generates "unique alpha uncorrelated to what our humans do" — Pure Alpha returned ~34% in 2025. Man Group's AHL reports AI contributing **approximately half of profits** in its Dimension Programme ($5.1B). The institutional consensus: **LLMs for research acceleration, not autonomous signal generation**.

### Commoditization risk is the primary strategic threat

Alpaca's MCP Server (Model Context Protocol) enables direct trading via ChatGPT, Claude, or VS Code — any user can connect a frontier LLM to execute trades. This dramatically lowers barriers. The Eurekahedge AI Hedge Fund Index delivered **9.8% annualized** (Dec 2009–Jul 2024) versus S&P 500's 13.7% — AI funds as a category have historically underperformed passive indexing.

### Where Halcyon Lab can build a moat

**No moat exists** in the model (Qwen3 8B is open-source), infrastructure (consumer GPU), data (public sources), or execution (Alpaca API). Potential moats that must be deliberately constructed:

- **Proprietary training data and fine-tuning**: Build a curated, labeled dataset of trading decisions with reasoning chains specific to S&P 100 pullback dynamics. Fine-tune Qwen3 on data that reflects your market hypotheses.
- **Live track record**: The single most valuable asset. Numerai's path from $60M to $550M was driven by verified performance. A 2+ year auditable track record with Sharpe >1.0 is the primary currency for capital raising.
- **Unique signal ensemble**: Combine LLM reasoning with classical quant signals (RSI, order flow, earnings call tone analysis) in a proprietary way not replicated in any open-source repository.
- **Execution discipline and risk framework**: Citadel's CTO: "how you use AI will drive performance." The pre-commitment rules, phase gates, and overfitting controls documented in this compendium are themselves a competitive advantage if rigorously executed.
- **Small capital advantage**: Zero market impact means Halcyon Lab can trade signals that large funds cannot economically pursue.

### Priority actions for Topic 10
1. **Now**: Accept that the basic pipeline is commoditized — focus differentiation on proprietary data/training
2. **Month 1–6**: Build proprietary labeled dataset of S&P 100 pullback decisions with reasoning chains
3. **Month 1–24**: Build auditable live track record — this is the #1 moat
4. **Ongoing**: Monitor TradingAgents and Trading-R1 for techniques to adapt
5. **Year 1**: Evaluate fine-tuning Qwen3 on proprietary data (LoRA/QLoRA, ~$300–$416 per run)
6. **Year 2+**: Consider Minotaur-style hybrid model: LLM for idea generation, quantitative system for execution

---

## Conclusion: five things that matter most

This compendium spans 10 topics, 75+ sub-questions, and hundreds of specific recommendations. Distilling to what actually moves the needle for a solo operator on consumer hardware with $100K:

**The math says you need more data than you have.** Minimum Backtest Length calculations show that validating a Sharpe 0.8 strategy requires 4.3 years of data. Bayesian methods with informative priors are not just theoretically elegant — they're operationally necessary to make decisions with 50–200 trades. Implement sequential phase gates immediately.

**Your execution costs are negligible; your psychology costs are not.** At $10K per trade on S&P 100 mega-caps, market impact is zero and slippage is 5 bps. But anchoring to backtest results (50% expected degradation), overconfidence from early wins (p>0.20 after 20 trades), and sunk cost with failing strategies will cost far more than any bid-ask spread. The 15 pre-commitment rules are the highest-value intervention in this document.

**The infrastructure is surprisingly robust at this scale.** SQLite handles 10+ million rows with proper indexing. Windows 11 runs 24/7 with registry hardening and NSSM service management. Render costs can drop to $13/month. None of these are bottlenecks — but Ollama VRAM fragmentation requires daily restarts, and Windows Update requires active prevention.

**Fund formation is expensive and premature.** At $79K–$180K annual operating costs, a fund isn't self-sustaining until $5–10M AUM. The defense contractor employment creates additional legal complexity. Focus the next 24 months on building a live track record, resolving employment ethics questions, and accumulating personal capital — fund formation is a Year 3+ decision.

**The competitive moat must be built, not assumed.** Every component of the basic pipeline (open-source LLM, free broker API, public data) is commoditized. Halcyon Lab's sustainable advantage comes from three sources that take time to create: proprietary training data and fine-tuning, an auditable live track record, and the execution discipline to avoid the cognitive traps that destroy most algorithmic traders.