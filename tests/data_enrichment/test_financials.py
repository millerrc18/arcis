"""Tests for src/data_enrichment/financials.py.

Sprint 5 Wave C7b.4 (T24): stock_financials runtime promotion —
read-only enricher that reads the JSON sink left by
scripts/finnhub_fundamental_export.py and surfaces live P/E,
debt/equity, gross margin, ROIC, quality flag into the
FUNDAMENTAL SNAPSHOT packet section.

Four tests per spec section 4.13:
  1. plan=fundamental-1 -> reads JSON + enriches dict
  2. plan=free          -> returns None (last-known cached fallback preserved)
  3. FUNDAMENTAL SNAPSHOT in-place enrichment with live fields
  4. Snapshot age-days computed from JSON ``fetched_at``
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fundamentals_dir(tmp_path: Path) -> Path:
    """Temp directory acting as data/finnhub_fundamentals/<ticker>.json sink."""
    d = tmp_path / "finnhub_fundamentals"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_sample_json(dir_path: Path, ticker: str, fetched_at: str | None = None):
    """Write a sample Finnhub fundamentals JSON payload."""
    payload = {
        "symbol": ticker,
        "fetched_at": fetched_at or datetime.now(timezone.utc).isoformat(),
        "metric": {
            "peNormalizedAnnual": 28.5,
            "totalDebt/totalEquityAnnual": 1.45,
            "grossMarginTTM": 0.452,
            "roiTTM": 0.215,
        },
    }
    (dir_path / f"{ticker}.json").write_text(json.dumps(payload), encoding="utf-8")
    return payload


# ---------------------------------------------------------------------------
# Test 1: plan=fundamental-1 reads JSON + enriches
# ---------------------------------------------------------------------------


def test_plan_fundamental_1_reads_json_and_enriches(fundamentals_dir, monkeypatch):
    """plan=fundamental-1: read JSON sink, return fundamental dict
    populated with live P/E, debt/equity, gross margin, ROIC, quality
    flag, snapshot_age_days."""
    monkeypatch.setenv("FINNHUB_PLAN", "fundamental-1")
    from src.data_enrichment.financials import load_stock_financials

    _write_sample_json(fundamentals_dir, "AAPL")
    config = {"data_enrichment": {"finnhub_plan": "fundamental-1"}}

    result = load_stock_financials("AAPL", config=config, sink_dir=str(fundamentals_dir))

    assert result is not None
    assert result["fundamental_pe"] == pytest.approx(28.5)
    assert result["fundamental_debt_to_equity"] == pytest.approx(1.45)
    assert result["fundamental_gross_margin"] == pytest.approx(0.452)
    assert result["fundamental_roic"] == pytest.approx(0.215)
    # Quality flag is derived (P/E reasonable + ROIC > 0 => "ok").
    assert "fundamental_quality_flag" in result


# ---------------------------------------------------------------------------
# Test 2: plan=free returns None
# ---------------------------------------------------------------------------


def test_plan_free_returns_none(fundamentals_dir, monkeypatch):
    """plan=free: gate is closed; returns None — last-known cached
    fundamental_summary fallback is preserved by the caller (Decision 30)."""
    monkeypatch.setenv("FINNHUB_PLAN", "free")
    from src.data_enrichment.financials import load_stock_financials

    # Even with a JSON file present, plan-free must NOT load it.
    _write_sample_json(fundamentals_dir, "AAPL")
    config = {"data_enrichment": {"finnhub_plan": "free"}}

    result = load_stock_financials("AAPL", config=config, sink_dir=str(fundamentals_dir))
    assert result is None


# ---------------------------------------------------------------------------
# Test 3: FUNDAMENTAL SNAPSHOT in-place enrichment with live fields
# ---------------------------------------------------------------------------


def test_fundamental_snapshot_in_place_enriched_with_live_fields():
    """Live fundamental_* fields render inside the FUNDAMENTAL SNAPSHOT
    section (not as a separate block). When the feature dict carries
    fundamental_pe / fundamental_debt_to_equity / fundamental_gross_margin /
    fundamental_roic / fundamental_quality_flag, the rendered section MUST
    include those live values alongside the existing fundamental_summary."""
    from src.llm.packet_writer import _build_feature_prompt

    features = {
        "current_price": 150.0,
        "trend_state": "uptrend",
        "sma50_slope": "positive",
        "sma200_slope": "positive",
        "price_vs_sma50_pct": 5.0,
        "price_vs_sma200_pct": 10.0,
        "relative_strength_state": "strong",
        "rs_vs_spy_1m": 2.0,
        "rs_vs_spy_3m": 4.0,
        "rs_vs_spy_6m": 7.0,
        "pullback_depth_pct": 3.0,
        "atr_14": 2.5,
        "atr_pct": 1.5,
        "volume_ratio_20d": 1.2,
        "dist_to_sma20_pct": 1.0,
        "fundamental_summary": "Revenue (TTM): $383.3B (+3.1% YoY)",
        # T24 live fields (plan-supports + JSON sink read)
        "fundamental_pe": 28.5,
        "fundamental_debt_to_equity": 1.45,
        "fundamental_gross_margin": 0.452,
        "fundamental_roic": 0.215,
        "fundamental_quality_flag": "ok",
        "fundamental_snapshot_age_days": 1,
    }
    prompt = _build_feature_prompt(features, "AAPL")
    assert "=== FUNDAMENTAL SNAPSHOT ===" in prompt
    # Existing summary preserved.
    assert "Revenue (TTM): $383.3B" in prompt
    # T24 live fields appear in the section.
    assert "P/E" in prompt or "28.5" in prompt
    assert "Debt/Equity" in prompt or "1.45" in prompt
    # Gross margin live value present (formatted as percentage).
    assert "45.2%" in prompt or "Gross Margin" in prompt


# ---------------------------------------------------------------------------
# Test 4: snapshot age-days computed
# ---------------------------------------------------------------------------


def test_snapshot_age_days_computed(fundamentals_dir, monkeypatch):
    """The reader must compute fundamental_snapshot_age_days from the
    JSON ``fetched_at`` timestamp."""
    monkeypatch.setenv("FINNHUB_PLAN", "fundamental-1")
    from src.data_enrichment.financials import load_stock_financials

    three_days_ago = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    _write_sample_json(fundamentals_dir, "AAPL", fetched_at=three_days_ago)

    config = {"data_enrichment": {"finnhub_plan": "fundamental-1"}}
    result = load_stock_financials("AAPL", config=config, sink_dir=str(fundamentals_dir))

    assert result is not None
    age = result.get("fundamental_snapshot_age_days")
    assert age is not None
    # Allow 2-4 since reads can cross a day boundary.
    assert 2 <= age <= 4, f"Expected ~3 days, got {age}"


# ---------------------------------------------------------------------------
# Tests 5+6: WA3 — PE thresholds from config (Sprint 6 Wave A)
# ---------------------------------------------------------------------------


def test_quality_flag_respects_custom_thresholds():
    """Custom pe_min/pe_max in config override module-level defaults.

    With pe_min=5.0, pe_max=50.0: a stock with PE=3.0 (below min) must
    return 'low' even though 3.0 is within the default [2.0, 200.0] range.
    """
    from src.data_enrichment.financials import _derive_quality_flag

    custom_config = {
        "data_enrichment": {
            "fundamental_quality_thresholds": {
                "pe_min": 5.0,
                "pe_max": 50.0,
            }
        }
    }
    # PE=3.0 is below custom pe_min=5.0, ROIC positive — must be "low".
    result = _derive_quality_flag(pe=3.0, roic=0.12, config=custom_config)
    assert result == "low"

    # PE=20.0 is within [5.0, 50.0], ROIC positive — must be "ok".
    result_ok = _derive_quality_flag(pe=20.0, roic=0.12, config=custom_config)
    assert result_ok == "ok"


def test_quality_flag_falls_back_when_config_missing():
    """Without config the module-level defaults (pe_min=2.0, pe_max=200.0) apply.

    PE=3.0 is within the default range; positive ROIC → 'ok'.
    """
    from src.data_enrichment.financials import _derive_quality_flag

    result = _derive_quality_flag(pe=3.0, roic=0.12, config=None)
    assert result == "ok"
