"""Tests for T13c: normalize_earnings_time in src/data_ingestion/finnhub.py (I15)."""

import pytest
from src.data_ingestion.finnhub import normalize_earnings_time


@pytest.mark.parametrize("raw,expected", [
    ("Pre-market", "BMO"),
    ("pre-market", "BMO"),
    ("PRE", "BMO"),
    ("before market", "BMO"),
    ("before market open", "BMO"),
    ("BMO", "BMO"),
    ("bmo", "BMO"),
    ("After hours", "AMC"),
    ("after hours", "AMC"),
    ("AMC", "AMC"),
    ("amc", "AMC"),
    ("after market", "AMC"),
    ("After Market Close", "AMC"),
    (None, "TBD"),
    ("", "TBD"),
    ("unknown value", "TBD"),
    ("TBD", "TBD"),
])
def test_normalize_earnings_time(raw, expected):
    assert normalize_earnings_time(raw) == expected


def test_notify_position_earnings_warning_uses_bmo_for_pre_market():
    """I15: notify_position_earnings_warning renders BMO for Pre-market raw string."""
    from unittest.mock import patch, MagicMock

    resp = MagicMock()
    resp.status_code = 200
    resp.text = "ok"

    cfg = {"enabled": True, "bot_token": "123:ABC", "chat_id": "999"}
    with patch("src.notifications.telegram._get_telegram_config", return_value=cfg):
        with patch("requests.post", return_value=resp) as mock_post:
            from src.notifications.telegram import notify_position_earnings_warning
            notify_position_earnings_warning(
                ticker="AAPL",
                days_until=2,
                earnings_date="2026-05-10",
                earnings_time="Pre-market",
                current_pnl=120.5,
                current_pnl_pct=3.2,
            )

    sent_text = mock_post.call_args_list[0][1]["json"]["text"]
    assert "BMO" in sent_text
