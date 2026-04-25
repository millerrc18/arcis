# Halcyon-Lab Trading Readiness Audit (v3 — Path-Verified)

## 0. Revision Notes

v3 keeps every v2 content fix and replaces fabricated paths with Glob-verified real paths. Restores T1.04 CAP-reconciliation primary intent. Restores v1's F-1..F-18 numbering (V3-4). Preserves §3.1 decision matrix, §3.2 methodology table, §5 canonical Sharpe, §9 sign-off, T1.01 cutoff details, task decompositions, must-fail tests, DA-9/DA-10, Appendix B (V3-3).

v3 path corrections vs v2 (fabrications removed):
- `src/strategies/{mr,pullback,breakout}/` — DO NOT EXIST. Pullback signal is `src/ranking/ranker.py:486-541, 611` + `src/features/engine.py:285`. MR signal is `src/features/mean_reversion.py:88, 139-194`. Setup classifier is `src/features/setup_classifier.py`.
- `src/risk_governor/`, `src/live_trading/`, `src/bootcamp/` — NOT Python directories; they are config-key prefixes in `config/settings.local.yaml`. Sole governor module is `src/risk/governor.py`. Peer cap-reader is `src/shadow_trading/executor.py:_governor_cap` lines 104-113.
- `src/metrics/canonical_sharpe.py` — parent doesn't exist. Canonical lives at `src/analytics/canonical_sharpe.py` (NEW; `src/analytics/spy_benchmark.py` sibling exists).
- Bracket builder is `src/packets/template.py:154-186` (lines 163-170 hardcode multipliers).
- `src/brokers/alpaca/*` → `src/shadow_trading/{alpaca_clients,alpaca_adapter}.py`.
- `src/plugins/*` → `src/platform/{strategy_plugin,plugin_registry}.py`.
- `src/_archived/` — DOESN'T EXIST. Lazy-prices is the YAML at `src/platform/specs/lazy_prices_v1.yaml`.

T1.04 restored: primary task = effective_position_cap helper across 4 namespaces; CI enabled-flag guardrail retained as side feature.

## 1. Executive Summary

Five integrity issues degrade the live-paper signal: (1) pre-#651 trades polluting baseline, (2) **four** Sharpe formulas across ~12 call sites, (3) fail-OPEN safety surfaces, (4) bracket multipliers hardcoded in `src/packets/template.py:154-186` ignoring `strategies.{name}.stop_atr_*` config keys, (5) absent Alpaca startup probe.

**Verdict:** GO Mon 2026-04-27 with $100 cap in *warm-start* mode (positions reconciled, account live, NO new orders) until Stage-1 baseline memo is signed off. Once memo signed, $100 cap deploys; ramp gated on §3.1 decision matrix.

**Methodology:** ALL of CPCV + block bootstrap + MC permutation + PSR + MinTRL + White RC. MinTRL diagnostic. Promotion = ≥4 of 5 gating methods at α=0.05.

## 2. Three Tracks

Track 1 (Mon-blocking): T1.01, T1.05, T1.03, T1.04, T1.06, T1.07, T1.02. Track 2 (multi-week): T2.01–T2.18. Track 3 (continuous): T3.01, T3.02.

## 3. 3-Stage Roadmap

### Stage 1 — Recomputed Baseline (Monday, blocking)

### 3.1 Stage-1 Decision Matrix

| Case | Condition | Action |
|------|-----------|--------|
| (a) Green | S ≥ 0 AND t ≥ +1.5 AND CI lower > -0.2 | Deploy $100 Mon post-memo; ramp |
| (b) Hold | -0.2 < S < 0 OR \|t\| < 1.5 | Stay $100, NO ramp; re-eval after 20 sessions |
| (c) Halt | S < -0.2 OR t < -1.5 | Halt live; rollback paper; F-1 root-cause |

**Warm-start semantics:** Account live + reconciled but NO orders until memo signed. Mon EOD timeout → warm flat through Tue. Tue EOD → no-go paper-only.

**Ramp:** $100 → $250 → $500 → $1000 (weekly, conditional on case (a)).

### 3.2 Stage-2 Promotion Gate Pass-Criteria Table

| # | Method | Pass (α=0.05) | Inverse hard-block |
|---|--------|---------------|--------------------|
| 1 | CPCV | mean OOS Sharpe > 0, p < 0.05 | mean < 0, p < 0.10 |
| 2 | Block bootstrap | CI lower > 0 | CI upper < 0 |
| 3 | MC permutation | p < 0.05 | obs < median(perm) AND p < 0.10 |
| 4 | PSR | PSR > 0.95 | PSR < 0.10 |
| 5 | White RC | nominal-p < 0.05 | nominal-p > 0.90 |
| Diag | MinTRL | reported only | N/A |

Promotion = ≥4 of 5 gating methods pass AND zero inverse hard-blocks. If N < MinTRL, defer.

### Stage 3 — Excess-Sharpe > 1.0 (conditional on T2.14a/b/c pullback redesign)

## 4. Findings (F-1..F-18)

- **F-1 (ELEVATED, blocker)** — Pre-#651 quarantine. T1.01 + T1.05 propagate to attribution_trades + walkforward_trades. Schema: `src/schema/registry.py` line ~273.
- **F-2** — Multiple Sharpe definitions (12 call sites, 4 formulas):
  - PROD √n at `src/journal/stats.py:114-130`; consumer `src/notifications/telegram.py:1011-1023`. MIGRATE.
  - BACKTEST √252 at `src/platform/metrics.py:32-48`; downstream `src/platform/rigor/walkforward.py`, `walkforward_runner.py`, `walkforward_metrics.py`. MIGRATE preserving API.
  - THIRD √150 at `src/api/cloud_routes/trades.py:58-69` + `src/evaluation/cto_report.py:239-246`. MIGRATE.
  - FOURTH raw at `src/platform/rigor/cscv.py:37-45` → RENAME `_sharpe_for_pbo` (scale-invariant).
  - `src/evaluation/statistics.py:18-23` raw KEEP (`gate_evaluator.py:58` correct); duplicate PSR at lines 34-42 DELETE (canonical PSR at `src/platform/rigor/dsr.py:50-64`); MinTRL at lines 45-54 zero consumers.
  - `src/evaluation/model_monitor.py:61-66, 280-285` raw KEEP; `src/scheduler/reports.py:837` raw KEEP.
  - `src/evaluation/backtester.py:140-145` stride-5 sampler — ESCALATE on review.
  - Schema-stored Sharpe columns at `src/schema/registry.py:1766, 1887-1889, 2007-2008, 2136-2137, 2205-2206` — preserved.
  - Canonical: `src/analytics/canonical_sharpe.py` (NEW).
- **F-3** — Risk governor `enabled=False` regression. T1.04 part b: CI test fails on committed configs with `enabled: false`.
- **F-4** — `is_connected` returns True before SDK handshake. T2.17.
- **F-5** — No Alpaca REST probe. T1.07.
- **F-6 (ELEVATED, blocker)** — Bracket math hardcoded at `src/packets/template.py:154-186` (lines 163-170: `stop_distance=2*atr`, `target_prices=[price+1.5*atr, price+3.0*atr]`). Config keys `strategies.pullback.stop_atr_multiplier=2.0` (line 210) and `strategies.mean_reversion.stop_atr_multiple=2.5` (line 221, note `_multiple` singular) NOT read by template.py. T1.06 modifies template.py + callers `src/services/scan_service.py` + `src/services/mr_scan_service.py`.
- **F-7..F-18** — CPCV/bootstrap/permutation/PSR/White-RC/PBO absent (T2.01-T2.06); cost calibration unwired at `src/platform/cost_calibration.py:37-95` (T2.07/T2.08); universe lookahead at `src/evaluation/backtester.py:45-46` using biased `src/universe/sp100.py:31-136` (T2.09); F-16 STALE per `docs/superpowers/plans/2026-04-24-tier-a-b-rootcause-bundle.md` test #510 — verify-then-skip in T2.10; calendar inconsistency at `src/scheduler/holidays.py:14-25` (T2.11); allocator stub (T2.12a/b).

## 5. Canonical Excess Sharpe

```
rf_adjusted_excess_sharpe(returns) = mean(returns - rf_period) / std(returns - rf_period, ddof=1) * sqrt(252)
```

Diagnostic variants: `raw_sharpe`, `spy_relative_sharpe`. All gates measure on canonical. T1.03 implements `src/analytics/canonical_sharpe.py` (NEW).

## 6. Strategy / Signal-Layer Decisions

- **6.1 Pullback** — Signal IS the score at `src/ranking/ranker.py:486-541, 611`. `setup_type` stamped at `src/features/engine.py:285` but never consulted by `_score_ticker` (Grep-confirmed). Redesign T2.14a/b/c lands under NEW `src/scoring/pullback_logistic/`. Existing `_score_ticker` retained as fallback during cutover (config-flag gated).
- **6.2 Mean Reversion** — Keep entry at `src/features/mean_reversion.py:88` and exit at `:139-194`. Fix bracket via T1.06.
- **6.3 Setup classifier** — `src/features/setup_classifier.py` 6-class with 4 dead labels. T2.13 deletes dead labels only.
- **6.4 Lazy-prices** — Spec at `src/platform/specs/lazy_prices_v1.yaml` (no Python directory). T2.15 adds `status: shelved` + `revival_criteria` block in place.
- **6.5 Capital allocator** — NEW `src/allocator/`. T2.12a/b.
- **6.6 Plugin interface** — `src/platform/strategy_plugin.py:34-71` + `src/platform/plugin_registry.py:19-43`. Grep zero `@register_plugin` in src/. T2.18 deletes (-300 LOC), sequenced after T2.15.

## 7. Benchmark Decision

Primary: rf-adjusted excess Sharpe (canonical). Secondary: SPY-relative (diagnostic). Factor-model alpha → Stage 3 (T2.16a/b).

## 8. Methodology Toolkit

All 6 methods wired. New code under NEW `src/methods/`. T2.01-T2.06.

## 9. Pre-flight Monday Checklist (10 items, all GREEN required)

1. Pre-#651 quarantine across shadow_trades + propagation (T1.01, T1.05).
2. Canonical Sharpe live; F-2 sites migrated (T1.03).
3. Effective position cap reconciled across 4 namespaces (T1.04 part a) — startup-logged.
4. CI guardrail fails if any committed `config/settings*.yaml` has `risk_governor.enabled: false` (T1.04 part b).
5. `is_connected` + 4 surfaces fail-CLOSED (T2.17).
6. Bracket multipliers read from `strategies.{pullback|mean_reversion}.stop_atr_*` end-to-end (T1.06).
7. Alpaca REST probe; 5 endpoints 200 within 5s (T1.07).
8. Stage-1 baseline against quarantined-clean (T1.02).
9. **Memo signed off:**
   - Path: `audits/2026-04-27/stage1_baseline_memo.md`.
   - Contents: raw + SPY-relative + rf-adjusted Sharpe; 95% block-bootstrap CI; N-trades; methodology hash; pre-#651 exclusion count; canonical Sharpe SHA; FRED rf series version.
   - Sign-off: git commit with `Signed-off-by: <operator email>` matching `arcis.yaml` `operator.email` (fallback `config/settings.local.yaml` if `arcis.yaml` not present — verify at task start).
   - Timeout: Mon EOD → warm flat Tue; Tue EOD → no-go paper-only.
   - T1.07 verification: parses Signed-off-by; non-zero exit on fail.
10. **Transcript saved** at `audits/2026-04-27/preflight_transcript.txt` (T1.07).

## 10. Open Questions

- Warm-start semantics OK?
- Hold-window 20 sessions or longer?
- N=150 fixed or adapt to MinTRL?
- T1.04 helper at top of `src/risk/governor.py` (default) vs new `src/risk/cap_utils.py`?

## 11. Out of Scope

IB integration; live ML retraining; new strategy classes beyond pullback redesign; UI; multi-account; crypto/FX; rename of `_multiplier` vs `_multiple` (separate PR).

## Appendix A — Glob-verified file references

**Verified-real:** `src/risk/governor.py` (sole governor; no `src/risk_governor/`, `src/live_trading/`, `src/bootcamp/`); `src/shadow_trading/executor.py:104-113` `_governor_cap`; `src/packets/template.py:154-186` (bracket); `src/services/{scan_service,mr_scan_service}.py`; `src/ranking/ranker.py:486-541, 611`; `src/features/{mean_reversion,setup_classifier,engine}.py`; `src/journal/stats.py:114-130`; `src/notifications/telegram.py:1011-1023`; `src/platform/metrics.py:32-48`; `src/platform/rigor/{walkforward,walkforward_runner,walkforward_metrics,cscv,dsr,walkforward_universe}.py`; `src/api/cloud_routes/trades.py:58-69`; `src/evaluation/{cto_report,statistics,gate_evaluator,model_monitor,backtester}.py`; `src/scheduler/{reports,holidays}.py`; `src/analytics/{__init__,spy_benchmark}.py`; `src/data_ingestion/market_data.py`; `src/universe/sp100.py:31-136`; `src/platform/{strategy_plugin,plugin_registry,cost_calibration,promotion}.py`; `src/platform/specs/{lazy_prices_v1,post_audit_ruleset_v1}.yaml`; `src/schema/registry.py`; `tests/test_tier_1_5_hygiene.py:43`; `tests/risk/test_governor_disabled_alert.py`; `config/settings.{local,example}.yaml`; `src/trading/ib_broker.py` (read-only, dormant).

**NEW (created by tasks):** `src/analytics/canonical_sharpe.py` (T1.03); `src/methods/` directory + `cpcv.py`/`block_bootstrap.py`/`mc_permutation.py`/`psr.py`/`promotion_gate.py`/`white_rc.py`/`pbo.py`/`cost_sensitivity.py`/`factor_alpha_core.py`/`factor_alpha_wiring.py` (T2.01-T2.06, T2.08, T2.16a/b); `src/data_ingestion/risk_free_rate.py` (T2.10); `src/scheduler/holidays.py` extended via T2.11; `src/allocator/{risk_parity_core,wiring}.py` (T2.12a/b); `src/scoring/pullback_logistic/{features,model,score}.py` (T2.14a/b/c); `audits/2026-04-27/{stage1_baseline_memo.md, devils_advocate_stage1.md, preflight_transcript.txt}` (T1.02, T1.07, T3.01); `scripts/{quarantine_pre_651,quarantine_propagation_migration,preflight_monday,stage1_baseline_recompute,independent_baseline_recompute}.py`; `tests/test_config_guardrails.py`, `tests/risk/test_cap_reconciliation.py` (T1.04); other co-located NEW test files.

## Appendix B — Pre-registered counter-arguments (preserved from v1/v2)

- 'Stage 1 is torture-tested fitting' → T3.01 + T3.02 independent recompute against direct sqlite3; >5% divergence reopens F-1.
- '≥4 of 5 promotion is data-snooping' → each method pre-registered (§3.2).
- '$100 too small to learn' → §3.1 ramp scales to $1000 by week 4.
- 'Probe fails Monday' → T1.07 transcript; warm + flat; rollback only on negative Sharpe per §3.1(c).