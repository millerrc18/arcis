# Sprint 5: Dashboard Polish & UX (Claude Code)

> **Executor:** Claude Code
> **Scope:** 9 tasks
> **Prerequisite:** Sprint 4E MERGED. System is in autonomous lockdown — this sprint is UI-only, no backend logic changes.
> **Read first:** AGENTS.md, docs/conventions.md
> **Context:** First hands-on dashboard review found 9 UX issues. None affect trading — all are visual/interaction polish. The dashboard is the primary interface for monitoring the system from a phone during lockdown.
> **Test baseline:** 1,110 tests. Must not decrease.

---

## Design System Reference

All pages must use the Arcis design system. Verify before starting:
- CSS vars: `grep "arcis-" frontend/src/index.css | head -20`
- Financial data class: `className="financial-data"` (JetBrains Mono, tabular-nums)
- P&L always includes ▲/▼ arrows alongside color (colorblind accessible)
- Mobile-first: single column, no horizontal scroll on iPhone
- Dark mode is default. All pages must work in both dark and light mode.

---

## Pre-Sprint Checks (MANDATORY)

```bash
find src -name "*.py" ! -path "*__pycache__*" -exec sh -c 'lines=$(wc -l < "$1"); if [ "$lines" -gt 400 ]; then echo "VIOLATION: $1 ($lines lines)"; fi' _ {} \;
python3 -c "
import ast, pathlib
for p in pathlib.Path('src').rglob('*.py'):
    try:
        tree = ast.parse(p.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                length = node.end_lineno - node.lineno
                if length > 60: print(f'VIOLATION: {p}:{node.name} ({length} lines)')
    except: pass
"
find tests -name "test_*.py" -exec grep -c "def test_" {} + | awk -F: '{s+=$2}END{print "Tests:", s}'
# Must be ≥ 1110
cd frontend && npm run build && cd ..
```

---

## Task 1: Shadow Ledger + Live Trades — Better Table Layout

**Pages:** `frontend/src/pages/ShadowLedger.jsx` (and `LiveLedger.jsx` if it exists)

**Problem:** Tables have too much whitespace. Columns don't use available screen width effectively.

**Fix:**
1. Make the table `width: 100%` with `table-layout: auto`
2. Give important columns more room: Ticker, P&L, Entry Price, Current Price, Days Held
3. Compact less-important columns: Strategy badge (pill, no label), IS bps (just the number)
4. Add alternating row shading for readability: `var(--arcis-bg-elevated)` on even rows
5. On mobile (<768px): hide IS bps and strategy columns, show only Ticker / P&L / Days
6. Sort by P&L% descending by default (best performers at top)
7. Add a summary row at the top: total positions, total unrealized P&L, avg days held
8. Financial numbers in `className="financial-data"` with ▲/▼ arrows on P&L

---

## Task 2: Fix Validation Page — Wire "Run Validation" Button

**Page:** `frontend/src/pages/Validation.jsx` (or `SystemValidation.jsx`)

**Problem:** "Run Validation" button does nothing when clicked.

**Fix:**
1. Find the validation button's onClick handler
2. It should call `POST /api/commands/submit` with `{"command_type": "action", "command_name": "validate-system"}`
3. After submission, poll `GET /api/commands/{id}/status` every 3 seconds until complete
4. Display the validation results when they come back
5. Show a loading spinner while waiting
6. If the command queue is not responding (e.g., watch loop not running), show a clear error: "Watch loop offline — validation requires the local system to be running"

**Note:** The `validate-system` command may not be in the executor's command list yet. Check `src/commands/executor.py` — if it's missing, add it:
```python
"validate-system": lambda payload, db_path, config: _run_validation(db_path, config),
```
Where `_run_validation` calls `run_full_validation()` from `src/evaluation/system_validator.py`.

---

## Task 3: Training Page Improvements

**Page:** `frontend/src/pages/Training.jsx`

**Fix:**
1. **Hero section:** Total examples (large number), examples this week, avg quality score (or "Not scored" if 0)
2. **Outcome distribution chart:** Horizontal stacked bar showing WIN/LOSS/TIMEOUT/PASS percentages. Use `var(--arcis-success)` for WIN, `var(--arcis-danger)` for LOSS, `var(--arcis-warning)` for TIMEOUT, `var(--arcis-text-muted)` for PASS
3. **Source breakdown:** Simple bar chart or list — historical_backfill, blinded_win, blinded_loss, synthetic_claude
4. **Ticker coverage:** "20/100 tickers covered" with a progress bar
5. **Regime coverage:** Show which regimes have examples and which are gaps
6. **Recent examples table:** Last 10 examples with ticker, source, outcome_type, quality_score, created_at
7. **Target vs actual:** Show v2 spec targets (40% WIN, 25% LOSS, 5% TIMEOUT, 15% PASS) alongside actual distribution
8. If `outcome_type` column doesn't exist in the API response, handle gracefully — show "Outcome data pending migration"

---

## Task 4: CTO Report Page — Handle Sparse Data Gracefully

**Page:** `frontend/src/pages/CTOReport.jsx`

**Problem:** Fund metrics show N/A, no trend lines, confidence calibration is 0, rubric score N/A. All caused by only 5 closed trades — not a bug, but the page should communicate this clearly.

**Fix:**
1. **Add minimum-data notices:** When metrics can't be computed, show "Requires N+ closed trades" instead of N/A or 0. Specific thresholds: Sortino/Calmar/beta/alpha need ≥20 trades. Confidence calibration needs trades with conviction scores recorded.
2. **Trend lines:** If fewer than 3 data points, show "Collecting data..." with a subtle animation or progress indicator instead of an empty chart
3. **Phase progress bar:** Add a prominent bar showing "5/50 trades toward Phase 1 gate" at the top of the report
4. **Rubric score:** Show "Quality scoring not yet applied" instead of "N/A" when scored count is 0
5. **Conditional rendering:** Only show metric sections that have meaningful data. Don't show empty charts with zero lines.
6. **Win rate callout:** When win rate is 100% on <10 trades, add a subtle note: "Early results — need 50+ trades for statistical significance"

---

## Task 5: Docs Page — Fix Mobile Navigation + Redesign Layout

**Page:** `frontend/src/pages/Docs.jsx` (or `Research.jsx`)

**Problem:** On iPhone, can't go back to document list after opening a document. Layout feels clunky.

**Fix:**
1. **Mobile back button:** Add a prominent "← Back to documents" button at the top when viewing a document on mobile. Must be always visible (sticky or at the very top).
2. **Redesign layout:**
   - **Desktop:** Two-column: document list on left (sidebar, scrollable, 300px wide), document viewer on right
   - **Mobile:** Single column with list → detail navigation (tap document → shows document → back button returns to list)
3. **Document list:**
   - Group by category (research, decisions, sprints) or just show alphabetically
   - Show document title + date + word count preview
   - Search/filter bar at top
   - Currently selected document highlighted
4. **Document viewer:**
   - Render markdown content properly
   - Code blocks with syntax highlighting
   - Comfortable reading width (max 720px, centered)
5. **Use React state** for navigation, not separate routes (keeps it snappy)

---

## Task 6: Notes Page — Polish

**Page:** `frontend/src/pages/Notes.jsx`

**Problem:** Functional but feels like room to improve.

**Fix:**
1. **Better typography:** Notes content in a comfortable reading font/size. Date stamps in `var(--arcis-text-muted)`.
2. **Categories/tags:** If notes have categories, show filter pills at the top
3. **Expand/collapse:** Long notes should truncate to 3 lines with "Show more" toggle
4. **Create note UX:** The input area should feel like a clean text editor, not a form field. Larger textarea, subtle border, placeholder "Add a note..."
5. **Delete confirmation:** If there's a delete button, add a confirmation dialog
6. **Empty state:** When no notes exist, show "No notes yet — add your first note above" with a subtle illustration or icon
7. **Reverse chronological:** Most recent notes at top

---

## Task 7: Logs Page — Clickable Entries + Command History

**Page:** `frontend/src/pages/Logs.jsx`

**Problem:** Can't click into log entries. No commands showing in command history.

**Fix:**
1. **Expandable log entries:** Click a log row to expand and show `details_json` content in a formatted view (JSON pretty-printed in a code block)
2. **Command history section:** Separate section (or tab) showing recent commands from `GET /api/commands/recent`. Each command shows: type, name, status (pending/completed/failed), submitted time, execution time, result preview
3. **Auto-refresh:** Logs auto-refresh every 30 seconds. Commands auto-refresh every 10 seconds (faster because users are waiting for command results)
4. **Color coding:** ERROR = `var(--arcis-danger)`, WARNING = `var(--arcis-warning)`, INFO = `var(--arcis-text-secondary)`, CRITICAL = bold red background
5. **Command submission:** Small "Run command" dropdown at the top with common commands (scan, council, collect-data). Clicking submits via `POST /api/commands/submit` and adds to the command list with "pending" status
6. **Empty state:** If no logs/commands, show "System logs will appear here once the watch loop starts recording" — not just a blank page

---

## Task 8: Settings Page — Palette H Styling

**Page:** `frontend/src/pages/Settings.jsx`

**Problem:** Looks vanilla/unstyled compared to other pages.

**Fix:**
1. **Apply Palette H consistently:** All inputs, toggles, dropdowns should use `var(--arcis-bg-elevated)` background, `var(--arcis-border)` borders, `var(--arcis-text-primary)` text
2. **Section grouping:** Group settings into cards: Trading, Risk, Model, Scheduler. Each card has a header with an icon and description
3. **Input styling:** Number inputs with +/- stepper buttons. Toggle switches for boolean settings (not checkboxes). Dropdowns with custom styling matching the theme.
4. **Source badges:** Each setting shows "yaml default" (muted) or "dashboard override" (accent color pill) to indicate where the value comes from
5. **Save feedback:** When a setting change is submitted, show a brief "Saving..." → "Saved ✓" animation
6. **Reset button:** "Reset all to YAML defaults" at the bottom with confirmation dialog
7. **Responsive:** Settings should be single-column on mobile, two-column on desktop

---

## Task 9: Documentation Update (MANDATORY)

Run verification from `docs/sprint-checklist.md`. Update:
- AGENTS.md counts (if any new files)
- CHANGELOG.md (Sprint 5 entry)
- Regenerate `config/known_violations.json` if any violations were fixed

```bash
python -m pytest tests/ -x -q
cd frontend && npm run build && cd ..
find tests -name "test_*.py" -exec grep -c "def test_" {} + | awk -F: '{s+=$2}END{print "Tests:", s}'
```

Paste and complete sprint checklist.

---

## Important Notes for CC

1. **This is a UI-only sprint.** Do not change any backend logic, API endpoints, or database schema. If a backend change is needed (like adding `validate-system` to the executor), keep it minimal.
2. **Test on mobile viewport.** Use Chrome DevTools responsive mode (375px width) to verify every page looks right on iPhone.
3. **Don't break existing functionality.** Every page currently works (except Validation button). Improve the UX without removing features.
4. **Use existing API endpoints.** All data needed is already available through the existing API. Don't create new endpoints.
5. **Use the Arcis design system.** `var(--arcis-*)` for all colors. No hardcoded hex values. `className="financial-data"` for all financial numbers. ▲/▼ arrows on all P&L values.
