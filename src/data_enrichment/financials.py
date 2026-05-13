"""Plan-gated stock_financials runtime reader (Sprint 5 Wave C7b.4 / T24).

Called by: data_enrichment.enricher (runtime enrichment pass)
Calls: data_enrichment.finnhub_plan
Owns tables: none — reads `data/finnhub_fundamentals/<ticker>.json`,
            the JSON sink written by scripts/finnhub_fundamental_export.py
Config keys: data_enrichment.finnhub_plan, FINNHUB_PLAN
Tests: tests/data_enrichment/test_financials.py

Runtime promotion of the Finnhub fundamental export pipeline. The export
script is nightly + offline; this module reads its JSON sink at scan time
to surface live P/E, debt/equity, gross margin, ROIC, and a quality flag
into the FUNDAMENTAL SNAPSHOT packet section.

Decision 30: gated on ``finnhub_plan_supports('stock_financials', config)``.
When the plan does not support the feature, returns None and the caller
preserves the existing SEC-EDGAR-derived fundamental_summary fallback.

This module NEVER calls the Finnhub API — only reads the JSON sink. The
sink is refreshed by scripts/finnhub_fundamental_export.py nightly (T24
does NOT modify that script).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from src.data_enrichment.finnhub_plan import finnhub_plan_supports

logger = logging.getLogger(__name__)

DEFAULT_SINK_DIR = "data/finnhub_fundamentals"

# Quality-flag thresholds. Coarse heuristic from spec section 4.13: a
# snapshot is "ok" when P/E is finite and within a reasonable equity range
# AND ROIC is positive; otherwise "low".
_PE_REASONABLE_LO = 2.0
_PE_REASONABLE_HI = 200.0


def _derive_quality_flag(
    pe: float | None,
    roic: float | None,
    config: dict | None = None,
) -> str | None:
    """Coarse quality flag from P/E + ROIC. Returns "ok" / "low" / None.

    P/E thresholds are operator-tunable via
    ``data_enrichment.fundamental_quality_thresholds.pe_min`` and
    ``data_enrichment.fundamental_quality_thresholds.pe_max`` in
    ``config/settings.local.yaml``.  Falls back to the module-level
    ``_PE_REASONABLE_LO`` / ``_PE_REASONABLE_HI`` constants when the
    config keys are absent or config is None (backward-compatible).
    """
    thresholds = ((config or {}).get("data_enrichment") or {}).get(
        "fundamental_quality_thresholds") or {}
    pe_lo = float(thresholds.get("pe_min", _PE_REASONABLE_LO))
    pe_hi = float(thresholds.get("pe_max", _PE_REASONABLE_HI))

    if pe is None and roic is None:
        return None
    pe_ok = (
        isinstance(pe, (int, float))
        and pe_lo <= pe <= pe_hi
    )
    roic_ok = isinstance(roic, (int, float)) and roic > 0
    if pe_ok and roic_ok:
        return "ok"
    return "low"


def _coerce_float(value) -> float | None:
    """Numeric coercion; returns None on non-finite or bad input."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    # Reject NaN / inf — they would corrupt downstream prompt rendering.
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def _compute_snapshot_age_days(fetched_at: str | None) -> int | None:
    """Days since the JSON sink's ``fetched_at`` timestamp."""
    if not fetched_at:
        return None
    try:
        ts = datetime.fromisoformat(str(fetched_at).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - ts).days)
    except (ValueError, TypeError):
        return None


def _read_sink_payload(sink_path: Path, ticker: str) -> dict | None:
    """Read + parse a sink JSON file; logs + returns None on failure."""
    if not sink_path.exists():
        logger.debug(
            "[FINANCIALS] No JSON sink for %s at %s — caller falls back "
            "to last-known fundamental_summary", ticker, sink_path,
        )
        return None
    try:
        return json.loads(sink_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "[FINANCIALS] Failed to read %s: %s — falling back to None",
            sink_path, exc,
        )
        return None


def _extract_fundamental_dict(payload: dict, config: dict | None = None) -> dict:
    """Project a Finnhub fundamentals JSON payload onto the runtime
    fundamental_* feature-dict surface."""
    metric = payload.get("metric") or {}
    pe = _coerce_float(metric.get("peNormalizedAnnual"))
    roic = _coerce_float(metric.get("roiTTM"))
    return {
        "fundamental_pe": pe,
        "fundamental_debt_to_equity": _coerce_float(
            metric.get("totalDebt/totalEquityAnnual")),
        "fundamental_gross_margin": _coerce_float(metric.get("grossMarginTTM")),
        "fundamental_roic": roic,
        "fundamental_quality_flag": _derive_quality_flag(pe, roic, config),
        "fundamental_snapshot_age_days": _compute_snapshot_age_days(
            payload.get("fetched_at")),
    }


def load_stock_financials(
    ticker: str,
    config: dict | None = None,
    sink_dir: str = DEFAULT_SINK_DIR,
) -> dict | None:
    """Read the per-ticker Finnhub fundamentals JSON sink (plan-gated).

    Returns a dict with the following keys when plan supports + sink JSON
    exists: fundamental_pe, fundamental_debt_to_equity,
    fundamental_gross_margin, fundamental_roic, fundamental_quality_flag,
    fundamental_snapshot_age_days.

    Returns None when plan does not support stock_financials (Decision 30)
    or the JSON sink file does not exist (caller preserves the existing
    SEC-EDGAR fundamental_summary fallback).
    """
    if not finnhub_plan_supports("stock_financials", config):
        logger.info(
            "[FINANCIALS] Skipped %s — Finnhub plan does not support "
            "stock_financials", ticker,
        )
        return None
    payload = _read_sink_payload(Path(sink_dir) / f"{ticker}.json", ticker)
    if payload is None:
        return None
    return _extract_fundamental_dict(payload, config)
