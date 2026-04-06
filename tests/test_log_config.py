"""Tests for structured log formatting."""

import logging
import json


class TestStructuredFormatter:
    def test_plain_message_unchanged(self):
        from src.log_config import StructuredFormatter
        fmt = StructuredFormatter("%(message)s")
        record = logging.LogRecord("test", logging.INFO, "", 0, "hello world", (), None)
        result = fmt.format(record)
        assert result == "hello world"
        assert "|ctx:" not in result

    def test_ctx_appended_as_json(self):
        from src.log_config import StructuredFormatter
        fmt = StructuredFormatter("%(message)s")
        record = logging.LogRecord("test", logging.INFO, "", 0, "exit failed", (), None)
        record.ctx = {"event": "exit_failed", "ticker": "TGT"}
        result = fmt.format(record)
        assert result.startswith("exit failed |ctx:")
        ctx_json = result.split("|ctx:")[1]
        parsed = json.loads(ctx_json)
        assert parsed["event"] == "exit_failed"
        assert parsed["ticker"] == "TGT"

    def test_ctx_none_no_suffix(self):
        from src.log_config import StructuredFormatter
        fmt = StructuredFormatter("%(message)s")
        record = logging.LogRecord("test", logging.INFO, "", 0, "normal log", (), None)
        record.ctx = None
        result = fmt.format(record)
        assert "|ctx:" not in result

    def test_ctx_empty_dict_no_suffix(self):
        from src.log_config import StructuredFormatter
        fmt = StructuredFormatter("%(message)s")
        record = logging.LogRecord("test", logging.INFO, "", 0, "normal log", (), None)
        record.ctx = {}
        result = fmt.format(record)
        assert "|ctx:" not in result

    def test_full_format_string(self):
        from src.log_config import StructuredFormatter
        fmt = StructuredFormatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")
        record = logging.LogRecord("src.executor", logging.ERROR, "", 0, "broker fail", (), None)
        record.ctx = {"event": "exit_failed"}
        result = fmt.format(record)
        assert "[src.executor] ERROR: broker fail |ctx:" in result

    def test_ctx_with_scan_id(self):
        from src.log_config import StructuredFormatter
        fmt = StructuredFormatter("%(message)s")
        record = logging.LogRecord("test", logging.INFO, "", 0, "scan done", (), None)
        record.ctx = {"event": "scan_complete", "scan_id": "s-042", "duration_s": 180}
        result = fmt.format(record)
        parsed = json.loads(result.split("|ctx:")[1])
        assert parsed["scan_id"] == "s-042"
        assert parsed["duration_s"] == 180
