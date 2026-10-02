"""T4: universe snapshots are built from the vendored CSVs, immutable, and
validated before every recording run."""
from datetime import date
from pathlib import Path

import pytest

from arcis.recorder.config import Config
from arcis.recorder.errors import UniverseError
from arcis.recorder.universe import build_universe, read_symbols, validate_universe

DAY = date(2026, 10, 2)
SYMBOLS = ["AAPL", "MSFT", "NVDA"]


def make_config(tmp_path: Path, symbols: list[str] | None = None) -> Config:
    return Config(
        data_root=tmp_path / "data",
        alpaca_base_url="https://paper-api.alpaca.markets",
        alpaca_api_key="k",
        alpaca_api_secret="s",
        universe_name="sp500",
        universe_source="test",
        symbols=symbols if symbols is not None else list(SYMBOLS),
        rate_limit={"max_requests_per_minute": 200, "max_requests_per_day": 50000},
        retry={"max_attempts": 5, "base_delay_seconds": 1.0, "max_delay_seconds": 60.0},
    )


def make_vendored(tmp_path: Path, symbols: list[str]) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    p = config_dir / "sp500.csv"
    p.write_text("symbol\n" + "".join(s + "\n" for s in symbols))
    return config_dir


def test_build_universe_writes_dated_snapshot(tmp_path):
    config = make_config(tmp_path)
    config_dir = make_vendored(tmp_path, SYMBOLS)
    path = build_universe(config, DAY, config_dir)
    assert path == tmp_path / "data" / "universe" / "2026-10-02.csv"
    assert read_symbols(path) == SYMBOLS


def test_build_universe_is_idempotent(tmp_path):
    config = make_config(tmp_path)
    config_dir = make_vendored(tmp_path, SYMBOLS)
    first = build_universe(config, DAY, config_dir)
    second = build_universe(config, DAY, config_dir)
    assert first == second


def test_build_universe_refuses_vendored_mismatch(tmp_path):
    config = make_config(tmp_path, symbols=["AAPL", "MSFT"])
    config_dir = make_vendored(tmp_path, SYMBOLS)
    with pytest.raises(UniverseError, match="differ from config.symbols"):
        build_universe(config, DAY, config_dir)


def test_build_universe_refuses_to_mutate_snapshot(tmp_path):
    config = make_config(tmp_path)
    config_dir = make_vendored(tmp_path, SYMBOLS)
    target = tmp_path / "data" / "universe" / "2026-10-02.csv"
    target.parent.mkdir(parents=True)
    target.write_text("symbol\nAAPL\n")
    with pytest.raises(UniverseError, match="immutable"):
        build_universe(config, DAY, config_dir)


def test_validate_universe_ok(tmp_path):
    config = make_config(tmp_path)
    config_dir = make_vendored(tmp_path, SYMBOLS)
    build_universe(config, DAY, config_dir)
    validate_universe(config, DAY)  # no error


def test_validate_universe_missing_snapshot(tmp_path):
    config = make_config(tmp_path)
    with pytest.raises(UniverseError, match="missing"):
        validate_universe(config, DAY)


def test_validate_universe_symbol_mismatch(tmp_path):
    config = make_config(tmp_path)
    target = tmp_path / "data" / "universe" / "2026-10-02.csv"
    target.parent.mkdir(parents=True)
    target.write_text("symbol\nAAPL\nMSFT\n")
    with pytest.raises(UniverseError, match="differ from config.symbols"):
        validate_universe(config, DAY)


def test_read_symbols_rejects_bad_header(tmp_path):
    p = tmp_path / "u.csv"
    p.write_text("ticker\nAAPL\n")
    with pytest.raises(UniverseError, match="header"):
        read_symbols(p)


def test_read_symbols_rejects_duplicates(tmp_path):
    p = tmp_path / "u.csv"
    p.write_text("symbol\nAAPL\nAAPL\n")
    with pytest.raises(UniverseError, match="duplicate"):
        read_symbols(p)
