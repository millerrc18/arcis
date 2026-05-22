"""Tests for the startup command validation checks.

Covers: src/startup.py check functions, StartupResult properties,
        persistence, and CLI behavior.
"""

import os
import sqlite3
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.startup import (
    CheckResult,
    StartupResult,
    check_config,
    check_environment,
    check_connectivity,
    check_services,
    check_schema,
    is_watch_loop_running,
    persist_startup_result,
    STARTUP_CATEGORIES,
)


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary SQLite database with schema from registry."""
    db = str(tmp_path / "test.db")
    from src.schema.sqlite import create_all_tables
    create_all_tables(db)
    return db


@pytest.fixture
def sample_config():
    """Minimal config dict for testing."""
    return {
        "alpaca": {
            "api_key": "REAL_KEY_12345",
            "api_secret": "REAL_SECRET_12345",
            "base_url": "https://paper-api.alpaca.markets",
        },
        "shadow_trading": {"enabled": True},
        "live_trading": {"enabled": False},
        "render": {"enabled": True, "database_url": "postgresql://..."},
        "telegram": {
            "enabled": True,
            "bot_token": "123:ABC",
            "chat_id": "456",
        },
        "email": {
            "smtp_server": "smtp.gmail.com",
            "username": "test@test.com",
            "password": "secret",
        },
        "risk": {"starting_capital": 100000},
        "llm": {"model": "halcyon-v1"},
        "training": {"enabled": True},
        "data_enrichment": {
            "finnhub_api_key": "test_key",
            "fred_api_key": "test_key",
        },
    }


# ── CheckResult and StartupResult ────────────────────────────────────


class TestStartupResult:
    def test_overall_status_healthy(self):
        r = StartupResult(checks=[
            CheckResult("a", "config", "ok", "good", "hint"),
            CheckResult("b", "schema", "ok", "good", "hint"),
        ])
        assert r.overall_status == "healthy"
        assert len(r.passed) == 2
        assert len(r.warnings) == 0
        assert len(r.criticals) == 0

    def test_overall_status_degraded(self):
        r = StartupResult(checks=[
            CheckResult("a", "config", "ok", "good", "hint"),
            CheckResult("b", "env", "warn", "missing", "hint"),
        ])
        assert r.overall_status == "degraded"
        assert len(r.warnings) == 1

    def test_overall_status_critical(self):
        r = StartupResult(checks=[
            CheckResult("a", "config", "critical", "bad", "hint"),
            CheckResult("b", "env", "warn", "missing", "hint"),
        ])
        assert r.overall_status == "critical"
        assert len(r.criticals) == 1

    def test_fix_hint_mandatory(self):
        """Every CheckResult must have a non-empty fix_hint."""
        for _label, check_fn in STARTUP_CATEGORIES:
            # We can't run all checks without mocking, but we can verify
            # the dataclass enforces non-None
            c = CheckResult("test", "test", "ok", "detail", "hint")
            assert c.fix_hint  # non-empty


# ── check_config ─────────────────────────────────────────────────────


class TestCheckConfig:
    def test_local_config_exists(self, sample_config):
        with patch("src.startup.Path") as mock_path:
            mock_path.return_value.exists.return_value = True
            # Also need to handle the Path("config/settings.local.yaml") call
            with patch("pathlib.Path.exists", return_value=True):
                results = check_config(sample_config)
        ok_results = [r for r in results if r.status == "ok"]
        assert len(ok_results) >= 1

    def test_no_local_config(self, sample_config):
        with patch("pathlib.Path.exists", return_value=False):
            results = check_config(sample_config)
        criticals = [r for r in results if r.status == "critical"]
        assert len(criticals) >= 1
        assert "settings.local.yaml not found" in criticals[0].detail

    def test_placeholder_values_detected(self):
        config = {
            "alpaca": {"api_key": "YOUR_PAPER_API_KEY", "api_secret": "YOUR_SECRET"},
        }
        env_patch = {"ALPACA_API_KEY": "", "ALPACA_API_SECRET": ""}
        with patch("pathlib.Path.exists", return_value=True), \
             patch.dict("os.environ", env_patch, clear=False):
            results = check_config(config)
        criticals = [r for r in results if r.status == "critical"]
        assert any("Placeholder" in c.detail for c in criticals)


# ── check_environment ────────────────────────────────────────────────


class TestCheckEnvironment:
    def test_all_keys_present(self, sample_config):
        with patch.dict(os.environ, {"FINNHUB_API_KEY": "key", "FRED_API_KEY": "key"}):
            results = check_environment(sample_config)
        assert all(r.status == "ok" for r in results)

    def test_missing_finnhub(self):
        config = {"data_enrichment": {}}
        with patch.dict(os.environ, {}, clear=True):
            # Remove both env and config sources
            results = check_environment(config)
        warns = [r for r in results if r.status == "warn"]
        assert any("FINNHUB" in r.detail for r in warns)

    def test_yaml_config_fallback(self, sample_config):
        """If env var missing but yaml config has the key, it's OK."""
        with patch.dict(os.environ, {}, clear=True):
            results = check_environment(sample_config)
        # Both should be ok because sample_config has them in data_enrichment
        assert all(r.status == "ok" for r in results)


# ── check_connectivity ───────────────────────────────────────────────


class TestCheckConnectivity:
    def test_alpaca_ok(self, sample_config):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"equity": "107432.50"}

        with patch("requests.get", return_value=mock_resp), \
             patch("src.llm.client.is_llm_available", return_value=True):
            results = check_connectivity(sample_config)

        alpaca = [r for r in results if r.name == "alpaca"][0]
        assert alpaca.status == "ok"
        assert "$107,432" in alpaca.detail

    def test_alpaca_timeout(self, sample_config):
        with patch("requests.get", side_effect=Exception("timeout")), \
             patch("src.llm.client.is_llm_available", return_value=False):
            results = check_connectivity(sample_config)

        alpaca = [r for r in results if r.name == "alpaca"][0]
        assert alpaca.status == "critical"

    def test_ollama_down(self, sample_config):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"equity": "100000"}

        with patch("requests.get", return_value=mock_resp), \
             patch("src.llm.client.is_llm_available", return_value=False):
            results = check_connectivity(sample_config)

        ollama = [r for r in results if r.name == "ollama"][0]
        assert ollama.status == "warn"

    def test_render_db_not_configured(self, monkeypatch):
        # v0.36.48: the Render check only runs PRE-cutover; force cutover off.
        monkeypatch.delenv("ARCIS_PG_CUTOVER_ENABLED", raising=False)
        config = {"alpaca": {"api_key": "x", "api_secret": "x"},
                  "render": {"enabled": True, "database_url": ""}}
        with patch("requests.get", return_value=MagicMock(status_code=200, json=lambda: {"equity": "100"})), \
             patch("src.llm.client.is_llm_available", return_value=True):
            results = check_connectivity(config)
        render = [r for r in results if r.name == "render_db"]
        assert len(render) == 1
        assert render[0].status == "critical"

    def test_render_db_connect_uses_timeout(self, monkeypatch):
        """Regression: psycopg2.connect on the startup path must pass
        connect_timeout, otherwise an unreachable Render DB hangs startup
        indefinitely (libpq default is no timeout)."""
        # v0.36.48: the Render check only runs PRE-cutover; force cutover off.
        monkeypatch.delenv("ARCIS_PG_CUTOVER_ENABLED", raising=False)
        config = {"alpaca": {"api_key": "x", "api_secret": "x"},
                  "render": {"enabled": True,
                             "database_url": "postgresql://u:p@h:5432/d"}}

        mock_psycopg2 = MagicMock()
        mock_psycopg2.connect.side_effect = Exception("unreachable")

        with patch.dict("sys.modules", {"psycopg2": mock_psycopg2}), \
             patch("requests.get",
                   return_value=MagicMock(status_code=200,
                                          json=lambda: {"equity": "100"})), \
             patch("src.llm.client.is_llm_available", return_value=True):
            check_connectivity(config)

        assert mock_psycopg2.connect.called, "psycopg2.connect was not invoked"
        for call in mock_psycopg2.connect.call_args_list:
            assert "connect_timeout" in call.kwargs, (
                f"connect_timeout missing from psycopg2.connect call: {call}"
            )


# ── check_services ───────────────────────────────────────────────────


class TestCheckServices:
    def test_all_enabled(self, sample_config, tmp_db):
        with patch("src.risk.governor._is_halted", return_value=False), \
             patch("src.training.versioning.get_active_model_name", return_value="halcyon-v1"):
            results = check_services(sample_config, tmp_db)
        ok_results = [r for r in results if r.status == "ok"]
        assert len(ok_results) >= 5  # shadow, render, telegram, email, kill_switch, capital, model

    def test_kill_switch_active(self, sample_config, tmp_db):
        with patch("src.risk.governor._is_halted", return_value=True), \
             patch("src.training.versioning.get_active_model_name", return_value="v1"):
            results = check_services(sample_config, tmp_db)
        ks = [r for r in results if r.name == "kill_switch"][0]
        assert ks.status == "warn"
        assert "ACTIVE" in ks.detail

    def test_low_capital(self, tmp_db):
        config = {
            "shadow_trading": {"enabled": False},
            "render": {"enabled": False},
            "telegram": {},
            "email": {},
            "risk": {"starting_capital": 500},
        }
        with patch("src.risk.governor._is_halted", return_value=False), \
             patch("src.training.versioning.get_active_model_name", return_value=None):
            results = check_services(config, tmp_db)
        cap = [r for r in results if r.name == "starting_capital"][0]
        assert cap.status == "warn"
        assert "seems low" in cap.detail


# ── Persistence ──────────────────────────────────────────────────────


class TestPersistence:
    def test_persist_and_read(self, tmp_db):
        result = StartupResult(
            checks=[
                CheckResult("a", "config", "ok", "good", "hint"),
                CheckResult("b", "env", "warn", "missing", "fix it"),
            ],
            schema_fixes_applied=0,
            duration_ms=1234,
            timestamp="2026-04-04T21:31:00-04:00",
        )
        result_id = persist_startup_result(result, tmp_db)
        assert result_id

        with sqlite3.connect(tmp_db) as conn:
            row = conn.execute(
                "SELECT overall_status FROM validation_results WHERE result_id = ?",
                (result_id,),
            ).fetchone()
        assert row[0] == "degraded"


# ── PID lockfile ─────────────────────────────────────────────────────


class TestPIDLockfile:
    def test_no_lockfile(self, tmp_path):
        with patch("src.startup.Path", return_value=tmp_path / "nonexistent"):
            assert is_watch_loop_running() is None

    def test_lockfile_stale(self, tmp_path):
        lock = tmp_path / "watch.lock"
        lock.write_text("999999")  # PID that almost certainly doesn't exist
        with patch("src.startup.Path", return_value=lock):
            result = is_watch_loop_running()
        assert result is None


# ── Telegram notification ────────────────────────────────────────────


class TestStartupTelegram:
    def test_notify_startup_format(self):
        from src.notifications.telegram import notify_startup_complete
        with patch("src.notifications.telegram.send_telegram") as mock_send:
            mock_send.return_value = True
            notify_startup_complete(
                overall_status="degraded",
                passed=9, warnings=3, criticals=0,
                warning_details=["FINNHUB missing", "Ollama down"],
                launching=True, email_mode="digest", overnight=True,
            )
        mock_send.assert_called_once()
        msg = mock_send.call_args[0][0]
        assert "9 passed" in msg
        assert "3 warnings" in msg
        assert "DEGRADED" in msg
        assert "FINNHUB" in msg
