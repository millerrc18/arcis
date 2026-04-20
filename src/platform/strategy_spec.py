"""Strategy specification loader + validator.

Called by: src.platform.backtest_engine, scripts.run_backtest,
           src.scheduler.watch (Sprint 4 via Task 9).
Calls: pyyaml (safe_load), pathlib, src.platform._strategy_spec_ranking.
Owns tables: none.
Config keys: none.
Tests: tests/platform/test_strategy_spec.py,
       tests/platform/specs/test_schema_final_blocks.py,
       tests/platform/specs/test_schema_c1_refinements.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Ranking-block validators live in a submodule to keep this file focused.
# See src/platform/_strategy_spec_ranking.py for the Item 3-8 validators.
from src.platform._strategy_spec_ranking import (
    KNOWN_REGIME_LABELS,
    KNOWN_SCORING_METRICS,
    validate_adjustments as _validate_adjustments,
    validate_bands as _validate_bands,
    validate_derived_metrics as _validate_derived_metrics,
)

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
# Sprint E seed sets. See docs/sprints/schema_final_blocks_evaluation.md
# for strict-vs-warn justification per block.
KNOWN_ATTRIBUTION_HOOKS = frozenset({"log_before_llm", "log_after_llm"})
KNOWN_ENRICHERS = frozenset({"technicals", "insider", "macro", "news", "sector"})
# Sprint C.1 Item 2 (#568): aligned to runtime dispatch in
# enrichment.py::attach_post_scan_features (hardcoded imports for
# compute_traffic_light + attach_event_risk_scores). strict=True in
# _LIST_BLOCKS makes drift hard-fail. Sprint F wires string dispatch.
KNOWN_POST_SCAN_HELPERS = frozenset({"traffic_light", "event_risk"})
# Sprint C.1 Item 9 (#569): all categories use lowercase_with_underscores.
# Runtime emits lowercase via event_risk_score.py `components` dict
# (lines 201-207); MACRO_EVENT_TYPES uppercase at line 25 is internal
# CSV/DB input-normalization only, invisible to specs. Union of
# sprint-prompt earnings + MACRO_EVENT_TYPES (lowercased) + KNOWN_EVENTS.
KNOWN_EVENT_RISK_CATEGORIES = frozenset({
    "earnings_imminent", "earnings_elevated",
    "fomc", "nfp", "cpi",
    "cpi_print", "export_controls", "fomc_decision", "industrial_policy",
    "nfp_friday", "opex_monthly", "opex_weekly", "ppi_print",
    "quarter_end_rebalance", "sanctions_initial", "sanctions_escalation",
    "tariff_pause", "tariff_announcement", "tariff_escalation",
    "trade_disruption",
})
KNOWN_BOOTCAMP_KEYS = frozenset({
    "qualification_threshold", "max_positions",
    "watchlist_threshold", "traffic_light_floor",
})
# Dispatch table: (outer, inner, known_refs, strict). strict=True rejects;
# strict=False warns. Sprint C.1 Item 2: post_scan.chain flipped to
# strict=True post-contents-fix.
_LIST_BLOCKS: tuple[tuple[str, str, frozenset[str], bool], ...] = (
    ("hooks", "attribution", KNOWN_ATTRIBUTION_HOOKS, True),
    ("enrichment", "chain", KNOWN_ENRICHERS, False),
    ("post_scan", "chain", KNOWN_POST_SCAN_HELPERS, True),
    ("event_risk", "quarantine_categories", KNOWN_EVENT_RISK_CATEGORIES, False),
)
REQUIRED_KEYS = (
    "spec_version", "strategy_id", "display_name", "universe", "entry", "exit",
    "position_sizing", "attribution",
)

__all__ = [
    "ALLOWED_ENTRY_KINDS", "ALLOWED_EXIT_KINDS", "ALLOWED_SIZING_METHODS",
    "KNOWN_REGIME_KEYS", "KNOWN_REGIME_LABELS",
    "KNOWN_ATTRIBUTION_HOOKS", "KNOWN_ENRICHERS",
    "KNOWN_POST_SCAN_HELPERS", "KNOWN_EVENT_RISK_CATEGORIES",
    "KNOWN_BOOTCAMP_KEYS", "KNOWN_SCORING_METRICS",
    "REQUIRED_KEYS",
    "StrategySpec", "validate_spec",
    "load_spec", "load_spec_from_yaml", "list_available_specs",
]


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
        _validate_ranking_block(spec["ranking"], errors)
    for outer, inner, known, strict in _LIST_BLOCKS:
        if outer in spec and isinstance(spec[outer], dict):
            _validate_known_ref_list(
                spec[outer].get(inner), known,
                f"{outer}.{inner}", errors, strict=strict,
            )
    if "bootcamp" in spec and isinstance(spec["bootcamp"], dict):
        _validate_bootcamp_overrides(spec["bootcamp"], errors)
    return (len(errors) == 0, errors)


def _validate_ranking_block(ranking: Any, errors: list[str]) -> None:
    """Dispatch ranking-block sub-validators (Sprint C.1 Items 3-8).

    derived_metrics runs first so its output names can be referenced by
    bands and adjustments. All three share the same effective
    known_metrics set.
    """
    if not isinstance(ranking, dict):
        errors.append("ranking must be a dict when present")
        return
    derived_names: frozenset[str] = frozenset()
    if "derived_metrics" in ranking:
        derived_names = _validate_derived_metrics(ranking["derived_metrics"], errors)
    known_metrics = KNOWN_SCORING_METRICS | derived_names
    if "bands" in ranking:
        bands = ranking["bands"]
        if not isinstance(bands, list):
            errors.append("ranking.bands must be a list when present")
        else:
            _validate_bands(bands, errors, known_metrics=known_metrics)
    if "adjustments" in ranking:
        adj = ranking["adjustments"]
        if not isinstance(adj, dict):
            errors.append("ranking.adjustments must be a dict when present")
        else:
            _validate_adjustments(adj, errors, known_metrics=known_metrics)


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
        # Sprint C.1 Item 1 (#567): hard-rename packet_worthy → min_score.
        # Original field was validated as bool but runtime stored an int
        # threshold — type mismatch. Hard-rename, no legacy alias.
        if not _is_int_0_100(rval.get("min_score")):
            errors.append(
                f"position_sizing.regimes[{rkey}].min_score must be an int in [0, 100]"
            )
        if not _is_unit_number(rval.get("position_pct")):
            errors.append(
                f"position_sizing.regimes[{rkey}].position_pct must be a number in [0.0, 1.0]"
            )


def _validate_known_ref_list(
    items: Any, known: frozenset[str], path: str,
    errors: list[str], *, strict: bool,
) -> None:
    """Validate optional list-of-string-refs. strict=True rejects unknowns;
    strict=False warns via logger (Sprint C/D precedent)."""
    if items is None:
        return
    if not isinstance(items, list):
        errors.append(f"{path} must be a list when present")
        return
    if not items:
        errors.append(f"{path} must be a non-empty list when present")
        return
    for i, item in enumerate(items):
        if not isinstance(item, str) or not item:
            errors.append(f"{path}[{i}] must be a non-empty string")
            continue
        if item not in known:
            if strict:
                errors.append(
                    f"{path}[{i}] unknown ref {item!r} "
                    f"(known: {', '.join(sorted(known))})"
                )
            else:
                logger.warning(
                    "[PLATFORM] %s[%d]: unknown ref %r (known: %s)",
                    path, i, item, ", ".join(sorted(known)),
                )


def _is_positive_int(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool) and x > 0


def _is_int_0_100(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool) and 0 <= x <= 100


_BOOTCAMP_RULES: tuple[tuple[str, Any, str], ...] = (
    ("qualification_threshold", _is_int_0_100, "must be an int in [0, 100]"),
    ("watchlist_threshold", _is_int_0_100, "must be an int in [0, 100]"),
    ("max_positions", _is_positive_int, "must be a positive int"),
    ("traffic_light_floor", _is_unit_number, "must be a number in [0.0, 1.0]"),
)


def _validate_bootcamp_overrides(block: dict, errors: list[str]) -> None:
    unknown = set(block.keys()) - KNOWN_BOOTCAMP_KEYS
    if unknown:
        errors.append(
            f"bootcamp: unknown keys {sorted(unknown)!r} "
            f"(allowed: {sorted(KNOWN_BOOTCAMP_KEYS)})"
        )
    for key, check, msg in _BOOTCAMP_RULES:
        if key in block and not check(block[key]):
            errors.append(f"bootcamp.{key} {msg}")


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
