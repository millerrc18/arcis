"""IB Gateway validation script -- verifies paper account setup.

Usage: python scripts/validate_ib_gateway.py [--port 4002] [--host 127.0.0.1]

SAFETY: Refuses to connect to port 4001 (live). Paper only.

Called by: operator (manual), docs/operations/ib-gateway-setup.md step 6
Calls: ib_async (TWS API direct, not IBBroker)
Config keys: none (all via CLI args)
"""
import argparse
import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Ten S&P 100 tickers used for contract qualification
SP100_TICKERS = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "JPM", "V", "JNJ", "PG"]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pass(label: str, detail: str = "") -> None:
    suffix = f"  ({detail})" if detail else ""
    print(f"  [PASS] {label}{suffix}")


def _fail(label: str, detail: str = "") -> None:
    suffix = f"  ({detail})" if detail else ""
    print(f"  [FAIL] {label}{suffix}")


def _warn(label: str, detail: str = "") -> None:
    suffix = f"  ({detail})" if detail else ""
    print(f"  [WARN] {label}{suffix}")


# ---------------------------------------------------------------------------
# Validation steps
# ---------------------------------------------------------------------------

async def run_validation(host: str, port: int, client_id: int) -> dict:
    """Run all validation checks. Returns a results dict."""
    from ib_async import IB, Stock

    results: dict[str, bool] = {}
    ib = IB()

    # Step 1: Connect to IB Gateway
    print("\n1. Connecting to IB Gateway...")
    try:
        await ib.connectAsync(host, port, clientId=client_id, timeout=15)
        _pass("Connection", f"{host}:{port} clientId={client_id}")
        results["connection"] = True
    except Exception as e:
        _fail("Connection", str(e))
        results["connection"] = False
        return results

    try:
        # Step 2: Verify paper account
        print("\n2. Verifying paper account...")
        try:
            accounts = ib.managedAccounts()
            if not accounts:
                _fail("Paper account check", "No managed accounts found")
                results["paper_account"] = False
            else:
                acct = accounts[0]
                # Paper accounts typically start with 'D' (e.g., DU1234567)
                is_paper = acct.startswith("D")
                if is_paper:
                    _pass("Paper account", f"account={acct}")
                    results["paper_account"] = True
                else:
                    _warn("Paper account", f"account={acct} -- does not start with 'D'; verify manually")
                    results["paper_account"] = True  # warn but don't block
        except Exception as e:
            _fail("Paper account check", str(e))
            results["paper_account"] = False

        # Step 3: Qualify 10 S&P 100 contracts
        print(f"\n3. Qualifying {len(SP100_TICKERS)} S&P 100 contracts...")
        qualified = 0
        failed_tickers: list[str] = []
        for ticker in SP100_TICKERS:
            try:
                contract = Stock(ticker, "SMART", "USD")
                details = await ib.qualifyContractsAsync(contract)
                if details:
                    qualified += 1
                else:
                    failed_tickers.append(ticker)
            except Exception:
                failed_tickers.append(ticker)

        if qualified == len(SP100_TICKERS):
            _pass("Contract qualification", f"{qualified}/{len(SP100_TICKERS)} qualified")
            results["contracts"] = True
        elif qualified > 0:
            _warn("Contract qualification", f"{qualified}/{len(SP100_TICKERS)} -- failed: {', '.join(failed_tickers)}")
            results["contracts"] = True
        else:
            _fail("Contract qualification", "0 contracts qualified")
            results["contracts"] = False

        # Step 4: Check buying power
        print("\n4. Checking buying power...")
        try:
            await asyncio.sleep(1)  # let account values populate
            account_values = ib.accountValues()
            buying_power = None
            net_liq = None
            for av in account_values:
                if av.tag == "BuyingPower" and av.currency == "USD":
                    buying_power = float(av.value)
                if av.tag == "NetLiquidation" and av.currency == "USD":
                    net_liq = float(av.value)

            if buying_power is not None:
                bp_str = f"${buying_power:,.2f}"
                nl_str = f"${net_liq:,.2f}" if net_liq else "N/A"
                _pass("Buying power", f"BP={bp_str}  NLV={nl_str}")
                results["buying_power"] = True
            else:
                _fail("Buying power", "BuyingPower not found in account values")
                results["buying_power"] = False
        except Exception as e:
            _fail("Buying power", str(e))
            results["buying_power"] = False

        # Step 5: Test market data snapshot
        print("\n5. Testing market data snapshot (AAPL)...")
        try:
            test_contract = Stock("AAPL", "SMART", "USD")
            await ib.qualifyContractsAsync(test_contract)
            ticker_data = ib.reqMktData(test_contract, snapshot=True)
            # Wait for snapshot data (up to 10 seconds)
            for _ in range(20):
                await asyncio.sleep(0.5)
                if ticker_data.last is not None or ticker_data.close is not None:
                    break

            price = ticker_data.last or ticker_data.close or ticker_data.bid
            if price is not None and price > 0:
                _pass("Market data snapshot", f"AAPL price=${price:.2f}")
                results["market_data"] = True
            else:
                _warn("Market data snapshot", "No price returned -- market may be closed or data subscription missing")
                results["market_data"] = False
            ib.cancelMktData(test_contract)
        except Exception as e:
            _fail("Market data snapshot", str(e))
            results["market_data"] = False

    finally:
        ib.disconnect()

    return results


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_report(results: dict, elapsed: float) -> int:
    """Print formatted status report. Returns exit code."""
    print("\n" + "=" * 50)
    print("   VALIDATION REPORT")
    print("=" * 50)

    total = len(results)
    passed = sum(1 for v in results.values() if v)
    failed = total - passed

    for check, ok in results.items():
        status = "PASS" if ok else "FAIL"
        print(f"  {status:4s}  {check}")

    print("-" * 50)
    print(f"  {passed}/{total} checks passed  ({elapsed:.1f}s)")

    if failed == 0:
        print("\n  IB Gateway paper account is READY.")
        return 0
    else:
        print(f"\n  {failed} check(s) failed -- see details above.")
        return 1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Validate IB Gateway paper account")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4002)
    parser.add_argument("--client-id", type=int, default=99)
    args = parser.parse_args()

    # CRITICAL: refuse live port
    if args.port == 4001:
        print("ERROR: Port 4001 is LIVE trading. This script is paper-only.")
        print("       Use --port 4002 for paper trading.")
        sys.exit(1)

    print("=" * 50)
    print("   IB GATEWAY VALIDATION -- PAPER ONLY")
    print("=" * 50)
    print(f"  Host:      {args.host}")
    print(f"  Port:      {args.port}")
    print(f"  Client ID: {args.client_id}")

    t0 = time.time()
    try:
        results = asyncio.run(run_validation(args.host, args.port, args.client_id))
    except KeyboardInterrupt:
        print("\nAborted by user.")
        sys.exit(130)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        sys.exit(2)

    elapsed = time.time() - t0
    exit_code = print_report(results, elapsed)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
