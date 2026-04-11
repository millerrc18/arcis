# IB Integration Smoke Test

> **When to run:** After all 7 IB sprints are merged to main
> **Time:** ~40 minutes
> **Requirements:** IB Gateway running on port 4002 (paper), watch loop available

## Prerequisites
- [ ] All IB sprints merged to main
- [ ] `git pull origin main` on local machine
- [ ] `pip install ib_async` (if not already installed)
- [ ] IB Gateway running on port 4002 (paper)
- [ ] `python -m src.main validate-schema --fix`
- [ ] `python scripts/validate_ib_integration.py` passes

## Phase 1: Shadow Mode (5 min)
- [ ] Set `ib.shadow_mode: true` in settings.local.yaml
- [ ] Start watch loop: `python -m src.main watch --email-mode silent`
- [ ] Wait for one scan cycle to complete
- [ ] Check: `SELECT COUNT(*) FROM ib_shadow_log` → should have entries
- [ ] Check: Alpaca paper trades still executing normally
- [ ] Stop watch loop (Ctrl+C)

## Phase 2: Dual Routing (10 min)
- [ ] Set `ib.shadow_mode: false`, `ib.paper_routing: true`, `paper_routing_threshold: 80`
- [ ] Start watch loop
- [ ] Wait for trades to generate (may need to wait for scan cycle)
- [ ] Check: `SELECT ticker, broker FROM shadow_trades WHERE status='open'`
  - High-score trades should have broker="ib"
  - Low-score trades should have broker="alpaca"
- [ ] Check: IB bracket trades have ib_child_order_ids populated
- [ ] Check: Dashboard shows both broker types on Shadow Ledger
- [ ] Stop watch loop

## Phase 3: IB Bracket Monitoring (15 min)
- [ ] With IB paper trades open, wait for bracket fills
- [ ] Check: Exit detected via IB child order status (not Alpaca)
- [ ] Check: P&L calculated correctly on close
- [ ] Check: reconciler handles IB positions correctly

## Phase 4: Failure Recovery (5 min)
- [ ] Stop IB Gateway while trades are open
- [ ] Wait for next scan cycle
- [ ] Check: Next trade falls back to Alpaca (broker="alpaca")
- [ ] Check: Warning logged: "IB Gateway down — falling back"
- [ ] Restart IB Gateway
- [ ] Check: Next high-score trade routes back to IB

## Phase 5: Dashboard Verification (5 min)
- [ ] Open dashboard
- [ ] Health page: IB Gateway status card shows Connected
- [ ] Shadow Ledger: broker column visible per trade
- [ ] IB Shadow page: shows shadow comparison data
- [ ] CTO Report: trade counts include both brokers

## Phase 6: Validation Scripts
- [ ] `python scripts/validate_ib_gateway.py` — all checks pass
- [ ] `python scripts/validate_ib_integration.py` — all checks pass

## Result
- [ ] All checks passed → IB integration validated, ready for 30-day stability gate
- [ ] Failures documented below:
  - 
