# S03 — Pre-Tag Power Measurement

| | |
|---|---|
| **Branch** | `feat/s03-pre-tag-power` |
| **Repository** | `millerrc18/arcis` (public). Market data stays under the data root; only aggregate statistics are committed. |
| **Depends on** | S01 merged (scaffold, tooling, `config/universe.csv`, the data-root guard). S02 T3 and T4 done (legacy candidate counts; `incumbent_v1` frozen). Alpaca keys passing S01 T1's credential check. |
| **Ledger row** | None. This sprint adds no package; it produces one script, one report, and the figures PREREGISTRATION.md §2.1 and §3.2 record. |
| **Invariants** | I-7 data outside the repo and sync folders · I-12 no blind exception handling · I-16 nothing private and no market data in a public repo · this sprint's own rule: no signal-conditional statistic |
| **Runs** | After S01 merges and S02 T4; finishes before `prereg-v1` (SCOPE §5 Step 2m, D-024) |
| **Tasks** | 5 |

## Why this sprint exists

PREREGISTRATION.md §2.1 and §3.2 require the minimum detectable effects "computed on the actual panel before
tagging", from measured dispersion and within-date correlation. The only figures in hand are R07's, which assume
about 100 names; the universe is the S&P 500 (D-012). RESEARCH-QUESTIONS.md scheduled the measurement for
Step 3, after the tag, and neither S01 nor S02 performs it.

The gap matters. A rough calculation from R03's dispersion puts the 24-month §2.1 minimum detectable effect at
about 32, 23, and 15 bp if the incumbent qualifies 1%, 2%, and 5% of stock-days, before any inflation from
overlapping labels. That straddles the 25 bp minimum effect (D-022). Without this sprint, the Q1 clock would start
with no evidence that the test can detect the effect it exists to detect.

The measurement must not turn into a backtest. Splitting historical returns by the incumbent's qualification, or by
any score, would be an unregistered look at the answer Q1 is designed to give (PREREGISTRATION.md §0 rule 5). This
sprint therefore measures second moments across all stock-days and estimates power with synthetic effects placed on
randomly chosen stock-days.

## Hard scope

**In:** a credential and access check; daily bars for the current S&P 500 constituents and SPY from 2016 into the
data root; news metadata counts for the most recent 12 months; second-moment statistics by horizon; power
simulations for §2.1 and §3.2; the measured figures recorded in PREREGISTRATION.md; one report.

**Out:** any return, mean, hit rate, or statistic conditional on the incumbent's qualification, its score, or any text
score; loading `config/incumbent_v1.yaml`; implementing the ranker, cost model, or simulator (Steps 4–5); retaining
article text (metadata only, `include_content=false`); committing bars, news metadata, or per-stock series; changing
any preregistered threshold.

If a task appears to need anything from **Out**, stop and write it up in the sprint report.

## Ground rules

1. **Second moments only.** The code computes dispersions, correlations, autocorrelations, and counts. It never
   computes a return conditional on a signal, and it never reads the incumbent's rules.
2. **Synthetic effects only.** Power comes from injecting a known effect into randomly assigned stock-days, never
   into stock-days a real signal selects. The qualification rate is an input taken from S02's legacy candidate
   counts, not measured by applying rules to history.
3. **State both biases.** The §2.1 label is a bracketed trade that needs the Step 5 simulator. An unbracketed
   15-session forward return stands in for it; brackets truncate the label, so this proxy overstates dispersion and
   pushes the minimum detectable effect up. Current-constituent bars omit names that left the index, which were
   likely more volatile, so dispersion is understated and the effect is pushed down. The report states both and
   does not call the result conservative.
4. **Only aggregates leave the data root.** Bars, news metadata, and per-stock series stay under the data root
   (I-7, I-16). The report and PREREGISTRATION.md carry aggregate statistics and minimum detectable effects only.
   Whether Alpaca's terms allow publishing aggregates derived from its market data is an OD-8 question (RESEARCH-QUESTIONS.md, "Alpaca, in writing").

## Artifacts this sprint produces

| Path | What it is |
|---|---|
| `tools/measure_power.py` | Measurement and simulation, reproducible from the data root with recorded seeds |
| `docs/research/power-measurement.md` | The report |
| PREREGISTRATION.md §2.1 and §3.2 | The measured minimum detectable effects, replacing the planning figures |

---

## Tasks

### T1 — Credential and access check

- Call `GET https://paper-api.alpaca.markets/v2/account`. A 401 means the keys are invalid: fix them and rerun,
  as in S01 T1.
- Request daily bars (`/v2/stocks/bars`, `timeframe=1Day`, `adjustment=all`) for three symbols from 2016-01-01,
  and news metadata (`/v1beta1/news`, `include_content=false`) for the same symbols over the last 30 days.
- Record the status codes, the earliest bar date returned, the data feed, and the rate-limit headers. Inspect
  responses in memory and record field names only.

**Done when:** the access facts are in the report and no response body was written outside the data root.

### T2 — Pull the panel into the data root

- Daily bars for every symbol in `config/universe.csv` plus SPY, 2016-01-01 through the latest close,
  `adjustment=all`, written under `raw/bars/` in the data root through S01's data-root guard, with a manifest
  (symbols, date range, row counts, SHA-256).
- News metadata for the most recent 12 months with `include_content=false`: per stock-day, the article count and
  the earliest `created_at` only.
- Coverage: symbols with no bars, symbols whose first bar is after 2016, and gaps.

**Done when:** the manifests exist, coverage is in the report, and nothing under the data root is tracked by git.

### T3 — Second moments by horizon

For horizons of 1, 2, 5, 10, and 15 sessions, measured from the first tradable point after the close:

- the cross-sectional standard deviation of raw, market-adjusted, and beta-adjusted forward returns (rolling
  252-session betas, as in PREREGISTRATION.md §2.5), pooled and by calendar year;
- the within-date correlation of residuals after removing date means, the quantity that date-clustered errors
  depend on, pooled and by year;
- the first-order autocorrelation of each stock's overlapping forward returns;
- from T2's news counts, the share of stock-days with at least one article and the distribution of article counts.

No statistic in this task is conditioned on any signal, rule, or score.

**Done when:** the tables are in the report, each citing the function that produced it.

### T4 — Power simulations

A date-block bootstrap of the real residual panel (20-session blocks), with synthetic effects injected into randomly
assigned stock-days, at least 2,000 replications per cell, seeds fixed and recorded, results shown with simulation
standard errors.

- **§2.1:** one-sided α = 2.5% on `b_Q`, date fixed effects, date-clustered errors, the beta-adjusted 15-session
  forward return as the label proxy. Qualification rates of 0.5%, 1%, 2%, 5%, and 10% of stock-days, plus the
  planning rate from S02 T3's candidate counts. Report the effect detectable with 80% power at the 12- and
  24-month looks.
- **§3.2:** Q2 and Q3 as co-primary hypotheses under Holm at a family α of 2.5%, the 1-day beta-adjusted outcome,
  and the news-bearing share from T3. Report the effect detectable at 12 and 24 months, per one-standard-deviation
  score difference as R07 did.

**Done when:** both tables exist and the script reproduces them from the recorded seeds.

### T5 — Record, report, and PR

- Put the measured figures into PREREGISTRATION.md §2.1's power line and §3.2's planning-power line, citing the report.
- If the 24-month §2.1 effect at the planning qualification rate exceeds the 25 bp minimum effect (D-022), say so in
  the report's first paragraph and propose a SCOPE §9 entry: the test cannot detect its own minimum effect, and
  `prereg-v1` waits for a decision.
- Write `docs/research/power-measurement.md`: access facts, coverage and survivorship limits, both proxy biases, the
  tables, and a plain statement that no signal-conditional statistic was computed.
- Update the research log's Supersession Map (the measurement supersedes R07's 100-name table), the README
  documentation map, the CHANGELOG, and this sprint report. Open the PR.

**Done when:** the PR is open, CI is green, and PREREGISTRATION.md §2.1 and §3.2 hold measured figures.

---

## Acceptance criteria

1. No bars, news metadata, or per-stock series are tracked by git; the data is under the data root (I-7, I-16).
2. A test asserts the script never opens `config/incumbent_v1.yaml`, and the PR description confirms that no
   signal-conditional statistic was computed.
3. The §2.1 table covers every listed qualification rate at 12 and 24 months; the §3.2 table covers 12 and
   24 months; both reproduce from recorded seeds.
4. PREREGISTRATION.md §2.1 and §3.2 carry the measured figures in place of the planning figures.
5. The report states both biases: the unbracketed label overstates dispersion, and survivorship understates it.
6. If the 24-month §2.1 effect exceeds 25 bp at the planning rate, the report opens with that and a §9 entry is proposed.
7. The script passes the size and hygiene checks. `numpy` and `pandas` are added only as a `research` dependency
   group, justified in the sprint report.

## After merge (Ryan)

1. Read both tables. If the §2.1 test cannot detect 25 bp at 24 months, decide before the tag: accept an
   underpowered test, lengthen the efficacy look, or revisit the minimum effect.
2. Tag `prereg-v1` (SCOPE §5 Step 2t).

## Sprint report

**Completed 2026-10-04.** All five tasks done. PR #5 opened, reviewed by Pip (approve) and Claude Code (reject with 7 blocking findings). All blocking findings addressed in a second push:

1. **Planning rate:** replaced the unverifiable 17.5% (S02's rough 15–20% on S&P 100) with a preregistered 5% forward parameter for the S&P 500 universe (≈25 names/day). The legacy archive contains only closed trades, not daily qualification records, so the exact rate could not be computed.
2. **Label horizon:** Family A now uses the spec-compliant 15-session beta-adjusted forward return (was 10-session, undeclared).
3. **News share:** 7.74% with reproducible NY-timezone methodology (was 8.0% with unclear UTC bucketing).
4. **Clean-room guard:** `raise RuntimeError` instead of `assert` (survives `python -O`); added `tests/test_s03_cleanroom.py` with AST verification that no script opens the incumbent file (acceptance criterion 2).
5. **News pagination:** raises `RuntimeError` on truncation instead of silently stopping at the page cap.
6. **Size limits:** all scripts refactored to ≤400 lines / ≤60-line functions; `tools/checks.py` now checks `tools/` as well as `src/`.
7. **Missing outputs:** Family B now reports 12-month MDE (6.3 bp); all cells include binomial power SEs (≈0.9pp at 80% power).

**Results:** 24-month §2.1 MDE at 5% planning rate is **18.3 bp** (< 25 bp minimum effect; power at 25 bp is 0.98). §3.2 MDE is 6.3 bp (12 mo) / 4.3 bp (24 mo), within the realistic 3–8 bp range. **prereg-v1 is clear to proceed.**

**Deviations:** four scripts instead of the single `tools/measure_power.py` (size-limit compliance); planning rate is a forward parameter, not S02-derived.

**Dependencies added to research group:** `numpy` (explicit; was transitive via pandas), `pandas`, `pyarrow` (parquet), `requests` (Alpaca API — newly added, not pre-existing), `scipy` (`stats.norm.ppf` for power thresholds).

---

## Ralph Loop log (spec review before hand-off)

**Pass 1 — draft (2026-09-24).** Five tasks: access check, panel pull, second moments, power simulation, record.

**Pass 2 — contamination and bias review.**

1. §2.1's minimum detectable effect depends on how often the incumbent qualifies, and the obvious way to measure
   that, applying the rules to history, puts a qualification flag next to historical returns. That is one line of
   code away from an unregistered look at Q1. The sprint never reads the rules; the rate comes from S02's legacy
   candidate counts, and every effect in the simulation is synthetic and randomly placed.
2. The §2.1 label needs the Step 5 simulator, which does not exist before the tag. An unbracketed 15-session
   return stands in for it, and the direction of that bias is stated.
3. Current-constituent bars understate dispersion through survivorship, which works against the proxy's bias. The
   report states both rather than calling the figure conservative.
4. Publishing aggregate statistics derived from Alpaca bars is a terms question like the one that took Finnhub out
   of scope (D-023). It was added to the OD-8 questions in RESEARCH-QUESTIONS.md.
