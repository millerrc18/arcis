"""Tests for HTML-escape coverage in notify_risk_alert and notify_exposure_alert.

Sprint 5 Wave B T5 — extends _html_escape coverage to the two remaining
functions that concatenate external-source strings into Telegram HTML-mode
payloads without sanitization.
"""
from unittest.mock import patch, MagicMock


def _make_post_mock():
    """Return a mock for requests.post that captures the payload."""
    m = MagicMock()
    m.return_value.raise_for_status.return_value = None
    return m


# ── notify_risk_alert ────────────────────────────────────────────────────────


def test_notify_risk_alert_escapes_ticker_with_special_chars():
    """alert_type containing HTML-special chars must be escaped in the payload."""
    from src.notifications.telegram import notify_risk_alert

    post_mock = _make_post_mock()
    with patch("src.notifications.telegram._get_telegram_config",
               return_value={"enabled": True, "bot_token": "t", "chat_id": "1"}), \
         patch("src.notifications.telegram.requests.post", post_mock):
        notify_risk_alert("<RISKY>", "some detail")

    call_kwargs = post_mock.call_args
    payload_text = call_kwargs[1]["json"]["text"]
    assert "&lt;RISKY&gt;" in payload_text
    assert "<RISKY>" not in payload_text


def test_notify_risk_alert_clean_input_round_trips():
    """Normal alert_type/detail strings must not be double-escaped."""
    from src.notifications.telegram import notify_risk_alert

    post_mock = _make_post_mock()
    with patch("src.notifications.telegram._get_telegram_config",
               return_value={"enabled": True, "bot_token": "t", "chat_id": "1"}), \
         patch("src.notifications.telegram.requests.post", post_mock):
        notify_risk_alert("AAPL", "position exceeds limit")

    call_kwargs = post_mock.call_args
    payload_text = call_kwargs[1]["json"]["text"]
    assert "AAPL" in payload_text
    assert "position exceeds limit" in payload_text
    # No spurious amp-escaping of clean strings
    assert "&amp;" not in payload_text


# ── notify_exposure_alert ────────────────────────────────────────────────────


def test_notify_exposure_alert_escapes_position_detail_with_html():
    """sector and tickers containing HTML-special chars must be escaped."""
    from src.notifications.telegram import notify_exposure_alert

    post_mock = _make_post_mock()
    with patch("src.notifications.telegram._get_telegram_config",
               return_value={"enabled": True, "bot_token": "t", "chat_id": "1"}), \
         patch("src.notifications.telegram.requests.post", post_mock):
        notify_exposure_alert(
            sector="Tech & AI",
            count=3,
            tickers=["<NVDA>", "AAPL", "MSFT"],
            exposure_pct=35.0,
            limit_pct=25.0,
        )

    call_kwargs = post_mock.call_args
    payload_text = call_kwargs[1]["json"]["text"]
    # sector must be escaped in both positions (header and recommendation)
    assert "Tech &amp; AI" in payload_text
    assert "Tech & AI" not in payload_text
    # ticker with angle brackets must be escaped
    assert "&lt;NVDA&gt;" in payload_text
    assert "<NVDA>" not in payload_text


def test_notify_exposure_alert_clean_input_round_trips():
    """Normal sector/ticker strings must pass through unchanged (no double-escape)."""
    from src.notifications.telegram import notify_exposure_alert

    post_mock = _make_post_mock()
    with patch("src.notifications.telegram._get_telegram_config",
               return_value={"enabled": True, "bot_token": "t", "chat_id": "1"}), \
         patch("src.notifications.telegram.requests.post", post_mock):
        notify_exposure_alert(
            sector="Technology",
            count=2,
            tickers=["AAPL", "MSFT"],
            exposure_pct=30.0,
            limit_pct=25.0,
        )

    call_kwargs = post_mock.call_args
    payload_text = call_kwargs[1]["json"]["text"]
    assert "Technology" in payload_text
    assert "AAPL" in payload_text
    assert "MSFT" in payload_text
    # No spurious escaping
    assert "&amp;" not in payload_text
