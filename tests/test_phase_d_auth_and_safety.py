"""Tier-4 scoped feature work (#576, #598, #624, #622)."""

from __future__ import annotations

import inspect
import pathlib
import re

import pytest


# ── #576 — actions.py POST endpoints have local-token gate ──

class TestActionsRouterAuthGate:
    """All 7 POST endpoints in actions.py must be gated through the
    verify_local_token dep so operators can opt in to hardening via
    ARCIS_LOCAL_API_TOKEN env var."""

    def test_actions_router_has_local_auth_dependency(self):
        from src.api.routes import actions
        # APIRouter exposes its router-level dependencies via .dependencies
        deps = getattr(actions.router, "dependencies", None) or []
        # Each dep is a Depends(callable); inspect the callable name
        names = [getattr(d, "dependency", None).__name__ for d in deps if getattr(d, "dependency", None)]
        assert "verify_local_token" in names, (
            "actions.router must include verify_local_token at the router level (#576)"
        )

    def test_local_auth_no_op_when_env_unset(self, monkeypatch):
        from src.api.local_auth import verify_local_token
        monkeypatch.delenv("ARCIS_LOCAL_API_TOKEN", raising=False)
        # Should not raise even with no Authorization header
        assert verify_local_token(authorization=None) is None

    def test_local_auth_rejects_when_env_set_and_no_header(self, monkeypatch):
        from fastapi import HTTPException
        from src.api.local_auth import verify_local_token
        monkeypatch.setenv("ARCIS_LOCAL_API_TOKEN", "secret123")
        with pytest.raises(HTTPException) as exc:
            verify_local_token(authorization=None)
        assert exc.value.status_code == 401

    def test_local_auth_accepts_correct_bearer(self, monkeypatch):
        from src.api.local_auth import verify_local_token
        monkeypatch.setenv("ARCIS_LOCAL_API_TOKEN", "secret123")
        assert verify_local_token(authorization="Bearer secret123") is None

    def test_local_auth_uses_constant_time_compare(self):
        from src.api import local_auth
        src = inspect.getsource(local_auth)
        assert "compare_digest" in src, (
            "verify_local_token must use hmac.compare_digest (#576)"
        )


# ── #598 — platform.py POST endpoints have Depends(verify_auth) ──

class TestPlatformPostsHaveVerifyAuth:
    """3 mutating POST endpoints in cloud_routes/platform.py must include
    verify_auth in their decorator dependencies."""

    SRC = pathlib.Path("src/api/cloud_routes/platform.py").read_text(encoding="utf-8")

    def test_promotions_has_verify_auth_dep(self):
        m = re.search(
            r"@router\.post\(\s*[\"']/api/platform/promotions[\"'][^)]*\)",
            self.SRC,
            re.DOTALL,
        )
        assert m, "/api/platform/promotions decorator not found"
        assert "verify_auth" in m.group(0), (
            "/api/platform/promotions must declare verify_auth dependency (#598)"
        )

    def test_demotions_has_verify_auth_dep(self):
        m = re.search(
            r"@router\.post\(\s*[\"']/api/platform/demotions[\"'][^)]*\)",
            self.SRC,
            re.DOTALL,
        )
        assert m, "/api/platform/demotions decorator not found"
        assert "verify_auth" in m.group(0), (
            "/api/platform/demotions must declare verify_auth dependency (#598)"
        )

    def test_backtests_has_verify_auth_dep(self):
        m = re.search(
            r"@router\.post\(\s*[\"']/api/platform/backtests[\"'][^)]*\)",
            self.SRC,
            re.DOTALL,
        )
        assert m, "/api/platform/backtests decorator not found"
        assert "verify_auth" in m.group(0), (
            "/api/platform/backtests must declare verify_auth dependency (#598)"
        )

    def test_cloud_app_overrides_platform_verify_auth(self):
        """cloud_app must wire its real verify_auth into platform's placeholder
        via dependency_overrides — the placeholder is a no-op until it does."""
        from src.api import cloud_app
        # The override is a runtime dict; presence of the assignment is enough
        # to assert the wiring exists (we can't easily verify the override is
        # active without a full TestClient run).
        src = pathlib.Path("src/api/cloud_app.py").read_text(encoding="utf-8")
        assert "dependency_overrides" in src and "_platform_module.verify_auth" in src, (
            "cloud_app must override _platform_module.verify_auth with the real verify_auth (#598)"
        )


# ── #624 — stuck-resolution PnL must be NULL not 0 when price unknown ──

class TestStuckResolutionPnlIsNullable:
    def test_helper_returns_none_when_price_unknown(self):
        from src.shadow_trading.reconcile import _resolve_stuck_pnl
        trade = {"entry_price": 100.0, "shares": 10}
        pnl = _resolve_stuck_pnl(trade, exit_reason="timeout",
                                 current_price_provider=lambda t: None)
        assert pnl is None, (
            "#624 — must return None (NULL pnl) when price unknown, "
            "not 0.0 (which contaminates training_examples)"
        )

    def test_helper_returns_real_pnl_when_price_known(self):
        from src.shadow_trading.reconcile import _resolve_stuck_pnl
        trade = {"entry_price": 100.0, "shares": 10}
        pnl = _resolve_stuck_pnl(trade, exit_reason="timeout",
                                 current_price_provider=lambda t: 105.0)
        assert pnl == pytest.approx(50.0)  # (105 - 100) * 10

    def test_helper_uses_target_for_target_hit(self):
        from src.shadow_trading.reconcile import _resolve_stuck_pnl
        trade = {"entry_price": 100.0, "shares": 10, "target_1": 110.0}
        pnl = _resolve_stuck_pnl(trade, exit_reason="target_1_hit",
                                 current_price_provider=lambda t: None)
        assert pnl == pytest.approx(100.0)  # (110 - 100) * 10 — uses target

    def test_helper_uses_stop_for_stop_hit(self):
        from src.shadow_trading.reconcile import _resolve_stuck_pnl
        trade = {"entry_price": 100.0, "shares": 10, "stop_price": 95.0}
        pnl = _resolve_stuck_pnl(trade, exit_reason="stop_hit",
                                 current_price_provider=lambda t: None)
        assert pnl == pytest.approx(-50.0)  # (95 - 100) * 10


# ── #622 — signal.signal calls in watch.py are wrapped ──

class TestWatchSignalHandlerAudit:
    def test_all_signal_signal_calls_wrapped_in_try_except(self):
        text = pathlib.Path("src/scheduler/watch.py").read_text(encoding="utf-8")
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if "signal.signal(" in line and not line.strip().startswith("#"):
                # Window of 12 lines before and after
                window = "\n".join(lines[max(0, i - 12):min(len(lines), i + 12)])
                assert ("except ValueError" in window
                        or "except (ValueError" in window
                        or "except (RuntimeError, ValueError" in window), (
                    f"#622 — watch.py:{i + 1} signal.signal() not wrapped in "
                    f"try/except ValueError. Worker-thread starts will raise."
                )
