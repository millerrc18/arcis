# B9 — Dashboard timeout visibility (Live + Shadow ledger) (Pass 1 design)

> **Operator addition (2026-04-25):** Added during Pass 1 review immediately after B8 was scoped. The LLM-set timeout from B8 is operationally meaningless if the operator can't see it — they need to compare a trade's holding window against the LLM's expected window in real time, not just at post-mortem. Both Live Ledger and Shadow Ledger pages must surface this.

## Pass 1 finding — current dashboard state

Two ledger pages display ongoing/closed trades:

- `frontend/src/pages/LiveLedger.jsx` — live (real-money) trades from Alpaca + IB
- `frontend/src/pages/ShadowLedger.jsx` — shadow (paper) trades from the bootcamp pipeline
- `frontend/src/pages/TradeHistory.jsx` — closed-trade history with the excess-Sharpe lead panel (added v0.19.0)

Backend routes feeding these pages:

- `src/api/cloud_routes/trades.py` — cloud API consumed by halcyonlab.app
- `src/api/routes/shadow.py` and similar local-API routes (consumed by `python -m src.main dashboard`)

Pass 2 will need to confirm exact local-API route paths during implementation; cloud route is the canonical surface.

**Today neither ledger surfaces:**

- `timeout_days` (the operative timeout — currently NULL on most rows pre-B8)
- `llm_timeout_days` (B8's new field)
- `duration_days` (held-time, exists on shadow_trades and is populated)

The operator currently has no way to answer "is this trade close to its expected timeout?" without dropping into the SQLite shell.

## Implementation plan (Pass 2)

### 1. Backend — extend API response shape

**Cloud API (`src/api/cloud_routes/trades.py`):**

Add fields to the trade-row response:

```python
{
  ...existing fields...,
  "duration_days": int | None,             # held time so far (or final)
  "timeout_days": int,                     # operative timeout (LLM-set OR default)
  "llm_timeout_days": int | None,          # what the LLM said (NULL pre-B8 or invalid)
  "timeout_progress_pct": float,           # duration_days / timeout_days × 100; capped at 999 if duration exceeds
  "timeout_status": str,                   # "on_track" | "approaching" | "overdue" | "unknown"
}
```

`timeout_status` thresholds (operator-tunable later if needed):

- `< 50%` → `on_track`
- `50–80%` → `on_track`
- `80–100%` → `approaching` (yellow on dashboard)
- `> 100%` → `overdue` (red)
- `timeout_days IS NULL` → `unknown` (gray)

**Local API (`src/api/routes/shadow.py` and the live equivalent):**

Mirror the cloud shape. Per CLAUDE.md "Local API binds to 127.0.0.1 only — not exposed to network" — same response, same fields, ensures `python -m src.main dashboard` shows the same data as cloud.

### 2. Service-layer helpers

A pure-function helper, e.g., `src/services/shadow_service.py:_compute_timeout_status(duration_days, timeout_days)`, returns the dict slice. Both routes call it. Keeps the threshold logic in one place.

```python
def _compute_timeout_status(duration_days: int | None, timeout_days: int | None) -> dict:
    if timeout_days is None or duration_days is None:
        return {"timeout_progress_pct": None, "timeout_status": "unknown"}
    pct = round(100.0 * duration_days / timeout_days, 1)
    if pct >= 100: status = "overdue"
    elif pct >= 80: status = "approaching"
    else: status = "on_track"
    return {"timeout_progress_pct": min(pct, 999.0), "timeout_status": status}
```

Each function ≤ 60 lines (CI guardrail).

### 3. Frontend — Live Ledger

**File:** `frontend/src/pages/LiveLedger.jsx`

Add a "Timeout" column to the trades table:

```jsx
<TimeoutCell
  durationDays={trade.duration_days}
  timeoutDays={trade.timeout_days}
  llmTimeoutDays={trade.llm_timeout_days}
  status={trade.timeout_status}
  progressPct={trade.timeout_progress_pct}
/>
```

`TimeoutCell` (NEW component at `frontend/src/components/TimeoutCell.jsx`) renders:

```
[ 5 / 15 days ]  ← progress text (held / expected)
[████░░░░░░░]   ← visual bar, color by status
LLM: 15          ← small caption: what the LLM said (or "default" if NULL)
```

Color treatment:

- `on_track`: green text, green bar
- `approaching`: amber text, amber bar
- `overdue`: red text, red bar with subtle pulse animation
- `unknown`: gray text, gray bar

If `llm_timeout_days != timeout_days` (LLM was rejected → fell back to default), show a small ⚠ icon with tooltip: "LLM proposed N days; out of bounds; using default 15."

### 4. Frontend — Shadow Ledger

**File:** `frontend/src/pages/ShadowLedger.jsx`

Same `TimeoutCell` component, dropped into the same column position. Shadow ledger already has more columns than live (it shows scan-context fields), so the timeout column should sit next to `entry_time` for visual proximity.

Operator preference TBD: do you want the timeout column always-visible, or behind a column-picker toggle? Pass 2 default: always visible. Pass 2 can add a hide/show toggle if the table feels crowded.

### 5. Frontend — Trade History

**File:** `frontend/src/pages/TradeHistory.jsx`

For *closed* trades, the timeout column shows the final `duration_days / timeout_days` ratio (always 100% capped or above for `exit_reason=timeout` trades; below for `target_1`/`target_2`/`stop_loss` exits).

Useful for retrospective: "Did this winning trade have time to run, or did it hit timeout right before its target?"

### 6. Tests

**Backend (`tests/api/test_trades_route_timeout.py` NEW):**

| Case | Expected response |
|---|---|
| Trade with `duration=5, timeout=15` | `progress_pct=33.3, status=on_track` |
| Trade with `duration=14, timeout=15` | `progress_pct=93.3, status=approaching` |
| Trade with `duration=20, timeout=15` | `progress_pct=133.3, status=overdue` |
| Trade with `timeout_days=NULL` | `progress_pct=None, status=unknown` |
| Trade with `llm_timeout_days != timeout_days` (LLM rejected) | Both fields exposed in response |

**Frontend (`frontend/src/components/TimeoutCell.test.jsx` NEW — Vitest):**

Snapshot tests for each `status` value + the LLM-mismatch warning icon. Component is pure-render, easy to test.

## Scope fence verification

Pass 2 files:

| File | Type |
|---|---|
| `src/api/cloud_routes/trades.py` | Modified (add fields) |
| `src/api/routes/shadow.py` | Modified (mirror) |
| `src/api/routes/live.py` (if separate from shadow.py — confirm in Pass 2) | Modified |
| `src/services/shadow_service.py` | Add `_compute_timeout_status` helper |
| `frontend/src/pages/LiveLedger.jsx` | Modified |
| `frontend/src/pages/ShadowLedger.jsx` | Modified |
| `frontend/src/pages/TradeHistory.jsx` | Modified |
| `frontend/src/components/TimeoutCell.jsx` | NEW |
| `tests/api/test_trades_route_timeout.py` | NEW |
| `frontend/src/components/TimeoutCell.test.jsx` | NEW |

Total: 6-8 backend files + 4 frontend files. Sprint scope rule says ESCALATE if >2 files outside listed scope — B9 is operator-added so the scope is operator-authorized. Documented for traceability.

**Key dependency:** B9 cannot ship until B8's columns exist in the runtime DB. Pass 2 ordering:

1. B8 lands the schema columns (`llm_timeout_days`) + writer
2. B9 surfaces them via API + frontend

If B9 ships before B8, the `llm_timeout_days` field in the API response will always be NULL — degrades gracefully (UX shows "default" caption) but is wasteful.

## Coordination notes

- **B5** (instrumentation_version) — B9 might also surface `instrumentation_version` as a small badge on each trade row ("v3" = full instrumentation, anything less = caveat the data). Out of scope for this task; could be a B9-followup if useful.
- **A2 / B2.C** (CVS qty mismatch) — B9 doesn't address it directly, but the timeout-overdue status will visually flag stuck trades like the CVS one (held >15 days with no exit) without requiring SQL.

## Risks / unknowns

1. **Mobile responsive behavior** — LiveLedger and ShadowLedger have mobile-responsive sidebars (per MASTER.md). The new timeout column adds horizontal real estate. Pass 2 must verify the column collapses gracefully on narrow viewports (likely as a tooltip on the row's existing primary cell).

2. **Render cloud sync** — `src/sync/render_sync.py` syncs SQLite to Postgres. Adding `llm_timeout_days` to the recommendations + shadow_trades tables means a Postgres schema change too (per CLAUDE.md "After local schema changes: Run `render_migrate.py` to sync Postgres"). B8 already triggers this; B9 inherits.

3. **TanStack Query cache invalidation** — the ledger pages use TanStack Query (per MASTER.md frontend stack). Adding fields to the response shape is backward-compatible (existing queries ignore new fields), but if a query has `select` transforms, those need updating. Pass 2 verification.

4. **TradeHistory timeout column for non-timeout exits** — shows progress_pct even for trades that exited via target/stop. The 33.3% timeout progress on a winning target_1 exit is actually *positive* signal ("the trade hit target with plenty of time to spare") — we should display it as such, maybe with a subtle "✓ ahead of schedule" indicator. Pass 2 UX call.

## Pass 2 commit message template

```
feat(dashboard): surface LLM-set timeout in live + shadow ledgers (Track 1.5 / B9)

Adds duration_days, timeout_days, llm_timeout_days, timeout_progress_pct,
timeout_status to trades API response. Frontend TimeoutCell component
renders held/expected ratio with color treatment by status (on_track /
approaching / overdue / unknown).

Surfaces B8's per-trade timeout to the operator without requiring
SQL access. Closes Track 1.5 / B9 (operator-added task).

Depends on B8 (schema columns must exist).
```
