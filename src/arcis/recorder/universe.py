"""Universe management: build dated snapshots from the vendored CSVs and
validate them before every recording run.

The vendored lists live in config/sp500.csv and config/sp100.csv. The
`universe` command copies the configured one to
data_root/universe/<YYYY-MM-DD>.csv. Snapshots are immutable: writing a
snapshot that already exists with different content is an error.
"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from arcis.recorder.config import Config
from arcis.recorder.errors import UniverseError

HEADER = "symbol"


def read_symbols(csv_path: Path) -> list[str]:
    if not csv_path.is_file():
        raise UniverseError(f"universe CSV not found: {csv_path}")
    with csv_path.open(newline="") as f:
        rows = list(csv.reader(f))
    if not rows or rows[0] != [HEADER]:
        raise UniverseError(f"{csv_path}: expected a single '{HEADER}' header row")
    symbols = [r[0].strip() for r in rows[1:] if r and r[0].strip()]
    if not symbols:
        raise UniverseError(f"{csv_path}: no symbols")
    if len(set(symbols)) != len(symbols):
        raise UniverseError(f"{csv_path}: duplicate symbols")
    return symbols


def snapshot_path(config: Config, day: date) -> Path:
    return config.data_root / "universe" / f"{day.isoformat()}.csv"


def build_universe(config: Config, day: date, config_dir: Path) -> Path:
    """Write the dated snapshot from the vendored CSV. Refuses when the
    vendored symbols differ from config.symbols, or when a different
    snapshot already exists for the day (immutability)."""
    vendored = config_dir / f"{config.universe_name}.csv"
    vendored_symbols = read_symbols(vendored)
    if vendored_symbols != config.symbols:
        raise UniverseError(
            f"{vendored} symbols differ from config.symbols "
            f"({len(vendored_symbols)} vs {len(config.symbols)}); "
            "update the config or the vendored list, never silently"
        )
    target = snapshot_path(config, day)
    content = HEADER + "\n" + "".join(s + "\n" for s in vendored_symbols)
    if target.is_file():
        if target.read_text() != content:
            raise UniverseError(
                f"{target} already exists with different content; snapshots are immutable"
            )
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return target


def latest_snapshot(config: Config, day: date) -> Path | None:
    """Most recent snapshot on or before `day`. Returns None when no snapshot
    exists yet (fresh data root)."""
    universe_dir = config.data_root / "universe"
    if not universe_dir.is_dir():
        return None
    candidates = []
    for csv_path in universe_dir.glob("*.csv"):
        try:
            snap_day = date.fromisoformat(csv_path.stem)
        except ValueError:
            continue
        if snap_day <= day:
            candidates.append((snap_day, csv_path))
    if not candidates:
        return None
    return max(candidates)[1]


def validate_universe(config: Config, day: date) -> None:
    """Fail-closed check run before every recording run: a snapshot for `day`
    must exist (falling back to the latest available when today's snapshot
    hasn't been built yet — e.g. polls running between 00:00 UTC and the
    00:05 ET snapshot cron), and its symbols must equal config.symbols."""
    target = snapshot_path(config, day)
    if not target.is_file():
        fallback = latest_snapshot(config, day)
        if fallback is None:
            raise UniverseError(
                f"{target} is missing; run `arcis-recorder universe` first"
            )
        target = fallback
    if read_symbols(target) != config.symbols:
        raise UniverseError(
            f"{target} symbols differ from config.symbols; refusing to record"
        )
