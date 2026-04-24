"""Shared Sprint F byte-identity helpers.

This module owns the JSON float round-trip contract for Sprint F fixtures:

- every float is serialized as ``{"__float_repr__": repr(x)}``
- fixtures are dumped with sorted keys and tight separators
- fixture hashes are computed over that normalized JSON form

The representation is intentionally explicit so fixture files stay portable
across Python versions without depending on the stdlib JSON encoder's float
formatting details.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pandas as pd

from src.features.event_proximity import get_event_proximity_features
from src.platform.strategy_spec import StrategySpec
from src.simulation.cache import fetch_cached_ohlcv
from src.universe.sp100 import get_sp100_universe

PRIMARY_FIXTURE_DATE = "2024-03-26"
FIXTURE_DATES = (
    "2024-01-16",
    "2024-02-13",
    "2024-03-26",
    "2024-04-23",
    "2024-05-21",
    "2024-06-18",
    "2024-07-16",
    "2024-08-13",
    "2024-09-10",
    "2024-11-19",
)
FIXTURE_DIR = Path(__file__).parent / "fixtures"

_FLOAT_SENTINEL = "__float_repr__"
_CACHE_ENV_VAR = "ARCIS_SIM_CACHE_ROOT"
_DEFAULT_CACHE_GLOB = "data/simulation_cache"


def _is_usable_cache_root(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    try:
        return any(child.suffix == ".parquet" for child in path.iterdir())
    except OSError:
        return False


def _normalize_scalar(value: Any) -> Any:
    if hasattr(value, "item") and not isinstance(value, (str, bytes, bytearray)):
        try:
            return _normalize_scalar(value.item())
        except Exception:
            pass
    if isinstance(value, float):
        return {_FLOAT_SENTINEL: repr(value)}
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if isinstance(value, Path):
        return str(value)
    return str(value)


def json_normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): json_normalize(val)
            for key, val in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [json_normalize(item) for item in value]
    if isinstance(value, set):
        return [json_normalize(item) for item in sorted(value)]
    return _normalize_scalar(value)


def json_restore(value: Any) -> Any:
    if isinstance(value, dict):
        if set(value.keys()) == {_FLOAT_SENTINEL}:
            return float(value[_FLOAT_SENTINEL])
        return {key: json_restore(val) for key, val in value.items()}
    if isinstance(value, list):
        return [json_restore(item) for item in value]
    return value


def stable_json_dumps(value: Any) -> str:
    return json.dumps(
        json_normalize(value),
        sort_keys=True,
        separators=(",", ":"),
    )


def stable_hash(value: Any) -> str:
    payload = stable_json_dumps(value).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def dump_fixture(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stable_json_dumps(payload), encoding="utf-8")


def load_fixture(path: Path) -> dict:
    return json_restore(json.loads(path.read_text(encoding="utf-8")))


def fixture_path(kind: str, as_of_date: str) -> Path:
    return FIXTURE_DIR / f"sprint_F_{kind}_{as_of_date}.json"


def resolve_cache_root(explicit: str | Path | None = None) -> Path:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(Path(explicit))

    env_value = os.environ.get(_CACHE_ENV_VAR)
    if env_value:
        candidates.append(Path(env_value))

    repo_root = Path(__file__).resolve().parents[3]
    candidates.extend(
        [
            repo_root / _DEFAULT_CACHE_GLOB,
            repo_root.parent / "halcyon-lab" / _DEFAULT_CACHE_GLOB,
            Path("/mnt/c/arcis/halcyon-lab") / _DEFAULT_CACHE_GLOB,
            Path("C:/arcis/halcyon-lab") / _DEFAULT_CACHE_GLOB,
        ]
    )

    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if _is_usable_cache_root(resolved):
            return resolved

    searched = ", ".join(str(path) for path in seen)
    raise FileNotFoundError(
        f"Could not locate simulation cache. Set {_CACHE_ENV_VAR} or pass --cache-root. "
        f"Searched: {searched}"
    )


def build_sprint_f_incumbent_strategy() -> StrategySpec:
    raw = {
        "ranking": {
            "derived_metrics": {
                "sector_rs_score": {
                    "operation": "weighted_sum",
                    "inputs": {"_sector_rs_score": 1.0},
                },
            },
            "bands": [
                {"metric": "trend_state", "category": "strong_uptrend", "score": 30},
                {"metric": "trend_state", "category": "uptrend", "score": 20},
                {"metric": "trend_state", "category": "neutral", "score": 5},
                {
                    "metric": "relative_strength_state",
                    "category": "strong_outperformer",
                    "score": 25,
                    "weight": 0.6,
                    "blend_group": "rs_blend",
                },
                {
                    "metric": "relative_strength_state",
                    "category": "outperformer",
                    "score": 15,
                    "weight": 0.6,
                    "blend_group": "rs_blend",
                },
                {
                    "metric": "sector_rs_score",
                    "range": [20.0, 30.0],
                    "score": 25,
                    "weight": 0.4,
                    "blend_group": "rs_blend",
                },
                {
                    "metric": "sector_rs_score",
                    "range": [10.0, 19.999999],
                    "score": 15,
                    "weight": 0.4,
                    "blend_group": "rs_blend",
                },
                {
                    "metric": "sector_rs_score",
                    "range": [1.0, 9.999999],
                    "score": 5,
                    "weight": 0.4,
                    "blend_group": "rs_blend",
                },
                {
                    "metric": "sector_rs_score",
                    "range": [-1.0, 0.999999],
                    "score": 0,
                    "weight": 0.4,
                    "blend_group": "rs_blend",
                },
                {"metric": "pullback_depth_pct", "range": [-8.0, -3.0], "score": 25},
                {"metric": "pullback_depth_pct", "range": [-12.0, -8.0], "score": 10},
                {"metric": "dist_to_sma20_pct", "range": [-5.0, -1.0], "score": 10},
                {"metric": "volume_ratio_20d", "range": [-999999.0, 0.799999], "score": 15},
                {"metric": "iv_rank", "range": [-999999.0, 24.999999], "score": 3},
                {
                    "conditions": [
                        {"metric": "iv_rank", "operator": ">", "threshold": 75.0},
                        {
                            "metric": "put_call_vol_ratio",
                            "operator": ">",
                            "threshold": 1.2,
                        },
                    ],
                    "score": -3,
                },
            ],
            "adjustments": {
                "bands": [
                    {
                        "conditions": [
                            {"metric": "regime_label", "operator": "==", "threshold": "calm_uptrend"},
                            {
                                "metric": "market_breadth_label",
                                "operator": "==",
                                "threshold": "healthy",
                            },
                        ],
                        "score": 5,
                    },
                    {
                        "conditions": [
                            {"metric": "regime_label", "operator": "==", "threshold": "calm_uptrend"},
                            {
                                "metric": "market_breadth_label",
                                "operator": "==",
                                "threshold": "narrowing",
                            },
                        ],
                        "score": 2,
                    },
                    {
                        "conditions": [
                            {"metric": "regime_label", "operator": "==", "threshold": "transitional"},
                        ],
                        "score": -3,
                    },
                    {
                        "conditions": [
                            {
                                "metric": "regime_label",
                                "operator": "==",
                                "threshold": "calm_downtrend",
                            },
                        ],
                        "score": -5,
                    },
                    {
                        "conditions": [
                            {
                                "metric": "regime_label",
                                "operator": "==",
                                "threshold": "volatile_downtrend",
                            },
                        ],
                        "score": -10,
                    },
                    {"metric": "spy_rsi_14", "range": [75.000001, 999999.0], "score": -3},
                    {"metric": "spy_rsi_14", "range": [-999999.0, 29.999999], "score": 3},
                ],
                "clamp": [-10.0, 10.0],
            },
        },
        "enrichment": {"chain": ["technicals", "macro", "insider", "news", "sector"]},
        "post_scan": {"chain": ["traffic_light", "event_risk"]},
    }
    return StrategySpec(
        strategy_id="sprint_f_incumbent_v1",
        display_name="Sprint F Incumbent",
        universe={"tickers": ["SP100"]},
        entry={"kind": "scheduled"},
        exit={"kind": "python_plugin"},
        position_sizing={"method": "fixed_pct_equity", "pct": 0.1},
        attribution={"benchmark": "SPY"},
        raw=raw,
        source="synthetic://sprint_f_incumbent_v1",
    )


def load_market_snapshot(
    as_of_date: str,
    *,
    cache_root: str | Path | None = None,
    start: str = "2023-01-01",
    end: str = "2024-12-31",
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    cache_dir = resolve_cache_root(cache_root)
    cutoff = pd.Timestamp(as_of_date)

    ohlcv_data: dict[str, pd.DataFrame] = {}
    for ticker in get_sp100_universe():
        df = fetch_cached_ohlcv(ticker, start, end, cache_dir=cache_dir)
        if df is None or df.empty:
            continue
        sliced = df[df.index <= cutoff].copy()
        if not sliced.empty:
            ohlcv_data[ticker] = sliced

    spy = fetch_cached_ohlcv("SPY", start, end, cache_dir=cache_dir)
    if spy is None or spy.empty:
        raise FileNotFoundError(f"Missing SPY cache for {start}..{end} under {cache_dir}")
    spy = spy[spy.index <= cutoff].copy()
    if spy.empty:
        raise ValueError(f"SPY cache has no rows on or before {as_of_date}")

    return ohlcv_data, spy


# Canonical config snapshot used to capture the Sprint F byte-identity fixtures.
# Operator's local settings.local.yaml may diverge (e.g., bootcamp.enabled=true);
# without this fixed snapshot the legacy ranker pulls operator-specific
# thresholds and breaks fixture comparison.
_BYTE_IDENTITY_CONFIG = {
    "bootcamp": {"enabled": False},
    "regime_adaptive": {"enabled": True},
    "ranking": {},
    "risk": {},
    "trading": {},
}


@contextmanager
def historical_feature_patches(as_of_date: str):
    reference_date = pd.Timestamp(as_of_date).date()
    with (
        patch("src.features.engine._load_options_metrics", return_value={}),
        patch(
            "src.features.engine._load_event_proximity",
            side_effect=lambda: get_event_proximity_features(reference_date=reference_date),
        ),
        patch("src.features.earnings.get_next_earnings_date", return_value=None),
        patch("src.ranking.ranker.load_config", return_value=_BYTE_IDENTITY_CONFIG),
    ):
        yield


def compute_engine_outputs(
    as_of_date: str,
    *,
    strategy: StrategySpec | None = None,
    cache_root: str | Path | None = None,
) -> dict[str, dict]:
    from src.features.engine import compute_all_features

    ohlcv_data, spy = load_market_snapshot(as_of_date, cache_root=cache_root)
    with historical_feature_patches(as_of_date):
        if strategy is None:
            return compute_all_features(ohlcv_data, spy)
        return compute_all_features(ohlcv_data, spy, strategy=strategy)


def compute_ranked_outputs(
    as_of_date: str,
    *,
    strategy: StrategySpec | None = None,
    cache_root: str | Path | None = None,
) -> list[dict]:
    from src.ranking.ranker import rank_universe

    features = compute_engine_outputs(as_of_date, strategy=strategy, cache_root=cache_root)
    ranked_input = copy.deepcopy(features)
    with historical_feature_patches(as_of_date):
        if strategy is None:
            return rank_universe(ranked_input)
        return rank_universe(ranked_input, strategy=strategy)


def engine_fixture_payload(
    as_of_date: str,
    features: dict[str, dict],
) -> dict:
    tickers = []
    for ticker in sorted(features):
        tickers.append(
            {
                "ticker": ticker,
                "features_hash": stable_hash(features[ticker]),
            }
        )
    return {
        "fixture_id": f"sprint_F_engine_{as_of_date}",
        "generated_from": _git_sha(),
        "as_of_date": as_of_date,
        "spec_path": "synthetic://sprint_f_incumbent_v1",
        "n_tickers": len(tickers),
        "tickers": tickers,
    }


def ranker_fixture_payload(
    as_of_date: str,
    ranked: list[dict],
) -> dict:
    candidates = []
    for row in ranked:
        candidates.append(
            {
                "ticker": row["ticker"],
                "score": row["score"],
                "qualification": row["qualification"],
                "features_hash": stable_hash(row["features"]),
            }
        )
    return {
        "fixture_id": f"sprint_F_ranker_{as_of_date}",
        "generated_from": _git_sha(),
        "as_of_date": as_of_date,
        "spec_path": "synthetic://sprint_f_incumbent_v1",
        "n_candidates": len(candidates),
        "candidates": candidates,
    }


def _git_sha() -> str | None:
    head = Path(".git/HEAD")
    if not head.exists():
        return None
    try:
        ref = head.read_text(encoding="utf-8").strip()
        if ref.startswith("ref: "):
            ref_path = Path(".git") / ref[5:]
            if ref_path.exists():
                return ref_path.read_text(encoding="utf-8").strip()
        return ref
    except Exception:
        return None
