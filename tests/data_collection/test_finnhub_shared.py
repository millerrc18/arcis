"""Tests for src/data_collection/_finnhub_shared.py.

Sprint 6 Wave A — WA1.

Three cases per spec:
  (a) FINNHUB_API_KEY env var takes precedence over YAML config.
  (b) YAML config fallback when env var is unset.
  (c) None returned when neither source provides a key.
"""

from unittest.mock import patch


def test_get_finnhub_key_env_takes_precedence(monkeypatch):
    """Env FINNHUB_API_KEY overrides the YAML config value."""
    monkeypatch.setenv("FINNHUB_API_KEY", "env-key-abc")
    config_with_key = {"data_enrichment": {"finnhub_api_key": "yaml-key-xyz"}}
    with patch("src.config.load_config", return_value=config_with_key):
        from src.data_collection._finnhub_shared import get_finnhub_key
        assert get_finnhub_key() == "env-key-abc"


def test_get_finnhub_key_yaml_fallback(monkeypatch):
    """When FINNHUB_API_KEY env var is absent, returns the YAML config value."""
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    config_with_key = {"data_enrichment": {"finnhub_api_key": "yaml-key-xyz"}}
    with patch("src.config.load_config", return_value=config_with_key):
        from importlib import reload
        import src.data_collection._finnhub_shared as m
        reload(m)
        assert m.get_finnhub_key() == "yaml-key-xyz"


def test_get_finnhub_key_returns_none_when_neither_set(monkeypatch):
    """Returns None when env var is absent and YAML config has no key."""
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    config_without_key = {"data_enrichment": {}}
    with patch("src.config.load_config", return_value=config_without_key):
        from importlib import reload
        import src.data_collection._finnhub_shared as m
        reload(m)
        assert m.get_finnhub_key() is None
