"""Tests for configuration placeholder validation."""

from src.config import validate_config


class TestValidateConfig:
    def test_detects_placeholder_api_key(self):
        config = {"alpaca": {"api_key": "your-alpaca-api-key", "secret_key": "real-secret"}}
        warnings = validate_config(config)
        assert any("alpaca.api_key" in w for w in warnings)

    def test_detects_your_prefix_pattern(self):
        config = {"finnhub": {"api_key": "YOUR_FINNHUB_KEY"}}
        warnings = validate_config(config)
        assert len(warnings) >= 1

    def test_real_values_pass(self):
        config = {
            "alpaca": {"api_key": "PKAB1234567890", "secret_key": "abcdef1234567890"},
            "finnhub": {"api_key": "cs12345abcdef"},
        }
        warnings = validate_config(config)
        assert len(warnings) == 0

    def test_missing_keys_handled_gracefully(self):
        config = {}
        warnings = validate_config(config)
        assert isinstance(warnings, list)

    def test_empty_string_detected(self):
        config = {"alpaca": {"api_key": ""}}
        warnings = validate_config(config)
        assert any("alpaca.api_key" in w for w in warnings)
