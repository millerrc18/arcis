"""T4: configuration loading, validation, and the data-root guard."""
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from arcis.recorder.config import Config, load_config
from arcis.recorder.errors import ConfigError

REPO = Path(__file__).resolve().parent.parent

GOOD_DOC = {
    "data_root": "/tmp/arcis-test-data",
    "alpaca_base_url": "https://paper-api.alpaca.markets",
    "universe_name": "sp500",
    "universe_source": "test",
    "symbols": ["AAPL", "MSFT"],
    "rate_limit": {"max_requests_per_minute": 200, "max_requests_per_day": 50000},
    "retry": {"max_attempts": 5, "base_delay_seconds": 1.0, "max_delay_seconds": 60.0},
}
ENV = {"ALPACA_API_KEY": "key", "ALPACA_API_SECRET": "secret"}


def write_config(tmp_path: Path, doc: dict) -> Path:
    p = tmp_path / "recorder.yaml"
    p.write_text(yaml.safe_dump(doc))
    return p


def test_rejects_extra_fields():
    doc = dict(GOOD_DOC, bogus_field=1)
    with pytest.raises(ValidationError):
        Config(**{**doc, "alpaca_api_key": "k", "alpaca_api_secret": "s"})


def test_rejects_missing_required_field():
    doc = {k: v for k, v in GOOD_DOC.items() if k != "symbols"}
    with pytest.raises(ValidationError):
        Config(**{**doc, "alpaca_api_key": "k", "alpaca_api_secret": "s"})


def test_rejects_bad_universe_name():
    doc = dict(GOOD_DOC, universe_name="russell3000")
    with pytest.raises(ValidationError):
        Config(**{**doc, "alpaca_api_key": "k", "alpaca_api_secret": "s"})


def test_load_config_ok(tmp_path):
    p = write_config(tmp_path, GOOD_DOC)
    config = load_config(p, ENV)
    assert config.symbols == ["AAPL", "MSFT"]
    assert config.universe_name == "sp500"


def test_load_config_missing_file(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.yaml", ENV)


def test_load_config_bad_yaml(tmp_path):
    p = tmp_path / "recorder.yaml"
    p.write_text("not: [valid\n")
    with pytest.raises(ConfigError):
        load_config(p, ENV)


def test_load_config_missing_secret(tmp_path):
    p = write_config(tmp_path, GOOD_DOC)
    with pytest.raises(ConfigError, match="ALPACA_API_KEY"):
        load_config(p, {"ALPACA_API_SECRET": "s"})


def test_load_config_incomplete_document(tmp_path):
    doc = {k: v for k, v in GOOD_DOC.items() if k != "data_root"}
    p = write_config(tmp_path, doc)
    with pytest.raises(ConfigError):
        load_config(p, ENV)


def test_guard_refuses_repo_data_root(tmp_path):
    doc = dict(GOOD_DOC, data_root=str(REPO / "data"))
    p = write_config(tmp_path, doc)
    with pytest.raises(ConfigError, match="inside the repo"):
        load_config(p, ENV)


def test_guard_refuses_cloud_sync(tmp_path):
    for synced in ("Dropbox", "Google Drive", "OneDrive", "iCloud Drive"):
        doc = dict(GOOD_DOC, data_root=f"/home/hatch/{synced}/arcis-data")
        p = write_config(tmp_path, doc)
        with pytest.raises(ConfigError, match="cloud-sync"):
            load_config(p, ENV)


def test_guard_accepts_clean_path(tmp_path):
    doc = dict(GOOD_DOC, data_root=str(tmp_path / "data"))
    p = write_config(tmp_path, doc)
    config = load_config(p, ENV)
    assert config.data_root == tmp_path / "data"
