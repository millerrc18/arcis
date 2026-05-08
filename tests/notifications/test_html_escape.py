"""Tests for _html_escape helper in telegram.py (T13a / I6)."""

from src.notifications.telegram import _html_escape


def test_html_escape_ampersand():
    assert _html_escape("AT&T") == "AT&amp;T"


def test_html_escape_less_than():
    assert _html_escape("a<b") == "a&lt;b"


def test_html_escape_greater_than():
    assert _html_escape("a>b") == "a&gt;b"


def test_html_escape_no_special_chars():
    assert _html_escape("hello world") == "hello world"


def test_html_escape_multiple_entities():
    assert _html_escape("S&P 500 <index>") == "S&amp;P 500 &lt;index&gt;"


def test_html_escape_empty_string():
    assert _html_escape("") == ""
