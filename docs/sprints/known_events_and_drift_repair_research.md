# Pass 2 Research — known_events 2019-2024 backfill + drift repair

**Sprint:** `feat/known-events-and-doc-drift-repair` (Issue #522, v0.25.1)
**Date:** 2026-04-19
**Author:** CC
**Pass 1 eval:** `docs/sprints/known_events_and_drift_repair_evaluation.md`

---

## 1. Part 1 — primary-source verification per event

Research method: primary-source candidates sourced via research agent
delegation, cross-checked against Federal Register / Treasury OFAC /
USTR press-release URL patterns. Market-move numbers attributed to
research-agent recap of Reuters/WSJ/Bloomberg coverage (not
primary-source material itself since official feeds don't publish
returns).

For each event below: **Date** (market-impact date, which may differ
from official announcement date), **Label**, **Primary source**,
**Happened in one sentence**, **Market move**, **Sectors affected**,
**Verdict**.

### 1.1 INCLUDE (9 events)

---

**#1 · 2019-10-11 · TARIFF_PAUSE** — Phase One "in principle"

- **Primary source:** USTR press release,
  https://ustr.gov/about-us/policy-offices/press-office/press-releases/2019/october
  (month index; exact daily slug not deterministic across USTR archive).
  White House trumpwhitehouse.archives.gov Oct 11 2019 remarks as backup.
- **What happened:** Trump announced a Phase One deal framework;
  suspended the scheduled Oct 15 List 1/2/3 tariff step-up (25→30%);
  framed agricultural purchases, IP, currency, and structural commitments.
- **Market move:** SPY +1.07% close; intraday peak +1.9% before fading
  on skepticism about written terms. VIX -2.8 to ~15.6.
- **Affected sectors:** broad-market (index-level response). Minor extra
  in XLI (industrials, ag-exposed via DE).
- **Verdict:** INCLUDE — SPY close ≥ 1%; VIX delta ≥ 2.

**#2 · 2019-12-12 · TARIFF_ANNOUNCEMENT** — Phase One agreement
(market-impact date; official USTR release 2019-12-13)

- **Primary source:** USTR press release Dec 13 2019
  ("United States and China Reach Phase One Trade Agreement") at
  https://ustr.gov/about-us/policy-offices/press-office/press-releases/2019/december
- **What happened:** Text-level agreement reached. List 4A halved
  (15→7.5%); scheduled Dec 15 tariffs on $160B consumer goods cancelled.
- **Market move:** SPY +0.86% on Dec 12 (Reuters leak midday); the
  Dec 13 formal announcement closed ~flat (sell-the-news).
- **Affected sectors:** broad-market; retail (XRT) ag-sensitive names.
- **Verdict:** INCLUDE — encode 2019-12-12 as market-impact key.
  Metadata description notes Dec 13 USTR formal announcement.

**#3 · 2022-02-24 · SANCTIONS_INITIAL** — Russia invades Ukraine + OFAC Tranche 2

- **Primary source:** Treasury OFAC press release (JY0608),
  https://home.treasury.gov/news/press-releases/jy0608 · White House
  fact sheet https://www.whitehouse.gov/briefing-room/statements-releases/2022/02/24/fact-sheet-joined-by-allies-and-partners-the-united-states-imposes-devastating-costs-on-russia/
- **What happened:** Invasion ~05:00 Moscow Feb 24; Biden announced
  Tranche 2 actions under EO 14024 — CAPTA Directive (Sberbank
  correspondent), Directive 3 (debt/equity on 13 entities), full
  blocks on VTB + 3 others, export controls.
- **Market move:** SPY opened -2.6%, closed +1.5% — a 4%+ intraday
  range. VIX intraday ~37, closed ~30 (-1.6 vs prior close but
  intraday spike +5). Historic reversal.
- **Affected sectors:** broad-market (regime shift). Defense
  (ITA, LMT) ramped; energy (XLE, +3.5% over 3 days) leveraged.
- **Verdict:** INCLUDE — clearest regime-shift event in the window.

**#4 · 2022-03-08 · SANCTIONS_ESCALATION** — EO 14066 Russia oil/gas/LNG/coal import ban

- **Primary source:** White House EO 14066 (Mar 8 2022),
  https://www.whitehouse.gov/briefing-room/presidential-actions/2022/03/08/executive-order-on-prohibiting-certain-imports-and-new-investments-with-respect-to-continued-russian-federation-efforts-to-undermine-the-sovereignty-and-territorial-integrity-of-ukraine/
  · Federal Register 87 FR 14381.
- **What happened:** Imports of Russian crude, petroleum products,
  LNG, coal prohibited; new US investment in Russian energy banned.
- **Market move:** WTI closed $123.70 (+3.6% on Mar 8), intraday
  high $130.50 (highest since 2008). XLE +1.3% Mar 8, +3.1% Mar 7
  (2-day energy sector move >4%). SPY -0.72%, VIX +0.4.
- **Affected sectors:** XLE (energy), XOP (E&P), OIH (services).
- **Verdict:** INCLUDE — sector shock test passes; oil regime event
  of the decade.

**#5 · 2022-07-27 · INDUSTRIAL_POLICY** — Manchin-Schumer IRA deal
+ CHIPS Act Senate final passage (market-impact day for both)

- **Primary source:** Senate Majority Leader / Senator Manchin joint
  statement Jul 27 2022 (public on senate.gov same day); CHIPS vote
  tally on congress.gov S. Amdt. 5135 / HR 4346.
- **What happened:** After months of stall, Manchin-Schumer IRA
  framework agreement announced post-CHIPS vote; clean-energy
  industrial-policy trade thesis validated in a single session.
- **Market move:** TAN +5.7%, ICLN +3.9%, SOX +2.8% (CHIPS-driven).
  Pair-day for the whole industrial-policy trade thesis.
- **Affected sectors:** TAN (solar), ICLN (clean energy), SOX/SMH
  (semiconductors), XLB-clean (materials / battery supply chain).
- **Verdict:** INCLUDE — multi-sector rotation cleared 2σ.

**#6 · 2022-08-09 · INDUSTRIAL_POLICY** — CHIPS Act signed (PL 117-167)

- **Primary source:** White House fact sheet Aug 9 2022,
  https://www.whitehouse.gov/briefing-room/statements-releases/2022/08/09/fact-sheet-chips-and-science-act-will-lower-costs-create-jobs-strengthen-supply-chains-and-counter-china/
  · Congress.gov HR 4346 (PL 117-167).
- **What happened:** $52.7B semiconductor manufacturing + R&D
  subsidies; ~$24B Sec 48D investment tax credit.
- **Market move:** SOX -4.6% (sell-the-news + Micron pre-announce
  negative guide same morning); NVDA -3.97%. Reversal magnitude
  cleared 2σ semi-sector vol band.
- **Affected sectors:** SOX, SMH, SOXX (semiconductors).
- **Verdict:** INCLUDE — direction is counterintuitive but signal
  is real; walk-forward backtests looking at regime shifts around
  policy events should flag it regardless of direction.

**#7 · 2022-10-07 · EXPORT_CONTROLS** — BIS advanced chip / semi-equipment
export controls to China

- **Primary source:** BIS press release Oct 7 2022,
  https://www.bis.doc.gov/index.php/documents/about-bis/newsroom/press-releases
  (landing page; daily slug `3158-...` pattern) · Federal Register
  IFR 87 FR 62186 (published Oct 13, effective dates Oct 7 / Oct 12 /
  Oct 21).
- **What happened:** Export Administration Regulations expanded to
  control advanced-node logic/memory, HBM, advanced-compute ICs, and
  semi manufacturing equipment destined for PRC end users; US-person
  restriction on supporting PRC fab development.
- **Market move:** SOX -6.06%, NVDA -8.03%, AMD -13.87%, AMAT -6.83%,
  LRCX -6.46%. Textbook sector shock.
- **Affected sectors:** SOX, SMH, SOXX, semiconductor-equipment
  (AMAT, LRCX, KLAC).
- **Verdict:** INCLUDE — largest single-day semi sector move in the
  window.

**#8 · 2023-12-18 · TRADE_DISRUPTION** — Maersk/Hapag-Lloyd Red Sea halt
+ Operation Prosperity Guardian launch

- **Primary source:** Maersk Dec 15 press release
  https://www.maersk.com/news/articles/2023/12/15/maersk-pauses-all-transit-through-the-red-sea
  (initial pause; Dec 18 reaffirmation/extension + wider cross-carrier
  participation). DOD launch of Operation Prosperity Guardian Dec 18.
- **What happened:** After the Galaxy Leader seizure and the Maersk
  Hangzhou incident, major carriers paused Red Sea transits; US
  announced multinational escort mission.
- **Market move:** WTI +1.8% to $72.82 Dec 18; Brent +1.8% to $77.95.
  ZIM +8.4%, Matson +2.1%. Container spot rates (SCFI, Drewry WCI)
  surged +20–40% over next two weeks.
- **Affected sectors:** Shipping (ZIM, MATX), oil (XLE — modest),
  defense (ITA — modest), container rates (not an ETF but a real
  economic signal).
- **Verdict:** INCLUDE — shipping equity move cleared 2σ; supply-chain
  regime event.

**#9 · 2024-05-14 · TARIFF_ESCALATION** — Biden Section 301 tariff
increases on ~$18B imports from China

- **Primary source:** USTR 4-year-review release May 14 2024,
  https://ustr.gov/about-us/policy-offices/press-office/press-releases/2024/may
  · White House fact sheet
  https://www.whitehouse.gov/briefing-room/statements-releases/2024/05/14/fact-sheet-president-biden-takes-action-to-protect-american-workers-and-businesses-from-chinas-unfair-trade-practices/
  · Federal Register modification May 28.
- **What happened:** Section 301 tariffs on Chinese imports hiked:
  EVs 25→100%; EV lithium-ion batteries 7.5→25%; solar cells 25→50%;
  semis 25→50%; steel/aluminum to 25%; ship-to-shore cranes to 25%;
  syringes/PPE increases. Targets ~$18B import value.
- **Market move:** KWEB -1.6%, FXI -2.1%, BYDDY -1.8% (pre-market
  spike faded), NIO -3.9% into May 15, LI -5.4% through May 15. LIT
  +0.4% (ambiguous — global basket). SPY +0.48%, VIX flat.
- **Affected sectors:** china-exposed (KWEB, FXI), EV (BYDDY, NIO,
  LI); LIT ambiguous; US-made battery beneficiaries (EVgo, FCEL)
  modestly up.
- **Verdict:** INCLUDE — borderline at SPY-index level but
  **category-perfect** (direct Section 301 tariff event) and
  multi-single-name Chinese ADR move cleared 2σ by next session.
  Walk-forward systems building tariff-exclusion rules must capture
  this date because it's literally the defining 2024 tariff event.
  Documented as "sector-level inclusion" in metadata.

### 1.2 EXCLUDE (5 candidates reviewed and dropped)

| Candidate date | Agent verdict | Reason for exclude |
|---|---|---|
| 2019-12-13 | EXCLUDE | Actual move was Dec 12 leak; Dec 13 USTR day closed flat. Encoded as Dec 12 per #2 above. |
| 2020-01-15 | EXCLUDE | Phase One signing — SPY +0.17%, priced in since October. |
| 2022-02-28 | EXCLUDE | SWIFT Mon; SPY -0.24% muted; RUB -30% was historic but FX-only. Walk-forward S&P 100 system doesn't benefit. |
| 2022-04-06 | EXCLUDE | Treasury tranche + EO 14071; SPY -0.97% but hawkish Fed minutes same day contaminate attribution. |
| 2022-08-16 | EXCLUDE | IRA signing — rotation already ran Jul 27 (encoded as #5). Signing day flat. |
| 2024-01-12 | EXCLUDE | Houthi strikes; oil spike faded intraday, defense ETF move sub-threshold. |

### 1.3 Final coverage summary

**9 events INCLUDED** across the 2019-09-30 → 2024-09-30 window.

Coverage floor locked at **8** in the regression test (one below
firm count to accommodate a judgment call during implementation
without destabilizing the test). The prompt's "quality > volume"
discipline overrides the Pass 1 draft floor of 10.

### 1.4 New category labels landing

Added to `EVENT_CATEGORIES` (all roll up to `"Trade Policy"` for
consumer uniformity — `src/diagnostics/analyses.py:212` groups by
category):

- `SANCTIONS_INITIAL` → `"Trade Policy"`
- `SANCTIONS_ESCALATION` → `"Trade Policy"`
- `EXPORT_CONTROLS` → `"Trade Policy"`
- `INDUSTRIAL_POLICY` → `"Trade Policy"`
- `TRADE_DISRUPTION` → `"Trade Policy"`

Existing labels kept as-is. `TARIFF_ANNOUNCEMENT`, `TARIFF_PAUSE`,
`TARIFF_ESCALATION` already exist and are reused for events #1, #2, #9.

### 1.5 Schema addition: `EVENT_METADATA` + helper

Backward-compatible additive extension:

```python
class EventMeta(TypedDict):
    description: str
    affected_sectors: list[str]     # empty list = broad-market
    primary_source: str              # URL or stable doc ID
    market_impact_note: str          # optional attribution/caveat

EVENT_METADATA: dict[str, EventMeta]  # keyed by same date as KNOWN_EVENTS

def is_known_event(date_str: str, category: str | None = None) -> bool:
    ...
```

Existing 2026 entries in `KNOWN_EVENTS` will get minimal metadata
(description + empty sectors) so the metadata invariant holds for
every key, not just 2019-2024 additions. This avoids a leaky-abstraction
test where half the keys have metadata and half don't.

### 1.6 URL-verification notes

- Treasury press-release IDs (`jy0608`, `jy0612`, `jy0705`) follow
  treasury.gov's stable press-release numbering — high confidence.
- White House briefing-room slugs for 2022-2024 verified against
  their URL schema — high confidence on dates; exact slug may drift
  on archived pages but the dated path is canonical.
- BIS Oct-7-2022 press release: landing page URL used rather than
  deep-link to the PDF file (the numeric `3158-...` file ID is a BIS
  document sequence, not a stable slug pattern).
- USTR press releases: daily slugs on ustr.gov are not
  deterministically predictable from training data alone. Used
  month-index URLs as the primary citation target — operator can
  navigate to the specific day. Alternate: cite Federal Register
  modification notice where available (e.g., 87 FR 14381 for EO 14066).
- Direct WebFetch verification of URLs was attempted but blocked by
  Cloudflare/bot challenges (e.g., federalregister.gov redirects to
  `unblock.federalregister.gov`, Treasury press releases time out
  under automated fetch). URLs encoded are
  pattern-matched-against-known-good; operator verification recommended
  but not a blocker for this sprint.

---

## 2. Part 2 — `verify_docs.py` drift captured verbatim

### 2.1 Pre-fix output (exit=1)

```
============================================================
  Documentation Drift Report
  Source: MASTER.md
============================================================

  WARN  Python files: documented=214, actual=303 (+89)
  WARN  Test functions: documented=2141, actual=2498 (+357)
  WARN  Test files: documented=181, actual=226 (+45)
  WARN  Dashboard pages: documented=25, actual=28 (+3)
  WARN  Research docs: documented=107, actual=92 (-15)

  Results: 0 passed, 5 warnings, 0 skipped

  Update MASTER.md Section 2 to fix warnings.
```

### 2.2 Exact MASTER.md edits (line numbers from current file on disk)

- **Line 62 — Tests row**
  - current prefix: `| Tests | 2,141 tests across 181 test files (+44 tests, +7 test files Sprint 1; ...`
  - target prefix: `| Tests | 2,498 tests across 226 test files ( ... append: `+357 tests, +45 test files 2026-04-18/19 (Sprints platform-foundation/rigor/safety/shadow, dashboard, walkforward v1, training-data audit, hygiene bundle)`)`
  - Preserves all pre-existing sprint annotations verbatim; only the leading integer and a single new tail-annotation are edited.

- **Line 63 — Python files row**
  - current: `| Python files | 214 (+12 ...`
  - target: `| Python files | 303 (+12 ... ; +89 Sprint platform-foundation/rigor/safety/shadow + dashboard + walkforward + training audit + hygiene bundle 2026-04-18/19)`

- **Line 64 — Dashboard pages**
  - `| Dashboard pages | 25 |` → `| Dashboard pages | 28 |`
  - (No prose annotation in this row to preserve.)

- **Line 65 — Research docs**
  - `| Research docs | 107 |` → `| Research docs | 92 |`
  - 15-doc decrement reflects the doc pruning that happened between
    prior MASTER.md update and current state; no annotation needed.

- **Line 67 — Schema tables**
  - `| Schema tables | 61 (registry), 44+ synced to Postgres (+3 Sprint 1...`
  - target: `| Schema tables | 67 (registry), 58 synced to Postgres (+3 Sprint 1: backtest_results, backtest_trades, + 1 via platform; +3 Sprint 2: strategy_registry, strategy_promotion_events, trials_registry; +2 tables Sprint 3: correlation_matrices, factor_loadings; +3 tables v0.25.0 walk-forward: walkforward_results, walkforward_trades, sp100_historical_constituents; +3 local-only: operator_view_state, daily_ib_health, bracket_health)`
  - Note: the "+3 local-only" annotation for non-synced tables is
    new — explains the 67 vs 58 delta without removing existing
    annotations.

- **Line 88 — Dashboard component line**
  - `| Dashboard (Arcis) | LIVE -- 26 pages ...`
  - target: `... 28 pages (Walkforward Results added v0.25.0; Diagnostics page added earlier...)` — update count only, preserve rest.

- **Line 90 — Schema registry component**
  - `| Schema registry | LIVE -- 63 tables, single source of truth |`
  - target: `| Schema registry | LIVE -- 67 tables, single source of truth |`

- **Line 91 — Render sync**
  - `| Render sync | LIVE -- 44/51 tables synced to Postgres |`
  - target: `| Render sync | LIVE -- 58/67 tables synced to Postgres |`

### 2.3 Other files flagged in the sprint prompt

**CLAUDE.md line 14** — update `all 64 tables` → `all 67 tables`.
The authoritative-count one-liner stays (`python -c "from
src.schema.registry import TABLES; print(len(TABLES))"`).

**RELEASES.md** — v0.25.0 already present. v0.26.0 (training-data
audit) still lives in `CHANGELOG.md [Unreleased]` per convention
("unreleased until tagged"). No change required here.

**MASTER.md Section 5 heading `(41 confirmed)`** — accurate (list
terminates at `41.` entry). No change.

**`frontend/public/architecture.html`** — confirmed stale: 880 lines,
**zero** `walkforward` / `walk-forward` / `walk forward` references
after PR #520 added the 9-module walk-forward namespace. Per sprint
prompt ("don't hunt for things it doesn't flag"), scoped **OUT** of
this sprint. Follow-up issue to file in PR body: "Update
architecture.html to include walk-forward v1 layer + training-audit
capability".

### 2.4 Expected post-fix verify_docs.py state

After the MASTER.md edits in §2.2 land, `python scripts/verify_docs.py`
should print 5 PASS lines and exit 0. The test count target is a
moving target (new tests in this sprint will bump it); reconfirmed
post-implementation before commit.

---

## 3. Decisions locked for Pass 3 (implementation)

1. **9 events** to add to `KNOWN_EVENTS` + `EVENT_METADATA`.
2. **Coverage floor test:** 8 events in 2019-09-30 → 2024-09-30.
3. **5 new category labels** rolled under existing `"Trade Policy"`.
4. **Schema extension:** `EVENT_METADATA: dict[str, EventMeta]` + `is_known_event()` — no change to existing consumers.
5. **File size check:** projected ~240 lines in `known_events.py`
   after additions; well under 400-line guardrail.
6. **Existing 2026 entries** also get metadata rows to keep the
   metadata invariant total over `KNOWN_EVENTS.keys()`.
7. **MASTER.md** edits: lines 62, 63, 64, 65, 67, 88, 90, 91.
8. **CLAUDE.md** edit: line 14.
9. **Architecture.html** staleness filed as follow-up issue,
   not patched in this sprint.
10. **Tests file:** new `tests/diagnostics/test_known_events.py`
    with 6 test functions (per Pass 1 §2.7).

---

## 4. Out-of-scope confirmations

- `docs/archive/` — untouched.
- MASTER.md Sections other than 2 and sprint-queue rows — untouched.
- No new `EVENT_METADATA` consumer wiring — data-only addition.
- Architecture diagram (`frontend/public/architecture.html`) —
  follow-up, not this PR.
