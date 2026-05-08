"""Tests for atomic kill switch implementation."""

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from src.risk import governor

ET = ZoneInfo("America/New_York")

_DEFAULT_HALT_FILE = governor._DEFAULT_HALT_FILE


class TestAtomicKillSwitch:
    def setup_method(self):
        # Save whatever _HALT_FILE is now (may differ from _DEFAULT_HALT_FILE
        # if a prior test left it dirty without restoring).
        self._orig = governor._HALT_FILE
        self._test_file = "data/test_halt_switch"
        governor._HALT_FILE = self._test_file

        # Clean the test-specific halt file (and .tmp scratch) so each test
        # starts from a known-empty state regardless of prior test outcomes.
        for f in [self._test_file, self._test_file + ".tmp"]:
            if os.path.exists(f):
                os.remove(f)

        # Defensive: also remove the DEFAULT halt file.  A prior test (or a
        # real operator halt command left on disk) could have created
        # data/trading_halted.  If the module ever gets reloaded mid-suite
        # (e.g. importlib.reload in another test file), _HALT_FILE would
        # reset to _DEFAULT_HALT_FILE and suddenly _get_halt_path() would
        # check the real halt file instead of the test-scoped one, breaking
        # test_is_halted_false_when_no_file and test_halt_info_none_when_not_halted.
        default_path = Path(_DEFAULT_HALT_FILE)
        if default_path.exists():
            default_path.unlink(missing_ok=True)

    def teardown_method(self):
        # Restore to the DEFAULT halt file path, not self._orig — if self._orig
        # was itself a dirty value from a prior test's missing teardown, we
        # would propagate the contamination.  The safe baseline is the known
        # module-level default.
        governor._HALT_FILE = _DEFAULT_HALT_FILE

        for f in [self._test_file, self._test_file + ".tmp"]:
            if os.path.exists(f):
                os.remove(f)

        # Also clean the default path in case a test created it.
        default_path = Path(_DEFAULT_HALT_FILE)
        if default_path.exists():
            default_path.unlink(missing_ok=True)

    def test_halt_creates_file_with_timestamp(self):
        governor._global_halt(True, source="test", reason="unit test")
        path = governor._get_halt_path()
        assert path.exists()
        data = json.loads(path.read_text())
        assert "halted_at" in data
        assert data["source"] == "test"

    def test_resume_removes_file(self):
        governor._global_halt(True, source="test")
        assert governor._is_halted()
        governor._global_halt(False)
        assert not governor._is_halted()

    def test_is_halted_false_when_no_file(self):
        assert not governor._is_halted()

    def test_stale_halt_file_logs_warning(self, caplog):
        path = governor._get_halt_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        old_time = (datetime.now(ET) - timedelta(hours=49)).isoformat()
        path.write_text(json.dumps({"halted_at": old_time, "source": "test"}))

        with caplog.at_level(logging.WARNING):
            result = governor._is_halted()
        assert result is True
        assert "stale" in caplog.text.lower() or "48" in caplog.text

    def test_halt_info_returns_metadata(self):
        # source="cli" is in the operator-allowlist (operator policy 2026-05-08).
        # Original test used source="telegram" before the source allowlist
        # was added — telegram is no longer a permitted halt source.
        governor._global_halt(True, source="cli", reason="manual halt")
        info = governor._halt_info()
        assert info is not None
        assert info["source"] == "cli"
        assert info["reason"] == "manual halt"

    def test_halt_info_none_when_not_halted(self):
        assert governor._halt_info() is None

    def test_isolation_survives_default_halt_file_on_disk(self):
        """Regression: kill_switch tests must be unaffected by data/trading_halted.

        Simulates the pollution condition: a prior test or operator halt command
        left data/trading_halted on disk.  Because setup_method redirects
        _HALT_FILE to the test-scoped path, _get_halt_path() checks
        data/test_halt_switch (empty) — not data/trading_halted — so the
        tests see a clean halted=False state.
        """
        default_path = Path(_DEFAULT_HALT_FILE)
        default_path.parent.mkdir(parents=True, exist_ok=True)
        default_path.write_text(
            json.dumps({"halted_at": "2020-01-01T00:00:00+00:00", "source": "pollution"})
        )
        try:
            assert not governor._is_halted()
            assert governor._halt_info() is None
        finally:
            default_path.unlink(missing_ok=True)
