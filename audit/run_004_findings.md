# Audit Run #4 — code_quality

**Date:** 2026-04-01
**Focus:** code_quality
**Files:** 45–59 (15 files)

## Medium Findings (require GitHub issues)

### 1. backtester.py — Monolithic `backtest_model` function (160 lines)

- **File:** `src/evaluation/backtester.py`
- **Lines:** 25–185
- **Severity:** medium
- **Finding:** `backtest_model` is 160 lines and mixes data fetching, day-by-day simulation, trade tracking, and metric computation in one function. This makes it hard to test individual stages, reason about correctness, and maintain.
- **Suggested Fix:** Extract into helpers: `_fetch_backtest_data()`, `_simulate_trading_day()`, `_compute_backtest_metrics()`. Each can be unit-tested independently.

### 2. news.py — Code duplication between `fetch_recent_news` and `fetch_historical_news`

- **File:** `src/data_enrichment/news.py`
- **Lines:** 92–188 and 191–281
- **Severity:** medium
- **Finding:** Both functions (~90 lines each) replicate identical article processing, headline extraction, and sentiment classification logic. If one is updated and the other isn't, behavior will silently diverge.
- **Suggested Fix:** Extract shared logic into `_process_articles(articles, lookback_days, label)` helper. Both functions call it after their respective API fetch.

### 3. earnings_signals.py — `compute_earnings_signals` is 132 lines with 5 inline computations

- **File:** `src/data_enrichment/earnings_signals.py`
- **Lines:** 27–159
- **Severity:** medium
- **Finding:** Computes 5 distinct PEAD signals in one function with 5 separate try/except blocks. Each signal computation is independent and should be a separate helper for testability and readability.
- **Suggested Fix:** Extract `_compute_earnings_proximity()`, `_compute_last_surprise()`, `_compute_concordance()`, `_compute_revision_velocity()`, `_compute_inconsistency()`.

### 4. auditor.py — Duplicated email logic in `check_escalation` + redundant import

- **File:** `src/evaluation/auditor.py`
- **Lines:** 238–324
- **Severity:** medium
- **Finding:** The critical and alert branches both construct and send emails with nearly identical code. Also, `import sqlite3` at line 256 is redundant (already imported at module level, line 7).
- **Suggested Fix:** Extract `_send_audit_alert(subject_prefix, flag)` helper. Remove the redundant inner `import sqlite3`.

## Low Findings (no GitHub issue)

| # | File | Finding |
|---|------|---------|
| 5 | `src/data_enrichment/fundamentals.py` | Unused import `json` (line 12) |
| 6 | `src/evaluation/backtester.py` | Unused imports `json` (line 13) and `Path` (line 15) |
| 7 | `src/email/digest_builder.py` | Missing type hints on `_safe_fetchall` and `_safe_fetchone` (lines 25, 35) |
| 8 | `src/data_enrichment/enricher.py` | `enrich_features` is 123 lines (borderline; structured as sequential pipeline) |
| 9 | `src/data_enrichment/insiders.py` | `_fetch_from_finnhub` is 93 lines (borderline) |
| 10 | `src/email/digest_builder.py` | All 4 `build_*_digest` functions exceed 50 lines (50–70 each, identical pattern) |

## Files with No Findings

- `src/data_ingestion/__init__.py` (empty init)
- `src/email/__init__.py` (empty init)
- `src/evaluation/__init__.py` (empty init)
- `src/data_ingestion/market_data.py` (clean, well-structured)
- `src/data_integrity.py` (clean, focused validation)
- `src/email/notifier.py` (clean, good error handling)
- `src/data_enrichment/macro.py` (clean, well-organized)
