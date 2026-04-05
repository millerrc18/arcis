# Sprint: UI Overhaul — Bloomberg Terminal Aesthetic

> **Priority:** MEDIUM — professional presentation for stakeholders
> **Estimated time:** 3-5 hours CC time
> **Access:** LOCAL — frontend only, zero backend changes
> **Tag as v0.15.1 (or v0.16.1 depending on merge order)**
> **Branch:** `feat/ui-bloomberg`

> ⚠️ **FRONTEND ONLY.** This sprint touches ONLY files in `frontend/src/`.
> Zero overlap with gap-assessment or simulation-engine sprints.
> Can run in parallel with both.

---

## Design Direction: Bloomberg Terminal

The goal is a dashboard that makes someone say "you built this yourself?" — not flashy,
not startup-y, but **institutional and data-dense**. Bloomberg Terminal is the reference
because it's what fund managers, traders, and allocators recognize as "serious."

### Key Bloomberg Design Principles

1. **Near-black background** — not charcoal gray, actual near-black (#050507 is correct, keep it)
2. **Data density over whitespace** — more information per screen, less padding
3. **Monospace numbers EVERYWHERE** — every price, percentage, count, ratio uses JetBrains Mono
4. **Restrained color palette** — mostly gray text on dark bg. Color is EARNED:
   - Green (#22C55E) ONLY for positive P&L / passing metrics
   - Red (#EF4444) ONLY for negative P&L / failing metrics
   - Amber (#F59E0B) ONLY for warnings / attention items
   - Blue accent (#3B82F6) ONLY for interactive elements (buttons, links, active nav)
   - Everything else is grayscale
5. **No teal.** Bloomberg doesn't use teal. Replace ALL teal with blue accent or white.
6. **Squared corners** — reduce border-radius from 8px to 2-4px. Rounded = casual. Square = institutional.
7. **Thin borders** — 1px borders in very subtle colors, not the thicker accent-colored ones
8. **Information hierarchy via typography, not color** — bold for labels, regular for values, mono for numbers
9. **Status bar header** — system status always visible: LLM status, market state, traffic light, positions
10. **Tables are first-class** — not cards with tables inside. Proper financial data tables.

### What Bloomberg is NOT

- Not flashy gradients or glowing effects
- Not large hero cards with icons
- Not rounded pill buttons
- Not colorful sidebar with active indicators
- Not teal/green accent on everything

---

## Pre-Flight

1. Run `cd frontend && npm run build` — confirm it builds
2. Take screenshots of current state (for before/after comparison)
3. Read `frontend/src/index.css` — the CSS variable definitions
4. Read `frontend/src/components/Layout.jsx` — sidebar and nav
5. Read `frontend/src/pages/Dashboard.jsx` — main dashboard
6. Read `frontend/src/components/MetricCard.jsx` — KPI cards

---

## Task 1: CSS Variable Overhaul (`frontend/src/index.css`)

### Dark mode (default) — push darker, remove teal

```css
:root, [data-theme="dark"] {
  /* Bloomberg Dark — near-black with blue accent */
  --arcis-bg-primary: #030305;        /* Was #050507 — slightly darker */
  --arcis-bg-surface: #0A0A0F;        /* Was #0C0C10 — darker surface */
  --arcis-bg-elevated: #101018;        /* Was #12121A — subtle lift */
  --arcis-accent: #3B82F6;             /* Keep — blue is correct */
  --arcis-accent-hover: #2563EB;       /* Keep */
  --arcis-accent-muted: rgba(37, 99, 235, 0.06);  /* Slightly less visible */
  --arcis-text-primary: #D4D4D8;       /* Was #E4E4E7 — slightly dimmer, less eye strain */
  --arcis-text-secondary: #71717A;     /* Was #A1A1AA — more muted */
  --arcis-text-muted: #3F3F46;         /* Was #52525B — darker */
  --arcis-border: rgba(255, 255, 255, 0.06);  /* Was blue-tinted — now neutral */
  --arcis-border-hover: rgba(255, 255, 255, 0.12);

  /* Semantic — REMOVE teal entirely */
  --arcis-success: #22C55E;
  --arcis-danger: #EF4444;
  --arcis-warning: #F59E0B;
  --arcis-info: #3B82F6;
  /* DELETE: --arcis-teal and --arcis-teal-light — replace all references with accent or success */

  /* Bloomberg-style data colors */
  --arcis-positive: #22C55E;           /* P&L green */
  --arcis-negative: #EF4444;           /* P&L red */
  --arcis-neutral: #71717A;            /* Unchanged / zero */

  /* Tighter radius — institutional, not startup */
  --radius-sm: 2px;                    /* Was 4px */
  --radius-md: 3px;                    /* Was 6px */
  --radius-lg: 4px;                    /* Was 8px */
  --radius-xl: 6px;                    /* Was 12px */
}
```

### Light mode — clean but still professional

```css
[data-theme="light"] {
  --arcis-bg-primary: #FAFAFA;
  --arcis-bg-surface: #FFFFFF;
  --arcis-bg-elevated: #F4F4F5;
  --arcis-accent: #1D4ED8;             /* Slightly darker blue for light mode */
  --arcis-text-primary: #18181B;
  --arcis-text-secondary: #52525B;
  --arcis-text-muted: #A1A1AA;
  --arcis-border: #E4E4E7;
  --arcis-border-hover: #D4D4D8;
}
```

### Card styling — tighter, squared

```css
.arcis-card {
  background: var(--arcis-bg-surface);    /* Was elevated — surface is more Bloomberg */
  border: 1px solid var(--arcis-border);
  border-radius: var(--radius-md);         /* Was 8px → now 3px */
  padding: 12px;                           /* Was 16px — tighter */
  box-shadow: none;                        /* Bloomberg has no shadows */
  transition: border-color 0.15s ease;
}
.arcis-card:hover {
  border-color: var(--arcis-border-hover);
}
```

---

## Task 2: Replace ALL Teal References

Search and replace across the entire `frontend/src/` directory:

```bash
# Find all teal references
grep -rn "arcis-teal\|teal-light\|teal-400\|teal-500\|#14B8A6\|#0D9488\|#2DD4BF\|#0F766E" frontend/src/ --include="*.jsx" --include="*.css"
```

**Replacement rules:**
- `var(--arcis-teal-light)` → `var(--arcis-accent)` (interactive/progress elements)
- `var(--arcis-teal)` → `var(--arcis-accent)` (general accent)
- `var(--teal-400)` / `var(--teal-500)` → `var(--arcis-accent)` (chart colors)
- In Roadmap.jsx: progress bars were teal → change to accent blue
- In Dashboard.jsx: success indicators that were teal → keep as `var(--arcis-success)` if P&L related, else `var(--arcis-accent)`
- In Health.jsx: health indicators → `var(--arcis-success)` for healthy, `var(--arcis-accent)` for neutral

**Delete from CSS variables:**
```css
/* REMOVE these lines from both dark and light mode */
--arcis-teal: ...
--arcis-teal-light: ...
--teal-400: ...
--teal-500: ...
```

After removal, update `--chart-2` (currently teal) to a steel blue: `#60A5FA`.

---

## Task 3: Layout + Sidebar (`Layout.jsx`)

### Bloomberg-style sidebar

- Narrower: 56px width → 200px (current 224px is fine, reduce to 200)
- Remove rounded active indicators
- Active page: left border accent, not background highlight
- System status footer: show LLM status, market state, position count

```jsx
// Active nav item style — Bloomberg uses left border, not background
style={{
  borderLeft: isActive ? '2px solid var(--arcis-accent)' : '2px solid transparent',
  paddingLeft: '14px',
  background: 'transparent',  // No background highlight
  color: isActive ? 'var(--arcis-text-primary)' : 'var(--arcis-text-secondary)',
}}
```

### Top status bar (add to Layout)

Add a thin status bar above the content area:
```jsx
<div style={{
  height: 28,
  background: 'var(--arcis-bg-surface)',
  borderBottom: '1px solid var(--arcis-border)',
  display: 'flex',
  alignItems: 'center',
  padding: '0 16px',
  gap: 16,
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
  color: 'var(--arcis-text-secondary)',
}}>
  <span>ARCIS v0.15.0</span>
  <span>|</span>
  <span style={{ color: llmOk ? 'var(--arcis-success)' : 'var(--arcis-danger)' }}>
    LLM {llmOk ? 'ONLINE' : 'OFFLINE'}
  </span>
  <span>|</span>
  <span>MKT {marketOpen ? 'OPEN' : 'CLOSED'}</span>
  <span>|</span>
  <span>TL: {trafficLight}</span>
  <span>|</span>
  <span>{openPositions} POSITIONS</span>
  <span style={{ marginLeft: 'auto' }}>
    {new Date().toLocaleTimeString('en-US', { hour12: false })} ET
  </span>
</div>
```

This gives an instant "professional system" feel. The data comes from the existing health API.

---

## Task 4: MetricCard Component — Data Dense

Current MetricCards are too padded with large fonts. Bloomberg shows numbers tight and dense.

```jsx
// MetricCard — Bloomberg style
<div style={{
  background: 'var(--arcis-bg-surface)',
  border: '1px solid var(--arcis-border)',
  borderRadius: 'var(--radius-md)',
  padding: '10px 12px',
}}>
  <div style={{
    fontSize: 11,
    color: 'var(--arcis-text-secondary)',
    textTransform: 'uppercase',
    letterSpacing: '0.03em',
    marginBottom: 2,
  }}>{label}</div>
  <div style={{
    fontSize: 20,
    fontWeight: 600,
    fontFamily: 'var(--font-mono)',
    color: 'var(--arcis-text-primary)',
    fontVariantNumeric: 'tabular-nums',
  }}>{value}</div>
  {subtitle && (
    <div style={{
      fontSize: 11,
      fontFamily: 'var(--font-mono)',
      color: changeColor,
      marginTop: 2,
    }}>{subtitle}</div>
  )}
</div>
```

---

## Task 5: DataTable Component — Financial Grid

Current tables need Bloomberg-style treatment:

```css
/* Financial data table */
.data-table th {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--arcis-text-muted);
  padding: 6px 10px;
  border-bottom: 1px solid var(--arcis-border);
  font-weight: 500;
  white-space: nowrap;
}

.data-table td {
  font-size: 12px;
  padding: 5px 10px;
  border-bottom: 1px solid var(--arcis-border);
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums lining-nums;
}

.data-table tr:hover {
  background: var(--arcis-bg-elevated);
}
```

- Right-align all numeric columns
- Green/red for P&L columns only
- No alternating row colors (Bloomberg doesn't use zebra stripes)
- Condensed row height (28px, not 40px)

---

## Task 6: Dashboard Page — Information Dense Layout

Restructure Dashboard.jsx for maximum data density:

### Top row: 6-8 KPIs in a tight grid
```jsx
<div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 8 }}>
  {/* Trades, Win Rate, P&L, Sharpe, DD, PF, Expectancy, Build Score */}
</div>
```

### Middle: Equity curve (full width, 180px height — not too tall)

### Bottom: Two-column layout
- Left: Open positions table (DataTable, condensed)
- Right: Activity feed (monospace, terminal-style)

### Remove or shrink:
- Large welcome/summary text
- Oversized card headers
- Excessive spacing between sections

---

## Task 7: Chart Styling — Muted and Professional

All Recharts charts should follow Bloomberg conventions:

```jsx
// Chart defaults
const CHART_STYLE = {
  stroke: 'var(--arcis-accent)',      // Single line color — blue
  fill: 'var(--arcis-accent)',
  fillOpacity: 0.05,                   // Very subtle area fill
  grid: { stroke: 'var(--arcis-border)', strokeDasharray: '2 4' },
  axis: { stroke: 'var(--arcis-text-muted)', fontSize: 10 },
  tooltip: {
    background: 'var(--arcis-bg-elevated)',
    border: '1px solid var(--arcis-border)',
    fontSize: 11,
    fontFamily: 'var(--font-mono)',
  },
}
```

- Single color per chart (blue for primary, with green/red only for P&L)
- No gradient fills
- Minimal grid lines (horizontal only, dashed)
- No chart legends unless 2+ series — use inline labels instead

---

## Task 8: Roadmap.jsx — Remove Teal, Professional Progress

The Roadmap has 15 teal references. Replace ALL:

- Progress bars: teal → `var(--arcis-accent)`
- Done indicators: teal → `var(--arcis-success)`
- Gate metrics: teal passing → `var(--arcis-success)`, failing → `var(--arcis-danger)`
- Phase borders: teal → `var(--arcis-accent)`

---

## Task 9: Polish Details

1. **Button styles** — Remove all rounded-full pills. Use squared buttons:
   ```css
   button { border-radius: var(--radius-sm); }
   ```

2. **Tooltips** — Dark background, mono font, no rounded corners, 1px border

3. **Loading states** — Replace spinner with "LOADING..." text in mono (Bloomberg style)

4. **Empty states** — "NO DATA" in uppercase mono, centered, muted color

5. **Favicon + title** — Ensure browser tab shows "ARCIS" (not Halcyon Lab)

6. **Scrollbars** — Style thin and dark:
   ```css
   ::-webkit-scrollbar { width: 6px; }
   ::-webkit-scrollbar-track { background: var(--arcis-bg-primary); }
   ::-webkit-scrollbar-thumb { background: var(--arcis-border-hover); border-radius: 2px; }
   ```

---

## What NOT to Change

- **Keep the sidebar navigation structure** — just restyle it
- **Keep all existing page functionality** — only change visual presentation
- **Keep dark/light toggle** — but make light mode also professional
- **Keep JetBrains Mono** — it's perfect for this aesthetic
- **Keep Inter for body text** — it's the right choice for UI labels
- **Do NOT add animations** — Bloomberg is static. No transitions, no fades, no hover effects beyond subtle border color changes

---

## Verification

```bash
cd frontend && npm run build      # Must succeed
# Open in browser and verify:
# 1. No teal visible anywhere
# 2. Blue accent only on interactive elements
# 3. Green/red only on P&L and pass/fail
# 4. All numbers in monospace
# 5. Status bar visible at top
# 6. Squared corners throughout
# 7. Data-dense layout — more info visible without scrolling
# 8. Both dark and light mode work
```

**Before/after screenshots** — save to `docs/screenshots/` for comparison.

---

## Commit

```bash
git add frontend/
git commit -m "feat: Bloomberg Terminal UI overhaul — professional data-dense aesthetic

VISUAL CHANGES:
- Remove all teal: replaced with blue accent (interactive) and green (success)
- Near-black background pushed darker
- Squared corners throughout (8px → 2-4px)
- Data-dense MetricCards with tight padding
- Financial data tables with monospace numbers and condensed rows
- Top status bar: LLM, market, traffic light, positions, time
- Sidebar: left-border active state, narrower
- Charts: single-color, no gradients, minimal grid
- No shadows (Bloomberg has none)

PRESERVED:
- All functionality unchanged
- Dark/light toggle
- JetBrains Mono for numbers, Inter for labels"
```
