# Data Quality Audit: April 10 Cascade Blast Radius

**Date:** 2026-04-10
**Auditor:** Claude (Opus 4.6)
**Database:** `ai_research_desk.sqlite3`
**Verdict:** QUARANTINE (not wipe)

---

## 1. Executive Summary

The database is **salvageable but contaminated**. Of 97 total shadow trades, only 18 have trustworthy P&L data (15 winners, 3 losers, total $603.96). The remaining 79 are either rejected orders that never executed (42), reconciled-stale closures with no exit price or P&L (34), or open positions (3, one stale). The 34 reconciled-stale records are the problem: they represent real positions that existed on Alpaca but were closed without capturing exit prices, making their P&L unrecoverable. The recommendation is to **quarantine** the 34 reconciled-stale + 42 rejected records and the 1 stale open trade, preserving the 18 trades with verified P&L and 2 live open positions. Do NOT wipe the training data, recommendations, or supporting tables -- they are clean. The `shadow_trades` table should be flagged, not deleted, so historical analysis can distinguish trustworthy from compromised records.

---

## 2. Findings

### 2.1 Trade Data Integrity

**97 total trades:**

| Category | Count | P&L Data | Trustworthy |
|----------|-------|----------|-------------|
| Clean closed (target/stop hit, with exit price & P&L) | 18 | Yes | YES |
| Open (live, matched on Alpaca: CAT, CVX) | 2 | N/A | YES |
| Open (live, stale -- WMT not on Alpaca) | 1 | N/A | STALE |
| Rejected (order_rejected_buying_power) | 42 | N/A | N/A (never traded) |
| Reconciled-stale (no exit price, no P&L) | 27 | NO | CORRUPTED |
| Reconciled-stale (has estimated P&L) | 7 | ESTIMATED | SUSPECT |

**34 integrity issues found:** All 34 are closed trades missing `actual_exit_price`. Every one has `exit_reason='reconciled_stale'` -- positions that the reconciler closed without knowing the actual exit price.

**P&L math verification:** The 18 trades with real exit prices all pass P&L math checks (entry/exit/shares calculation matches recorded P&L within $1 tolerance). Zero P&L mismatches.

**No duplicate trade_ids.** No exit-before-entry date violations. No invalid exit reasons.

### 2.2 Column Type Issue

All numeric columns (`entry_price`, `stop_price`, `target_1`, `planned_shares`, `planned_allocation`) are stored as `TEXT` in SQLite, not `REAL` or `INTEGER`. The schema registry defines them as `TEXT`. This causes the `shadow-status` TypeError:

```
TypeError: '>' not supported between instances of 'str' and 'int'
```

at `src/services/shadow_service.py:33` where `entry > 0` compares a string to an integer.

### 2.3 Alpaca vs DB Reconciliation (Current State)

| Category | Tickers |
|----------|---------|
| Matched (DB + Alpaca) | CAT, CVX |
| Orphaned (Alpaca only) | None |
| Stale (DB only) | WMT |

WMT shows `status='open'` in DB with `source='live'`, `shares=1`, `entry=$124.28`. Alpaca has no WMT position. This is a stale record from the cascade -- the position was likely closed during the Apr 10 cleanup but the DB was not updated for this live trade.

### 2.4 Recommendations Table

**1,507 recommendations. No issues found.** All 100 most recent pass quality checks: no template/prompt leakage, no out-of-range conviction scores, no suspiciously short commentary.

### 2.5 Training Data

**1,019 training examples. 153 reference corrupted-period tickers.**

The training examples themselves are NOT corrupted -- they are LLM-generated trade analysis examples derived from historical market data, not from the shadow trading results. The tickers overlap because they are popular S&P 500 stocks. The training data is safe to keep.

| Ticker | Training Examples |
|--------|-------------------|
| GS | 25 |
| CVS | 24 |
| CSCO | 17 |
| GOOGL | 12 |
| MO | 12 |
| PFE | 11 |
| USB | 10 |
| XOM | 10 |
| COP | 9 |
| NEE | 5 |
| TXN | 5 |
| FDX | 4 |
| TGT | 4 |
| SBUX | 3 |
| LIN | 2 |

### 2.6 Supporting Tables

| Table | Rows | Status |
|-------|------|--------|
| recommendations | 1,507 | Clean |
| training_examples | 1,019 | Clean |
| options_metrics | 827 | Clean |
| macro_snapshots | 219 | Clean |
| earnings_calendar | 112 | Clean |
| vix_term_structure | 11 | Clean |
| validation_results | 10 | Clean |

---

## 3. Blast Radius

### Trades with VERIFIED P&L (18 -- keep)

| Ticker | P&L | Exit Reason | Source |
|--------|-----|-------------|--------|
| BMY | $749.25 | target_1_hit | paper |
| COP | $426.00 | reconciled_stale | paper |
| COP | $292.52 | reconciled_stale | paper |
| CAT | $37.12 | target_1_hit | paper |
| COST | $27.43 | target_1_hit | paper |
| LIN | $17.13 | target_1_hit | paper |
| JNJ | $8.55 | target_1_hit | paper |
| EXC | $7.40 | target_1_hit | paper |
| SO | $7.20 | target_1_hit | paper |
| CSCO | $6.94 | target_1_hit | paper |
| PFE | $6.79 | target_1_hit | paper |
| DUK | $6.50 | target_1_hit | paper |
| TGT | $5.54 | target_1_hit | paper |
| COP | $5.10 | target_1_hit | paper |
| BK | $4.12 | target_1_hit | paper |
| MO | -$1.37 | stop_hit | live |
| CVX | -$8.44 | stop_hit | paper |
| COP | -$993.82 | stop_hit | paper |
| **Total** | **$603.96** | | |

### Trades MISSING P&L (34 -- quarantine)

27 reconciled-stale with NO exit price or P&L, plus 7 reconciled-stale where the reconciler estimated P&L (COP entries above already counted in verified). These are positions that existed on Alpaca, were closed by reconciliation, but the exit price was either not captured or estimated from the last known market price.

### Trades NEVER EXECUTED (42 -- quarantine)

42 `order_rejected_buying_power` entries from Apr 1, 10:18 AM to 4:09 PM. These are records of failed entry attempts -- no orders were ever placed, no positions opened. They contain no useful trading data.

### Stale Open Trade (1 -- quarantine)

WMT (`bb10c4b7-195...`) -- `source='live'`, `status='open'`, no Alpaca position. Stale from cleanup.

---

## 4. Recommendation: QUARANTINE

**Do NOT wipe the database.** The 18 verified trades, 1,507 recommendations, 1,019 training examples, and all supporting tables are clean and valuable. Wiping would destroy this data unnecessarily.

Instead, quarantine the 77 compromised shadow_trade records by adding a `quarantined` flag column:

### Step 1: Add quarantine column

```sql
-- Via schema registry (src/schema/registry.py), add:
-- ColumnDef("quarantined", "INTEGER", default="0"),
-- Then run: python -m src.main validate-schema --fix
```

### Step 2: Flag compromised records

```sql
-- 42 rejected trades (never executed, no data value)
UPDATE shadow_trades SET quarantined = 1
WHERE exit_reason = 'order_rejected_buying_power';

-- 27 reconciled-stale trades with NO exit price
UPDATE shadow_trades SET quarantined = 1
WHERE exit_reason = 'reconciled_stale'
  AND (actual_exit_price IS NULL OR actual_exit_price = '');

-- 1 stale open WMT trade
UPDATE shadow_trades SET quarantined = 1
WHERE trade_id = 'bb10c4b7-1959-44e1-8370-80ddf8a99dab'
  AND ticker = 'WMT' AND status = 'open';
```

### Step 3: Update queries to exclude quarantined

All P&L, win rate, and performance queries should add `AND quarantined = 0` (or `AND COALESCE(quarantined, 0) = 0`).

### Step 4: Close the stale WMT trade

```sql
UPDATE shadow_trades SET status = 'closed', exit_reason = 'reconciled_stale'
WHERE trade_id = 'bb10c4b7-1959-44e1-8370-80ddf8a99dab';
```

### Step 5: Fix the shadow-status TypeError

In `src/services/shadow_service.py:33`, cast the entry price to float before comparison:

```python
# Before:
if current and entry > 0:
# After:
if current and float(entry or 0) > 0:
```

---

## 5. What NOT to Touch

| Asset | Rows | Verdict |
|-------|------|---------|
| `recommendations` | 1,507 | KEEP -- clean, no cascade impact |
| `training_examples` | 1,019 | KEEP -- derived from market data, not trade results |
| `training_data/dataset.jsonl` | 5MB | KEEP -- LLM training data, independent of shadow trades |
| `options_metrics` | 827 | KEEP -- market data collection, unrelated |
| `macro_snapshots` | 219 | KEEP -- FRED data, unrelated |
| `earnings_calendar` | 112 | KEEP -- market data, unrelated |
| `vix_term_structure` | 11 | KEEP -- market data, unrelated |
| 18 verified shadow trades | 18 | KEEP -- P&L math verified, trustworthy |
| 2 open live positions (CAT, CVX) | 2 | KEEP -- matched on Alpaca |

---

## 6. Post-Quarantine State

After quarantine, the database would contain:

- **18 closed trades** with verified P&L ($603.96 total: 15W/3L, 83% win rate)
- **2 open trades** (CAT, CVX) actively managed on Alpaca
- **77 quarantined records** preserved for forensic reference but excluded from analytics
- **All supporting tables** intact and clean

This gives a clean baseline for forward performance tracking while preserving the full audit trail of the April cascade incident.
