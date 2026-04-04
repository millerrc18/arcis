"""Tests for atomic kill switch implementation."""

import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.risk import governor

ET = ZoneInfo("America/New_York")


class TestAtomicKillSwitch:
    def setup_method(self):
        self._orig = governor._HALT_FILE
        self._test_file = "data/test_halt_switch"
        governor._HALT_FILE = self._test_file
        for f in [self._test_file, self._test_file + ".tmp"]:
            if os.path.exists(f):
                os.remove(f)

    def teardown_method(self):
        governor._HALT_FILE = self._orig
        for f in [self._test_file, self._test_file + ".tmp"]:
            if os.path.exists(f):
                os.remove(f)

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

        import logging
        with caplog.at_level(logging.WARNING):
            result = governor._is_halted()
        assert result is True
        assert "stale" in caplog.text.lower() or "48" in caplog.text

    def test_halt_info_returns_metadata(self):
        governor._global_halt(True, source="telegram", reason="manual halt")
        info = governor._halt_info()
        assert info is not None
        assert info["source"] == "telegram"
        assert info["reason"] == "manual halt"

    def test_halt_info_none_when_not_halted(self):
        assert governor._halt_info() is None
