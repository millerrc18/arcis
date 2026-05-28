"""Regression-lock for v0.36.36 — F-7: FINRA short-volume silent-success on mass failure.

`collect_finra_short_volume` returned a success-shaped dict regardless of how
many SP100 tickers it matched (`short_volume_finra.py:185-192`). If the FINRA
CDN serves a malformed/empty/format-drifted file, the collector matches 0 SP100
tickers and `_is_collector_error` (overnight.py) treats it as success →
`short_volume_daily` silently goes stale → feature enrichment loses short-volume
context with no operator signal. Same anti-pattern as v0.36.26 (institutional /
filings / press_releases) and v0.36.25 (institutional_ownership 6-day staleness).

Fix: raise `CollectorPartialFailureError` when 0 SP100 tickers matched against a
healthy universe (>= `_MASS_FAILURE_MIN_UNIVERSE`). A genuinely tiny universe is
not alarmed (avoids false positives in degenerate test/config states).
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from src.data_collection.errors import CollectorPartialFailureError

_HEADER = "Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n"
# Rows for tickers NOT in the SP100 universe — simulates CDN format drift /
# a file whose symbols don't match (the silent-failure mode).
_NO_SP100_MATCH = _HEADER + "20260516|FOO|1000|50|5000|Q\n20260516|BAR|2000|0|9000|Q\n"
_WITH_MATCH = _HEADER + "20260516|AAPL|1000|50|5000|Q\n20260516|FOO|2000|0|9000|Q\n"


def _init_test_db(db_path: str) -> None:
    from tests.conftest import init_test_db
    init_test_db(db_path)


def _resp(text: str) -> MagicMock:
    m = MagicMock()
    m.status_code = 200
    m.text = text
    return m


def test_mass_failure_raises_on_zero_sp100_matched(tmp_path):
    """Healthy universe (>=10) + 0 matched tickers → CollectorPartialFailureError."""
    db_path = str(tmp_path / "t.db")
    _init_test_db(db_path)
    universe = [f"TKR{i}" for i in range(100)]  # 100 tickers, none == FOO/BAR
    with patch("src.data_collection.short_volume_finra.retry_with_backoff", return_value=_resp(_NO_SP100_MATCH)), \
         patch("src.data_collection.short_volume_finra.get_sp100_universe", return_value=universe):
        from src.data_collection.short_volume_finra import collect_finra_short_volume
        with pytest.raises(CollectorPartialFailureError):
            collect_finra_short_volume(target_date=date(2026, 5, 16), db_path=db_path)


def test_no_raise_when_some_tickers_matched(tmp_path):
    """Partial/normal collection (>=1 match) returns success — not a mass failure."""
    db_path = str(tmp_path / "t.db")
    _init_test_db(db_path)
    with patch("src.data_collection.short_volume_finra.retry_with_backoff", return_value=_resp(_WITH_MATCH)), \
         patch("src.data_collection.short_volume_finra.get_sp100_universe", return_value=["AAPL", "MSFT"]):
        from src.data_collection.short_volume_finra import collect_finra_short_volume
        result = collect_finra_short_volume(target_date=date(2026, 5, 16), db_path=db_path)
    assert result.primary_count == 1
    assert result.collector_name == "short_volume_finra"


def test_no_raise_when_universe_too_small(tmp_path):
    """A degenerate tiny universe (<10) is NOT alarmed even at 0 matches —
    avoids false positives distinct from a real CDN mass failure."""
    db_path = str(tmp_path / "t.db")
    _init_test_db(db_path)
    with patch("src.data_collection.short_volume_finra.retry_with_backoff", return_value=_resp(_NO_SP100_MATCH)), \
         patch("src.data_collection.short_volume_finra.get_sp100_universe", return_value=["AAPL", "MSFT"]):
        from src.data_collection.short_volume_finra import collect_finra_short_volume
        result = collect_finra_short_volume(target_date=date(2026, 5, 16), db_path=db_path)
    assert result.primary_count == 0  # no match, but universe too small to alarm
