"""Tests for Grafana Loki log handler.

Tests handler configuration, DedupFilter, and error paths.
No network calls — all tests are offline.
"""
import logging
import time

from src.observability.loki_handler import setup_loki_handler, DedupFilter


def test_handler_returns_none_when_disabled():
    """Config has enabled: false."""
    config = {"observability": {"grafana": {"enabled": False}}}
    assert setup_loki_handler(config) is None


def test_handler_returns_none_when_config_missing():
    """No observability section at all."""
    assert setup_loki_handler({}) is None


def test_handler_returns_none_when_token_missing(monkeypatch):
    """Config enabled but GRAFANA_LOKI_TOKEN env var not set."""
    monkeypatch.delenv("GRAFANA_LOKI_TOKEN", raising=False)
    config = {"observability": {"grafana": {
        "enabled": True, "loki_url": "http://fake", "loki_user": "123"
    }}}
    assert setup_loki_handler(config) is None


def test_dedup_filter_suppresses_duplicates():
    """Same message within window is filtered."""
    f = DedupFilter(window_seconds=60)
    record = logging.LogRecord("test", logging.INFO, "", 0, "hello", (), None)
    assert f.filter(record) is True
    assert f.filter(record) is False  # duplicate suppressed


def test_dedup_filter_allows_after_window():
    """Message allowed again after window expires."""
    f = DedupFilter(window_seconds=0.1)
    record = logging.LogRecord("test", logging.INFO, "", 0, "hello", (), None)
    assert f.filter(record) is True
    time.sleep(0.15)
    assert f.filter(record) is True  # window expired
