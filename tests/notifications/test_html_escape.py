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


# Fix 2 — None-guard and str-coercion tests
def test_html_escape_none_returns_empty_string():
    """_html_escape(None) must return '' not raise AttributeError."""
    assert _html_escape(None) == ""


def test_html_escape_int_coerces_to_str():
    """_html_escape(123) must return '123' via str coercion."""
    assert _html_escape(123) == "123"


def test_html_escape_complex_entities_order():
    """Escaping order: & first, then < and >. Result must be idempotent on double-call."""
    raw = "<a>&</a>"
    expected = "&lt;a&gt;&amp;&lt;/a&gt;"
    assert _html_escape(raw) == expected
