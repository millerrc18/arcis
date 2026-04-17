# Sprint: Equity Research Desk MVP (Phase 2 Foundation)

**Authority:**
- Deep research report: `docs/research/deep-research/research-desk-design-report.md` (pending commit)
- Design decision: full 10-task MVP, 14-hour weekend build
- SD#41 REVISED foundation: excess-Sharpe is primary metric from day 1
- Second Alpaca paper account: ALREADY CREATED

**Branch:** `feat/research-desk-mvp`
**Tag on merge:** v0.24.0
**Effort:** ~14 hours across Saturday-Sunday April 19-20

---

## Goal

Stand up a second trading desk that:
1. Runs on a **separate Alpaca paper account** with clean attribution
2. Uses **filing-anchored earnings drift** on 14-28 day holds (Lazy Prices + ML-SUE) — not another flavor of mean reversion
3. Uses the 8B LLM as a **structured extraction engine** (10-K YoY diff + earnings-call tone + news bias), never as a synthesizer or target-price generator
4. Instruments **excess-Sharpe vs SPY** on every trade from trade #1
5. Coexists with the existing Equity Swing Desk without breaking it

**The skinny functional path:** one desk-tagged trade routed to the second paper account with a real SPY-excess number attached, end-to-end through the full pipeline.

---

## Strategy Parameters (from deep research)

| Parameter | Value | Source |
|---|---|---|
| Alpha source | Lazy Prices YoY filing diff + ML-SUE revived PEAD | Cohen-Malloy-Nguyen 2020, Kaczmarek-Zaremba 2025 |
| Universe (MVP) | S&P 100 (same as swing) — sp500 module needs creation; Phase 2a follow-up | Deep research §2 preferred sp500 |
| Hold period | 14-28 days, target 21 | Cohen-Malloy-Nguyen drift window |
| Max concurrent positions | 5 | Deep research §2 |
| Position size | 10-15% of research desk equity | Deep research §2 |
| Stop | entry − 3.0 × ATR(14d), floor 5%, cap 12% | ATR-based |
| Target | entry + 6.0 × ATR(14d), floor 10%, cap 25% | ATR-based |
| Timeout | 25 days force-close | Deep research §2 |
| Trailing activation | +4 × ATR (chandelier at high − 2.5 × ATR) | Deep research §2 |
| ATR/price filter | 1.0% ≤ ATR/price ≤ 6.0% | Volatility filter |
| Benchmark | SPY total return over exact hold window | SD#41 D1 instrumentation |

---

## Pre-Flight Checks (run these FIRST, do not skip)

```bash
# 1. Confirm pytest baseline passes before any changes
cd C:\arcis\halcyon-lab
python -m pytest tests/ -x --tb=short -q 2>&1 | tail -5
# Record the pass count here ↓ (baseline ~544 test functions; pytest collects many more as parameterized)

# 2. Confirm shadow_trades has 85 rows (or whatever current count is)
python -c "from src.config import DB_PATH; import sqlite3; c = sqlite3.connect(DB_PATH); print('shadow_trades total:', c.execute('SELECT COUNT(*) FROM shadow_trades').fetchone()[0])"

# 3. Confirm second Alpaca paper account env vars are set
python -c "import os; print('RESEARCH key:', bool(os.environ.get('ALPACA_RESEARCH_API_KEY'))); print('RESEARCH secret:', bool(os.environ.get('ALPACA_RESEARCH_API_SECRET')))"
# Both must print True. If not, STOP and add to .env first.

# 4. Confirm EDGAR collector has recent data (at least 1 filing in last 30 days)
python -c "from src.config import DB_PATH; import sqlite3; c = sqlite3.connect(DB_PATH); print('Recent EDGAR filings:', c.execute(\"SELECT COUNT(*) FROM edgar_filings WHERE filing_date > date('now', '-30 days')\").fetchone()[0])"

# 5. Back up the DB before migration
copy C:\arcis\data\ai_research_desk.sqlite3 C:\arcis\data\ai_research_desk.sqlite3.pre-research-desk.bak
```

---

## Task List

Each task has: file paths, function signatures, tests, acceptance criteria. Do NOT combine tasks. Commit after each one.

---

### Task 1 — Config structure for dual-desk architecture (1.0h)

**Files:**
- `config/settings.example.yaml` (add new section)
- `config/settings.local.yaml` (user copies values; do not commit)
- `src/config.py` (add `load_desk_config`)

**Add top-level section to settings YAML:**

```yaml
# ─── DESKS (SD#41 REVISED Phase 2 — Equity Research Desk) ──────────────
# Each desk has independent Alpaca credentials, risk parameters, and
# scan cadence. Desk 'swing' is the default; all existing trades are
# tagged desk='swing' on migration. Desk 'research' is new.
desks:
  swing:
    enabled: true
    alpaca_key_env: "ALPACA_API_KEY"          # existing paper account
    alpaca_secret_env: "ALPACA_API_SECRET"
    max_position_pct: 0.10                    # 10% of desk equity per position
    max_concurrent: 10
    max_hold_days: 8
    stop_atr_mult: 2.0
    target_atr_mult: 3.0
    starting_capital: 100000
  research:
    enabled: false                            # START DISABLED — turn on after MVP passes
    alpaca_key_env: "ALPACA_RESEARCH_API_KEY"
    alpaca_secret_env: "ALPACA_RESEARCH_API_SECRET"
    max_position_pct: 0.15                    # 15% — fewer concurrent so bigger each
    max_concurrent: 5
    min_hold_days: 14
    max_hold_days: 25
    stop_atr_mult: 3.0
    target_atr_mult: 6.0
    atr_pct_min: 0.010                        # 1.0% ATR/price floor
    atr_pct_max: 0.060                        # 6.0% ATR/price cap
    starting_capital: 100000
    universe: "sp100"                         # 'sp100' (MVP) or 'sp500' (Phase 2a)
    scan_cadence_seconds: 600                 # 10 min (research ticks slower than swing)
    llm_timeout_seconds: 6                    # hard timeout on grammar-constrained JSON
    cosine_quartile: 25                       # bottom q25 for Lazy Prices change signal
    sue_decile: 9                             # top decile for ML-SUE predicted return
```

**Add to `src/config.py`:**

```python
def load_desk_config(desk: str) -> dict:
    """Load configuration for a specific desk.

    Raises KeyError if desk not in config. Reads env var values for
    the alpaca_key_env/alpaca_secret_env string references and inlines
    the resolved credentials as 'alpaca_api_key'/'alpaca_api_secret'.
    """
    cfg = load_config()
    desks = cfg.get("desks", {})
    if desk not in desks:
        raise KeyError(f"Desk '{desk}' not in config. Available: {list(desks.keys())}")
    desk_cfg = dict(desks[desk])  # copy
    key_env = desk_cfg.get("alpaca_key_env", "")
    secret_env = desk_cfg.get("alpaca_secret_env", "")
    import os
    desk_cfg["alpaca_api_key"] = os.environ.get(key_env, "")
    desk_cfg["alpaca_api_secret"] = os.environ.get(secret_env, "")
    return desk_cfg
```

**Tests:** `tests/test_desk_config.py`

```python
def test_load_desk_config_swing(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "swing_key_test")
    monkeypatch.setenv("ALPACA_API_SECRET", "swing_secret_test")
    from src.config import load_desk_config
    cfg = load_desk_config("swing")
    assert cfg["alpaca_api_key"] == "swing_key_test"
    assert cfg["max_hold_days"] == 8

def test_load_desk_config_research(monkeypatch):
    monkeypatch.setenv("ALPACA_RESEARCH_API_KEY", "research_key_test")
    monkeypatch.setenv("ALPACA_RESEARCH_API_SECRET", "research_secret_test")
    from src.config import load_desk_config
    cfg = load_desk_config("research")
    assert cfg["alpaca_api_key"] == "research_key_test"
    assert cfg["max_hold_days"] == 25
    assert cfg["max_concurrent"] == 5

def test_load_desk_config_unknown_raises():
    from src.config import load_desk_config
    import pytest
    with pytest.raises(KeyError):
        load_desk_config("options")
```

**Acceptance:** All three tests pass. `research` stays `enabled: false` until the full MVP is validated at end of sprint.

**Constraint:** Do NOT break existing top-level `alpaca:` section. The new `desks:` section is additive. Existing `_get_alpaca_config()` in `alpaca_adapter.py` continues to work for backward compat through this sprint.

---

### Task 2 — Schema: add `desk` + research columns to shadow_trades (0.5h)

**File:** `src/schema/registry.py` — add to `shadow_trades` ColumnDef list

Add these columns **after** the existing `excess_return` / `realized_sector` columns (from D1):

```python
# SD#41 REVISED Phase 2 — Equity Research Desk tagging
ColumnDef("desk", "TEXT", default="swing",
          description="Desk tag: 'swing' (Phase 1 pullback-in-uptrend) or "
                      "'research' (Phase 2 Lazy Prices + ML-SUE). Defaults "
                      "to 'swing' for backward compat with pre-Phase-2 rows."),
ColumnDef("research_thesis", "TEXT",
          description="LLM-generated structured JSON research note (research "
                      "desk only). Schema in src/llm/research_prompt.py."),
ColumnDef("filing_anchor_accession", "TEXT",
          description="SEC EDGAR accession number that anchored the trade "
                      "(research desk only, filing-triggered entries)."),
```

**Index:** Add an index on `desk` in the `shadow_trades` IndexDef list:

```python
IndexDef("idx_shadow_trades_desk", ["desk"]),
```

**Migration behavior:** `ensure_columns` runs on watch loop startup and adds missing columns idempotently. Existing 85 rows get `desk='swing'` via the DEFAULT clause. No explicit migration script needed.

**Render sync coercion:** No change to `_REAL_COLUMNS` — all three new columns are TEXT.

**Tests:** `tests/test_schema_research_desk.py`

```python
def test_shadow_trades_has_desk_column():
    from src.schema.registry import TABLES
    shadow = TABLES["shadow_trades"]
    col_names = {c.name for c in shadow.columns}
    assert "desk" in col_names
    assert "research_thesis" in col_names
    assert "filing_anchor_accession" in col_names

def test_desk_defaults_to_swing():
    from src.schema.registry import TABLES
    shadow = TABLES["shadow_trades"]
    desk_col = next(c for c in shadow.columns if c.name == "desk")
    assert desk_col.default == "swing"

def test_ensure_columns_adds_desk_to_existing_db(tmp_path):
    """Simulate: DB exists without desk column, ensure_columns adds it."""
    import sqlite3
    from src.schema.sqlite import ensure_columns
    db = str(tmp_path / "migrate_test.db")
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE shadow_trades (trade_id TEXT PRIMARY KEY, ticker TEXT)")
    conn.close()
    ensure_columns(db)
    conn = sqlite3.connect(db)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(shadow_trades)")]
    assert "desk" in cols
```

**Acceptance:** Run `python -c "from src.schema.sqlite import ensure_columns; from src.config import DB_PATH; ensure_columns(DB_PATH)"` locally. Verify all 85 existing trades have `desk='swing'`:

```bash
python -c "from src.config import DB_PATH; import sqlite3; c = sqlite3.connect(DB_PATH); print(c.execute('SELECT desk, COUNT(*) FROM shadow_trades GROUP BY desk').fetchall())"
# Expected: [('swing', 85)]
```

---

### Task 3 — Alpaca dual-client factory (1.0h)

**File:** `src/shadow_trading/alpaca_clients.py` (new)

```python
"""Per-desk Alpaca TradingClient factory.

Called by: shadow_trading.executor, services.scan_service, services.research_scan_service
Calls: alpaca.trading.client
Owns tables: none
Config keys: desks.{swing,research}.{alpaca_key_env, alpaca_secret_env}
Tests: tests/test_alpaca_clients.py

SD#41 REVISED Phase 2 — dual-desk support. Each desk has its own
Alpaca paper account with distinct credentials. Clients are cached per
desk; calling get_client('swing') twice returns the same TradingClient
instance. Every client is asserted paper=True and the base_url is
checked for 'paper'.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from src.config import load_desk_config

logger = logging.getLogger(__name__)

_CLIENT_CACHE: dict[str, Any] = {}
_CACHE_LOCK = threading.Lock()


class DeskCredentialsError(RuntimeError):
    """Raised when a desk's Alpaca credentials are missing or invalid."""


def get_client(desk: str):
    """Return a cached TradingClient for the given desk.

    Raises DeskCredentialsError if the desk's env vars are not set.
    Tags the returned client with a `desk_tag` attribute for sanity-check
    assertions in the executor ('an order tagged swing never hits the
    research client').
    """
    with _CACHE_LOCK:
        if desk in _CLIENT_CACHE:
            return _CLIENT_CACHE[desk]
        cfg = load_desk_config(desk)
        key = cfg.get("alpaca_api_key", "")
        secret = cfg.get("alpaca_api_secret", "")
        if not key or not secret:
            raise DeskCredentialsError(
                f"Desk '{desk}' missing Alpaca credentials. "
                f"Check env vars {cfg.get('alpaca_key_env')} and "
                f"{cfg.get('alpaca_secret_env')}."
            )
        from alpaca.trading.client import TradingClient
        client = TradingClient(api_key=key, secret_key=secret, paper=True)
        # Attach the desk tag as a sanity-check attribute.
        client.desk_tag = desk
        _CLIENT_CACHE[desk] = client
        logger.info("[ALPACA] Initialized client for desk='%s'", desk)
        return client


def verify_accounts_distinct() -> dict:
    """Sanity check: both desks resolve to distinct Alpaca account numbers.

    Returns dict with account_number per desk. Used at startup to catch
    the 'both desks accidentally pointing at the same account' bug.
    Fail-fast: raises DeskCredentialsError if account numbers match.
    """
    swing_acct = get_client("swing").get_account().account_number
    research_acct = get_client("research").get_account().account_number
    if swing_acct == research_acct:
        raise DeskCredentialsError(
            f"SAFETY: swing and research desks resolve to SAME account "
            f"number {swing_acct}. Check env var values."
        )
    return {"swing": swing_acct, "research": research_acct}


def clear_cache_for_testing():
    """Clear the client cache. For test isolation only."""
    with _CACHE_LOCK:
        _CLIENT_CACHE.clear()
```

**Tests:** `tests/test_alpaca_clients.py`

```python
from unittest.mock import MagicMock, patch

import pytest

from src.shadow_trading.alpaca_clients import (
    DeskCredentialsError, clear_cache_for_testing, get_client,
    verify_accounts_distinct,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_cache_for_testing()
    yield
    clear_cache_for_testing()


def test_get_client_raises_on_missing_credentials(monkeypatch):
    monkeypatch.delenv("ALPACA_RESEARCH_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_RESEARCH_API_SECRET", raising=False)
    with pytest.raises(DeskCredentialsError):
        get_client("research")


def test_get_client_caches_instance(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "fake_key")
    monkeypatch.setenv("ALPACA_API_SECRET", "fake_secret")
    with patch("alpaca.trading.client.TradingClient") as mock_tc:
        mock_tc.return_value = MagicMock(desk_tag=None)
        c1 = get_client("swing")
        c2 = get_client("swing")
    assert c1 is c2
    assert mock_tc.call_count == 1


def test_get_client_tags_with_desk(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "fake")
    monkeypatch.setenv("ALPACA_API_SECRET", "fake")
    with patch("alpaca.trading.client.TradingClient") as mock_tc:
        mock_tc.return_value = MagicMock(desk_tag=None)
        client = get_client("swing")
    assert client.desk_tag == "swing"


def test_verify_accounts_distinct_raises_on_same_account(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "k1")
    monkeypatch.setenv("ALPACA_API_SECRET", "s1")
    monkeypatch.setenv("ALPACA_RESEARCH_API_KEY", "k2")
    monkeypatch.setenv("ALPACA_RESEARCH_API_SECRET", "s2")
    with patch("alpaca.trading.client.TradingClient") as mock_tc:
        m = MagicMock()
        m.get_account.return_value = MagicMock(account_number="ACCT-1234")
        mock_tc.return_value = m
        with pytest.raises(DeskCredentialsError, match="SAME account"):
            verify_accounts_distinct()
```

**Acceptance:** All 4 tests pass. Manually run `python -c "from src.shadow_trading.alpaca_clients import verify_accounts_distinct; print(verify_accounts_distinct())"` once credentials are in `.env` — must print two distinct account numbers.

---

### Task 4 — Research scanner: Lazy Prices + ML-SUE filter (2.5h)

**Files:**
- `src/services/research_scan_service.py` (new — mirrors `mr_scan_service.py` structure)
- `src/features/lazy_prices.py` (new — cosine similarity on YoY 10-K/10-Q sections)
- `src/features/ml_sue.py` (new — elastic-net over 12Q SUE + analyst revisions)
- `src/data_collection/edgar_collector.py` (EDIT — add item_1a Risk Factors extraction)

**EDGAR collector fix (critical pre-requisite):**

Current `_parse_sections()` in `src/data_collection/edgar_collector.py` line 193 captures MD&A but NOT Risk Factors. Lazy Prices paper uses both.

Add to the 10-K pattern dict:

```python
"item_1a": r"(?i)item\s+1a[.\s]+risk\s+factors(.*?)(?=item\s+1b|item\s+2|\Z)",
```

Add to the 10-Q pattern dict (some 10-Qs include 1A updates):

```python
"item_1a": r"(?i)item\s+1a[.\s]+risk\s+factors(.*?)(?=item\s+2|item\s+3|\Z)",
```

**File `src/features/lazy_prices.py`:**

```python
"""Lazy Prices cosine similarity on YoY 10-K/10-Q section changes.

Called by: services.research_scan_service
Calls: none (reads edgar_filings)
Owns tables: none
Config keys: desks.research.cosine_quartile
Tests: tests/test_lazy_prices.py

Authority: Cohen, Malloy, Nguyen (JF 2020) — Lazy Prices.
YoY change in Risk Factors (item_1a) and MD&A (item_7 / item_2) is the
signal. Bottom quartile similarity = biggest textual change = candidate.
"""

from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
from collections import Counter

from src.config import DB_PATH

logger = logging.getLogger(__name__)


def _tokenize(text: str) -> list[str]:
    """Lowercase, split on non-alpha. Simple, fast, good enough for cosine."""
    return re.findall(r"[a-z]{3,}", (text or "").lower())


def _cosine(a: Counter, b: Counter) -> float:
    """Cosine similarity of two token counters. Returns 0.0 if either empty."""
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    dot = sum(a[w] * b[w] for w in common)
    mag_a = math.sqrt(sum(v * v for v in a.values()))
    mag_b = math.sqrt(sum(v * v for v in b.values()))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def cosine_vs_prior_year(
    ticker: str, current_accession: str, section_key: str,
    db_path: str = DB_PATH,
) -> float | None:
    """Compute cosine similarity between current filing's section and the
    same section from the same ticker's prior-year filing (same form type).

    Returns None if prior-year filing not found or section missing.
    """
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        current = conn.execute(
            "SELECT ticker, form_type, filing_date, sections_json "
            "FROM edgar_filings WHERE accession_number = ?",
            (current_accession,),
        ).fetchone()
        if not current:
            return None
        prior = conn.execute(
            "SELECT sections_json FROM edgar_filings "
            "WHERE ticker = ? AND form_type = ? "
            "AND filing_date < ? AND filing_date >= date(?, '-400 days') "
            "ORDER BY filing_date DESC LIMIT 1",
            (ticker, current["form_type"], current["filing_date"], current["filing_date"]),
        ).fetchone()
    if not prior:
        return None
    try:
        cur_sections = json.loads(current["sections_json"] or "{}")
        prior_sections = json.loads(prior["sections_json"] or "{}")
    except json.JSONDecodeError:
        return None
    cur_text = cur_sections.get(section_key, "")
    prior_text = prior_sections.get(section_key, "")
    if not cur_text or not prior_text:
        return None
    return _cosine(Counter(_tokenize(cur_text)), Counter(_tokenize(prior_text)))


def recent_filings_with_cosine(
    days_back: int = 5, db_path: str = DB_PATH,
) -> list[dict]:
    """Return 10-K/10-Q filings from the last N days with YoY cosine
    similarity for Risk Factors (item_1a) and MD&A.

    Used as the event-driven entry trigger for the research desk.
    """
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT ticker, accession_number, form_type, filing_date "
            "FROM edgar_filings "
            "WHERE form_type IN ('10-K', '10-Q') "
            "AND filing_date >= date('now', ?) "
            "ORDER BY filing_date DESC",
            (f"-{days_back} days",),
        ).fetchall()
    results = []
    for r in rows:
        # MD&A section key differs per form
        mdna_key = "item_7" if r["form_type"] == "10-K" else "item_2"
        results.append({
            "ticker": r["ticker"],
            "accession": r["accession_number"],
            "form_type": r["form_type"],
            "filing_date": r["filing_date"],
            "cosine_risk_factors": cosine_vs_prior_year(
                r["ticker"], r["accession_number"], "item_1a", db_path,
            ),
            "cosine_mdna": cosine_vs_prior_year(
                r["ticker"], r["accession_number"], mdna_key, db_path,
            ),
        })
    return results


def passes_lazy_prices_filter(
    cosine_risk_factors: float | None,
    cosine_mdna: float | None,
    cosine_quartile_threshold: float,
) -> bool:
    """True if EITHER section is in the bottom quartile (most changed).

    We don't require both to change — the paper's signal is ANY material
    YoY change. A filing with only Risk Factors rewritten still qualifies.
    """
    if cosine_risk_factors is not None and cosine_risk_factors < cosine_quartile_threshold:
        return True
    if cosine_mdna is not None and cosine_mdna < cosine_quartile_threshold:
        return True
    return False
```

**File `src/features/ml_sue.py`:**

```python
"""ML-SUE signal using 12-quarter SUE + analyst revisions.

Called by: services.research_scan_service
Calls: none (reads analyst_estimates)
Owns tables: none
Config keys: desks.research.sue_decile
Tests: tests/test_ml_sue.py

Authority: Kaczmarek & Zaremba (FRL 2025) "Beyond the Last Surprise" —
machine-learning use of SUE from prior 12 quarters nearly doubles PEAD
Sharpe, especially in large-caps where recent surprises are priced
quickly but older ones are ignored.

MVP: uses a simple standardized weighted-average of the last 12 SUE
values (weights: recent-quarter 2x, middle-quarters 1x, oldest 0.5x)
rather than a full elastic-net fit. Phase 2a will replace with real
elastic-net once 60+ research trades close.
"""

from __future__ import annotations

import logging
import sqlite3
import statistics

from src.config import DB_PATH

logger = logging.getLogger(__name__)


def compute_weighted_sue(ticker: str, db_path: str = DB_PATH) -> float | None:
    """Weighted average of the last 12 quarterly surprise_pct values.

    Returns None if fewer than 4 quarters of data exist.
    """
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT surprise_pct FROM analyst_estimates "
            "WHERE ticker = ? AND surprise_pct IS NOT NULL "
            "AND metric IN ('eps', 'revenue', 'netIncome') "
            "ORDER BY date DESC LIMIT 12",
            (ticker,),
        ).fetchall()
    sues = [float(r["surprise_pct"]) for r in rows if r["surprise_pct"] is not None]
    if len(sues) < 4:
        return None
    weights = [2.0, 2.0, 1.5, 1.5] + [1.0] * 6 + [0.5] * 2
    weights = weights[: len(sues)]
    wmean = sum(s * w for s, w in zip(sues, weights)) / sum(weights)
    return wmean


def recent_positive_earnings_tickers(
    days_back: int = 5, db_path: str = DB_PATH,
) -> list[str]:
    """Tickers that had an earnings announcement in the last N days with
    positive current-quarter SUE. Filters the ML-SUE candidate set.
    """
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT ticker FROM analyst_estimates "
            "WHERE date >= date('now', ?) "
            "AND surprise_pct > 0 "
            "AND metric = 'eps'",
            (f"-{days_back} days",),
        ).fetchall()
    return [r[0] for r in rows]


def compute_decile_threshold(
    universe: list[str], db_path: str = DB_PATH,
) -> float | None:
    """9th-decile cutoff of weighted-SUE across the universe. Tickers
    above this threshold are candidates.
    """
    values = [
        s for s in (compute_weighted_sue(t, db_path) for t in universe)
        if s is not None
    ]
    if len(values) < 20:
        return None
    return statistics.quantiles(values, n=10)[-1]  # 90th percentile


def passes_ml_sue_filter(
    ticker: str, universe: list[str], db_path: str = DB_PATH,
) -> tuple[bool, float | None]:
    """True if ticker is in top decile of weighted-SUE.

    Returns (passes, weighted_sue). weighted_sue is None if the ticker
    has insufficient history.
    """
    ticker_sue = compute_weighted_sue(ticker, db_path)
    if ticker_sue is None:
        return False, None
    threshold = compute_decile_threshold(universe, db_path)
    if threshold is None:
        return False, ticker_sue
    return ticker_sue >= threshold, ticker_sue
```

**File `src/services/research_scan_service.py`:**

```python
"""Equity Research Desk scanner — filing-anchored earnings drift.

Called by: scheduler.watch (via _run_research_scan)
Calls: features.lazy_prices, features.ml_sue, llm.research_prompt,
       shadow_trading.executor
Owns tables: none (delegates)
Config keys: desks.research.*
Tests: tests/test_research_scan_service.py

Authority:
  Cohen-Malloy-Nguyen 2020 (Lazy Prices)
  Kaczmarek-Zaremba 2025 (ML-SUE revival)
  SD#41 REVISED Phase 2

Runs at 10-minute cadence during market hours. Two entry triggers:
  1. Filing-change: 10-K/10-Q in last 5 days with YoY cosine in bottom quartile
  2. ML-SUE: ticker in top decile of weighted-SUE after earnings surprise

Either trigger qualifies the ticker for LLM review. The LLM must
produce a non-disqualifying research note (src/llm/research_prompt.py)
before an order fires.
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import DB_PATH, load_desk_config

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


def _get_universe(universe_tag: str) -> list[str]:
    """Load ticker universe. 'sp100' or 'sp500'."""
    if universe_tag == "sp500":
        try:
            from src.universe.sp500 import get_sp500_universe
            return get_sp500_universe()
        except ImportError:
            logger.warning("[RESEARCH] sp500 universe not available — falling back to sp100")
    from src.universe.sp100 import get_sp100_universe
    return get_sp100_universe()


def find_research_candidates(db_path: str = DB_PATH) -> list[dict]:
    """Find tickers that pass either Lazy Prices or ML-SUE filter.

    Returns list of dicts with ticker, trigger type, and evidence fields.
    Does NOT execute trades — that's the executor's job.
    """
    cfg = load_desk_config("research")
    if not cfg.get("enabled", False):
        return []

    from src.features.lazy_prices import (
        recent_filings_with_cosine, passes_lazy_prices_filter,
    )
    from src.features.ml_sue import (
        recent_positive_earnings_tickers, passes_ml_sue_filter,
    )

    universe = _get_universe(cfg.get("universe", "sp500"))
    universe_set = set(universe)
    # The quartile threshold is computed across the universe's recent cosines;
    # for MVP we use a fixed literal threshold from the config that the
    # operator tunes empirically. At q25 in S&P 500 Lazy Prices data, cosine
    # is typically 0.70-0.80; start at 0.75 and tune.
    quartile_threshold = 0.75  # TODO: compute from rolling distribution post-MVP

    candidates: list[dict] = []

    # Trigger 1: Lazy Prices
    for filing in recent_filings_with_cosine(days_back=5, db_path=db_path):
        if filing["ticker"] not in universe_set:
            continue
        if passes_lazy_prices_filter(
            filing["cosine_risk_factors"], filing["cosine_mdna"], quartile_threshold,
        ):
            candidates.append({
                "ticker": filing["ticker"],
                "trigger": "lazy_prices",
                "accession": filing["accession"],
                "cosine_risk_factors": filing["cosine_risk_factors"],
                "cosine_mdna": filing["cosine_mdna"],
                "form_type": filing["form_type"],
                "filing_date": filing["filing_date"],
            })

    # Trigger 2: ML-SUE
    earnings_tickers = set(recent_positive_earnings_tickers(
        days_back=5, db_path=db_path,
    ))
    for ticker in earnings_tickers & universe_set:
        passes, wsue = passes_ml_sue_filter(ticker, universe, db_path=db_path)
        if passes:
            candidates.append({
                "ticker": ticker,
                "trigger": "ml_sue",
                "weighted_sue": wsue,
            })

    return candidates


def run_research_scan(config: dict | None = None, dry_run: bool = False) -> dict:
    """Run the research desk scan. Called by watch loop every 10 min."""
    if config is None:
        from src.config import load_config
        config = load_config()

    desk_cfg = config.get("desks", {}).get("research", {})
    if not desk_cfg.get("enabled", False):
        logger.debug("[RESEARCH] Desk disabled in config")
        return {"status": "disabled", "candidates": 0, "trades_opened": 0}

    candidates = find_research_candidates()
    logger.info("[RESEARCH] Found %d candidates", len(candidates))

    trades_opened = 0
    if not dry_run and candidates:
        # LLM review + order placement delegated to T6 (executor + research_prompt).
        # For this task's scope we stop at candidate identification.
        # T8 wires the LLM, T6 wires the order submission.
        pass

    return {
        "status": "ok",
        "candidates": len(candidates),
        "trades_opened": trades_opened,
        "timestamp": datetime.now(ET).isoformat(),
    }
```

**Tests:** `tests/test_research_scan_service.py` + `tests/test_lazy_prices.py` + `tests/test_ml_sue.py`

Key tests:
- `test_cosine_computation_symmetric`: cosine(a, b) == cosine(b, a)
- `test_cosine_identical_texts_returns_1`: identical text → 1.0
- `test_cosine_completely_different_returns_0`: disjoint vocab → 0.0
- `test_cosine_returns_none_when_prior_missing`: no prior-year filing → None
- `test_passes_lazy_prices_filter_either_section`: one section below threshold passes
- `test_weighted_sue_requires_4_quarters`: fewer than 4 → None
- `test_weighted_sue_weights_recent_higher`: constructed series, recent quarters dominate
- `test_find_research_candidates_empty_when_desk_disabled`
- `test_find_research_candidates_lazy_prices_trigger`: seeded DB, verify detection
- `test_run_research_scan_returns_disabled_when_flag_off`

**Acceptance:** All tests pass. Edgar collector with item_1a extraction works — verify by running the collector manually on a test ticker and inspecting `sections_json` contains `item_1a`.

---

### Task 5 — Risk governor: per-desk instantiation (1.0h)

**File:** `src/risk/governor.py` (EDIT)

Currently `RiskGovernor` is a class that reads config. Modify the existing class to accept a `desk` parameter that routes to `desks.{desk}.*` instead of top-level config:

```python
class RiskGovernor:
    def __init__(self, config: dict, desk: str = "swing"):
        """Risk governor scoped to a single desk.

        Desks have independent max_concurrent, max_position_pct,
        starting_capital. The cross-desk kill switch (portfolio-wide
        catastrophic loss) remains centralized.
        """
        self.desk = desk
        self.config = config
        self.desk_cfg = config.get("desks", {}).get(desk, {})
        # ... existing init logic, but read from self.desk_cfg ...
```

**Cross-desk ticker conflict check:** Add a method that blocks a new entry on desk X if ticker is currently open on desk Y:

```python
def check_cross_desk_ticker_conflict(self, ticker: str, db_path: str) -> bool:
    """Return True if ticker is open on ANY desk (blocks duplicate entry).

    Policy: hard no-overlap across desks for MVP. Deep research Section 5
    recommends soft-with-caps but MVP uses the simpler hard rule.
    """
    import sqlite3
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT desk FROM shadow_trades "
            "WHERE ticker = ? AND actual_exit_time IS NULL "
            "AND COALESCE(quarantined, 0) = 0 LIMIT 1",
            (ticker,),
        ).fetchone()
    return row is not None
```

**Registry pattern:**

```python
def get_governors_by_desk(config: dict) -> dict[str, RiskGovernor]:
    """Return {desk: RiskGovernor} for every enabled desk."""
    desks = config.get("desks", {})
    return {
        desk: RiskGovernor(config, desk=desk)
        for desk, cfg in desks.items() if cfg.get("enabled", False)
    }
```

**Tests:** `tests/test_risk_governor_multi_desk.py`

- `test_research_governor_reads_research_config`: `max_concurrent=5`, not 10
- `test_cross_desk_ticker_blocks_second_entry`: seed swing open on AAPL, research tries AAPL → blocked
- `test_cross_desk_ticker_allows_after_close`: swing closes AAPL, research can enter
- `test_get_governors_skips_disabled_desks`: research disabled → only swing governor returned

**Acceptance:** Existing governor tests still pass. New multi-desk tests pass.

---

### Task 6 — Executor: desk routing + excess-SPY attribution (2.0h)

**File:** `src/shadow_trading/executor.py` (EDIT)

Two changes:

**6a. Desk-aware client selection.** Every function that calls `_get_trading_client()` needs to route based on desk tag. Add a helper:

```python
def _get_client_for_desk(desk: str):
    """Return the Alpaca client for the given desk.

    Fallback: if desk is None or unknown, uses the legacy _get_trading_client
    (swing desk default). This preserves backward compat with pre-desk
    code paths during migration.
    """
    if not desk or desk == "swing":
        # Swing uses the existing _get_trading_client for backward compat
        # (it reads the top-level `alpaca:` config, which is the swing
        # credentials). Once all call sites explicitly pass desk, we can
        # migrate swing to the new factory too.
        return _get_trading_client()
    from src.shadow_trading.alpaca_clients import get_client
    return get_client(desk)
```

**Assertion guardrail:** In `open_shadow_trade` (around line 800), before submitting the order:

```python
# SAFETY: desk tag on the trade_data MUST match the client's desk_tag.
# Prevents the 'swing order accidentally hits research account' bug.
client_tag = getattr(client, "desk_tag", "swing")
trade_desk = trade_data.get("desk", "swing")
assert client_tag == trade_desk, (
    f"Desk routing mismatch: client={client_tag} trade={trade_desk}"
)
```

**6b. research_thesis + filing_anchor_accession persistence.** When a research trade opens, its research note JSON goes into `trade_data["research_thesis"]` and the filing accession into `trade_data["filing_anchor_accession"]`. `journal.store._filter_to_schema` already strips unknown columns, so writes will just work once the schema migration (Task 2) lands.

**Excess-SPY:** Already instrumented from D1. `close_shadow_trade` in `src/journal/store.py` already populates `spy_return_over_hold` and `excess_return` on every exit. No change needed — works identically for 21-day holds as for 7-day holds.

**Tests:** `tests/test_executor_desk_routing.py`

- `test_open_research_trade_uses_research_client`: mock both clients, open trade with desk='research', assert research client was called
- `test_open_swing_trade_uses_swing_client`: mirror test
- `test_desk_routing_mismatch_assertion`: construct a pathological case where trade_data.desk='research' but client.desk_tag='swing' → AssertionError
- `test_research_thesis_persists_to_shadow_trades`: open research trade, query DB, verify research_thesis column has the JSON

**Acceptance:** All executor tests (existing + new) pass.

---

### Task 7 — Journal desk-aware query helpers (1.0h)

**File:** `src/journal/store.py` (EDIT — add new function, don't modify existing)

```python
def get_open_shadow_trades_by_desk(
    desk: str | None = None, db_path: str = DB_PATH,
) -> list[dict]:
    """Open trades filtered by desk. desk=None returns all desks."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        if desk is None:
            rows = conn.execute(
                "SELECT * FROM shadow_trades "
                "WHERE actual_exit_time IS NULL "
                "AND COALESCE(quarantined, 0) = 0"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM shadow_trades "
                "WHERE actual_exit_time IS NULL AND desk = ? "
                "AND COALESCE(quarantined, 0) = 0",
                (desk,),
            ).fetchall()
    return [dict(r) for r in rows]


def get_closed_trades_by_desk(
    desk: str | None = None, db_path: str = DB_PATH,
) -> list[dict]:
    """Closed trades filtered by desk."""
    # (analogous implementation)
    ...
```

**Existing `get_open_shadow_trades()` stays unchanged** for backward compat — it returns all desks combined, which is what current callers expect.

**Tests:** `tests/test_journal_desk_isolation.py`

- `test_get_open_by_desk_swing_only`
- `test_get_open_by_desk_research_only`
- `test_get_open_by_desk_none_returns_both`
- `test_get_closed_by_desk_filters_correctly`

---

### Task 8 — LLM research commentary with grammar-constrained JSON (2.0h)

**File:** `src/llm/research_prompt.py` (new)

```python
"""Research desk LLM prompt — structured 10-K/earnings/news extraction.

Called by: services.research_scan_service (before order placement)
Calls: llm.client (Ollama/vLLM)
Owns tables: none
Config keys: desks.research.llm_timeout_seconds
Tests: tests/test_research_prompt.py

Authority: deep research §3 — "The LLM does one job well: structured
extraction and classification, anchored to quotable evidence." Every
creative task is rejected as theater at the 8B scale.

Output is strict JSON with mandatory verbatim quote grounding. Any
response where thesis_justification does not contain a substring that
appears verbatim in the filing is rejected.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


RESEARCH_PROMPT_TEMPLATE = """You are a disciplined securities analyst producing a structured research note for a quantitative trading system. You DO NOT make up facts. You DO NOT provide target prices or probability distributions. You extract and classify.

TICKER: {ticker}
FILING TYPE: {form_type}
FILING DATE: {filing_date}
TRIGGER: {trigger}
EVIDENCE: {evidence_summary}

RISK FACTORS SECTION (current vs prior year, cosine={cosine_risk_factors}):
{risk_factors_excerpt}

MD&A SECTION (current vs prior year, cosine={cosine_mdna}):
{mdna_excerpt}

Produce a JSON object with EXACTLY these keys:
- ticker: string
- as_of: ISO timestamp
- filing_anchor: {{form, accession, filed}}
- thesis_direction: "long" | "short" | "neutral"
- conviction: float in [0.0, 1.0]
- horizon_days: 21
- yoy_diff:
    - risk_factors_changed: bool
    - risk_delta_topics: list of strings from {{supply_chain, litigation, regulatory, competition, guidance, macroeconomic, personnel, other}}
    - mdna_tone_shift: "negative" | "neutral" | "positive"
    - cosine_sim_to_prior: float
- earnings_tone_shift: {{vs_prior_call, evidence_quote}} or null
- news_bias_14d: "bullish" | "bearish" | "mixed" | "thin" | null
- thesis_justification: string, max 400 chars, MUST include at least one verbatim substring of 20+ chars from the filing sections above
- disqualifiers: list (empty if none). Include "numerical_unverified" if thesis relies on specific numbers you cannot cite; "filing_too_short" if sections are <500 chars; "insufficient_prior_year" if cosine_sim_to_prior was null.

Return ONLY the JSON object. No preamble, no markdown, no explanation."""


def render_prompt(
    ticker: str, form_type: str, filing_date: str, trigger: str,
    evidence_summary: str, risk_factors_text: str | None,
    mdna_text: str | None, cosine_risk_factors: float | None,
    cosine_mdna: float | None,
) -> str:
    """Render the research prompt with excerpted sections (3000 chars each)."""
    rf_excerpt = (risk_factors_text or "[section not available]")[:3000]
    mdna_excerpt = (mdna_text or "[section not available]")[:3000]
    return RESEARCH_PROMPT_TEMPLATE.format(
        ticker=ticker,
        form_type=form_type,
        filing_date=filing_date,
        trigger=trigger,
        evidence_summary=evidence_summary,
        risk_factors_excerpt=rf_excerpt,
        mdna_excerpt=mdna_excerpt,
        cosine_risk_factors=(
            f"{cosine_risk_factors:.3f}" if cosine_risk_factors is not None else "N/A"
        ),
        cosine_mdna=(
            f"{cosine_mdna:.3f}" if cosine_mdna is not None else "N/A"
        ),
    )


REQUIRED_KEYS = {
    "ticker", "as_of", "filing_anchor", "thesis_direction", "conviction",
    "horizon_days", "yoy_diff", "thesis_justification", "disqualifiers",
}


def validate_research_note(
    note_json: dict | str, filing_sections_text: str,
) -> tuple[bool, str]:
    """Validate LLM output against the research-desk schema.

    Returns (is_valid, reason). reason is a short string explaining
    rejection. filing_sections_text is the concatenated risk_factors +
    mdna text, used to verify thesis_justification has verbatim grounding.
    """
    if isinstance(note_json, str):
        try:
            note_json = json.loads(note_json)
        except json.JSONDecodeError as exc:
            return False, f"invalid_json: {exc}"
    if not isinstance(note_json, dict):
        return False, "not_object"
    missing = REQUIRED_KEYS - set(note_json.keys())
    if missing:
        return False, f"missing_keys: {sorted(missing)}"
    direction = note_json.get("thesis_direction")
    if direction not in ("long", "short", "neutral"):
        return False, f"bad_direction: {direction!r}"
    conviction = note_json.get("conviction")
    if not isinstance(conviction, (int, float)) or not (0.0 <= conviction <= 1.0):
        return False, f"bad_conviction: {conviction!r}"
    justification = note_json.get("thesis_justification", "")
    if not justification or len(justification) > 400:
        return False, "justification_empty_or_too_long"
    # Verbatim grounding: find any 20+ character substring of justification
    # that appears literally in the filing sections.
    if not _has_verbatim_substring(justification, filing_sections_text, min_len=20):
        return False, "no_verbatim_quote_from_filing"
    if note_json.get("disqualifiers"):
        return False, f"self_disqualified: {note_json['disqualifiers']}"
    return True, "ok"


def _has_verbatim_substring(needle: str, haystack: str, min_len: int = 20) -> bool:
    """True if ANY substring of needle of length >=min_len appears in haystack.

    Normalizes whitespace before comparison so the LLM can lightly
    reformat quotes without failing the check.
    """
    norm_hay = re.sub(r"\s+", " ", haystack).lower()
    norm_needle = re.sub(r"\s+", " ", needle).lower()
    for i in range(len(norm_needle) - min_len + 1):
        chunk = norm_needle[i : i + min_len]
        if chunk in norm_hay:
            return True
    return False


def generate_research_note(
    ticker: str, candidate: dict, timeout_s: float = 6.0,
) -> dict | None:
    """Call the LLM for a structured research note. Returns None on any
    failure — caller treats None as 'skip this trade'.

    Uses src.llm.client.generate_structured which wraps Ollama's JSON
    schema mode. Schema-constrained decoding produces strict JSON; we
    still run validate_research_note() for semantic checks (verbatim
    quote grounding, thesis_direction enum, etc).
    """
    from src.llm.client import generate_structured

    # Build evidence_summary and fetch filing sections from DB
    # (implementation detail — read edgar_filings by accession)
    prompt = render_prompt(...)  # fill in from candidate

    # JSON schema enforces structure; validation enforces semantics.
    schema = {
        "name": "research_note",
        "schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "as_of": {"type": "string"},
                "filing_anchor": {"type": "object"},
                "thesis_direction": {
                    "type": "string",
                    "enum": ["long", "short", "neutral"],
                },
                "conviction": {"type": "number", "minimum": 0, "maximum": 1},
                "horizon_days": {"type": "integer"},
                "yoy_diff": {"type": "object"},
                "thesis_justification": {"type": "string", "maxLength": 400},
                "disqualifiers": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "ticker", "as_of", "filing_anchor", "thesis_direction",
                "conviction", "horizon_days", "yoy_diff",
                "thesis_justification", "disqualifiers",
            ],
        },
    }
    system_prompt = (
        "You are a disciplined securities analyst. Extract facts from the "
        "filing. Do not fabricate. Quote verbatim when possible."
    )

    note = generate_structured(
        prompt=prompt, system_prompt=system_prompt,
        response_schema=schema, temperature=0.3,
    )
    if note is None:
        logger.warning("[RESEARCH_LLM] generation failed for %s", ticker)
        return None

    filing_text = "..."  # concatenated from DB read
    ok, reason = validate_research_note(note, filing_text)
    if not ok:
        logger.warning("[RESEARCH_LLM] rejected for %s: %s", ticker, reason)
        return None
    return note
```

**Tests:** `tests/test_research_prompt.py`

- `test_validate_note_rejects_missing_keys`
- `test_validate_note_rejects_bad_direction`
- `test_validate_note_rejects_conviction_out_of_range`
- `test_validate_note_rejects_justification_without_verbatim_quote`: justification that doesn't appear in filing → rejected
- `test_validate_note_accepts_valid_note_with_quote`: justification contains a 30-char substring from filing → passes
- `test_validate_note_rejects_self_disqualified`: disqualifiers list non-empty → rejected
- `test_has_verbatim_substring_handles_whitespace`: whitespace-different but token-identical → passes
- `test_render_prompt_truncates_long_sections_to_3000`

**Acceptance:** All tests pass. Manually test against a real filing — render prompt for a known ticker, verify prompt output looks sensible.

---

### Task 9 — Watch loop: wire research scan (1.5h)

**File:** `src/scheduler/watch.py` (EDIT)

Add a new method mirroring `_run_mr_scan`:

```python
def _run_research_scan(self):
    """Run the research desk scan. 10-min cadence during market hours."""
    from src.services.research_scan_service import run_research_scan
    result = run_research_scan(self.config)
    logger.info("[WATCH] Research scan: %s", result)
```

**Add state flag in `__init__`:** `self._last_research_scan_time = None`

**Add dispatch in `_run_sync_body`:** During market hours, check if 10 minutes have elapsed since `_last_research_scan_time` and if so, fire `self._safe_run("research scan", self._run_research_scan)`.

**Critical:** The research scan MUST NOT block the swing scan. Research failures should log and continue. Wrap the entire scan in `_safe_run` which already handles this.

**Tests:** `tests/test_watch_research_integration.py`

- `test_research_scan_fires_at_10min_cadence`: mock datetime, verify scan fires
- `test_research_scan_failure_does_not_kill_swing`: patch research_scan to raise, verify swing still runs
- `test_research_scan_skipped_when_desk_disabled`: research.enabled=false → scan returns immediately

**Acceptance:** Watch loop starts cleanly with research desk disabled. No regression in swing.

---

### Task 10 — Dashboard + Telegram desk tagging (1.5h)

**File:** `frontend/src/pages/TradeHistory.jsx` (EDIT)

Add a desk filter selector above the trade table:

```jsx
const [deskFilter, setDeskFilter] = useState("all")  // "all" | "swing" | "research"

// In render:
<select value={deskFilter} onChange={(e) => setDeskFilter(e.target.value)}
        className="ml-2 arcis-input-sm">
  <option value="all">All desks</option>
  <option value="swing">Swing only</option>
  <option value="research">Research only</option>
</select>
```

Filter the trades client-side: `trades.filter(t => deskFilter === "all" || t.desk === deskFilter)`

**File:** `src/api/cloud_routes/trades.py` (EDIT)

The `/api/shadow/closed` endpoint already returns full trade rows; `desk` column is now present. No backend change needed unless it strips unknown columns.

**File:** `src/notifications/telegram.py` (EDIT)

In `notify_trade_opened` and `notify_trade_closed`, prefix the header with `[RESEARCH]` if desk is research:

```python
def notify_trade_opened(..., desk: str = "swing"):
    prefix = "[RESEARCH] " if desk == "research" else ""
    header = f"{prefix}🟢 <b>TRADE OPENED: {ticker}..."
```

Callers (`scan_service.py`, `research_scan_service.py`) pass `desk=` explicitly.

**Tests:** `tests/test_telegram_desk_prefix.py`

- `test_swing_trade_has_no_prefix`
- `test_research_trade_has_prefix`

**Acceptance:** `npm run build` passes in frontend. Dashboard renders Trade History with desk filter dropdown. Telegram test-send with desk='research' shows `[RESEARCH]` prefix.

---

## End-of-Sprint Go/No-Go Criteria

Before merging to main, ALL must be true:

1. `python -m pytest tests/ -x --tb=short -q` passes with pass count ≥ pre-sprint baseline + ~40 new tests
2. `cd frontend && npm run build` succeeds with no errors
3. `python -c "from src.shadow_trading.alpaca_clients import verify_accounts_distinct; print(verify_accounts_distinct())"` returns two distinct account numbers
4. Every pre-existing shadow_trades row has `desk='swing'` (no NULLs):
   ```bash
   python -c "from src.config import DB_PATH; import sqlite3; c=sqlite3.connect(DB_PATH); print(c.execute('SELECT COUNT(*) FROM shadow_trades WHERE desk IS NULL').fetchone()[0])"
   # Expected: 0
   ```
5. End-to-end dry run: flip `desks.research.enabled: true`, run one scan cycle manually, verify a candidate is identified (if any filings exist), LLM produces valid JSON, research trade gets logged with `desk='research'` and non-null `research_thesis`.
6. Flip `desks.research.enabled` back to `false` before committing the config.

**If any criterion fails:** do NOT merge. Revert config to `enabled: false`, push the branch as-is for review, and we fix in a follow-up.

---

## Commit Sequence (one atomic commit per task)

```
feat(config): dual-desk configuration structure with per-desk Alpaca credentials
feat(schema): add desk + research columns to shadow_trades (SD#41 D2 Phase 2)
feat(brokers): per-desk Alpaca TradingClient factory with account distinctness check
feat(features): Lazy Prices cosine + ML-SUE signals
feat(services): research_scan_service — filing-anchored earnings drift
fix(edgar): extract Risk Factors (item_1a) from 10-K/10-Q for Lazy Prices
feat(risk): per-desk RiskGovernor with cross-desk ticker conflict check
feat(executor): desk-aware Alpaca client routing with assertion guardrail
feat(journal): desk-aware open/closed trade query helpers
feat(llm): research_prompt with grammar-constrained JSON + verbatim-quote validation
feat(scheduler): wire research scan into watch loop at 10-min cadence
feat(frontend): TradeHistory desk filter dropdown
feat(telegram): [RESEARCH] prefix on research-desk notifications
docs(v0.24.0): changelog + MASTER.md Section 2 Equity Research Desk entry
```

---

## Out-of-Scope (Explicit Deferrals)

- **Fine-tuned research LoRA** — Phase 0 uses base Qwen3-8B with JSON-mode + validation (deep research §3, phased plan)
- **Synthetic training corpus** — empty `data/training/research/` dir with README only
- **Dedicated `/dashboard/research` route** — use `?desk=` URL param for now
- **Real-time cross-desk correlation monitor** — log only; Jupyter notebook analysis post-launch
- **Separate Telegram channel** — prefix-only for MVP
- **Backfill excess-SPY on historical swing trades** — already done via D1
- **S&P 500 universe file** — `src/universe/sp500.py` does **not** currently exist. The `_get_universe` function in `research_scan_service.py` tries to import it and falls back to sp100 on ImportError. **MVP operates on sp100** (same as swing). Creating sp500.py is explicitly Phase 2a follow-up — it's a 100-line file of tickers but testing coverage across 500 names is materially more work than the weekend allows. The research desk still earns its keep on sp100 because the alpha source (filing-anchored earnings drift) is orthogonal to swing's entry signal; it's just sparse (5-8 signals/month vs the 20-30 we'd see on sp500).
- **Elastic-net ML-SUE** — MVP uses weighted average of 12 quarters; replace with real elastic-net once 60+ research trades close (Phase 2a)
- **Cross-desk correlation nightly check** (|ρ| > 0.6 for 10 days → halve allocation) — post-MVP
- **Attribution A/B three-arm test** (Arm A mechanical / Arm B +LLM / Arm C redacted-filing) — post-MVP once we have 30+ research trades

---

## Risk Mitigations (from deep research §4)

| Risk | Mitigation |
|---|---|
| Alpaca picks up `APCA_API_KEY_ID` env var and mis-routes | Pass keys **explicitly** to `TradingClient(key, secret, paper=True)`; `verify_accounts_distinct` asserts account numbers differ |
| SQLite migration on live data | Copy DB to `.bak` before first run; `ensure_columns` is idempotent; DEFAULT `'swing'` makes ALTER metadata-only |
| Ollama cold-start spikes past 6s timeout | `asyncio.wait_for(..., timeout=6)`; on timeout persist `research_thesis="[LLM_TIMEOUT]"`; LLM is narrative-gating, not execution-gating |
| Desk tag leaks across clients | Executor asserts `order.desk == client.desk_tag`; required-green test in Task 6 |
| EDGAR collector may not have item_1a on older filings | Graceful degrade — Lazy Prices filter passes if EITHER section is below threshold; missing section returns None, not error |
| S&P 500 universe file may not exist | Fallback to sp100 in `_get_universe`; add sp500.py as follow-up if missing |

---

*Ralph looped 3× against the live repo state 2026-04-16. Ready for CC execution on branch `feat/research-desk-mvp`.*
