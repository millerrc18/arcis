# Sprint 4A: Arcis Brand Infrastructure

> **Executor:** Codex
> **Scope:** 8 tasks | Brand rename + palette + fonts + dark/light toggle + API stubs
> **Prerequisite:** None — this sprint runs first
> **Merge before:** Sprint 4B depends on this being merged

---

## System Overview

You are working on `halcyon-lab` (github.com/millerrc18/halcyon-lab), an autonomous AI-powered equity trading system. This system:

- Trades S&P 100 stocks via Alpaca bracket orders
- Uses a locally fine-tuned Qwen3 8B LLM for trade analysis
- Has a 5-agent AI council for portfolio-level strategic decisions
- Runs 13 scans/day during market hours via an APScheduler watch loop
- Has a React 18 dashboard served via Render at halcyonlab.app
- Has 165 Python files, 78 test files, 1,083 test functions, 66 research documents
- Is in Phase 1 (bootcamp) with ~25 open positions, ~5 closed trades toward a 50-trade gate

**The system is being rebranded from "Halcyon Lab" to "Arcis"** (Latin for fortress; backronym: Adaptive Regime Classification & Intelligence Systems). The dashboard palette is changing from teal-on-navy to "Electric Focus" (Palette H).

---

## Codebase Architecture

### Backend (Python 3.12 + FastAPI)
```
src/
├── api/
│   ├── cloud_app.py          # 200 lines — thin bootstrap, imports routers
│   ├── cloud_routes/          # Route modules (core, trades, training, notes, council, analytics)
│   ├── routes/                # Local API routes (system.py)
│   ├── app.py                 # Local FastAPI app
│   └── websocket.py           # WebSocket for real-time updates
├── cli/commands.py            # CLI command handlers (split from main.py)
├── council/                   # 10 modules: agents, agent_data, prompts, protocol, parsing, etc.
├── evaluation/                # hshs_live.py, gate_evaluator.py, quality_rubric.py
├── features/                  # traffic_light.py, event_risk_score.py, enrichment/
├── llm/                       # validator.py, grammar_client.py
├── notifications/telegram.py  # 32 notification functions
├── risk/governor.py           # 8 risk checks
├── scheduler/watch.py         # Main watch loop with APScheduler
├── services/scan_service.py   # Scan pipeline
├── shadow_trading/            # executor.py, bracket_monitor.py
├── sync/render_sync.py        # SQLite → Render Postgres sync
├── training/                  # generator.py, ingestion_gate.py
└── main.py                    # 250 lines — CLI entry point
```

### Frontend (React 18 + Tailwind CSS + React Query)
```
frontend/
├── public/
│   ├── index.html             # Page title, meta tags, font imports
│   └── manifest.json          # PWA manifest
├── src/
│   ├── api.js                 # API client with all fetch methods
│   ├── App.jsx                # Router, QueryClient, WebSocket provider
│   ├── config.js              # API_BASE, IS_CLOUD detection
│   ├── index.css              # CSS variables, font imports, base styles
│   ├── components/
│   │   ├── Layout.jsx         # Sidebar nav, header, mobile responsive
│   │   ├── AuthGate.jsx       # Password protection for cloud
│   │   ├── ErrorBoundary.jsx
│   │   ├── StatusBadge.jsx
│   │   └── Toast.jsx
│   └── pages/                 # 13 pages (Dashboard, ShadowLedger, Council, Health, etc.)
└── tailwind.config.js
```

### Current Color System (being replaced)
The current `frontend/src/index.css` defines CSS variables:
- `--teal-50` through `--teal-900` (primary brand color)
- `--amber-50` through `--amber-700` (accent)
- `--slate-50` through `--slate-900` (neutral)
- `--success`, `--warning`, `--danger`, `--info`, `--bullish`, `--bearish` (semantic)
- `--chart-1` through `--chart-8` (chart series)
- `--font-display`: Space Grotesk
- `--font-body`: Inter
- `--font-mono`: JetBrains Mono

Body background is `var(--slate-800)` (#0F172A) and text is `var(--slate-100)`.

### Current Brand References
The sidebar header in `Layout.jsx` says:
```jsx
<h1 style={{ fontFamily: 'var(--font-display)', color: 'var(--teal-400)' }}>HALCYON LAB</h1>
<div style={{ color: 'var(--slate-400)' }}>AI Research Desk</div>
```

The PWA manifest and index.html title say "Halcyon Lab".

---

## Brand Decisions (ALL FINAL — do not deviate)

| Property | Old Value | New Value |
|---|---|---|
| Name | Halcyon Lab | **Arcis** |
| Tagline | AI Research Desk | **Systematic Equity Research** |
| Display font | Space Grotesk | **Inter** (ExtraBold 800 for display) |
| Body font | Inter | **Inter** (unchanged) |
| Mono font | JetBrains Mono | **JetBrains Mono** (unchanged) |

### Palette H: Electric Focus

**Dark mode (DEFAULT):**
| Role | CSS Variable | Hex |
|---|---|---|
| Background | `--arcis-bg-primary` | `#050507` |
| Surface/Card | `--arcis-bg-surface` | `#0C0C10` |
| Elevated | `--arcis-bg-elevated` | `#12121A` |
| Accent | `--arcis-accent` | `#3B82F6` |
| Accent hover | `--arcis-accent-hover` | `#2563EB` |
| Accent muted | `--arcis-accent-muted` | `rgba(37, 99, 235, 0.08)` |
| Text primary | `--arcis-text-primary` | `#E4E4E7` |
| Text secondary | `--arcis-text-secondary` | `#A1A1AA` |
| Text muted | `--arcis-text-muted` | `#52525B` |
| Border default | `--arcis-border` | `rgba(37, 99, 235, 0.08)` |
| Border hover | `--arcis-border-hover` | `rgba(37, 99, 235, 0.15)` |

**Light mode (toggle):**
| Role | CSS Variable | Hex |
|---|---|---|
| Background | `--arcis-bg-primary` | `#F8FAFC` |
| Surface/Card | `--arcis-bg-surface` | `#FFFFFF` |
| Elevated | `--arcis-bg-elevated` | `#F1F5F9` |
| Accent | `--arcis-accent` | `#2563EB` |
| Accent hover | `--arcis-accent-hover` | `#1D4ED8` |
| Accent muted | `--arcis-accent-muted` | `rgba(37, 99, 235, 0.06)` |
| Text primary | `--arcis-text-primary` | `#0F172A` |
| Text secondary | `--arcis-text-secondary` | `#475569` |
| Text muted | `--arcis-text-muted` | `#64748B` |
| Border default | `--arcis-border` | `#E2E8F0` |
| Border hover | `--arcis-border-hover` | `#CBD5E1` |

**Shared (both modes):**
| Role | CSS Variable | Hex |
|---|---|---|
| Success / Profit | `--arcis-success` | `#22C55E` |
| Danger / Loss | `--arcis-danger` | `#EF4444` |
| Warning | `--arcis-warning` | `#F59E0B` |
| Teal (secondary) | `--arcis-teal` | `#0D9488` |
| Teal light | `--arcis-teal-light` | `#14B8A6` |
| Info / Blue | `--arcis-info` | `#3B82F6` |

**Chart series (both modes):**
| Variable | Hex | Purpose |
|---|---|---|
| `--chart-1` | `#3B82F6` | Blue (primary) |
| `--chart-2` | `#14B8A6` | Teal |
| `--chart-3` | `#F59E0B` | Amber |
| `--chart-4` | `#A78BFA` | Violet |
| `--chart-5` | `#FB7185` | Rose |
| `--chart-6` | `#22D3EE` | Cyan |
| `--chart-7` | `#FBBF24` | Yellow |
| `--chart-8` | `#E879F9` | Fuchsia |

### Typography Hierarchy
| Element | Font | Weight | Size | Extras |
|---|---|---|---|---|
| Page title (H1) | Inter | ExtraBold 800 | 24px | letter-spacing: -0.03em |
| Section header (H2) | Inter | SemiBold 600 | 18px | letter-spacing: -0.02em |
| Body text | Inter | Regular 400 | 14px | line-height: 20px |
| UI label | Inter | Medium 500 | 11px | letter-spacing: 0.04em, uppercase |
| KPI number | Inter | Bold 700 | 28px | font-variant-numeric: tabular-nums |
| Financial data | JetBrains Mono | Regular 400 | 13px | tabular-nums, slashed-zero |
| Ticker symbol | JetBrains Mono | Medium 500 | 12px | uppercase |

---

## Pre-Sprint Checks (MANDATORY — run before ANY tasks)

```bash
# File size guardrail — no src/ file over 400 lines
find src -name "*.py" ! -path "*__pycache__*" -exec sh -c 'lines=$(wc -l < "$1"); if [ "$lines" -gt 400 ]; then echo "VIOLATION: $1 ($lines lines)"; fi' _ {} \;

# Function length guardrail — no function over 60 lines
python3 -c "
import ast, pathlib
for p in pathlib.Path('src').rglob('*.py'):
    try:
        tree = ast.parse(p.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                length = node.end_lineno - node.lineno
                if length > 60:
                    print(f'VIOLATION: {p}:{node.name} ({length} lines)')
    except: pass
"

# Current test count (baseline)
find tests -name "test_*.py" -exec grep -c "def test_" {} + | awk -F: '{s+=$2}END{print "Tests:", s}'

# Frontend build check
cd frontend && npm run build && cd ..
```

Fix any violations BEFORE starting feature work. Do NOT add features and refactor in the same sprint.

---

## Task 1: Rename Halcyon Lab → Arcis Across Entire Codebase

**Goal:** Every user-visible string that says "Halcyon Lab", "Halcyon", or "HALCYON" becomes "Arcis" or "ARCIS".

**IMPORTANT — things that do NOT change:**
- `halcyon-lab` (GitHub repo name) — leave as-is
- `halcyonlab.app` (domain) — leave as-is
- `halcyonlatest` (Ollama model name) — leave as-is
- `halcyon_lab` in Python import paths — leave as-is (there are none, but check)
- `docs/research/` filenames — leave as-is (historical research documents)
- Git history — obviously untouched

**Things that DO change:**

1. **Frontend:**
   - `frontend/public/index.html`: `<title>Halcyon Lab</title>` → `<title>Arcis</title>`
   - `frontend/public/manifest.json`: `"name": "..."` and `"short_name": "..."` → `"Arcis"`
   - `frontend/src/components/Layout.jsx`: sidebar header `HALCYON LAB` → `ARCIS`, subtitle `AI Research Desk` → `Systematic Equity Research`
   - All page titles or breadcrumbs referencing "Halcyon"
   - `frontend/src/pages/Roadmap.jsx`: any "Halcyon" references in roadmap items

2. **Backend:**
   - `src/notifications/telegram.py`: any messages mentioning "Halcyon Lab" → "Arcis"
   - `src/scheduler/watch.py`: log messages if any mention "Halcyon"
   - `halcyon.log` filename → `arcis.log` (in watch.py RotatingFileHandler)

3. **Documentation:**
   - `README.md`: title and description
   - `AGENTS.md`: header and description
   - `CHANGELOG.md`: project name in header
   - `docs/architecture.md`: title and references
   - `docs/roadmap.md` and `docs/roadmap-complete.md`
   - Any other `.md` files in `docs/` that reference "Halcyon Lab" as a display name

**Search commands to verify completeness:**
```bash
# Find all remaining "Halcyon" references (case-insensitive)
grep -ri "halcyon" --include="*.py" --include="*.jsx" --include="*.js" --include="*.json" --include="*.html" --include="*.css" --include="*.md" --include="*.yaml" . | grep -v node_modules | grep -v __pycache__ | grep -v ".git/" | grep -v "docs/research/" | grep -v "halcyon-lab" | grep -v "halcyonlab.app" | grep -v "halcyonlatest"
# Should return empty (or only historical research doc content)
```

---

## Task 2: Replace CSS Color System with Palette H

**Goal:** Replace the entire `:root` color system in `frontend/src/index.css` with the Arcis Palette H variables.

Replace the current `:root` block with:

```css
:root, [data-theme="dark"] {
  /* Arcis Palette H: Electric Focus — Dark Mode (default) */
  --arcis-bg-primary: #050507;
  --arcis-bg-surface: #0C0C10;
  --arcis-bg-elevated: #12121A;
  --arcis-accent: #3B82F6;
  --arcis-accent-hover: #2563EB;
  --arcis-accent-muted: rgba(37, 99, 235, 0.08);
  --arcis-text-primary: #E4E4E7;
  --arcis-text-secondary: #A1A1AA;
  --arcis-text-muted: #52525B;
  --arcis-border: rgba(37, 99, 235, 0.08);
  --arcis-border-hover: rgba(37, 99, 235, 0.15);

  /* Semantic (shared) */
  --arcis-success: #22C55E;
  --arcis-danger: #EF4444;
  --arcis-warning: #F59E0B;
  --arcis-teal: #0D9488;
  --arcis-teal-light: #14B8A6;
  --arcis-info: #3B82F6;

  /* Chart series */
  --chart-1: #3B82F6; --chart-2: #14B8A6; --chart-3: #F59E0B;
  --chart-4: #A78BFA; --chart-5: #FB7185; --chart-6: #22D3EE;
  --chart-7: #FBBF24; --chart-8: #E879F9;

  /* Typography */
  --font-display: 'Inter', system-ui, sans-serif;
  --font-body: 'Inter', system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', 'SF Mono', monospace;

  /* Layout */
  --radius-sm: 4px; --radius-md: 6px; --radius-lg: 8px; --radius-xl: 12px;
}

[data-theme="light"] {
  --arcis-bg-primary: #F8FAFC;
  --arcis-bg-surface: #FFFFFF;
  --arcis-bg-elevated: #F1F5F9;
  --arcis-accent: #2563EB;
  --arcis-accent-hover: #1D4ED8;
  --arcis-accent-muted: rgba(37, 99, 235, 0.06);
  --arcis-text-primary: #0F172A;
  --arcis-text-secondary: #475569;
  --arcis-text-muted: #64748B;
  --arcis-border: #E2E8F0;
  --arcis-border-hover: #CBD5E1;
}
```

Update `body` styles:
```css
body {
  margin: 0;
  background: var(--arcis-bg-primary);
  color: var(--arcis-text-primary);
  font-family: var(--font-body);
  font-size: 14px;
  line-height: 20px;
}
```

Keep the `.financial-data` class unchanged — it's already correct.

Remove the old `--teal-*`, `--amber-*`, `--slate-*` variables entirely. Also remove `--font-display: 'Space Grotesk'` — it's replaced by Inter.

Remove Space Grotesk from the Google Fonts import URL in index.css (Inter and JetBrains Mono are already imported).

---

## Task 3: Update Font Imports

The current Google Fonts import in `frontend/src/index.css` already loads Inter and JetBrains Mono. **Remove Space Grotesk** from the import since we no longer use it:

Change:
```css
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=Inter:wght@100..900&family=JetBrains+Mono:wght@100..800&display=swap');
```
To:
```css
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');
```

This reduces the font payload significantly (only weights we actually use).

---

## Task 4: Dark/Light Mode Toggle

**Goal:** Add a theme toggle to the nav sidebar that switches between dark (default) and light mode.

Create `frontend/src/components/ThemeToggle.jsx`:
```jsx
import { useState, useEffect } from 'react'
import { Sun, Moon } from 'lucide-react'

export default function ThemeToggle() {
  const [theme, setTheme] = useState(() => {
    return localStorage.getItem('arcis-theme') || 'dark'
  })

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('arcis-theme', theme)
  }, [theme])

  return (
    <button
      onClick={() => setTheme(t => t === 'dark' ? 'light' : 'dark')}
      style={{
        background: 'transparent',
        border: '1px solid var(--arcis-border)',
        borderRadius: 'var(--radius-md)',
        color: 'var(--arcis-text-secondary)',
        padding: '6px',
        cursor: 'pointer',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
      title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
    >
      {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
    </button>
  )
}
```

Wire into `Layout.jsx` — place the toggle in the sidebar header area, next to the "ARCIS" text or in the top bar.

Also add initialization in `App.jsx` or `index.jsx` to set the data-theme attribute on load:
```jsx
// Set initial theme before React renders to prevent flash
const savedTheme = localStorage.getItem('arcis-theme') || 'dark'
document.documentElement.setAttribute('data-theme', savedTheme)
```

---

## Task 5: Apply Palette to All 13 Dashboard Pages

**Goal:** Replace every hardcoded color and old CSS variable reference with the new `--arcis-*` variables across all page files.

This is the largest task. Here is the mapping:

| Old Reference | New Reference |
|---|---|
| `var(--slate-800)`, `var(--slate-900)`, `#0F172A`, `#020617` | `var(--arcis-bg-primary)` |
| `var(--slate-700)`, `#1E293B` | `var(--arcis-bg-surface)` |
| `var(--slate-600)`, `#334155` | `var(--arcis-bg-elevated)` |
| `var(--teal-400)`, `var(--teal-500)`, `var(--teal-600)`, `#0D9488`, `#14B8A6`, `#2DD4BF` | `var(--arcis-accent)` for primary accent; `var(--arcis-teal)` when specifically teal-colored |
| `var(--slate-50)`, `var(--slate-100)`, `#F8FAFC`, `#E2E8F0` | `var(--arcis-text-primary)` |
| `var(--slate-300)`, `var(--slate-400)`, `#94A3B8`, `#64748B` | `var(--arcis-text-secondary)` |
| `var(--slate-500)`, `#475569` | `var(--arcis-text-muted)` |
| `var(--success)`, `var(--bullish)`, `#10B981`, `#22C55E`, `#1D9E75` | `var(--arcis-success)` |
| `var(--danger)`, `var(--bearish)`, `#EF4444` | `var(--arcis-danger)` |
| `var(--warning)`, `#F59E0B` | `var(--arcis-warning)` |
| `var(--info)`, `#3B82F6` | `var(--arcis-info)` |
| `border-[var(--slate-600)]` | `border` with `var(--arcis-border)` |

**Files to update (all in `frontend/src/`):**
- `components/Layout.jsx` — sidebar bg, nav active state, border colors, header colors
- `components/StatusBadge.jsx` — badge colors
- `components/AuthGate.jsx` — form styling
- `pages/Dashboard.jsx`
- `pages/ShadowLedger.jsx`
- `pages/LiveLedger.jsx`
- `pages/Council.jsx`
- `pages/Health.jsx`
- `pages/Training.jsx`
- `pages/CTOReport.jsx`
- `pages/Packets.jsx`
- `pages/Notes.jsx`
- `pages/Roadmap.jsx`
- `pages/Settings.jsx`
- `pages/Docs.jsx`
- `pages/Validation.jsx`

**Special attention to `Layout.jsx`:**
- Sidebar background: `bg-[var(--slate-900)]` → `bg-[var(--arcis-bg-primary)]`
- Sidebar border: `border-[var(--slate-600)]` → `border-[var(--arcis-border)]`
- Header: `HALCYON LAB` in teal-400 → `ARCIS` in `var(--arcis-accent)`
- Active nav item: `bg-[var(--teal-900)]/40` → `bg-[var(--arcis-accent-muted)]`
- Nav text colors: update to `--arcis-text-*` variables

**Verify after completion:**
```bash
# Should return NO results for old variable names
grep -r "var(--teal-\|var(--amber-\|var(--slate-\|var(--font-display)" frontend/src/ --include="*.jsx" --include="*.js" --include="*.css" | grep -v node_modules
```

---

## Task 6: Update package.json, manifest.json, PWA Meta Tags

**`frontend/package.json`:**
- `"name"` → `"arcis-dashboard"`

**`frontend/public/manifest.json`:**
- `"name"` → `"Arcis"`
- `"short_name"` → `"Arcis"`
- `"theme_color"` → `"#050507"`
- `"background_color"` → `"#050507"`

**`frontend/public/index.html`:**
- `<title>` → `Arcis`
- `<meta name="theme-color">` → `#050507`
- `<meta name="description">` → `Arcis — Systematic Equity Research`

---

## Task 7: Wire secrets through .env (eliminate YAML secrets friction)

A `.env.example` already exists in the repo root with all secret keys.
The pattern: `settings.yaml` is committed with NO secrets (just non-secret config).
All secrets load from `.env` via `python-dotenv` or `os.environ`.

Steps:
1. `pip install python-dotenv` and add to requirements.txt
2. In `src/main.py` (or a shared config loader), add at the very top:
   ```python
   from dotenv import load_dotenv
   load_dotenv()
   ```
3. Ensure ALL secret references go through `os.environ.get()`:
   - `src/shadow_trading/alpaca_adapter.py` — already does this ✓
   - `src/council/protocol.py` — needs `ANTHROPIC_API_KEY` from env
   - `src/data_collection/finnhub_collector.py` — needs `FINNHUB_API_KEY` from env
   - `src/data_collection/fred_collector.py` — needs `FRED_API_KEY` from env
   - `src/notifications/telegram.py` — needs `TELEGRAM_BOT_TOKEN` from env
   - `src/notifications/email_notifier.py` — needs `EMAIL_PASSWORD` from env
   - `src/api/cloud_app.py` — already does this for API_SECRET ✓
4. Remove secret values from `config/settings.example.yaml` — replace with comments like:
   ```yaml
   # api_key: loaded from ALPACA_API_KEY env var (see .env.example)
   ```
5. Keep ALL non-secret config in `settings.yaml` (thresholds, intervals, feature flags, etc.)

After this change, `settings.yaml` can be committed freely and stays in sync.
Only `.env` (gitignored) holds secrets.

---

## Task 8: Create API Endpoint Stubs

Add two new stub endpoints. These will be replaced with real implementations in Sprint 4B, but the frontend needs them to exist now.

**In `src/api/cloud_routes/analytics.py`** (or create a new file if it's cleaner):

```python
@router.get("/api/build-score")
async def get_build_score():
    """Build Score composite KPI — stub, replaced in Sprint 4B."""
    return {
        "build_score": 0,
        "delta_7d": 0,
        "components": {
            "gate_velocity": 0,
            "system_health": 0,
            "data_asset_value": 0,
            "model_quality": 0,
            "research_velocity": 0,
            "reliability": 0,
        },
        "data_asset_detail": {"quality": 0, "diversity": 0, "freshness": 0},
        "phase_progress": {
            "current_phase": 1,
            "trades_closed": 0,
            "trades_required": 50,
            "pct_complete": 0,
            "estimated_weeks_remaining": 0,
        },
        "decay_today": False,
        "history_7d": [],
    }


@router.get("/api/traffic-light/current")
async def get_traffic_light_current():
    """Current Traffic Light regime — stub, replaced in Sprint 4B."""
    return {"regime": "UNKNOWN", "score": 0, "vix": 0}
```

Ensure these routes are included in the router that `cloud_app.py` imports.

**In `frontend/src/api.js`**, add methods:
```javascript
getBuildScore: () => fetchApi('/build-score'),
getTrafficLightCurrent: () => fetchApi('/traffic-light/current'),
```

---

## Task 9: Documentation Update (MANDATORY)

Update the following files to reflect all changes made in this sprint:

1. **AGENTS.md** — Verify ALL counts match reality:
```bash
echo "Python files:" && find src -name "*.py" ! -path "*__pycache__*" | wc -l
echo "Test files:" && find tests -name "*.py" | wc -l
echo "Tests:" && find tests -name "*.py" -exec grep -c "def test_" {} + | awk -F: '{s+=$2}END{print s}'
echo "Dashboard pages:" && ls frontend/src/pages/*.jsx | wc -l
echo "Research docs:" && ls docs/research/*.md docs/research/*.pdf 2>/dev/null | wc -l
```

2. **CHANGELOG.md** — Add Sprint 4A entry:
```markdown
## Sprint 4A: Arcis Brand Infrastructure (YYYY-MM-DD)
- Rebranded from "Halcyon Lab" to "Arcis" across entire codebase
- Applied Palette H (Electric Focus) — dark mode default with light mode toggle
- Replaced Space Grotesk with Inter for all display text
- Added dark/light mode toggle with localStorage persistence
- Created API stubs for Build Score and Traffic Light endpoints
- Updated PWA manifest, meta tags, and package.json
```

3. **docs/architecture.md** — Update if module structure changed

4. **README.md** — Update project name and description

---

## Final Verification

Run these commands at the end of the sprint:

```bash
# 1. No old Halcyon references (excluding repo name, domain, model name, research docs)
grep -ri "halcyon" --include="*.py" --include="*.jsx" --include="*.js" --include="*.json" --include="*.html" --include="*.css" . | grep -v node_modules | grep -v __pycache__ | grep -v ".git/" | grep -v "docs/research/" | grep -v "halcyon-lab" | grep -v "halcyonlab.app" | grep -v "halcyonlatest" | grep -v "docs/sprints/" | grep -v "docs/roadmap"

# 2. No old CSS variable references
grep -r "var(--teal-\|var(--amber-\|var(--slate-\|Space.Grotesk" frontend/src/ --include="*.jsx" --include="*.js" --include="*.css" | grep -v node_modules

# 3. Frontend builds
cd frontend && npm run build && cd ..

# 4. All tests pass
python -m pytest tests/ -x -q

# 5. Test count hasn't decreased
find tests -name "test_*.py" -exec grep -c "def test_" {} + | awk -F: '{s+=$2}END{print "Tests:", s}'
# Must be ≥ 1083
```

---

## Sprint Checklist

Paste the contents of `docs/sprint-checklist.md` here and complete every applicable item before marking this sprint done.
