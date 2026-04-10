from src.shadow_trading.alpaca_adapter import get_all_positions
positions = get_all_positions()
print(f"{len(positions)} positions")
for p in positions:
    print(f"  {p['symbol']}: {p['qty']}")
