# Halcyon-Lab Trading Readiness Audit — Design Decisions (v3)

**Paired with:** `audit-spec.md`, `plan.md`

Records non-obvious decisions across v1/v2/v3 passes with rationale and alternatives. v3 corrected fabricated paths from v2 and restored T1.04's original cap-reconciliation intent.

---

## 1. v3 delta vs v2: replace every fabricated path with Glob-verified real path or explicit (NEW) marker; restore T1.04 CAP-reconciliation primary intent; restore v1 F-1..F-18 numbering; mark F-16 STALE

**Rationale:** v2 correctly applied content fixes (FR-1/2/3, DA-1..DA-10) but introduced fabricated directories (src/strategies/{mr,pullback,breakout}/, src/risk_governor/, src/live_trading/, src/bootcamp/, src/metrics/, src/brokers/alpaca/, src/plugins/, src/_archived/) that do not exist in the codebase. v3 ran 22 Glob queries to map every cited path to either a verified-real location or a (NEW) marker. T1.04 was reframed away from CAP-reconciliation by v2; v3 restores the v1 intent (effective_position_cap helper across 4 namespaces called from both src/risk/governor.py:385-404 and src/shadow_trading/executor.py:104-113) while retaining v2's enabled-flag CI guardrail as a side feature in NEW tests/test_config_guardrails.py. Lazy-prices shelving redirected from a fabricated src/_archived/ move to in-place YAML metadata at src/platform/specs/lazy_prices_v1.yaml. Pullback redesign placed under NEW src/scoring/pullback_logistic/ rather than v2's fabricated src/strategies/pullback/ because no src/strategies/ parent exists. Plugin removal targets verified-real src/platform/{strategy_plugin,plugin_registry}.py rather than fabricated src/plugins/. Bracket-builder fix targets verified-real src/packets/template.py:154-186 (lines 163-170 hardcode multipliers) with both _multiplier (pullback) and _multiple (MR) config keys accepted via fallback chain. F-2 evidence enriched with the four real Sharpe formulas across ~12 enumerated call sites with explicit KEEP/MIGRATE/RENAME/DELETE disposition (per V3 brief Sharpe call-site map). All v2 content (decision matrices, methodology table, sign-off mechanism, task decompositions, must-fail tests, DA-9, DA-10, counter-arguments) preserved.

**Alternatives considered:**
- Keep fabricated paths and trust them (rejected: V3-1 hard rule forbids; would propagate broken plan to /arcis:code Developers who cannot find the files)
- Use Find/Grep instead of Glob for verification (rejected: per agent guidance Glob is the correct tool for path-existence verification; faster than Grep on file content)
- Place T1.04 helper in NEW src/risk/cap_utils.py instead of top of src/risk/governor.py (rejected per Decision 9: introduces a new file when one helper function suffices in existing module; src/risk/governor.py is the primary consumer)
- Rename _multiplier vs _multiple config keys in T1.06 (rejected per Decision 10: out of scope per spec §11; risk of breaking other config readers; fallback chain is more robust)
- Move lazy-prices Python directory to src/_archived/ per v2 (rejected per Decision 11: there is no Python directory — only the YAML spec; in-place metadata flag is simpler and matches the actual artifact)
- Keep v2's F-Strategy-A..E numbering (rejected per V3-4: v1 had F-1..F-18 only with strategy decisions in §6; restoring single-numbering simplifies cross-references)
- Treat T1.04 as still-primarily-about-enabled-flags per v2 (rejected per V3-2: v1 charge was about CAP reconciliation; v2 drift loses the original bug-fix intent)


---

## Architect Reasoning (v3 amendment)

` and `<design>` JSON block for the orchestrator.

<reasoning>
v3 verification protocol completed:

1. **Read v2 outputs** (audit-spec.md, plan.md, design-decisions.md) before changes — confirmed v2 had fabricated paths matching the V3-1 charge (`src/strategies/{mr,pullback,breakout}/`, `src/risk_governor/`, `src/live_trading/`, `src/bootcamp/`, `src/metrics/`, `src/brokers/alpaca/`, `src/plugins/`, `src/_archived/`).

2. **Glob-verified 22+ path patterns** against the live codebase. Confirmed:
   - Sole governor: `src/risk/governor.py` only (no `src/risk_governor/`, `src/live_trading/`, `src/bootcamp/` directories)
   - No `src/strategies/` directory at all (only singular `src/strategy/` with one `canary.py`)
   - `src/analytics/` exists with `spy_benchmark.py` — valid parent for new `canonical_sharpe.py`
   - `src/packets/template.py` exists (single-segment, not `src/platform/packets/`)
   - `src/services/{scan_service,mr_scan_service}.py` both exist
   - `src/ranking/ranker.py`, `src/features/{mean_reversion,setup_classifier,engine}.py` all exist
   - `src/platform/{strategy_plugin,plugin_registry,cost_calibration,promotion}.py` all exist
   - `src/platform/rigor/{cscv,dsr,walkforward*}.py` all exist
   - `src/api/cloud_routes/trades.py`, `src/evaluation/{statistics,gate_evaluator,model_monitor,cto_report,backtester}.py`, `src/journal/stats.py`, `src/notifications/telegram.py`, `src/scheduler/{reports,holidays}.py` all exist
   - `tests/risk/` has only `test_governor_disabled_alert.py` — must mark T1.04's new test files `(NEW)`
   - `src/methods/`, `src/data/`, `src/calendars/`, `src/allocator/`, `src/cost/`, `src/scoring/` directories all do NOT exist — must mark `(NEW)`

3. **Read raw code** at:
   - `src/risk/governor.py:375-415` to confirm `RiskGovernor.__init__` reads ONLY `risk_governor.*` config namespace
   - `src/shadow_trading/executor.py:100-130` to confirm `_governor_cap` reads bootcamp/risk/shadow_trading but NOT risk_governor or live_trading — the divergence T1.04 fixes
   - `src/packets/template.py:150-190` to confirm bracket math hardcoded at lines 163-170
   - `config/settings.local.yaml:90-180, 200-235` to confirm 4 namespace caps and asymmetric `_multiplier`/`_multiple` keys

4. **T1.04 restoration:** v2's task description was entirely about `enabled` flag reconciliation. v3 rewrites it to make CAP reconciliation primary (per V3-2 charge): add `effective_position_cap(config)` helper, called from both `RiskGovernor.__init__` and `_governor_cap`, returning `min(...)` of all 4 namespace caps. Enabled-flag guardrail retained as side feature in NEW `tests/test_config_guardrails.py`. Made the `bootcamp` early-return decision explicit in scope_fence (fold into min vs preserve as special case — picked fold).

5. **F-2 evidence rewrite:** Enumerated four real Sharpe formulas and ~12 call sites with KEEP/MIGRATE/RENAME/DELETE disposition per site (per V3 brief's Sharpe call-site map):
   - PROD √n at journal/stats.py:114-130 → MIGRATE
   - BACKTEST √252 at platform/metrics.py:32-48 → MIGRATE (preserves walkforward downstream)
   - THIRD √150 at api/cloud_routes/trades.py:58-69 + cto_report.py:239-246 → MIGRATE
   - FOURTH raw at platform/rigor/cscv.py:37-45 → RENAME ONLY (`_sharpe_for_pbo`)
   - statistics.py raw → KEEP (gate_evaluator uses correctly); duplicate PSR → DELETE; MinTRL zero consumers → KEEP-OR-DELETE per T2.04
   - model_monitor.py + scheduler/reports.py raw → KEEP (intentional)
   - backtester.py:140-145 stride-5 → FLAG for ESCALATE

6. **F-6 correction:** Bracket math is at `src/packets/template.py:154-186`, lines 163-170 hardcode `2*atr` stop and `[1.5*atr, 3.0*atr]` targets. Config keys `strategies.pullback.stop_atr_multiplier=2.0` (line 210, plural-r) and `strategies.mean_reversion.stop_atr_multiple=2.5` (line 221, singular). T1.06 modifies template.py to read both keys (fallback chain) and updates the two service callers.

7. **§6 reabsorption (V3-4):** v2's `F-Strategy-A..E` block removed; strategy decisions live solely in §6. Findings list is F-1..F-18. F-16 noted STALE.

8. **Preserved verbatim from v2 (V3-3):** §3.1 decision matrix, §3.2 methodology table, §5 canonical Sharpe definition, §9 sign-off mechanism + memo + transcript, T1.01 cutoff details, task decompositions T2.14a/b/c + T2.12a/b + T2.16a/b, must-fail tests on Monday-blocking tasks, DA-9, DA-10, Appendix B counter-arguments, 3-stage roadmap, out-of-scope guardrails.

Files written to disk: `audit-spec.md`, `plan.md`, `design-decisions.md` at `C:\arcis\halcyon-lab\docs\audits\2026-04-27-trading-readiness\`.
