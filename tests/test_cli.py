"""T4: the `universe` subcommand builds the dated snapshot end to end."""
from pathlib import Path

import yaml

import arcis.recorder.cli as cli_module
from arcis.recorder.cli import main
from arcis.recorder.errors import RecorderError


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
        "alpaca_base_url": "https://data.alpaca.markets",
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


def test_poll_command(tmp_path, monkeypatch, capsys):
    config = write_full_config(tmp_path)
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_API_SECRET", "s")
    monkeypatch.setattr(cli_module, "poll_run", lambda c: {"pairs_stored": 5})
    rc = main(["--config", str(config), "poll"])
    assert rc == 0
    assert "pairs_stored" in capsys.readouterr().out


def test_sweep_command(tmp_path, monkeypatch, capsys):
    config = write_full_config(tmp_path)
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_API_SECRET", "s")
    monkeypatch.setattr(cli_module, "sweep_run", lambda c, s, e: {"pairs_stored": 3})
    rc = main(["--config", str(config), "sweep", "--start", "2026-09-28", "--end", "2026-09-29"])
    assert rc == 0
    assert "pairs_stored" in capsys.readouterr().out


def test_gaps_command_no_missing_days(tmp_path, monkeypatch, capsys):
    config = write_full_config(tmp_path)
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_API_SECRET", "s")
    report = {"last_poll_at": "2026-10-02T12:00:00+00:00", "missing_days": [], "days": {}}
    monkeypatch.setattr(cli_module, "gaps_run", lambda root, days: report)
    rc = main(["--config", str(config), "gaps"])
    assert rc == 0


def test_gaps_command_with_missing_days(tmp_path, monkeypatch):
    config = write_full_config(tmp_path)
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_API_SECRET", "s")
    report = {"last_poll_at": None, "missing_days": ["2026-10-01"], "days": {}}
    monkeypatch.setattr(cli_module, "gaps_run", lambda root, days: report)
    rc = main(["--config", str(config), "gaps"])
    assert rc == 1


def test_recorder_error_exits_nonzero(tmp_path, monkeypatch, capsys):
    config = write_full_config(tmp_path)
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_API_SECRET", "s")

    def boom(c):
        raise RecorderError("boom")

    monkeypatch.setattr(cli_module, "poll_run", boom)
    rc = main(["--config", str(config), "poll"])
    assert rc == 1
    assert "error: boom" in capsys.readouterr().err
