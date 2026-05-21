"""Tests for the deploy-atomicity startup guard (dual-GPU separation T6, §4.6).

WatchLoop._assert_ollama_watchdog_present():
- service not RUNNING -> raises + fires a loud alert.
- service RUNNING -> proceeds silently.
- ARCIS_SKIP_WATCHDOG_GUARD=1 -> skipped entirely (CI/dev escape hatch).
"""

import pytest

from src.scheduler import watch as watch_mod


def _make_loop():
    return watch_mod.WatchLoop(config={}, email_mode="digest")


def test_guard_raises_and_alerts_when_service_not_running(monkeypatch):
    monkeypatch.delenv("ARCIS_SKIP_WATCHDOG_GUARD", raising=False)
    loop = _make_loop()

    monkeypatch.setattr(loop, "_query_watchdog_service_state", lambda: "STOPPED")

    alerts = []
    monkeypatch.setattr(
        watch_mod, "safe_send",
        lambda event_type, **kw: alerts.append((event_type, kw)),
    )

    with pytest.raises(RuntimeError):
        loop._assert_ollama_watchdog_present()

    assert alerts, "expected a loud alert when the watchdog service is down"
    _event, kw = alerts[0]
    assert kw.get("success") is False


def test_guard_proceeds_when_service_running(monkeypatch):
    monkeypatch.delenv("ARCIS_SKIP_WATCHDOG_GUARD", raising=False)
    loop = _make_loop()

    monkeypatch.setattr(loop, "_query_watchdog_service_state", lambda: "RUNNING")

    alerts = []
    monkeypatch.setattr(
        watch_mod, "safe_send",
        lambda event_type, **kw: alerts.append((event_type, kw)),
    )

    # Must not raise and must not alert.
    loop._assert_ollama_watchdog_present()
    assert alerts == []


def test_guard_skipped_via_env_flag(monkeypatch):
    monkeypatch.setenv("ARCIS_SKIP_WATCHDOG_GUARD", "1")
    loop = _make_loop()

    def _boom():
        raise AssertionError("service state must not be queried when skipped")

    monkeypatch.setattr(loop, "_query_watchdog_service_state", _boom)

    alerts = []
    monkeypatch.setattr(
        watch_mod, "safe_send",
        lambda event_type, **kw: alerts.append((event_type, kw)),
    )

    # Skipped: no query, no raise, no alert.
    loop._assert_ollama_watchdog_present()
    assert alerts == []
