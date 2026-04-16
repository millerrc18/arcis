# Sprint: alpaca-py SDK migration (verification + optionality prep)

**Authority:** intraday feasibility report (`docs/research/deep-research/intraday-desk-feasibility-report.md`) Phase 1 decision #2
**Effort:** 1-2 hours (audit + optionality guardrails; **not** a rewrite)
**Branch:** `fix/alpaca-py-canonicalization` (follow-up sprint; spec written on `docs/alpaca-py-migration-spec`)
**Tag on merge:** patch bump (e.g. v0.22.1)
**Priority:** LOW (already shipped; spec documents the audit and pins the floor)

---

## Finding up-front — the migration is already done

A grep audit of the repo on 2026-04-16 shows:

- **Zero references** to the legacy `alpaca_trade_api` SDK anywhere in `src/`, `tests/`, or `requirements*.txt`.
- **`requirements.txt`** already pins `alpaca-py>=0.30,<1.0`.
- All current alpaca usage is via the modern `alpaca-py` packages:
  - `alpaca.trading.client.TradingClient`
  - `alpaca.trading.requests.{MarketOrderRequest, LimitOrderRequest, StopOrderRequest, GetOrdersRequest}`
  - `alpaca.trading.enums.{OrderSide, TimeInForce, OrderClass, QueryOrderStatus}`
  - `alpaca.data.historical.StockHistoricalDataClient`
  - `alpaca.data.requests.StockLatestTradeRequest`
  - `alpaca.common.exceptions.APIError`

The intraday feasibility report identified the legacy SDK as a migration risk because it was deprecated. The codebase has already moved to the modern SDK — either historically or as part of the broker-abstraction work for IB integration (`v0.14.0+`). This sprint's *execution* scope therefore collapses to verification + small guardrails.

---

## Goal

Turn the already-complete migration into a **documented, tested, version-pinned** state so:

1. Future intraday work (Phase 6) can rely on the modern SDK being the only Alpaca surface.
2. Accidental reintroduction of the legacy SDK is caught at CI time.
3. The two production surfaces (`src/shadow_trading/alpaca_adapter.py`, `src/shadow_trading/executor.py`) are audited against alpaca-py current best practices before intraday work begins.

---

## Pre-Flight Checks

```bash
# 1. Confirm zero legacy-SDK references.
grep -rn "alpaca_trade_api\|alpaca-trade-api" src/ tests/ requirements*.txt 2>/dev/null | head
# Expected: empty.

# 2. Enumerate current alpaca-py usage.
grep -rnE "^\s*(from|import)\s+alpaca" src/ tests/ --include="*.py" 2>/dev/null | awk -F: '{print $1}' | sort -u
# Expected: src/shadow_trading/alpaca_adapter.py, src/shadow_trading/executor.py,
# tests/test_executor_import.py.

# 3. Verify pinned version.
grep -iE "^alpaca" requirements*.txt
# Expected: alpaca-py>=0.30,<1.0 (or tighter pin).

# 4. Streaming usage — should be empty until Phase 6.
grep -rnE "TradingStream|StockDataStream" src/ --include="*.py" | grep -v test
# Expected: empty. Streaming is Phase 6 only.

# 5. Version check at runtime.
python -c "import alpaca; print('alpaca-py version:', alpaca.__version__)"
# Expected: >= 0.30.0
```

If any pre-flight fails, stop and reclassify the sprint from "verification" to "migration."

---

## Current alpaca-py Usage Map

### `src/shadow_trading/alpaca_adapter.py` (primary broker surface)

| Line | Import | Purpose |
|---|---|---|
| 143 | `TradingClient` | Account, positions, order lifecycle |
| 154 | `StockHistoricalDataClient` | Historical OHLCV lookups |
| 186–187 | `MarketOrderRequest, LimitOrderRequest, OrderSide, TimeInForce` | Bracket entry order construction |
| 224–225 | `MarketOrderRequest, OrderSide, TimeInForce` | Exit order submission |
| 279–280 | `MarketOrderRequest, LimitOrderRequest, OrderSide, TimeInForce, OrderClass` | Bracket order (parent + stop + target) |
| 370 | `StockLatestTradeRequest` | Real-time price probe |
| 460 | `GetOrdersRequest` | Order query by status |
| 537 | `TradingClient` | Separate connection for live trading context |
| 580–581 | `MarketOrderRequest, OrderSide, TimeInForce` | Live-order path |
| 652–653 | `MarketOrderRequest, OrderSide, TimeInForce` | Cancel-and-close pattern |

### `src/shadow_trading/executor.py` (execution orchestration)

| Line | Import | Purpose |
|---|---|---|
| 41 | `APIError` (top-level) | Typed exception handling across all Alpaca calls |
| 693 | `StopOrderRequest` | Secondary stop order for brackets |
| 694 | `OrderSide, TimeInForce` | Stop-order construction |

### `tests/test_executor_import.py`

| Line | Import | Purpose |
|---|---|---|
| 43, 59 | `APIError` | Exception-handling test surface |

**Total:** 2 source files + 1 test file. All usage is synchronous (no `asyncio`), which is appropriate for the current swing-trade cadence. Streaming (`TradingStream`, `StockDataStream`) is **intentionally absent** — it's a Phase 6 intraday concern per the feasibility report.

---

## Task List

### Task 1 — Pin alpaca-py version tighter

**File:** `requirements.txt`

Current: `alpaca-py>=0.30,<1.0`

Change to: `alpaca-py>=0.33,<1.0` (or whatever is currently installed and tested locally; check via `pip show alpaca-py`). Rationale: the `>=0.30` floor is older than what production runs on, and a too-open range means CI can pull a differently-behaving version than the dev machine.

**Constraint:** Do NOT bump past `1.0` in this sprint — the 1.0 release will likely contain breaking changes and needs its own sprint.

### Task 2 — Guardrail test: no legacy SDK imports

**File:** `tests/test_repo_structure.py` (extend) **or** `tests/trading/test_alpaca_sdk_guard.py` (new, if subdir exists; otherwise extend the existing structure test).

Add a test that grepgs src/ and tests/ for any `alpaca_trade_api` import and asserts zero matches. This prevents accidental reintroduction when CC or a human pastes old code from an LLM session.

```python
def test_no_legacy_alpaca_trade_api_imports():
    """SD#41 follow-up — legacy alpaca-trade-api SDK is deprecated; we use alpaca-py."""
    import subprocess
    result = subprocess.run(
        ["grep", "-rn", "--include=*.py",
         "alpaca_trade_api", "src/", "tests/"],
        capture_output=True, text=True
    )
    assert result.stdout.strip() == "", (
        f"Legacy alpaca_trade_api import detected:\n{result.stdout}"
    )
```

Alternative (no subprocess): walk `src/` and `tests/` in Python, parse imports via `ast`, assert no module starts with `alpaca_trade_api`.

### Task 3 — Per-call-site audit of current alpaca-py usage

**Deliverable:** Checklist document `docs/research/alpaca-py-current-best-practices-audit.md`.

For each of the 10 imports in `alpaca_adapter.py`, verify:

- Request object construction uses the modern pattern (`MarketOrderRequest(symbol=...)` not dict-based)
- `TradingClient(paper=True)` is explicit about paper vs live
- Exception handling uses `APIError` specifically, not bare `Exception`
- `client_order_id` is set for idempotency where applicable
- Enums are used (`OrderSide.BUY`) not string literals (`"buy"`)

No code changes in this sprint unless the audit finds a bug. Any findings flagged as follow-up tickets.

### Task 4 — Streaming readiness note for Phase 6

**File:** `docs/research/alpaca-py-intraday-streaming-gap.md` (new, ~1 page).

Document which streaming classes will be needed for Phase 6 and the expected integration points. The goal is to make future Phase 6 work mechanical rather than architectural:

- `alpaca.trading.stream.TradingStream` — order + fill events
- `alpaca.data.live.stock.StockDataStream` — minute bars, quotes
- Connection lifecycle (subscribe/unsubscribe per ticker, reconnect behavior)
- Where in the existing codebase the handlers would attach (waits on asyncio refactor sprint — see `sprint-asyncio-handler-refactor.md`)

**This is documentation only. No code.**

### Task 5 — Update CHANGELOG + release notes

- `CHANGELOG.md` — a `### Verified / Documented` entry under the next patch release noting the audit outcome.
- `MASTER.md` Section 11 Infrastructure Prep — change the `alpaca-py SDK migration` row from `SPEC WRITTEN` to `VERIFIED COMPLETE (audit only, no code change needed)` once this sprint ships.

---

## Backward Compatibility

No runtime behavior changes. The CI guardrail test will catch any regression, but existing trades, existing brackets, and all Alpaca-touching paths stay on the modern SDK they already use.

---

## Test Plan

- New test `test_no_legacy_alpaca_trade_api_imports` must pass.
- Existing tests must not regress:
  - `tests/test_executor_import.py` (4 tests) — import smoke test
  - `tests/test_broker_interface.py` (19 tests) — SD#41 IB tests
  - `tests/test_live_trading.py` (~15 tests) — IB shadow + paper routing
  - `tests/test_alpaca_*` if any (grep to confirm)

Any behavior-level test that exercises Alpaca should use the existing `mock_alpaca` fixture pattern; do NOT introduce new network dependencies in tests.

---

## Success Criteria

1. `grep -rn 'alpaca_trade_api' src/ tests/` returns empty (verified via new test).
2. `requirements.txt` pins alpaca-py to a tighter floor.
3. `docs/research/alpaca-py-current-best-practices-audit.md` exists with per-call-site findings (pass or action item).
4. `docs/research/alpaca-py-intraday-streaming-gap.md` exists with the Phase 6 readiness note.
5. MASTER.md Section 11 Infrastructure Prep row updated.
6. Full pytest — no regressions. Net +1 passing test (the new guardrail).

---

## Out-of-Scope

- Implementing `TradingStream` / `StockDataStream` handlers (Phase 6 sprint).
- Bumping alpaca-py past 1.0 (separate sprint when 1.0 ships).
- Refactoring `alpaca_adapter.py` for organization/readability (the structure is fine; splitting it touches too much of the execution path).
- Changing `TradingClient` singleton vs per-request pattern (no evidence a change is needed).
- Rewriting the IB broker (SD#41 IB cold storage keeps IB dormant; see `sprint-ib-cold-storage.md`).

---

## Research Notes

**Why the "migration" was already done:** it likely landed incrementally during the IB broker abstraction work (`v0.14.0 IB integration`). The broker-interface abstraction required a clean Alpaca wrapper, which was easier to build against the modern SDK than to retrofit the legacy one. The legacy SDK would also have forced either a second-broker-style adapter or a messy try/except around deprecation warnings.

**Version choice (>=0.33):** Alpaca deprecated `alpaca-trade-api` in 2022 and the 0.30 series of `alpaca-py` is broadly stable. 0.33+ includes consistent typing on Order responses and fixes around bracket order response shapes (per Alpaca's GitHub changelog). Confirm the currently-installed version before pinning.

**Intraday Phase 6 dependency:** both `TradingStream` (for fills) and `StockDataStream` (for bars/quotes) are in current alpaca-py. Phase 6 adds handlers; no SDK-level change needed. The asyncio handler refactor (separate spec) is the architectural prerequisite.

---

## Commit Messages (for the follow-up execution sprint)

```
chore(deps): tighten alpaca-py pin to >=0.33,<1.0
test: guardrail against legacy alpaca-trade-api re-introduction
docs: per-call-site alpaca-py best-practices audit
docs: alpaca-py intraday streaming readiness note
docs: MASTER.md — verify alpaca-py migration complete
```
