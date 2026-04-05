# Sprint: Bloomberg Terminal UI Overhaul — Page-by-Page with 3× Ralph Loop

> **Priority:** MEDIUM — professional presentation for stakeholders
> **Estimated time:** 8-12 hours CC time
> **Access:** LOCAL — frontend only, zero backend changes
> **Branch:** `feat/ui-bloomberg`
> **Quality gate:** Independent agent auditor must rate EVERY page ≥ 9/10

> ⚠️ **FRONTEND ONLY.** This sprint touches ONLY files in `frontend/src/`.
> Zero overlap with gap-assessment or simulation-engine sprints.

---

## Guiding Aesthetic: Bloomberg Terminal

This dashboard should make someone say "you built this yourself?" — not flashy, not startup-y,
but **institutional, data-dense, and undeniably professional**. Bloomberg Terminal is the reference
because it's what fund managers, traders, and allocators recognize as "serious."

### Bloomberg Design Principles (INTERNALIZE THESE)

1. **Near-black background** — #030305 primary, #0A0A0F surface. Not charcoal. DARK.
2. **Data density over whitespace** — more information per screen, less padding
3. **Monospace numbers EVERYWHERE** — every price, %, count, ratio = JetBrains Mono tabular-nums
4. **Color is EARNED** — mostly gray/white text on dark. Color reserved for:
   - Green (#22C55E) → positive P&L, passing gates, healthy status
   - Red (#EF4444) → negative P&L, failing gates, errors
   - Amber (#F59E0B) → warnings, attention items
   - Blue (#3B82F6) → interactive elements ONLY (buttons, links, active nav)
   - Everything else → grayscale
5. **NO TEAL.** Bloomberg doesn't use teal. Replace ALL teal across the entire codebase.
6. **Squared corners** — 2-4px radius. Rounded = casual. Square = institutional.
7. **Thin neutral borders** — 1px, rgba(255,255,255,0.06). Not colored. Not thick.
8. **No shadows.** Bloomberg is flat. Remove all box-shadows.
9. **Status bar at top** — system vitals always visible (LLM, market, traffic light, positions, time)
10. **Typography hierarchy through weight, not color** — bold labels, regular values, mono for data

### Creative License

CC has creative freedom to:
- Add UI elements that improve information density (sparklines, inline indicators, micro-charts)
- Reorganize page layouts for better data flow
- Add new metrics displays if the API already provides the data
- Add subtle hover states, keyboard navigation, or data highlights
- Merge or split panels if it improves the page
- Add section dividers, header treatments, or grid layouts

CC does NOT have license to:
- Change any backend code or API endpoints
- Break any existing data connections
- Remove any functional element (buttons, tables, charts that serve a purpose)
- Add animations or transitions (Bloomberg is static)
- Use gradients, glowing effects, or decorative elements

---

## Pre-Flight

1. `cd frontend && npm run build` — confirm baseline builds
2. Take screenshots of EVERY page in current state (save to `docs/screenshots/before/`)
3. Read `frontend/src/index.css` — current CSS variables
4. Read `frontend/src/components/Layout.jsx` — sidebar and nav structure
5. Catalog all API data connections per page (from the useQuery calls)

---

## Phase 1: Design System Foundation

### Task 1.1: CSS Variables (`frontend/src/index.css`)

Apply the Bloomberg palette. See the full variable spec below.

**Dark mode:**
```css
:root, [data-theme="dark"] {
  --arcis-bg-primary: #030305;
  --arcis-bg-surface: #0A0A0F;
  --arcis-bg-elevated: #101018;
  --arcis-accent: #3B82F6;
  --arcis-accent-hover: #2563EB;
  --arcis-accent-muted: rgba(37, 99, 235, 0.06);
  --arcis-text-primary: #D4D4D8;
  --arcis-text-secondary: #71717A;
  --arcis-text-muted: #3F3F46;
  --arcis-border: rgba(255, 255, 255, 0.06);
  --arcis-border-hover: rgba(255, 255, 255, 0.12);
  --arcis-success: #22C55E;
  --arcis-danger: #EF4444;
  --arcis-warning: #F59E0B;
  --arcis-info: #3B82F6;
  --arcis-positive: #22C55E;
  --arcis-negative: #EF4444;
  --arcis-neutral: #71717A;
  --radius-sm: 2px;
  --radius-md: 3px;
  --radius-lg: 4px;
  --radius-xl: 6px;
}
```

**Remove ALL teal variables.** Global search-replace:
- `var(--arcis-teal-light)` → `var(--arcis-accent)` for interactive, `var(--arcis-success)` for positive
- `var(--arcis-teal)` → `var(--arcis-accent)`
- `var(--teal-400)` / `var(--teal-500)` → `var(--arcis-accent)`
- Delete `--arcis-teal`, `--arcis-teal-light`, `--teal-400`, `--teal-500` from both themes

**Card styling — no shadows, tight padding, squared:**
```css
.arcis-card {
  background: var(--arcis-bg-surface);
  border: 1px solid var(--arcis-border);
  border-radius: var(--radius-md);
  padding: 12px;
  box-shadow: none;
}
```

**Scrollbar styling:**
```css
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: var(--arcis-bg-primary); }
::-webkit-scrollbar-thumb { background: var(--arcis-border-hover); border-radius: 2px; }
```

### Task 1.2: Layout + Status Bar (`frontend/src/components/Layout.jsx`)

**Sidebar:** Narrow to ~200px. Active item = left blue border (2px), not background highlight.
No rounded pills. No hover background changes — just color shifts.

**Add a status bar** above the content area (28px height):
```
ARCIS v0.15.0 | LLM ONLINE | MKT CLOSED | TL: GREEN | 9 POSITIONS | 16:42:31 ET
```
Data sourced from existing health/status API. Monospace, 11px, dim text.

### Task 1.3: Shared Components

Update these components to match the design system:

**MetricCard** — tighter padding (10px 12px), uppercase 11px label, 20px mono value, 2px radius
**DataTable** — 10px uppercase headers, mono cells, right-align numbers, 28px row height, no zebra stripes
**LoadingSpinner** — replace spinner with "LOADING..." text in mono uppercase
**EmptyState** — "NO DATA" in mono uppercase, centered
**StatusBadge** — squared, 2px radius, no rounded-full
**PnlText** — ensure green/red ONLY, mono font, +/- prefix

---

## Phase 2: Page-by-Page Overhaul with 3× Ralph Loop

**For EACH of the 18 pages, follow this protocol:**

### Ralph Loop Protocol (repeat 3 times per page)

**Pass 1 — Implement:** Apply the design system. Fix layout, typography, colors, spacing.
Ensure all data connections work and render correctly.

**Pass 2 — Review for gaps:** Re-read the page code. Ask:
- Is every data field being displayed? Is there API data available that isn't shown?
- Is the layout information-dense enough? Could we show more without scrolling?
- Are numbers in monospace? Are P&L values green/red? Are labels uppercase?
- Is there any teal remaining? Any rounded corners > 4px? Any shadows?
- Could adding a sparkline, inline indicator, or summary stat improve the page?
- Is the information hierarchy clear? Does the eye know where to look first?

**Pass 3 — Polish:** Fix everything identified in Pass 2. Add any UI elements that improve
the page. Verify the page builds and renders correctly.

### Page Order (largest/most important first)

**Tier 1 — Primary pages (highest visibility):**

1. **Dashboard.jsx** (503 lines) — The homepage. Must be perfect.
   - Top row: 6-8 KPIs in tight grid (trades, WR, PF, Sharpe, DD, expectancy, build score, HSHS)
   - Equity curve: full width, ~180px, subtle blue area fill
   - Two-column bottom: open positions table (left) + activity feed (right)
   - System audit chip + traffic light state visible
   - All numbers mono, P&L green/red, everything else neutral

2. **ShadowLedger.jsx** (729 lines) — The trade log. Data-heaviest page.
   - Full-width financial data table
   - Column sorting, P&L coloring, monospace throughout
   - Filters/search bar: squared, compact
   - Entry/exit prices right-aligned, mono

3. **CTOReport.jsx** (369 lines) — The executive summary.
   - This is what you'd show an allocator. Must feel like a Bloomberg report.
   - Section headers with thin borders, not large colored blocks
   - All metrics in a structured grid, not loose paragraphs
   - Fund metrics prominently displayed

4. **Roadmap.jsx** (548 lines) — The strategic plan.
   - Remove ALL teal (15 references)
   - Progress bars: blue accent
   - Gate metrics: green/red for pass/fail
   - Phase cards: clean borders, compact, professional

**Tier 2 — Functional pages:**

5. **LiveLedger.jsx** (400 lines) — Live trade monitoring
6. **Council.jsx** (464 lines) — AI Council display
7. **Health.jsx** (296 lines) — System health metrics
8. **Training.jsx** (322 lines) — Model training status
9. **Validation.jsx** (285 lines) — Data validation results
10. **StressTest.jsx** (198 lines) — Stress test results
11. **Attribution.jsx** (157 lines) — Alpha attribution

**Tier 3 — Support pages:**

12. **Settings.jsx** (329 lines) — Configuration
13. **Logs.jsx** (274 lines) — Log viewer
14. **Notes.jsx** (385 lines) — Research notes
15. **Docs.jsx** (286 lines) — Documentation browser
16. **Packets.jsx** (88 lines) — Trade packets
17. **Architecture.jsx** (195 lines) — System architecture
18. **DBSchema.jsx** (194 lines) — Database schema viewer

---

## Phase 3: Independent Agent Auditor

**After completing all 18 pages, run this auditor protocol.**

For EACH page, use the Anthropic API (`claude-sonnet-4-20250514`) to conduct an independent
UI/UX review. The auditor prompt:

```
You are a senior UI/UX auditor specializing in financial dashboard design. You have
extensive experience with Bloomberg Terminal, Refinitiv Eikon, and FactSet interfaces.

Rate this dashboard page on a scale of 1-10 across these dimensions:
1. Visual hierarchy — does the eye know where to look?
2. Data density — is information efficiently presented?
3. Typography — are numbers monospace? Labels clear? Sizes appropriate?
4. Color usage — is color earned (green/red for P&L only, blue for interactive)?
5. Professionalism — would this pass in a fund manager's office?
6. Consistency — does it match the Bloomberg Terminal aesthetic?
7. Functionality — do all data connections appear to work?

For each dimension, provide:
- Score (1-10)
- One specific improvement suggestion

Overall score: [average of 7 dimensions]

If overall score < 9.0, provide a SPECIFIC action list to reach 9.0+.
```

**Implementation:**
1. After each page is styled, take a mental snapshot of the final state
2. Review the JSX code as the "screenshot" — the auditor evaluates code structure,
   styling patterns, data bindings, and layout
3. If score < 9.0, implement the auditor's suggestions and re-audit
4. Repeat until 9.0+ on every page

**Acceptance criteria: ALL 18 pages must score ≥ 9.0/10 from the auditor.**

---

## Phase 4: Integration Verification

After all pages pass the auditor:

```bash
cd frontend && npm run build    # Must succeed with zero warnings

# Manual verification checklist:
# [ ] Every page loads without console errors
# [ ] All data connections render real data (not placeholder)
# [ ] All charts render correctly
# [ ] All tables sort/filter correctly
# [ ] Dark mode: fully styled, no white elements or teal
# [ ] Light mode: fully styled, professional
# [ ] Status bar shows live system data
# [ ] Sidebar navigation works for all 18 pages
# [ ] No teal visible ANYWHERE (global grep confirms zero matches)
# [ ] All numbers are monospace
# [ ] All P&L values are green/red
# [ ] All corners are ≤ 4px radius
# [ ] No box shadows anywhere
```

**Take screenshots of every page.** Save to `docs/screenshots/after/`.

---

## Commit Strategy

```bash
# Commit 1: Design system foundation
git add frontend/src/index.css frontend/src/components/
git commit -m "feat(ui): Bloomberg design system — CSS variables, layout, shared components

Near-black palette, all teal removed, squared corners (2-4px),
no shadows, status bar, monospace numbers, condensed spacing.
Shared components: MetricCard, DataTable, Layout, StatusBadge."

# Commit 2: Tier 1 pages (Dashboard, ShadowLedger, CTOReport, Roadmap)
git add frontend/src/pages/Dashboard.jsx frontend/src/pages/ShadowLedger.jsx \
       frontend/src/pages/CTOReport.jsx frontend/src/pages/Roadmap.jsx
git commit -m "feat(ui): Tier 1 pages — Dashboard, ShadowLedger, CTOReport, Roadmap

Bloomberg aesthetic: data-dense KPI grids, financial tables,
monospace numbers, green/red P&L only, zero teal.
All 4 pages pass agent auditor at 9.0+/10."

# Commit 3: Tier 2 pages
git add frontend/src/pages/LiveLedger.jsx frontend/src/pages/Council.jsx \
       frontend/src/pages/Health.jsx frontend/src/pages/Training.jsx \
       frontend/src/pages/Validation.jsx frontend/src/pages/StressTest.jsx \
       frontend/src/pages/Attribution.jsx
git commit -m "feat(ui): Tier 2 pages — LiveLedger, Council, Health, Training, Validation, StressTest, Attribution

All 7 pages Bloomberg-styled and pass agent auditor at 9.0+/10."

# Commit 4: Tier 3 pages + screenshots
git add frontend/src/pages/ docs/screenshots/
git commit -m "feat(ui): Tier 3 pages + before/after screenshots

Settings, Logs, Notes, Docs, Packets, Architecture, DBSchema.
All 18 pages pass agent auditor at 9.0+/10.
Before/after screenshots in docs/screenshots/."
```

Do NOT merge to main. Push to `feat/ui-bloomberg` only.
