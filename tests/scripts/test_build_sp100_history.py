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


def test_corporate_action_rename_reverse_applies():
    """A rename event walked backwards replaces the new ticker with the old."""
    from scripts import build_sp100_history
    current = ["AAPL", "BKNG", "MSFT"]
    changes = [
        {"date": "2018-02-27", "type": "rename", "from": "PCLN", "to": "BKNG"},
    ]
    table = build_sp100_history.build_history_table(current, changes)
    # At and after the rename date: BKNG should be present, PCLN absent
    assert "BKNG" in table["2018-02-27"]
    assert "PCLN" not in table["2018-02-27"]
    # Before the rename date: PCLN should be present, BKNG absent
    earliest = min(k for k in table if k < "2018-02-27")
    assert "PCLN" in table[earliest]
    assert "BKNG" not in table[earliest]


def test_corporate_action_merger_reverse_applies():
    """A merger event walked backwards replaces the merged ticker with both originals."""
    from scripts import build_sp100_history
    current = ["AAPL", "RTX", "MSFT"]
    changes = [
        {"date": "2020-04-03", "type": "merger", "from": ["UTX", "RTN"], "to": "RTX"},
    ]
    table = build_sp100_history.build_history_table(current, changes)
    # At/after the merger date: RTX present, UTX+RTN absent
    assert "RTX" in table["2020-04-03"]
    assert "UTX" not in table["2020-04-03"]
    assert "RTN" not in table["2020-04-03"]
    # Before the merger date: both originals present, RTX absent
    earliest = min(k for k in table if k < "2020-04-03")
    assert "UTX" in table[earliest]
    assert "RTN" in table[earliest]
    assert "RTX" not in table[earliest]


def test_corporate_action_removal_via_acquisition_reverse_applies():
    """A removal-via-acquisition walked backwards adds the delisted ticker back."""
    from scripts import build_sp100_history
    current = ["AAPL", "MSFT"]
    changes = [
        {"date": "2017-06-13", "type": "removal-via-acquisition", "from": "YHOO"},
    ]
    table = build_sp100_history.build_history_table(current, changes)
    # At/after removal: YHOO absent
    assert "YHOO" not in table["2017-06-13"]
    # Before removal: YHOO present (added back when walking backwards)
    earliest = min(k for k in table if k < "2017-06-13")
    assert "YHOO" in table[earliest]


def test_corporate_action_spinoff_reverse_applies():
    """A spinoff walked backwards replaces the children with the parent."""
    from scripts import build_sp100_history
    current = ["AAPL", "CHILD_A", "CHILD_B", "MSFT"]
    changes = [
        {"date": "2019-01-15", "type": "spinoff", "from": "PARENT", "to": ["CHILD_A", "CHILD_B"]},
    ]
    table = build_sp100_history.build_history_table(current, changes)
    # At/after spinoff: children present, parent absent
    assert "CHILD_A" in table["2019-01-15"]
    assert "CHILD_B" in table["2019-01-15"]
    assert "PARENT" not in table["2019-01-15"]
    # Before spinoff: parent present, children absent
    earliest = min(k for k in table if k < "2019-01-15")
    assert "PARENT" in table[earliest]
    assert "CHILD_A" not in table[earliest]
    assert "CHILD_B" not in table[earliest]


def test_corporate_action_unknown_type_raises():
    """Unknown event types must raise ValueError, not silently skip."""
    import pytest
    from scripts import build_sp100_history
    current = ["AAPL", "MSFT"]
    changes = [
        {"date": "2020-01-01", "type": "fictional_event_type", "foo": "bar"},
    ]
    with pytest.raises(ValueError, match="Unknown event type"):
        build_sp100_history.build_history_table(current, changes)


def test_validator_size_gate_skips_spot_checks_on_synthetic():
    """Synthetic fixtures (today's snapshot < 50 tickers) bypass historical spot-checks."""
    from scripts import build_sp100_history
    table = {
        "2015-03-19": ["AAPL", "MSFT", "GOOG"],
        "2026-04-28": ["AAPL", "MSFT", "GOOG"],
    }
    violations = build_sp100_history._validate_table(table)
    # Synthetic 3-ticker fixture cannot satisfy historical spot-checks (BKNG, RTX, etc.
    # aren't in this universe), but the size-gate must skip them entirely.
    assert violations == [], f"Expected no violations on synthetic fixture, got: {violations}"


def test_validator_size_gate_runs_spot_checks_on_production():
    """Production-scale fixtures (today's snapshot >= 50) trigger spot-checks."""
    from scripts import build_sp100_history
    # Build a 60-ticker fake "today" snapshot that does NOT include the spot-checked
    # historical tickers, ensuring the validator surfaces violations.
    today_tickers = sorted(f"FAKE{i:03d}" for i in range(60))
    table = {
        "2015-03-19": list(today_tickers),
        "2026-04-28": list(today_tickers),
    }
    violations = build_sp100_history._validate_table(table)
    # At minimum, we expect violations for PCLN/KRFT/UTX/RTN/EMC/YHOO/RTX/BKNG/KHC checks.
    assert len(violations) > 0, "Expected production-scale fixture to surface spot-check violations"
    # Sanity check: at least one violation mentions a known spot-check ticker
    joined = " ".join(violations)
    assert any(t in joined for t in ["PCLN", "BKNG", "RTX", "EMC", "YHOO", "KRFT", "KHC"]), \
        f"Expected at least one spot-check ticker in violations: {violations}"


def test_validator_catches_missing_historical_ticker():
    """A regression that loses PCLN from a 2015 snapshot must surface as a violation."""
    from scripts import build_sp100_history
    # Build a production-scale snapshot deliberately missing PCLN at 2015-03-19
    today_tickers = ["AAPL", "MSFT", "BKNG"] + [f"FAKE{i:03d}" for i in range(57)]
    snapshot_2015 = sorted(today_tickers)  # has BKNG instead of PCLN — the bug pattern from PR #802 review
    table = {
        "2015-03-19": snapshot_2015,
        "2026-04-28": sorted(today_tickers),
    }
    violations = build_sp100_history._validate_table(table)
    assert any("PCLN" in v for v in violations), \
        f"Expected violation flagging missing PCLN at 2015-03-19, got: {violations}"
