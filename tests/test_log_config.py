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


class TestSetupLoggingUnicodeSafety:
    """Regression guard for 2026-04-14 incident where ❌ (\\u274c) crashed the
    console logger on Windows cp1252 stdout, dropping '[WATCH] Reconciliation:
    2 mismatched' and spamming tracebacks instead."""

    def test_setup_logging_does_not_crash_on_emoji_with_narrow_encoding(self, monkeypatch):
        import io
        import sys
        from src.log_config import setup_logging

        # Simulate a Windows console: cp1252 with strict errors would raise
        # UnicodeEncodeError on \u274c (❌). Python's logging framework catches
        # the exception internally via handleError() and silently drops the
        # record — so we must assert the message actually reached the stream
        # (possibly with emoji replaced), not merely that no exception escaped.
        raw = io.BytesIO()
        narrow_stream = io.TextIOWrapper(
            raw, encoding="cp1252", errors="strict", newline="", write_through=True
        )
        monkeypatch.setattr(sys, "stdout", narrow_stream)

        try:
            setup_logging()
            logger = logging.getLogger("unicode_safety_test")
            logger.info("status: %s reconciliation done", "\u274c 2 mismatched")
            for h in logging.getLogger().handlers:
                h.flush()
            narrow_stream.flush()
        finally:
            logging.getLogger().handlers.clear()

        written = raw.getvalue().decode("cp1252", errors="replace")
        assert "reconciliation done" in written, (
            f"Log message was silently dropped by logging.handleError(); "
            f"stream bytes: {raw.getvalue()!r}"
        )
        assert "2 mismatched" in written


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
