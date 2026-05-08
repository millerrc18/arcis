"""Tests for T13b notify_* updates in telegram.py."""

from unittest.mock import MagicMock, patch
import pytest


def _make_cfg(enabled=True):
    return {
        "enabled": enabled,
        "bot_token": "123:ABC",
        "chat_id": "999",
    }


def _mock_ok():
    resp = MagicMock()
    resp.status_code = 200
    resp.text = "ok"
    return resp


# ── C16: notify_research_digest truncates summary with marker ─────────────

def test_research_digest_truncates_long_summary():
    """C16: long digest_summary truncated with [truncated; see email digest]."""
    long_summary = "X" * 1000

    with patch("src.notifications.telegram._get_telegram_config", return_value=_make_cfg()):
        with patch("requests.post", return_value=_mock_ok()) as mock_post:
            from src.notifications.telegram import notify_research_digest
            notify_research_digest(10, 3, long_summary)

    sent_text = mock_post.call_args_list[0][1]["json"]["text"]
    assert "[truncated; see email digest]" in sent_text


def test_research_digest_short_summary_no_truncation_marker():
    """C16: short summary is not truncated."""
    short_summary = "Short summary."

    with patch("src.notifications.telegram._get_telegram_config", return_value=_make_cfg()):
        with patch("requests.post", return_value=_mock_ok()) as mock_post:
            from src.notifications.telegram import notify_research_digest
            notify_research_digest(5, 1, short_summary)

    sent_text = mock_post.call_args_list[0][1]["json"]["text"]
    assert "[truncated; see email digest]" not in sent_text
    assert short_summary in sent_text


# ── C7: notify_overnight_complete dict-with-success pattern ───────────────

def test_overnight_complete_dict_with_success_false_renders_error():
    """C7: dict val with success=False renders ❌, not ✅."""
    results = {
        "data_collect": {"success": False, "error": "connection timeout"},
    }

    with patch("src.notifications.telegram._get_telegram_config", return_value=_make_cfg()):
        with patch("requests.post", return_value=_mock_ok()) as mock_post:
            from src.notifications.telegram import notify_overnight_complete
            notify_overnight_complete(results)

    sent_text = mock_post.call_args_list[0][1]["json"]["text"]
    assert "❌" in sent_text
    assert "✅" not in sent_text


def test_overnight_complete_dict_with_success_true_renders_ok():
    """C7: dict val with success=True renders ✅."""
    results = {
        "data_collect": {"success": True},
    }

    with patch("src.notifications.telegram._get_telegram_config", return_value=_make_cfg()):
        with patch("requests.post", return_value=_mock_ok()) as mock_post:
            from src.notifications.telegram import notify_overnight_complete
            notify_overnight_complete(results)

    sent_text = mock_post.call_args_list[0][1]["json"]["text"]
    assert "✅" in sent_text


# ── I11: notify_action_required raises ValueError on unknown urgency ──────

def test_action_required_unknown_urgency_raises():
    """I11: unknown urgency level raises ValueError."""
    from src.notifications.telegram import notify_action_required
    with pytest.raises(ValueError, match="urgency"):
        notify_action_required("do something", "detail", urgency="extreme")


def test_action_required_known_urgency_does_not_raise():
    """I11: known urgency levels do not raise."""
    with patch("src.notifications.telegram._get_telegram_config", return_value=_make_cfg()):
        with patch("requests.post", return_value=_mock_ok()):
            from src.notifications.telegram import notify_action_required
            for urgency in ("low", "normal", "high", "critical"):
                notify_action_required("action", "detail", urgency=urgency)


# ── I16: _html_escape used in notify_premarket_brief and notify_weekly_digest

def test_premarket_brief_no_raw_amp():
    """I16: &amp; not hardcoded; output identical via _html_escape."""
    with patch("src.notifications.telegram._get_telegram_config", return_value=_make_cfg()):
        with patch("requests.post", return_value=_mock_ok()) as mock_post:
            from src.notifications.telegram import notify_premarket_brief
            notify_premarket_brief(
                vix=18.5, vix_change=-0.3, regime="bull",
                spy_futures_pct=0.25, ten_year=4.2,
                earnings_today=["AAPL"], fomc_days=5, nfp_days=None,
                council_consensus="long", council_confidence=72,
                open_paper=3, open_live=1,
            )

    sent_text = mock_post.call_args_list[0][1]["json"]["text"]
    assert "S&amp;P" in sent_text
    assert "S&P" not in sent_text.replace("S&amp;P", "")


def test_weekly_digest_no_raw_amp():
    """I16: &amp; not hardcoded in weekly_digest; output identical via _html_escape."""
    with patch("src.notifications.telegram._get_telegram_config", return_value=_make_cfg()):
        with patch("requests.post", return_value=_mock_ok()) as mock_post:
            from src.notifications.telegram import notify_weekly_digest, WeeklyDigestPayload
            notify_weekly_digest(WeeklyDigestPayload(
                period_start="2026-05-01", period_end="2026-05-07",
                opened_paper=5, opened_live=2,
                closed_paper=3, closed_live=1,
                win_rate=0.6, expectancy=1.5,
                best_ticker="AAPL", best_pct=3.0,
                worst_ticker="META", worst_pct=-1.5,
                pnl_paper=250.0, pnl_live=80.0,
                training_start=4000, training_end=4200,
                signal_start=900, signal_end=950,
                scoring_backlog=10, quality_avg=4.2,
                canary_status="STABLE", llm_success_rate=0.92,
                regime="bull", vix=16.0, vix_range_low=14.0, vix_range_high=20.0,
                spy_weekly_pct=1.2,
                council_sessions=5, council_consensus="long", council_avg_confidence=75,
                earnings_next_week=["MSFT"], events_next_week=["FOMC"],
            ))

    sent_text = mock_post.call_args_list[0][1]["json"]["text"]
    assert "P&amp;L" in sent_text
