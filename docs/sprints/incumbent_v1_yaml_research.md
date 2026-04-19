# Pass 2 — Incumbent v1 YAML research: feasibility + scope decision (#523)

**Branch:** `refactor/incumbent-v1-yaml-spec`
**Date:** 2026-04-19
**Predecessor:** `docs/sprints/incumbent_v1_yaml_evaluation.md` (Pass 1)

## Objective

Re-read every file Pass 1 referenced. Confirm or refute each of the 8 surfaced blockers. Verify whether the `lazy_prices_v1.yaml` schema is adequate. Make the feasibility call.

## Method

Read end-to-end:
- `src/features/engine.py` (364 lines) — read in full during Pass 1
- `src/ranking/ranker.py` (330 lines) — read in full during Pass 1
- `src/services/scan_service.py` (294 lines) — read in full during Pass 1
- `src/platform/strategy_spec.py` (116 lines) — read in full
- `src/llm/packet_writer.py` lines 490-630 — read `enhance_packet_with_llm` and the deterministic-field boundary comment
- `src/packets/template.py` (198 lines) — read in full
- `src/simulation/engine.py` lines 1-120 — read for REGIME_BRACKETS + classify_vix_regime

Spot-checked: `src/features/event_risk_score.py` (322 lines, header only), `src/features/earnings.py` (134 lines, headers), `config/settings.example.yaml` + `settings.local.yaml` presence.

## Blocker reassessment

### Blocker 1 — `daily_scan` entry kind has no runtime ✓ **CONFIRMED**

`src/platform/strategy_spec.py:24`:
```python
ALLOWED_ENTRY_KINDS = {"scheduled", "event_driven", "python_plugin"}
```

`daily_scan` is not a valid kind. Even `scheduled` — the nearest analog — raises `NotImplementedError` in `signal_eval.py:180`:
```python
if kind == "scheduled":
    raise NotImplementedError("[SIGNAL_EVAL] scheduled-kind find_candidates_for_date not yet implemented")
```

This maps to open issue **#494** (in the v0.25.2 parked subphase). Runtime wiring for the incumbent's `daily_scan` requires either adding a new kind + runtime, or closing #494 and using `scheduled`. Neither is a no-logic-change operation.

### Blocker 2 — LLM modifies brackets ✗ **REFUTED**

`src/llm/packet_writer.py:508-514`:
```python
"""Enhance a trade packet with LLM-written prose.

If LLM is disabled or unavailable, returns the packet unchanged.
Never modifies deterministic fields (entry, stop, targets, sizing,
confidence, event_risk). This separation is critical -- see #6: equal
weight between rules-based and LLM systems is maintained until 200+
trades validate the LLM's conviction calibration. The LLM writes prose
and provides a conviction score, but the mechanical system controls
all trade parameters and sizing. #18: bracket exits are always mechanical.
"""
```

The LLM is restricted to writing `why_now` + `deeper_analysis` prose and producing a `conviction` score. It **does not** touch `entry_zone`, `stop_invalidation`, `targets`, `position_sizing`. This is an intentional architectural separation (citations #6, #18).

**Brackets are fully deterministic**, computed in `packets/template.py:71-76`:
```python
entry_zone = f"${price:.2f} area"
stop_price = price - stop_distance    # stop_distance = 2 * atr
stop_invalidation = f"${stop_price:.2f} close basis"
target_1 = price + 1.5 * atr
target_2 = price + 3.0 * atr
targets = f"${target_1:.2f} / ${target_2:.2f}"
```

With `stop_distance = 2 * atr if atr > 0 else price * 0.03`.

Pass 1 was wrong about this blocker. Byte-identical ORDER prices (entry, stop, targets) ARE theoretically achievable because they're mechanical. This widens the feasibility window for a bracket-subset spec — but does NOT resolve Blockers 1, 3, 4, 5, 6, 7.

### Blocker 3 — Config-driven state (bootcamp, regime_adaptive) ✓ **CONFIRMED**

`ranker.py:35-69` explicitly branches on:
- `config['bootcamp']['enabled']` → returns bootcamp thresholds (`qualification_threshold`, `watchlist_threshold`) with caps `max_packets=20, max_watchlist=30`
- `config['regime_adaptive']['enabled']` → overrides `packet_worthy` per `REGIME_THRESHOLDS` lookup (7 regimes × 2 values)

v0.25.0 decision (`docs/decisions/013-strategy-evaluation-apr-19.md`) set bootcamp ON with qualification=55, max_positions=20 for the Monday trading session. A frozen incumbent_v1.yaml either:
- Pins bootcamp state at a specific SHA (but then "v1" is conflated with a particular config snapshot)
- Captures bootcamp as a spec mode (new schema field)

### Blocker 4 — Attribution Phase 1/2 hooks ✓ **CONFIRMED**

`scan_service.py:152-166, 183-195`:
```python
attribution_id = log_attribution_before_llm(ticker, ranker_score, entry_price, stop_price, target_price)
...
log_attribution_after_llm(attribution_id, llm_action, llm_conviction, recommendation_id)
```

These hooks have no YAML expression and are load-bearing for the alpha attribution experiment (Deployed Components → in-progress).

### Blocker 5 — Data enrichment step ✓ **CONFIRMED**

`scan_service.py:67-71`:
```python
from src.data_enrichment.enricher import enrich_features
features = enrich_features(features, config)
```

Adds fundamental/insider/macro data to feature dicts. Lazy-prices doesn't enrich. Incumbent depends on enrichment (LLM prompts reference `fundamental_summary`, `insider_summary`).

### Blocker 6 — Post-scan enrichment chain ✓ **CONFIRMED**

`scan_service.py:76-107`:
```python
from src.features.enrichment import attach_post_scan_features
attach_post_scan_features(features, config=config, spy=spy, vix_value=vix_value)
```

Adds `traffic_light_multiplier`, `event_risk_multiplier`, `market_event_risk` dict, `regime_label`. Executes AFTER ranking-feature compute, BEFORE ranker. No spec-YAML representation.

### Blocker 7 — Setup classifier + log_setup_signal ✓ **CONFIRMED**

`features/engine.py:270-283` (deferred import workaround for circular):
```python
from src.features.setup_classifier import classify_setup, log_setup_signal
classification = classify_setup(feat, df)
feat["setup_type"] = classification["setup_type"]
feat["setup_confidence"] = classification["confidence"]
feat["setup_desk"] = classification["tradeable_by_desk"]
log_setup_signal(ticker, classification, feat, regime=...)
```

Writes to `setup_signals` table; downstream LLM prompt consumes `setup_type`. Spec YAML has no place for "run this helper mid-feature-compute".

### Blocker 8 — Simulation vs live use different bracket logic ✓ **CONFIRMED + EXPANDED**

Two distinct bracket tables exist in the codebase:

**Live pipeline** (`packets/template.py:71-76`): ATR-based, NOT regime-adaptive:
- Stop: entry − 2·ATR
- Target 1: entry + 1.5·ATR
- Target 2: entry + 3·ATR
- Timeout: from config (`shadow_trading.timeout_days` default 15; pullback override 7)

**Simulation pipeline** (`simulation/engine.py:89-93`): ATR × VIX-regime-adaptive, single target:
```python
REGIME_BRACKETS = {
    "low":      {"stop_atr_mult": 2.0, "target_atr_mult": 2.0, "timeout_days": 8},
    "normal":   {"stop_atr_mult": 2.0, "target_atr_mult": 2.0, "timeout_days": 8},
    "elevated": {"stop_atr_mult": 2.5, "target_atr_mult": 2.5, "timeout_days": 7},
    "extreme":  {"stop_atr_mult": 3.0, "target_atr_mult": 3.0, "timeout_days": 5},
}
```

VIX regime via `classify_vix_regime()`:
- <12 → low
- 12-20 → normal
- 20-30 → elevated
- 30+ → extreme

**These are different strategies.** Live is "always 2·ATR stop, 1.5·ATR target_1, 3·ATR target_2, timeout from config". Sim is "regime-adaptive, single target, shorter timeouts in higher vol". They disagree on:
- Target count (2 live vs 1 sim)
- Target multiple(s) (1.5/3 live vs {2/2/2.5/3} sim)
- Stop multiple (2 live vs {2/2/2.5/3} sim)
- Timeout (15d or 7d from config live vs {8/8/7/5} sim)

A single `incumbent_v1.yaml` cannot capture both. Must pick which path is "the incumbent". Per memory + Roadmap.jsx, incumbent = live paper-trading strategy. Sim/engine.py is the backtester (Validation machinery), distinct from the incumbent.

## Schema adequacy

The `lazy_prices_v1.yaml` schema as-is is **inadequate** for incumbent without extension:

- **`entry.kind: daily_scan`** not in ALLOWED set
- **Scoring bands** (not simple thresholds) — ranker uses `[-8,-3]→+25; [-12,-8)→+10` style step functions that `signal[].operator: less_than` cannot express
- **Multi-block ranking DSL** — trend bonus + RS + pullback + dist_sma20 + volume + options + regime_adjustment; not representable as `signal[]`
- **Regime-adaptive position sizing** — lazy_prices uses `fixed_pct_equity`; incumbent needs per-regime position_pct table
- **Attribution hooks** — no declaration form
- **Data enrichment** — no block
- **Post-scan chain** — no block
- **Two-target brackets** — lazy_prices has single `target.multiplier`; incumbent has target_1=1.5·ATR AND target_2=3·ATR
- **Event-risk gating** (elevated/imminent → earnings_risk_packet) — no declaration
- **Setup classification hook** — no declaration

Adding all of these turns the spec format into a **trading DSL**, which is a major platform evolution. Sprint hard rule #2 forbids feature additions — this clashes.

## Scope options

### Option A — Runtime-wired incumbent (full refactor)
- Extend schema with ~10 new sections (scoring bands, ranking DSL, multi-target brackets, hooks, enrichment, etc.)
- Implement `daily_scan` kind in `signal_eval.py` (closes #494 as prerequisite)
- Build spec-driven runtime that byte-identically reproduces `scan_service.run_scan`
- Swap runtime to read from YAML
- Regression test runs YAML through backtest engine against fixture, compares orders

**Scope:** 3-5 sprints. Violates hard rule #2 (no feature additions) and hard rule #5 (never refactor + feature).

**Outcome:** NOT feasible in 1 sprint.

### Option B — Reference-only incumbent YAML
- Write `incumbent_v1.yaml` with all parameters captured as values
- YAML has no runtime effect; existing Python code is source-of-truth
- Regression test: load YAML, assert values match Python constants (e.g., `atr_multiplier: 2.0` in YAML == `stop_distance = 2 * atr` in template.py)
- YAML serves as v0.26.1 walk-forward reference (human-readable frozen snapshot)
- `derived_from: null` per R8 ✓

**Scope:** 1 sprint. Respects hard rules #1, #2, #5. No byte-identical order stream test because runtime doesn't change.

**Outcome:** Doesn't satisfy the prompt's "run against fixed historical fixture" regression test literally. The prompt implies runtime-wired YAML.

### Option C — STOP and file blocker issue
- Ship Pass 1 + Pass 2 docs only
- Close #523 with "BLOCKED — see issue #NNN"
- Issue #NNN: enumerate the schema extensions + runtime work required + ordering (close #494 first)
- Follow-up sprint(s) unwind coupling before retry

**Scope:** 0 additional engineering; docs + blocker issue only.

**Outcome:** Honors the prompt's explicit risk path: "If Pass 2 reveals cross-dependencies that don't YAML-ify, STOP and file issue with specific coupling. Do NOT force incomplete refactor."

## Recommendation

**Option C** — STOP and file blocker issue.

Justification:
1. Blockers 1, 3, 4, 5, 6, 7, 8 stand after Pass 2 re-read. Blocker 2 is refuted, which removes the "LLM randomness" reason alone but does NOT resolve the other 7.
2. The lazy_prices schema cannot represent incumbent's ranking DSL, multi-target brackets, regime-adaptive sizing, hooks, enrichment pipeline without ~10 new schema sections.
3. `daily_scan` runtime is gated on #494, which is open and in the v0.25.2 parked subphase (pending).
4. Hard rules (no logic changes, no feature additions, never refactor + feature) explicitly forbid the Option A scope creep.
5. Option B satisfies hard rules but violates the literal regression test spec ("run against fixed historical fixture" with order-stream assertion). Would require operator sign-off on scope reduction.

## Blocker issue draft (for follow-up sprint)

**Title:** Unblock incumbent_v1.yaml extraction — decouple runtime from hardcoded scan pipeline

**Body outline:**

> v0.26.0 attempted to extract incumbent pullback-in-uptrend strategy into `src/platform/specs/incumbent_v1.yaml` (#523). Blocked by 7 cross-dependencies that don't cleanly YAML-ify. See `docs/sprints/incumbent_v1_yaml_{evaluation,research}.md` for full inventory.
>
> **Prerequisite work (ordered):**
>
> 1. Close **#494** — implement `scheduled`-kind `find_candidates_for_date` in `src/platform/signal_eval.py`. Current state: raises `NotImplementedError`.
> 2. Close **#493** — implement `python_plugin`-kind `find_candidates_for_date`.
> 3. Extend spec schema with:
>    - `daily_scan` entry kind (or reuse `scheduled` with daily cron)
>    - Scoring-DSL block (metric + bands + score value per band)
>    - Multi-block ranking DSL (trend bonus + RS + pullback + vol + regime)
>    - Multi-target brackets (target_1, target_2 with per-target multiplier)
>    - Regime-adaptive position sizing
>    - Attribution hook declarations
>    - Data-enrichment block (enricher refs)
>    - Post-scan chain block (helpers to run after ranking)
>    - Event-risk gate block
>    - Bootcamp-mode override section
>    - Setup-classifier hook
> 4. Port scan pipeline to be spec-driven (read parameters from loaded `StrategySpec`):
>    - `compute_all_features` reads entry-signal bands from spec (instead of hardcoded in ranker)
>    - `rank_universe` reads ranking DSL from spec (instead of `_score_ticker()` hardcoded branches)
>    - `build_packet_from_features` reads bracket multiples from spec (instead of `2 * atr`)
>    - `check_and_manage_open_trades` reads timeout_days from spec (instead of config)
> 5. Regression test: run spec-driven pipeline against fixture; assert order stream matches pre-refactor baseline.
>
> **Recommended sprint count:** 3-5, pacing carefully to preserve byte-identical order stream at each step. Each schema extension lands as its own PR with regression coverage. Final sprint flips `scan_service.run_scan` to load incumbent_v1.yaml as source-of-truth.
>
> **Labels:** architecture, technical-debt, spec-driven, v0.26.x

## Next step

Ship Pass 1 + Pass 2 docs + blocker-issue filing as the v0.26.0 deliverable. PR body marks #523 as BLOCKED with link to the new issue. No `incumbent_v1.yaml` created, no schema extension, no runtime change.
