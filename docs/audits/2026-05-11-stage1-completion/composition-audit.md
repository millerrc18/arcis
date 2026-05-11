# Stage 1 Corpus Composition Audit

- **Corpus ID:** `stage1-001`
- **Code SHA:** `56fd7fb7e5f34279810e49eaed2c16d46f202882`
- **Generated at:** 2026-05-11T06:18:12+00:00
- **Walk-forward window:** 2023-09-01 → 2026-04-28

## 1. Entry count vs target

- Actual: **67,528**
- Aspirational target: **67,681**
- Delta: **-153** (~0.2% of target)

Manifest `coverage_limit_hits` (decision points skipped, per gate):
  - `fundamentals_no_cik`: 669
  - `fundamentals_no_data`: 261
  - `insiders_fetch_failed`: 39
  - `macro_series_unavailable`: 504
  - `news_coverage_gap`: 2
  - `news_fetch_failed`: 54
  - **total skips:** 1,529

## 2. llm_action distribution

| Action | Count | Share |
|---|---|---|
| `taken` | 67,319 | 99.7% |
| `parse_failed` | 124 | 0.2% |
| `conviction_none` | 85 | 0.1% |

> Note: this corpus stores **pre-trade LLM decisions**, not realized outcomes. The sprint spec's WIN/LOSS/TIMEOUT/PASS taxonomy refers to *outcomes* attached during shadow-trade evaluation (downstream of Stage 1). Here we audit only the `llm_action` field.

- `parse_failed` count: **124** (manifest: 124, rate: 0.184%)

### Conviction histogram (1-10 scale)

| Conviction | Count | Share |
|---|---|---|
| 1 | 3 | 0.0% |
| 2 | 25 | 0.0% |
| 3 | 203 | 0.3% |
| 4 | 1,877 | 2.8% |
| 5 | 4,629 | 6.9% |
| 6 | 11,532 | 17.1% |
| 7 | 34,089 | 50.5% |
| 8 | 13,777 | 20.4% |
| 9 | 1,387 | 2.1% |
| 10 | 6 | 0.0% |

## 3. Response length distribution (characters)

- min: **321**
- p10: **2,094**
- median: **2,548**
- mean: **2,599**
- p90: **3,175**
- max: **6,957**

10-bin histogram:

| Bin (chars) | Count | Share |
|---|---|---|
| 321 – 984 | 186 | 0.3% |
| 984 – 1,648 | 749 | 1.1% |
| 1,648 – 2,311 | 16,597 | 24.6% |
| 2,311 – 2,975 | 38,151 | 56.5% |
| 2,975 – 3,639 | 9,978 | 14.8% |
| 3,639 – 4,302 | 1,455 | 2.2% |
| 4,302 – 4,966 | 294 | 0.4% |
| 4,966 – 5,629 | 86 | 0.1% |
| 5,629 – 6,293 | 22 | 0.0% |
| 6,293 – 6,957 | 10 | 0.0% |

### Template-fallback heuristic

Bucket counts (template_fallback signal: short cluster around 750-800 chars vs real LLM around 2400-3000):

- `<1000 chars`: **186** (0.3%)
- `1000-2000 chars`: **3,872** (5.7%)
- `>=2000 chars`: **63,470** (94.0%)
- `parse_failed` length median: **823** chars (n=124)

> Distribution is **unimodal** at the long mode. No template-fallback signal detected. The small short-tail aligns with `parse_failed` entries.

## 4. Per-ticker entry counts

- Unique tickers: **103**
- Max per-ticker: **670**
- Min per-ticker: **203**
- Median per-ticker: **670**

Top 10 tickers by entry count:

| Ticker | Count |
|---|---|
| AAPL | 670 |
| ABBV | 670 |
| ABT | 670 |
| ACN | 670 |
| ADBE | 670 |
| AMAT | 670 |
| AMD | 670 |
| AMGN | 670 |
| AMT | 670 |
| AMZN | 670 |

Bottom 10 tickers by entry count:

| Ticker | Count |
|---|---|
| KHC | 203 |
| PLTR | 279 |
| GEV | 327 |
| EXC | 391 |
| BRK.B | 669 |
| ISRG | 669 |
| AAPL | 670 |
| ABBV | 670 |
| ABT | 670 |
| ACN | 670 |

### Per-ticker-per-week rate

- Max per-(ticker, ISO-week): **6**
- Ticker-weeks exceeding the ≤3 cap: **13,909** of 14,111 (98.6%)

> Stage 1 generates **daily** decision points across ~103 tickers, so 5-6 entries per ticker per week is expected (one entry per trading day). The ≤3 cap referenced in the sprint spec applies to a downstream sampling stage, not raw corpus emission. Flagging informationally only.

## 5. Date coverage

- Unique trading dates: **665**
- Date range: **2023-09-01 → 2026-04-28**
- Unique ISO weeks observed: **140**

- ISO weeks in range with **zero** entries: **0**

Per-week entry-count distribution (across observed weeks):

- min: 101
- median: 505
- p10: 404
- p90: 505
- max: 606

## 6. model_version distribution

| Version | Count | Share |
|---|---|---|
| `arcis:v1.0.0` | 67,528 | 100.0% |

> Single model_version present — no real-LLM vs template_fallback split detectable via this field. Bimodality check (§3) is the fallback signal.

## 7. Verdict preview (consumed by A3 cold-read)

- Length distribution is **unimodal at long mode** (median 2548 chars); no template_fallback signal beyond the 124 parse_failed entries.
- Entry count 67,528 falls 153 short of the aspirational 67,681; attributable to 1,529 coverage-gate skips in the manifest.
- 0 week(s) have zero entries in the 2023-09-01 → 2026-04-28 window.
