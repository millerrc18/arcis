"""T4: the `universe` subcommand builds the dated snapshot end to end."""
from pathlib import Path

import yaml

from arcis.recorder.cli import main


def write_full_config(tmp_path: Path) -> Path:
    """A config dir mirroring the repo layout, whose symbols match the real
    vendored sp500.csv."""
    import shutil

    repo = Path(__file__).resolve().parent.parent
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    shutil.copy(repo / "config" / "sp500.csv", config_dir / "sp500.csv")
    symbols = (config_dir / "sp500.csv").read_text().splitlines()[1:]
    doc = {
        "data_root": str(tmp_path / "data"),
        "alpaca_base_url": "https://paper-api.alpaca.markets",
        "universe_name": "sp500",
        "universe_source": "test",
        "symbols": symbols,
        "rate_limit": {"max_requests_per_minute": 200, "max_requests_per_day": 50000},
        "retry": {"max_attempts": 5, "base_delay_seconds": 1.0, "max_delay_seconds": 60.0},
    }
    p = config_dir / "recorder.yaml"
    p.write_text(yaml.safe_dump(doc))
    return p


def test_universe_command_builds_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_API_SECRET", "s")
    config = write_full_config(tmp_path)
    rc = main(["--config", str(config), "universe", "--date", "2026-10-02"])
    assert rc == 0
    snapshot = tmp_path / "data" / "universe" / "2026-10-02.csv"
    assert snapshot.is_file()
    assert len(snapshot.read_text().splitlines()) == 504  # header + 503


def test_universe_command_fails_cleanly_on_bad_config(tmp_path, capsys):
    rc = main(["--config", str(tmp_path / "missing.yaml"), "universe"])
    assert rc == 1
    assert "error:" in capsys.readouterr().err
