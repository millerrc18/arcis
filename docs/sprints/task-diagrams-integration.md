# Task: Complete 13 Architecture Diagrams + Integrate into MASTER.md

> **Scope:** Create 6 missing SVGs, verify 7 existing SVGs, integrate all 13 into MASTER.md
> **Priority:** LOW — visual polish, not blocking anything

---

## Context

`docs/diagrams/svg/` contains 7 complete SVG diagrams (04-10) and a README mapping all 13 to MASTER.md sections. 6 diagrams (01-03, 11-13) need to be created.

**Read `docs/diagrams/svg/README.md` for the full index.**

All SVGs must:
- Be standalone (self-contained `<style>` block, no external dependencies)
- Support light AND dark mode via `@media (prefers-color-scheme: dark)`
- Use the same color ramp system as the existing files (04-10)
- Use `viewBox="0 0 680 H"` where H fits content tightly
- Use system-ui font family, 14px for titles (.th), 12px for subtitles (.ts)

---

## Step 1: Study the existing style pattern

Read `docs/diagrams/svg/05-risk-governor.svg` for the full style block reference. Copy the exact `<style>` block (including all color classes and dark mode overrides) into every new SVG.

---

## Step 2: Create 6 missing SVGs

### 01-system-architecture.svg (Section 3)
Full pipeline diagram. 6 rows:
- Row 1: 5 data source boxes (yfinance, SEC EDGAR, Finnhub, FRED/VIX, Earnings) — c-blue. Add a 6th small box "+4 more" (Options, Google Trends, Insider, CBOE)
- Row 2: Feature engine bar (7 dimensions) — c-teal, full width
- Row 3: Deterministic ranker → LLM (halcyon-v1.0.0) — c-purple
- Row 4: Risk governor (8 checks) — c-coral, full width
- Row 5: Alpaca paper (c-amber) + Alpaca live (c-amber, dashed border) side by side. NOTE: IB integration is planned but not deployed — show current state
- Row 6: Training pipeline feedback bar (c-pink)
- Dashed curved arrow from bottom-right back up to feature engine labeled "Flywheel"
- viewBox height ~520

### 02-broker-abstraction.svg (Section 3)
Multi-broker architecture (PLANNED — IB not yet deployed). Shows:
- Top: Executor box (c-purple)
- Left branch: "Paper trades (unchanged)" → Alpaca adapter (direct, c-amber) → Alpaca paper API. Add note: "No abstraction needed — direct call"
- Right branch: "Live trades" → Broker factory (c-teal) → dashed ABC interface box (BrokerAdapter)
- Factory branches to: AlpacaLiveBroker (c-amber) + IBBroker (c-green, dashed border — planned)
- Bottom: Alpaca live API + IB Gateway :4001
- viewBox height ~440

### 03-flywheel-moat.svg (Section 8)
Compounding loop. Diamond layout:
- Top: Execute trades (c-teal)
- Right: Observe outcomes (c-amber)
- Bottom: Generate training data (c-purple)
- Left: Retrain model (c-coral)
- Curved arrows connecting them in a cycle
- Center text: "Each cycle improves the next"
- Bottom section below dashed line: 3 gray boxes explaining "More trades → more data → better model → better trades"
- viewBox height ~480

### 11-trade-lifecycle.svg (Section 3)
Signal to close flow:
- Row 1: Market scan → Feature engine → Ranker ≥40 → LLM enhance (left to right, c-blue/c-teal/c-purple)
- Arrow down to: Attribution logging (c-amber)
- Arrow down to: Risk governor with "Rejected" branch left (c-red) and "Approved" down
- Dual execution: Alpaca paper (c-amber) + Alpaca live (c-amber) side by side. NOTE: Show current state (both Alpaca), not future IB state
- Arrow down to: Position monitor every 15 min (c-teal)
- Small Telegram notification icon/note after execution
- Bottom: 3 exit boxes: Stop hit (c-gray) / Target hit (c-green) / Timeout (c-amber)
- Left margin timestamps: 9:30 ET, ~10s later, Immediate, 1-15 days
- viewBox height ~520

### 12-training-pipeline.svg (Section 7)
Self-blinding architecture:
- Top: Closed trade + features (c-gray)
- Red dashed firewall line: "Temporal firewall — outcome NEVER crosses this line"
- Two branches below firewall:
  - Left: Stage 1 Blinded generation (c-purple) → Stage 2 Quality scoring (c-teal)
  - Right: Outcome templates 3-5x (c-amber) → Batch generation (c-gray)
- Small note between stages: "3-stage curriculum: structure → evidence → decision"
- Converge to: Training set 62/38 ratio (c-purple)
- Bottom: QLoRA fine-tune → champion-challenger gate (c-coral)
- Side: Leakage test TF-IDF <55% (c-red) with arrow from training set
- viewBox height ~480

### 13-phase-gates.svg (Section 6)
Growth roadmap:
- Phase 1 box (c-teal) → Amber gate box (50 trades, WR≥45%) → Phase 2 (c-teal) → Amber gate (100 trades, Sharpe≥1) → arrow down
- Phase 3-4 (c-teal, multi-strategy + options) → Amber gate (3-month track) → Fund formation (c-green, Wyoming LLC → LP)
- Timeline bar below showing progress: green fill proportional to closed trades / 50. Read current count from MASTER.md Section 2 at build time. If unsure, use placeholder "N/50"
- Timeline labels: Apr 2026, Jul 2026, Dec 2026, 2027+
- Bottom: 3 lines of Phase 1 gate criteria text
- viewBox height ~400

---

## Step 3: Verify existing 7 SVGs

Open each of 04-10 and verify:
- `<style>` block includes dark mode media query
- All text elements have class="th" or class="ts"
- viewBox height matches content (no excess whitespace)
- No text overflows box boundaries (check: chars × 8 < box width for 14px text)

---

## Step 4: Integrate into MASTER.md

For each of the 13 sections in MASTER.md, add a diagram reference image below the section heading where one maps. Use GitHub-rendered image syntax:

```markdown
## 3. Architecture Overview

![System architecture](docs/diagrams/svg/01-system-architecture.svg)

... existing section content ...
```

**Mapping (from README.md):**

| MASTER.md Section | Diagrams |
|---|---|
| Section 3: Architecture | 01, 02, 04, 06, 09, 11 |
| Section 6: Phase Gates | 10, 13 |
| Section 7: Frameworks | 05, 08, 12 |
| Section 8: Revenue & Business | 03, 07 |

Don't put more than 2 diagrams per section — pick the most impactful. If a section has 6 mapped diagrams, put the 2 best inline and link the rest at the bottom:

```markdown
> See also: [Trade lifecycle](docs/diagrams/svg/11-trade-lifecycle.svg), [Watch loop](docs/diagrams/svg/09-watch-loop-24hr.svg)
```

---

## Step 5: Commit

```bash
git add docs/diagrams/svg/ MASTER.md
git commit -m "docs: 13 architecture diagrams — complete set with MASTER.md integration

6 new SVGs: system-architecture, broker-abstraction, flywheel-moat,
trade-lifecycle, training-pipeline, phase-gates.
7 verified: multi-cadence, risk-governor, data-enrichment, revenue-path,
ai-council, watch-loop-24hr, hardware-scaling.

All support light/dark mode. Integrated into MASTER.md sections 3, 6, 7, 8."
```
