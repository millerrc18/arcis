# Sprint 4A: Arcis Brand Infrastructure (Codex)
# Mechanical changes — rename, theme, fonts, API stubs.
# Fire to Codex. Fresh session. After Sprint 3 merges.

> **CONTEXT:** Arcis (formerly Halcyon Lab) is an autonomous AI-powered equity
> trading system. This sprint renames the entire codebase from "Halcyon Lab"
> to "Arcis" and applies the new visual identity. All changes are mechanical
> find-and-replace, CSS variable definitions, and boilerplate API endpoints.
> NO complex logic. NO component redesigns. Those are Sprint 4B (CC).
>
> **BRAND DECISIONS (final):**
> - Name: Arcis (Latin for fortress, backronym: Adaptive Regime Classification & Intelligence Systems)
> - Palette: B (Technical Sophistication) — deep indigo + teal + cyan
> - Typography: Inter (headings/body/UI) + JetBrains Mono (financial data/tickers)
> - Dashboard mode: Dark mode default with light mode toggle
> - Voice: "AI-informed", "systematic", "research-driven" (SEC-safe)

---

## Pre-read:
```
cat AGENTS.md
cat frontend/src/App.jsx
cat frontend/src/config.js
cat frontend/src/index.css
cat frontend/public/manifest.json
cat frontend/public/index.html
cat package.json
cat README.md
```

## Task 1: Rename "Halcyon Lab" → "Arcis" across entire codebase

Search and replace ALL instances. Be case-sensitive and thorough:

```
"Halcyon Lab" → "Arcis"
"halcyon-lab" → "arcis" (in prose/docs only — DO NOT rename the git repo or directory)
"halcyon_lab" → "arcis"
"Halcyon" → "Arcis" (when referring to the product, NOT in research doc filenames or git history)
"HALCYON" → "ARCIS"
"halcyonlatest" → leave as-is (this is the Ollama model name on Ryan's machine)
"halcyonlab.app" → leave as-is (this is the live domain)
```

Files to check (not exhaustive):
- README.md
- AGENTS.md
- CHANGELOG.md
- frontend/public/index.html (title, meta tags)
- frontend/public/manifest.json (name, short_name)
- frontend/src/App.jsx (any brand text)
- frontend/src/pages/*.jsx (any brand text in headers, footers)
- frontend/public/architecture-letter.html
- docs/*.md (update references in prose)
- src/notifications/telegram.py (bot messages)
- src/api/cloud_app.py and cloud_routes/*.py (API response headers if any)
- config/settings.example.yaml (comments)

**DO NOT rename:**
- The GitHub repo (stays millerrc18/halcyon-lab for now)
- The directory name on disk
- The Ollama model name (halcyonlatest)
- The domain (halcyonlab.app)
- Research document filenames in docs/research/
- Git history

## Task 2: Add Inter + JetBrains Mono fonts

In `frontend/public/index.html`, add Google Fonts preconnect and stylesheet:
```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
```

In `frontend/src/index.css` (or global Tailwind config), set:
```css
:root {
  --font-sans: 'Inter', system-ui, -apple-system, sans-serif;
  --font-mono: 'JetBrains Mono', 'Fira Code', monospace;
}

body {
  font-family: var(--font-sans);
  -webkit-font-smoothing: antialiased;
}

.financial-data, .ticker, .price, .mono {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums lining-nums;
  font-feature-settings: "tnum" 1, "lnum" 1;
}
```

## Task 3: Define Palette B CSS custom properties

Create or update `frontend/src/theme.css` with the complete Palette B color system:

```css
/* Palette B: Technical Sophistication — Arcis */
:root {
  /* Dark mode (default) */
  --bg-primary: #0B1120;
  --bg-surface: #141B2D;
  --bg-elevated: #1A2236;
  --bg-hover: #1E2940;

  --color-primary: #14B8A6;      /* Teal */
  --color-primary-dim: #0D9488;  /* Teal darker */
  --color-secondary: #1E1B4B;    /* Deep Indigo */
  --color-accent: #06B6D4;       /* Cyan */

  --text-primary: #ECFDF5;
  --text-secondary: #CBD5E1;
  --text-muted: #94A3B8;
  --text-dim: #64748B;

  --border-default: rgba(255, 255, 255, 0.08);
  --border-hover: rgba(255, 255, 255, 0.15);

  --profit: #22C55E;
  --loss: #EF4444;
  --warning: #F59E0B;
  --neutral: #9CA0AE;

  /* Chart colors (8, colorblind-safe) */
  --chart-1: #14B8A6;  /* Teal */
  --chart-2: #3B82F6;  /* Blue */
  --chart-3: #F59E0B;  /* Amber */
  --chart-4: #A78BFA;  /* Violet */
  --chart-5: #FB7185;  /* Rose */
  --chart-6: #22D3EE;  /* Cyan */
  --chart-7: #FBBF24;  /* Yellow */
  --chart-8: #E879F9;  /* Fuchsia */
}

/* Light mode */
[data-theme="light"] {
  --bg-primary: #F0FDFA;
  --bg-surface: #FFFFFF;
  --bg-elevated: #F8FFFE;
  --bg-hover: #E6FAF7;

  --color-primary: #0D9488;
  --color-primary-dim: #0F766E;
  --color-secondary: #312E81;
  --color-accent: #0891B2;

  --text-primary: #134E4A;
  --text-secondary: #475569;
  --text-muted: #64748B;
  --text-dim: #94A3B8;

  --border-default: rgba(0, 0, 0, 0.08);
  --border-hover: rgba(0, 0, 0, 0.15);

  --profit: #059669;
  --loss: #DC2626;
  --warning: #D97706;
  --neutral: #6B7280;
}
```

## Task 4: Dark/light mode toggle infrastructure

Add a theme toggle component and wire it into the app:

1. Create `frontend/src/components/ThemeToggle.jsx`:
   - Reads from localStorage ('arcis-theme')
   - Applies `data-theme="light"` or `data-theme="dark"` on `<html>`
   - Defaults to dark if no preference saved
   - Simple sun/moon icon toggle

2. Wire into App.jsx layout/header area.

3. Ensure ALL existing components use CSS variables instead of hardcoded colors.
   Search for hardcoded hex values in JSX files and replace with variables:
   ```bash
   grep -rn "#[0-9a-fA-F]\{6\}" frontend/src/ --include="*.jsx" --include="*.css" | head -30
   ```

## Task 5: Create boilerplate API endpoints

Add these endpoints to `src/api/cloud_routes/analytics.py` (or new file):

```python
@router.get("/api/build-score")
async def build_score():
    """Build Score composite KPI. Returns current score + 7-day history."""
    # Stub — returns placeholder until Sprint 4B implements computation
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
        "phase_progress": {"current_phase": 1, "trades_closed": 0, "trades_required": 50},
        "message": "Build Score computation not yet implemented"
    }

@router.get("/api/traffic-light/current")
async def traffic_light_current():
    """Current Traffic Light regime state."""
    # Query traffic_light_state table
    ...

@router.get("/api/council/value-summary")
async def council_value_summary():
    """Council value attribution summary."""
    # Query council_parameter_log
    ...
```

Also add to `frontend/src/api.js`:
```javascript
getBuildScore: () => fetchApi('/api/build-score'),
getTrafficLightCurrent: () => fetchApi('/api/traffic-light/current'),
getCouncilValueSummary: () => fetchApi('/api/council/value-summary'),
```

## Task 6: Update page titles and meta tags

In `frontend/public/index.html`:
```html
<title>Arcis</title>
<meta name="description" content="Systematic equity research, built on large language models.">
```

In `frontend/public/manifest.json`:
```json
{
  "name": "Arcis",
  "short_name": "Arcis",
  "description": "Systematic equity research, built on large language models."
}
```

## Task 7: Apply theme variables to existing components

For every `.jsx` file in `frontend/src/pages/` and `frontend/src/components/`:
- Replace hardcoded background colors with `var(--bg-surface)` or `var(--bg-primary)`
- Replace hardcoded text colors with `var(--text-primary)`, `var(--text-secondary)`, etc.
- Replace hardcoded green/red with `var(--profit)` / `var(--loss)`
- Replace hardcoded teal with `var(--color-primary)`
- Add `font-family: var(--font-mono)` to any element showing prices, P&L, tickers, or numerical data

This is mechanical find-and-replace across ~15 JSX files.

## Task 8: Update Telegram bot messages

In `src/notifications/telegram.py`, replace any "Halcyon" references in bot messages:
- "🏛️ AI COUNCIL SESSION" → keep as-is (no brand name in this message)
- Any "Halcyon Lab" in notification text → "Arcis"

## Task 9: All tests pass + frontend builds

```bash
python -m pytest tests/ -v --tb=short
cd frontend && npm run build && cd ..
```

## Task 10: Documentation update

- AGENTS.md: update brand references
- CHANGELOG.md: add Sprint 4A entry
- README.md: update project name and description
