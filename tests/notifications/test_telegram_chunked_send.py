"""Tests for chunked send in send_telegram (T13a / C15)."""

from unittest.mock import MagicMock, patch, call


def _make_cfg(enabled=True):
    return {
        "enabled": enabled,
        "bot_token": "123:ABC",
        "chat_id": "999",
    }


def _mock_response(status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = "ok"
    return resp


def test_long_message_splits_into_two_chunks():
    """5000-char body → 2 messages with [chunk 1/2] and [chunk 2/2] markers."""
    long_msg = "A" * 5000

    with patch("src.notifications.telegram._get_telegram_config", return_value=_make_cfg()):
        with patch("requests.post", return_value=_mock_response()) as mock_post:
            from src.notifications.telegram import send_telegram
            result = send_telegram(long_msg)

    assert result is True
    assert mock_post.call_count == 2

    first_call_text = mock_post.call_args_list[0][1]["json"]["text"]
    second_call_text = mock_post.call_args_list[1][1]["json"]["text"]

    assert "[chunk 1/2]" in first_call_text
    assert "[chunk 2/2]" in second_call_text


def test_short_message_no_chunking():
    """Message under 4000 chars → single message, no chunk markers."""
    short_msg = "B" * 100

    with patch("src.notifications.telegram._get_telegram_config", return_value=_make_cfg()):
        with patch("requests.post", return_value=_mock_response()) as mock_post:
            from src.notifications.telegram import send_telegram
            result = send_telegram(short_msg)

    assert result is True
    assert mock_post.call_count == 1

    sent_text = mock_post.call_args_list[0][1]["json"]["text"]
    assert "[chunk" not in sent_text


def test_message_exactly_at_limit_no_chunking():
    """Message at exactly 4000 chars → single message."""
    msg = "C" * 4000

    with patch("src.notifications.telegram._get_telegram_config", return_value=_make_cfg()):
        with patch("requests.post", return_value=_mock_response()) as mock_post:
            from src.notifications.telegram import send_telegram
            result = send_telegram(msg)

    assert result is True
    assert mock_post.call_count == 1


def test_chunked_send_returns_false_on_failure():
    """If any chunk fails to send, return False."""
    long_msg = "D" * 5000

    fail_resp = MagicMock()
    fail_resp.status_code = 400
    fail_resp.text = "bad request"

    with patch("src.notifications.telegram._get_telegram_config", return_value=_make_cfg()):
        with patch("requests.post", return_value=fail_resp):
            from src.notifications.telegram import send_telegram
            result = send_telegram(long_msg)

    assert result is False


# Fix 3 — plaintext fallback when HTML chunking returns 400
def test_chunked_send_html_400_falls_back_to_plaintext():
    """Fix 3: 5000-char HTML message where chunk-mode returns 400 → retries all chunks as plaintext."""
    # Body with an HTML tag that could straddle the boundary
    long_msg = "X" * 3990 + "<b>tag spans</b>" + "Y" * 1000

    ok_resp = _mock_response(200)
    fail_resp = _mock_response(400)

    # First HTML chunk → 400; plaintext retry → 200
    responses = [fail_resp, ok_resp, ok_resp]
    response_iter = iter(responses)

    def side_effect(*args, **kwargs):
        return next(response_iter)

    with patch("src.notifications.telegram._get_telegram_config", return_value=_make_cfg()):
        with patch("requests.post", side_effect=side_effect) as mock_post:
            from src.notifications.telegram import send_telegram
            result = send_telegram(long_msg)

    assert result is True
    # Should have tried HTML first (failed), then retried both chunks as plaintext
    assert mock_post.call_count == 3

    # First call was HTML (parse_mode="HTML")
    first_kwargs = mock_post.call_args_list[0][1]["json"]
    assert first_kwargs["parse_mode"] == "HTML"

    # Subsequent calls (plaintext retry) must have parse_mode=None or absent
    second_kwargs = mock_post.call_args_list[1][1]["json"]
    assert second_kwargs.get("parse_mode") is None

    third_kwargs = mock_post.call_args_list[2][1]["json"]
    assert third_kwargs.get("parse_mode") is None
