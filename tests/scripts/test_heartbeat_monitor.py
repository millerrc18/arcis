"""Tests for scripts/heartbeat_monitor.py — the independent PG/heartbeat watchdog.

Non-vacuous: the edge-trigger/de-dup logic is driven across DOWN→UP transitions
with a real on-disk state file; pg_reachable is exercised against real closed and
listening sockets. Regression-locks the 2026-06-11 "21h outage went unnoticed".
"""
from __future__ import annotations

import socket
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from scripts import heartbeat_monitor as hm


def _write_heartbeat(data_root, age_seconds: float) -> None:
    ts = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    (data_root / "watchdog.txt").write_text(ts.isoformat(), encoding="utf-8")


class TestEvaluate:
    def test_down_when_pg_unreachable(self, tmp_path):
        _write_heartbeat(tmp_path, 10)  # heartbeat fresh — PG is the only fault
        with patch.object(hm, "pg_reachable", return_value=False):
            r = hm.evaluate(tmp_path / "watchdog.txt", 1800)
        assert r["down"] is True
        assert any("unreachable" in x for x in r["reasons"])

    def test_down_when_heartbeat_stale(self, tmp_path):
        _write_heartbeat(tmp_path, 4000)  # > 1800s
        with patch.object(hm, "pg_reachable", return_value=True):
            r = hm.evaluate(tmp_path / "watchdog.txt", 1800)
        assert r["down"] is True
        assert any("stale" in x for x in r["reasons"])

    def test_down_when_heartbeat_missing(self, tmp_path):
        with patch.object(hm, "pg_reachable", return_value=True):
            r = hm.evaluate(tmp_path / "watchdog.txt", 1800)  # no watchdog.txt
        assert r["down"] is True
        assert any("missing" in x for x in r["reasons"])

    def test_healthy_when_pg_ok_and_heartbeat_fresh(self, tmp_path):
        _write_heartbeat(tmp_path, 60)
        with patch.object(hm, "pg_reachable", return_value=True):
            r = hm.evaluate(tmp_path / "watchdog.txt", 1800)
        assert r["down"] is False
        assert r["reasons"] == []


class TestPgReachableRealSocket:
    def test_false_on_closed_port(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()  # now nothing listens on `port`
        assert hm.pg_reachable("127.0.0.1", port, timeout=1.0) is False

    def test_true_on_listening_port(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
        try:
            assert hm.pg_reachable("127.0.0.1", port, timeout=1.0) is True
        finally:
            s.close()


class TestEdgeTriggerAndDedup:
    def test_pages_once_after_fail_threshold_then_recovers_once(self, tmp_path):
        send = MagicMock(return_value=True)
        with patch.object(hm, "_send_alert", send):
            # Run 1 — DOWN, but consecutive(1) < threshold(2): no page yet (anti-flap).
            with patch.object(hm, "pg_reachable", return_value=False):
                r1 = hm.run_once(fail_threshold=2, data_root=tmp_path)
            assert r1["down"] is True
            assert send.call_count == 0

            # Run 2 — DOWN, consecutive(2) == threshold: pages exactly once.
            with patch.object(hm, "pg_reachable", return_value=False):
                hm.run_once(fail_threshold=2, data_root=tmp_path)
            assert send.call_count == 1
            assert "DOWN" in send.call_args[0][0]

            # Run 3 — still DOWN, already alerting: NO repeat page.
            with patch.object(hm, "pg_reachable", return_value=False):
                hm.run_once(fail_threshold=2, data_root=tmp_path)
            assert send.call_count == 1

            # Run 4 — UP (pg ok + fresh heartbeat): one RECOVERED page.
            _write_heartbeat(tmp_path, 10)
            with patch.object(hm, "pg_reachable", return_value=True):
                hm.run_once(fail_threshold=2, data_root=tmp_path)
            assert send.call_count == 2
            assert "RECOVERED" in send.call_args[0][0]

            # Run 5 — still UP: no further page.
            with patch.object(hm, "pg_reachable", return_value=True):
                hm.run_once(fail_threshold=2, data_root=tmp_path)
            assert send.call_count == 2

    def test_transient_single_down_does_not_page(self, tmp_path):
        send = MagicMock(return_value=True)
        _write_heartbeat(tmp_path, 10)
        with patch.object(hm, "_send_alert", send):
            with patch.object(hm, "pg_reachable", return_value=False):
                hm.run_once(fail_threshold=2, data_root=tmp_path)  # 1 down < 2
            with patch.object(hm, "pg_reachable", return_value=True):
                hm.run_once(fail_threshold=2, data_root=tmp_path)  # recovered before threshold
        assert send.call_count == 0  # a one-run blip never pages

    def test_dry_run_never_sends(self, tmp_path):
        send = MagicMock(return_value=True)
        with patch.object(hm, "_send_alert", send), \
                patch.object(hm, "pg_reachable", return_value=False):
            hm.run_once(fail_threshold=1, dry_run=True, data_root=tmp_path)
            hm.run_once(fail_threshold=1, dry_run=True, data_root=tmp_path)
        assert send.call_count == 0
