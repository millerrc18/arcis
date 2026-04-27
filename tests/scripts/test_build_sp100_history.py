"""Hermetic tests for scripts/build_sp100_history.py.

All tests monkeypatch fetch_wikipedia_html — no real HTTP calls.
"""
from __future__ import annotations

import json
import re
import sys

import pytest


CONSTITUENTS_HTML = """
<html><body>
<table class="wikitable">
<tr><th>Symbol</th><th>Name</th><th>Sector</th></tr>
<tr><td>MSFT</td><td>Microsoft</td><td>Technology</td></tr>
<tr><td>AAPL</td><td>Apple</td><td>Technology</td></tr>
<tr><td>GOOG</td><td>Alphabet</td><td>Technology</td></tr>
</table>
</body></html>
"""

CHANGE_HISTORY_HTML = """
<html><body>
<table class="wikitable">
<tr><th>Date</th><th>Added</th><th>Removed</th></tr>
<tr><td>March 20, 2023</td><td>NVDA</td><td>WBA</td></tr>
<tr><td>June 18, 2022</td><td>DXCM</td><td>EMRG</td></tr>
</table>
</body></html>
"""

FOOTNOTE_HTML = """
<html><body>
<table class="wikitable">
<tr><th>Date</th><th>Added</th><th>Removed</th></tr>
<tr><td>July 1, 2024[3]</td><td>SMCI</td><td>KHC</td></tr>
</table>
</body></html>
"""

DUPLICATE_HTML = """
<html><body>
<table class="wikitable">
<tr><th>Date</th><th>Added</th><th>Removed</th></tr>
<tr><td>March 20, 2023</td><td>NVDA</td><td>WBA</td></tr>
<tr><td>March 20, 2023</td><td>NVDA</td><td>WBA</td></tr>
</table>
</body></html>
"""

MAIN_HTML = CONSTITUENTS_HTML


def test_parse_current_constituents_returns_sorted_list():
    from scripts import build_sp100_history
    result = build_sp100_history.parse_current_constituents(CONSTITUENTS_HTML)
    assert result == ["AAPL", "GOOG", "MSFT"]


def test_parse_change_history_returns_records():
    from scripts import build_sp100_history
    result = build_sp100_history.parse_change_history(CHANGE_HISTORY_HTML)
    assert len(result) == 2
    for record in result:
        assert set(record.keys()) == {"date", "added", "removed"}
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", record["date"])


def test_parse_change_history_strips_footnote_refs():
    from scripts import build_sp100_history
    result = build_sp100_history.parse_change_history(FOOTNOTE_HTML)
    assert len(result) == 1
    assert result[0]["date"] == "2024-07-01"


def test_parse_change_history_dedupes_duplicate_events():
    from scripts import build_sp100_history
    result = build_sp100_history.parse_change_history(DUPLICATE_HTML)
    assert len(result) == 1


def test_build_history_table_reconstructs_snapshots():
    from scripts import build_sp100_history
    current = ["AAPL", "MSFT", "NVDA"]
    changes = [{"date": "2024-07-01", "added": "NVDA", "removed": "GOOG"}]
    table = build_sp100_history.build_history_table(current, changes)
    assert len(table) >= 2
    change_date_snapshot = table["2024-07-01"]
    assert "NVDA" in change_date_snapshot
    assert "GOOG" not in change_date_snapshot
    prior_key = min(k for k in table if k < "2024-07-01")
    prior_snapshot = table[prior_key]
    assert "GOOG" in prior_snapshot
    assert "NVDA" not in prior_snapshot


def test_build_history_table_invariants():
    from scripts import build_sp100_history
    current = ["AAPL", "MSFT", "NVDA"]
    changes = [{"date": "2024-07-01", "added": "NVDA", "removed": "GOOG"}]
    table = build_sp100_history.build_history_table(current, changes)
    for key, value in table.items():
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", key), f"Key {key!r} not ISO date"
        assert isinstance(value, list), f"Value for {key} is not a list"
        assert value == sorted(value), f"Value for {key} is not sorted"
        assert len(value) > 0, f"Value for {key} is empty"
        assert len(value) <= 110, f"Value for {key} has {len(value)} tickers (>110)"


def test_main_writes_byte_identical_output_when_run_twice(tmp_path, monkeypatch):
    from scripts import build_sp100_history
    monkeypatch.setattr(
        "scripts.build_sp100_history.fetch_wikipedia_html",
        lambda url: MAIN_HTML,
    )
    out1 = tmp_path / "out1.json"
    out2 = tmp_path / "out2.json"
    rc1 = build_sp100_history.main(["--output", str(out1)])
    rc2 = build_sp100_history.main(["--output", str(out2)])
    assert rc1 == 0
    assert rc2 == 0
    assert out1.read_bytes() == out2.read_bytes()


def test_main_dry_run_does_not_write_file(tmp_path, monkeypatch):
    from scripts import build_sp100_history
    monkeypatch.setattr(
        "scripts.build_sp100_history.fetch_wikipedia_html",
        lambda url: MAIN_HTML,
    )
    out = tmp_path / "dry_run_output.json"
    rc = build_sp100_history.main(["--output", str(out), "--dry-run"])
    assert rc == 0
    assert not out.exists()


def test_json_format_invariants(tmp_path, monkeypatch):
    from scripts import build_sp100_history
    monkeypatch.setattr(
        "scripts.build_sp100_history.fetch_wikipedia_html",
        lambda url: MAIN_HTML,
    )
    out = tmp_path / "output.json"
    rc = build_sp100_history.main(["--output", str(out)])
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    keys = list(data.keys())
    assert keys == sorted(keys)
    for key, value in data.items():
        assert isinstance(value, list)
        assert value == sorted(value)
