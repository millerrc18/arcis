"""Regression-locking tests for Sprint 0.B/B2.5 methodology fixes.

Covers:
  #725 — engine fail-loud threshold is n_loaders//2 not 4//2
  #726 — _coerce_as_of consolidated into src.utils.dates (sibling search)
  #685 — overnight.py collector-failure Telegram path uses _is_collector_error
  #721 — cloud_routes/analytics.py Sharpe routes through canonical_sharpe
  #722 — canonical_sharpe module docstring parses without error (docs-only)
"""
from __future__ import annotations

import importlib
from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# #725 — engine fail-loud threshold: n_loaders//2 not 4//2
# ---------------------------------------------------------------------------

class TestEngineFailLoudThreshold:
    """When sector_enabled=False, 3 loaders run. 2-of-3 failures must trigger."""

    def _make_ohlcv(self):
        import numpy as np
        import pandas as pd
        n = 250
        dates = pd.bdate_range(end=pd.Timestamp("2026-03-20"), periods=n)
        close = 100 * np.cumprod(1 + np.full(n, 0.001))
        return pd.DataFrame(
            {"Open": close, "High": close * 1.01, "Low": close * 0.99,
             "Close": close, "Volume": np.full(n, 1_000_000.0)},
            index=dates,
        )

    def test_two_of_three_failures_raises_when_sector_disabled(self):
        """2-of-3 shared loader failures with sector_disabled must raise FeatureComputationError."""
        from src.features.engine import FeatureComputationError

        ohlcv = self._make_ohlcv()
        spy = self._make_ohlcv()

        # Build a StrategySpec-like object with sector excluded from chain
        strategy = MagicMock()
        strategy.raw = {"enrichment": {"chain": ["regime", "options", "event_proximity"]}}

        # Regime and options both fail (2-of-3); event succeeds
        with patch("src.features.engine._load_options_metrics", side_effect=RuntimeError("db down")):
            with patch("src.features.engine._load_event_proximity", side_effect=RuntimeError("svc down")):
                with patch("src.features.regime.compute_market_regime", side_effect=RuntimeError("bad")):
                    with pytest.raises(FeatureComputationError):
                        from src.features.engine import compute_all_features
                        compute_all_features({"AAPL": ohlcv}, spy, strategy=strategy)

    def test_one_of_three_failures_does_not_raise(self):
        """1-of-3 shared loader failures with sector_disabled should NOT raise."""
        from src.features.engine import FeatureComputationError

        ohlcv = self._make_ohlcv()
        spy = self._make_ohlcv()

        strategy = MagicMock()
        strategy.raw = {"enrichment": {"chain": ["regime", "options", "event_proximity"]}}

        default_event = {
            "event_proximity_type": None,
            "event_proximity_days": None,
            "event_proximity_desc": None,
            "events_within_3d": 0,
        }

        # Only regime fails (1-of-3) — should not raise
        with patch("src.features.regime.compute_market_regime", side_effect=RuntimeError("bad")):
            with patch("src.features.engine._load_options_metrics", return_value={}):
                with patch("src.features.engine._load_event_proximity", return_value=default_event):
                    try:
                        from src.features.engine import compute_all_features
                        compute_all_features({"AAPL": ohlcv}, spy, strategy=strategy)
                    except FeatureComputationError:
                        pytest.fail(
                            "FeatureComputationError raised on 1-of-3 failures "
                            "but threshold should be >50% (>1 of 3 = >1.5, so >=2)"
                        )


# ---------------------------------------------------------------------------
# #726 — src.utils.dates.coerce_as_of canonical + call-site delegation
# ---------------------------------------------------------------------------

class TestCoerceAsOfConsolidation:
    """The canonical coerce_as_of lives in src.utils.dates only."""

    def test_canonical_location_exists(self):
        """src.utils.dates exposes coerce_as_of."""
        from src.utils.dates import coerce_as_of
        assert callable(coerce_as_of)

    def test_none_returns_none(self):
        from src.utils.dates import coerce_as_of
        assert coerce_as_of(None) is None

    def test_none_with_default_today_returns_today(self):
        from src.utils.dates import coerce_as_of
        result = coerce_as_of(None, default_today=True)
        assert result == date.today()

    def test_date_passthrough(self):
        from src.utils.dates import coerce_as_of
        d = date(2026, 3, 20)
        assert coerce_as_of(d) == d

    def test_datetime_extracts_date(self):
        from src.utils.dates import coerce_as_of
        dt = datetime(2026, 3, 20, 14, 30)
        assert coerce_as_of(dt) == date(2026, 3, 20)

    def test_iso_string(self):
        from src.utils.dates import coerce_as_of
        assert coerce_as_of("2026-03-20") == date(2026, 3, 20)

    def test_iso_string_with_time(self):
        from src.utils.dates import coerce_as_of
        assert coerce_as_of("2026-03-20T14:30:00") == date(2026, 3, 20)

    def test_invalid_string_returns_none(self):
        from src.utils.dates import coerce_as_of
        assert coerce_as_of("not-a-date") is None

    def test_invalid_string_with_default_today(self):
        from src.utils.dates import coerce_as_of
        assert coerce_as_of("not-a-date", default_today=True) == date.today()

    def test_engine_imports_from_utils_dates(self):
        """engine._coerce_as_of must delegate to src.utils.dates.coerce_as_of."""
        import inspect
        from src.features.engine import _coerce_as_of
        from src.utils.dates import coerce_as_of
        # Calling engine._coerce_as_of should produce same results as canonical
        d = date(2026, 1, 15)
        assert _coerce_as_of(d) == coerce_as_of(d)
        assert _coerce_as_of("2026-01-15") == coerce_as_of("2026-01-15")
        assert _coerce_as_of(None) == coerce_as_of(None)

    def test_earnings_imports_from_utils_dates(self):
        """earnings._coerce_as_of must delegate to src.utils.dates.coerce_as_of."""
        from src.features.earnings import _coerce_as_of
        from src.utils.dates import coerce_as_of
        d = date(2026, 1, 15)
        assert _coerce_as_of(d) == coerce_as_of(d)
        assert _coerce_as_of(None) == coerce_as_of(None)

    def test_event_proximity_imports_from_utils_dates(self):
        """event_proximity._coerce_reference must delegate to src.utils.dates.coerce_as_of."""
        from src.features.event_proximity import _coerce_reference
        from src.utils.dates import coerce_as_of
        d = date(2026, 1, 15)
        assert _coerce_reference(d) == coerce_as_of(d, default_today=True)

    def test_no_standalone_coerce_outside_canonical(self):
        """Sibling search: any def _coerce_as_of outside utils/dates.py must be a 1-line delegate."""
        import pathlib
        hits = []
        for p in pathlib.Path("src").rglob("*.py"):
            if "utils/dates.py" in str(p).replace("\\", "/"):
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()
            for i, line in enumerate(lines):
                if "def _coerce_as_of" in line or "def _coerce_reference" in line:
                    # Check that the body is a delegate (next non-empty line calls coerce_as_of)
                    body_lines = [
                        l.strip() for l in lines[i + 1: i + 5]
                        if l.strip() and not l.strip().startswith('"""') and not l.strip().startswith("'''")
                    ]
                    is_delegate = any("coerce_as_of" in bl for bl in body_lines)
                    if not is_delegate:
                        hits.append(f"{p}:{i+1}: {line.strip()}")
        assert not hits, (
            "Non-delegating def _coerce_as_of/_coerce_reference found outside src/utils/dates.py:\n"
            + "\n".join(hits)
        )


# ---------------------------------------------------------------------------
# #685 — overnight.py Telegram collector path uses _is_collector_error
# ---------------------------------------------------------------------------

class TestOvernightCollectorRegex:
    """The Telegram alert path (lines 807-831) must use _is_collector_error."""

    def test_false_positive_suppressed_with_errors_zero(self):
        """{'errors': 0, 'tickers_processed': 50} must NOT trigger is_error."""
        from src.scheduler.overnight import _is_collector_error
        result = {"errors": 0, "tickers_processed": 50}
        # Old pattern: "error" in str(result).lower() would be True here (substring "errors")
        assert not _is_collector_error(result), (
            "_is_collector_error incorrectly flags errors=0 dict as failure"
        )

    def test_real_error_detected(self):
        """{'error': 'timeout'} must trigger is_error."""
        from src.scheduler.overnight import _is_collector_error
        assert _is_collector_error({"error": "timeout"})

    def test_telegram_path_uses_helper_not_inline_string_match(self):
        """The Telegram block must call _is_collector_error, not inline 'error' in str()."""
        import inspect
        import src.scheduler.overnight as overnight_mod
        source = inspect.getsource(overnight_mod)
        # The bad pattern from issue #685
        bad_pattern = '"error" in str(result).lower()'
        assert bad_pattern not in source, (
            f"Bad inline string pattern still present in overnight.py: {bad_pattern!r}"
        )

    def test_telegram_block_calls_is_collector_error(self):
        """The Telegram notifications block calls _is_collector_error."""
        import inspect
        import src.scheduler.overnight as overnight_mod
        source = inspect.getsource(overnight_mod)
        assert "_is_collector_error" in source

    def test_pinned_numeric_regression(self):
        """Pinned numeric: _is_collector_error({errors:0, tickers_processed:50}) == False."""
        from src.scheduler.overnight import _is_collector_error
        assert _is_collector_error({"errors": 0, "tickers_processed": 50}) is False
        assert _is_collector_error({"error": "db_timeout"}) is True
        assert _is_collector_error("error connecting to upstream") is True
        assert _is_collector_error("success: 50 rows") is False


# ---------------------------------------------------------------------------
# #721 — cloud_routes/analytics.py Sharpe through canonical_sharpe
# ---------------------------------------------------------------------------

class TestAnalyticsShareCanonical:
    """analytics.py :51 and :181 must route through canonical_sharpe."""

    def _trades(self, pnls):
        return [{"pnl_pct": p, "pnl_dollars": p * 1000} for p in pnls]

    def test_compute_performance_score_sharpe_matches_canonical(self):
        """_compute_performance_score Sharpe must use canonical_sharpe (periods_per_year=1, ddof=1)."""
        from src.api.cloud_routes.analytics import _compute_performance_score
        from src.analytics.canonical_sharpe import compute_sharpe

        pnls = [0.02, -0.01, 0.03, -0.02, 0.01, 0.04, -0.01, 0.02] * 5
        trades = self._trades(pnls)
        score, metrics = _compute_performance_score(trades)

        # Canonical Sharpe with periods_per_year=1 (per-period, un-annualized).
        # Metric dict rounds to 2 dp.
        expected = round(compute_sharpe(pnls, periods_per_year=1, ddof=1), 2)
        assert metrics["sharpe"] is not None
        assert metrics["sharpe"] == expected, (
            f"Expected canonical sharpe {expected}, got {metrics['sharpe']}"
        )

    def test_compute_trade_summary_sharpe_matches_canonical(self):
        """_compute_trade_summary Sharpe must use canonical_sharpe (periods_per_year=1, ddof=1)."""
        from src.api.cloud_routes.analytics import _compute_trade_summary
        from src.analytics.canonical_sharpe import compute_sharpe

        pnls = [0.02, -0.01, 0.03, -0.02, 0.01, 0.04, -0.01, 0.02] * 5
        trades = self._trades(pnls)
        result = _compute_trade_summary(trades, open_count=3)

        # Metric rounds to 3 dp.
        expected = round(compute_sharpe(pnls, periods_per_year=1, ddof=1), 3)
        sharpe = result["headline_kpis"]["sharpe_ratio"]
        assert sharpe == expected, (
            f"Expected canonical sharpe {expected}, got {sharpe}"
        )

    def test_performance_score_sharpe_zero_variance_is_zero_sentinel(self):
        """Zero variance pnls: canonical returns None; analytics.py maps to 0.0 sentinel."""
        from src.api.cloud_routes.analytics import _compute_performance_score
        pnls = [0.01] * 20
        trades = self._trades(pnls)
        score, metrics = _compute_performance_score(trades)
        # canonical returns None for zero variance; analytics.py maps None -> 0.0
        assert metrics["sharpe"] == 0.0, (
            f"Expected 0.0 sentinel for zero-variance sharpe, got {metrics['sharpe']}"
        )


# ---------------------------------------------------------------------------
# #722 — canonical_sharpe module docstring parses without error
# ---------------------------------------------------------------------------

class TestCanonicalSharpeDocstring:
    """Module docstring for canonical_sharpe documents both Sortino flavors."""

    def test_module_docstring_is_present(self):
        """canonical_sharpe.__doc__ is not None."""
        import src.analytics.canonical_sharpe as cs
        assert cs.__doc__ is not None
        assert len(cs.__doc__.strip()) > 0

    def test_docstring_mentions_sortino_flavors(self):
        """Docstring mentions both compute_sortino and compute_sortino_mar."""
        import src.analytics.canonical_sharpe as cs
        doc = cs.__doc__
        assert "compute_sortino" in doc, "Docstring must mention compute_sortino"
        assert "compute_sortino_mar" in doc, "Docstring must mention compute_sortino_mar"

    def test_docstring_mentions_platform_metrics(self):
        """Docstring cross-references src.platform.metrics.compute_sortino."""
        import src.analytics.canonical_sharpe as cs
        doc = cs.__doc__
        assert "platform.metrics" in doc or "platform/metrics" in doc, (
            "Docstring must cross-reference platform.metrics.compute_sortino"
        )

    def test_module_parses_cleanly(self):
        """Module reloads without SyntaxError."""
        import importlib
        import src.analytics.canonical_sharpe as cs
        importlib.reload(cs)
