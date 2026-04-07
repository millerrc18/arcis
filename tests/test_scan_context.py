"""Tests for scan_id generation and ScanContext."""


class TestScanContext:
    def test_scan_id_field_exists(self):
        from src.scheduler.universe_scanner import ScanContext
        ctx = ScanContext(config={}, scan_id="s-001")
        assert ctx.scan_id == "s-001"

    def test_scan_id_defaults_to_none(self):
        from src.scheduler.universe_scanner import ScanContext
        ctx = ScanContext(config={})
        assert ctx.scan_id is None
