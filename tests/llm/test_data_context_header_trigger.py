"""Tests for the DATA CONTEXT header prepend (Sprint 5 Wave C7b.4 / T24).

The DATA CONTEXT header is a prompt preamble that the LLM packet writer
prepends when ≥1 Tier-2 section omits from the prompt (spec section
4.8.1). Tier-2 sections in Wave C7b are:
  * INSTITUTIONAL FLOW  (T21)
  * MATERIAL EVENTS     (T22 + T23 sub-blocks)
  * FUNDAMENTAL SNAPSHOT live-enrichment (T24)

Tier-1 sections (always present, plan-independent) are NOT counted for
header-trigger purposes (Decision 32).

Three tests per brief:
  1. Header omitted when all Tier-2 sections present
  2. Header present when ≥1 Tier-2 section omits
  3. Header content lists exact omitted section names
"""

from __future__ import annotations

import pytest


def _base_features() -> dict:
    """Minimal Tier-1 features that always render so test feature dicts
    are well-formed without polluting Tier-2 signals."""
    return {
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
    }


# ---------------------------------------------------------------------------
# Test 1: Header omitted when all Tier-2 sections present
# ---------------------------------------------------------------------------


def test_header_omitted_when_all_tier2_sections_present():
    """When INSTITUTIONAL FLOW + MATERIAL EVENTS + FUNDAMENTAL SNAPSHOT
    live-enrichment are ALL present, DATA CONTEXT header MUST be absent."""
    from src.llm.packet_writer import _build_feature_prompt

    features = _base_features()
    # INSTITUTIONAL FLOW present (T21).
    features.update({
        "_institutional_plan_supports": True,
        "institutional_total_shares": 1_000_000_000,
        "institutional_num_holders": 100,
        "institutional_top5_pct": 25.0,
        "institutional_qoq_delta_pct": 1.5,
        "institutional_data_age_days": 2,
    })
    # MATERIAL EVENTS (filings_sentiment sub-block) present (T22).
    features.update({
        "_filings_sentiment_plan_supports": True,
        "filing_sentiment_score": 0.42,
        "filing_sentiment_label": "positive",
        "latest_filing_type": "10-K",
        "latest_filing_age_days": 7,
    })
    # FUNDAMENTAL SNAPSHOT live-enrichment present (T24).
    features.update({
        "fundamental_summary": "Revenue (TTM): $383.3B",
        "fundamental_pe": 28.5,
        "fundamental_debt_to_equity": 1.45,
        "fundamental_gross_margin": 0.452,
        "fundamental_roic": 0.215,
        "fundamental_quality_flag": "ok",
        "fundamental_snapshot_age_days": 1,
    })

    prompt = _build_feature_prompt(features, "AAPL")
    assert "=== DATA CONTEXT ===" not in prompt, (
        "DATA CONTEXT header MUST be absent when all Tier-2 sections "
        "render with content"
    )


# ---------------------------------------------------------------------------
# Test 2: Header present when ≥1 Tier-2 section omits
# ---------------------------------------------------------------------------


def test_header_present_when_one_tier2_section_omits():
    """When at least one Tier-2 section omits (INSTITUTIONAL FLOW is
    plan-gated off here), DATA CONTEXT header MUST be present so the LLM
    knows the omission is intentional, not data missing."""
    from src.llm.packet_writer import _build_feature_prompt

    features = _base_features()
    # INSTITUTIONAL FLOW plan-gated off (the omission).
    features["_institutional_plan_supports"] = False
    # MATERIAL EVENTS present (filings_sentiment).
    features.update({
        "_filings_sentiment_plan_supports": True,
        "filing_sentiment_score": 0.42,
        "filing_sentiment_label": "positive",
        "latest_filing_type": "10-K",
        "latest_filing_age_days": 7,
    })
    # FUNDAMENTAL SNAPSHOT live-enrichment present.
    features.update({
        "fundamental_summary": "Revenue (TTM): $383.3B",
        "fundamental_pe": 28.5,
        "fundamental_debt_to_equity": 1.45,
        "fundamental_gross_margin": 0.452,
        "fundamental_roic": 0.215,
        "fundamental_quality_flag": "ok",
        "fundamental_snapshot_age_days": 1,
    })

    prompt = _build_feature_prompt(features, "AAPL")
    assert "=== DATA CONTEXT ===" in prompt, (
        "DATA CONTEXT header MUST be present when ≥1 Tier-2 section omits"
    )


# ---------------------------------------------------------------------------
# Test 3: Header content lists exact omitted section names
# ---------------------------------------------------------------------------


def test_header_lists_exact_omitted_section_names():
    """The DATA CONTEXT header MUST enumerate the exact omitted Tier-2
    section names so the LLM can interpret the absence (plan-gated)
    distinct from a transient data gap."""
    from src.llm.packet_writer import _build_feature_prompt

    features = _base_features()
    # Both INSTITUTIONAL FLOW and MATERIAL EVENTS omit; FUNDAMENTAL
    # SNAPSHOT live-enrichment present.
    features["_institutional_plan_supports"] = False
    features["_filings_sentiment_plan_supports"] = False
    features["_press_releases_plan_supports"] = False
    features.update({
        "fundamental_summary": "Revenue (TTM): $383.3B",
        "fundamental_pe": 28.5,
        "fundamental_debt_to_equity": 1.45,
        "fundamental_gross_margin": 0.452,
        "fundamental_roic": 0.215,
        "fundamental_quality_flag": "ok",
        "fundamental_snapshot_age_days": 1,
    })

    prompt = _build_feature_prompt(features, "AAPL")
    assert "=== DATA CONTEXT ===" in prompt
    # Header MUST mention INSTITUTIONAL FLOW and MATERIAL EVENTS as
    # omitted, since both are plan-gated off in this fixture.
    header_part = prompt.split("=== DATA CONTEXT ===", 1)[1].split("===", 1)[0]
    assert "INSTITUTIONAL FLOW" in header_part, (
        "DATA CONTEXT header MUST list INSTITUTIONAL FLOW as an omitted "
        "section when plan-gated off"
    )
    assert "MATERIAL EVENTS" in header_part, (
        "DATA CONTEXT header MUST list MATERIAL EVENTS as an omitted "
        "section when no sub-block has plan-support"
    )
    # Sanity: FUNDAMENTAL SNAPSHOT enrichment is present here so it
    # MUST NOT appear in the omitted list.
    assert "FUNDAMENTAL SNAPSHOT" not in header_part, (
        "FUNDAMENTAL SNAPSHOT live-enrichment is present in this fixture "
        "and MUST NOT appear in the omitted-sections list"
    )
