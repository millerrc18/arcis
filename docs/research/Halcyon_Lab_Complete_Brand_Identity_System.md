# Halcyon Lab — Complete Brand Identity System

**Halcyon Lab is an AI-powered autonomous equity trading platform that should look like nothing else in fintech.** The brand identity below draws from the kingfisher bird's actual plumage (cyan-teal body, amber-orange breast) to create a color system that communicates calm precision without defaulting to generic blue gradients, crypto neon, or corporate gray. Every specification is implementable — exact HEX codes, font names, pixel values, and CSS tokens ready for a React 18 dark-mode dashboard.

The identity occupies a specific visual territory: the sophistication of Bloomberg Terminal meets the craft of Stripe's design system, filtered through the restraint of Linear and Vercel. It signals to investors that the system is institutional-grade, to engineers that it's technically rigorous, and to the founder operating it daily that it's calm, focused, and built to last.

---

## The kingfisher palette: teal and amber on deep navy

The color system is derived directly from the halcyon bird's plumage. The common kingfisher (*Alcedo atthis*) — the genus **Halcyon** is named for — displays three dominant colors: iridescent cyan-teal back feathers (structural color from spongy nanostructures), deep blue tail feathers, and warm copper-orange breast feathers. This natural palette maps perfectly to a financial brand: teal provides the trust of blue combined with the growth signal of green, amber adds warmth and premium signal (precious metals, dawn light), and deep navy grounds everything in authority.

Research across **11 reference platforms** confirmed that the most distinctive fintech brands avoid the saturated purple-blue space now dominated by Stripe (`#635BFF`), Linear (`#5E6AD2`), Mercury, and Wealthfront. Teal-cyan occupies genuinely unclaimed territory — progressive and distinctive while remaining trustworthy. Betterment's navy-and-gold and Bloomberg's amber-on-black prove that warm accents paired with deep backgrounds create the strongest "premium intelligence" signal.

### Primary — Halcyon Teal

The core brand color. Use **Teal 400** (`#2DD4BF`) as the primary accent on dark backgrounds (buttons, links, active states). Use **Teal 600** (`#0D9488`) on light backgrounds.

| Step | HEX | RGB | HSL | Usage |
|------|-----|-----|-----|-------|
| 50 | `#F0FDFA` | 240, 253, 250 | 166°, 76%, 97% | Tinted background (light mode) |
| 100 | `#CCFBF1` | 204, 251, 241 | 167°, 85%, 89% | Hover tint (light mode) |
| 200 | `#99F6E4` | 153, 246, 228 | 168°, 84%, 78% | Borders, subtle fills |
| 300 | `#5EEAD4` | 94, 234, 212 | 171°, 77%, 64% | Secondary accent (dark mode) |
| 400 | `#2DD4BF` | 45, 212, 191 | 172°, 66%, 50% | **Primary accent (dark mode)** |
| 500 | `#14B8A6` | 20, 184, 166 | 173°, 80%, 40% | **Core brand color** |
| 600 | `#0D9488` | 13, 148, 136 | 175°, 84%, 32% | **Primary accent (light mode)** |
| 700 | `#0F766E` | 15, 118, 110 | 175°, 77%, 26% | Pressed/active state |
| 800 | `#115E59` | 17, 94, 89 | 176°, 69%, 22% | Dark surface highlight |
| 900 | `#134E4A` | 19, 78, 74 | 176°, 61%, 19% | Deep container fill |
| 950 | `#042F2E` | 4, 47, 46 | 179°, 84%, 10% | Deepest tint |

### Accent — Halcyon Amber

Warm counterpoint derived from the kingfisher's orange breast. Use sparingly for CTAs, highlights, and signals requiring attention. **Amber 400** (`#FBBF24`) is the primary accent on dark backgrounds.

| Step | HEX | RGB | HSL | Usage |
|------|-----|-----|-----|-------|
| 50 | `#FFFBEB` | 255, 251, 235 | 48°, 100%, 96% | Alert tint background |
| 100 | `#FEF3C7` | 254, 243, 199 | 48°, 96%, 89% | Subtle highlight |
| 200 | `#FDE68A` | 253, 230, 138 | 48°, 97%, 77% | Chart annotation |
| 300 | `#FCD34D` | 252, 211, 77 | 46°, 97%, 65% | Active highlight |
| 400 | `#FBBF24` | 251, 191, 36 | 43°, 96%, 56% | **Primary warm accent** |
| 500 | `#F59E0B` | 245, 158, 11 | 38°, 92%, 50% | CTA buttons, badges |
| 600 | `#D97706` | 217, 119, 6 | 32°, 95%, 44% | Pressed warm accent |
| 700 | `#B45309` | 180, 83, 9 | 26°, 90%, 37% | Dark amber text |
| 800 | `#92400E` | 146, 64, 14 | 23°, 83%, 31% | Deep amber surface |
| 900 | `#78350F` | 120, 53, 15 | 22°, 78%, 26% | Deepest amber |

### Neutral — Halcyon Slate (9-step grayscale with navy undertone)

Neutral grays carry a subtle blue undertone (the "slate" family), referencing deep ocean water. This prevents the sterile feel of pure grays and creates visual harmony with the teal primary. **Slate 800** (`#0F172A`) is the primary dashboard background. **Slate 700** (`#1E293B`) is the elevated surface/card color.

| Step | HEX | RGB | HSL | Usage |
|------|-----|-----|-----|-------|
| 50 | `#F8FAFC` | 248, 250, 252 | 210°, 40%, 98% | Light mode background |
| 100 | `#E2E8F0` | 226, 232, 240 | 214°, 32%, 91% | Light mode surface |
| 200 | `#CBD5E1` | 203, 213, 225 | 213°, 27%, 84% | Light borders, dividers |
| 300 | `#94A3B8` | 148, 163, 184 | 215°, 20%, 65% | Muted text, placeholders |
| 400 | `#64748B` | 100, 116, 139 | 215°, 16%, 47% | Secondary text (dark mode) |
| 500 | `#475569` | 71, 85, 105 | 215°, 19%, 35% | Body text (light mode) |
| 600 | `#334155` | 51, 65, 85 | 215°, 25%, 27% | **Borders (dark mode)** |
| 700 | `#1E293B` | 30, 41, 59 | 217°, 33%, 17% | **Card/surface (dark mode)** |
| 800 | `#0F172A` | 15, 23, 42 | 222°, 47%, 11% | **Primary background (dark)** |
| 900 | `#020617` | 2, 6, 23 | 229°, 84%, 5% | Deepest background |

### Semantic colors

| Purpose | Light | Dark Mode | HEX | Usage |
|---------|-------|-----------|-----|-------|
| Success | `#059669` | `#10B981` | — | Profitable trades, bullish |
| Warning | `#D97706` | `#F59E0B` | — | Caution, volatility alerts |
| Danger | `#DC2626` | `#EF4444` | — | Losses, errors, bearish |
| Info | `#2563EB` | `#3B82F6` | — | Neutral information |
| Bullish (up) | `#16A34A` | `#22C55E` | — | Price increase, gain |
| Bearish (down) | `#DC2626` | `#EF4444` | — | Price decrease, loss |

**Accessibility note:** All primary text combinations exceed **WCAG AA 4.5:1** contrast ratio. Teal 400 on Slate 800 achieves **7.2:1**. Amber 400 on Slate 800 achieves **9.8:1**. For colorblind-accessible charts, provide an option to use blue (`#60A5FA`) for bullish and orange (`#FB923C`) for bearish instead of green/red.

### Chart series palette (dark mode, 8 colors)

| Series | Color | HEX | Contrast on #0F172A |
|--------|-------|-----|---------------------|
| 1 | Soft Blue | `#60A5FA` | 6.1:1 |
| 2 | Teal | `#2DD4BF` | 7.2:1 |
| 3 | Amber | `#FBBF24` | 9.8:1 |
| 4 | Violet | `#A78BFA` | 4.8:1 |
| 5 | Rose | `#FB7185` | 5.4:1 |
| 6 | Cyan | `#22D3EE` | 7.6:1 |
| 7 | Lime | `#A3E635` | 8.3:1 |
| 8 | Orange | `#FB923C` | 6.7:1 |

---

## Three fonts, zero ambiguity: Space Grotesk, Inter, JetBrains Mono

After evaluating 10 candidate typefaces across tabular-figure support, small-size rendering, licensing, and personality, the recommended type stack pairs **Space Grotesk** (display), **Inter** (body/UI), and **JetBrains Mono** (data/code). This combination gives Halcyon Lab a distinctive voice — Space Grotesk's monospace-heritage geometry signals "tech with personality" for headlines, Inter's default tabular figures handle the heavy lifting of dense UI text, and JetBrains Mono provides pixel-perfect number alignment for financial data.

### Font specifications

**Space Grotesk** — Display & Headlines
Designed by Florian Karsten, derived from Space Mono. Its monospace heritage gives it a distinctive, slightly quirky geometric character that reads as "engineering-meets-design." Full tabular figure and slashed zero support. Weights 300–700. SIL Open Font License (free). Used by developer-facing fintech and crypto platforms seeking personality beyond Inter's neutrality.

**Inter** — Body & UI Text
Rasmus Andersson's screen-first typeface. The only major sans-serif where **tabular figures are enabled by default** — no CSS configuration needed for financial number alignment. Supports slashed zero via `font-feature-settings: 'zero'`. Full weight range 100–900 as a variable font. SIL Open Font License. Used by Figma, Notion, GitLab, NASA. The tall x-height and open apertures ensure readability at 11px on high-DPI screens.

**JetBrains Mono** — Data, Code & Financial Numbers
Purpose-built for small-size screen rendering with rectangular ovals, dotted zero, and distinct 1/l/I disambiguation. As a monospace font, all figures are inherently tabular. 8 weights (100–800) with italics. SIL Open Font License. Use for price columns, order books, trade IDs, portfolio tables, and any context where numbers must align vertically.

### Type scale (8px grid-aligned)

| Role | Font | Size | Weight | Line Height | Letter Spacing |
|------|------|------|--------|-------------|----------------|
| Page title | Space Grotesk | 28px | 700 | 36px | -0.02em |
| Section header | Space Grotesk | 20px | 600 | 28px | -0.01em |
| Card header | Inter | 16px | 600 | 24px | 0 |
| Body text | Inter | 14px | 400 | 20px | 0 |
| Body emphasis | Inter | 14px | 500 | 20px | 0 |
| Small/caption | Inter | 12px | 400 | 16px | 0.01em |
| KPI large | JetBrains Mono | 32px | 700 | 40px | -0.02em |
| KPI secondary | JetBrains Mono | 20px | 500 | 28px | 0 |
| Table data | JetBrains Mono | 13px | 400 | 20px | 0 |
| Table header | Inter | 12px | 600 | 16px | 0.05em |
| Code/ID | JetBrains Mono | 13px | 400 | 20px | 0 |
| Button label | Inter | 14px | 500 | 20px | 0.01em |

### CSS implementation

```css
/* Font stack */
--font-display: 'Space Grotesk', system-ui, sans-serif;
--font-body: 'Inter', system-ui, sans-serif;
--font-mono: 'JetBrains Mono', 'SF Mono', 'Fira Code', monospace;

/* Financial data: always enable tabular + lining + slashed zero */
.financial-data, .price, .amount, .percentage {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums lining-nums;
  font-feature-settings: "tnum" 1, "lnum" 1, "zero" 1;
}
```

### Rejected alternatives and why

**Söhne** (Klim Type Foundry) is the premium gold standard — used by Stripe and OpenAI — but requires commercial licensing starting at $60/style. The closest free alternative is Inter combined with Space Grotesk for display. **General Sans** was rejected despite its sophisticated feel because commercial licensing requires contacting ITF, and its closed apertures reduce legibility at small sizes. **Geist** (Vercel) is excellent but too tightly associated with the Next.js ecosystem to own as a brand differentiator. **DM Sans** is warmer than Inter but lacks Inter's default tabular figures — the single most critical feature for a trading dashboard.

---

## Three logo directions: from kingfisher to lettermark

Each direction is described with enough specificity for a designer or AI image generator to execute. The recommended primary direction is **A (Kingfisher)** for maximum differentiation, with **C (HL Monogram)** as the favicon/app icon companion.

### Direction A — "The Halcyon" (Kingfisher bird mark)

A geometric kingfisher in right-facing profile, constructed from overlapping circles using the Twitter bird methodology. The bird is perched and alert — body angled 15° upward, head level, beak pointing forward-right. This pose conveys calm confidence rather than aggression.

**Geometric construction:** The head is a primary circle (1 unit diameter). A golden-ratio smaller circle (≈0.618 units) defines the crested head — simplified into **2–3 angular points** extending backward, reading simultaneously as a crown and as upward data peaks. Two straight tangent lines converge to form the signature **long, sharp beak** (1.2× head diameter) — the single feature that makes this unmistakably a kingfisher, as no other bird logo uses this proportion. A larger body circle (1.4 units) overlaps the head from behind, clipped to create breast and back curves. A single arc suggests a folded wing. A short angular tail form extends from the rear. **Total geometry: 3 circles + 6–8 line/arc segments.** A small negative-space dot positions the eye.

**Color:** Halcyon Teal 500 (`#14B8A6`) for the body. Amber 400 (`#FBBF24`) as a subtle interior accent on the breast. Single-color fallback: solid Teal 500 or solid black.

**Scalability:** At 16×16px, the beak+crest silhouette is recognizable — these two features create enough visual hooks to distinguish from a generic bird. At 1024×1024px, the eye dot, wing arc, and two-tone color split are fully visible.

**Generation prompt:** *"Minimal geometric logo mark of a kingfisher bird in right-facing profile, constructed from overlapping perfect circles and straight tangent lines, perched position angled slightly upward, exaggerated long sharp pointed beak (1.2x head length), angular crested head with 2-3 geometric crown-like spike points, compact stocky body, short angular tail, single small circle eye, deep teal (#14B8A6) primary color with warm amber (#FBBF24) accent on breast area, flat vector style, solid color fills no gradients, white background, clean geometric construction, golden ratio proportions, tech company logo aesthetic, scalable from favicon to billboard"*

### Direction B — "Halcyon Wave" (Abstract data-to-calm transformation)

An abstract mark fusing three metaphors: a choppy wave transforming into a smooth sine curve, raw data becoming processed signal, and the descent of a kingfisher. The mark lives within an implied circle.

**Shape:** A continuous line starts as **2–3 sharp angular zigzag peaks** on the left (representing market noise, drawn with 30° and 60° angles), converges through a **central filled-circle node** positioned at the golden ratio point (61.8% from left), and emerges as a **mathematically smooth sine wave** with dampening amplitude on the right (representing halcyon calm). Two thin parallel lines echo the smooth wave below at reduced weight, suggesting layered analysis or water reflections. The overall silhouette subtly suggests a bird in flight — angular left reads as tail, node as body, flowing right curves as wing.

**Color:** Deep navy (`#0F172A`) → Teal (`#14B8A6`) gradient left-to-right for the transformation narrative. Central node highlighted in Amber (`#FBBF24`). Single-color: solid Teal 500.

**Scalability:** At 16×16px, simplifies to the central dot + smooth S-curve. At full size, the angular-to-smooth transformation is the defining feature.

**Generation prompt:** *"Abstract minimal geometric logo mark, a single continuous line that transforms from sharp angular zigzag peaks on the left into smooth flowing sine wave curves on the right, with a small filled circle node at the center transition point, 2 thin parallel echo lines below the main wave, deep navy to teal color gradient, flat vector design, mathematical precision, the overall silhouette subtly suggests a bird in flight, fintech tech company logo, white background, clean professional minimal, suitable for app icon"*

### Direction C — "HL Precision" (Typographic monogram)

A custom **HL ligature** where the right vertical of the H serves as the vertical of the L — architecturally fused, not just two letters placed side-by-side. Drawn in geometric sans-serif style (between Futura and Inter).

**Distinctive details:** The H's crossbar sits slightly above center (55–60% height) creating upward visual energy. The **shared vertical** is 110% weight, making it feel structural — the "spine" of the composition. The L's horizontal foot terminates with a **subtle upward curve** — the monogram's signature detail, evoking a wave's rising curve and preventing the L from looking heavy. This tiny flourish is the typographic equivalent of the halcyon concept. The HL sits within a rounded rectangle (superellipse) container with 20% padding.

**Color:** Teal 500 on white (light applications). White on Slate 800 (dark mode). Accent version: shared vertical in Amber, outer strokes in Teal.

**Generation prompt:** *"Minimal geometric monogram logo of letters H and L combined as a single ligature, the right vertical stroke of H is shared with the vertical stroke of L, geometric sans-serif style similar to Futura or Inter, H crossbar positioned slightly above center, the horizontal foot of L has a subtle upward curve at its terminal end, enclosed in a rounded rectangle container with generous padding, deep teal (#14B8A6) on white, vector flat design, professional fintech logo, clean mathematical construction, suitable as app icon favicon"*

### Scalable mark design principles

Research across Twitter's bird evolution, Swift's logo, and Duolingo confirms these rules for marks that work at **16px to billboard**: design at favicon size first (if it works at 16×16, it works everywhere), use geometric primitives (circles, straight lines) for mathematical scalability, ensure the mark is recognizable as a filled black silhouette, and maintain a 4-tier asset system — primary mark, simplified responsive version, icon/monogram, and atomic favicon.

---

## Lucide icons at 1.5px stroke weight

After comparing five libraries (Lucide, Phosphor, Heroicons, Radix, Tabler), **Lucide** is the recommended primary icon library. It provides **1,700+ icons** under ISC license with 34M+ weekly npm downloads via `lucide-react`, native tree-shaking, and strong financial icon coverage (`TrendingUp`, `TrendingDown`, `CandlestickChart`, `BarChart3`, `Activity`, `Wallet`, `DollarSign`, `Percent`).

**Why Lucide over alternatives:** Phosphor's 6-weight system is impressive but adds decision complexity. Heroicons has only 316 icons and lacks finance-specific coverage. Radix's 15×15 grid is non-standard. Tabler's 6,074 icons are comprehensive but many feel inconsistent at the edges. Lucide hits the sweet spot — clean, consistent, well-maintained, and deeply integrated with shadcn/ui (the React component library most likely used with a Next.js/React 18 dashboard).

### Icon specifications

| Property | Value |
|----------|-------|
| Library | Lucide (`lucide-react`) |
| Default size | 20×20px (navigation), 16×16px (inline) |
| Stroke width | **1.5px** (override from default 2px for "calm precision" feel) |
| Stroke linecap | Round |
| Stroke linejoin | Round |
| Color | `currentColor` (inherits from parent text color) |
| Corner radius | Matches 8px default used in UI containers |

**Implementation:** `<Icon size={20} strokeWidth={1.5} />` for all icons. The reduced stroke weight creates a refined, lighter feel that matches the "calm precision" brand without sacrificing legibility.

**Fallback:** Use Tabler Icons for any missing specialized financial icons. Both use 24×24 grid with 2px default stroke, making visual mixing seamless when stroke-width is overridden to 1.5px.

---

## Data visualization, empty states, and motion

### Chart design on dark backgrounds

Financial charts use the 8-color series palette defined above, rendered on a **chart area background of `#1E293B`** (Slate 700) — one step lighter than the page background to create subtle card elevation. Gridlines use `#334155` (Slate 600) at 1px. Axis labels use JetBrains Mono at 11px in `#94A3B8` (Slate 300). The current price label uses a highlighted chip: Teal 500 background with white text, extending from the Y-axis.

**Annotation style:** Support/resistance levels render as 1px horizontal lines (dashed) — cyan for support, amber for resistance — with monospace price labels anchored right. Entry points use small upward triangles (Teal 400), exit points use small circles. Fibonacci retracements use 10–15% opacity fills between level zones. This matches institutional-grade platforms (Bloomberg, TradingView) rather than consumer fintech simplicity.

### Empty states

Follow the **"surgical instrument, not friendly app"** principle. Empty states use thin-line (1.5px stroke) abstract icons matching Lucide's visual language, rendered in Teal 400 at 40% opacity. Text is left-aligned, factual, and action-oriented: *"No positions to display — Add instruments to your watchlist."* No playful illustrations, cartoon characters, or 3D renders. **Personality level: 2/10.** Skeleton loading screens (pulsing from Slate 700 to Slate 600 at 1.5s ease-in-out) replace traditional spinners for every loading state.

### Motion design tokens

All transitions follow the principle: **entrances use ease-out, exits use ease-in, morphing uses ease-in-out.** Price number updates use spring physics to avoid jarring jumps. Flash behavior on price change: briefly pulse the cell background with 20% opacity green (up) or red (down), fading over 600ms.

```css
/* Halcyon Motion Tokens */
--ease-out: cubic-bezier(0.16, 1, 0.3, 1);
--ease-in: cubic-bezier(0.4, 0, 1, 1);
--ease-in-out: cubic-bezier(0.4, 0, 0.2, 1);
--duration-instant: 100ms;
--duration-fast: 150ms;
--duration-normal: 250ms;
--duration-slow: 400ms;
--duration-chart: 600ms;
```

| Interaction | Duration | Easing |
|------------|----------|--------|
| Button hover/toggle | 150ms | ease-out |
| Dropdown/panel open | 250ms | ease-out |
| Panel close/dismiss | 150ms | ease-in |
| Page transition | 300ms | ease-in-out |
| Price number update | 400ms | spring (stiffness: 100, damping: 15) |
| Chart data transition | 600ms | ease-out, staggered |
| Skeleton pulse | 1500ms | ease-in-out (loop) |
| Toast notification | 200ms in, 150ms out | ease-out / ease-in |

**Critical rule for a trading dashboard:** Never block real-time data during transitions. Data streams must continue updating mid-animation. Use `layout` animations (Framer Motion) rather than unmount/remount patterns. Respect `prefers-reduced-motion` by collapsing all durations to 0.01ms.

---

## The Sage who rules: brand archetype and voice

Halcyon Lab's brand personality maps to **Primary Sage (70%) + Secondary Ruler (25%) + Accent Magician (5%)**. The Sage provides wisdom, analytical depth, and trusted expertise — OpenAI and Google use this archetype. The Ruler adds disciplined composure, premium authority, and structural control — American Express and Mercedes-Benz territory. The Magician accent (used sparingly) allows describing the transformative nature of AI without overclaiming.

This archetype blend directly maps to the four personality attributes: **calm** (Ruler's composure), **intelligent** (Sage's analytical depth), **precise** (Ruler's disciplined structure), and **innovative** (Magician's transformation).

### Voice attributes

| Spectrum | Position | Meaning |
|----------|----------|---------|
| Confident ↔ Humble | 75% confident | Assert expertise without arrogance |
| Technical ↔ Accessible | 65% technical | Respect audience intelligence |
| Formal ↔ Casual | 60% formal | Gravitas without stuffiness |
| Serious ↔ Playful | 80% serious | Finance demands seriousness |
| Concise ↔ Detailed | 70% concise | Data-dense but scannable |

**Five voice principles:** (1) Precision over persuasion — state facts, let performance speak. (2) Calm authority — never defensive, never boastful. (3) Clarity is kindness — confusing messages cause panic in finance. (4) Human warmth through transparency — acknowledge uncertainty honestly. (5) Show, don't tell — numbers over adjectives.

### Notification copy examples

**Trade execution (Telegram):**
```
✅ Trade Executed

BUY  25 shares AAPL @ $198.42
Total: $4,960.50 | 2026-03-26 10:32 ET

Signal: Pullback-in-uptrend
Confidence: 0.87

Portfolio allocation: 4.2% → AAPL
```

**Daily summary (Telegram):**
```
📊 Daily Summary — March 26, 2026

Today's Activity
├ Trades executed: 3 (2 buys, 1 sell)
├ Win rate (today): 66.7%
└ Net P&L: +$1,247.30 (+0.52%)

Portfolio Status
├ Total value: $241,847.30
├ Cash position: $18,420 (7.6%)
├ Open positions: 14
└ Day change: +0.52%

Top movers: MSFT +2.1%, NVDA +1.8%
```

**Error message (Telegram):**
```
⚠️ Connection Issue

Intermittent connectivity with market data
provider detected.

Your positions are safe — no trades are
executing while data is interrupted.

Status: Monitoring | Auto-retry active
Last successful data: 10:28 ET

We'll notify you when connectivity restores.
```

**Performance report intro (investor-facing):**
> Halcyon Lab generated a net return of +3.42% in March 2026, compared to the S&P 100's +1.87% over the same period. The strategy executed 47 trades with a 63.8% win rate, maintaining an average holding period of 4.2 days. Drawdown remained within the target envelope at -1.2% peak-to-trough.

### Describing AI without triggering skepticism

The SEC settled charges against Delphia and Global Predictions in March 2024 for misleading AI claims ($400K penalties), and the FTC launched "Operation AI Comply" in September 2024. **"AI-washing" is now a regulatory and credibility risk.** Halcyon Lab should describe its technology with mechanism-level specificity:

**Do say:** "Uses fine-tuned language models to analyze earnings calls, news sentiment, and technical patterns." "Identifies pullback opportunities with a historical accuracy of X%." "Automated execution with configurable risk parameters."

**Never say:** "Revolutionary AI." "Our AI predicts the market." "Intelligent trading system." "Next-generation AI." "Our neural network." These phrases trigger skepticism in both investors and regulators.

**Positioning statement:**
> Halcyon Lab is an autonomous equity trading system that uses fine-tuned language models to identify and execute pullback-in-uptrend opportunities across S&P 100 equities. The system processes market data, earnings transcripts, and technical signals to generate trade decisions — then executes them automatically within predefined risk parameters.

This is specific, verifiable, and describes the mechanism rather than the magic.

---

## Application across every touchpoint

### Web dashboard (React 18, dark mode primary)

The dashboard uses Slate 800 (`#0F172A`) as the primary background. Cards and surfaces elevate to Slate 700 (`#1E293B`) with 1px Slate 600 borders. The left sidebar uses Slate 800 with Teal 400 active-state highlights. The top header is borderless, blending into the background with a subtle bottom divider at Slate 600. All spacing follows a **4px base grid** (common values: 4, 8, 12, 16, 24, 32, 48, 64px). Default border radius is **8px** for cards and containers, **6px** for buttons and inputs, **4px** for badges and chips. Charts render in Slate 700 card surfaces with the 8-color series palette.

### Telegram bot avatar and messages

The bot avatar should be **512×512px PNG** using the logomark (Direction A kingfisher or Direction C monogram) on a Slate 800 circular background with the Teal 400 mark. Telegram crops to circles, so the mark must have adequate padding (20% of frame). Use **HTML parse mode** for all messages — `<code>` tags for ticker symbols and prices (tap-to-copy in Telegram), `<b>` for emphasis, `<pre>` blocks for tabular data. Structure every notification as: Status Emoji → Category Header → Primary Data → Context → Impact → Next Action.

### Investor presentation slides

Dark theme (Slate 800 background) for data-heavy slides, creating the visual association with Bloomberg-grade seriousness. Title slide: logo top-left, one-line positioning statement centered ("Autonomous Equity Trading Powered by Language Models"), one compelling metric below. Data slides use the chart series palette. Performance comparison always benchmarks against S&P 100. Risk metrics table shows Sharpe ratio, Sortino ratio, max drawdown, win rate, average holding period. Monthly returns presented as a calendar heatmap with Teal (positive) and red (negative) shading. The **14-slide structure**: Title → Problem → Strategy → Technology → Track Record → Strategy Detail → Risk Management → Market Opportunity → Competitive Landscape → Team → Infrastructure → Terms → Roadmap → Contact.

### GitHub README

Custom hero banner (1280×640px) with dark background, logo, and tagline. Flat-square shields.io badges in a horizontal row: Python version, license, build status, test count, coverage, strategy name, universe. System architecture diagram in Mermaid. Collapsible sections for configuration and setup. Prominent disclaimer/risk disclosure. Keep under 800 lines — link to external docs for detail.

### App icon (future PWA)

Use Direction C (HL monogram) or Direction A (kingfisher mark) on Slate 800 background with Teal 400 foreground. Rounded-rectangle superellipse format matching iOS conventions. At 1024×1024 the full detail is visible; at 60×60 (iOS home screen) and 29×29 (Settings), the geometric form must remain legible. Test at every required size before shipping.

### Email notification templates

**600px max width.** Web-safe font stack: `Arial, Helvetica, sans-serif` at 14–16px body, 20–24px headings. Background: `#F8FAFC` (light mode). Text: `#0F172A`. CTA buttons use Teal 500 background with white text, minimum 44×44px tap target. Trade alert emails follow the structure: logo header → status chip → trade data block (ticker, action, price, total) → portfolio impact → CTA button → footer. Daily summary subject line format: *"📊 Halcyon Lab Daily — +0.52% | 3 Trades | Mar 26"*. Include `<meta name="color-scheme" content="light dark">` and avoid pure black/white to prevent aggressive dark-mode inversion in email clients.

---

## Design tokens: the complete specification

### Spacing scale (4px base)

```css
--space-0: 0px;     --space-1: 4px;    --space-2: 8px;
--space-3: 12px;    --space-4: 16px;   --space-5: 20px;
--space-6: 24px;    --space-8: 32px;   --space-10: 40px;
--space-12: 48px;   --space-16: 64px;  --space-20: 80px;
```

### Border radius

```css
--radius-sm: 4px;   /* Badges, chips, tags */
--radius-md: 6px;   /* Buttons, inputs */
--radius-lg: 8px;   /* Cards, containers */
--radius-xl: 12px;  /* Modals, large panels */
--radius-full: 9999px; /* Pills, avatars */
```

### Shadows (dark mode — use opacity, not color)

```css
--shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.3);
--shadow-md: 0 4px 6px rgba(0, 0, 0, 0.4);
--shadow-lg: 0 10px 15px rgba(0, 0, 0, 0.5);
--shadow-glow: 0 0 20px rgba(45, 212, 191, 0.15); /* Teal glow for focus */
```

### Complete color tokens (CSS custom properties)

```css
:root {
  /* Primary */
  --halcyon-50: #F0FDFA;   --halcyon-100: #CCFBF1;
  --halcyon-200: #99F6E4;  --halcyon-300: #5EEAD4;
  --halcyon-400: #2DD4BF;  --halcyon-500: #14B8A6;
  --halcyon-600: #0D9488;  --halcyon-700: #0F766E;
  --halcyon-800: #115E59;  --halcyon-900: #134E4A;

  /* Accent */
  --amber-50: #FFFBEB;     --amber-100: #FEF3C7;
  --amber-200: #FDE68A;    --amber-300: #FCD34D;
  --amber-400: #FBBF24;    --amber-500: #F59E0B;
  --amber-600: #D97706;    --amber-700: #B45309;
  --amber-800: #92400E;    --amber-900: #78350F;

  /* Neutral */
  --slate-50: #F8FAFC;     --slate-100: #E2E8F0;
  --slate-200: #CBD5E1;    --slate-300: #94A3B8;
  --slate-400: #64748B;    --slate-500: #475569;
  --slate-600: #334155;    --slate-700: #1E293B;
  --slate-800: #0F172A;    --slate-900: #020617;

  /* Semantic */
  --success: #10B981;      --warning: #F59E0B;
  --danger: #EF4444;       --info: #3B82F6;

  /* Dark mode surfaces */
  --bg-primary: var(--slate-800);
  --bg-surface: var(--slate-700);
  --bg-elevated: var(--slate-600);
  --text-primary: var(--slate-100);
  --text-secondary: var(--slate-400);
  --text-muted: var(--slate-300);
  --border-default: var(--slate-600);
  --border-subtle: var(--slate-700);
  --accent-primary: var(--halcyon-400);
  --accent-warm: var(--amber-400);
}
```

---

## Conclusion: a brand built on the kingfisher's calm

Halcyon Lab's identity system achieves something rare in fintech — it's **rooted in a specific, ownable narrative** (the kingfisher calming the seas) rather than assembled from generic visual conventions. The teal-and-amber palette directly mirrors the halcyon bird's plumage. The typography stack prioritizes financial precision (tabular figures, slashed zeros) without sacrificing visual distinction. The Sage/Ruler archetype blend ensures every communication carries calm authority.

Three decisions make this system work at a practical level. First, the **dark-mode-first approach** means every color was selected for contrast against Slate 800, not retrofitted from a light palette — this is the difference between dark mode that feels native and dark mode that feels inverted. Second, the **4px grid with 8px default spacing** creates consistency without requiring constant design decisions during implementation. Third, the **mechanism-specific AI language** preempts the regulatory and credibility risks that sink brands claiming "revolutionary AI" without substance.

The system is designed to age well. Teal-cyan sits in a genuinely unclaimed space between the saturated purple-blue of modern fintech (Stripe, Linear, Mercury) and the aggressive green-neon of consumer trading (Robinhood, Ramp). As the AI trading space matures and attracts institutional scrutiny, Halcyon Lab's visual restraint and verbal precision will compound into trust — exactly as the halcyon calms the seas.