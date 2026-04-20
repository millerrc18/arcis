# Sprint C Pass 2 — scoring-DSL schema research findings (#549)

Pass 2 verifies the three assumptions behind Pass 1's design before code is
written:

1. No existing spec uses `ranking.bands` (→ new block, no migration).
2. The proposed DSL shape maps 1-to-1 onto the incumbent ranker's hardcoded
   bands (→ Sprint F port is mechanical).
3. No spec consumer breaks on a new optional top-level key (→ backward
   compat is free).

## 1. Existing `ranking` usage on main — confirmed zero in strategy specs

### 1.1 Strategy-spec YAML files (`src/platform/specs/*.yaml`)

Grep result (ripgrep, pattern `ranking`):

```
(no matches in src/platform/specs/)
```

The two specs on main — `lazy_prices_v1.yaml` and `post_audit_ruleset_v1.yaml`
— have no top-level `ranking` key. Confirmed by direct read: both files end
at `attribution:` / `llm_enhancement:` with no further top-level sections.

### 1.2 Test fixtures (`tests/**/*.yaml`)

Grep across the entire repo for `ranking` in any `.yaml`:

```
config/settings.example.yaml:423:  enabled: true  # ...use static qualification_threshold from bootcamp/ranking.
config/settings.example.yaml:432:#     ranking.packet_worthy_threshold with the values below.
```

Both hits are in `config/settings.example.yaml` and refer to the
**application-level** `ranking` config block (consumed by `ranker.py::_load_thresholds`,
not by `strategy_spec.py`). These live in `config/settings.*.yaml`, never
in a strategy spec, and are fetched via `load_config()` — an entirely
different code path. No collision: strategy specs do not share a YAML
namespace with app settings.

**Conclusion.** `ranking.bands` is a net-new top-level key on strategy
specs. No migration step is needed.

## 2. Incumbent ranker → DSL shape mapping

### 2.1 `_score_ticker` hardcoded bands (ranker.py:189–205)

| # | Metric | Range (Python) | Score | DSL band |
|---|--------|----------------|-------|----------|
| 1 | `pullback_depth_pct` | `-8 <= p <= -3` | +25 | `{metric: pullback_depth_pct, range: [-8, -3], score: 25}` |
| 2 | `pullback_depth_pct` | `-12 <= p < -8` | +10 | `{metric: pullback_depth_pct, range: [-12, -8], score: 10}` |
| 3 | `dist_to_sma20_pct` | `-5 <= d <= -1` | +10 | `{metric: dist_to_sma20_pct, range: [-5, -1], score: 10}` |
| 4 | `volume_ratio_20d` | `v < 0.8` | +15 | **see §2.3** — half-open |

### 2.2 Inclusivity — the `-8` boundary

Band #1 uses `<=` on both sides (`-8 <= p <= -3`). Band #2 uses strict
`<` on the upper (`p < -8`) to avoid double-counting at exactly `-8`. The
DSL as specified in the sprint prompt serializes both as closed intervals.

Two coping strategies available to Sprint F's port:
- **First-match-wins** iteration order (bands evaluated top to bottom; stop
  after first match per metric).
- **Tighten ranges at spec-authoring time** (e.g. `[-12, -8.01]` /
  `[-8, -3]`).

Either is a Sprint F runtime decision — not a schema concern. The schema's
job is to surface the overlap as a warning so the operator sees it. See
evaluation doc §5.

### 2.3 Unbounded-end bands (volume_ratio_20d)

`if vol_ratio < 0.8` is a one-sided threshold — no lower bound in Python.
The DSL requires two-element ranges. Two clean options for Sprint F:

- **Encode with a sentinel low bound.** `range: [0, 0.8]` — volume ratios
  are non-negative by construction, so `[0, 0.8]` is exactly equivalent to
  `< 0.8` on the domain of the metric.
- **Extend the DSL** to allow `range: [null, 0.8]` for half-open ranges.

Preferred: option 1 for Sprint F (concrete bounds, no schema change). The
Sprint F port doc will pick the convention.

Schema impact on Sprint C: **none**. The current validation requires two
numeric elements with `lo < hi`. Option 1 satisfies it; option 2 would
require a future schema amendment.

### 2.4 Non-band scoring components

`_score_ticker` also applies score from:
- `trend_state` (categorical, not a band — `strong_uptrend` → +30, etc.)
- `relative_strength_state` (categorical)
- `iv_rank` + `put_call_vol_ratio` (conditional categorical bands)
- `_regime_adjustment` (derived function of regime_label/breadth/spy_rsi)

These are **out of scope** for the `ranking.bands` DSL — they need a
separate `ranking.categorical` or `ranking.conditional` block if we want
to express them declaratively. Sprint F can port the numeric bands first
(this sprint's shape) and either leave the categorical scoring in code or
expand the DSL in a later sprint.

**No schema change needed now** — the current `{metric, range, score}`
shape is sufficient for all four numeric bands in `_score_ticker`.

## 3. Spec consumers — backward-compat audit

### 3.1 `spec.raw` readers (audit of `src/**`)

| File | Line | Access | Risk of new `ranking` key |
|------|------|--------|---------------------------|
| `src/scheduler/watch.py` | 762 | `spec.raw.get("shadow_cadence_seconds", 600)` | Unaffected — reads a specific key. |
| `src/platform/shadow_harness.py` | (docstring ref only) | N/A | No code access. |
| `src/platform/backtest_engine.py` | 187 | `json.dumps(spec.raw, sort_keys=True, default=str)` | **Hash changes when `ranking` is added.** This is *correct* — the reproducibility hash must reflect any config change that affects trade selection or scoring. |
| `src/platform/backtest_persist.py` | 56 | `strategy.raw.get("spec_version", 1)` | Unaffected — specific key. |
| `src/api/cloud_routes/platform.py` | 108 | `body["spec"] = spec.raw` | Full-body pass-through — harmless, extra key flows through to the response consumer. |

**Net finding.** No consumer breaks. The one behavioral change — the
reproducibility hash captures the new `ranking` key — is intentional and
desirable: a spec that scores trades differently must hash differently.

### 3.2 `validate_spec` return-signature callers

Callers unpacking `(ok, errors)`:

```
src/platform/strategy_spec.py:85     ok, errors = validate_spec(d)
tests/platform/test_strategy_spec.py: 7 call sites use the same pattern
tests/platform/specs/test_post_audit_ruleset_v1.py: uses load_spec (indirect)
```

Pass 1's decision to keep the signature `(ok, errors)` — and channel
overlap warnings through the logger — avoids updating any of these call
sites. If a structured warning channel is needed later, a v2
`validate_spec_v2(spec) → (ok, errors, warnings)` can be added beside the
current function.

### 3.3 Schema-registry CI guardrails

The CLAUDE.md rules forbid `CREATE TABLE` / `ALTER TABLE` outside
`src/schema/registry.py`. `strategy_spec.py` contains neither today and
this sprint adds neither — confirmed via grep (`CREATE TABLE|ALTER TABLE`
on `src/platform/strategy_spec.py` → zero). No schema-registry impact.

## 4. Sprint F preview — port shape

For the record, Sprint F's port will look approximately like:

```python
# Sprint F — src/ranking/ranker.py _score_ticker, replacing the hardcoded bands.
bands = spec.raw.get("ranking", {}).get("bands", [])
for band in bands:
    lo, hi = band["range"]
    value = features.get(band["metric"])
    value_f = _as_float(value)
    if value_f is None:
        continue
    if lo <= value_f <= hi:
        score += band["score"]
        # Optional: break per metric for first-match-wins semantics.
```

Bands absent ⇒ scoring falls back to the current hardcoded logic (or is
disabled entirely, depending on the Sprint F design decision). This sprint
makes no commitment — the schema tolerates bands absent (§7.14 test in
Pass 1).

## 5. Overlap-warning noise estimate

The incumbent uses two `pullback_depth_pct` bands with a shared `-8`
endpoint. Under closed-interval overlap semantics (Pass 1 §5), declaring
them directly as `[-12,-8]` + `[-8,-3]` will emit one warning per spec
load. Acceptable — that warning is exactly the signal we want the operator
to see so they can choose between first-match-wins and tightening the
range.

Operators who want silence can write `[-12.0, -8.001]` / `[-8.0, -3.0]`;
the schema accepts floats and the runtime comparison is float-safe.

Expected total warning volume on main: **zero** (no specs use bands yet).
Once Sprint F ships and specs start declaring bands, 0–1 warnings per
spec load.

## 6. Risk register

| Risk | Mitigation |
|------|------------|
| Adding a new top-level key breaks `_from_dict` construction | Not a risk — `StrategySpec` dataclass uses explicit field names; `.raw` retains the full dict for Sprint F. No new dataclass field needed this sprint. |
| Test count floor (1500 per run_ci_locally.ps1) regresses | New test file adds 16 tests. Floor stays above. |
| `ranking.weights` (hypothetical existing non-bands shape) gets rejected | Explicit pass-through test — `test_ranking_weights_still_loads` (Pass 1 §7 test #16). Only `bands` sub-key is validated. |
| Bool-is-int trap silently accepts YAML `true` as numeric | Explicit `not isinstance(x, bool)` guard + regression test (Pass 1 §7 test #7). |
| Float overflow / non-finite (`.inf`, `.nan`) ranges | Out of scope — `isinstance(x, (int, float))` admits these; Sprint F's comparison will misbehave but the YAML loader is unlikely to emit them. Note for Sprint F port. |

## 7. Ready for Pass 3

All three Pass-2 assumptions validated:

- ✅ Zero existing usage of `ranking.bands` in strategy specs.
- ✅ Incumbent ranker's four numeric bands map 1-to-1 onto the DSL shape
      (one needs the `[0, upper]` sentinel convention; no schema change).
- ✅ Zero consumers break on a new optional top-level key; hash-change
      behavior is intentional.

Proceed to Pass 3: implement validation + write tests + update
CHANGELOG / MASTER.
