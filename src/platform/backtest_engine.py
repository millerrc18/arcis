"""Strategy-agnostic historical replay harness.

Called by: scripts.run_backtest, src.platform.promotion (via Task 10).
Calls: src.attribution.logger, src.analytics.spy_benchmark,
       src.platform.data_loader, src.platform.metrics.
Owns tables: backtest_results, backtest_trades (declared in schema/registry,
             written by scripts/run_backtest.py:_persist).
Config keys: PLATFORM_EDGAR_DB (optional env override for event_driven DB).
Tests: tests/platform/test_backtest_engine.py.

Pattern reference (study before editing): src.evaluation.backtester.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pandas as pd

from src.analytics.spy_benchmark import excess_return, spy_return_over_range
from src.attribution.logger import simulate_mechanical_outcome
from src.features.indicators import compute_atr
from src.platform.data_loader import load_ohlcv_range
from src.platform.metrics import compute_all_metrics
from src.platform.features.cosine_similarity import cosine_similarity_yoy
from src.platform.signal_eval import (
    _evaluate_event_signal,
    _matches_scheduled_trigger,
    _query_event_rows,
)
from src.platform.strategy_spec import StrategySpec

logger = logging.getLogger(__name__)


@dataclass
class BacktestConfig:
    strategy: StrategySpec
    start_date: str
    end_date: str
    initial_capital: float = 100_000.0
    commission_bps: float = 0.0
    slippage_bps: float = 3.0
    spread_bps: float = 1.5
    random_seed: int = 42
    survivorship_haircut_bps: int = 75


@dataclass
class BacktestTrade:
    trade_id: str
    ticker: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    shares: int
    pnl_dollars: float
    pnl_pct: float
    exit_reason: str  # 'win' | 'loss' | 'timeout'
    hold_days: int
    spy_return_over_hold: float | None
    excess_return: float | None
    realized_sector: str | None
    regime_at_entry: str | None
    metadata: dict = field(default_factory=dict)


@dataclass
class BacktestResult:
    strategy_id: str
    config: BacktestConfig
    trades: list[BacktestTrade]
    equity_curve: list[tuple[str, float]]
    metrics: dict
    reproducibility: dict


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%d")


def _ohlcv_to_dicts(df: pd.DataFrame) -> list[dict]:
    """Convert OHLCV DataFrame (yfinance-style, capitalized cols) → list[dict]."""
    if df is None or df.empty:
        return []
    records: list[dict] = []
    for idx, row in df.iterrows():
        date_val = idx
        if hasattr(date_val, "strftime"):
            date_str = date_val.strftime("%Y-%m-%d")
        else:
            date_str = str(date_val)[:10]
        records.append({
            "date": date_str,
            "open": float(row.get("Open", row.get("open", 0.0))),
            "high": float(row.get("High", row.get("high", 0.0))),
            "low": float(row.get("Low", row.get("low", 0.0))),
            "close": float(row.get("Close", row.get("close", 0.0))),
        })
    return records


def _compute_bracket_prices(
    entry_price: float, exit_spec: dict, history_df: pd.DataFrame | None,
) -> tuple[float, float]:
    """Return (stop_price, target_price) per spec.exit.stop/target methods.

    'pct': fixed pct; 'atr_based': clamp(multiplier*atr/entry, floor, cap).
    history_df must contain bars STRICTLY BEFORE entry (no look-ahead).
    """
    stop_cfg = exit_spec.get("stop", {})
    target_cfg = exit_spec.get("target", {})
    stop_pct = _pct_from_spec(stop_cfg, entry_price, history_df)
    target_pct = _pct_from_spec(target_cfg, entry_price, history_df)
    stop_price = entry_price * (1.0 - stop_pct)
    target_price = entry_price * (1.0 + target_pct)
    return stop_price, target_price


def _pct_from_spec(
    spec: dict, entry_price: float, history_df: pd.DataFrame | None,
) -> float:
    """Convert a stop/target spec into a fractional pct (e.g. 0.02)."""
    method = spec.get("method", "pct")
    if method == "pct":
        return float(spec.get("value", 0.0))
    if method == "atr_based" and history_df is not None and not history_df.empty:
        period = int(spec.get("atr_period", 14))
        atr = compute_atr(
            history_df["High"], history_df["Low"], history_df["Close"],
            period=period,
        )
        if atr <= 0 or entry_price <= 0:
            return float(spec.get("floor_pct", 0.0))
        raw = (float(spec.get("multiplier", 1.0)) * atr) / entry_price
        floor = float(spec.get("floor_pct", 0.0))
        cap = float(spec.get("cap_pct", 1.0))
        return max(floor, min(cap, raw))
    return float(spec.get("floor_pct", spec.get("value", 0.0)))


def _apply_costs(
    entry: float, raw_exit: float, cfg: BacktestConfig,
) -> tuple[float, float]:
    """Symmetric per-side transaction cost application. Matches engine.py.

    per_side bps are applied once on entry (raises cost basis) and once on
    exit (lowers proceeds), so total round-trip cost = 2 * per_side bps —
    but each leg is charged only per_side, not 2 * per_side.
    """
    per_side = cfg.commission_bps + cfg.slippage_bps + cfg.spread_bps
    entry_adj = entry * (1.0 + per_side / 10_000.0)
    exit_adj = raw_exit * (1.0 - per_side / 10_000.0)
    return entry_adj, exit_adj


def _iter_trading_days(start_iso: str, end_iso: str) -> list[datetime]:
    """Inclusive business-day range (Mon–Fri)."""
    return [d.to_pydatetime() for d in pd.bdate_range(start_iso, end_iso)]


def _git_sha() -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL,
        )
        return out.decode().strip()
    except Exception:
        return None


def _reproducibility_dict(spec: StrategySpec, started: str, ended: str) -> dict:
    spec_json = json.dumps(spec.raw, sort_keys=True, default=str)
    return {
        "spec_hash": hashlib.sha256(spec_json.encode()).hexdigest(),
        "code_git_sha": _git_sha(),
        "started_at": started,
        "ended_at": ended,
        "run_id": str(uuid.uuid4()),
    }


def _load_forward_ohlcv(
    ticker: str, entry_iso: str, timeout: int,
) -> list[dict]:
    """Return up to `timeout` forward bars (excluding the entry bar)."""
    entry_dt = datetime.fromisoformat(entry_iso)
    forward_end = entry_dt + timedelta(days=int(timeout * 1.7) + 7)
    df = load_ohlcv_range(ticker, entry_iso, _iso(forward_end))
    if df is None or df.empty:
        return []
    df = df[df.index > pd.Timestamp(entry_iso)]
    return _ohlcv_to_dicts(df)[:timeout] if not df.empty else []


def _attribute_vs_spy(
    pnl_pct: float, entry_iso: str, exit_iso: str,
) -> tuple[float | None, float | None]:
    """Return (spy_return_fraction, excess_fraction). Both None if unavailable."""
    spy_ret = spy_return_over_range(entry_iso, exit_iso)
    # excess_return expects pnl in PERCENT and spy in FRACTION; result in PERCENT.
    excess_pct = excess_return(pnl_pct * 100.0, spy_ret)
    excess = excess_pct / 100.0 if excess_pct is not None else None
    return spy_ret, excess


def _build_trade(
    cfg: BacktestConfig,
    ticker: str,
    entry_iso: str,
    entry_price: float,
    exit_spec: dict,
    history_df: pd.DataFrame | None,
    metadata: dict,
) -> BacktestTrade | None:
    """Run bracket simulation + build a BacktestTrade. Returns None on failure."""
    if entry_price <= 0:
        return None
    timeout = int(exit_spec.get("timeout_days", 21))
    stop_price, target_price = _compute_bracket_prices(
        entry_price, exit_spec, history_df,
    )
    ohlcv_list = _load_forward_ohlcv(ticker, entry_iso, timeout)
    if not ohlcv_list:
        return None

    outcome, raw_exit, days_held = simulate_mechanical_outcome(
        entry_price, stop_price, target_price, timeout, ohlcv_list,
    )
    if days_held == 0:
        return None

    exit_iso = ohlcv_list[min(days_held, len(ohlcv_list)) - 1]["date"]
    entry_adj, exit_adj = _apply_costs(entry_price, raw_exit, cfg)
    pnl_pct = (exit_adj - entry_adj) / entry_adj

    sizing = cfg.strategy.position_sizing
    shares = int(math.floor(
        cfg.initial_capital * float(sizing.get("pct", 0.05)) / entry_adj,
    ))
    spy_ret, excess = _attribute_vs_spy(pnl_pct, entry_iso, exit_iso)

    return BacktestTrade(
        trade_id=str(uuid.uuid4()), ticker=ticker,
        entry_date=entry_iso, exit_date=exit_iso,
        entry_price=entry_adj, exit_price=exit_adj,
        shares=shares, pnl_dollars=shares * (exit_adj - entry_adj),
        pnl_pct=pnl_pct, exit_reason=outcome, hold_days=days_held,
        spy_return_over_hold=spy_ret, excess_return=excess,
        realized_sector=None, regime_at_entry=None, metadata=metadata,
    )


def _run_scheduled(cfg: BacktestConfig) -> list[BacktestTrade]:
    spec = cfg.strategy
    tickers = spec.universe.get("tickers", [])
    if not isinstance(tickers, list):
        return []
    trades: list[BacktestTrade] = []
    for ticker in tickers:
        history_start = (
            datetime.fromisoformat(cfg.start_date) - timedelta(days=90)
        )
        df = load_ohlcv_range(ticker, _iso(history_start), cfg.end_date)
        if df is None or df.empty:
            continue
        for day in _iter_trading_days(cfg.start_date, cfg.end_date):
            if not _matches_scheduled_trigger(day, spec.entry):
                continue
            day_iso = _iso(day)
            day_ts = pd.Timestamp(day_iso)
            if day_ts not in df.index:
                continue
            bar = df.loc[day_ts]
            entry_price = float(bar.get("Close", bar.get("close", 0.0)))
            history_df = df[df.index < day_ts]
            trade = _build_trade(
                cfg, ticker, day_iso, entry_price, spec.exit, history_df,
                metadata={"trigger": "scheduled"},
            )
            if trade is not None:
                trades.append(trade)
    return trades


def _inject_cosine_scores(
    sections: dict,
    signal: list[dict],
    ticker: str,
    accession: str,
    db_path: str,
) -> dict:
    """Compute YoY cosine similarity for each cosine_similarity signal condition
    and inject the result under '<target>_cosine_yoy' so _evaluate_event_signal
    can read them.

    If a pre-computed value already exists in sections (e.g. from a test fixture
    that seeds sections_json directly), it is left untouched.  Live computation
    is only attempted when the key is absent.
    """
    live_db = os.environ.get("PLATFORM_EDGAR_DB", db_path)
    for condition in signal:
        if condition.get("metric") != "cosine_similarity":
            continue
        target = condition.get("target", "")
        key = f"{target}_cosine_yoy"
        if key in sections:
            continue  # already present (e.g. test fixture)
        try:
            cos = cosine_similarity_yoy(ticker, accession, target, live_db)
        except Exception as exc:
            logger.debug(
                "[PLATFORM] cosine_similarity_yoy failed %s/%s/%s: %s",
                ticker, accession, target, exc,
            )
            cos = None
        if cos is not None:
            sections[key] = cos
    return sections


def _run_event_driven(cfg: BacktestConfig) -> list[BacktestTrade]:
    spec = cfg.strategy
    signal = spec.entry.get("signal", [])
    combinator = spec.entry.get("combinator", "all")  # "all" (AND) or "any" (OR)
    rows = _query_event_rows(spec, cfg)

    from src.config import DB_PATH as _default_db
    db_path = os.environ.get("PLATFORM_EDGAR_DB", _default_db)

    trades: list[BacktestTrade] = []
    for row in rows:
        try:
            sections = json.loads(row.get("sections_json") or "{}")
        except json.JSONDecodeError:
            continue
        # Inject live-computed cosine scores for any cosine_similarity
        # signal conditions whose key is not already in sections_json.
        # Hotfix v0.24.0-alpha2.1: edgar_collector stores raw section text
        # under 'item_1a' / 'item_7'; _evaluate_event_signal expects the
        # pre-computed float under 'item_1a_cosine_yoy'. Bridge the gap here
        # so the signal evaluator always sees the right key regardless of
        # whether sections_json was pre-computed or is raw text.
        ticker = row.get("ticker", "")
        accession = row.get("accession_number", "")
        sections = _inject_cosine_scores(
            sections, signal, ticker, accession, db_path,
        )
        if not _evaluate_event_signal(sections, signal, combinator):
            continue
        filing_date = row["filing_date"]
        # Entry at NEXT trading day's open after filing.
        history_start = (
            datetime.fromisoformat(filing_date) - timedelta(days=90)
        )
        forward_end = (
            datetime.fromisoformat(filing_date) + timedelta(days=30)
        )
        df = load_ohlcv_range(ticker, _iso(history_start), _iso(forward_end))
        if df is None or df.empty:
            continue
        after = df[df.index > pd.Timestamp(filing_date)]
        if after.empty:
            continue
        first_bar = after.iloc[0]
        entry_ts = after.index[0]
        entry_iso = entry_ts.strftime("%Y-%m-%d")
        entry_price = float(first_bar.get("Open", first_bar.get("open", 0.0)))
        history_df = df[df.index < entry_ts]
        trade = _build_trade(
            cfg, ticker, entry_iso, entry_price, spec.exit, history_df,
            metadata={"filing_accession": row.get("accession_number")},
        )
        if trade is not None:
            trades.append(trade)
    return trades


def _build_equity_curve(
    cfg: BacktestConfig, trades: list[BacktestTrade],
) -> list[tuple[str, float]]:
    """Mark-to-market only at trade close. Anchor first and last dates."""
    curve: list[tuple[str, float]] = [(cfg.start_date, cfg.initial_capital)]
    capital = cfg.initial_capital
    for t in sorted(trades, key=lambda x: x.exit_date):
        capital += t.pnl_dollars
        curve.append((t.exit_date, capital))
    if curve[-1][0] != cfg.end_date:
        curve.append((cfg.end_date, capital))
    return curve


def run_backtest(config: BacktestConfig) -> BacktestResult:
    """Deterministic historical replay. See module docstring."""
    started = datetime.now(timezone.utc).isoformat()
    spec = config.strategy
    kind = spec.entry.get("kind")

    if kind == "scheduled":
        trades = _run_scheduled(config)
    elif kind == "event_driven":
        trades = _run_event_driven(config)
    elif kind == "python_plugin":
        raise NotImplementedError("python_plugin entry kind not supported in MVP")
    else:
        raise ValueError(f"unknown entry.kind: {kind!r}")

    equity_curve = _build_equity_curve(config, trades)
    metrics = compute_all_metrics(
        trades, equity_curve,
        survivorship_haircut_bps=config.survivorship_haircut_bps,
    )
    ended = datetime.now(timezone.utc).isoformat()
    reproducibility = _reproducibility_dict(spec, started, ended)

    return BacktestResult(
        strategy_id=spec.strategy_id,
        config=config,
        trades=trades,
        equity_curve=equity_curve,
        metrics=metrics,
        reproducibility=reproducibility,
    )
