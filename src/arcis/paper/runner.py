#!/usr/bin/env python3
"""Step P daily paper trading runner.

Runs the three-account execution experiment:
1. Generate signals from the frozen incumbent (pre-market).
2. Place orders on all three accounts (market open).
3. Monitor fills (intraday).
4. Reconcile and update calibration (EOD).

Usage:
    python -m arcis.paper.runner --mode signals   # pre-market
    python -m arcis.paper.runner --mode orders    # market open
    python -m arcis.paper.runner --mode reconcile # EOD

API keys are read from environment variables:
    ALPACA_PAPER_A_KEY, ALPACA_PAPER_A_SECRET
    ALPACA_PAPER_B_KEY, ALPACA_PAPER_B_SECRET
    ALPACA_PAPER_C_KEY, ALPACA_PAPER_C_SECRET
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date

from arcis.paper import AlpacaPaper, PaperConfig
from arcis.paper.calibration import FillTracker, calibrate_buffer, validate_d020
from arcis.paper.signals import SignalConfig, generate_signals, signals_to_orders


def load_universe(data_root: str = "/home/hatch/arcis-data") -> list[str]:
    """Load the trading universe from the latest snapshot."""
    import csv
    from pathlib import Path
    universe_dir = Path(data_root) / "universe"
    files = sorted(universe_dir.glob("*.csv"))
    if not files:
        return []
    latest = files[-1]
    with open(latest) as f:
        reader = csv.DictReader(f)
        return [row["symbol"] for row in reader]


def load_configs() -> dict[str, PaperConfig]:
    """Load paper account configs from environment."""
    configs = {}
    for account in ["A", "B", "C"]:
        key = os.environ.get(f"ALPACA_PAPER_{account}_KEY")
        secret = os.environ.get(f"ALPACA_PAPER_{account}_SECRET")
        if not key or not secret:
            print(f"warning: missing keys for account {account}, skipping",
                  file=sys.stderr)
            continue
        configs[account] = PaperConfig(
            name=account, api_key=key, api_secret=secret)
    return configs


def run_signals(as_of: date, data_root: str) -> None:
    """Generate and save signals (pre-market)."""
    config = SignalConfig()
    signals = generate_signals(as_of, data_root, config)
    print(f"generated {len(signals)} signals for {as_of}")
    # TODO: save to a signals file for the orders step


def run_orders(as_of: date, buffer_bp: float = 10.0,
               dry_run: bool = False) -> None:
    """Place orders on all three accounts (market open)."""
    configs = load_configs()
    if not configs:
        print("no paper accounts configured", file=sys.stderr)
        sys.exit(1)

    # Generate signals from the frozen incumbent
    tickers = load_universe()
    print(f"scanning {len(tickers)} tickers...")
    sig_config = SignalConfig()
    signals = generate_signals(as_of, tickers, sig_config)
    print(f"placing orders for {len(signals)} signals")

    for account, config in configs.items():
        client = AlpacaPaper(config)
        orders = signals_to_orders(signals, account, buffer_bp)
        for order in orders:
            if dry_run:
                print(f"  {account}: DRY RUN {order['symbol']} "
                      f"{order['type']} {order['qty']} @ "
                      f"{order.get('limit_price', 'MKT')}")
            else:
                # Map signal_to_order output to place_order kwargs
                result = client.place_order(
                    symbol=order["symbol"],
                    qty=order["qty"],
                    side=order["side"],
                    order_type=order["type"],
                    limit_price=order.get("limit_price"),
                )
                print(f"  {account}: {order['symbol']} -> {result['id']}")


def run_reconcile(buffer_bp: float = 10.0) -> None:
    """Reconcile fills and update calibration (EOD)."""
    from arcis.paper import FillRecord
    configs = load_configs()
    tracker = FillTracker()

    for account, config in configs.items():
        client = AlpacaPaper(config)
        orders = client.get_orders(status="closed")
        n_fills = 0
        for o in orders:
            if o.get("status") != "filled":
                continue
            filled_qty = int(float(o.get("filled_qty", 0)))
            if filled_qty == 0:
                continue
            fill_price = float(o["filled_avg_price"])
            # Signal price = limit price (D-029: limit = signal close)
            # For market orders (B), use the filled price as baseline (no slippage ref)
            signal_price = float(o["limit_price"]) if o.get("limit_price") else fill_price
            slippage_bp = (fill_price - signal_price) / signal_price * 10000 if signal_price else 0.0
            tracker.record(FillRecord(
                symbol=o["symbol"],
                signal_date=o.get("submitted_at", "")[:10],
                account=account,
                order_id=o["id"],
                fill_price=fill_price,
                fill_qty=filled_qty,
                fill_time=o.get("filled_at", ""),
                signal_price=signal_price,
                slippage_bp=slippage_bp,
            ))
            n_fills += 1
        print(f"  {account}: {n_fills} fills from {len(orders)} closed orders")

    # Generate calibration reports
    for account in configs:
        fills = tracker.by_account(account)
        report = calibrate_buffer(tracker, account, len(fills), buffer_bp)
        print(f"  {account}: {report.n_fills} fills, "
              f"mean slippage {report.mean_slippage_bp:.1f}bp, "
              f"{report.buffer_adequate_pct:.1f}% within {buffer_bp}bp buffer")

        d020 = validate_d020(tracker, account)
        print(f"  {account}: D-020 compliance {d020.compliance_rate:.1%}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Step P paper lane runner")
    parser.add_argument("--mode", required=True,
                        choices=["signals", "orders", "reconcile"])
    parser.add_argument("--date", default=str(date.today()),
                        help="Signal date (YYYY-MM-DD)")
    parser.add_argument("--data-root", default="data",
                        help="Data plane root")
    parser.add_argument("--buffer-bp", type=float, default=10.0,
                        help="Adverse buffer in basis points")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print orders without placing them")
    args = parser.parse_args()

    as_of = date.fromisoformat(args.date)

    if args.mode == "signals":
        run_signals(as_of, args.data_root)
    elif args.mode == "orders":
        run_orders(as_of, args.buffer_bp, dry_run=args.dry_run)
    elif args.mode == "reconcile":
        run_reconcile(args.buffer_bp)


if __name__ == "__main__":
    main()
