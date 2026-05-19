"""Regression-lock for v0.36.25 Finnhub collector fixes.

Two collectors broken-on-PG-cutover (silently since 2026-05-13):

1. `institutional_ownership_collector.py` hit `/stock/institutional-ownership`
   which returns HTTP 302 → 404 (deprecated/never-existed endpoint).
   The correct endpoint is `/stock/ownership` — confirmed live with the
   production API key, returns `{"ownership":[...], "symbol":"AAPL"}` with
   ~8000 holder records per ticker. Fields (`share`, `filingDate`, `name`,
   `change`) match the existing `_aggregate_holders` parser unchanged.

2. `filings_sentiment_collector.py` hit `/stock/filings-sentiment` which
   returns HTTP 302 → 200 with body `{}`. No working alternative URL
   found (probed `/stock/sentiment` (404), `/news-sentiment` (returns
   news sentiment, not filings)). Until a working endpoint is found,
   gate it off via `_FEATURE_MATRIX` to stop wasted API calls.

These regression-locks pin both contracts so the bugs can't silently
re-introduce themselves.
"""
from __future__ import annotations

from src.data_collection import institutional_ownership_collector
from src.data_enrichment.finnhub_plan import _FEATURE_MATRIX


def test_institutional_ownership_uses_stock_ownership_endpoint():
    """The collector module must reference `/stock/ownership`, not the
    deprecated `/stock/institutional-ownership` URL.

    Pre-v0.36.25 the latter returned 302→404 with HTML body, then
    `resp.json()` died parsing `<` with `Expecting value: line 1 column 1`.
    """
    import inspect
    source = inspect.getsource(institutional_ownership_collector)
    assert "/stock/ownership" in source, (
        "institutional_ownership_collector must call /stock/ownership "
        "(the correct Finnhub endpoint). See v0.36.25 fix."
    )
    # Active code should NOT contain the deprecated URL.
    # Allow it in docstrings/comments for historical context — check active
    # f-strings only, line-by-line skipping comments and docstrings.
    in_triple_quote = False
    bad_lines: list[int] = []
    for i, line in enumerate(source.splitlines(), start=1):
        stripped = line.lstrip()
        triple_count = stripped.count('"""') + stripped.count("'''")
        if stripped.startswith("#"):
            if triple_count % 2 == 1:
                in_triple_quote = not in_triple_quote
            continue
        if in_triple_quote:
            if triple_count % 2 == 1:
                in_triple_quote = not in_triple_quote
            continue
        if triple_count % 2 == 1:
            in_triple_quote = not in_triple_quote
            continue
        if "/stock/institutional-ownership" in stripped:
            bad_lines.append(i)
    assert not bad_lines, (
        f"Pre-fix `/stock/institutional-ownership` URL found in ACTIVE CODE "
        f"at line(s) {bad_lines}. The endpoint returns HTTP 302→404 and has "
        "been silently broken since 2026-05-13. Use `/stock/ownership` instead."
    )


def test_filings_sentiment_is_not_in_fundamental_1_matrix():
    """`filings_sentiment` must NOT be in the fundamental-1 plan capability
    set until a working Finnhub endpoint is confirmed.

    `/stock/filings-sentiment` returns body `{}` (no data) for every ticker.
    Until either Finnhub restores the endpoint or we find the new path,
    plan-gate it off to stop wasted ratelimit quota.

    To re-enable: probe the correct URL, update
    `filings_sentiment_collector._fetch_finnhub_filings_sentiment`, then
    re-add `filings_sentiment` to the `fundamental-1` set in
    `_FEATURE_MATRIX`.
    """
    assert "filings_sentiment" not in _FEATURE_MATRIX["fundamental-1"], (
        "`filings_sentiment` is in _FEATURE_MATRIX['fundamental-1'] but the "
        "Finnhub /stock/filings-sentiment endpoint returns body `{}` and is "
        "broken. v0.36.25 removed it from the matrix to stop wasted API calls. "
        "Re-enable only after confirming a working endpoint."
    )


def test_institutional_ownership_remains_in_fundamental_1_matrix():
    """Sanity: institutional_ownership SHOULD remain in the plan matrix —
    only its URL was wrong, the plan-gate capability remains valid."""
    assert "institutional_ownership" in _FEATURE_MATRIX["fundamental-1"], (
        "institutional_ownership must remain in _FEATURE_MATRIX['fundamental-1'] — "
        "the v0.36.25 fix was a URL change, not a plan-gate change. "
        "If you intended to gate it off, document why."
    )
