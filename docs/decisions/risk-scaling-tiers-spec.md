# Design Spec: Account-Size Risk Scaling Tiers

> **Strategy Decision:** #26 (Scaling Levers deep research, April 2026)
> **Author:** Claude (CTO)
> **Status:** SPEC — ready for sprint prompt conversion
> **Estimated effort:** 2-3 hours CC time
> **Ralph Loop:** 3x (see bottom)

---

## Problem

`planned_risk_pct_max` is a single static value in config. The scaling levers
research shows risk per trade should decrease as equity grows:

| Equity | Risk/Trade | Rationale |
|--------|-----------|-----------|
| $5K-$100K | 2.0% | Proving the edge, small absolute dollars |
| $100K-$500K | 1.5% | Scaling phase, drawdowns start to hurt |
| $500K-$1M | 1.25% | Real money, recovery from DD is slow |
| $1M+ | 1.0% | Institutional, capital preservation |

Currently the system uses a fixed value everywhere. A 2% risk at $5K = $100 loss.
At $500K = $10,000 loss. At $3M = $60,000 loss. The psychological and financial
impact is not linear — the governor must account for this.

---

## Design

### Config (settings.example.yaml)

Add `scaling_tiers` under the `risk:` section:

```yaml
risk:
  starting_capital: 100000
  planned_risk_pct_min: 0.005
  planned_risk_pct_max: 0.02        # Base max — overridden by tiers when enabled
  max_open_positions: 10

  # Account-size risk scaling (Strategy Decision #26)
  # Governor checks current equity and applies the matching tier.
  # Tiers are evaluated in order — first match wins.
  # If scaling is disabled or tiers are empty, planned_risk_pct_max is used.
  # Current equity = starting_capital + sum(closed trade P&L). Uses realized
  # P&L only (not unrealized) to prevent oscillation during market hours.
  risk_scaling:
    enabled: true
    tiers:
      - equity_below: 100000
        risk_pct_max: 0.02          # 2.0% — prove the edge
      - equity_below: 500000
        risk_pct_max: 0.015         # 1.5% — scaling phase
      - equity_below: 1000000
        risk_pct_max: 0.0125        # 1.25% — real money
      - equity_below: 999999999
        risk_pct_max: 0.01          # 1.0% — institutional
    notify_on_transition: true      # Telegram alert when tier changes
```

### New function: get_current_equity()

**File:** `src/risk/governor.py`

Extract the equity computation that currently lives duplicated in both
`compute_current_drawdown` (governor.py line 188) and `open_shadow_trade`
(executor.py line 275-290) into a single shared function:

```python
def get_current_equity(config: dict | None = None,
                       db_path: str = DB_PATH) -> float:
    """Compute current equity from starting capital + realized P&L.

    Uses only closed-trade P&L (not unrealized) to prevent equity
    oscillation during market hours from affecting position sizing.

    Returns: current equity in dollars.
    """
    config = config or load_config()
    starting_capital = config.get("risk", {}).get("starting_capital", 100000)
    try:
        import sqlite3
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(pnl_dollars), 0) "
                "FROM shadow_trades WHERE status = 'closed'"
            ).fetchone()
            total_pnl = row[0] if row else 0
        return starting_capital + total_pnl
    except Exception as e:
        logger.warning("[RISK] Equity computation failed: %s — using starting_capital", e)
        return starting_capital
```

### New function: get_effective_risk_pct()

**File:** `src/risk/governor.py`

```python
def get_effective_risk_pct(config: dict | None = None,
                           db_path: str = DB_PATH) -> tuple[float, str]:
    """Get the risk percentage for the current equity tier.

    Returns: (effective_risk_pct, tier_label)
      - effective_risk_pct: float, e.g. 0.015
      - tier_label: str, e.g. "$100K-$500K (1.5%)"

    If scaling is disabled or tiers are empty, returns
    (planned_risk_pct_max, "static").
    """
    config = config or load_config()
    risk_cfg = config.get("risk", {})
    base = risk_cfg.get("planned_risk_pct_max", 0.02)

    scaling = risk_cfg.get("risk_scaling", {})
    if not scaling.get("enabled", False):
        return base, "static"

    tiers = scaling.get("tiers", [])
    if not tiers:
        return base, "static"

    equity = get_current_equity(config, db_path)

    # Tiers evaluated in order — first match wins
    for tier in sorted(tiers, key=lambda t: t["equity_below"]):
        if equity < tier["equity_below"]:
            label = f"<${tier['equity_below']:,.0f} ({tier['risk_pct_max']:.1%})"
            return tier["risk_pct_max"], label

    # Equity exceeds all tiers — use the last tier's value
    last = tiers[-1]
    label = f">=${last['equity_below']:,.0f} ({last['risk_pct_max']:.1%})"
    return last["risk_pct_max"], label
```

### Tier transition notification

**File:** `src/risk/governor.py` (new function)

```python
def check_tier_transition(config: dict, db_path: str = DB_PATH) -> dict | None:
    """Check if equity has crossed a tier boundary since last check.

    Called once per day (e.g., during EOD recap). Stores last known tier
    in the activity_log table. Returns transition dict if changed, None otherwise.
    """
```

Call from the watch loop EOD block. Sends Telegram alert:
```
📊 RISK TIER CHANGE
Equity: $103,450
Previous tier: <$100K (2.0% risk/trade)
New tier: <$500K (1.5% risk/trade)
Max risk per trade: $1,551.75
```

---

## Integration Points (3 call sites to update)

### Site 1: src/packets/template.py (line 32)

**Current:**
```python
risk_pct = risk_cfg.get("planned_risk_pct_max", 0.01)
```

**New:**
```python
from src.risk.governor import get_effective_risk_pct
risk_pct, _tier = get_effective_risk_pct(config)
```

This is where initial packet position sizing happens. The packet will now
show the tier-adjusted risk, and shares/allocation will reflect it.

### Site 2: src/shadow_trading/executor.py (line 294 — Thorp drawdown)

**Current:**
```python
base_risk = config.get("risk", {}).get("planned_risk_pct_max", 0.02)
adjusted = drawdown_adjusted_risk(base_risk, current_dd_pct)
```

**New:**
```python
from src.risk.governor import get_effective_risk_pct, get_current_equity
base_risk, _tier = get_effective_risk_pct(config, db_path)
adjusted = drawdown_adjusted_risk(base_risk, current_dd_pct)
```

Also refactor the equity computation (lines 275-290) to use `get_current_equity()`:
```python
current_equity = get_current_equity(config, db_path)
starting_capital = config.get("risk", {}).get("starting_capital", 100000)
# Peak equity still needs the windowed SQL query (get_current_equity only returns current)
```

### Site 3: src/shadow_trading/executor.py (line 1396 — live trades)

**Current:**
```python
risk_pct_max = live_risk.get("planned_risk_pct_max", 0.02)
```

**New:**
```python
from src.risk.governor import get_effective_risk_pct
# Live trades use the same tier system but based on LIVE equity
# For now, use the paper equity tiers (live account is too small for meaningful tiers)
risk_pct_max, _tier = get_effective_risk_pct(config, db_path)
```

**Decision needed:** Should live trades use their own tier system based on live
equity, or share the paper tier system? At $100 live capital, the tiers would
always return 2% (the lowest tier). Recommendation: share the paper equity
tiers until live capital exceeds $25K, then add a separate `live_trading.risk_scaling`
config block.

### Display sites (no sizing impact, just visibility)

**src/api/routes/system.py (line 508-509):** Add `effective_risk_pct` and
`risk_tier` to the API response so the dashboard can display current tier.

**src/api/cloud_routes/core.py (lines 190-191):** Same — add tier info.

**Dashboard:** The CTO Report and Health pages should show the current equity,
active tier, and effective risk percentage. This is a display-only change.

---

## Interaction with existing risk adjustments

The risk scaling tiers set the BASE risk per trade. Existing adjustments
are applied ON TOP of the tier:

```
Config risk_pct_max (static)
  → Tier lookup (account-size scaling)    ← NEW
    → Thorp drawdown adjustment           ← existing (executor.py line 294)
      → Traffic Light multiplier          ← existing (governor check 0a)
        → Event risk multiplier           ← existing (governor check 0b)
          → Final effective allocation
```

Example: equity = $200K, drawdown = 8%, Traffic Light = 0.7, no event risk:
- Tier: $100K-$500K → 1.5%
- Thorp: 8% DD reduces risk by ~25% → 1.125%
- Traffic Light: × 0.7 → 0.7875%
- Final: 0.7875% of $200K = $1,575 max risk per trade

This is the correct cascade — each adjustment narrows the risk, never widens.

---

## Config validation

Add to `src/startup.py` startup checks:

1. If `risk_scaling.enabled: true`, tiers must be non-empty
2. Each tier must have `equity_below` (number > 0) and `risk_pct_max` (0 < x <= 0.05)
3. Tiers must be sorted ascending by equity_below (warn if not, auto-sort)
4. The final tier's equity_below should be very large (warn if < 10,000,000)
5. No tier's risk_pct_max should exceed planned_risk_pct_max (the base max)

---

## Tests

1. `test_get_effective_risk_pct_static` — scaling disabled returns base max
2. `test_get_effective_risk_pct_tiers` — equity $50K returns 2%, $200K returns 1.5%, $800K returns 1.25%, $2M returns 1.0%
3. `test_get_effective_risk_pct_empty_tiers` — empty tiers returns base max
4. `test_get_current_equity` — starting_capital + closed P&L (mock DB)
5. `test_tier_transition_detection` — equity crosses from $99K to $101K triggers notification
6. `test_packet_template_uses_tiered_risk` — packet sizing reflects tier
7. `test_thorp_uses_tiered_base` — Thorp adjustment starts from tier value, not config static
8. `test_cascade_order` — tier → Thorp → TL → event risk all compose correctly

---

## Ralph Loop

### Iteration 1:
- Initial spec covered config + function + 3 call sites
- MISSED: interaction with Thorp drawdown — Thorp adjusts base_risk, which should
  be the TIER value not the config value. Fixed: Site 2 now calls get_effective_risk_pct
  before passing to drawdown_adjusted_risk
- MISSED: duplicate equity computation in executor — added get_current_equity helper

### Iteration 2:
- Live trade site (#3) raises a design question: should live use own tiers?
  Added decision note recommending shared tiers until live > $25K
- Added config validation to startup.py — tiers must be sorted, non-empty, bounded
- Added cascade diagram showing how tier interacts with existing adjustments

### Iteration 3:
- Added tier transition Telegram notification — operators need to know when risk changes
- Added display integration points (API + dashboard) — CTO Report should show active tier
- Added test for cascade order — verify the adjustment chain composes correctly
- Verified that get_effective_risk_pct returns a label alongside the value so
  logging and dashboards can display "tier: <$500K (1.5%)" without re-deriving it
