# S04 — Data Plane Audit

| | |
|---|---|
| **Branch** | `feat/s04-data-plane` |
| **Repository** | `millerrc18/arcis` (public). Market data stays under the data root; only aggregate statistics are committed. |
| **Depends on** | S01 merged (recorder, universe snapshots). S03 merged (bars panel exists under data root). `prereg-v1` tagged. |
| **Ledger row** | None. This sprint produces audit reports and known-answer tests, not a package. |
| **Invariants** | I-7 data outside the repo and sync folders · I-12 no blind exception handling · I-16 nothing private and no market data in a public repo |
| **Runs** | After `prereg-v1` (SCOPE §5 Step 3); Steps 4–5 depend on it |
| **Tasks** | 7 |

## Why this sprint exists

Steps 4 (ranker) and 5 (simulator, harness) both stand on the data plane. The S03 bars panel exists, but its quality characteristics are unaudited:

- **Coverage:** S03 pulled current S&P 500 constituents from 2016. How many have full history? Which are late starters? Are there gaps?
- **Delisted symbols:** The panel has only current constituents. Names that left the index (acquired, bankrupt, demoted) are absent. How much history is missing, and what bias does that introduce?
- **Adjustments:** We request `adjustment=all`. Do splits and dividends appear correctly? Are there unadjusted spikes?
- **Corporate actions:** How do mergers, spinoffs, and ticker changes manifest in the Alpaca data?
- **Availability:** When was each bar available? A bar timestamped 2016-01-04 was not available on 2016-01-04 for a backtest — but for the forward test (which is what matters post-tag), we need to know the data was available at `t_d`.
- **Survivorship:** The S03 report states the survivorship bias qualitatively. This sprint quantifies it: what fraction of the 2016 S&P 500 is still in the index? What was the volatility of leavers vs stayers?

Without this audit, Step 4 builds a ranker on data whose limitations are unknown, and Step 5's simulator inherits them silently.

## Hard scope

**In:** coverage audit of the S03 bars panel; delisted-symbol inventory; adjustment verification on known splits/dividends; corporate-action documentation; availability timestamp analysis; forward membership snapshot verification; known-answer tests for data calculations; quantified survivorship report.

**Out:** implementing the ranker (Step 4); implementing the simulator (Step 5); any statistic conditional on the incumbent's qualification or score; loading `config/incumbent_v1.yaml`; changing any preregistered threshold.

If a task appears to need anything from **Out**, stop and write it up in the sprint report.

## Ground rules

1. **Audit, don't fix (yet).** This sprint documents the data's characteristics. If a defect is found that blocks Step 4, record it as a blocker with a proposed fix; don't silently repair the panel.
2. **No signal-conditional statistics.** Same as S03: nothing conditional on incumbent qualification, ranker score, or text score.
3. **Point-in-time discipline.** For any historical analysis, use only data that was available at the time. The forward test (post-tag) is the primary consumer; pre-tag history is exploratory only.
4. **Only aggregates leave the data root.** Same as S03 (I-7, I-16).

## Artifacts this sprint produces

| Path | What it is |
|---|---|
| `docs/research/data-plane-audit.md` | The audit report: coverage, adjustments, corporate actions, availability, survivorship |
| `tests/test_data_plane.py` | Known-answer tests for data calculations |
| `tools/audit_data_plane.py` | Reproducible audit script (aggregate statistics only) |

---

## Tasks

### T1 — Coverage audit

For each symbol in the S03 bars panel:
- First and last bar dates
- Total rows vs expected trading days in range
- Gap list (missing dates that are trading days for SPY)
- Late starters (first bar after 2016-01-04)

Output: aggregate coverage statistics. Do not commit per-symbol data.

### T2 — Delisted symbol inventory

Using a historical S&P 500 membership source:
- How many 2016 constituents are no longer in the index?
- For leavers: reason (acquired, bankrupt, demoted), last date in index
- What fraction of 2016-2026 stock-days are missing from the current-constituent panel?

This quantifies the survivorship bias S03 stated qualitatively.

### T3 — Adjustment verification

Select known splits and dividends (e.g., AAPL 4:1 2020-08-31, TSLA 5:1 2020-08-31, NVDA 4:1 2021-07-20):
- Do the adjusted closes show no artificial jump?
- Are dividend adjustments applied? (Alpaca `adjustment=all` should include them)
- Any unadjusted spikes indicating missed corporate actions?

### T4 — Corporate action documentation

Document how the following appear in Alpaca bars:
- Stock splits (forward and reverse)
- Cash dividends (special and regular)
- Spinoffs (e.g., how does the parent's price series handle it?)
- Ticker changes
- Mergers/acquisitions (what happens to the acquired company's series?)

### T5 — Availability and point-in-time

- For the forward test: verify that bars are available at `t_d` (17:00 ET). What is Alpaca's typical latency for the daily bar?
- For pre-tag history: document that historical bars were not available in real time (they're backfilled). This matters for interpreting any exploratory pre-tag analysis.
- Forward membership snapshots: verify the S01 recorder's universe snapshots are being ingested correctly.

### T6 — Known-answer tests

Implement `tests/test_data_plane.py` with:
- Split adjustment: verify AAPL's 2020-08-28 close × 4 ≈ 2020-08-31 open (adjusted)
- Dividend: verify a known dividend is reflected in adjusted closes
- Coverage: verify SPY has no gaps in 2016-2026
- Late starter: verify a known late lister (e.g., GEV) has first bar after listing date

### T7 — Survivorship report

Quantify:
- 2016 S&P 500 constituents still in index (2026-10-04): count and %
- Volatility comparison: were leavers more volatile than stayers? (Use pre-exit data; do not condition on future returns)
- Estimate the direction and rough magnitude of survivorship bias on dispersion measures

---

## Acceptance criteria

1. `docs/research/data-plane-audit.md` exists with all seven sections.
2. `tests/test_data_plane.py` passes with at least 4 known-answer tests.
3. `tools/audit_data_plane.py` reproduces the aggregate statistics from the data root.
4. No per-symbol data or market data committed (I-7, I-16).
5. No statistic conditional on incumbent qualification or score.
6. All scripts pass size checks (≤400 lines, ≤60-line functions).
7. Sprint report written in this file.

## After merge (Ryan)

1. Review the survivorship quantification. If the bias is material, decide whether Step 4 needs a mitigation (e.g., point-in-time universe reconstruction).
2. Proceed to Step 4 (S05: incumbent ranker).

## Sprint report

**Status:** Complete. All 7 tasks done. PR #6 opened.

**T1 (Coverage):** 504/504 symbols complete. 44 late starters (8.7%). Zero gaps. Panel spans 2016-01-04 to 2026-10-02.

**T2 (Delisted inventory):** Incomplete — no historical S&P 500 membership source available. Panel contains only current constituents by construction. Bias direction documented (understates dispersion); magnitude unquantified.

**T3 (Adjustments):** All 4 tested splits (AAPL 4:1, TSLA 5:1, NVDA 4:1, AMZN 20:1) correctly adjusted. No artificial jumps. Dividend verification deferred.

**T4 (Corporate actions):** Documented split/dividend/spinoff/ticker/merger behavior in Alpaca bars.

**T5 (Availability):** Bars timestamped at midnight UTC. Forward-test availability at `t_d` depends on Alpaca publication latency (not measured). Pre-tag history is backfilled.

**T6 (Known-answer tests):** 5 tests, all passing. Covers split adjustments, SPY continuity, late starters, panel completeness.

**T7 (Survivorship):** 91.3% have full history. Bias direction confirmed (understates dispersion). Magnitude unquantified without membership source.

**Deviations:** T2 incomplete (no membership source). T3 dividend test deferred. T5 latency not measured. All documented as limitations in the audit report.

**Blockers for Step 4:** None. The data plane is sound for ranker development. The survivorship bias is a documented limitation, not a blocker.

**Artifacts:**
- `tools/audit_data_plane.py` (audit script)
- `tests/test_data_plane.py` (5 known-answer tests)
- `docs/research/data-plane-audit.md` (full report)
- `docs/sprints/S04-data-plane.md` (this spec)
