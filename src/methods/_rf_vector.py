"""Per-period risk-free rate vector helper for the methodology toolkit.

Sprint-0 Wave-3b RF-WIRING: kpis.py and stage1_baseline_recompute.py both
already implement an inline `_compute_per_trade_rf(trades)` helper that turns
trade rows into a per-trade rf vector via FRED DTB3 with a placeholder
fallback (kpis.py:75-133, stage1_baseline_recompute.py:119-170). The five
methodology consumers (cpcv, cpcv_anchored, block_bootstrap_ci,
mc_permutation_pvalue, promotion_gate) operate on raw return arrays + an
optional list of dates rather than full trade dicts, so this module exposes a
narrower helper:

    compute_per_period_rf_vector(dates: Sequence[date]) -> tuple[list[float], bool]

Returns (rf_vec, used_fred). Each element is the per-period rf rate at the
matching index; placeholder fallback per index when FRED fails. The boolean
flag is True iff at least one element came from FRED — used by the
promotion-gate logger to mark the rf source.

Why a separate module: keep `risk_free_rate.py`'s public surface minimal
(only `get_rf_rate(date)` is the canonical adapter API), and avoid coupling
between methods/ and api/cloud_routes/.

Called by: src.methods.cpcv, src.methods.block_bootstrap,
  src.methods.mc_permutation, src.methods.promotion_gate.
Calls: src.data_ingestion.risk_free_rate.get_rf_rate,
  src.data_collection.errors.CollectorConfigError.
Owns tables: none.
Config keys: none (FRED_API_KEY env honored transitively via get_rf_rate).
Tests: tests/methods/test_rf_vector.py (regression-locking) +
  tests/methods/test_promotion_gate.py (integration with mocked FRED).
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Sequence

logger = logging.getLogger(__name__)

# Per-trading-day fallback rate. Annualized ~2.52% / 252 ~= 0.01% per
# trading day. Mirrors scripts/stage1_baseline_recompute.py:RF_PERIOD_CONSTANT
# and src/api/cloud_routes/kpis.py:_RF_PERIOD — keep all three in lockstep.
RF_PERIOD_CONSTANT = 0.0001


def compute_per_period_rf_vector(
    dates: Sequence[_dt.date],
) -> tuple[list[float], bool]:
    """Build a per-period rf vector from a sequence of dates.

    For each date, calls `get_rf_rate(date)` to get the per-trading-day
    decimal rate from FRED DTB3. On any failure (config error, network,
    KeyError), falls back to `RF_PERIOD_CONSTANT` for that entry and logs a
    WARNING with the `[METHODS_RF_FALLBACK]` marker (mirrors the kpis.py /
    stage1 pattern; the marker is unique to this module so log greps stay
    site-attributable).

    Args:
        dates: Sequence of `datetime.date` objects, one per period (e.g. one
            per trade).

    Returns:
        (rf_vec, used_fred) — `rf_vec` has the same length as `dates`;
        `used_fred` is True iff at least one entry came from FRED (i.e. not
        every date fell through to the placeholder).
    """
    from src.data_collection.errors import CollectorConfigError
    from src.data_ingestion.risk_free_rate import get_rf_rate

    rfs: list[float] = []
    used_fred = False
    for d in dates:
        if not isinstance(d, _dt.date):
            logger.warning(
                "[METHODS_RF_FALLBACK] non-date input %r — using placeholder rf=%s",
                d, RF_PERIOD_CONSTANT,
            )
            rfs.append(RF_PERIOD_CONSTANT)
            continue
        try:
            per_day = get_rf_rate(d)
        except CollectorConfigError as exc:
            logger.warning(
                "[METHODS_RF_FALLBACK] FRED API key missing — using "
                "placeholder rf=%s (date=%s): %s",
                RF_PERIOD_CONSTANT, d, exc,
            )
            rfs.append(RF_PERIOD_CONSTANT)
            continue
        except Exception as exc:  # noqa: BLE001  — network/HTTP/KeyError fallthrough
            logger.warning(
                "[METHODS_RF_FALLBACK] FRED fetch failed — using "
                "placeholder rf=%s (date=%s): %s",
                RF_PERIOD_CONSTANT, d, exc,
                exc_info=True,
            )
            rfs.append(RF_PERIOD_CONSTANT)
            continue
        used_fred = True
        rfs.append(per_day)
    return rfs, used_fred
