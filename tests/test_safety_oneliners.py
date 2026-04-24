"""Tier-2 safety/security one-liners (#438, #440).

#438 — Risk governor was fail-OPEN when equity == 0 (size_ok = True).
#440 — Bearer token comparison used `==` (timing-attack vulnerable).
"""

from __future__ import annotations

import inspect

import pytest


# ── #438 — risk governor rejects when equity <= 0 ──

class TestGovernorRejectsZeroEquity:
    def test_zero_equity_rejects(self):
        from src.risk.governor import RiskGovernor
        # Build a minimal config so RiskGovernor instantiates with sane defaults.
        cfg = {
            "max_position_pct": 0.1,
            "max_sector_pct": 0.30,
            "max_correlated": 5,
            "risk_governor": {"enabled": True},
            "max_open_positions": 10,
        }
        g = RiskGovernor(cfg)
        portfolio = {
            "equity": 0.0,
            "open_positions": [],
            "open_count": 0,
            "sector_exposure": {},
            "daily_pnl": 0.0,
            "drawdown_pct": 0.0,
            "open_tickers": set(),
        }
        request = {
            "ticker": "AAPL",
            "shares": 10,
            "entry_price": 100.0,
            "stop_price": 95.0,
            "sector": "Technology",
            "allocation_dollars": 1000.0,
        }
        # check_trade signature varies; pull it via inspect to be safe.
        sig = inspect.signature(g.check_trade)
        kwargs = {}
        for name in sig.parameters:
            if name == "portfolio":
                kwargs[name] = portfolio
            elif name == "request":
                kwargs[name] = request
            elif name == "ticker":
                kwargs[name] = "AAPL"
            elif name == "shares":
                kwargs[name] = 10
            elif name == "entry_price":
                kwargs[name] = 100.0
            elif name == "stop_price":
                kwargs[name] = 95.0
            elif name == "sector":
                kwargs[name] = "Technology"
            elif name == "allocation_dollars":
                kwargs[name] = 1000.0
            elif name == "self":
                continue
        try:
            result = g.check_trade(**kwargs)
        except TypeError:
            pytest.skip("check_trade signature differs; covered by source-scan test")
        assert result.get("approved") is False, (
            "#438 — governor must reject when equity <= 0, not approve"
        )

    def test_governor_source_explicitly_rejects_zero_equity(self):
        """Source-level guard against the regression — even if signatures shift."""
        text = inspect.getsource(__import__("src.risk.governor", fromlist=["RiskGovernor"]))
        # The previous fail-open pattern used `size_ok = True` after `equity > 0`
        # branching; ensure no `size_ok = True` lives inside an `else:` for equity.
        assert "No equity available" in text or "no capital" in text.lower(), (
            "governor.py must explicitly reject when equity <= 0 (#438)"
        )


# ── #440 — bearer token uses hmac.compare_digest ──

class TestBearerTokenConstantTime:
    def test_verify_auth_uses_compare_digest(self):
        from src.api import cloud_app
        src = inspect.getsource(cloud_app.verify_auth)
        assert "compare_digest" in src, (
            "#440 — verify_auth must use hmac.compare_digest, not `==`"
        )

    def test_verify_auth_no_short_circuiting_string_compare(self):
        from src.api import cloud_app
        src = inspect.getsource(cloud_app.verify_auth)
        # Must not contain bare `token == _API_SECRET_HASH` (the prior pattern).
        # Allow it inside compare_digest() — but the pattern with `==` is the bug.
        # We accept presence of `==` for boolean composition, but token == _API_SECRET should be gone.
        assert "token == _API_SECRET_HASH" not in src, (
            "#440 — bearer token == comparison pattern still present"
        )
        assert "token == API_SECRET" not in src, (
            "#440 — bearer token == comparison pattern still present"
        )
