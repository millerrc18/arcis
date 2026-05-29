"""Regression tests for C3 — db_path=None resolution.

Audit 2026-04-20 saw 13 TypeErrors/day in the intra-day reconcile path
because ``src/scheduler/watch.py:694`` calls ``reconcile_all_paper_trades``
without passing ``db_path``. The default was ``None``; that ``None``
propagated through ``get_strategies_by_status`` to ``sqlite3.connect(None)``
which raises ``TypeError``.

Fix: both ``reconcile_all_paper_trades`` and ``get_strategies_by_status``
now resolve ``db_path=None`` to the config default ``DB_PATH``.
"""
from __future__ import annotations

from unittest.mock import patch


def test_reconcile_all_paper_trades_resolves_none_to_config_db_path():
    """db_path=None must resolve to config DB_PATH, not propagate as None."""
    captured: dict = {}

    def fake_reconcile(desk, dry_run, db_path):
        captured.setdefault("reconcile", []).append(db_path)
        return {"status": "ok", "desk": desk}

    def fake_get_strategies(statuses, db_path=None):
        captured["get_strategies"] = db_path
        return []  # no research strategies — keeps the test focused

    with patch(
        "src.shadow_trading.reconcile_dispatch.reconcile_paper_trades",
        side_effect=fake_reconcile,
    ), patch(
        "src.shadow_trading.reconcile_dispatch.get_strategies_by_status",
        side_effect=fake_get_strategies,
    ):
        from src.config import DB_PATH
        from src.shadow_trading.reconcile_dispatch import reconcile_all_paper_trades

        reconcile_all_paper_trades()  # default db_path=None is the bug site

        # swing desk receives resolved DB_PATH, not None
        assert captured["reconcile"][0] == DB_PATH
        # downstream strategy lookup also receives resolved DB_PATH
        assert captured["get_strategies"] == DB_PATH


def test_reconcile_all_paper_trades_preserves_explicit_path(tmp_path):
    """Caller-supplied db_path must NOT be overridden by config."""
    explicit = str(tmp_path / "explicit.sqlite3")
    captured: dict = {}

    def fake_reconcile(desk, dry_run, db_path):
        captured.setdefault("paths", []).append(db_path)
        return {"status": "ok"}

    def fake_get_strategies(statuses, db_path=None):
        captured["get_strategies"] = db_path
        return []

    with patch(
        "src.shadow_trading.reconcile_dispatch.reconcile_paper_trades",
        side_effect=fake_reconcile,
    ), patch(
        "src.shadow_trading.reconcile_dispatch.get_strategies_by_status",
        side_effect=fake_get_strategies,
    ):
        from src.shadow_trading.reconcile_dispatch import reconcile_all_paper_trades

        reconcile_all_paper_trades(db_path=explicit)

        assert captured["paths"][0] == explicit
        assert captured["get_strategies"] == explicit


def test_get_strategies_by_status_resolves_none_to_config():
    """Explicit db_path=None must resolve, not crash sqlite3.connect."""
    from src.config import DB_PATH
    from src.platform import promotion

    captured: dict = {}

    class FakeCursor:
        def fetchall(self):
            return []

    class FakeConn:
        def execute(self, *a, **kw):
            return FakeCursor()

        def close(self):
            pass

    def fake_connect(path, *args, **kwargs):
        # *args/**kwargs: get_strategies_by_status now routes through
        # connect_db(), which calls sqlite3.connect(path, timeout=...).
        captured["path"] = path
        return FakeConn()

    with patch.object(promotion.sqlite3, "connect", side_effect=fake_connect):
        result = promotion.get_strategies_by_status(
            ["shadow_trading"], db_path=None,
        )

    assert result == []
    assert captured["path"] == DB_PATH
    # sanity: the None guard did not leak None into sqlite3
    assert captured["path"] is not None


def test_get_strategies_by_status_preserves_explicit_path(tmp_path):
    """Explicit non-None db_path flows through unchanged."""
    from src.platform import promotion

    explicit = str(tmp_path / "foo.sqlite3")
    captured: dict = {}

    class FakeCursor:
        def fetchall(self):
            return []

    class FakeConn:
        def execute(self, *a, **kw):
            return FakeCursor()

        def close(self):
            pass

    with patch.object(
        promotion.sqlite3, "connect",
        side_effect=lambda p, *a, **k: (captured.__setitem__("path", p), FakeConn())[1],
    ):
        result = promotion.get_strategies_by_status(
            ["shadow_trading"], db_path=explicit,
        )

    assert result == []
    assert captured["path"] == explicit


def test_get_strategies_by_status_empty_statuses_short_circuits():
    """Pre-existing short-circuit behavior preserved: empty statuses → []."""
    from src.platform.promotion import get_strategies_by_status

    assert get_strategies_by_status([]) == []
    assert get_strategies_by_status([], db_path=None) == []
