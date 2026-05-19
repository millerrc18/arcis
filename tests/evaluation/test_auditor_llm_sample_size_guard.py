"""Regression-lock for LLM-narrative sample-size guard in run_daily_audit (v0.36.27).

Pre-fix, the LLM auditor at `src/evaluation/auditor.py:121` was sent the
full CTO data regardless of sample size and asked to write a narrative
assessment. The LLM would then panic on tiny samples:

- 2026-05-18: "0% win rate vs 57% for base model, negative expectancy"
  off N=2 closes attributed to arcis:v1.0.0 (4-of-10 was the real
  picture)
- 2026-05-19: "100% of trades executed with scores below 70, all
  resulting in immediate stop losses, complete failure of the scoring/
  selection..." off N=3 closes where all 3 had recommendation_id=None
  (defaulted to score=0 in the band logic — not actually broken)

Both audits triggered Telegram CRITICAL alerts that wasted operator
attention. CLAUDE.md's strict-rigor discipline applies to AI-generated
commentary too — no critical claims on small samples.

Post-fix: when `trade_summary.trades_closed < _LLM_AUDIT_MIN_SAMPLE`
(currently 10), the LLM call is skipped and replaced with a deterministic
low-volume summary. Deterministic prechecks (`_append_deterministic_prechecks`)
still run — they have their own per-check sample guards from v0.36.22.
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


def _build_minimal_cto_data(trades_closed: int) -> dict:
    """Minimal cto_data shape sufficient to drive run_daily_audit."""
    return {
        "trade_summary": {
            "trades_closed": trades_closed,
            "trades_opened": trades_closed,
            "trades_open": 0,
            "win_rate": 0.5,
            "sharpe_ratio": 1.0,
            "max_drawdown_pct": 5.0,
            "max_drawdown_dollars": 100,
            "profit_factor": 1.5,
            "max_consecutive_losses": 2,
            "avg_winner_pct": 3.0,
            "avg_loser_pct": -2.0,
            "expectancy_dollars": 10,
        },
        "closed_trades": [{"ticker": f"T{i}", "pnl_dollars": 10} for i in range(trades_closed)],
        "by_model_version": {},
    }


@pytest.fixture
def patched_audit_deps():
    """Patch persistent storage + Claude client + init paths so run_daily_audit is hermetic."""
    with patch("src.evaluation.auditor.connect_db") as mock_connect, \
         patch("src.evaluation.auditor.init_training_tables"), \
         patch("src.evaluation.cto_report.generate_cto_report") as mock_cto, \
         patch("src.training.claude_client.generate_training_example") as mock_llm, \
         patch("src.evaluation.auditor._append_deterministic_prechecks") as mock_prechecks, \
         patch("src.risk.governor.get_portfolio_state", return_value={}):

        # connect_db is used as context manager; make conn.execute a no-op
        mock_conn = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_prechecks.return_value = None

        yield {
            "cto": mock_cto,
            "llm": mock_llm,
            "prechecks": mock_prechecks,
            "conn": mock_conn,
        }


def test_low_sample_skips_llm_narrative(patched_audit_deps):
    """trades_closed=3 → LLM is NOT called, deterministic prechecks still run."""
    from src.evaluation.auditor import run_daily_audit

    patched_audit_deps["cto"].return_value = _build_minimal_cto_data(trades_closed=3)

    result = run_daily_audit(db_path=":memory:")

    assert patched_audit_deps["llm"].call_count == 0, (
        "LLM auditor was called on N=3 sample. Should be skipped under "
        "_LLM_AUDIT_MIN_SAMPLE to avoid small-sample hallucinations like "
        "'100% of trades executed with scores below 70' off 3 closes."
    )
    # Deterministic prechecks still ran
    assert patched_audit_deps["prechecks"].call_count == 1, (
        "Deterministic prechecks must still run regardless of sample size — "
        "they have their own per-check sample guards (v0.36.22)."
    )
    # Result indicates low-sample suppression
    summary = (result.get("summary") or "").lower()
    assert "low" in summary or "sample" in summary or "small" in summary, (
        f"Expected the summary to mention low/small/sample, got: {result.get('summary')!r}"
    )


def test_zero_sample_skips_llm_narrative(patched_audit_deps):
    """trades_closed=0 → still safe, LLM not called, deterministic prechecks run."""
    from src.evaluation.auditor import run_daily_audit

    patched_audit_deps["cto"].return_value = _build_minimal_cto_data(trades_closed=0)

    result = run_daily_audit(db_path=":memory:")

    assert patched_audit_deps["llm"].call_count == 0
    assert patched_audit_deps["prechecks"].call_count == 1
    assert result.get("overall_assessment") in ("green", "yellow"), (
        f"Zero-sample audit should default to green/yellow, got "
        f"{result.get('overall_assessment')!r}"
    )


def test_sufficient_sample_invokes_llm_narrative(patched_audit_deps):
    """trades_closed >= threshold → LLM IS called (existing behavior preserved)."""
    from src.evaluation.auditor import run_daily_audit, _LLM_AUDIT_MIN_SAMPLE

    patched_audit_deps["cto"].return_value = _build_minimal_cto_data(
        trades_closed=_LLM_AUDIT_MIN_SAMPLE + 5,
    )
    # Make the LLM return a parseable response
    patched_audit_deps["llm"].return_value = (
        '{"overall_assessment": "green", "summary": "Healthy day", '
        '"flags": [], "metrics_to_watch": [], "model_health": "healthy"}'
    )

    result = run_daily_audit(db_path=":memory:")

    assert patched_audit_deps["llm"].call_count == 1, (
        f"LLM should be called when trades_closed >= {_LLM_AUDIT_MIN_SAMPLE}, "
        f"got call_count={patched_audit_deps['llm'].call_count}"
    )
    assert result.get("overall_assessment") == "green"


def test_exact_threshold_invokes_llm_narrative(patched_audit_deps):
    """trades_closed == threshold → LLM IS called (>= comparison)."""
    from src.evaluation.auditor import run_daily_audit, _LLM_AUDIT_MIN_SAMPLE

    patched_audit_deps["cto"].return_value = _build_minimal_cto_data(
        trades_closed=_LLM_AUDIT_MIN_SAMPLE,
    )
    patched_audit_deps["llm"].return_value = (
        '{"overall_assessment": "green", "summary": "OK", '
        '"flags": [], "metrics_to_watch": [], "model_health": "healthy"}'
    )

    run_daily_audit(db_path=":memory:")

    assert patched_audit_deps["llm"].call_count == 1, (
        f"At exactly trades_closed={_LLM_AUDIT_MIN_SAMPLE} the LLM should run (>=)"
    )


def test_one_below_threshold_skips_llm_narrative(patched_audit_deps):
    """trades_closed = threshold - 1 → LLM skipped."""
    from src.evaluation.auditor import run_daily_audit, _LLM_AUDIT_MIN_SAMPLE

    patched_audit_deps["cto"].return_value = _build_minimal_cto_data(
        trades_closed=_LLM_AUDIT_MIN_SAMPLE - 1,
    )

    run_daily_audit(db_path=":memory:")

    assert patched_audit_deps["llm"].call_count == 0
