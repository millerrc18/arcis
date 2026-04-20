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
REQUIRED_KEYS = (
    "spec_version", "strategy_id", "display_name", "universe", "entry", "exit",
    "position_sizing", "attribution",
)


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
