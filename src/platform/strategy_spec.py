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
    if "entry" in spec and isinstance(spec["entry"], dict):
        kind = spec["entry"].get("kind")
        if kind not in ALLOWED_ENTRY_KINDS:
            errors.append(
                f"entry.kind must be one of {sorted(ALLOWED_ENTRY_KINDS)}, got {kind!r}"
            )
    if "exit" in spec and isinstance(spec["exit"], dict):
        kind = spec["exit"].get("kind")
        if kind not in ALLOWED_EXIT_KINDS:
            errors.append(
                f"exit.kind must be one of {sorted(ALLOWED_EXIT_KINDS)}, got {kind!r}"
            )
    return (len(errors) == 0, errors)


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
