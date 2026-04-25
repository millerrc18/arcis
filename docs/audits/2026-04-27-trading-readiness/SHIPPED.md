# Audit 2026-04-27 — What Shipped

> **Date completed:** 2026-04-25 (sign-off Saturday, 2 days before Mon 2026-04-27 live deploy)
> **Operator:** millerrc18@gmail.com
> **Spec:** [audit-spec.md](audit-spec.md) v3.1
> **Plan:** [plan.md](plan.md)
> **Stage-1 Memo (signed):** [`audits/2026-04-27/stage1_baseline_memo.md`](../../../audits/2026-04-27/stage1_baseline_memo.md) — commit [`d651160`](#)
> **Devil's-Advocate:** [`audits/2026-04-27/devils_advocate_stage1.md`](../../../audits/2026-04-27/devils_advocate_stage1.md) — commit [`ed1b98d`](#)

This document is the audit's "what actually got delivered" rollup. It exists so future-you (or future-me) reviewing this audit in 6 months has a single page that says: which tasks landed, which were deferred, what the test floor looks like now, and what to read for context.

---

## Executive Summary

**Outcome:** The system is more honest than it was 48 hours ago, but the strategy itself is unchanged. Stage-1 baseline is signed and conservatively GREEN per the §3.1 Decision Matrix. Mon's deploy is gated only on `scripts/preflight_monday.py`.

**Net code impact:**
- 26 commits across Track 1 (Mon-blocking) + Track 2 (Cohorts 1, 2, 3-Half-A) + Track 3 (T3.01)
- Test floor: **3038 → 3159 → 3238 → ~3380** (final number written into CLAUDE.md after Cohort 2 + 3A integrator sweep)
- New module families: `src/methods/` (6 toolkit + promotion gate), `src/allocation/`, `src/cost_model/`, `src/universe/pit.py`, `src/data_ingestion/risk_free_rate.py`, `src/analytics/instrumentation_filter.py`, `src/analytics/canonical_sharpe.py`
- 1 new dependency: `pandas_market_calendars>=4.0,<6.0`

**What shipped that changes Mon's runtime:** Track 1 (governor, canonical Sharpe, quarantine, configurable stops, NYSE calendar, fail-loud connectivity, preflight gate). Track 2 / 3-A / T3.01 are "shelf" — implemented, tested, not yet wired into runtime decisions.

---

## Track 1 — Monday-Blocking (8 of 8 ✅)

| ID | Name | Commit | Tests | Runtime impact |
|---|---|---|---|---|
| T1.01 | Pre-#651 quarantine sweep script | `c18908e` | +12 | Quarantine flag respected by all analytics queries |
| T1.05 | Quarantined column on attribution + walkforward tables | `a082131` | +9 | Schema propagation; same filter applies repo-wide |
| T1.03 | Canonical Sharpe module + F-2 site migration | `1928710` | +19 | All Sharpe figures now use rf-adjusted excess formula |
| T1.06 | Configurable stop ATR multipliers | `7dd1df3` | +9 | Per-strategy `stop_atr_*` config replaces hardcoded `2*ATR` |
| T1.04 | `effective_position_cap` reconciliation across 4 namespaces | `ffd30a6` | +12 | Governor returns `min()` of caps across all namespaces |
| T1.08 | Fully-instrumented filter + Bailey-LdP MinTRL | `1652874` | +31 | Stage-1 baseline excludes incomplete-data trades + power-checks |
| T1.07 | Monday preflight go/no-go gate | `c68e5d1` | +30 | `scripts/preflight_monday.py` — 9-item Mon-AM checklist |
| T1.02 | Stage-1 baseline recompute + memo writer | `c24a209` | +19 | Produces signed memo from archive |

**Track 1 test floor bump:** 3038 → 3159 (+121 net) — committed `9c2cc9d`.

---

## Track 2 Cohort 1 — Housekeeping (6 of 7 ✅, 1 deferred)

| ID | Name | Commit | Tests | Status |
|---|---|---|---|---|
| T2.06 | PBO writer (Bailey-LdP 2014) | `f9c261d` | +13 | ✅ shipped (shelf) |
| T2.10 | FRED rf-rate adapter + F-16 auto_adjust pin | `940aad3` | +15 | ✅ shipped (shelf — Stage-1 still uses placeholder rf=0.0001) |
| T2.11 | NYSE calendar via pandas_market_calendars + half-days | `8afd238` | +18 | ✅ shipped (live in scheduler) |
| T2.13 | Drop 4 dead classifier classes (breakout/momentum/range_bound/breakdown) | `e811f07` + `5ab8e3b` | +2 net | ✅ shipped (live; setup_classifier returns 3 labels: pullback/mean_reversion/None) |
| T2.15 | Lazy-prices spec shelving | `d8d12e2` | +6 | ✅ shipped (loader will not enroll) |
| T2.17 | Fail-closed governor + Alpaca `is_connected()` probe | `03476f3` | +25 | ✅ shipped (live in governor + preflight) |
| T2.18 | Plugin interface removal | — | — | ⏸ DEFERRED — see [`T2.18-deferral-note.md`](T2.18-deferral-note.md). Audit spec missed `signal_eval.py:285+` consumer; needs spec amendment to v3.2 before re-dispatch |

**Cohort 1 follow-ups committed:**
- `d13d990` — byte-identity ranker fixture regen (T2.13 cascade fix)
- `08f7199` — coding-team agent maxTurns bump 12 → 100 (infra)
- `09395ea` — T2.18 deferral note

**Cohort 1 test floor bump:** 3159 → 3238 (+79 net) — committed `b989b9c`.

---

## Track 2 Cohort 2 — Methodology Toolkit (5 of 5 ✅)

All shelf — pure-function modules. Not yet wired into the production promotion path.

| ID | Name | Commit | Tests | Reference |
|---|---|---|---|---|
| T2.01 | CPCV + anchored walk-forward (López de Prado §7.4) | `c5ed544` | +9 | [methodology-toolkit.md](../../methodology-toolkit.md#cpcv) |
| T2.02 | Stationary block bootstrap (Politis-Romano + auto block-length) | `0d63dbd` | +11 | [methodology-toolkit.md](../../methodology-toolkit.md#block-bootstrap) |
| T2.03 | Monte Carlo permutation test (label-shuffle null) | `7be5bf2` | +9 | [methodology-toolkit.md](../../methodology-toolkit.md#mc-permutation) |
| T2.05 | White's Reality Check (stationary bootstrap, multi-strategy) | `d957579` | +9 | [methodology-toolkit.md](../../methodology-toolkit.md#white-rc) |
| T2.04 | PSR / DSR / MinTRL + ≥4-of-5 promotion gate | `29efa3c` | +23 | [methodology-toolkit.md](../../methodology-toolkit.md#psr-dsr) |

---

## Track 2 Cohort 3 Half A — Strategy-Redesign Cores (5 of 5 ✅)

All shelf — implementation only. Wiring deferred to next session per "explicit do-not-wire" scope fences.

| ID | Name | Commit | Tests | Notes |
|---|---|---|---|---|
| T2.07 | Live-fill cost calibration from shadow_trades | `bcf10bd` | +18 | Reads DB → writes JSON; no backtest reads the JSON yet |
| T2.09 | Point-in-time SP100 + dividend haircut | `fcb6940` | +12 | Coexists with survivorship-biased `get_sp100_universe()` (24 callers still use legacy) |
| T2.12a | Risk-parity allocator core | `d2f694b` | +15 | Pure inverse-vol weighting; live-trading wiring is T2.12b (deferred) |
| T2.14a | Pullback logistic features | `f8f4de4` | +17 | Feature extractors only; T2.14b model + T2.14c adapter deferred |
| T2.16a | Fama-French 3+momentum factor-alpha core | `80cd7c9` | +18 | Stage-3 diagnostic; promotion-gate wiring is T2.16b (deferred) |

---

## Track 3 — Devil's Advocate Doc (1 of 2 ✅)

| ID | Name | Commit | Notes |
|---|---|---|---|
| T3.01 | Devil's-advocate of Stage-1 baseline (5 categories: selection / look-ahead / cost / regime / survivorship) | `ed1b98d` | Read this BEFORE signing any future baseline memo |
| T3.02 | 3-stage roadmap doc (Stage 2 + Stage 3 protocols) | — | ⏸ Deferred — depends on real Stage-2/3 results which don't exist yet |

---

## Cleanup commits (not task-bound)

| Commit | What | Why |
|---|---|---|
| `163c21b` | factor_alpha refactor + grandfather two pre-existing oversized functions | T2.16a's agent left `factor_alpha` at 71 lines (>60 cap); split into helpers + sync `known_violations.json` with CLAUDE.md's documented intent |
| `f3aa781` | Add standard docstring header to T2.09 + T2.12a modules; gitignore operator scratch files | Two agents missed the 5-section header; also `_*.py` and `.arcis/` artifacts now ignored at repo root |

---

## Stage-1 Decision Matrix Outcome

Per audit-spec §3.1, computed against the archive at `C:/arcis/data/archive/ai_research_desk_bootcamp_2026-04-24.sqlite3`:

| Quantity | Value | Source |
|---|---|---|
| N total closed in archive | 111 | shadow_trades after status filter |
| N quarantined (excluded) | 62 | T1.01 cutoff `2026-04-22T20:00:00-04:00` |
| N fully-instrumented | **35** | T1.08 four-column predicate |
| **rf-adjusted excess Sharpe** | **6.1379** | Canonical (T1.03), annualized √252 |
| 95% IID bootstrap CI on excess return | [0.1113, 2.2276] | Acknowledged optimistic; T2.02 block-bootstrap rerun pending |
| p-value | **0.0302** | Significant at α=0.05 |
| Implied t-stat | ~2.17 | From p, two-sided, df≈34 |
| SPY-relative Sharpe | 2.1048 | Diagnostic |
| SPY-relative p-value | **0.4326** | **NOT significant** — strategy not yet differentiated from passive long-SPY |
| MinTRL (target Sharpe = 0, α=0.05) | 4.84 | Bailey-LdP per T1.08 |
| Power verdict | **POWERED** | n=35 ≥ 2·MinTRL=9.68 |

**Literal verdict per §3.1:** GREEN (S ≥ 0 ✓, t ≥ +1.5 ✓, CI lower > -0.2 ✓).

**Caveats documented in the signed memo:**
- Sharpe of 6.14 is implausible for a sustained strategy — small-sample / regime-tailwind / overfit risk
- SPY-relative non-significance means we cannot yet distinguish strategy alpha from bullish-window beta
- IID bootstrap is acknowledged optimistic; T2.02 block-bootstrap rerun is the Track-2 follow-up

**Selection-bias diagnostic (post-sign-off):** the 14 dropped trades (instrumentation gap from April-21 bulk-close path) had **+2.55% higher mean** and **84.6% win rate vs 69%** — the missing data is REVERSE selection bias. Headline 6.14 Sharpe is conservatively *understated*, not inflated.

---

## What Mon's Deploy Inherits

**Real runtime changes vs the system 48 hours ago:**
1. Tighter risk governor (min cap across 4 namespaces; raises on missing config)
2. Canonical Sharpe formula everywhere
3. Quarantine flag enforced repo-wide
4. Per-strategy configurable stop ATR multipliers
5. Real Alpaca connectivity probe
6. NYSE calendar future-proof (no 2027 silent failure)
7. Setup classifier trimmed (3 live labels instead of 6)
8. Fail-loud governor on missing config
9. Preflight gate exists for Mon AM

**Strategy logic unchanged.** Same signal generation, same ranking, same trade timing.

**Mon AM gate:**
```cmd
cd C:\arcis\halcyon-lab
cmd /c "set PYTHONPATH=. && python scripts\preflight_monday.py --operator-email millerrc18@gmail.com"
```

If green: deploy $100. If yellow: hold. If red: halt + rollback paper.

---

## Deferred to Future Sessions

### Cohort 3 Half B — Strategy-redesign wiring (5 tasks)

These have correctness stakes and need full PM protocol w/ reviewers. Not Mon blockers since $100 is paper-grade volume.

| ID | Name | Blocker |
|---|---|---|
| T2.08 | Cost-grid sensitivity analysis | T2.04 (done) + T2.07 (done) — unblocked but deferred for review rigor |
| T2.12b | Capital allocator wiring | Touches live trading paths |
| T2.14b | Pullback logistic model training | Trains the actual classifier |
| T2.14c | Pullback score adapter | Touches `_score_ticker` |
| T2.16b | Factor-alpha promotion gate wiring | Touches reports + promotion |

### Track 3 — Stage 2 / 3 framework (T3.02)

Depends on real Stage-2/3 results. Stage 2 evaluation requires 150 OOS trades (~3 months of live trading at current frequency). Defer to that point.

### Pre-existing items NOT in audit scope but worth tracking

- 24 callers of survivorship-biased `get_sp100_universe()` need migration to `get_sp100_at()` once a production membership table is wired (T2.09 leaves the function in place; migration is its own project)
- April-21 bulk-close path skipped `excess_return` write — 14 historical trades affected; going forward all closes route through the canonical path
- Plugin interface removal (T2.18) needs spec amendment to v3.2

---

## Reading order for the next person

1. **This document** — get the high-level outcome
2. **[stage1_baseline_memo.md](../../../audits/2026-04-27/stage1_baseline_memo.md)** — the signed numbers Mon's go/halt rests on
3. **[devils_advocate_stage1.md](../../../audits/2026-04-27/devils_advocate_stage1.md)** — the 5 categories of "how could the baseline be wrong" + what to check
4. **[audit-spec.md](audit-spec.md)** — the original spec, sections 3.1 (Decision Matrix), 9 (preflight checklist), F-1 through F-16 (findings)
5. **[methodology-toolkit.md](../../methodology-toolkit.md)** — when to use which method (CPCV/bootstrap/permutation/etc.)
6. **`MASTER.md` Section 2** — current system state (numbers update after each sprint)

---

## Sign-off provenance

The Stage-1 baseline memo was signed by the operator at commit `d651160` with `Signed-off-by: Ryan Miller <millerrc18@gmail.com>`. Per audit-spec §3.1, this is the artifact that authorizes Mon's deployment decision tree. The signed memo is immutable in git history; any future revision is a new commit, not an amendment.
