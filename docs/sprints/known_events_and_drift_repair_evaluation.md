# Pass 1 Evaluation — known_events 2019-2024 backfill + doc drift repair

**Sprint:** `feat/known-events-and-doc-drift-repair` (Issue #522, v0.25.1)
**Date:** 2026-04-19
**Author:** CC

---

## 0. Overview

Two deliverables in one PR, justified by shared local-CI gating:

1. **Part 1 (primary):** backfill `src/diagnostics/known_events.py` with
   2019-2024 tariff / sanction / trade-war events so the tariff-exclusion
   rule planned for v0.26.2 has real coverage over walk-forward OOS
   windows (`walkforward_config.py` R1 window: 2019-01-01 → 2024-09-30).
2. **Part 2 (secondary):** make `scripts/verify_docs.py` exit 0 after
   today's 11-PR session left MASTER.md Section 2 counts stale.

No behavior change in any consuming code. Data additions only for Part 1,
doc updates only for Part 2.

---

## 1. Orientation findings

### 1.1 Actual `KNOWN_EVENTS` schema (read-before-plan)

The existing schema is simpler than the sprint prompt implies. From
`src/diagnostics/known_events.py`:

```python
KNOWN_EVENTS: dict[str, str]       # ISO date → event label
EVENT_CATEGORIES: dict[str, str]    # event label → category
```

Consumer (`src/diagnostics/analyses.py:208-214`) emits a per-row
`{date, event, category}` tuple. **No sectors, description, or citation
field currently exists in the schema.** There is no `is_known_event()`
function either; the prompt's reference is aspirational.

### 1.2 `verify_docs.py` drift check — live output

Run locally (2026-04-19 15:02 ET):

```
WARN  Python files: documented=214, actual=303 (+89)
WARN  Test functions: documented=2141, actual=2498 (+357)
WARN  Test files: documented=181, actual=226 (+45)
WARN  Dashboard pages: documented=25, actual=28 (+3)
WARN  Research docs: documented=107, actual=92 (-15)
Results: 0 passed, 5 warnings, 0 skipped
```

5/5 checks drifted. Research docs is the only *negative* delta — 15 files
either moved or were pruned since the last MASTER.md update. Pass 2 will
confirm the new live values by re-running.

### 1.3 Other possibly-stale items (to verify in Pass 2)

| Item | Line | Current doc value | Candidate live value |
|---|---|---|---|
| MASTER.md Section 2 `Schema tables` | 67 | 61 | 67 (per registry) |
| MASTER.md Section 2 `Schema registry` component | 90 | 63 | 67 |
| MASTER.md Section 2 `Render sync` | 91 | 44/51 | 47+/67 (check `sync_to_postgres=True` count) |
| MASTER.md line 88 `Dashboard (Arcis)` component | 88 | 26 | 28 (matches jsx file count) |
| CLAUDE.md line 14 `all 64 tables` | 14 | 64 | 67 |
| MASTER.md Section 5 heading "(41 confirmed)" | 635 | 41 | 41 (list ends at #41 — accurate) |
| RELEASES.md | — | v0.25.0 latest | v0.25.0 latest — current |

MASTER.md Section 5 is **not drifted** despite operator memory suggesting
otherwise — the numbered list terminates at SD#41, matching the heading.

RELEASES.md already contains v0.25.0. v0.26.0 remains in CHANGELOG
[Unreleased], consistent with "unreleased until tagged".

---

## 2. Part 1 — Event backfill plan

### 2.1 Schema decision: additive extension, not replacement

The cleanest path that satisfies both the sprint constraint (primary-source
citation per event) and the guardrail (no behavior change in consuming
code) is to **extend, not replace**:

- Keep `KNOWN_EVENTS: dict[str, str]` and `EVENT_CATEGORIES: dict[str, str]`
  exactly as they are; append new dated entries and any new category labels.
  `analyses.py:210-213` continues to work unchanged.
- Add a new parallel structure `EVENT_METADATA: dict[str, EventMeta]` keyed
  by the same date string, where `EventMeta` is a `TypedDict` carrying the
  richer fields (sectors, description, primary-source URL). No consumer is
  required to read this yet; it's audit-trail data for v0.26.2.
- Add `is_known_event(date_str: str, category: str | None = None) -> bool`
  as a small pure helper. When `category` is None, returns True iff the
  date is keyed in `KNOWN_EVENTS`. When `category` is given, returns True
  iff the date is keyed AND its event's category matches.

This preserves the 2026 entries currently in the file untouched and lets
the future tariff-exclusion rule do `is_known_event(d, "Trade Policy")`
as a one-liner.

### 2.2 Point-in-time vs date-range handling

Several events (Russia sanctions rounds, Red Sea disruption) are
multi-day shocks. The existing schema is point-in-time, and consumers
already handle date-by-date lookup. My plan: **encode the market-moving
primary date(s) only**, not full ranges. Where an event genuinely had
distinct shock days (announcement + escalation), add each as its own
key with a distinct label (`TARIFF_ANNOUNCEMENT` vs `TARIFF_ESCALATION`
mirroring the existing 2026 pattern).

Research rigor: a date only qualifies if S&P 100 proxy (SPY) moved ≥1%
intraday OR VIX moved ≥2 points OR a clearly identifiable sector
rotation (>2σ one-day sector return) occurred on or within one
trading day of the event. Pass 2 will verify each via primary source.

### 2.3 Candidate event list (12-18 target; quality > volume)

Organized by category. Each candidate gets verification in Pass 2.

**A. Trump I trade war tail (2019-Q4 – 2020-Q1)**

| Candidate date | Proposed label | Rationale |
|---|---|---|
| 2019-10-11 | TARIFF_PAUSE | "Phase One in principle" announcement — SPY +1.09% |
| 2019-12-13 | TARIFF_ANNOUNCEMENT | Phase One deal agreed; tariff rollback on $120B — SPY +0.01% muted (priced in) — **likely EXCLUDE** |
| 2020-01-15 | TARIFF_ANNOUNCEMENT | Phase One signed at White House — mostly priced in — **likely EXCLUDE** |

**B. COVID-era trade/export policy (2020)**

Generally EXCLUDE — COVID shock dominates; can't isolate tariff signal.
Possible candidate: 2020-04-03 DPA invocation blocking N95 mask exports,
but market moved on COVID, not on DPA. **EXCLUDE all unless primary
source shows clean separation.**

**C. Russia/Ukraine sanctions (2022)**

| Candidate date | Proposed label | Rationale |
|---|---|---|
| 2022-02-24 | SANCTIONS_INITIAL | Russia invades; first US/EU sanctions — SPY -2.51% intraday, VIX +6.6 |
| 2022-02-26 | SANCTIONS_ESCALATION | SWIFT ban announced (Sat) — gap open Mon; capture Mon 02-28 instead? |
| 2022-02-28 | SANCTIONS_ESCALATION | SWIFT Monday gap + ruble collapse |
| 2022-03-08 | SANCTIONS_ESCALATION | US Russian oil/gas import ban — WTI +5.5%, XLE +3% |
| 2022-04-06 | SANCTIONS_ESCALATION | Treasury "severe" sanctions package — moderate move — **marginal** |

**D. Semiconductor export controls (2022)**

| Candidate date | Proposed label | Rationale |
|---|---|---|
| 2022-10-07 | EXPORT_CONTROLS | BIS rule: advanced chip/equipment to China — SOX -6.1%, NVDA -7.6% |

**E. IRA / CHIPS Act (2022)**

| Candidate date | Proposed label | Rationale |
|---|---|---|
| 2022-08-09 | INDUSTRIAL_POLICY | CHIPS Act signed — SOX +3.3% pre/post sector rotation |
| 2022-08-16 | INDUSTRIAL_POLICY | IRA signed — clean-energy rotation (TAN +2.8%) |

Category choice: IRA/CHIPS aren't tariffs per se but are trade-policy-
adjacent industrial-policy interventions causing measurable sector
rotation. Including under a new `INDUSTRIAL_POLICY` sub-category keeps
them separable from pure tariff/sanctions data. **Alternate decision:**
exclude both as not-tariff-primary; keep the scope tight. **Pass 2
decision point** — verify the rotation is big enough to qualify.

**F. Red Sea / Houthi disruption (late 2023 – early 2024)**

| Candidate date | Proposed label | Rationale |
|---|---|---|
| 2023-12-18 | SHIPPING_DISRUPTION | Maersk + Hapag-Lloyd halt Red Sea transits — WTI +2%, Cape rates spike |
| 2024-01-12 | MILITARY_TRADE_ACTION | US/UK strikes on Houthi — oil + defense both up |

Category: not tariff/sanctions. Proposed new category
`SHIPPING_DISRUPTION` or fold into `SANCTIONS_ESCALATION`? I lean
toward a distinct `TRADE_DISRUPTION` label — different mechanism.

**G. Biden China tariff increases (2024-05)**

| Candidate date | Proposed label | Rationale |
|---|---|---|
| 2024-05-14 | TARIFF_ESCALATION | Biden announces $18B tariff increases (EVs 100%, semis 50%) — targeted sector moves (XLI, LIT, chips) |

### 2.4 Inclusion summary (tentative, firm in Pass 2)

Target coverage: **12-15 events** across 2019-09 → 2024-09.

Confident INCLUDE (8): 2019-10-11, 2022-02-24, 2022-02-28, 2022-03-08,
2022-10-07, 2023-12-18, 2024-01-12, 2024-05-14.

Likely INCLUDE pending primary-source move verification (4-7):
2022-08-09, 2022-08-16, 2022-04-06, 2019-12-13.

Likely EXCLUDE: Phase One signing 2020-01-15 (priced in), all COVID
policy days (confound), smaller sanctions tranches that didn't move
markets.

**Coverage count floor for regression test:** at least **10** events in
the 2019-09-30 to 2024-09-30 window must be present after this sprint.
Set floor slightly below firm-include count (8) + likely-include lower
bound (2) = 10 to give buffer against rationalized exclusions.

### 2.5 New category labels to add

Proposed additions to `EVENT_CATEGORIES`:

- `SANCTIONS_INITIAL` → `"Trade Policy"`
- `SANCTIONS_ESCALATION` → `"Trade Policy"`
- `EXPORT_CONTROLS` → `"Trade Policy"`
- `INDUSTRIAL_POLICY` → `"Trade Policy"` (if Pass 2 decides to include)
- `TRADE_DISRUPTION` → `"Trade Policy"`
- `MILITARY_TRADE_ACTION` → `"Trade Policy"`

All collapse to the single `"Trade Policy"` category so existing consumer
behavior (grouping by category) treats them uniformly. The finer-grained
label is preserved for downstream analysis.

### 2.6 File-size budget

Current `known_events.py` is 42 lines. Adding ~15 events + metadata
dict + `is_known_event` helper + docstring updates projects to
~200-250 lines. **Under the 400-line guardrail; no split required.**

### 2.7 Test plan

New test module `tests/diagnostics/test_known_events.py`:

1. `test_known_events_schema_invariants` — every key parses as ISO
   date (`datetime.date.fromisoformat`); every value is in
   `EVENT_CATEGORIES`.
2. `test_event_categories_closed_set` — every unique value in
   `KNOWN_EVENTS` has a matching `EVENT_CATEGORIES` entry.
3. `test_coverage_count_floor_2019_2024` — at least 10 entries fall
   in 2019-09-30 ≤ date ≤ 2024-09-30.
4. `test_metadata_schema_invariants` — for each new 2019-2024 event,
   `EVENT_METADATA[date]` has required keys (`description`,
   `affected_sectors: list[str]`, `primary_source: str`). Sectors
   list may be empty (broad-market); description must be non-empty;
   primary_source must be a URL or a stable document ID.
5. `test_is_known_event_basic` — lookup returns True for representative
   in-window dates, False for nearby non-event dates.
6. `test_is_known_event_category_filter` — True when category matches
   event category; False when category doesn't match.

No changes to `test_regime_diagnostic.py` or any other test file.

---

## 3. Part 2 — Drift repair plan

### 3.1 Scope (MASTER.md only — what verify_docs.py checks)

Replace values in **Section 2** of MASTER.md:

| Field | Current | Target |
|---|---|---|
| Tests | 2,141 | 2,498 (or re-capture in Pass 2) |
| Python files | 214 | 303 |
| Test files (inline in Tests row) | 181 | 226 |
| Dashboard pages | 25 | 28 |
| Research docs | 107 | 92 |
| Schema tables | 61 | 67 |

MASTER.md Section 2 rows have prose explanations appended (e.g.,
"+55 tests Sprint 2..."). I will **preserve those annotations** and
only update the leading integer plus append a "v0.25.0–v0.26.0"
delta note if clearly warranted. The scope discipline from the prompt:
don't restructure sections, don't edit archived docs.

### 3.2 Scope (other files explicitly flagged in prompt)

- **CLAUDE.md line 14** — change `all 64 tables` → `all 67 tables`.
- **Architecture diagram (`frontend/public/architecture.html`)** —
  verify_docs.py doesn't check it. Per prompt, "don't hunt for things
  it doesn't flag". I'll **read it once** in Pass 2 to see if there's
  a glaring mismatch (e.g., it still says "no walkforward layer"); fix
  if trivial, file a follow-up otherwise.
- **RELEASES.md** — current (v0.25.0 is the latest release). No change.

### 3.3 Out of scope

- MASTER.md Section 5 heading "(41 confirmed)" — actually accurate.
- Component status rows in Section 2 prose (e.g., line 88 "Dashboard
  -- 26 pages"). These are free-text, not verify_docs.py targets.
  Will update the one for "Dashboard" and "Schema registry" to match
  new counts, but only because they're the same metric verify_docs.py
  already flagged; other prose stays untouched.
- Anything under `docs/archive/` per prompt.

---

## 4. Decisions I'm committing to now

1. **Schema:** additive — keep existing dicts, add `EVENT_METADATA`
   and `is_known_event()`. Consumer code unchanged.
2. **Date-range:** point-in-time per existing schema; multi-day events
   encoded as distinct keys with `_ESCALATION` suffix.
3. **Coverage floor:** 10 events in 2019-09-30 → 2024-09-30.
4. **Category labels:** 6 new labels, all rolling up to existing
   `"Trade Policy"` bucket for consumer uniformity.
5. **File size:** single file under 400 lines; no split.
6. **Tests:** new `tests/diagnostics/test_known_events.py` with 6
   tests covering schema invariants, coverage floor, metadata
   integrity, and helper behavior.
7. **Doc drift fix scope:** MASTER.md Section 2 only + CLAUDE.md
   line 14. Nothing else unless Pass 2 surfaces trivial adjacent fix.

Pass 2 will do the primary-source verification for each event and the
final-value re-capture for MASTER.md counts.

---

## 5. Open questions parked for Pass 2

- Include CHIPS/IRA signing dates? Verify the sector rotation size
  via primary market data.
- 2022-04-06 Treasury sanctions package — did it actually move markets
  beyond noise? Check SPY / VIX move-size.
- For the 2022-02-26 SWIFT announcement (a Saturday), attribute move
  to next-trading-day 2022-02-28 or skip?
- Architecture diagram (`architecture.html`) — worth touching or
  follow-up issue?
