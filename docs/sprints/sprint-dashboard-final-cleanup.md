# Sprint DB-FINAL: Unfinished Work Cleanup

**Date:** April 12, 2026
**Scope:** 7 tasks carried forward from DB-1 through DB-3
**Branch:** `fix/dashboard-final-cleanup`

---

## Implementation Plan

### Task 1: time_to_mfe logging (DB-1 Task 9 — carried forward)

**Schema** — add 2 columns to shadow_trades in `src/schema/registry.py`:
```python
ColumnDef("time_to_mfe_days", "INTEGER",
          description="Days from entry to maximum favorable excursion peak. "
          "Updated each monitoring cycle when MFE increases."),
ColumnDef("mfe_timestamp", "TEXT",
          description="ISO timestamp when MFE last increased (peak P&L moment)."),
```

**Executor** — modify `check_and_manage_open_trades()` in `src/shadow_trading/executor.py` around line 932. When MFE increases (new high), record day count and timestamp:
```python
# Existing:
if price_move > mfe:
    mfe = price_move
# Add:
    mfe_days = days_open
    mfe_ts = now.isoformat()
else:
    mfe_days = trade.get("time_to_mfe_days")
    mfe_ts = trade.get("mfe_timestamp")
```

Then in the update dict (~line 951), add `"time_to_mfe_days": mfe_days, "mfe_timestamp": mfe_ts`.

**Close** — in `src/journal/store.py` close_shadow_trade, set final time_to_mfe_days (already available from last update — no change needed unless the field is wiped on close).

**Test** — 3 cases: MFE increases → days and timestamp update; MFE stays flat → values unchanged; trade closes → final values preserved.

### Task 2: Attribution logger fix (DB-2a Task 6 — carried forward)

**Diagnosis:** Attribution hooks exist in `src/scheduler/universe_scanner.py` (lines 169-223). Phase 1 (`log_attribution_before_llm`) fires before LLM, Phase 2 (`log_attribution_after_llm`) fires after. Both are wrapped in `try/except` with `logger.debug` — failures are invisible.

**Fix 1:** Change all attribution `logger.debug` to `logger.warning` in universe_scanner.py so failures are visible in logs.

**Fix 2:** Check `_parse_price` compatibility. The function is imported from executor.py and may fail on the entry_zone format (which could be "150.00 area" not just "150.00"). Test with actual packet data.

**Fix 3:** Verify the attribution_trades table syncs to Postgres (check sync_to_postgres flag in registry). If not synced, the dashboard will show 0 pairs even if local has data.

**Fix 4:** Add a simple integration test: mock a scan cycle, verify both Phase 1 and Phase 2 fire, verify a row exists in attribution_trades with both ranker and LLM fields populated.

### Task 3: Mobile responsive — sidebar collapse

**File:** `frontend/src/components/Layout.jsx`

Add responsive sidebar: on viewports < 768px, collapse the sidebar. Show a hamburger icon (Menu from lucide-react — already imported) in the header. Tap opens sidebar as an overlay with a semi-transparent backdrop. Tap backdrop or X closes it.

```jsx
const [sidebarOpen, setSidebarOpen] = useState(false)
// In header: 
<button className="md:hidden" onClick={() => setSidebarOpen(!sidebarOpen)}>
  {sidebarOpen ? <X size={20} /> : <Menu size={20} />}
</button>
// Sidebar wrapper:
<aside className={`fixed inset-y-0 left-0 z-40 w-64 transform transition-transform 
  md:relative md:translate-x-0 ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'}`}>
```

### Task 4: Mobile responsive — content layout

**Cross-cutting CSS in Layout.jsx and individual pages:**

- Main content: change `<main className="flex-1 overflow-y-auto p-4">` to `p-3 md:p-6`
- MetricCard grids: use `grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-3 md:gap-4`
- Tables: wrap all `<table>` elements in `<div className="overflow-x-auto">` with `-webkit-overflow-scrolling: touch`
- Charts: ensure all ResponsiveContainer uses `width="100%"` (most already do)
- Touch targets: ensure all buttons/links have `min-h-[44px]` on mobile

### Task 5: Whitespace optimization

**Layout.jsx:** Increase main padding from `p-4` to `p-4 md:p-6 lg:p-8`

**Cross-cutting on all card-based pages:** Change `space-y-4` to `space-y-4 md:space-y-6` between sections. Card padding: `p-4 md:p-6`.

**Content width:** The main area is `flex-1` which already fills available space. The sidebar is fixed-width. No max-w constraint to change — the content already fills the viewport minus sidebar. The issue is individual card padding being too tight, not container width.

### Task 6: Architecture + DB Schema — disable drag, fix canvas

**Architecture.jsx:** Add `nodesDraggable={false}` and `nodesConnectable={false}` to the ReactFlow component. Nodes already have fixed positions via `initialNodes`. This makes the layout deterministic on load. Keep zoom/pan for exploration.

**DBSchema.jsx:** Same treatment — `nodesDraggable={false}`, `nodesConnectable={false}`.

**Canvas artifact fix:** The corrupted graphic in bottom-right is likely the ReactFlow MiniMap or a background pattern rendering issue. If the glitch persists after disabling drag, remove the `<MiniMap>` component from both pages and test.

### Task 7: Page consolidation prep

Add `data-testid` attributes to key components on Health.jsx, Validation.jsx, and Monitoring.jsx. These three pages will merge into "System Health" in a future sprint. Example:
```jsx
<div data-testid="health-hshs-radar">...</div>
<div data-testid="validation-category-config">...</div>
<div data-testid="monitoring-resource-chart">...</div>
```

---

## Ralph Loop Findings

### Pass 1:
Task 3 (sidebar collapse) needs careful z-index management. The sidebar overlay must be above the main content but below any modals. Use `z-40` for sidebar, `z-30` for backdrop. Also: the sidebar currently renders the status badges (LLM CLOUD, Shadow CLOUD) at the bottom — these need to stay visible when collapsed, possibly moving to the header bar on mobile.

### Pass 2:
Task 2 (attribution) — checking the hooks alone may not be enough. The `_parse_price` function in executor.py parses strings like "$150.00 area" or "150.00 - 152.00". If it returns 0 or throws, the attribution row will have `ranker_only_entry = 0.0` which makes the ranker-only simulation meaningless. The fix should include a defensive check: if any of entry/stop/target parse to 0 or None, skip attribution logging entirely rather than writing corrupt data. Also verify `attribution_trades` has `sync_to_postgres=True` in the registry — if False, the cloud dashboard will never see the pairs.

### Pass 3:
Task 4 (mobile content layout) is underspecified for tables. The Shadow Ledger, Live Ledger, Logs, Stress Test, and Model Performance pages all have wide tables that will overflow on 375px viewports. The `overflow-x-auto` wrapper is necessary but not sufficient — the first column (ticker) should be sticky (`sticky left-0 z-10 bg-inherit`) so the user always knows which row they're looking at while scrolling horizontally. This is a 2-line CSS addition per table but applies to ~6 pages.
