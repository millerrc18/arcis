# Purpose: Integration tests for src/tools/testpatternscan — AST-based test anti-pattern detector.
# Called by: pytest
# Calls: src.tools.testpatternscan.scan, src.tools.testpatternscan.Finding
# Owns tables: none
# Config keys: none
# Tests: this file
"""Integration tests for the TestPatternScan tool (src/tools/testpatternscan/).

13 cases per the Task 7 TEST_STRATEGY:
  (a) VACUOUS POSITIVE — @patch with no assertion → 1 finding.
  (b) VACUOUS NEGATIVE — @patch with .assert_called_once() → 0 findings.
  (c) PATCH-DRIFT POSITIVE — real module + fake symbol → 1 finding.
  (d) PATCH-DRIFT NEGATIVE — real module + real symbol → 0 findings.
  (e) MOCK-ONLY POSITIVE (opt-in) → 1 finding.
  (f) MOCK-ONLY OFF BY DEFAULT → 0 findings.
  (g) SIDE-EFFECT-UNREACHED POSITIVE (opt-in) → 1 finding.
  (h) SIDE-EFFECT-UNREACHED OFF BY DEFAULT → 0 findings.
  (i) UNKNOWN KIND → TestPatternScanError raised.
  (j) SYNTAX ERROR IN TARGET FILE → skip with WARNING + continue.
  (k) CLI SUBPROCESS error envelope + exit 1 on unknown kind.
  (l) CLI SUBPROCESS JSON list + exit 0 on valid scan.
  (m) DA4 SIDE-EFFECT SAFETY — poison-trap on load_dotenv/sqlite3/psycopg2.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def vacuous_test_file(tmp_path):
    """Test file with a truly vacuous test (Mock setup, no assertions)."""
    f = tmp_path / "test_vacuous.py"
    f.write_text(
        """
from unittest.mock import patch

@patch('foo.bar')
def test_vacuous_example(mock_bar):
    mock_bar.return_value = 42
    result = some_sut()
""",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture()
def non_vacuous_test_file(tmp_path):
    """Test file with a test that has a proper assertion."""
    f = tmp_path / "test_non_vacuous.py"
    f.write_text(
        """
from unittest.mock import patch

@patch('foo.bar')
def test_non_vacuous_example(mock_bar):
    mock_bar.return_value = 42
    result = some_sut()
    mock_bar.assert_called_once()
""",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture()
def patch_drift_positive_file(tmp_path):
    """Test file patching a real module with a nonexistent symbol."""
    f = tmp_path / "test_patch_drift.py"
    f.write_text(
        """
from unittest.mock import patch

@patch('src.tools._safety.gone_symbol_xyz')
def test_something(mock_sym):
    pass
""",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture()
def patch_drift_negative_file(tmp_path):
    """Test file patching a real module with a real symbol."""
    f = tmp_path / "test_no_drift.py"
    f.write_text(
        """
from unittest.mock import patch

@patch('src.tools._safety.safe_op')
def test_something(mock_safe_op):
    mock_safe_op.assert_called_once()
""",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture()
def mock_only_test_file(tmp_path):
    """Test that only checks mock interactions, never SUT return values."""
    f = tmp_path / "test_mock_only.py"
    f.write_text(
        """
from unittest.mock import patch, MagicMock

@patch('some.module.dependency')
def test_mock_only_example(mock_dep):
    mock_dep.return_value = 99
    some_sut()
    mock_dep.assert_called_with('arg1')
    assert mock_dep.call_count == 1
""",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture()
def side_effect_unreached_file(tmp_path):
    """Test that sets mock.side_effect but the test takes return_value branch."""
    f = tmp_path / "test_side_effect_unreached.py"
    f.write_text(
        """
from unittest.mock import patch, MagicMock

def test_side_effect_not_reached():
    mock = MagicMock()
    mock.side_effect = Exception('should never be raised')
    mock.return_value = 42
    result = mock()
    assert result == 42
""",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture()
def syntax_error_file(tmp_path):
    """A directory with one valid file and one syntactically invalid file."""
    valid = tmp_path / "test_valid.py"
    valid.write_text(
        """
def test_simple():
    assert 1 + 1 == 2
""",
        encoding="utf-8",
    )
    broken = tmp_path / "test_broken.py"
    broken.write_text("def test_broken(\n    this is not valid python syntax\n", encoding="utf-8")
    return tmp_path


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_vacuous_positive(vacuous_test_file):
    """(a) @patch with no assertion → 1 vacuous finding."""
    from src.tools.testpatternscan import scan

    results = scan(path=vacuous_test_file)
    vacuous = [f for f in results if f.rule == "vacuous"]
    assert len(vacuous) == 1, f"Expected 1 vacuous finding, got {vacuous}"
    assert vacuous[0].function == "test_vacuous_example"
    assert vacuous[0].confidence == "high"


def test_vacuous_negative(non_vacuous_test_file):
    """(b) @patch with .assert_called_once() → 0 vacuous findings."""
    from src.tools.testpatternscan import scan

    results = scan(path=non_vacuous_test_file)
    vacuous = [f for f in results if f.rule == "vacuous"]
    assert len(vacuous) == 0, f"Expected 0 vacuous findings, got {vacuous}"


def test_patch_drift_positive(patch_drift_positive_file):
    """(c) @patch('src.tools._safety.gone_symbol_xyz') → 1 patch_drift finding."""
    from src.tools.testpatternscan import scan

    results = scan(path=patch_drift_positive_file, kinds=["patch_drift"])
    drift = [f for f in results if f.rule == "patch_drift"]
    assert len(drift) == 1, f"Expected 1 patch_drift finding, got {drift}"
    assert "gone_symbol_xyz" in drift[0].detail


def test_patch_drift_negative(patch_drift_negative_file):
    """(d) @patch('src.tools._safety.safe_op') → 0 patch_drift findings."""
    from src.tools.testpatternscan import scan

    results = scan(path=patch_drift_negative_file, kinds=["patch_drift"])
    drift = [f for f in results if f.rule == "patch_drift"]
    assert len(drift) == 0, f"Expected 0 patch_drift findings, got {drift}"


def test_mock_only_positive(mock_only_test_file):
    """(e) mock_only opt-in: test only checking mock interactions → 1 mock_only finding."""
    from src.tools.testpatternscan import scan

    results = scan(path=mock_only_test_file, kinds=["mock_only"])
    mock_only = [f for f in results if f.rule == "mock_only"]
    assert len(mock_only) == 1, f"Expected 1 mock_only finding, got {mock_only}"


def test_mock_only_off_by_default(mock_only_test_file):
    """(f) mock_only NOT in default kinds → 0 findings from default scan."""
    from src.tools.testpatternscan import scan

    results = scan(path=mock_only_test_file)
    mock_only = [f for f in results if f.rule == "mock_only"]
    assert len(mock_only) == 0, f"Expected 0 mock_only from default scan, got {mock_only}"


def test_side_effect_unreached_positive(side_effect_unreached_file):
    """(g) side_effect_unreached opt-in: side_effect set but not triggered → 1 finding."""
    from src.tools.testpatternscan import scan

    results = scan(path=side_effect_unreached_file, kinds=["side_effect_unreached"])
    unreached = [f for f in results if f.rule == "side_effect_unreached"]
    assert len(unreached) == 1, f"Expected 1 side_effect_unreached finding, got {unreached}"


def test_side_effect_unreached_off_by_default(side_effect_unreached_file):
    """(h) side_effect_unreached NOT in default kinds → 0 findings."""
    from src.tools.testpatternscan import scan

    results = scan(path=side_effect_unreached_file)
    unreached = [f for f in results if f.rule == "side_effect_unreached"]
    assert len(unreached) == 0, f"Expected 0 side_effect_unreached from default, got {unreached}"


def test_unknown_kind_raises(tmp_path):
    """(i) Unknown rule kind → TestPatternScanError raised."""
    from src.tools.testpatternscan import TestPatternScanError, scan

    with pytest.raises(TestPatternScanError, match="unknown rule kind"):
        scan(path=tmp_path, kinds=["nonexistent_rule"])


def test_syntax_error_skipped_with_warning(syntax_error_file, caplog):
    """(j) Malformed Python file skipped with WARNING; valid file findings still returned."""
    import logging

    from src.tools.testpatternscan import scan

    with caplog.at_level(logging.WARNING):
        results = scan(path=syntax_error_file)

    # The valid file (test_simple, no mock setup) won't produce vacuous findings,
    # but the scan must not raise — it must have logged a warning about test_broken.py
    warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("test_broken" in r.message for r in warning_records), (
        f"Expected a WARNING about test_broken.py. Got: {[r.message for r in warning_records]}"
    )


def test_cli_unknown_kind_json_exit1(tmp_path):
    """(k) CLI with unknown kind + --json → error envelope + exit 1."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.tools.testpatternscan",
            "--path",
            str(tmp_path),
            "--kinds",
            "nonexistent",
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1, f"Expected exit 1, got {result.returncode}. stdout={result.stdout}"
    envelope = json.loads(result.stdout)
    assert "error" in envelope
    assert envelope["error"]["tool"] == "testpatternscan"


def test_cli_valid_scan_json_exit0(tmp_path):
    """(l) CLI with valid path + --json → JSON list of findings + exit 0."""
    test_file = tmp_path / "test_sample.py"
    test_file.write_text(
        """
from unittest.mock import patch

@patch('foo.bar')
def test_something(mock_bar):
    mock_bar.return_value = 1
    some_call()
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.tools.testpatternscan",
            "--path",
            str(tmp_path),
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"Expected exit 0, got {result.returncode}. stdout={result.stdout} stderr={result.stderr}"
    )
    findings = json.loads(result.stdout)
    assert isinstance(findings, list)


def test_scan_does_not_trigger_module_imports_da4(tmp_path, monkeypatch, caplog):
    """(m) DA4 SIDE-EFFECT SAFETY: scan must NOT import any module it patches.

    Verifies PatchDriftRule uses importlib.util.find_spec + ast.parse ONLY.
    Poison-traps on load_dotenv, sqlite3.connect, psycopg2.connect ensure
    that if the scanner accidentally imports src.api.app (or any module that
    triggers these), the test fails immediately.
    """
    # Poison-trap 1: load_dotenv must NOT be called
    monkeypatch.setattr(
        "dotenv.load_dotenv",
        lambda *a, **kw: (_ for _ in ()).throw(
            RuntimeError("DA4 violation: load_dotenv called during scan")
        ),
    )

    # Poison-trap 2: sqlite3.connect must NOT be called
    import sqlite3

    monkeypatch.setattr(
        sqlite3,
        "connect",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("DA4 violation: sqlite3.connect called during scan")
        ),
    )

    # Poison-trap 3: psycopg2.connect must NOT be called (skip if not installed)
    try:
        import psycopg2

        monkeypatch.setattr(
            psycopg2,
            "connect",
            lambda *a, **kw: (_ for _ in ()).throw(
                RuntimeError("DA4 violation: psycopg2.connect called during scan")
            ),
        )
    except ImportError:
        pass

    # Capture initial DATABASE_URL state
    initial_db_url = os.environ.get("DATABASE_URL")

    # Write a test file that @patches src.api.app
    test_file = tmp_path / "test_xyz.py"
    test_file.write_text(
        """
from unittest.mock import patch

@patch('src.api.app.something_important_xyz')
def test_thing(mock_app):
    mock_app.return_value = 42
    result = some_sut()
    assert result == 42
""",
        encoding="utf-8",
    )

    # Run the scan — must NOT trigger any poison-trap
    from src.tools.testpatternscan import scan

    result = scan(path=tmp_path, kinds=["patch_drift"])

    # Sanity: scan should have completed (poison-traps would have raised)
    assert isinstance(result, list)

    # Verify DATABASE_URL env preserved
    final_db_url = os.environ.get("DATABASE_URL")
    assert final_db_url == initial_db_url, (
        f"DATABASE_URL changed during scan: {initial_db_url!r} -> {final_db_url!r}"
    )
