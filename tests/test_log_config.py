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


class TestDBLogHandlerCtx:
    def test_ctx_stored_in_details_json(self, tmp_path):
        """DBLogHandler should store ctx dict in details_json column."""
        import sqlite3
        from src.journal.store import initialize_database

        db = str(tmp_path / "test.db")
        initialize_database(db)

        from src.scheduler.watch import DBLogHandler
        handler = DBLogHandler(db_path=db)

        record = logging.LogRecord(
            "src.test", logging.WARNING, "", 0, "test warning", (), None)
        record.ctx = {"event": "test_event", "ticker": "AAPL"}
        handler.emit(record)

        with sqlite3.connect(db) as conn:
            row = conn.execute("SELECT details_json FROM log_entries LIMIT 1").fetchone()
        assert row is not None
        parsed = json.loads(row[0])
        assert parsed["event"] == "test_event"
        assert parsed["ticker"] == "AAPL"
