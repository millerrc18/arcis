# Earnings tables PIT discipline audit — closes #860

_Author: PM (rescue from terminated agent dispatch — `arcis:design-codebase-analyst` opus terminated at 60s before worktree setup)._
_Date: 2026-04-29. Closes #860. Pre-Stage-1 robustness audit per operator's "review #860 before walkforward" request._

## TL;DR

The `as_of` filter that PR #868 added to `src/data_enrichment/earnings_signals.py` (`AND collected_at <= ?`) is:

- **REAL for `analyst_estimates`** for cross-day revisions (`INSERT OR IGNORE` blocks intra-day duplicates but each calendar day is a fresh row). Operator can rely on it for the standard daily-collection cadence.
- **COSMETIC for `earnings_calendar`** because the writer is `INSERT ... ON CONFLICT(ticker, earnings_date) DO UPDATE` (an UPSERT that **overwrites `collected_at` on every re-collection**). The filter "works" structurally but the meaning is "earnings dates whose LATEST collection happened before as_of" — which is NOT what the as_of filter is supposed to express.

Plus a meta-finding: **`earnings_calendar` is currently EMPTY (0 rows)** in the production DB. Whatever was supposed to populate it isn't running, OR the table was wiped recently and not backfilled. Earnings-proximity computations against this table return None for every ticker today.

## Implications for #859 PIT plumbing (PR #868)

PR #868 adds these PIT filter clauses:
1. `WHERE earnings_date >= date(?)` (replaces `date('now')` literal) — refers to `earnings_calendar.earnings_date`. Since the table is empty, this query returns nothing regardless of as_of. **No-op until the table is repopulated.**
2. `WHERE collected_at <= ?` on `analyst_estimates` — see analysis below per metric.
3. `analyst_revision_velocity_30d` window — uses `as_of - 30d` correctly per the parameter binding, but limited to cross-day revisions because intra-day revisions don't enter the table.

## Audit methodology

Schema inspected at `src/schema/registry.py:972-1001` (`analyst_estimates`) and `src/schema/registry.py:1173-1188` (`earnings_calendar`). Writers traced via grep. Live-data sample queried from `C:/arcis/data/ai_research_desk.sqlite3` (`mode=ro` URI, no writes).

## `analyst_estimates` — schema + writer + live state

### Schema (registry.py:972-1001)

```python
TableDef(
    name="analyst_estimates",
    columns=[
        ColumnDef("id", "INTEGER", nullable=False),       # PK auto
        ColumnDef("ticker", "TEXT", nullable=False),
        ColumnDef("date", "TEXT", nullable=False),         # snapshot date (YYYY-MM-DD)
        ColumnDef("consensus_buy", "INTEGER"),
        # ... ~16 estimate fields ...
        ColumnDef("collected_at", "TEXT", nullable=False), # ISO timestamp
        ColumnDef("source", "TEXT", default="finnhub"),
    ],
    primary_key="id",
    indexes=[
        IndexDef("idx_analyst_ticker_date", ["ticker", "date"]),
        IndexDef("idx_analyst_unique", ["ticker", "date", "source"], unique=True),  # ← key
    ],
)
```

The `idx_analyst_unique` index on `(ticker, date, source)` makes intra-day duplicates impossible.

### Writer (analyst_collector.py:152)

```python
conn.execute(
    """INSERT OR IGNORE INTO analyst_estimates
    (ticker, date, consensus_buy, ..., collected_at)
    VALUES (?, ?, ?, ..., ?, 'finnhub', ?)""",
    (ticker, today_str, ..., collected_at),
)
# ... except sqlite3.IntegrityError: pass  # Duplicate — already collected today
```

`INSERT OR IGNORE` + UNIQUE(ticker, date, source) means:
- First INSERT for (TSLA, 2024-06-15, finnhub) at 09:00 → row created with collected_at=09:00
- Second INSERT for (TSLA, 2024-06-15, finnhub) at 14:00 (revision) → IGNORED, not stored
- Next-day INSERT for (TSLA, 2024-06-16, finnhub) → new row created

**PIT classification**: PARTIAL. Cross-day revisions are tracked as separate rows; intra-day revisions are dropped silently.

### Live state (read-only query)

```sql
SELECT 
    SUM(CASE WHEN n = 1 THEN 1 ELSE 0 END) AS single_row,
    SUM(CASE WHEN n > 1 THEN 1 ELSE 0 END) AS multiple_rows,
    COUNT(*) AS total_groups
FROM (SELECT ticker, date, source, COUNT(*) AS n
      FROM analyst_estimates
      GROUP BY ticker, date, source);
-- Result: single_row=20, multiple_rows=0, total_groups=20

SELECT COUNT(*), COUNT(DISTINCT collected_at) FROM analyst_estimates;
-- Result: 20 rows, 1 distinct collected_at
```

Only 20 rows total, all from a single collection cycle. Each row is its own group (no duplicates by the unique index). The `collected_at` distinctness of 1 means the table was populated in a single batch — likely a recent backfill or a single-day's collection.

### #868 filter analysis

`WHERE collected_at <= ?` on `analyst_estimates`:
- For as_of in the past relative to a row's collected_at → row excluded ✓ (correct PIT behavior)
- For as_of after a row's collected_at → row included ✓ (correct)
- For mid-day revisions of the SAME row → invisible because they were never stored ✗ (cosmetic)

For Stage 1 walk-forward (decision points are end-of-day), intra-day revisions don't matter — Stage 1 cares about "what was the consensus visible on date T at end-of-day", which is exactly what the first-of-day INSERT captures. **The filter is good enough for Stage 1.**

## `earnings_calendar` — schema + writer + live state

### Schema (registry.py:1173-1188)

```python
TableDef(
    name="earnings_calendar",
    columns=[
        ColumnDef("id", "INTEGER", nullable=False),
        ColumnDef("ticker", "TEXT", nullable=False),
        ColumnDef("earnings_date", "TEXT", nullable=False),
        ColumnDef("earnings_time", "TEXT"),
        ColumnDef("confirmed", "INTEGER", default="0"),
        ColumnDef("collected_at", "TEXT", nullable=False),
    ],
    primary_key="id",
    # NO explicit indexes — but the upsert relies on a UNIQUE on (ticker, earnings_date)
)
```

The schema doesn't define a `UNIQUE` index on `(ticker, earnings_date)`, but the writer's `ON CONFLICT(ticker, earnings_date)` clause DEPENDS on one existing. This is fragile — the upsert will silently fall back to a normal INSERT if the constraint is missing, leading to duplicate rows. **Schema gap worth fixing alongside the PIT decision.**

### Writer (scripts/fetch_earnings_calendar.py:138)

```python
conn.execute(
    """INSERT INTO earnings_calendar
    (ticker, earnings_date, earnings_time, confirmed, collected_at)
    VALUES (?, ?, ?, 0, ?)
    ON CONFLICT(ticker, earnings_date)
    DO UPDATE SET earnings_time=excluded.earnings_time,
                  collected_at=excluded.collected_at""",
    (ticker, date_str, time_str, collected_at),
)
```

UPSERT semantics:
- First INSERT for (TSLA, 2024-08-15) → row created with collected_at=2024-06-10T09:00
- Second INSERT for (TSLA, 2024-08-15) at 2024-06-12T09:00 → row UPDATED, collected_at=2024-06-12T09:00 (LOST: original 2024-06-10 timestamp)

**PIT classification**: BROKEN. Each (ticker, earnings_date) pair has at most ONE row, and `collected_at` reflects the most recent re-collection — not the FIRST time we knew about that earnings date.

### Live state

```sql
SELECT COUNT(*), COUNT(DISTINCT collected_at) FROM earnings_calendar;
-- Result: 0 rows, 0 distinct collected_at
```

**The table is empty.** Either:
- The fetcher hasn't run successfully in a while
- The table was recently wiped (e.g. during Friday bootcamp archive cycle SD#42)
- Or the writer never ran (script not on overnight schedule? failing silently?)

This is a separate operational issue but affects #859: with an empty `earnings_calendar`, the proximity computation in `compute_earnings_signals` returns `earnings_proximity_days=None` for every ticker. Section 9 of the prompt renders "Days to Next Earnings: n/a" universally.

### #868 filter analysis

`WHERE earnings_date >= date(?)` on `earnings_calendar`:
- This is the proximity-window filter (find next earnings on or after as_of)
- It uses `earnings_date`, not `collected_at` — so the upsert overwrite isn't directly relevant here
- BUT: a row whose latest collected_at is 2024-06-12 was originally seen on 2024-06-10. At as_of=2024-06-11, we want to know "did we know about this earnings date by 06-11". The current schema DOESN'T let us answer that.

For Stage 1, this means: **the earnings calendar can only tell us "was this earnings date scheduled at the time of our last fetch", not "was it scheduled at the time of the historical decision point".** If an earnings announcement was scheduled then later cancelled then later rescheduled, the audit trail is gone.

## Recommendations

### For Stage 1 robustness (operator decision)

| Option | Action | Pros | Cons |
|---|---|---|---|
| A | Accept-as-is, document in addendum-2 | Zero engineering work | Earnings calendar is a moderate signal — broken PIT here means the "Days to Next Earnings" prompt field is questionable for backtest. |
| B | Repopulate `earnings_calendar` + accept the upsert overwrite as PIT-best-effort | Simple — operator runs the fetcher | Still PIT-broken at write time, but at least there's data to filter |
| C | Migrate `earnings_calendar` to append-only (drop ON CONFLICT, add INSERT OR IGNORE on (ticker, earnings_date, earnings_time, collected_at) so revisions become new rows) | Real PIT correctness | Schema migration + writer change; existing 0 rows means low backfill cost |
| D | Drop Section 9 from corpus prompts (placeholder) | Eliminates contamination risk | LLM was trained with this section; placeholder changes inference distribution |

**PM lean: B + addendum-2 entry**. The current state (empty table) is the more urgent issue. Once data exists, Stage 1 walk-forward can use the cross-day cadence (~daily fetches) and accept the modest known limitation. Option C is a future cleanup but not blocking.

For `analyst_estimates`: **no action needed** — cross-day PIT is correct for Stage 1's end-of-day decision cadence. PR #868's filter is real here.

## Pre-reg implications

Addendum-2 must record:

1. **`earnings_calendar` is PIT-best-effort** (cross-day cadence, no intra-day revision tracking, table-empty as of 2026-04-29 audit).
2. **`analyst_estimates` is PIT-correct for cross-day** (intra-day revisions silently dropped by INSERT OR IGNORE — acceptable for Stage 1 end-of-day decision cadence).
3. **Operator must repopulate `earnings_calendar`** before running Stage 1, OR accept that Section 9 "Days to Next Earnings" renders 'n/a' on every backtest decision (mismatching the runtime distribution where the table is presumably populated).

## Strict-rigor receipts

- Both schemas inspected at `src/schema/registry.py:972-1001` (analyst_estimates) and `src/schema/registry.py:1173-1188` (earnings_calendar)
- Writers traced via grep:
  - `src/data_collection/analyst_collector.py:152` — `INSERT OR IGNORE` with `idx_analyst_unique` constraint
  - `scripts/fetch_earnings_calendar.py:138` — `INSERT ... ON CONFLICT DO UPDATE` (upsert)
- Live data sampled from `C:/arcis/data/ai_research_desk.sqlite3` via `mode=ro` URI:
  - analyst_estimates: 20 rows, 1 distinct collected_at, 0 multi-row (ticker, date, source) groups
  - earnings_calendar: 0 rows
- Cross-referenced PR #868's PR body which explicitly flagged `#860` as a dependency
- Doc-only deliverable; no code or schema changes
- PM-rescue from terminated agent: `arcis:design-codebase-analyst` opus terminated at 60s before worktree setup; PM did the audit directly

## What this audit did NOT cover

- Did not audit whether the operational issue ("earnings_calendar is empty") is a recent regression or longstanding. Operator-side: check overnight scheduler logs for `fetch_earnings_calendar` runs.
- Did not measure backtest contamination magnitude (how many decision points would flip if Section 9 became PIT-correct). Worth measuring on a small smoke window if Option C is chosen.
- Did not audit whether `analyst_estimates` revisions ARE actually being collected daily (only verified table is non-empty and writer logic is sound). Operator-side: spot-check `SELECT date, COUNT(*) FROM analyst_estimates GROUP BY date ORDER BY date DESC LIMIT 30` to see daily cadence.
