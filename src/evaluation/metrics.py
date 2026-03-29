from typing import Iterable


def expectancy(trade_pnls: Iterable[float]) -> float:
    pnls = list(trade_pnls)
    if not pnls:
        return 0.0
    return sum(pnls) / len(pnls)
