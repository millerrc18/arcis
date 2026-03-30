# Sprint 4A: Arcis Brand Infrastructure (Codex)

> **Executor:** Codex (mechanical, well-specified tasks)
> **Estimated scope:** 8 tasks, ≤10 files touched per task
> **Merge before:** Sprint 4B (CC builds on top of this)
> **Codebase guardrails:** No src/ file over 400 lines. No function over 60 lines. Run checks BEFORE starting.

## Context

You are working on halcyon-lab, an autonomous AI-powered equity trading system.
The system is being rebranded from "Halcyon Lab" to "Arcis" (Latin for fortress).
The dashboard palette is being changed to "Electric Focus" (Palette H).
The dashboard is a React 18 app in `frontend/` served via Render.

**Brand decisions (all finalized):**
- Name: Arcis (Adaptive Regime Classification & Intelligence Systems)
- Palette H: True black + electric blue
  - Dark mode (default): Background #050507, Surface #0C0C10, Accent #3B82F6, Text #E4E4E7, Muted #52525B
  - Light mode: Background #F8FAFC, Surface #FFFFFF, Accent #2563EB, Text #0F172A, Muted #64748B
  - Card borders: 1px solid rgba(37, 99, 235, 0.08) dark / 1px solid #E2E8F0 light
  - Shared semantic: Success #22C55E, Danger #EF4444, Warning #F59E0B
  - Secondary accent: Teal #0D9488 (for Build Score, HSHS)
- Typography: Inter (Google Fonts variable, all weights) + JetBrains Mono (financial data)
- Dashboard visual hierarchy:
  - H1 (page title): Inter ExtraBold 800, 24px, -0.03em
  - H2 (section): Inter SemiBold 600, 18px, -0.02em
  - Body: Inter Regular 400, 14px, line-height 20px
  - UI Label: Inter Medium 500, 11px, 0.04em tracking, uppercase
  - KPI number: Inter Bold 700, 28px, tabular-nums
  - Financial data: JetBrains Mono Regular 400, 13px, tabular-nums, slashed-zero
  - Ticker symbol: JetBrains Mono Medium 500, 12px, uppercase

## Pre-sprint checks

Run these BEFORE starting any tasks:

```bash
# File size guardrail
find src -name "*.py" ! -path "*__pycache__*" -exec sh -c 'lines=$(wc -l < "$1"); if [ "$lines" -gt 400 ]; then echo "VIOLATION: $1 ($lines lines)"; fi' _ {} \;

# Function length guardrail
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

# Current test count
find tests -name "test_*.py" -exec grep -c "def test_" {} + | awk -F: '{s+=$2}END{print "Tests:", s}'
```

Fix any violations BEFORE starting feature work.

---

## Tasks

### Task 1: Rename Halcyon Lab → Arcis across entire codebase

Search and replace all occurrences. Be careful with:
- `halcyon-lab` (repo name) → leave as-is (GitHub repo won't change yet)
- `halcyonlab.app` (domain) → leave as-is (domain won't change yet)
- `halcyonlatest` (Ollama model name) → leave as-is (model won't change yet)
- `halcyon.log` → rename to `arcis.log`
- `Halcyon Lab` / `HALCYON` / `Halcyon` (display name) → `Arcis` / `ARCIS` / `Arcis`
- Comments, docstrings, page titles, README, CHANGELOG → update to Arcis
- `<title>` tags in frontend → Arcis
- Telegram bot messages → "Arcis" not "Halcyon"

Files to check: `frontend/public/index.html`, `frontend/src/App.jsx`, all `frontend/src/pages/*.jsx`,
`src/notifications/telegram.py`, `README.md`, `AGENTS.md`, `CHANGELOG.md`, `docs/*.md`,
`frontend/public/manifest.json`, `frontend/src/config.js`

### Task 2: Create Tailwind CSS custom properties for Palette H

Create `frontend/src/styles/arcis-theme.css`:

```css
:root {
  /* Palette H: Electric Focus */
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
  --arcis-success: #22C55E;
  --arcis-danger: #EF4444;
  --arcis-warning: #F59E0B;
  --arcis-teal: #0D9488;
  --arcis-teal-light: #14B8A6;
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

/* Financial data styling */
.financial-data {
  font-variant-numeric: tabular-nums lining-nums;
  font-feature-settings: "tnum" 1, "lnum" 1;
}
```

Import this in `frontend/src/index.css` or `App.jsx`.

### Task 3: Add Inter + JetBrains Mono fonts

Add Google Fonts imports to `frontend/public/index.html`:

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
```

Update Tailwind config (`tailwind.config.js`) to use Inter as the default sans font and JetBrains Mono as the mono font.

### Task 4: Dark/light mode toggle

Create `frontend/src/components/ThemeToggle.jsx`:
- Read initial theme from `localStorage.getItem('arcis-theme')` or default to `'dark'`
- Set `data-theme` attribute on `<html>` element
- Toggle button (sun/moon icon from lucide-react) in the top nav
- Persist choice to localStorage

Wire into the main layout (App.jsx or wherever the nav lives).

### Task 5: Apply palette to all existing dashboard pages

Replace the current color system (teal-600, navy backgrounds, etc.) with the new CSS custom properties across all 13 pages:
- Background: `var(--arcis-bg-primary)`
- Cards: `var(--arcis-bg-surface)` with `border: 1px solid var(--arcis-border)`
- Text: `var(--arcis-text-primary)`, `var(--arcis-text-secondary)`, `var(--arcis-text-muted)`
- Accent: `var(--arcis-accent)`
- P&L green: `var(--arcis-success)`, P&L red: `var(--arcis-danger)`

This is a find-and-replace across all JSX files. Every hardcoded color should reference a CSS variable.

### Task 6: Update package.json, manifest.json, PWA meta tags

- `frontend/package.json`: name → "arcis-dashboard"
- `frontend/public/manifest.json`: name → "Arcis", short_name → "Arcis", theme_color → "#050507"
- `frontend/public/index.html`: `<title>Arcis</title>`, meta theme-color → "#050507"
- Favicon: update background color if it references teal (the actual icon design stays — logo is pending)

### Task 7: Create API endpoint stubs

Add to `src/api/cloud_routes/analytics.py` (or a new file):

```python
@router.get("/api/build-score")
async def get_build_score():
    """Build Score composite KPI — stub for Sprint 4B implementation."""
    return {
        "build_score": 0,
        "delta_7d": 0,
        "components": {
            "gate_velocity": 0, "system_health": 0, "data_asset_value": 0,
            "model_quality": 0, "research_velocity": 0, "reliability": 0
        },
        "phase_progress": {"current_phase": 1, "trades_closed": 0, "trades_required": 50}
    }

@router.get("/api/traffic-light/current")
async def get_traffic_light_current():
    """Current Traffic Light regime — stub for Sprint 4B implementation."""
    return {"regime": "UNKNOWN", "score": 0, "vix": 0}
```

Wire into `cloud_app.py` router includes. Add corresponding methods to `frontend/src/api.js`.

### Task 8: Documentation update (MANDATORY)

- Update AGENTS.md with all current counts (run verification commands)
- Update CHANGELOG.md with Sprint 4A entry
- Update architecture.md if module structure changed
- Update README.md with new brand name
- Verify all counts match code reality

---

## Sprint Checklist (MANDATORY)

Paste the contents of `docs/sprint-checklist.md` here and complete every applicable item.
Run all verification commands before marking the sprint complete.
