"""Ranking-block validators for strategy specs.

Split out of strategy_spec.py in Sprint C.1 (#569) to keep the main
validator module focused and under its line-count guardrail. All
ranking-related schema validation lives here: numeric+categorical+compound
bands (Items 3/4/8), weighted blend groups (Item 5), adjustments block
(Item 6), derived_metrics block (Item 7), and the regime-labels registry
(Item 6 addendum).

Called by: src.platform.strategy_spec.validate_spec.
Calls: logging (stdlib).
Owns tables: none.
Config keys: none.
Tests: tests/platform/specs/test_schema_c1_refinements.py.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# 5-label set from compute_market_regime() regime.py:161-170. Separate
# from KNOWN_REGIME_KEYS (7-label, threshold dispatch) — these drive
# ranking.adjustments compound-condition thresholds on `regime_label`.
# Additions require a refinement sprint (C.1-style).
KNOWN_REGIME_LABELS = frozenset({
    "calm_uptrend", "volatile_uptrend",
    "calm_downtrend", "volatile_downtrend",
    "transitional",
})

# Metrics referenced by _score_ticker (ranker.py:165-220) and
# _regime_adjustment (ranker.py:72-102). Effective set at validation =
# this frozenset ∪ derived-metric names. Additions require a refinement
# sprint (C.1-style). Same discipline as KNOWN_REGIME_KEYS.
KNOWN_SCORING_METRICS = frozenset({
    "trend_state", "relative_strength_state", "pullback_depth_pct",
    "dist_to_sma20_pct", "volume_ratio_20d", "iv_rank", "put_call_vol_ratio",
    "regime_label", "market_breadth_label", "spy_rsi_14",
})

# Equality operators accept numeric or string thresholds; others require numeric.
ALLOWED_BAND_OPERATORS = frozenset({">", ">=", "<", "<=", "==", "!="})
_EQUALITY_OPERATORS = frozenset({"==", "!="})

# Covers _compute_sector_rs (ranker.py:105-147) exactly. Future ops via
# refinement sprint — do not silently extend.
ALLOWED_DERIVED_OPS = frozenset({"subtract", "weighted_sum"})


def _is_numeric(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def validate_bands(
    bands: list, errors: list[str], *, known_metrics: frozenset[str] = frozenset(),
) -> None:
    """Validate ranking.bands. Shapes: numeric range / categorical / compound AND.
    Exactly one of 'range', 'category', 'conditions' per band."""
    parsed_numeric: list[tuple[str, float, float, int]] = []
    parsed_cat: list[tuple[str, str, int]] = []
    for i, band in enumerate(bands):
        _validate_one_band(
            band, i, errors, parsed_numeric, parsed_cat,
            known_metrics=known_metrics,
        )
    _warn_range_overlaps(parsed_numeric)
    _error_duplicate_categoricals(parsed_cat, errors)
    _validate_band_weights(bands, errors)


def _validate_one_band(
    band: Any, i: int, errors: list[str],
    parsed_numeric: list, parsed_cat: list, *,
    known_metrics: frozenset[str],
) -> None:
    """Shape-dispatch for a single band; delegates to shape-specific helpers."""
    path = f"ranking.bands[{i}]"
    if not isinstance(band, dict):
        errors.append(f"{path} must be a dict")
        return
    has_range = "range" in band
    has_cat = "category" in band
    has_conds = "conditions" in band
    shapes = sum([has_range, has_cat, has_conds])
    if shapes == 0:
        errors.append(f"{path} must specify one of 'range', 'category', or 'conditions'")
        return
    if shapes > 1:
        errors.append(
            f"{path} must specify exactly one of 'range', 'category', 'conditions' "
            "(mutually exclusive)"
        )
        return
    if not _is_numeric(band.get("score")):
        errors.append(f"{path}.score must be numeric")
        return
    if has_conds:
        _validate_compound_band(band, path, errors, known_metrics=known_metrics)
    else:
        _validate_simple_band(
            band, i, path, errors, parsed_numeric, parsed_cat,
            has_cat=has_cat, known_metrics=known_metrics,
        )


def _validate_compound_band(
    band: dict, path: str, errors: list[str], *, known_metrics: frozenset[str],
) -> None:
    """Item 4 — compound AND via conditions[]."""
    if "metric" in band:
        errors.append(f"{path} with 'conditions' may not specify a top-level 'metric'")
        return
    conds = band["conditions"]
    if not isinstance(conds, list) or not conds:
        errors.append(f"{path}.conditions must be a non-empty list")
        return
    for j, cond in enumerate(conds):
        _validate_band_condition(
            cond, f"{path}.conditions[{j}]", errors, known_metrics=known_metrics,
        )


def _validate_simple_band(
    band: dict, i: int, path: str, errors: list[str],
    parsed_numeric: list, parsed_cat: list, *,
    has_cat: bool, known_metrics: frozenset[str],
) -> None:
    """Items 3 + 8 — single-metric band (range or category)."""
    metric = band.get("metric")
    if not isinstance(metric, str) or not metric:
        errors.append(f"{path}.metric must be a non-empty string")
        return
    if known_metrics and metric not in known_metrics:
        errors.append(
            f"{path}.metric {metric!r} not in known scoring metrics "
            f"(known: {', '.join(sorted(known_metrics))})"
        )
        return
    if has_cat:
        cat = band["category"]
        if not isinstance(cat, str) or not cat:
            errors.append(f"{path}.category must be a non-empty string")
            return
        parsed_cat.append((metric, cat, i))
        return
    rng = band["range"]
    if (
        not isinstance(rng, list) or len(rng) != 2
        or not all(_is_numeric(x) for x in rng)
    ):
        errors.append(f"{path}.range must be a 2-element list of numerics")
        return
    lo, hi = rng
    if lo >= hi:
        errors.append(f"{path}.range[0] must be < range[1] (got {lo} >= {hi})")
        return
    parsed_numeric.append((metric, float(lo), float(hi), i))


def _warn_range_overlaps(parsed_numeric: list[tuple[str, float, float, int]]) -> None:
    """Sprint C behavior, unchanged: warn on overlapping numeric ranges for the same metric."""
    by_metric: dict[str, list[tuple[float, float, int]]] = {}
    for metric, lo, hi, idx in parsed_numeric:
        by_metric.setdefault(metric, []).append((lo, hi, idx))
    for metric, entries in by_metric.items():
        for a in range(len(entries)):
            for b in range(a + 1, len(entries)):
                if entries[a][0] <= entries[b][1] and entries[b][0] <= entries[a][1]:
                    logger.warning(
                        "[PLATFORM] ranking.bands overlap: metric=%s band#%d[%s,%s] "
                        "overlaps band#%d[%s,%s]",
                        metric, entries[a][2], entries[a][0], entries[a][1],
                        entries[b][2], entries[b][0], entries[b][1],
                    )


def _error_duplicate_categoricals(
    parsed_cat: list[tuple[str, str, int]], errors: list[str],
) -> None:
    """Sprint C.1 Item 3: duplicate (metric, category) pairs are errors."""
    seen: dict[tuple[str, str], int] = {}
    for metric, cat, idx in parsed_cat:
        key = (metric, cat)
        if key in seen:
            errors.append(
                f"ranking.bands[{idx}] duplicates metric={metric!r} category={cat!r} "
                f"from ranking.bands[{seen[key]}]"
            )
        else:
            seen[key] = idx


def _validate_band_condition(
    cond: Any, path: str, errors: list[str], *,
    known_metrics: frozenset[str] = frozenset(),
) -> None:
    """One condition inside a compound band (Item 4). When metric='regime_label'
    and operator is equality, threshold validated against KNOWN_REGIME_LABELS."""
    if not isinstance(cond, dict):
        errors.append(f"{path} must be a dict")
        return
    metric = cond.get("metric")
    if not isinstance(metric, str) or not metric:
        errors.append(f"{path}.metric must be a non-empty string")
        return
    if known_metrics and metric not in known_metrics:
        errors.append(
            f"{path}.metric {metric!r} not in known scoring metrics "
            f"(known: {', '.join(sorted(known_metrics))})"
        )
    op = cond.get("operator")
    if op not in ALLOWED_BAND_OPERATORS:
        errors.append(
            f"{path}.operator must be one of {sorted(ALLOWED_BAND_OPERATORS)}, got {op!r}"
        )
        return
    thr = cond.get("threshold")
    if op in _EQUALITY_OPERATORS:
        if not isinstance(thr, (int, float, str)) or isinstance(thr, bool):
            errors.append(f"{path}.threshold must be numeric or string for operator {op!r}")
            return
    else:
        if not _is_numeric(thr):
            errors.append(f"{path}.threshold must be numeric for operator {op!r}")
            return
    if metric == "regime_label" and op in _EQUALITY_OPERATORS and isinstance(thr, str):
        if thr not in KNOWN_REGIME_LABELS:
            errors.append(
                f"{path}.threshold {thr!r} not in KNOWN_REGIME_LABELS "
                f"(known: {', '.join(sorted(KNOWN_REGIME_LABELS))})"
            )


def _validate_band_weights(bands: list, errors: list[str]) -> None:
    """weight + blend_group cohesion (Item 5). Both or neither. weight in
    [0, 1]; blend_group non-empty string. Warn if group weights != 1.0."""
    by_group: dict[str, list[tuple[int, float]]] = {}
    for i, band in enumerate(bands):
        if not isinstance(band, dict):
            continue
        w = band.get("weight")
        g = band.get("blend_group")
        if w is None and g is None:
            continue
        path = f"ranking.bands[{i}]"
        if w is None:
            errors.append(f"{path} has blend_group without weight")
            continue
        if g is None:
            errors.append(f"{path} has weight without blend_group")
            continue
        if not _is_numeric(w) or not (0.0 <= w <= 1.0):
            errors.append(f"{path}.weight must be a number in [0.0, 1.0]")
            continue
        if not isinstance(g, str) or not g:
            errors.append(f"{path}.blend_group must be a non-empty string")
            continue
        by_group.setdefault(g, []).append((i, float(w)))

    for g, entries in by_group.items():
        total = sum(w for _, w in entries)
        if abs(total - 1.0) > 0.01:
            logger.warning(
                "[PLATFORM] ranking.bands blend_group=%r weights sum to %.3f (not 1.0)",
                g, total,
            )


def validate_adjustments(
    adj_block: dict, errors: list[str], *,
    known_metrics: frozenset[str] = frozenset(),
) -> None:
    """ranking.adjustments (Item 6). Shape: {bands: [...], clamp: [lo, hi]?}.
    Reuses validate_bands grammar."""
    clamp = adj_block.get("clamp")
    if clamp is not None:
        if (
            not isinstance(clamp, list) or len(clamp) != 2
            or not all(_is_numeric(x) for x in clamp) or clamp[0] >= clamp[1]
        ):
            errors.append(
                "ranking.adjustments.clamp must be a 2-element list of numerics with lo < hi"
            )
    bands = adj_block.get("bands")
    if bands is None:
        errors.append("ranking.adjustments.bands is required")
        return
    if not isinstance(bands, list):
        errors.append("ranking.adjustments.bands must be a list")
        return
    validate_bands(bands, errors, known_metrics=known_metrics)


def validate_derived_metrics(dm_block: Any, errors: list[str]) -> frozenset[str]:
    """ranking.derived_metrics (Item 7). Returns derived-metric names to
    union into known_metrics.
    Shape: <name>: {operation: subtract|weighted_sum, inputs: list|dict}.
    """
    if not isinstance(dm_block, dict):
        errors.append("ranking.derived_metrics must be a dict when present")
        return frozenset()
    specs = _parse_derived_metric_specs(dm_block, errors)
    _check_derived_metric_cycles(specs, errors)
    return frozenset(specs.keys())


def _parse_derived_metric_specs(
    dm_block: dict, errors: list[str],
) -> dict[str, dict]:
    """Per-entry shape/type validation. Returns valid entries only."""
    specs: dict[str, dict] = {}
    for name, entry in dm_block.items():
        if not isinstance(name, str) or not name:
            errors.append("ranking.derived_metrics keys must be non-empty strings")
            continue
        path = f"ranking.derived_metrics[{name!r}]"
        if not isinstance(entry, dict):
            errors.append(f"{path} must be a dict")
            continue
        op = entry.get("operation")
        if op not in ALLOWED_DERIVED_OPS:
            errors.append(
                f"{path}.operation must be one of {sorted(ALLOWED_DERIVED_OPS)}, got {op!r}"
            )
            continue
        if _validate_derived_inputs(entry.get("inputs"), op, path, errors):
            specs[name] = entry
    return specs


def _validate_derived_inputs(
    inputs: Any, op: str, path: str, errors: list[str],
) -> bool:
    """Returns True if inputs are valid for the given op."""
    if op == "subtract":
        if (
            not isinstance(inputs, list) or len(inputs) != 2
            or not all(isinstance(x, str) and x for x in inputs)
        ):
            errors.append(
                f"{path}.inputs must be a list of 2 non-empty strings for 'subtract'"
            )
            return False
        return True
    # weighted_sum
    if not isinstance(inputs, dict) or not inputs:
        errors.append(f"{path}.inputs must be a non-empty dict for 'weighted_sum'")
        return False
    for k, w in inputs.items():
        if not isinstance(k, str) or not k:
            errors.append(f"{path}.inputs keys must be non-empty strings")
            return False
        if not _is_numeric(w):
            errors.append(f"{path}.inputs[{k!r}] weight must be numeric")
            return False
    return True


def _check_derived_metric_cycles(
    specs: dict[str, dict], errors: list[str],
) -> None:
    """DAG cycle detection via DFS with gray/black marking per node."""
    def _refs(e: dict) -> list[str]:
        inp = e.get("inputs")
        if isinstance(inp, list):
            return [x for x in inp if isinstance(x, str)]
        if isinstance(inp, dict):
            return [k for k in inp.keys() if isinstance(k, str)]
        return []

    GRAY, BLACK = 1, 2
    state: dict[str, int] = {}

    def _visit(node: str) -> bool:
        s = state.get(node)
        if s == GRAY:
            return True
        if s == BLACK or node not in specs:
            return False
        state[node] = GRAY
        for ref in _refs(specs[node]):
            if _visit(ref):
                return True
        state[node] = BLACK
        return False

    for name in specs:
        if state.get(name) is None and _visit(name):
            errors.append(f"ranking.derived_metrics[{name!r}] participates in a cycle")
