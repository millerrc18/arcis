"""Strategy specification loader + validator.

Called by: src.platform.backtest_engine, scripts.run_backtest,
           src.scheduler.watch (Sprint 4 via Task 9).
Calls: pyyaml (safe_load), pathlib.
Owns tables: none.
Config keys: none.
Tests: tests/platform/test_strategy_spec.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_SPECS_DIR = Path(__file__).parent / "specs"

ALLOWED_ENTRY_KINDS = {"scheduled", "event_driven", "python_plugin"}
ALLOWED_EXIT_KINDS = {"mechanical", "python_plugin"}
ALLOWED_SIZING_METHODS = {"fixed_pct_equity", "regime_adaptive"}
# Matches REGIME_THRESHOLDS.keys() in src/ranking/ranker.py and
# classify_regime() return-set in src/features/regime.py. Changing this
# set is a breaking schema change — coordinate with ranker port (#530
# Sprint F) before editing.
KNOWN_REGIME_KEYS = frozenset({
    "BULL_LOW_VOL", "BULL_HIGH_VOL", "TRANSITION", "CORRECTION",
    "BEAR_EARLY", "BEAR_ESTABLISHED", "CRISIS",
})
REQUIRED_KEYS = (
    "spec_version", "strategy_id", "display_name", "universe", "entry", "exit",
    "position_sizing", "attribution",
)


def _is_positive_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x > 0


def _is_unit_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and 0.0 <= x <= 1.0


@dataclass
class StrategySpec:
    strategy_id: str
    display_name: str
    universe: dict
    entry: dict
    exit: dict
    position_sizing: dict
    attribution: dict
    llm_enhancement: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)
    source: str = ""


def validate_spec(spec: dict) -> tuple[bool, list[str]]:
    errors: list[str] = []
    for k in REQUIRED_KEYS:
        if k not in spec:
            errors.append(f"missing required key: {k}")
    if "universe" in spec and not isinstance(spec["universe"], dict):
        errors.append("universe must be a dict")
    if isinstance(spec.get("universe"), dict) and "sector_filter" in spec["universe"]:
        sf = spec["universe"]["sector_filter"]
        if not isinstance(sf, list) or not sf or not all(isinstance(x, str) for x in sf):
            errors.append(
                "universe.sector_filter must be a non-empty list of strings when present"
            )
    if "entry" in spec and isinstance(spec["entry"], dict):
        kind = spec["entry"].get("kind")
        if kind not in ALLOWED_ENTRY_KINDS:
            errors.append(
                f"entry.kind must be one of {sorted(ALLOWED_ENTRY_KINDS)}, got {kind!r}"
            )
        if "event_exclusion" in spec["entry"]:
            ex = spec["entry"]["event_exclusion"]
            if not isinstance(ex, dict):
                errors.append("entry.event_exclusion must be a dict when present")
            else:
                cats = ex.get("categories")
                if not isinstance(cats, list) or not cats or not all(isinstance(x, str) for x in cats):
                    errors.append(
                        "entry.event_exclusion.categories must be a non-empty list of strings"
                    )
    if "exit" in spec and isinstance(spec["exit"], dict):
        kind = spec["exit"].get("kind")
        if kind not in ALLOWED_EXIT_KINDS:
            errors.append(
                f"exit.kind must be one of {sorted(ALLOWED_EXIT_KINDS)}, got {kind!r}"
            )
        _validate_exit_brackets(spec["exit"], errors)
    if "position_sizing" in spec and isinstance(spec["position_sizing"], dict):
        _validate_position_sizing(spec["position_sizing"], errors)
    if "ranking" in spec:
        ranking = spec["ranking"]
        if not isinstance(ranking, dict):
            errors.append("ranking must be a dict when present")
        elif "bands" in ranking:
            bands = ranking["bands"]
            if not isinstance(bands, list):
                errors.append("ranking.bands must be a list when present")
            else:
                _validate_bands(bands, errors)
    return (len(errors) == 0, errors)


def _validate_bands(bands: list, errors: list[str]) -> None:
    parsed: list[tuple[str, float, float, int]] = []
    for i, band in enumerate(bands):
        if not isinstance(band, dict):
            errors.append(f"ranking.bands[{i}] must be a dict")
            continue
        metric = band.get("metric")
        if not isinstance(metric, str) or not metric:
            errors.append(
                f"ranking.bands[{i}].metric must be a non-empty string"
            )
            continue
        rng = band.get("range")
        if (
            not isinstance(rng, list)
            or len(rng) != 2
            or not all(
                isinstance(x, (int, float)) and not isinstance(x, bool)
                for x in rng
            )
        ):
            errors.append(
                f"ranking.bands[{i}].range must be a 2-element list of numerics"
            )
            continue
        lo, hi = rng
        if lo >= hi:
            errors.append(
                f"ranking.bands[{i}].range[0] must be < range[1] "
                f"(got {lo} >= {hi})"
            )
            continue
        score = band.get("score")
        if not isinstance(score, (int, float)) or isinstance(score, bool):
            errors.append(f"ranking.bands[{i}].score must be numeric")
            continue
        parsed.append((metric, float(lo), float(hi), i))

    by_metric: dict[str, list[tuple[float, float, int]]] = {}
    for metric, lo, hi, idx in parsed:
        by_metric.setdefault(metric, []).append((lo, hi, idx))
    for metric, entries in by_metric.items():
        for a in range(len(entries)):
            a_lo, a_hi, a_i = entries[a]
            for b in range(a + 1, len(entries)):
                b_lo, b_hi, b_i = entries[b]
                if a_lo <= b_hi and b_lo <= a_hi:
                    logger.warning(
                        "[PLATFORM] ranking.bands overlap: metric=%s "
                        "band#%d[%s,%s] overlaps band#%d[%s,%s]",
                        metric, a_i, a_lo, a_hi, b_i, b_lo, b_hi,
                    )


def _validate_exit_brackets(exit_block: dict, errors: list[str]) -> None:
    kind = exit_block.get("kind")
    has_target = "target" in exit_block
    has_targets = "targets" in exit_block

    if kind == "mechanical":
        if has_target and has_targets:
            errors.append("exit: 'target' and 'targets' are mutually exclusive — specify one")
            return
        if not has_target and not has_targets:
            errors.append("exit: mechanical kind requires one of 'target' or 'targets'")
            return
    if not has_targets:
        return  # legacy singular exit.target has no interior validation

    targets = exit_block["targets"]
    if not isinstance(targets, list) or not targets:
        errors.append("exit.targets must be a non-empty list when present")
        return

    seen: dict[str, int] = {}
    for i, entry in enumerate(targets):
        if not isinstance(entry, dict):
            errors.append(f"exit.targets[{i}] must be a dict")
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            errors.append(f"exit.targets[{i}].name must be a non-empty string")
        elif name in seen:
            errors.append(
                f"exit.targets[{i}].name duplicates exit.targets[{seen[name]}].name"
            )
        else:
            seen[name] = i
        if not _is_positive_number(entry.get("atr_multiple")):
            errors.append(f"exit.targets[{i}].atr_multiple must be a positive number")

    stop = exit_block.get("stop")
    if not isinstance(stop, dict):
        errors.append("exit.stop must be a dict with 'atr_multiple' when exit.targets is used")
        return
    if not _is_positive_number(stop.get("atr_multiple")):
        errors.append(
            "exit.stop.atr_multiple must be a positive number (required when exit.targets is used)"
        )


def _validate_position_sizing(sizing: dict, errors: list[str]) -> None:
    method = sizing.get("method")
    if method is None:
        return  # permissive: absence handled upstream (REQUIRED_KEYS only checks the parent)
    if method not in ALLOWED_SIZING_METHODS:
        errors.append(
            f"position_sizing.method must be one of {sorted(ALLOWED_SIZING_METHODS)}, "
            f"got {method!r}"
        )
        return
    if method != "regime_adaptive":
        return  # fixed_pct_equity interior passes through unvalidated (backward compat)

    regimes = sizing.get("regimes")
    if not isinstance(regimes, dict) or not regimes:
        errors.append(
            "position_sizing.regimes must be a non-empty dict when method == 'regime_adaptive'"
        )
        return
    for rkey, rval in regimes.items():
        if rkey not in KNOWN_REGIME_KEYS:
            logger.warning(
                "[PLATFORM] position_sizing.regimes: unknown regime key %r (known: %s)",
                rkey, ", ".join(sorted(KNOWN_REGIME_KEYS)),
            )
        if not isinstance(rval, dict):
            errors.append(f"position_sizing.regimes[{rkey}] must be a dict")
            continue
        if not isinstance(rval.get("packet_worthy"), bool):
            errors.append(f"position_sizing.regimes[{rkey}].packet_worthy must be a bool")
        if not _is_unit_number(rval.get("position_pct")):
            errors.append(
                f"position_sizing.regimes[{rkey}].position_pct must be a number in [0.0, 1.0]"
            )


def _from_dict(d: dict, source: str) -> StrategySpec:
    ok, errors = validate_spec(d)
    if not ok:
        raise ValueError(f"invalid strategy spec ({source}): {errors}")
    return StrategySpec(
        strategy_id=d["strategy_id"],
        display_name=d["display_name"],
        universe=d["universe"],
        entry=d["entry"],
        exit=d["exit"],
        position_sizing=d["position_sizing"],
        attribution=d["attribution"],
        llm_enhancement=d.get("llm_enhancement", {}),
        raw=d,
        source=source,
    )


def load_spec_from_yaml(path: Path) -> StrategySpec:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return _from_dict(data, source=f"yaml:{path}")


def load_spec(
    strategy_id: str,
    specs_dir: Path = _SPECS_DIR,
) -> StrategySpec:
    path = Path(specs_dir) / f"{strategy_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"no spec found for strategy_id={strategy_id!r} at {path}"
        )
    return load_spec_from_yaml(path)


def list_available_specs(
    specs_dir: Path = _SPECS_DIR,
) -> list[StrategySpec]:
    out: list[StrategySpec] = []
    for p in sorted(Path(specs_dir).glob("*.yaml")):
        try:
            out.append(load_spec_from_yaml(p))
        except Exception as e:
            logger.warning(
                "[PLATFORM] skipping malformed spec %s: %s", p, e
            )
    return out
