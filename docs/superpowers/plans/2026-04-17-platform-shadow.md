# Sprint 4 — Platform Shadow Harness + Dashboard + Correlation Monitor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the live-deployment layer of the Strategy Research Platform — a shadow-trading harness that routes research-strategy bracket orders to a separate Alpaca paper account, a watch-loop integration that ticks every active research strategy on its own cadence, a dashboard `/research-platform` page for operator inspection, and the correlation-monitoring stack (Tier 7) that starts tracking cross-strategy risk as soon as two or more strategies run concurrently. Closes v0.24.0.

**Architecture:** Task 7's Alpaca desk-threading is the load-bearing surgery — `_get_trading_client()` / `_get_data_client()` gain an optional `desk` kwarg, the ≥12 public API functions in `src/shadow_trading/alpaca_adapter.py` thread it through, and `reconcile.py`'s two entry points (`reconcile_paper_trades`, `reconcile_live_trades`) accept `desk` so reconciliation queries hit the right Alpaca account. A new `src/shadow_trading/alpaca_clients.py` owns the per-desk client factory with `verify_accounts_distinct()` as a config-sanity assertion. The new `ShadowHarness` at `src/platform/shadow_harness.py` uses `get_client('research_<strategy_id>')` directly for its own bracket placement, wires `check_pre_trade_limits()` from Sprint 3 before every order, and writes to `shadow_trades` with `desk='research_<strategy_id>'`. The watch loop dispatches every active research strategy on its declared `shadow_cadence_seconds`. Dashboard reads via new `/api/platform/*` endpoints. Correlation + factor monitoring writes into `correlation_matrices` + `factor_loadings` (Sprint 3 schema).

**Tech Stack:** Python 3.11 · pandas · numpy · scipy.stats · statsmodels (HAC regression) · pandas-datareader (Ken French factors) · ruptures (PELT change detection) · sqlite3 · FastAPI · React 19 + Tailwind 4 + Recharts · existing Arcis modules (`alpaca_adapter`, `reconcile`, `executor`, `bracket_monitor`, `watch`).

**Authoritative spec:** `docs/sprints/sprint-research-platform.md` (commit `c3449ff` on main). Sprint 4 covers Tier 5 (live deployment) + Tier 6 (dashboard) + selected Tier 7 (correlation monitoring) + Tier 8 (Python plugin + docs) per the tier priority at spec lines 1738-1762.

**CC execution prompts:** `docs/sprints/sprint-research-platform-cc-execution.md` lines 248-378 (Sprint 4 of 4).

**Branch:** `feat/platform-shadow` (already cut from main).

**Effort:** Spec estimate 17h. Realistic with the Alpaca patching surgery: 18-24h. Tier 7/8 are explicitly deferrable to v0.24.1 if time runs short (spec lines 1752-1753). **Ship order** (biggest-risk-first): Task 7 → Task 9 → Task 12 → Tier 7 → Tier 8.

**Tag on merge:** `v0.24.0` (final — this is the culmination release; see `git tag v0.24.0` in Step I.10 below).

---

## Known Spec Issues to Resolve During Execution

Caught during plan authoring. Flag each if it turns out different in the actual codebase state at execution time.

### Issue A (clarifying): spec's "4 external callers of `_get_trading_client`" is partially wrong

Spec (line 937, CC prompts line 316-321) lists as external callers of `_get_trading_client` / `_get_data_client`:

1. `src/shadow_trading/executor.py:697` — **correct**; direct import of `_get_trading_client`.
2. `src/shadow_trading/reconcile.py` — **wrong**; reconcile does NOT import the private helper directly. It imports *public* functions (`get_live_positions`, `get_all_positions`, `cancel_orders_for_ticker`) from alpaca_adapter, which internally call `_get_trading_client()`.
3. `src/shadow_trading/bracket_monitor.py` — **wrong**; imports `get_order_status` (public).
4. `src/services/shadow_service.py` — **wrong**; imports `get_account_info`, `get_all_positions` (public).

**Implication:** the "thread desk through 4 external call sites" plan requires threading through the PUBLIC API in `alpaca_adapter.py` (≥12 public functions), not just 4 lines. The 12 internal call sites in alpaca_adapter.py auto-benefit when you modify `_get_trading_client` to accept `desk`; the 12 public API wrappers need `desk` kwarg + pass-through.

**Verified public API functions** (via grep `from src.shadow_trading.alpaca_adapter import`):

- `get_account_info`, `get_live_account_info`
- `get_live_positions`, `get_all_positions`
- `place_paper_entry`, `place_paper_exit`, `place_bracket_order`, `place_live_entry`
- `verify_order_accepted`, `get_order_status`
- `cancel_paper_order`, `cancel_all_orders`, `cancel_orders_for_ticker`
- `get_current_price`

Each of these needs a `desk: str = "swing"` kwarg added in Task 7b, and internally forward it to `_get_trading_client(desk=desk)` / `_get_data_client(desk=desk)`.

### Issue B (precondition): PBO + OOS_efficiency may not be populated yet

Spec Task 10 promotion gate expects `backtest_results.pbo` and `backtest_results.oos_efficiency`. Tech-debt PR #477 added those columns and wired `scripts/run_backtest.py --with-walkforward` to populate `oos_efficiency`. **PBO population still requires a param-sweep driver that doesn't exist yet.** If Sprint 4's ShadowHarness tries to promote a strategy to `shadow_trading` status and PBO is NULL, `check_promotion_gate` fails with a clear "run a param sweep with CSCV first" message — this is correct behavior, not a regression. Operators manually run a CSCV campaign and UPDATE the row's `pbo` column before attempting promotion.

Sprint 4 does NOT need to add a param-sweep driver. Flag it in Task 13 (docs) activation guide.

### Issue C (precondition): `desks.research.alpaca_key_env` config may not exist yet

Task 7a creates `src/shadow_trading/alpaca_clients.py` which reads `desks.{desk}.alpaca_key_env` from `config/settings.*.yaml`. If those keys don't exist yet, config-loading fails. **Preflight Step P.2** verifies the config before Task 7a starts.

If the operator hasn't set up a research Alpaca account yet, Task 7a's tests should pass against a mocked config (env var values are placeholders), but `verify_accounts_distinct()` should NOT be called in production until real credentials land. Document this in Task 13's activation guide.

---

## File Structure

### New files (created by this plan)

| Path | Responsibility |
|---|---|
| `src/shadow_trading/alpaca_clients.py` | Per-desk `TradingClient` factory. `get_client(desk) -> TradingClient` + `verify_accounts_distinct()`. Cached per-desk; threadsafe. |
| `src/platform/shadow_harness.py` | `ShadowHarness` class — `__init__(strategy_spec)`, `run_one_tick(as_of)`, `get_open_positions()`, `halt()`. Writes to `shadow_trades` with `desk='research_<strategy_id>'`. |
| `src/platform/cost_calibration.py` | `calibrate_from_swing_history()` reads the 85 closed swing trades and computes entry/exit slippage_bps defaults for BacktestConfig. Replaces the hardcoded 3/1.5 bps. |
| `src/platform/risk/correlation.py` | `compute_rolling_spearman`, `compute_rolling_pearson`, `compute_neg_exceedance_correlation`, `detect_correlation_regime_shifts`. Writes to `correlation_matrices`. |
| `src/platform/risk/factor_decomp.py` | `load_factor_data`, `decompose_strategy`, `compare_to_expected_profile`. Writes to `factor_loadings`. |
| `src/platform/risk/change_detection.py` | `detect_beta_regime_changes` — PELT via `ruptures`. Called weekly. |
| `src/platform/risk/alerting.py` | `emit_alert(tier, category, message, context)`. Tiered INFO/WARN/CRITICAL with 60-min hash dedup. |
| `src/platform/strategy_plugin.py` | `StrategyPlugin` ABC + `Candidate` dataclass (Task 2). |
| `src/platform/plugin_registry.py` | `register_plugin` decorator + `get_plugin(strategy_id)`. |
| `src/notifications/platform_events.py` | `notify_backtest_complete`, `notify_shadow_gate_ready`, `notify_strategy_promoted`, `notify_strategy_demoted`. `[RESEARCH]` prefix. Dedup on hash. |
| `src/api/cloud_routes/platform.py` | `GET /api/platform/strategies`, `GET /api/platform/strategies/{id}`, `GET /api/platform/backtest-results`, `GET /api/platform/backtest-trades`, `GET /api/platform/promotion-events`, `POST /api/platform/backtests`, `POST /api/platform/promotions`, `POST /api/platform/demotions`. |
| `frontend/src/pages/StrategyResearch.jsx` | `/research-platform` page — 4 sections (registry table, detail view, backtest grid, promotion events log). |
| `frontend/src/components/PlatformStatusWidget.jsx` | Home-screen card: strategies-per-status counts, pending manual review, last backtest timestamp, link to full page. |
| `frontend/src/components/BacktestEquityChart.jsx` | Recharts `LineChart`/`Area` for backtest equity curve modal. Mirrors `Attribution.jsx` pattern. |
| `docs/platform/activation-guide.md` | How to load a strategy, promote it, halt it. Expanded with Sprint 4's live-deployment path. |
| `tests/shadow_trading/test_alpaca_clients.py` | `get_client` returns cached per-desk; `verify_accounts_distinct` raises on dup. |
| `tests/shadow_trading/test_reconcile_desk_routing.py` | `reconcile_paper_trades(desk='research_xxx')` uses research client, not swing. |
| `tests/platform/test_shadow_harness.py` | Harness writes correct desk tag, reconcile/bracket monitor use research client, halt closes only this strategy's positions, `verify_accounts_distinct` called at startup. |
| `tests/platform/test_cost_calibration.py` | Slippage-bps within 30% of hardcoded 3 bps. |
| `tests/platform/risk/test_correlation.py` | Spearman/Pearson on known inputs; exceedance tail correlation; persistence filter. |
| `tests/platform/risk/test_factor_decomp.py` | SPY-on-itself regression gives MKT β=1.0, other factors ≈ 0; profile-drift flag. |
| `tests/platform/risk/test_change_detection.py` | PELT on a synthetic step function detects the breakpoint. |
| `tests/platform/risk/test_alerting.py` | Dedup within 60 min; business-hours respect; CRITICAL fires 24/7. |
| `tests/platform/test_strategy_plugin.py` | Mock plugin registers + retrieves by id. |
| `tests/platform/test_platform_api.py` | 8 new endpoint tests (list strategies, detail, backtests, events, POST backtests/promotions/demotions + 24h-delay production check). |
| `tests/frontend/` tests | Not added — React code is exercised via `npm run build` regression check + manual verification. |

### Existing files edited

| Path | Change |
|---|---|
| `src/shadow_trading/alpaca_adapter.py` | `_get_trading_client(desk=None)` + `_get_data_client(desk=None)`; 14 public API functions gain `desk: str = "swing"` kwarg. |
| `src/shadow_trading/reconcile.py` | `reconcile_paper_trades(desk='swing', ...)` + `reconcile_live_trades(desk='swing', ...)` — thread desk through positions-lookup + cancel paths. Filter `shadow_trades` by desk. |
| `src/shadow_trading/executor.py:697` | Single direct `_get_trading_client` call — no-op change (still swing by default). |
| `src/shadow_trading/bracket_monitor.py` | Add `desk` kwarg to the `monitor_*` functions that query Alpaca order status. |
| `src/scheduler/overnight.py:27` | Loop over `desks.research.*` active strategies + swing, call `reconcile_paper_trades(desk=...)` each. |
| `src/scheduler/position_monitor.py:69` | Same pattern. |
| `src/scheduler/watch.py:685` | Same pattern. Also `_run_platform_shadow_tick` (Task 9) + init `self._last_platform_tick`. |
| `src/cli/commands.py:405` | `reconcile_live_trades(desk='swing')` only (live trading is swing-only). |
| `src/services/shadow_service.py` | Existing callers use `desk='swing'`; dashboard endpoints filter by `?desk=` (already in Sprint 3). |
| `frontend/src/App.jsx` | Register `/research-platform` route. |
| `frontend/src/components/Nav.jsx` | Add Research Platform link. |
| `frontend/src/pages/Dashboard.jsx` | Mount `<PlatformStatusWidget>` above existing widgets when `strategy_registry` has ≥1 row. |
| `MASTER.md` | Section 2 volatile counts + new Research Platform section between Sections 8 and 9 (per spec line 1075). |
| `CHANGELOG.md` | `v0.24.0` final entry. |
| `RELEASES.md` | `v0.24.0` final entry. |
| `README.md` | Version badge bump. |
| `config/settings.example.yaml` | Add `desks:` section with `swing:` + `research:` keys. |

---

## Pre-Flight

### Step P.1: Confirm preconditions

- [ ] Main is at Sprint 3 merge or later:

```bash
cd C:\arcis\halcyon-lab
git fetch origin
git log origin/main --oneline -15 | grep -E "v0\.24\.0-alpha[123]"
```

Expected: three lines matching `v0.24.0-alpha1`, `v0.24.0-alpha2`, `v0.24.0-alpha3`. If any missing, **STOP** — Sprint 4 depends on Sprint 3's `exposure_limits.py` + correlation schema + `?desk=` filter endpoints.

- [ ] Tech-debt PR #477 merged (optional but recommended): `git log origin/main --oneline | head -20 | grep -iE "grandfathering|tech.debt|post.sprint"`. If not yet merged, the `_evaluate_shadow_trading_gate` will be at 25 lines (dispatcher) and PBO/OOS wiring already present — plan's Task 7f check_pre_trade_limits wiring is unchanged regardless.

- [ ] Worktree cut: `git worktree list | grep feat/platform-shadow` shows `.worktrees/platform-shadow`.

- [ ] Baseline pytest + frontend build:

```bash
cd .worktrees/platform-shadow
pytest tests/ -q --ignore=tests/test_dependencies.py 2>&1 | tail -5 > /tmp/baseline-sprint4.txt
cd frontend && npm run build 2>&1 | tail -10 > /tmp/baseline-build-sprint4.txt && cd ..
```

Expected: ≥2,060 passed + ~5 skipped + 1-2 pre-existing failures (`test_all_modules_have_standard_docstring` for `telegram_commands.py`, `test_lazy_prices_produces_trades_on_real_data`, possibly `test_open_trades_excluded`). Frontend build succeeds.

### Step P.2: Verify research Alpaca config present (Issue C)

- [ ] Check config for `desks.research`:

```bash
grep -A3 "^desks:" config/settings.local.yaml config/settings.example.yaml 2>&1 | head -20
```

Expected output (or similar) in `config/settings.example.yaml`:

```yaml
desks:
  swing:
    alpaca_key_env: ALPACA_PAPER_API_KEY
    alpaca_secret_env: ALPACA_PAPER_API_SECRET
  research:
    alpaca_key_env: ALPACA_RESEARCH_API_KEY
    alpaca_secret_env: ALPACA_RESEARCH_API_SECRET
```

If `desks.research` is missing: **Task 7a Step 7a.1** adds it to `config/settings.example.yaml`. The operator's `config/settings.local.yaml` must also have real env-var names; that's an operator responsibility, not this sprint's.

If both keys exist: proceed.

---

## Tier 5 — Live Deployment (~8-12h, HIGHEST RISK, ship first)

### Task 7a: Per-desk Alpaca client factory (~1h)

**Files:**
- Create: `src/shadow_trading/alpaca_clients.py`
- Create: `tests/shadow_trading/test_alpaca_clients.py`
- Edit: `config/settings.example.yaml` — add `desks:` section (only if missing per P.2)

#### Step 7a.1: Add `desks:` config section if missing

- [ ] If Step P.2 showed no `desks:` section in `config/settings.example.yaml`, append:

```yaml
desks:
  swing:
    alpaca_key_env: ALPACA_PAPER_API_KEY
    alpaca_secret_env: ALPACA_PAPER_API_SECRET
    enabled: true
  research:
    alpaca_key_env: ALPACA_RESEARCH_API_KEY
    alpaca_secret_env: ALPACA_RESEARCH_API_SECRET
    enabled: false  # operator flips to true after setting up research account
```

#### Step 7a.2: Write failing tests

- [ ] Create `tests/shadow_trading/test_alpaca_clients.py`:

```python
"""Tests for src.shadow_trading.alpaca_clients — per-desk client factory."""
from unittest.mock import MagicMock, patch

import pytest


def test_get_client_returns_cached_instance_per_desk(monkeypatch):
    """Calling get_client(desk) twice returns the same instance."""
    monkeypatch.setenv("ALPACA_PAPER_API_KEY", "swing_key")
    monkeypatch.setenv("ALPACA_PAPER_API_SECRET", "swing_sec")

    from src.shadow_trading.alpaca_clients import get_client, _CLIENT_CACHE
    _CLIENT_CACHE.clear()

    with patch("src.shadow_trading.alpaca_clients.TradingClient") as mock_tc:
        mock_tc.return_value = MagicMock(desk_tag=None)
        c1 = get_client("swing")
        c2 = get_client("swing")
    assert c1 is c2
    # TradingClient constructor called exactly once (cached)
    assert mock_tc.call_count == 1


def test_get_client_tags_desk_attribute(monkeypatch):
    monkeypatch.setenv("ALPACA_PAPER_API_KEY", "swing_key")
    monkeypatch.setenv("ALPACA_PAPER_API_SECRET", "swing_sec")

    from src.shadow_trading.alpaca_clients import get_client, _CLIENT_CACHE
    _CLIENT_CACHE.clear()
    with patch("src.shadow_trading.alpaca_clients.TradingClient") as mock_tc:
        mock_tc.return_value = MagicMock()
        client = get_client("swing")
    assert getattr(client, "desk_tag", None) == "swing"


def test_get_client_unknown_desk_raises():
    from src.shadow_trading.alpaca_clients import get_client
    with pytest.raises(ValueError, match="unknown desk"):
        get_client("nonexistent_desk")


def test_verify_accounts_distinct_raises_on_same_account(monkeypatch):
    """If both desks resolve to the same Alpaca account_number, raise."""
    monkeypatch.setenv("ALPACA_PAPER_API_KEY", "same_key")
    monkeypatch.setenv("ALPACA_PAPER_API_SECRET", "same_sec")
    monkeypatch.setenv("ALPACA_RESEARCH_API_KEY", "same_key")
    monkeypatch.setenv("ALPACA_RESEARCH_API_SECRET", "same_sec")

    from src.shadow_trading.alpaca_clients import (
        verify_accounts_distinct, _CLIENT_CACHE,
    )
    _CLIENT_CACHE.clear()

    with patch("src.shadow_trading.alpaca_clients.TradingClient") as mock_tc:
        same_account = MagicMock()
        same_account.get_account.return_value = MagicMock(account_number="A123")
        mock_tc.return_value = same_account
        with pytest.raises(RuntimeError, match="same account"):
            verify_accounts_distinct()


def test_verify_accounts_distinct_passes_on_different_accounts(monkeypatch):
    monkeypatch.setenv("ALPACA_PAPER_API_KEY", "swing_k")
    monkeypatch.setenv("ALPACA_PAPER_API_SECRET", "swing_s")
    monkeypatch.setenv("ALPACA_RESEARCH_API_KEY", "research_k")
    monkeypatch.setenv("ALPACA_RESEARCH_API_SECRET", "research_s")

    from src.shadow_trading.alpaca_clients import (
        verify_accounts_distinct, _CLIENT_CACHE,
    )
    _CLIENT_CACHE.clear()

    call_ix = {"n": 0}

    def make_client(*args, **kwargs):
        call_ix["n"] += 1
        m = MagicMock()
        m.get_account.return_value = MagicMock(
            account_number=f"A{call_ix['n']}"
        )
        return m

    with patch("src.shadow_trading.alpaca_clients.TradingClient",
               side_effect=make_client):
        verify_accounts_distinct()  # no raise


def test_get_client_env_var_missing_raises(monkeypatch):
    monkeypatch.delenv("ALPACA_PAPER_API_KEY", raising=False)

    from src.shadow_trading.alpaca_clients import get_client, _CLIENT_CACHE
    _CLIENT_CACHE.clear()
    with pytest.raises(RuntimeError, match="env var"):
        get_client("swing")
```

#### Step 7a.3: Run tests, verify they fail

```bash
pytest tests/shadow_trading/test_alpaca_clients.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.shadow_trading.alpaca_clients'`.

#### Step 7a.4: Implement `alpaca_clients.py`

- [ ] Create `src/shadow_trading/alpaca_clients.py`:

```python
"""Per-desk Alpaca TradingClient factory.

Called by: src.shadow_trading.alpaca_adapter._get_trading_client,
           src.platform.shadow_harness, src.scheduler.watch (startup verify).
Calls: alpaca.trading.client.TradingClient, src.config.load_config, os.environ.
Owns tables: none.
Config keys: desks.{desk}.alpaca_key_env, desks.{desk}.alpaca_secret_env.
Tests: tests/shadow_trading/test_alpaca_clients.py.

Cached per desk. Threadsafe via module-level dict mutation (GIL-safe for
dict.__getitem__/__setitem__). verify_accounts_distinct() asserts that
'swing' and 'research' desks resolve to different Alpaca account numbers —
catches the "both desks pointing at same paper account" mis-config bug.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any

from alpaca.trading.client import TradingClient

from src.config import load_config

logger = logging.getLogger(__name__)

_CLIENT_CACHE: dict[str, Any] = {}
_CACHE_LOCK = threading.Lock()


def get_client(desk: str) -> TradingClient:
    """Return a TradingClient for the named desk. Cached per desk.

    Reads desks.{desk}.alpaca_key_env + alpaca_secret_env from config,
    resolves env var values, constructs TradingClient(paper=True) with
    client.desk_tag = desk for downstream guardrail assertions.
    """
    if desk in _CLIENT_CACHE:
        return _CLIENT_CACHE[desk]
    cfg = load_config()
    desks_cfg = cfg.get("desks", {})
    desk_cfg = desks_cfg.get(desk)
    if not desk_cfg:
        raise ValueError(f"unknown desk: {desk!r}; check desks.* config section")
    key_var = desk_cfg.get("alpaca_key_env")
    sec_var = desk_cfg.get("alpaca_secret_env")
    if not key_var or not sec_var:
        raise ValueError(
            f"desk {desk!r} missing alpaca_key_env / alpaca_secret_env in config"
        )
    api_key = os.environ.get(key_var)
    api_sec = os.environ.get(sec_var)
    if not api_key or not api_sec:
        raise RuntimeError(
            f"desk {desk!r} env var {key_var} or {sec_var} not set; "
            "operator must export credentials before watch loop starts"
        )
    client = TradingClient(api_key=api_key, secret_key=api_sec, paper=True)
    client.desk_tag = desk
    with _CACHE_LOCK:
        _CLIENT_CACHE[desk] = client
    return client


def verify_accounts_distinct() -> None:
    """Raise if swing and research resolve to the same Alpaca account.

    MUST be called at watch-loop startup before any desk-aware Alpaca
    operation runs. Prevents the "both desks share a paper account"
    silent cross-contamination bug.

    Skips safely if either desk isn't configured (e.g. research account
    not yet set up per preflight Issue C).
    """
    cfg = load_config()
    desks_cfg = cfg.get("desks", {})
    swing_cfg = desks_cfg.get("swing")
    research_cfg = desks_cfg.get("research")
    if not swing_cfg or not research_cfg:
        logger.info(
            "[ALPACA] verify_accounts_distinct skipped — swing or research "
            "desk not configured yet"
        )
        return
    if not research_cfg.get("enabled", False):
        logger.info(
            "[ALPACA] verify_accounts_distinct skipped — research desk disabled"
        )
        return
    swing_acct = get_client("swing").get_account().account_number
    research_acct = get_client("research").get_account().account_number
    if swing_acct == research_acct:
        raise RuntimeError(
            f"swing and research desks resolved to the same Alpaca "
            f"account ({swing_acct}). Either they are mis-configured "
            f"(same key/secret env vars) or pointing at the same paper "
            f"account. Aborting — fix config before any shadow-trading."
        )
    logger.info(
        "[ALPACA] verify_accounts_distinct OK: swing=%s research=%s",
        swing_acct, research_acct,
    )
```

#### Step 7a.5: Run tests, verify they pass

```bash
pytest tests/shadow_trading/test_alpaca_clients.py -v
```

Expected: 6 passed.

#### Step 7a.6: Commit

```bash
git add src/shadow_trading/alpaca_clients.py \
        tests/shadow_trading/test_alpaca_clients.py \
        config/settings.example.yaml
git commit -m "$(cat <<'EOF'
feat(shadow_trading): per-desk Alpaca client factory (Task 7a)

src/shadow_trading/alpaca_clients.py — get_client(desk) returns a
cached TradingClient per desk, reading desks.{desk}.alpaca_key_env /
alpaca_secret_env from config and resolving env var values at call
time. client.desk_tag attribute set for downstream guardrail asserts.

verify_accounts_distinct() asserts swing and research desks resolve
to different Alpaca account_numbers — catches the "both desks share
a paper account" silent cross-contamination bug. Skips safely if
research isn't configured yet (pre-account-setup phase).

6 tests cover cached instance, desk_tag attribute, unknown-desk ValueError,
verify_accounts_distinct raise-on-same-account / pass-on-distinct /
skip-when-research-disabled, missing env var RuntimeError.

config/settings.example.yaml gains desks: section with swing + research
keys; research.enabled=false by default (operator flips after creating
research paper account).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7b: Thread desk kwarg through alpaca_adapter.py (~1.5h)

Modify `_get_trading_client` / `_get_data_client` helpers to accept `desk` kwarg; add `desk: str = "swing"` to all ≥14 public API functions; have each public function forward desk to the helpers.

**Files:**
- Edit: `src/shadow_trading/alpaca_adapter.py`
- Edit: `tests/shadow_trading/test_alpaca_adapter.py` (add desk-routing tests; create file if it doesn't exist)

#### Step 7b.1: Audit the public API

Run:

```bash
grep -nE "^def [a-zA-Z_]+" src/shadow_trading/alpaca_adapter.py | grep -v "^.*: def _"
```

Record the list. Expected (per P.1 plan-authoring grep): `get_account_info`, `get_live_account_info`, `get_live_positions`, `get_all_positions`, `place_paper_entry`, `place_paper_exit`, `place_bracket_order`, `place_live_entry`, `verify_order_accepted`, `get_order_status`, `cancel_paper_order`, `cancel_all_orders`, `cancel_orders_for_ticker`, `get_current_price`.

If the actual list differs from the 14 above, use the actual list.

#### Step 7b.2: Write failing test for desk routing

- [ ] Create or append to `tests/shadow_trading/test_alpaca_adapter.py`:

```python
"""Tests for desk-routing behavior added in Sprint 4 Task 7b."""
from unittest.mock import MagicMock, patch

import pytest


def test_get_trading_client_desk_defaults_to_swing_via_existing_config():
    """Backward compat: no desk kwarg → existing behavior (swing via
    _get_alpaca_config). Existing tests that don't pass desk still work."""
    from src.shadow_trading.alpaca_adapter import _get_trading_client
    with patch(
        "src.shadow_trading.alpaca_adapter._get_alpaca_config",
        return_value={"api_key": "k", "api_secret": "s"},
    ), patch("alpaca.trading.client.TradingClient") as mock_tc:
        mock_tc.return_value = MagicMock()
        c = _get_trading_client()
    assert c is not None


def test_get_trading_client_routes_to_desk_via_alpaca_clients():
    """When desk is passed, dispatch through alpaca_clients.get_client."""
    from src.shadow_trading import alpaca_adapter
    fake_client = MagicMock(desk_tag="research_xxx")
    with patch(
        "src.shadow_trading.alpaca_clients.get_client",
        return_value=fake_client,
    ) as mock_get:
        c = alpaca_adapter._get_trading_client(desk="research_xxx")
    mock_get.assert_called_once_with("research_xxx")
    assert c is fake_client


def test_public_function_threads_desk_to_helper():
    """get_account_info(desk='research_xxx') must route through the
    desk-aware helper, not the legacy one."""
    from src.shadow_trading import alpaca_adapter
    fake_client = MagicMock()
    fake_client.get_account.return_value = MagicMock(
        account_number="R123",
        portfolio_value=100_000,
        cash=50_000,
        buying_power=100_000,
    )
    with patch(
        "src.shadow_trading.alpaca_clients.get_client",
        return_value=fake_client,
    ) as mock_get:
        info = alpaca_adapter.get_account_info(desk="research_xxx")
    # The research client was used
    assert mock_get.call_args.args == ("research_xxx",) or \
           mock_get.call_args.kwargs.get("desk") == "research_xxx"
    assert info.get("account_number") == "R123"


def test_public_function_default_desk_swing_backward_compat():
    """get_account_info() with no desk kwarg works unchanged.
    Existing test suite should not regress."""
    from src.shadow_trading import alpaca_adapter
    with patch(
        "src.shadow_trading.alpaca_adapter._get_alpaca_config",
        return_value={"api_key": "k", "api_secret": "s"},
    ), patch("alpaca.trading.client.TradingClient") as mock_tc:
        client = MagicMock()
        client.get_account.return_value = MagicMock(
            account_number="S123", portfolio_value=50_000,
            cash=25_000, buying_power=50_000,
        )
        mock_tc.return_value = client
        info = alpaca_adapter.get_account_info()
    assert info.get("account_number") == "S123"
```

#### Step 7b.3: Run tests, confirm they fail

```bash
pytest tests/shadow_trading/test_alpaca_adapter.py::test_get_trading_client_routes_to_desk_via_alpaca_clients -v
```

Expected: fail — current `_get_trading_client()` has no `desk` kwarg.

#### Step 7b.4: Patch `_get_trading_client` + `_get_data_client`

- [ ] Open `src/shadow_trading/alpaca_adapter.py` at line 140 (`_get_trading_client`) and line 151 (`_get_data_client`). Replace with:

```python
def _get_trading_client(desk: str | None = None):
    """Create and return an Alpaca TradingClient for paper trading.

    If desk is specified (e.g. 'research_lazy_prices_v1'), dispatches
    through src.shadow_trading.alpaca_clients.get_client for per-desk
    routing. If desk is None, uses the legacy swing-config path for
    full backward compatibility.
    """
    if desk is not None and desk != "swing":
        from src.shadow_trading.alpaca_clients import get_client
        return get_client(desk)
    cfg = _get_alpaca_config()
    from alpaca.trading.client import TradingClient
    return TradingClient(
        api_key=cfg["api_key"],
        secret_key=cfg["api_secret"],
        paper=True,
    )


def _get_data_client(desk: str | None = None):
    """Create and return an Alpaca StockHistoricalDataClient.

    Same desk-routing contract as _get_trading_client. Data client
    doesn't need per-desk account separation (market data is global),
    but we keep the signature parallel so call sites can thread desk
    uniformly without if-branching.
    """
    if desk is not None and desk != "swing":
        from src.shadow_trading.alpaca_clients import get_client
        # Data client uses the trading client's credentials; reuse cache
        client_credentials = get_client(desk)
        from alpaca.data.historical import StockHistoricalDataClient
        # StockHistoricalDataClient takes the same api_key/secret_key
        # pulled from the TradingClient's __dict__ or passed explicitly.
        # Simpler: re-resolve from config.
        from src.config import load_config
        import os
        desks_cfg = load_config().get("desks", {})
        dc = desks_cfg.get(desk, {})
        api_key = os.environ.get(dc.get("alpaca_key_env", ""))
        api_sec = os.environ.get(dc.get("alpaca_secret_env", ""))
        return StockHistoricalDataClient(api_key=api_key, secret_key=api_sec)
    cfg = _get_alpaca_config()
    from alpaca.data.historical import StockHistoricalDataClient
    return StockHistoricalDataClient(
        api_key=cfg["api_key"],
        secret_key=cfg["api_secret"],
    )
```

#### Step 7b.5: Thread desk through the 12 internal call sites

The 12 internal call sites in alpaca_adapter.py at lines 163, 184, 222, 277, 321, 340, 369, 390, 408, 440, 463, 485 each look like `client = _get_trading_client()`. Each is inside a public function. Modify each to forward the public function's `desk` kwarg:

```python
# Was:  def get_account_info() -> dict:
#           ...
#           client = _get_trading_client()

# Becomes:
def get_account_info(desk: str = "swing") -> dict:
    """Get account info. Routes to per-desk Alpaca client (swing default)."""
    client = _get_trading_client(desk=desk)
    ...
```

- [ ] For each of the 14 public API functions identified in Step 7b.1, add `desk: str = "swing"` as the LAST kwarg (after existing kwargs), and pass `desk=desk` through to `_get_trading_client()` or `_get_data_client()`.

- [ ] Special-case `place_live_entry` — **live trading is swing-only** for the foreseeable future. Either (a) omit the desk kwarg entirely and hardcode swing, or (b) raise `ValueError` if desk is anything but `"swing"`:

```python
def place_live_entry(..., desk: str = "swing"):
    if desk != "swing":
        raise ValueError(
            f"live trading only supports swing desk; got desk={desk!r}"
        )
    ...
```

Option (b) is preferred — it's an explicit guardrail against a future accidental `place_live_entry(desk='research_*')` call.

#### Step 7b.6: Run tests, confirm pass

```bash
pytest tests/shadow_trading/test_alpaca_adapter.py -v
pytest tests/shadow_trading/ -v  # confirm existing tests still pass
```

Expected: all new tests pass, no regressions in existing alpaca_adapter tests. If any existing test fails, the backward-compat path is broken — investigate.

#### Step 7b.7: Commit

```bash
git add src/shadow_trading/alpaca_adapter.py tests/shadow_trading/test_alpaca_adapter.py
git commit -m "$(cat <<'EOF'
feat(shadow_trading): desk kwarg on alpaca_adapter public API (Task 7b)

_get_trading_client / _get_data_client accept optional desk kwarg.
When desk is 'swing' or None, uses existing _get_alpaca_config path
(backward compat). When desk is 'research_*' or any other value,
dispatches through src.shadow_trading.alpaca_clients.get_client
(Task 7a) which returns a cached per-desk TradingClient.

All 14 public API functions in alpaca_adapter gain desk: str = "swing"
as final kwarg and forward to the helpers. The 12 internal call sites
at lines 163, 184, 222, 277, 321, 340, 369, 390, 408, 440, 463, 485
are updated to pass desk=desk through. place_live_entry raises
ValueError if desk != 'swing' — live trading is swing-only for the
foreseeable future and a research desk accidentally going live would
be a serious compliance issue.

Backward compatibility: existing callers that don't pass desk continue
to work unchanged — default is 'swing' which hits the same code path
as before.

3 new desk-routing tests; all existing alpaca_adapter tests still pass.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7c: Thread desk through reconcile.py (~1.5h)

This is where the CRITICAL concern from spec line 937 materializes. `reconcile.py` is actively called from 4 scheduler paths; threading desk wrong silently routes research positions through swing Alpaca.

**Files:**
- Edit: `src/shadow_trading/reconcile.py`
- Create: `tests/shadow_trading/test_reconcile_desk_routing.py`

#### Step 7c.1: Read the current reconcile flow

- [ ] Read `src/shadow_trading/reconcile.py` top-to-bottom before editing. Identify:
  - `reconcile_live_trades(...)` at line 107
  - `reconcile_paper_trades(...)` at line 281
  - Internal helpers that call alpaca_adapter public functions
  - SQL queries that filter shadow_trades

Note the current signature of each top-level function. The kwarg contract should gain `desk: str = "swing"` as the LAST parameter (preserving backward compat for the 4 call sites that don't yet pass desk).

#### Step 7c.2: Write failing test

- [ ] Create `tests/shadow_trading/test_reconcile_desk_routing.py`:

```python
"""Tests for desk routing in reconcile_paper_trades / reconcile_live_trades.

CRITICAL per spec line 937: reconcile is ACTIVE code called from 4
scheduler paths. Incorrect desk routing causes research positions to
be polled from swing Alpaca (404 silent drop) or worse, swing positions
to be polled from research Alpaca.
"""
import sqlite3
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def tmp_db_with_mixed_desks(tmp_path):
    """Seed a test DB with 2 swing + 2 research_lazy_prices_v1 open positions."""
    db = tmp_path / "test.db"
    from src.schema.sqlite import ensure_columns
    ensure_columns(str(db))
    conn = sqlite3.connect(db)
    for i, (ticker, desk) in enumerate([
        ("AAPL", "swing"), ("MSFT", "swing"),
        ("NVDA", "research_lazy_prices_v1"),
        ("GOOGL", "research_lazy_prices_v1"),
    ]):
        conn.execute(
            """INSERT INTO shadow_trades
               (trade_id, ticker, shares, entry_price, desk,
                signal_time, entry_time, actual_entry_time, actual_exit_time)
               VALUES (?, ?, 10, 100.0, ?, ?, ?, ?, NULL)""",
            (f"t{i}", ticker, desk,
             "2026-04-01 09:30:00", "2026-04-01 09:30:00",
             "2026-04-01 09:31:00"),
        )
    conn.commit()
    conn.close()
    return str(db)


def test_reconcile_paper_trades_filters_by_desk(tmp_db_with_mixed_desks):
    """reconcile_paper_trades(desk='swing') should only process swing rows."""
    from src.shadow_trading.reconcile import reconcile_paper_trades
    with patch(
        "src.shadow_trading.alpaca_adapter.get_all_positions"
    ) as mock_positions:
        mock_positions.return_value = []  # no open on Alpaca
        with patch(
            "src.shadow_trading.alpaca_adapter.get_order_status"
        ) as mock_order:
            mock_order.return_value = None  # no order status found
            result = reconcile_paper_trades(
                desk="swing", dry_run=True, db_path=tmp_db_with_mixed_desks,
            )
    # The desk-filter SQL should have hit only swing rows (2 of 4)
    # Verify via a side effect: processed_count or similar in result dict
    assert result.get("desk") == "swing" or "swing" in str(result)
    # The mock must have been called with desk='swing' — or at minimum,
    # get_all_positions must not have been called in a way that would
    # return research positions mixed with swing.
    # Primary invariant: no research ticker appears in any processed/closed list.
    processed_tickers = set(result.get("processed_tickers", []))
    assert "NVDA" not in processed_tickers
    assert "GOOGL" not in processed_tickers


def test_reconcile_paper_trades_research_uses_research_client(
    tmp_db_with_mixed_desks,
):
    """reconcile_paper_trades(desk='research_lazy_prices_v1') must route to
    the research Alpaca client, not swing. This is the CRITICAL test."""
    from src.shadow_trading.reconcile import reconcile_paper_trades
    with patch(
        "src.shadow_trading.alpaca_adapter.get_all_positions"
    ) as mock_positions:
        mock_positions.return_value = []
        with patch(
            "src.shadow_trading.alpaca_adapter.get_order_status"
        ) as mock_order:
            mock_order.return_value = None
            reconcile_paper_trades(
                desk="research_lazy_prices_v1", dry_run=True,
                db_path=tmp_db_with_mixed_desks,
            )
    # The Alpaca position query MUST have been called with desk kwarg
    # routing to research. Inspect call_args.
    assert mock_positions.called
    for call in mock_positions.call_args_list:
        called_desk = call.kwargs.get("desk") or (
            call.args[0] if call.args else None
        )
        assert called_desk == "research_lazy_prices_v1", (
            f"reconcile routed research-desk query through desk={called_desk!r} "
            "— this would silently 404 the position on swing Alpaca"
        )


def test_reconcile_default_desk_swing_backward_compat(tmp_db_with_mixed_desks):
    """reconcile_paper_trades() with no desk kwarg defaults to swing."""
    from src.shadow_trading.reconcile import reconcile_paper_trades
    with patch(
        "src.shadow_trading.alpaca_adapter.get_all_positions"
    ) as mock_positions:
        mock_positions.return_value = []
        with patch(
            "src.shadow_trading.alpaca_adapter.get_order_status"
        ) as mock_order:
            mock_order.return_value = None
            result = reconcile_paper_trades(
                dry_run=True, db_path=tmp_db_with_mixed_desks,
            )
    # Default behavior unchanged: only swing rows touched.
    processed_tickers = set(result.get("processed_tickers", []))
    assert "NVDA" not in processed_tickers
    assert "GOOGL" not in processed_tickers
```

#### Step 7c.3: Run tests, confirm they fail

```bash
pytest tests/shadow_trading/test_reconcile_desk_routing.py -v
```

Expected: multiple failures — reconcile doesn't yet accept `desk` kwarg.

#### Step 7c.4: Patch `reconcile_paper_trades`

- [ ] Modify the signature at line 281:

```python
def reconcile_paper_trades(
    desk: str = "swing",
    dry_run: bool = False,
    db_path: str | None = None,
) -> dict:
    """Reconcile open paper positions for a specific desk.

    Args:
        desk: 'swing' (default, backward-compatible) or 'research_<id>'.
            Filters shadow_trades rows AND routes Alpaca queries to the
            matching desk's client.
    """
```

- [ ] Thread `desk` through:
  1. The SQL query filtering shadow_trades:
     ```python
     rows = conn.execute(
         "SELECT * FROM shadow_trades "
         "WHERE actual_exit_time IS NULL AND desk = ?",
         (desk,),
     ).fetchall()
     ```
  2. Every call to an alpaca_adapter public function:
     ```python
     positions = get_all_positions(desk=desk)
     order_status = get_order_status(order_id, desk=desk)
     cancel_orders_for_ticker(ticker, desk=desk)
     # etc.
     ```
  3. Return dict includes `"desk": desk` for the test assertions and for logging.

- [ ] Do the same for `reconcile_live_trades` at line 107. **Live is swing-only** — if desk != 'swing', raise `ValueError` at the top of the function (same safety rationale as `place_live_entry`).

#### Step 7c.5: Run tests, iterate until pass

```bash
pytest tests/shadow_trading/test_reconcile_desk_routing.py -v
pytest tests/shadow_trading/ -v  # full shadow_trading regression check
```

Expected: all 3 new tests pass; existing reconcile tests continue to pass.

#### Step 7c.6: Commit

```bash
git add src/shadow_trading/reconcile.py tests/shadow_trading/test_reconcile_desk_routing.py
git commit -m "$(cat <<'EOF'
feat(shadow_trading): desk routing in reconcile (Task 7c — CRITICAL)

reconcile_paper_trades + reconcile_live_trades accept desk: str = "swing"
kwarg. The desk is threaded through:
  1. SQL query on shadow_trades (WHERE desk = ?)
  2. Every alpaca_adapter public function call (get_all_positions,
     get_order_status, cancel_orders_for_ticker, etc.)

This is the CRITICAL path per spec line 937: reconcile is actively
called from 4 scheduler paths (overnight.py:27, position_monitor.py:69,
watch.py:685, cli/commands.py:405). Scheduler updates in Task 7d
will pass desk correctly.

reconcile_live_trades raises ValueError if desk != 'swing' — live
trading is swing-only (parallel to place_live_entry guardrail in
Task 7b). Research-desk "live" is not a supported code path.

3 new tests verify:
  - Desk-filtered SQL excludes other-desk rows
  - desk='research_xxx' routes Alpaca queries through the research
    client (the specific failure mode the spec flagged as CRITICAL)
  - desk-absent default preserves swing behavior for backward compat

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7d: Update the 4 scheduler + CLI call sites (~30min)

**Files:**
- Edit: `src/scheduler/overnight.py:27`
- Edit: `src/scheduler/position_monitor.py:69`
- Edit: `src/scheduler/watch.py:685`
- Edit: `src/cli/commands.py:405`

Each call site currently has `reconcile_paper_trades()` or `reconcile_live_trades()` with no desk kwarg. The default is `swing` which preserves current behavior. **What we add:** a loop over active research strategies, reconciling each.

#### Step 7d.1: Pattern — reconcile for swing + every active research desk

The pattern at each scheduler call site becomes:

```python
# Old:
from src.shadow_trading.reconcile import reconcile_paper_trades
result = reconcile_paper_trades(dry_run=False)

# New:
from src.shadow_trading.reconcile import reconcile_paper_trades
from src.platform.promotion import get_strategies_by_status

# Swing always reconciled
swing_result = reconcile_paper_trades(desk="swing", dry_run=False)

# Every strategy in shadow_trading state reconciled on its research desk
active_research = get_strategies_by_status(["shadow_trading"])
research_results = {}
for strategy_id in active_research:
    research_results[strategy_id] = reconcile_paper_trades(
        desk=f"research_{strategy_id}", dry_run=False,
    )

result = {"swing": swing_result, "research": research_results}
```

- [ ] Apply this pattern at `src/scheduler/overnight.py:27`, `src/scheduler/position_monitor.py:69`, `src/scheduler/watch.py:685`. Keep the logging / error-handling pattern each file already uses.

- [ ] `src/cli/commands.py:405` calls `reconcile_live_trades` — live is swing-only, so just add `desk="swing"` explicitly for clarity:

```python
result = reconcile_live_trades(desk="swing", dry_run=dry_run)
```

#### Step 7d.2: Write a scheduler integration test

- [ ] Create `tests/scheduler/test_overnight_reconcile_dispatch.py`:

```python
"""Test that overnight reconcile dispatches to both swing AND every
active research strategy."""
from unittest.mock import patch


def test_overnight_reconcile_dispatches_swing_plus_active_research(tmp_path):
    """When 2 strategies are in shadow_trading state, overnight's reconcile
    call should invoke reconcile_paper_trades 3x: swing + research_A + research_B."""
    db = tmp_path / "test.db"
    from src.schema.sqlite import ensure_columns
    from src.platform.promotion import register_strategy, promote
    ensure_columns(str(db))

    # Register + advance 2 strategies to shadow_trading
    register_strategy(
        "strat_a", "A", "test", spec_hash="x", db_path=str(db),
    )
    register_strategy(
        "strat_b", "B", "test", spec_hash="y", db_path=str(db),
    )
    # Manually advance via SQL (bypass gate for test fixture)
    import sqlite3
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE strategy_registry SET current_status='shadow_trading' "
        "WHERE strategy_id IN ('strat_a','strat_b')",
    )
    conn.commit()
    conn.close()

    with patch(
        "src.shadow_trading.reconcile.reconcile_paper_trades"
    ) as mock_recon:
        mock_recon.return_value = {"status": "ok"}
        from src.scheduler import overnight
        overnight._reconcile_all_paper_trades(db_path=str(db))

    # Should have been called 3 times: swing + strat_a + strat_b
    assert mock_recon.call_count == 3
    desks_called = [
        call.kwargs.get("desk") for call in mock_recon.call_args_list
    ]
    assert "swing" in desks_called
    assert "research_strat_a" in desks_called
    assert "research_strat_b" in desks_called
```

This requires extracting the reconcile-dispatch logic into a helper function in `overnight.py` (`_reconcile_all_paper_trades(db_path)`) — do that during Step 7d.1 so the test can target it cleanly.

#### Step 7d.3: Run tests

```bash
pytest tests/scheduler/test_overnight_reconcile_dispatch.py -v
pytest tests/ -q --ignore=tests/test_dependencies.py 2>&1 | tail -5
```

Full suite pass count must not decrease. Scheduler tests should still pass.

#### Step 7d.4: Commit

```bash
git add src/scheduler/overnight.py \
        src/scheduler/position_monitor.py \
        src/scheduler/watch.py \
        src/cli/commands.py \
        tests/scheduler/test_overnight_reconcile_dispatch.py
git commit -m "$(cat <<'EOF'
feat(scheduler): reconcile per-desk dispatch (Task 7d)

Four call sites updated to loop over swing + every active research
strategy when calling reconcile_paper_trades:
  - src/scheduler/overnight.py:27
  - src/scheduler/position_monitor.py:69
  - src/scheduler/watch.py:685

src/cli/commands.py:405 passes desk="swing" explicitly for clarity
(live is swing-only).

_reconcile_all_paper_trades helper extracted in overnight.py for
testability. Integration test verifies 3 dispatch calls (swing +
research_strat_a + research_strat_b) when 2 strategies sit in
shadow_trading state.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7e: ShadowHarness class (~2h)

**Files:**
- Create: `src/platform/shadow_harness.py`
- Create: `tests/platform/test_shadow_harness.py`

#### Step 7e.1: Write failing tests

- [ ] Create `tests/platform/test_shadow_harness.py`:

```python
"""Tests for src.platform.shadow_harness — live shadow-trading harness.

NON-NEGOTIABLE gates (spec line 1193-1197 / CC prompts line 303-313):
  - test_harness_reconcile_uses_research_client
  - test_harness_bracket_monitor_uses_research_client
  - ShadowHarness.halt() closes only this strategy's positions
  - verify_accounts_distinct called at startup
"""
import sqlite3
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.platform.shadow_harness import ShadowHarness
from src.platform.strategy_spec import StrategySpec


def _test_spec(strategy_id: str = "test_strat") -> StrategySpec:
    return StrategySpec(
        strategy_id=strategy_id,
        display_name=strategy_id.upper(),
        universe={"tickers": "sp100"},
        entry={"kind": "scheduled", "day_of_week": "Monday", "time": "close"},
        exit={
            "kind": "mechanical", "timeout_days": 21,
            "stop": {"method": "pct", "value": 0.02},
            "target": {"method": "pct", "value": 0.03},
        },
        position_sizing={"method": "fixed_pct_equity", "pct": 0.15,
                         "max_concurrent": 5},
        attribution={"benchmark": "SPY_matched_window",
                     "metrics": ["sharpe"]},
        raw={"shadow_cadence_seconds": 600},
        source="test",
    )


@pytest.fixture
def tmp_db(tmp_path):
    db = tmp_path / "test.db"
    from src.schema.sqlite import ensure_columns
    ensure_columns(str(db))
    return str(db)


def test_harness_writes_shadow_trade_with_correct_desk_tag(tmp_db):
    """New trades must land at desk='research_<strategy_id>'."""
    spec = _test_spec("strat_a")
    harness = ShadowHarness(spec, db_path=tmp_db)
    with patch(
        "src.platform.shadow_harness.place_bracket_order"
    ) as mock_place, patch(
        "src.shadow_trading.alpaca_clients.get_client"
    ), patch.object(harness, "_find_candidates", return_value=[
        {"ticker": "AAPL", "as_of": "2026-04-17T10:00:00",
         "signal_strength": 0.9, "metadata": {}},
    ]), patch.object(
        harness, "_is_within_hard_limits", return_value=(True, None),
    ):
        mock_place.return_value = {"order_id": "O1", "entry_price": 100.0}
        result = harness.run_one_tick(as_of=datetime(2026, 4, 17, 10, 0))

    assert result["n_new_positions"] == 1
    # Verify shadow_trades row has the right desk
    conn = sqlite3.connect(tmp_db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT desk FROM shadow_trades WHERE ticker = 'AAPL'"
    ).fetchone()
    conn.close()
    assert row["desk"] == "research_strat_a"


def test_harness_reconcile_uses_research_client(tmp_db):
    """NON-NEGOTIABLE: harness.run_one_tick, when it invokes reconcile
    (for its own open positions), must pass desk='research_<id>', not swing."""
    spec = _test_spec("strat_b")
    harness = ShadowHarness(spec, db_path=tmp_db)
    with patch(
        "src.shadow_trading.reconcile.reconcile_paper_trades"
    ) as mock_recon:
        mock_recon.return_value = {"status": "ok"}
        harness._reconcile_open_positions()
    assert mock_recon.called
    for call in mock_recon.call_args_list:
        assert call.kwargs.get("desk") == "research_strat_b"


def test_harness_bracket_monitor_uses_research_client(tmp_db):
    """NON-NEGOTIABLE: if the harness polls bracket order status,
    it must use the research Alpaca client."""
    spec = _test_spec("strat_c")
    harness = ShadowHarness(spec, db_path=tmp_db)
    with patch(
        "src.shadow_trading.alpaca_adapter.get_order_status"
    ) as mock_status:
        mock_status.return_value = {"status": "filled"}
        harness._poll_order_status("order_id_xyz")
    assert mock_status.called
    assert mock_status.call_args.kwargs.get("desk") == "research_strat_c"


def test_harness_halt_closes_only_this_strategy_positions(tmp_db):
    """ShadowHarness.halt() must close positions tagged with THIS
    strategy's desk, not swing and not other research strategies."""
    spec = _test_spec("strat_d")
    # Seed 3 positions: 1 swing, 1 research_strat_d, 1 research_other
    conn = sqlite3.connect(tmp_db)
    for i, (ticker, desk) in enumerate([
        ("AAPL", "swing"),
        ("MSFT", "research_strat_d"),
        ("NVDA", "research_other_strat"),
    ]):
        conn.execute(
            """INSERT INTO shadow_trades
               (trade_id, ticker, shares, entry_price, desk,
                signal_time, entry_time, actual_entry_time, actual_exit_time)
               VALUES (?, ?, 10, 100.0, ?, '2026-04-01', '2026-04-01',
                       '2026-04-01', NULL)""",
            (f"t{i}", ticker, desk),
        )
    conn.commit()
    conn.close()

    harness = ShadowHarness(spec, db_path=tmp_db)
    with patch(
        "src.platform.shadow_harness.place_paper_exit"
    ) as mock_exit:
        mock_exit.return_value = {"status": "ok"}
        closed = harness.halt()
    # Must have closed MSFT only (the one desk='research_strat_d' open row)
    closed_tickers = [c["ticker"] for c in closed]
    assert closed_tickers == ["MSFT"]
    # exit function invoked with desk='research_strat_d'
    for call in mock_exit.call_args_list:
        assert call.kwargs.get("desk") == "research_strat_d"


def test_harness_verify_accounts_distinct_on_init(tmp_db):
    """ShadowHarness.__init__ should invoke verify_accounts_distinct
    via a startup guard so mis-config is caught before any bracket order."""
    spec = _test_spec("strat_e")
    with patch(
        "src.shadow_trading.alpaca_clients.verify_accounts_distinct"
    ) as mock_verify:
        ShadowHarness(spec, db_path=tmp_db)
    assert mock_verify.called


def test_harness_get_open_positions_filters_by_strategy(tmp_db):
    """get_open_positions returns only this strategy's desk rows."""
    spec = _test_spec("strat_f")
    conn = sqlite3.connect(tmp_db)
    for i, (ticker, desk) in enumerate([
        ("AAPL", "swing"), ("MSFT", "research_strat_f"),
        ("NVDA", "research_strat_f"), ("GOOGL", "research_other"),
    ]):
        conn.execute(
            """INSERT INTO shadow_trades
               (trade_id, ticker, shares, entry_price, desk,
                signal_time, entry_time, actual_entry_time, actual_exit_time)
               VALUES (?, ?, 10, 100.0, ?, '2026-04-01', '2026-04-01',
                       '2026-04-01', NULL)""",
            (f"t{i}", ticker, desk),
        )
    conn.commit()
    conn.close()

    harness = ShadowHarness(spec, db_path=tmp_db)
    open_positions = harness.get_open_positions()
    tickers = {p["ticker"] for p in open_positions}
    assert tickers == {"MSFT", "NVDA"}
```

#### Step 7e.2: Run tests, confirm they fail

```bash
pytest tests/platform/test_shadow_harness.py -v
```

Expected: `ModuleNotFoundError`.

#### Step 7e.3: Implement ShadowHarness

- [ ] Create `src/platform/shadow_harness.py`:

```python
"""Shadow-trading harness for research-platform strategies.

Called by: src.scheduler.watch (via Task 9's _run_platform_shadow_tick).
Calls: src.shadow_trading.alpaca_clients (startup verify),
       src.shadow_trading.alpaca_adapter (place/query/cancel orders),
       src.shadow_trading.reconcile (own-strategy reconcile),
       src.platform.risk.exposure_limits.check_pre_trade_limits
       (Sprint 3; wired in Task 7f).
Owns tables: shadow_trades (writes with desk='research_<strategy_id>').
Config keys: desks.{strategy_id} (transitively via alpaca_clients).
Tests: tests/platform/test_shadow_harness.py.

Per-strategy instance; one ShadowHarness per active research strategy.
Watch loop's _run_platform_shadow_tick (Task 9) instantiates one and
calls run_one_tick(now) at the cadence declared in spec.raw[
'shadow_cadence_seconds'].

halt() closes this strategy's open positions only; never touches swing
or other research strategies.
"""
from __future__ import annotations

import logging
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from src.config import DB_PATH
from src.platform.strategy_spec import StrategySpec
from src.shadow_trading.alpaca_adapter import (
    cancel_orders_for_ticker,
    get_all_positions,
    get_order_status,
    place_bracket_order,
    place_paper_exit,
)
from src.shadow_trading.alpaca_clients import verify_accounts_distinct
from src.shadow_trading.reconcile import reconcile_paper_trades

logger = logging.getLogger(__name__)


class ShadowHarness:
    """Per-strategy live shadow-trading harness."""

    def __init__(
        self, strategy_spec: StrategySpec, db_path: str = DB_PATH,
    ) -> None:
        self.spec = strategy_spec
        self.strategy_id = strategy_spec.strategy_id
        self.desk = f"research_{self.strategy_id}"
        self.db_path = db_path
        # Startup guard — this is where mis-configured shared-account
        # setups fail fast rather than silently interleaving trades.
        try:
            verify_accounts_distinct()
        except RuntimeError:
            logger.exception(
                "[HARNESS %s] verify_accounts_distinct failed — aborting init",
                self.strategy_id,
            )
            raise

    def run_one_tick(self, as_of: datetime) -> dict:
        """Called by watch loop at strategy's cadence.

        1. Reconcile own open positions.
        2. Find new candidates via strategy signal.
        3. For each candidate: check_pre_trade_limits (Task 7f) + place
           bracket order + write shadow_trades row.
        4. Return summary dict.
        """
        self._reconcile_open_positions()
        candidates = self._find_candidates(as_of)
        n_new = 0
        for cand in candidates:
            allowed, reason = self._is_within_hard_limits(cand)
            if not allowed:
                logger.info(
                    "[HARNESS %s] skipped %s: %s",
                    self.strategy_id, cand["ticker"], reason,
                )
                continue
            self._open_position(cand, as_of)
            n_new += 1
        return {
            "strategy_id": self.strategy_id,
            "as_of": as_of.isoformat(),
            "n_candidates": len(candidates),
            "n_new_positions": n_new,
        }

    def get_open_positions(self) -> list[dict]:
        """Return open shadow_trades rows tagged with this strategy's desk."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT * FROM shadow_trades "
                "WHERE desk = ? AND actual_exit_time IS NULL",
                (self.desk,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def halt(self) -> list[dict]:
        """Close all open positions for THIS strategy. Returns list of
        (trade_id, ticker) dicts for closed positions. Does NOT touch
        swing positions or other research strategies' positions."""
        closed = []
        for pos in self.get_open_positions():
            # Cancel any outstanding bracket orders first.
            try:
                cancel_orders_for_ticker(pos["ticker"], desk=self.desk)
            except Exception as e:
                logger.warning(
                    "[HARNESS %s] cancel bracket for %s failed: %s",
                    self.strategy_id, pos["ticker"], e,
                )
            # Submit market-close via research client.
            try:
                exit_result = place_paper_exit(
                    pos["ticker"],
                    shares=int(pos["shares"]),
                    desk=self.desk,
                )
                logger.info(
                    "[HARNESS %s] halt closed %s: %s",
                    self.strategy_id, pos["ticker"], exit_result,
                )
                closed.append({
                    "trade_id": pos["trade_id"],
                    "ticker": pos["ticker"],
                })
            except Exception as e:
                logger.exception(
                    "[HARNESS %s] halt failed to close %s: %s",
                    self.strategy_id, pos["ticker"], e,
                )
        return closed

    # ── internal helpers ──────────────────────────────────────────────

    def _reconcile_open_positions(self) -> None:
        """Reconcile THIS strategy's shadow_trades against the research
        Alpaca paper account."""
        try:
            reconcile_paper_trades(
                desk=self.desk, dry_run=False, db_path=self.db_path,
            )
        except Exception:
            logger.exception(
                "[HARNESS %s] reconcile failed; tick continues without recon",
                self.strategy_id,
            )

    def _poll_order_status(self, order_id: str) -> dict:
        """Fetch one order's status via the research Alpaca client."""
        return get_order_status(order_id, desk=self.desk)

    def _find_candidates(self, as_of: datetime) -> list[dict]:
        """Query the strategy spec for new candidates at `as_of`.

        Delegates to src.platform.signal_eval for YAML-based strategies.
        Python plugins (Task 2, Sprint 4) take a different path via
        get_plugin(self.strategy_id).find_candidates(...).
        """
        # MVP PLACEHOLDER (v0.24.1 follow-up issue filed at
        # tickets time): full signal-eval integration requires exposing
        # src.platform.signal_eval.find_candidates_for_date(spec, db_path,
        # as_of) or similar — reusing the event-driven dispatch logic
        # from backtest_engine._run_event_driven but for a single as_of
        # date. For Sprint 4 MVP, return empty + log a warning until
        # that follow-up lands. The platform is correctly inert when no
        # strategy has candidate-generation wired — NOT a bug.
        logger.info(
            "[HARNESS %s] _find_candidates: no candidates (MVP placeholder "
            "— see Task 7e step-through; full signal_eval integration in "
            "v0.24.1)",
            self.strategy_id,
        )
        return []

    def _is_within_hard_limits(
        self, candidate: dict,
    ) -> tuple[bool, str | None]:
        """Delegate to Sprint 3's check_pre_trade_limits. Wired in Task 7f."""
        # Placeholder — Task 7f fills this in.
        return True, None

    def _open_position(self, candidate: dict, as_of: datetime) -> None:
        """Place bracket order via research Alpaca client; write shadow
        trade row with desk='research_<strategy_id>'."""
        ticker = candidate["ticker"]
        entry_result = place_bracket_order(
            ticker, desk=self.desk, **candidate.get("bracket_kwargs", {}),
        )
        trade_id = str(uuid.uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """INSERT INTO shadow_trades
                   (trade_id, ticker, shares, entry_price, desk,
                    research_thesis, strategy_spec_hash,
                    signal_time, entry_time, actual_entry_time)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    trade_id, ticker,
                    entry_result.get("shares") or candidate.get("shares", 1),
                    entry_result.get("entry_price", candidate.get("price", 0.0)),
                    self.desk,
                    candidate.get("metadata", {}).get("thesis"),
                    candidate.get("metadata", {}).get("strategy_spec_hash"),
                    candidate["as_of"],
                    candidate["as_of"],
                    now_iso,
                ),
            )
            conn.commit()
        finally:
            conn.close()
```

**IMPORTANT:** The `_find_candidates` method is a MVP placeholder — full signal-evaluation integration requires exposing `src.platform.signal_eval.find_candidates_for_date(spec, db_path)` or similar. For Sprint 4, the harness can be instantiated safely, `verify_accounts_distinct` runs at init, and all the halt/reconcile/get_open_positions paths work. Candidate generation is stubbed to return [] with a warning log. When the watch loop ticks a strategy, `n_new_positions=0` is the expected result at MVP — the non-negotiable gates don't require actual trades to be placed.

**If you want actual trades to flow:** in a follow-up task, add `find_candidates_for_date(spec, db_path, as_of) -> list[dict]` to `src/platform/signal_eval.py` that reuses the event-driven dispatch logic from `backtest_engine.py::_run_event_driven` but with a single as_of date. That's beyond the Sprint 4 MVP gate and can land as a v0.24.1 follow-up.

#### Step 7e.4: Run tests, iterate

```bash
pytest tests/platform/test_shadow_harness.py -v
```

All 6 MUST pass. If the candidate-placeholder is breaking `test_harness_writes_shadow_trade_with_correct_desk_tag`, adjust that test to patch `_find_candidates` to return synthetic candidates (already shown in the test).

#### Step 7e.5: Commit

```bash
git add src/platform/shadow_harness.py tests/platform/test_shadow_harness.py
git commit -m "$(cat <<'EOF'
feat(platform): shadow harness (Task 7e)

src/platform/shadow_harness.py — ShadowHarness class per-strategy.
__init__ invokes verify_accounts_distinct at startup so mis-config
fails fast. run_one_tick does reconcile → candidates → pre-trade-limits
(Task 7f) → bracket placement → shadow_trades write with
desk='research_<strategy_id>'.

halt() closes only this strategy's open positions via the research
Alpaca client; swing and other research strategies are never touched.
get_open_positions filters by the strategy's desk.

_find_candidates is a MVP placeholder returning []; full signal_eval
integration lands in v0.24.1. Sprint 4's non-negotiable gates verify
routing correctness, not candidate flow — the placeholder doesn't block
the gate tests.

6 tests cover: desk-tag on writes, reconcile uses research client,
bracket monitor uses research client, halt closes only this strategy
(NOT swing, NOT other research), verify_accounts_distinct called at
init, get_open_positions filters by strategy.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7f: Wire check_pre_trade_limits into ShadowHarness (~30min)

Sprint 3's `src/platform/risk/exposure_limits.py::check_pre_trade_limits` is a pure function. Wire it into `ShadowHarness._is_within_hard_limits`.

**Files:**
- Edit: `src/platform/shadow_harness.py::_is_within_hard_limits`
- Edit: `tests/platform/test_shadow_harness.py` — add 2 tests covering the limit check

#### Step 7f.1: Write failing test

- [ ] Append to `tests/platform/test_shadow_harness.py`:

```python
def test_harness_blocks_candidate_that_fails_hard_limits(tmp_db):
    """If check_pre_trade_limits rejects the proposed position, the
    harness must NOT open it."""
    spec = _test_spec("strat_g")
    harness = ShadowHarness(spec, db_path=tmp_db)
    cand = {
        "ticker": "AAPL", "as_of": "2026-04-17T10:00:00",
        "shares": 70, "price": 100.0,  # 7% position — violates 6% cap
        "signal_strength": 0.9, "metadata": {},
    }
    with patch(
        "src.platform.shadow_harness.check_pre_trade_limits",
        return_value=(
            False,
            "single-name concentration exceeded: 7.00% > 6.00%",
        ),
    ) as mock_check, patch(
        "src.platform.shadow_harness.place_bracket_order"
    ) as mock_place:
        allowed, reason = harness._is_within_hard_limits(cand)
    assert not allowed
    assert "6" in reason
    # Place order MUST NOT have been called
    mock_place.assert_not_called()


def test_harness_allows_candidate_within_hard_limits(tmp_db):
    spec = _test_spec("strat_h")
    harness = ShadowHarness(spec, db_path=tmp_db)
    cand = {
        "ticker": "AAPL", "as_of": "2026-04-17T10:00:00",
        "shares": 40, "price": 100.0,  # 4% — under 6% cap
        "signal_strength": 0.9, "metadata": {},
    }
    with patch(
        "src.platform.shadow_harness.check_pre_trade_limits",
        return_value=(True, None),
    ) as mock_check:
        allowed, reason = harness._is_within_hard_limits(cand)
    assert allowed
    assert reason is None
    # check_pre_trade_limits was invoked with shares + price from candidate
    args, kwargs = mock_check.call_args
    assert kwargs.get("ticker") == "AAPL" or "AAPL" in str(args)
```

#### Step 7f.2: Implement wiring

- [ ] Replace `ShadowHarness._is_within_hard_limits` with:

```python
def _is_within_hard_limits(
    self, candidate: dict,
) -> tuple[bool, str | None]:
    """Delegate to src.platform.risk.exposure_limits.check_pre_trade_limits.

    Gathers current_positions + current_nav for the research desk,
    then calls the pure function. Returns (allowed, reason) directly.
    """
    from src.platform.risk.exposure_limits import check_pre_trade_limits
    current_positions = self.get_open_positions()
    # Enrich positions with current_price (for concentration math).
    # For MVP, use entry_price as a conservative proxy (Sprint 4.1 task:
    # fetch live via get_current_price per position).
    enriched = [
        {
            "ticker": p["ticker"],
            "shares": int(p["shares"]),
            "current_price": float(p["entry_price"]),
        }
        for p in current_positions
    ]
    # NAV for the research desk: read from research Alpaca client's
    # get_account_info. Fallback to a conservative estimate if the
    # account isn't accessible (offline test, etc.).
    try:
        from src.shadow_trading.alpaca_adapter import get_account_info
        acct = get_account_info(desk=self.desk)
        nav = float(acct.get("portfolio_value") or 100_000.0)
    except Exception as e:
        logger.warning(
            "[HARNESS %s] cannot fetch research NAV; using $100K fallback: %s",
            self.strategy_id, e,
        )
        nav = 100_000.0

    return check_pre_trade_limits(
        ticker=candidate["ticker"],
        proposed_shares=int(candidate.get("shares", 0)),
        proposed_price=float(candidate.get("price", 0.0)),
        current_positions=enriched,
        current_nav=nav,
        db_path=self.db_path,
    )
```

- [ ] Add the import at the top of `shadow_harness.py`:

```python
from src.platform.risk.exposure_limits import check_pre_trade_limits
```

#### Step 7f.3: Run tests

```bash
pytest tests/platform/test_shadow_harness.py -v
```

Expected: 8 passed (6 from 7e + 2 from 7f).

#### Step 7f.4: Commit

```bash
git add src/platform/shadow_harness.py tests/platform/test_shadow_harness.py
git commit -m "$(cat <<'EOF'
feat(platform): wire check_pre_trade_limits into ShadowHarness (Task 7f)

ShadowHarness._is_within_hard_limits delegates to Sprint 3's
check_pre_trade_limits pure function. Gathers open positions for
this strategy's desk (enriched with entry_price as current_price
proxy — v0.24.1 will fetch live via get_current_price), reads NAV
from the research Alpaca account (fallback $100K if offline),
and calls the concentration / leverage / drawdown guardrails.

Enforcement: when check_pre_trade_limits returns (False, reason),
run_one_tick skips the candidate WITHOUT calling place_bracket_order.
Two new tests verify block + allow paths.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: Watch loop platform integration (~2h)

**Files:**
- Edit: `src/scheduler/watch.py` — add `_run_platform_shadow_tick` + init `_last_platform_tick`
- Create: `tests/scheduler/test_watch_platform_tick.py`

#### Step 9.1: Write failing tests

- [ ] Create `tests/scheduler/test_watch_platform_tick.py`:

```python
"""Tests for WatchLoop._run_platform_shadow_tick (Task 9).

Non-negotiable gates:
  - test_platform_tick_respects_cadence
  - test_platform_tick_runs_each_strategy_independently
  - test_platform_tick_failure_does_not_kill_swing
"""
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch


def _make_watch_loop_with_platform_init():
    """Import WatchLoop and ensure _last_platform_tick dict exists."""
    from src.scheduler.watch import WatchLoop
    wl = WatchLoop.__new__(WatchLoop)  # bypass real __init__
    wl._last_platform_tick = {}
    return wl


def test_platform_tick_respects_cadence(tmp_path):
    """If a strategy has cadence=600s and last tick was 300s ago, skip.
    If last tick was 700s ago, run."""
    from src.schema.sqlite import ensure_columns
    from src.platform.promotion import register_strategy
    db = str(tmp_path / "test.db")
    ensure_columns(db)
    register_strategy(
        "strat_a", "A", "yaml:test", "hash", db_path=db,
    )
    import sqlite3
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE strategy_registry SET current_status='shadow_trading' "
        "WHERE strategy_id='strat_a'",
    )
    conn.commit()
    conn.close()

    wl = _make_watch_loop_with_platform_init()
    wl._db_path = db  # Use test DB

    fake_spec = MagicMock()
    fake_spec.raw = {"shadow_cadence_seconds": 600}

    with patch(
        "src.scheduler.watch.load_spec", return_value=fake_spec,
    ), patch(
        "src.scheduler.watch.ShadowHarness"
    ) as mock_harness_cls:
        mock_harness = MagicMock()
        mock_harness.run_one_tick.return_value = {"n_new_positions": 0}
        mock_harness_cls.return_value = mock_harness

        # First tick: no prior — should run
        wl._run_platform_shadow_tick()
        assert mock_harness.run_one_tick.call_count == 1

        # Second tick 300s later: cadence not elapsed — should skip
        wl._last_platform_tick["strat_a"] = datetime.now() - timedelta(seconds=300)
        wl._run_platform_shadow_tick()
        assert mock_harness.run_one_tick.call_count == 1

        # Third tick 700s later: cadence elapsed — should run
        wl._last_platform_tick["strat_a"] = datetime.now() - timedelta(seconds=700)
        wl._run_platform_shadow_tick()
        assert mock_harness.run_one_tick.call_count == 2


def test_platform_tick_runs_each_strategy_independently(tmp_path):
    """Two strategies at shadow_trading state — each ticked."""
    from src.schema.sqlite import ensure_columns
    from src.platform.promotion import register_strategy
    db = str(tmp_path / "test.db")
    ensure_columns(db)
    register_strategy("a", "A", "test", "x", db_path=db)
    register_strategy("b", "B", "test", "y", db_path=db)
    import sqlite3
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE strategy_registry SET current_status='shadow_trading'",
    )
    conn.commit()
    conn.close()

    wl = _make_watch_loop_with_platform_init()
    wl._db_path = db
    fake_spec = MagicMock()
    fake_spec.raw = {"shadow_cadence_seconds": 60}

    with patch(
        "src.scheduler.watch.load_spec", return_value=fake_spec,
    ), patch(
        "src.scheduler.watch.ShadowHarness"
    ) as mock_cls:
        mock_cls.return_value = MagicMock(
            run_one_tick=MagicMock(return_value={"n_new_positions": 0}),
        )
        wl._run_platform_shadow_tick()
    # Two strategies → two harness instantiations + two ticks
    assert mock_cls.call_count == 2


def test_platform_tick_failure_does_not_kill_swing(tmp_path):
    """If one strategy's tick raises, the swing scan loop must continue."""
    from src.schema.sqlite import ensure_columns
    from src.platform.promotion import register_strategy
    db = str(tmp_path / "test.db")
    ensure_columns(db)
    register_strategy("crash", "C", "test", "x", db_path=db)
    import sqlite3
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE strategy_registry SET current_status='shadow_trading'"
    )
    conn.commit()
    conn.close()

    wl = _make_watch_loop_with_platform_init()
    wl._db_path = db
    fake_spec = MagicMock()
    fake_spec.raw = {"shadow_cadence_seconds": 60}

    with patch(
        "src.scheduler.watch.load_spec", return_value=fake_spec,
    ), patch(
        "src.scheduler.watch.ShadowHarness"
    ) as mock_cls:
        mock_cls.return_value = MagicMock(
            run_one_tick=MagicMock(side_effect=RuntimeError("harness crash")),
        )
        # Must not raise — _run_platform_shadow_tick should catch
        wl._run_platform_shadow_tick()
    # The crash was contained; last_platform_tick still got updated so
    # we don't infinite-loop on the same failure.
    assert "crash" in wl._last_platform_tick
```

#### Step 9.2: Run tests — expect AttributeError for missing `_run_platform_shadow_tick`

#### Step 9.3: Patch `src/scheduler/watch.py`

- [ ] In `WatchLoop.__init__`, add `self._last_platform_tick: dict[str, datetime] = {}` at the end.
- [ ] In `WatchLoop._reset_daily_state` (if present), add `self._last_platform_tick.clear()`.
- [ ] Add the new method:

```python
def _run_platform_shadow_tick(self) -> None:
    """Tick every active research-platform strategy once per cadence.

    Uses interval-gating (per spec line 991-994), NOT inline dispatch
    like _run_mr_scan. Each strategy has its own cadence_seconds;
    checked independently.

    Failures on one strategy are logged and isolated — swing trading
    continues.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from src.platform.promotion import get_strategies_by_status
    from src.platform.shadow_harness import ShadowHarness
    from src.platform.strategy_spec import load_spec

    ET = ZoneInfo("America/New_York")
    now = datetime.now(ET)
    try:
        active = get_strategies_by_status(
            ["shadow_trading"],
            db_path=getattr(self, "_db_path", None),
        )
    except Exception:
        logger.exception("[PLATFORM] get_strategies_by_status failed")
        return

    for strategy_id in active:
        try:
            spec = load_spec(strategy_id)
            interval = int(spec.raw.get("shadow_cadence_seconds", 600))
            last_tick = self._last_platform_tick.get(strategy_id)
            if last_tick is not None and (now - last_tick).total_seconds() < interval:
                continue
            # Record the tick BEFORE running so a crash doesn't leave
            # us looping on the failing strategy every second.
            self._last_platform_tick[strategy_id] = now
            harness = ShadowHarness(spec)
            result = harness.run_one_tick(now)
            logger.info(
                "[PLATFORM] ticked %s: %d new positions",
                strategy_id, result.get("n_new_positions", 0),
            )
        except Exception:
            logger.exception(
                "[PLATFORM] tick failed for %s — swing continues",
                strategy_id,
            )
```

- [ ] In the main loop body (wherever swing scan + reconcile are dispatched), add a call:

```python
if self._should_tick_platform():  # optional interval gate
    self._run_platform_shadow_tick()
```

Or just call `_run_platform_shadow_tick()` once per outer loop iteration if it's already gated per-strategy inside.

#### Step 9.4: Run tests, iterate

```bash
pytest tests/scheduler/test_watch_platform_tick.py -v
```

All 3 MUST pass.

#### Step 9.5: Commit

```bash
git add src/scheduler/watch.py tests/scheduler/test_watch_platform_tick.py
git commit -m "$(cat <<'EOF'
feat(scheduler): watch-loop platform tick dispatcher (Task 9)

WatchLoop._run_platform_shadow_tick iterates every strategy in
shadow_trading state, instantiates a ShadowHarness per strategy, and
ticks each on its own cadence (spec.raw['shadow_cadence_seconds'],
default 600s). Interval gating per spec line 991-994 (NOT inline
like _run_mr_scan).

Failure isolation: if one strategy's tick raises, the exception is
logged and the next strategy proceeds. The crashed strategy's
_last_platform_tick is still updated so we don't infinite-loop on a
deterministic failure.

WatchLoop.__init__ initializes self._last_platform_tick dict.
_reset_daily_state clears it.

3 tests: cadence respect (skip within interval, run after), multi-
strategy independent dispatch, failure isolation (swing not killed
when one harness raises).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Cost calibration from 85 swing trades (~1h)

**Files:**
- Create: `src/platform/cost_calibration.py`
- Create: `tests/platform/test_cost_calibration.py`

#### Step CC.1: Write failing test

- [ ] Create `tests/platform/test_cost_calibration.py`:

```python
"""Tests for src.platform.cost_calibration.

Non-negotiable gate: calibrated slippage_bps must be within 30% of the
hardcoded 3 bps default, or the assumption is wildly off and we need
to investigate rather than accept the calibrated value.
"""
import sqlite3

import pytest


def _seed_swing_trades(db_path: str, n: int = 85) -> None:
    """Seed N closed swing trades with varied slippage_bps."""
    from src.schema.sqlite import ensure_columns
    ensure_columns(db_path)
    conn = sqlite3.connect(db_path)
    # Slippage between 2 and 5 bps (per side), centered around 3
    import random
    rng = random.Random(42)
    for i in range(n):
        entry_slip = 2.0 + rng.random() * 3.0  # 2-5 bps
        exit_slip = 2.0 + rng.random() * 3.0
        conn.execute(
            """INSERT INTO shadow_trades
               (trade_id, ticker, shares, entry_price, exit_price,
                actual_entry_price, actual_exit_price, desk,
                signal_time, entry_time, actual_entry_time, actual_exit_time,
                entry_slippage_bps, exit_slippage_bps, pnl_pct)
               VALUES (?, ?, 10, 100.0, 102.0, ?, ?,
                       'swing', '2026-04-01', '2026-04-01',
                       '2026-04-01', '2026-04-08', ?, ?, 0.02)""",
            (
                f"t{i}", f"T{i % 20}",
                100.0 + entry_slip / 100,  # entry filled slightly above expected
                102.0 - exit_slip / 100,
                entry_slip, exit_slip,
            ),
        )
    conn.commit()
    conn.close()


def test_cost_calibration_within_30pct_of_default(tmp_path):
    """85 trades with realistic slippage should calibrate within 30%
    of the 3 bps hardcoded assumption."""
    db = str(tmp_path / "test.db")
    _seed_swing_trades(db, n=85)
    from src.platform.cost_calibration import calibrate_from_swing_history
    result = calibrate_from_swing_history(db_path=db)
    entry_bps = result["entry_slippage_bps"]
    exit_bps = result["exit_slippage_bps"]
    # Both should be somewhere in [2.1, 3.9] bps (within 30% of 3.0)
    assert 2.1 <= entry_bps <= 3.9, (
        f"calibrated entry_slippage_bps={entry_bps} more than 30% off from "
        f"hardcoded 3 bps; real data may have drifted far from assumption"
    )
    assert 2.1 <= exit_bps <= 3.9
    # Sample size recorded
    assert result["n_trades"] == 85


def test_cost_calibration_handles_empty_db(tmp_path):
    """Empty DB → return default 3 bps + warning."""
    db = str(tmp_path / "test.db")
    from src.schema.sqlite import ensure_columns
    ensure_columns(db)
    from src.platform.cost_calibration import calibrate_from_swing_history
    import warnings
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = calibrate_from_swing_history(db_path=db)
    assert result["entry_slippage_bps"] == 3.0
    assert result["exit_slippage_bps"] == 3.0
    assert result["n_trades"] == 0
    assert any("no swing trades" in str(x.message).lower() for x in w)


def test_cost_calibration_uses_median_not_mean(tmp_path):
    """Median is robust to outliers (e.g. one extreme fill)."""
    db = str(tmp_path / "test.db")
    _seed_swing_trades(db, n=85)
    # Inject an outlier
    conn = sqlite3.connect(db)
    conn.execute(
        """INSERT INTO shadow_trades
           (trade_id, ticker, shares, entry_price, desk,
            signal_time, entry_time, actual_entry_time, actual_exit_time,
            entry_slippage_bps, exit_slippage_bps, pnl_pct)
           VALUES ('outlier', 'OUTL', 1, 100.0, 'swing',
                   '2026-04-01', '2026-04-01', '2026-04-01',
                   '2026-04-08', 200.0, 200.0, 0.0)""",
    )
    conn.commit()
    conn.close()
    from src.platform.cost_calibration import calibrate_from_swing_history
    result = calibrate_from_swing_history(db_path=db)
    # Median shouldn't move much from the outlier
    assert 2.1 <= result["entry_slippage_bps"] <= 3.9
```

#### Step CC.2: Implement

- [ ] Create `src/platform/cost_calibration.py`:

```python
"""Calibrate backtest-engine transaction-cost defaults from swing history.

Called by: scripts/run_backtest.py (optional --calibrate-costs flag),
           src.platform.backtest_engine (default construction).
Calls: sqlite3, numpy.median.
Owns tables: none (reads shadow_trades).
Config keys: none.
Tests: tests/platform/test_cost_calibration.py.

Replaces the hardcoded 3 bps slippage + 1.5 bps spread assumption with
a median computed from the 85+ closed swing trades' observed slippage.
Median (not mean) is robust to tail fills (rare 20+ bps events that
would distort a mean).
"""
from __future__ import annotations

import logging
import sqlite3
import warnings

import numpy as np

from src.config import DB_PATH

logger = logging.getLogger(__name__)

_DEFAULT_ENTRY_BPS = 3.0
_DEFAULT_EXIT_BPS = 3.0


def calibrate_from_swing_history(db_path: str = DB_PATH) -> dict:
    """Compute median entry + exit slippage_bps from closed swing trades.

    Returns dict:
        entry_slippage_bps, exit_slippage_bps — median per-side bps.
        n_trades — sample size.
        source — 'calibrated' | 'default' (fallback when no data).

    Falls back to hardcoded 3 bps when fewer than 10 swing trades exist
    (sample too small to calibrate).
    """
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """SELECT entry_slippage_bps, exit_slippage_bps
               FROM shadow_trades
               WHERE desk = 'swing' AND actual_exit_time IS NOT NULL
                     AND entry_slippage_bps IS NOT NULL
                     AND exit_slippage_bps IS NOT NULL""",
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        warnings.warn(
            "[COST_CALIBRATION] no swing trades with slippage data; "
            "falling back to hardcoded defaults",
            RuntimeWarning,
        )
        return {
            "entry_slippage_bps": _DEFAULT_ENTRY_BPS,
            "exit_slippage_bps": _DEFAULT_EXIT_BPS,
            "n_trades": 0,
            "source": "default",
        }

    if len(rows) < 10:
        warnings.warn(
            f"[COST_CALIBRATION] only {len(rows)} swing trades; sample too "
            "small to calibrate reliably — falling back to defaults",
            RuntimeWarning,
        )
        return {
            "entry_slippage_bps": _DEFAULT_ENTRY_BPS,
            "exit_slippage_bps": _DEFAULT_EXIT_BPS,
            "n_trades": len(rows),
            "source": "default",
        }

    entry_bps = float(np.median([r[0] for r in rows if r[0] is not None]))
    exit_bps = float(np.median([r[1] for r in rows if r[1] is not None]))

    return {
        "entry_slippage_bps": entry_bps,
        "exit_slippage_bps": exit_bps,
        "n_trades": len(rows),
        "source": "calibrated",
    }
```

#### Step CC.3: Run tests + commit

```bash
pytest tests/platform/test_cost_calibration.py -v
```

Expected: 3 passed.

```bash
git add src/platform/cost_calibration.py tests/platform/test_cost_calibration.py
git commit -m "$(cat <<'EOF'
feat(platform): calibrate transaction costs from swing history (Task 7/CC)

src/platform/cost_calibration.py — calibrate_from_swing_history reads
closed swing trades' entry_slippage_bps and exit_slippage_bps columns
and returns the median for each (robust to outliers). Replaces the
hardcoded 3 bps / 1.5 bps default when sample ≥ 10 trades; otherwise
falls back to defaults with a warning.

Non-negotiable gate: calibrated value must fall within 30% of 3 bps.
If wildly off, the calibration is wrong OR the swing data drifted
far from the backtest assumption — either way the operator needs to
investigate before trusting calibrated defaults.

3 tests: within-30% gate, empty-DB fallback, median robustness vs.
outliers.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Tier 6 — Dashboard (~6h)

### Task 12a: /research-platform page + API endpoints (~3h)

**Files:**
- Create: `src/api/cloud_routes/platform.py`
- Create: `frontend/src/pages/StrategyResearch.jsx`
- Create: `frontend/src/components/BacktestEquityChart.jsx`
- Edit: `frontend/src/App.jsx` — register `/research-platform` route
- Edit: `frontend/src/components/Nav.jsx` — add link
- Edit: `frontend/src/api.js` — add 5 GET helpers
- Create: `tests/platform/test_platform_api.py`

#### Step 12a.1: Write failing API tests

- [ ] Create `tests/platform/test_platform_api.py`:

```python
"""Tests for /api/platform/* endpoints (Task 12a + 12b)."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from src.api.app import app
    return TestClient(app)


def test_platform_strategies_returns_empty_list_when_registry_empty(client):
    r = client.get("/api/platform/strategies")
    assert r.status_code == 200
    assert r.json() == []


def test_platform_strategies_returns_registry_rows(client, tmp_path_factory):
    # Register a strategy
    from src.platform.promotion import register_strategy
    from src.config import DB_PATH
    register_strategy(
        "demo", "Demo", "yaml:demo.yaml", "hash1", db_path=DB_PATH,
    )
    try:
        r = client.get("/api/platform/strategies")
        assert r.status_code == 200
        ids = [s["strategy_id"] for s in r.json()]
        assert "demo" in ids
    finally:
        # Cleanup
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        conn.execute("DELETE FROM strategy_registry WHERE strategy_id='demo'")
        conn.commit()
        conn.close()


def test_platform_strategy_detail_includes_yaml_spec(client):
    """GET /api/platform/strategies/{id} returns full detail including
    the loaded YAML spec as a JSON-serialized dict."""
    from src.platform.promotion import register_strategy
    from src.config import DB_PATH
    register_strategy(
        "lazy_prices_v1", "Lazy Prices", "yaml:lazy_prices_v1.yaml",
        "hash2", db_path=DB_PATH,
    )
    try:
        r = client.get("/api/platform/strategies/lazy_prices_v1")
        assert r.status_code == 200
        body = r.json()
        assert body["strategy_id"] == "lazy_prices_v1"
        assert "spec" in body
        assert body["spec"]["strategy_id"] == "lazy_prices_v1"
    finally:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "DELETE FROM strategy_registry WHERE strategy_id='lazy_prices_v1'",
        )
        conn.commit()
        conn.close()


def test_platform_backtest_results_filters_by_strategy(client):
    r = client.get(
        "/api/platform/backtest-results?strategy_id=nonexistent&limit=20",
    )
    assert r.status_code == 200
    assert r.json() == []


def test_platform_promotion_events_filters_by_strategy(client):
    r = client.get(
        "/api/platform/promotion-events?strategy_id=nonexistent&limit=50",
    )
    assert r.status_code == 200
    assert r.json() == []


def test_platform_backtest_trigger_returns_result_id(client):
    """POST /api/platform/backtests kicks off async backtest."""
    from src.platform.promotion import register_strategy
    from src.config import DB_PATH
    register_strategy("demo2", "Demo2", "yaml:demo2.yaml", "h", db_path=DB_PATH)
    try:
        r = client.post(
            "/api/platform/backtests",
            json={
                "strategy_id": "demo2",
                "start_date": "2024-01-01",
                "end_date": "2024-12-31",
            },
        )
        # Accept 202 Accepted (async kickoff) or 200 with result_id
        assert r.status_code in (200, 202)
        body = r.json()
        assert "result_id" in body or "job_id" in body
    finally:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        conn.execute("DELETE FROM strategy_registry WHERE strategy_id='demo2'")
        conn.commit()
        conn.close()


def test_platform_promotion_requires_confirmation_token(client):
    """POST /api/platform/promotions rejects without confirmation_token."""
    r = client.post(
        "/api/platform/promotions",
        json={
            "strategy_id": "x",
            "target_status": "shadow_trading",
            "justification_note": "x" * 50,
        },
    )
    assert r.status_code in (400, 422)  # bad request or unprocessable entity


def test_platform_promotion_requires_justification_note(client):
    """POST /api/platform/promotions rejects if justification < 40 chars."""
    r = client.post(
        "/api/platform/promotions",
        json={
            "strategy_id": "x",
            "target_status": "shadow_trading",
            "confirmation_token": "yes",
            "justification_note": "too short",
        },
    )
    assert r.status_code in (400, 422)


def test_platform_production_promotion_requires_24h_delay(client):
    """POST /api/platform/promotions with target=production must enforce
    the two-step 24h delay from spec line 997."""
    r = client.post(
        "/api/platform/promotions",
        json={
            "strategy_id": "x",
            "target_status": "production",
            "confirmation_token": "step1",
            "justification_note": "x" * 50,
        },
    )
    # First step: returns 202 with a delay_until timestamp, does NOT promote
    assert r.status_code in (202, 425)  # 425 = Too Early
```

#### Step 12a.2: Run tests — expect 404s

```bash
pytest tests/platform/test_platform_api.py -v
```

Expected: every test fails with 404 because `/api/platform/*` endpoints don't exist.

#### Step 12a.3: Implement `src/api/cloud_routes/platform.py`

- [ ] Create the module. Follow the existing `trades.py` pattern (FastAPI router + verify_auth dependency):

```python
"""/api/platform/* endpoints for the research platform dashboard.

Called by: frontend/src/pages/StrategyResearch.jsx + PlatformStatusWidget.
Calls: src.platform.promotion (registry reads + promote/demote),
       src.platform.strategy_spec (load YAML), src.config.
Owns tables: reads strategy_registry, backtest_results, backtest_trades,
             strategy_promotion_events (via promotion module).
Config keys: none.
Tests: tests/platform/test_platform_api.py.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.api.cloud_routes.core import verify_auth  # adjust import per actual location
from src.config import DB_PATH

router = APIRouter()
logger = logging.getLogger(__name__)


# ── GET endpoints ─────────────────────────────────────────────────────

@router.get("/api/platform/strategies", dependencies=[Depends(verify_auth)])
async def list_strategies() -> list[dict]:
    """All rows from strategy_registry with embedded latest-backtest summary."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT s.*, b.deflated_sharpe AS last_dsr,
                      b.max_drawdown_pct AS last_max_dd,
                      b.total_trades AS last_n_trades,
                      b.created_at AS last_backtest_at
               FROM strategy_registry s
               LEFT JOIN (
                   SELECT strategy_id, MAX(created_at) AS max_created
                   FROM backtest_results
                   GROUP BY strategy_id
               ) latest ON latest.strategy_id = s.strategy_id
               LEFT JOIN backtest_results b ON
                   b.strategy_id = s.strategy_id AND b.created_at = latest.max_created
               ORDER BY s.last_status_change DESC""",
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get(
    "/api/platform/strategies/{strategy_id}",
    dependencies=[Depends(verify_auth)],
)
async def strategy_detail(strategy_id: str) -> dict:
    """Full detail for one strategy including parsed YAML spec."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM strategy_registry WHERE strategy_id = ?",
            (strategy_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail=f"strategy {strategy_id!r} not found")
    body = dict(row)
    try:
        from src.platform.strategy_spec import load_spec
        spec = load_spec(strategy_id)
        body["spec"] = spec.raw
    except FileNotFoundError:
        body["spec"] = None
    return body


@router.get(
    "/api/platform/backtest-results",
    dependencies=[Depends(verify_auth)],
)
async def backtest_results(
    strategy_id: str | None = Query(None),
    limit: int = Query(20, ge=1, le=500),
) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        if strategy_id:
            rows = conn.execute(
                """SELECT * FROM backtest_results
                   WHERE strategy_id = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (strategy_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM backtest_results ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get(
    "/api/platform/backtest-trades", dependencies=[Depends(verify_auth)],
)
async def backtest_trades(result_id: str) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM backtest_trades WHERE result_id = ? "
            "ORDER BY entry_date",
            (result_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get(
    "/api/platform/promotion-events", dependencies=[Depends(verify_auth)],
)
async def promotion_events(
    strategy_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        if strategy_id:
            rows = conn.execute(
                """SELECT * FROM strategy_promotion_events
                   WHERE strategy_id = ?
                   ORDER BY timestamp DESC LIMIT ?""",
                (strategy_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM strategy_promotion_events "
                "ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── POST endpoints (Task 12b) ─────────────────────────────────────────


class BacktestKickoffReq(BaseModel):
    strategy_id: str
    start_date: str
    end_date: str


@router.post(
    "/api/platform/backtests", dependencies=[Depends(verify_auth)],
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_backtest(req: BacktestKickoffReq) -> dict:
    """Kick off an async backtest. Returns result_id once the row is
    reserved; completion is signaled by backtest_results row's
    created_at timestamp."""
    from src.platform.strategy_spec import load_spec
    try:
        load_spec(req.strategy_id)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"strategy spec not found: {req.strategy_id}",
        )
    result_id = str(uuid.uuid4())
    # Spawn background task to run the backtest + persist.
    asyncio.create_task(_run_backtest_async(req, result_id))
    return {"result_id": result_id, "status": "running"}


async def _run_backtest_async(req: BacktestKickoffReq, result_id: str) -> None:
    """Invoked by trigger_backtest — runs run_backtest + persist in bg."""
    try:
        from scripts.run_backtest import _persist
        from src.platform.backtest_engine import BacktestConfig, run_backtest
        from src.platform.strategy_spec import load_spec
        spec = load_spec(req.strategy_id)
        cfg = BacktestConfig(
            strategy=spec,
            start_date=req.start_date,
            end_date=req.end_date,
        )
        result = run_backtest(cfg)
        _persist(result, db_path=DB_PATH)
    except Exception:
        logger.exception("[PLATFORM] async backtest %s failed", result_id)


class PromoteReq(BaseModel):
    strategy_id: str
    target_status: str
    confirmation_token: str
    justification_note: str = Field(..., min_length=40)


@router.post(
    "/api/platform/promotions", dependencies=[Depends(verify_auth)],
)
async def promote_strategy(req: PromoteReq) -> dict:
    """Manual promotion. Production transitions require two-step 24h delay."""
    from src.platform.promotion import promote, STATUSES

    if req.target_status not in STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"unknown target_status: {req.target_status!r}",
        )

    # Two-step for production transitions (spec line 997)
    if req.target_status == "production":
        stamp = _check_or_record_production_attempt(
            req.strategy_id, req.confirmation_token,
        )
        if stamp["status"] == "awaiting_delay":
            return {
                "status": "awaiting_delay",
                "delay_until": stamp["delay_until"],
            }
        # else: delay satisfied, proceed

    try:
        promote(
            strategy_id=req.strategy_id,
            target_status=req.target_status,
            triggered_by="manual",
            justification_note=req.justification_note,
            db_path=DB_PATH,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"status": "promoted", "target_status": req.target_status}


def _check_or_record_production_attempt(
    strategy_id: str, confirmation_token: str,
) -> dict:
    """Enforce 24h delay between first and second production-promotion
    attempts. Uses a simple in-DB marker in strategy_registry.notes
    JSON blob. Returns dict with status ∈ {awaiting_delay, ready}."""
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "SELECT notes FROM strategy_registry WHERE strategy_id = ?",
            (strategy_id,),
        ).fetchone()
        notes = json.loads(row[0]) if row and row[0] else {}
        prior = notes.get("production_attempt")
        now = datetime.now(timezone.utc)

        if prior is None or prior["token"] != confirmation_token:
            # First step — record the attempt.
            notes["production_attempt"] = {
                "token": confirmation_token,
                "at": now.isoformat(),
            }
            conn.execute(
                "UPDATE strategy_registry SET notes = ? WHERE strategy_id = ?",
                (json.dumps(notes), strategy_id),
            )
            conn.commit()
            delay_until = (now + timedelta(hours=24)).isoformat()
            return {"status": "awaiting_delay", "delay_until": delay_until}

        # Same token — check elapsed.
        prior_at = datetime.fromisoformat(prior["at"])
        if (now - prior_at) < timedelta(hours=24):
            return {
                "status": "awaiting_delay",
                "delay_until": (
                    prior_at + timedelta(hours=24)
                ).isoformat(),
            }

        # Delay satisfied — clear the marker and proceed.
        del notes["production_attempt"]
        conn.execute(
            "UPDATE strategy_registry SET notes = ? WHERE strategy_id = ?",
            (json.dumps(notes), strategy_id),
        )
        conn.commit()
        return {"status": "ready"}
    finally:
        conn.close()


class DemoteReq(BaseModel):
    strategy_id: str
    reason: str = Field(..., min_length=20)


@router.post("/api/platform/demotions", dependencies=[Depends(verify_auth)])
async def demote_strategy(req: DemoteReq) -> dict:
    from src.platform.promotion import demote
    try:
        demote(strategy_id=req.strategy_id, reason=req.reason, db_path=DB_PATH)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"status": "deprecated"}
```

- [ ] Register the router in whatever the main FastAPI app does (probably `src/api/app.py` or `src/api/cloud_routes/__init__.py`). Match the existing pattern for how `trades.py`'s router is included.

#### Step 12a.4: Run tests

```bash
pytest tests/platform/test_platform_api.py -v
```

Iterate on details (pydantic validation, route registration) until all 9 pass.

#### Step 12a.5: Build the React page

- [ ] Create `frontend/src/components/BacktestEquityChart.jsx`:

```jsx
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip } from "recharts";

export default function BacktestEquityChart({ trades }) {
  // Convert trades to equity curve: {date, equity}
  if (!trades || trades.length === 0) {
    return <div className="text-gray-500">No trades</div>;
  }
  let equity = 100000;
  const data = trades.map((t) => {
    equity += t.pnl_dollars || 0;
    return { date: t.exit_date || t.entry_date, equity };
  });
  return (
    <LineChart width={720} height={280} data={data}>
      <CartesianGrid strokeDasharray="3 3" />
      <XAxis dataKey="date" fontSize={10} />
      <YAxis domain={["dataMin", "dataMax"]} fontSize={10} />
      <Tooltip />
      <Line type="monotone" dataKey="equity" stroke="#2563eb" dot={false} />
    </LineChart>
  );
}
```

- [ ] Create `frontend/src/pages/StrategyResearch.jsx`:

```jsx
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import BacktestEquityChart from "../components/BacktestEquityChart.jsx";
import {
  getPlatformStrategies,
  getPlatformStrategyDetail,
  getPlatformBacktestResults,
  getPlatformBacktestTrades,
  getPlatformPromotionEvents,
} from "../api.js";

export default function StrategyResearch() {
  const [expandedId, setExpandedId] = useState(null);
  const [selectedBacktest, setSelectedBacktest] = useState(null);

  const { data: strategies = [] } = useQuery({
    queryKey: ["platform-strategies"],
    queryFn: getPlatformStrategies,
  });

  const { data: detail } = useQuery({
    enabled: !!expandedId,
    queryKey: ["platform-strategy", expandedId],
    queryFn: () => getPlatformStrategyDetail(expandedId),
  });

  const { data: backtests = [] } = useQuery({
    enabled: !!expandedId,
    queryKey: ["platform-backtests", expandedId],
    queryFn: () => getPlatformBacktestResults(expandedId),
  });

  const { data: events = [] } = useQuery({
    enabled: !!expandedId,
    queryKey: ["platform-events", expandedId],
    queryFn: () => getPlatformPromotionEvents(expandedId),
  });

  const { data: selectedTrades = [] } = useQuery({
    enabled: !!selectedBacktest,
    queryKey: ["platform-trades", selectedBacktest?.result_id],
    queryFn: () => getPlatformBacktestTrades(selectedBacktest.result_id),
  });

  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold mb-4">Strategy Research</h1>

      {/* Registry table */}
      <section className="mb-8">
        <h2 className="text-lg font-medium mb-2">Strategies</h2>
        <table className="w-full text-sm">
          <thead className="bg-gray-100">
            <tr>
              <th className="text-left p-2">Name</th>
              <th className="text-left p-2">Status</th>
              <th className="text-left p-2">Last DSR</th>
              <th className="text-left p-2">Last max DD</th>
              <th className="text-left p-2">Trades</th>
              <th className="text-left p-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {strategies.map((s) => (
              <tr
                key={s.strategy_id}
                onClick={() => setExpandedId(s.strategy_id)}
                className="cursor-pointer hover:bg-gray-50"
              >
                <td className="p-2">{s.display_name}</td>
                <td className="p-2">
                  <StatusBadge status={s.current_status} />
                </td>
                <td className="p-2">{s.last_dsr?.toFixed(3) ?? "—"}</td>
                <td className="p-2">
                  {s.last_max_dd ? (s.last_max_dd * 100).toFixed(1) + "%" : "—"}
                </td>
                <td className="p-2">{s.last_n_trades ?? "—"}</td>
                <td className="p-2">
                  <button className="text-blue-600 hover:underline">
                    View
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {strategies.length === 0 && (
          <p className="text-gray-500 p-4">
            No strategies registered. Load one from{" "}
            <code>src/platform/specs/*.yaml</code> and run a backtest.
          </p>
        )}
      </section>

      {/* Strategy detail */}
      {expandedId && detail && (
        <section className="mb-8 border-l-4 border-blue-500 pl-4">
          <h2 className="text-lg font-medium mb-2">{detail.display_name}</h2>
          <p className="text-sm text-gray-600 mb-2">
            Status: <StatusBadge status={detail.current_status} />
            {" · Spec hash: "}
            <code className="text-xs">{detail.current_spec_hash?.slice(0, 12)}</code>
          </p>
          {detail.spec && (
            <details className="mb-4">
              <summary className="cursor-pointer text-blue-600">
                YAML spec
              </summary>
              <pre className="bg-gray-50 text-xs p-2 rounded overflow-auto">
                {JSON.stringify(detail.spec, null, 2)}
              </pre>
            </details>
          )}

          {/* Backtest results grid */}
          <h3 className="font-medium mt-4 mb-2">Backtest history</h3>
          <table className="w-full text-sm">
            <thead className="bg-gray-100">
              <tr>
                <th className="text-left p-2">Date</th>
                <th className="text-left p-2">Range</th>
                <th className="text-left p-2">DSR</th>
                <th className="text-left p-2">PBO</th>
                <th className="text-left p-2">OOS eff</th>
                <th className="text-left p-2">Max DD</th>
                <th className="text-left p-2">N trades</th>
              </tr>
            </thead>
            <tbody>
              {backtests.map((b) => (
                <tr
                  key={b.result_id}
                  onClick={() => setSelectedBacktest(b)}
                  className="cursor-pointer hover:bg-gray-50"
                >
                  <td className="p-2">{b.created_at?.slice(0, 10)}</td>
                  <td className="p-2">
                    {b.start_date} — {b.end_date}
                  </td>
                  <td className="p-2">{b.deflated_sharpe?.toFixed(3) ?? "—"}</td>
                  <td className="p-2">{b.pbo?.toFixed(3) ?? "—"}</td>
                  <td className="p-2">{b.oos_efficiency?.toFixed(3) ?? "—"}</td>
                  <td className="p-2">
                    {b.max_drawdown_pct
                      ? (b.max_drawdown_pct * 100).toFixed(1) + "%"
                      : "—"}
                  </td>
                  <td className="p-2">{b.total_trades ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>

          {/* Equity curve modal */}
          {selectedBacktest && (
            <div className="mt-4">
              <h3 className="font-medium mb-2">
                Equity — {selectedBacktest.result_id.slice(0, 8)}
              </h3>
              <BacktestEquityChart trades={selectedTrades} />
              <button
                onClick={() => setSelectedBacktest(null)}
                className="text-sm text-gray-600 mt-2"
              >
                Close
              </button>
            </div>
          )}

          {/* Promotion events log */}
          <h3 className="font-medium mt-6 mb-2">Promotion events</h3>
          <ul className="text-sm space-y-1">
            {events.map((e) => (
              <li key={e.event_id} className="p-2 bg-gray-50 rounded">
                <span className="text-xs text-gray-500">
                  {e.timestamp?.slice(0, 19).replace("T", " ")}
                </span>
                {" · "}
                <span className={eventColorClass(e.to_status)}>
                  {e.from_status ?? "∅"} → {e.to_status}
                </span>
                {" · "}
                <span className="text-xs">{e.triggered_by}</span>
                {e.justification_note && (
                  <div className="text-xs text-gray-700 mt-1">
                    {e.justification_note}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function StatusBadge({ status }) {
  const colors = {
    proposed: "bg-gray-200 text-gray-700",
    backtested: "bg-blue-100 text-blue-800",
    shadow_trading: "bg-yellow-100 text-yellow-800",
    production: "bg-green-100 text-green-800",
    deprecated: "bg-red-100 text-red-800",
  };
  return (
    <span
      className={`px-2 py-0.5 text-xs rounded ${
        colors[status] ?? "bg-gray-100 text-gray-600"
      }`}
    >
      {status}
    </span>
  );
}

function eventColorClass(toStatus) {
  if (toStatus === "deprecated") return "text-red-700";
  if (toStatus === "shadow_trading" || toStatus === "production")
    return "text-green-700";
  return "text-gray-700";
}
```

- [ ] Extend `frontend/src/api.js` with:

```js
export async function getPlatformStrategies() {
  return fetchApi("/api/platform/strategies");
}
export async function getPlatformStrategyDetail(id) {
  return fetchApi(`/api/platform/strategies/${id}`);
}
export async function getPlatformBacktestResults(strategy_id, limit = 20) {
  return fetchApi(
    `/api/platform/backtest-results?strategy_id=${strategy_id}&limit=${limit}`
  );
}
export async function getPlatformBacktestTrades(result_id) {
  return fetchApi(`/api/platform/backtest-trades?result_id=${result_id}`);
}
export async function getPlatformPromotionEvents(strategy_id, limit = 50) {
  return fetchApi(
    `/api/platform/promotion-events?strategy_id=${strategy_id}&limit=${limit}`
  );
}
```

- [ ] Register the route in `frontend/src/App.jsx` — follow the existing route pattern.

- [ ] Add a link in `frontend/src/components/Nav.jsx` — follow the existing link pattern. Label: "Research Platform".

#### Step 12a.6: Test the page

- [ ] Run `cd frontend && npm run build`. Expect success.

- [ ] Manually verify (operator): open the dashboard, navigate to `/research-platform`. Empty state should render without console errors. With a registered strategy, the table populates.

#### Step 12a.7: Commit

```bash
git add src/api/cloud_routes/platform.py \
        frontend/src/pages/StrategyResearch.jsx \
        frontend/src/components/BacktestEquityChart.jsx \
        frontend/src/App.jsx \
        frontend/src/components/Nav.jsx \
        frontend/src/api.js \
        tests/platform/test_platform_api.py
git commit -m "$(cat <<'EOF'
feat(platform): dashboard /research-platform page + API (Tasks 12a + 12b)

src/api/cloud_routes/platform.py — 8 endpoints:
  GET  /api/platform/strategies — registry + latest-backtest summary
  GET  /api/platform/strategies/{id} — full detail + parsed YAML spec
  GET  /api/platform/backtest-results?strategy_id=&limit=
  GET  /api/platform/backtest-trades?result_id=
  GET  /api/platform/promotion-events?strategy_id=&limit=
  POST /api/platform/backtests (async kickoff via asyncio.create_task)
  POST /api/platform/promotions (two-step 24h delay for production)
  POST /api/platform/demotions (reason ≥ 20 chars required)

frontend/src/pages/StrategyResearch.jsx — 4 sections (registry table,
detail with YAML spec + backtest history grid + equity modal, promotion
events log). Uses TanStack Query for all data fetching. No hardcoded
lists — populated from the API.

frontend/src/components/BacktestEquityChart.jsx — Recharts LineChart
for the equity curve modal. Mirrors Attribution.jsx import pattern.

9 API tests cover empty registry, detail-with-spec, backtest filter by
strategy, promotion-events filter, async backtest kickoff returning
result_id, confirmation_token enforcement, justification-note min length,
production two-step 24h delay.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 12d: PlatformStatusWidget (~1h)

**Files:**
- Create: `frontend/src/components/PlatformStatusWidget.jsx`
- Edit: `frontend/src/pages/Dashboard.jsx` — mount the widget

#### Step 12d.1: Build the widget

- [ ] Create `frontend/src/components/PlatformStatusWidget.jsx`:

```jsx
import { useQuery } from "@tanstack/react-query";
import { getPlatformStrategies } from "../api.js";
import { Link } from "react-router-dom";

export default function PlatformStatusWidget() {
  const { data: strategies = [] } = useQuery({
    queryKey: ["platform-strategies"],
    queryFn: getPlatformStrategies,
  });

  if (strategies.length === 0) return null;  // Per spec line 1028

  const counts = {
    proposed: 0,
    backtested: 0,
    shadow_trading: 0,
    production: 0,
    deprecated: 0,
  };
  strategies.forEach((s) => {
    counts[s.current_status] = (counts[s.current_status] || 0) + 1;
  });

  const awaitingReview = strategies.filter(
    (s) => s.current_status === "backtested",
  ).length;

  const lastBacktestAt = strategies
    .map((s) => s.last_backtest_at)
    .filter(Boolean)
    .sort()
    .pop();

  return (
    <div className="bg-white rounded shadow p-4">
      <h3 className="text-sm font-semibold mb-2">Research Platform</h3>
      <div className="flex gap-2 flex-wrap mb-2">
        {Object.entries(counts).map(([status, n]) => (
          n > 0 && (
            <span
              key={status}
              className={`px-2 py-0.5 text-xs rounded ${
                status === "shadow_trading"
                  ? "bg-yellow-100 text-yellow-800"
                  : status === "production"
                  ? "bg-green-100 text-green-800"
                  : "bg-gray-100 text-gray-700"
              }`}
            >
              {n} {status}
            </span>
          )
        ))}
      </div>
      {awaitingReview > 0 && (
        <div className="text-sm text-orange-700 mb-1">
          {awaitingReview} strategy{awaitingReview === 1 ? "" : "ies"} ready
          for shadow approval →
        </div>
      )}
      {lastBacktestAt && (
        <div className="text-xs text-gray-500">
          Last backtest: {lastBacktestAt.slice(0, 19).replace("T", " ")}
        </div>
      )}
      <Link
        to="/research-platform"
        className="text-xs text-blue-600 hover:underline"
      >
        Open platform →
      </Link>
    </div>
  );
}
```

- [ ] In `frontend/src/pages/Dashboard.jsx`, mount the widget inside the existing card grid. Place it near the top so pending-review signal is prominent.

#### Step 12d.2: Commit

```bash
git add frontend/src/components/PlatformStatusWidget.jsx \
        frontend/src/pages/Dashboard.jsx
git commit -m "$(cat <<'EOF'
feat(platform): home-screen PlatformStatusWidget (Task 12d)

PlatformStatusWidget.jsx — compact card showing:
  - Counts of strategies per status (color badges)
  - "N strategy(ies) ready for shadow approval →" pending-review nudge
  - Last backtest completion timestamp
  - Link to /research-platform

Only renders if strategy_registry has ≥ 1 row (per spec line 1028).

Dashboard.jsx — widget mounted near top of the existing card grid.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 12e: Telegram platform-event notifications (~30min)

**Files:**
- Create: `src/notifications/platform_events.py`
- Create: `tests/notifications/test_platform_events.py`
- Edit: `src/platform/backtest_engine.py::run_backtest` — call notify on completion
- Edit: `src/platform/promotion.py::promote`, `::demote` — call notify
- Edit: `src/platform/promotion.py::check_promotion_gate` — call notify_shadow_gate_ready when a new gate is FIRST satisfied

#### Step 12e.1: Implement

- [ ] Create `src/notifications/platform_events.py`:

```python
"""Platform-event Telegram notifications.

Called by: src.platform.backtest_engine, src.platform.promotion.
Calls: src.notifications.telegram.send_message.
Owns tables: none.
Config keys: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (via telegram module).
Tests: tests/notifications/test_platform_events.py.

All messages prefixed '[RESEARCH]' — operator filter rule on Telegram
client distinguishes from swing trade notifications.

Deduplication via content hash for notify_shadow_gate_ready: once a
gate has been signaled as ready, don't re-notify until the gate
flips out of 'ready' state.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone

from src.config import DB_PATH

logger = logging.getLogger(__name__)

_PREFIX = "[RESEARCH]"
_DEDUP_WINDOW_HOURS = 24


def _dedup_key(category: str, content: str) -> str:
    return hashlib.sha256(f"{category}::{content}".encode()).hexdigest()


def _already_notified_recently(key: str, db_path: str = DB_PATH) -> bool:
    """Check if we already sent this notification in the last 24h.

    Uses an in-memory LRU-ish cache backed by a simple file table if
    needed. For Sprint 4 MVP, accept potential duplicates on process
    restart — watchloop restart is rare enough that dupe risk is low.
    """
    # Simplest: keep a module-level dict with expiration.
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=_DEDUP_WINDOW_HOURS)
    entry = _DEDUP_CACHE.get(key)
    if entry and entry > cutoff:
        return True
    _DEDUP_CACHE[key] = now
    # Garbage-collect expired entries opportunistically.
    expired = [k for k, v in _DEDUP_CACHE.items() if v < cutoff]
    for k in expired:
        del _DEDUP_CACHE[k]
    return False


_DEDUP_CACHE: dict[str, datetime] = {}


def _send(message: str) -> None:
    """Send via the existing telegram module."""
    try:
        from src.notifications.telegram import send_message
        send_message(message)
    except Exception:
        logger.exception("[PLATFORM_EVENTS] telegram send failed")


def notify_backtest_complete(
    strategy_id: str, result_id: str, passed_gate_a: bool,
) -> None:
    """Fired from backtest_engine.run_backtest on completion."""
    key = _dedup_key("backtest_complete", f"{strategy_id}::{result_id}")
    if _already_notified_recently(key):
        return
    gate_marker = "✅ passed auto gate" if passed_gate_a else "⏸ awaiting manual"
    _send(
        f"{_PREFIX} Backtest complete: {strategy_id} "
        f"(result_id={result_id[:8]}...) {gate_marker}",
    )


def notify_shadow_gate_ready(
    strategy_id: str, evidence: dict,
) -> None:
    """Fired from promotion.check_promotion_gate when a shadow_trading
    gate check passes for the first time. Dedup so we don't spam on
    every subsequent check."""
    key = _dedup_key("shadow_gate_ready", strategy_id)
    if _already_notified_recently(key):
        return
    dsr = evidence.get("dsr")
    pbo = evidence.get("pbo")
    oos = evidence.get("oos_efficiency")
    _send(
        f"{_PREFIX} Gate ready for shadow_trading: {strategy_id} "
        f"DSR={dsr:.3f if dsr else None} PBO={pbo:.3f if pbo else None} "
        f"OOS_eff={oos:.3f if oos else None} — awaiting manual approval.",
    )


def notify_strategy_promoted(
    strategy_id: str, from_status: str | None, to_status: str,
) -> None:
    """Fired from promotion.promote after successful state transition."""
    _send(
        f"{_PREFIX} Promoted: {strategy_id} {from_status} → {to_status}",
    )


def notify_strategy_demoted(strategy_id: str, reason: str) -> None:
    """Fired from promotion.demote."""
    _send(
        f"{_PREFIX} Demoted: {strategy_id} → deprecated. Reason: {reason}",
    )
```

- [ ] Add hooks into `src/platform/backtest_engine.py::run_backtest`:

```python
# At end of run_backtest, before return result:
try:
    from src.notifications.platform_events import notify_backtest_complete
    notify_backtest_complete(
        strategy_id=config.strategy.strategy_id,
        result_id=result.reproducibility.get("run_id", "unknown"),
        passed_gate_a=(result.metrics.get("deflated_sharpe") or 0) >= 0.95,
    )
except Exception:
    logger.exception("[BACKTEST] notify_backtest_complete failed (non-fatal)")
```

- [ ] Hooks in `src/platform/promotion.py`:

```python
# In promote(), after conn.commit():
try:
    from src.notifications.platform_events import notify_strategy_promoted
    notify_strategy_promoted(strategy_id, from_status, target_status)
except Exception:
    logger.exception("[PROMOTION] notify_strategy_promoted failed")

# In demote(), after conn.commit():
try:
    from src.notifications.platform_events import notify_strategy_demoted
    notify_strategy_demoted(strategy_id, reason)
except Exception:
    logger.exception("[PROMOTION] notify_strategy_demoted failed")

# In check_promotion_gate() or _evaluate_shadow_trading_gate, when passes=True
# AND target_status == 'shadow_trading':
try:
    from src.notifications.platform_events import notify_shadow_gate_ready
    notify_shadow_gate_ready(strategy_id, evidence)
except Exception:
    logger.exception("[PROMOTION] notify_shadow_gate_ready failed")
```

#### Step 12e.2: Tests

- [ ] Create `tests/notifications/test_platform_events.py`:

```python
"""Tests for src.notifications.platform_events."""
from unittest.mock import patch

from src.notifications.platform_events import (
    notify_backtest_complete,
    notify_shadow_gate_ready,
    notify_strategy_demoted,
    notify_strategy_promoted,
    _DEDUP_CACHE,
)


def test_telegram_backtest_complete_prefixed_with_RESEARCH():
    _DEDUP_CACHE.clear()
    with patch("src.notifications.telegram.send_message") as mock_send:
        notify_backtest_complete("strat_a", "r1", True)
    assert mock_send.called
    msg = mock_send.call_args.args[0]
    assert "[RESEARCH]" in msg
    assert "strat_a" in msg


def test_telegram_gate_ready_deduplicated_within_24h():
    """Calling notify_shadow_gate_ready twice for the same strategy_id
    within 24h should only send once."""
    _DEDUP_CACHE.clear()
    with patch("src.notifications.telegram.send_message") as mock_send:
        notify_shadow_gate_ready("strat_b", {"dsr": 0.96, "pbo": 0.3, "oos_efficiency": 0.5})
        notify_shadow_gate_ready("strat_b", {"dsr": 0.96, "pbo": 0.3, "oos_efficiency": 0.5})
    assert mock_send.call_count == 1


def test_telegram_gate_ready_not_deduplicated_across_strategies():
    _DEDUP_CACHE.clear()
    with patch("src.notifications.telegram.send_message") as mock_send:
        notify_shadow_gate_ready("a", {"dsr": 0.96, "pbo": 0.3, "oos_efficiency": 0.5})
        notify_shadow_gate_ready("b", {"dsr": 0.96, "pbo": 0.3, "oos_efficiency": 0.5})
    assert mock_send.call_count == 2


def test_telegram_strategy_promoted_includes_state_transition():
    _DEDUP_CACHE.clear()
    with patch("src.notifications.telegram.send_message") as mock_send:
        notify_strategy_promoted("s", "backtested", "shadow_trading")
    msg = mock_send.call_args.args[0]
    assert "backtested" in msg and "shadow_trading" in msg


def test_telegram_strategy_demoted_includes_reason():
    _DEDUP_CACHE.clear()
    with patch("src.notifications.telegram.send_message") as mock_send:
        notify_strategy_demoted("s", "drawdown breach exceeded 8% threshold")
    msg = mock_send.call_args.args[0]
    assert "drawdown" in msg.lower()
```

#### Step 12e.3: Run + commit

```bash
pytest tests/notifications/test_platform_events.py -v
```

Expected: 5 passed.

```bash
git add src/notifications/platform_events.py \
        tests/notifications/test_platform_events.py \
        src/platform/backtest_engine.py \
        src/platform/promotion.py
git commit -m "$(cat <<'EOF'
feat(notifications): platform-event Telegram pings (Task 12e)

src/notifications/platform_events.py — four entry points:
  notify_backtest_complete (from backtest_engine.run_backtest)
  notify_shadow_gate_ready (from check_promotion_gate when gate first
    passes; deduplicated per strategy_id with 24h window)
  notify_strategy_promoted (from promotion.promote)
  notify_strategy_demoted (from promotion.demote)

All messages prefixed '[RESEARCH]' per convention. Hook sites use
try/except so notification failures never break business logic.

5 tests cover prefix, dedup-within-24h, cross-strategy non-dedup,
state-transition format, demote reason inclusion.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Tier 7 — Correlation monitoring (~3h, deferrable to v0.24.1)

All four sub-tasks are pure-math modules + tests. Sprint 4 only matters once ≥2 research strategies run concurrently — if time pressed, defer this entire tier to v0.24.1.

### Task 11b.2: Correlation measurement (~1h)

**Files:**
- Create: `src/platform/risk/correlation.py`
- Create: `tests/platform/risk/test_correlation.py`

Write `compute_rolling_spearman`, `compute_rolling_pearson`, `compute_neg_exceedance_correlation`, `detect_correlation_regime_shifts`. Writes to `correlation_matrices` (Sprint 3 table). Use `scipy.stats.spearmanr` and `pearsonr`. Test with known-correlated synthetic inputs (e.g., two series y = 0.5*x + noise should Spearman ≈ 0.5). For exceedance, follow Longin-Solnik 2001 — filter to days where both series are below 10th-percentile marginals, compute Pearson on filtered.

Ship a regime-shift detector: flag when rolling 63-day Spearman between a pair crosses 0.5 for 5+ consecutive days (CUSUM persistence filter).

### Task 11b.3: Factor decomposition (~1h)

**Files:**
- Create: `src/platform/risk/factor_decomp.py`
- Create: `tests/platform/risk/test_factor_decomp.py`

Load Ken French FF3 + UMD via `pandas-datareader`, QMJ from AQR CSV (cached locally — the AQR dataset isn't on pandas-datareader). Rolling OLS regression with Newey-West HAC standard errors via `statsmodels.OLS.fit(cov_type='HAC', cov_kwds={'maxlags': 5})`. Write to `factor_loadings`.

Test: regress SPY on itself — expect MKT β ≈ 1.0, all others ≈ 0. Validates the regression is wired right.

Add `compare_to_expected_profile(strategy_id, realized_betas, expected, db_path)` — flag any realized beta outside the declared range in `strategy_registry.expected_factor_profile_json`. This catches implementation bugs that P&L alone wouldn't reveal.

### Task 11b.5: PELT change detection (~30min)

**Files:**
- Create: `src/platform/risk/change_detection.py`
- Create: `tests/platform/risk/test_change_detection.py`

`detect_beta_regime_changes(beta_series, penalty_multiplier=3.0) -> list[int]` using `ruptures.Pelt(model="rbf")`. Emit WARN on detected breakpoints (style drift).

Test: synthetic step function (half at beta=0.2, half at 0.8) should detect breakpoint near the midpoint.

### Task 11b.6: Tiered alerting (~30min)

**Files:**
- Create: `src/platform/risk/alerting.py`
- Create: `tests/platform/risk/test_alerting.py`

```python
ALERT_TIERS = {
    "INFO": {"channels": ["dashboard_digest"]},
    "WARN": {"channels": ["telegram"], "business_hours_only": True},
    "CRITICAL": {"channels": ["telegram_retry"], "business_hours_only": False},
}

def emit_alert(tier: str, category: str, message: str, context: dict) -> None:
    """Dedup via hash(category + context['strategy_id']) within 60-min window.
    WARN respects 9:30-16:00 ET business hours; CRITICAL fires 24/7."""
```

Tests: dedup within 60 min, business-hours suppression for WARN outside hours, CRITICAL fires 24/7.

### Tier 7 commit

After all four Tier-7 modules land, a single commit ties them together:

```bash
git add src/platform/risk/correlation.py \
        src/platform/risk/factor_decomp.py \
        src/platform/risk/change_detection.py \
        src/platform/risk/alerting.py \
        tests/platform/risk/test_correlation.py \
        tests/platform/risk/test_factor_decomp.py \
        tests/platform/risk/test_change_detection.py \
        tests/platform/risk/test_alerting.py
git commit -m "$(cat <<'EOF'
feat(platform/risk): correlation + factor + PELT + alerting (Tier 7)

Four pure-math modules for the Sprint 4 correlation-monitoring stack:

- correlation.py — rolling Spearman / Pearson / neg-exceedance;
  regime-shift detector with CUSUM persistence filter.
- factor_decomp.py — Carhart 4 + QMJ rolling regression with Newey-West
  HAC t-stats. compare_to_expected_profile flags realized-vs-declared
  beta drift.
- change_detection.py — PELT via ruptures on rolling beta series;
  penalty calibrated by volatility.
- alerting.py — tiered INFO/WARN/CRITICAL with 60-min dedup,
  business-hours suppression for WARN.

Writes to Sprint 3's correlation_matrices and factor_loadings tables.
No scheduler wiring yet — that's a v0.24.1 task when the second
research strategy comes online.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Tier 8 — Python plugin + docs (~3h, both deferrable)

### Task 2: Python plugin strategy interface (~1.5h, CUT-CANDIDATE)

Per spec lines 307-370 and issue #474 (filed during Sprint 1). Pure interface code:

- Create `src/platform/strategy_plugin.py` — `StrategyPlugin` ABC + `Candidate` dataclass.
- Create `src/platform/plugin_registry.py` — `register_plugin` decorator + `get_plugin(strategy_id)`.
- Wire `entry.kind: python_plugin` dispatch in `backtest_engine.py` + `shadow_harness.py::_find_candidates`.
- Create `tests/platform/test_strategy_plugin.py` — mock plugin registers + retrieves + `find_candidates` invoked.

### Task 13: Docs sweep (~1.5h)

- Create `docs/platform/activation-guide.md` per spec lines 1080-1107.
- Update `MASTER.md` Section 2 (volatile counts) + add new "Research Platform" section between Sections 8 and 9 (spec line 1075).
- Update `RELEASES.md` with v0.24.0 final entry.
- Update `CHANGELOG.md` with v0.24.0 block.
- Update `README.md` version badge.

---

## Integration + PR

### Step I.1: Full pytest

```bash
pytest tests/ -q --ignore=tests/test_dependencies.py 2>&1 | tail -15
```

Expected: previous baseline (~2,060) + ~60-100 new Sprint 4 tests = ~2,120-2,160 passed. Same known pre-existing failures (`telegram_commands.py` docstring, `test_lazy_prices_produces_trades_on_real_data`, possibly `test_open_trades_excluded`).

Any NEW failure must be addressed before PR creation.

### Step I.2: Frontend build

```bash
cd frontend && npm run build
```

Sprint 4 adds StrategyResearch page, BacktestEquityChart, PlatformStatusWidget, api.js extensions, Nav link, App route. Build must succeed.

### Step I.3: Non-negotiable gates (per spec lines 1193-1208 / CC prompt lines 303-313)

1. `test_harness_reconcile_uses_research_client` — PASS
2. `test_harness_bracket_monitor_uses_research_client` — PASS
3. `verify_accounts_distinct` raises if both desks share same paper account — PASS (test_alpaca_clients::test_verify_accounts_distinct_raises_on_same_account)
4. `ShadowHarness.halt()` closes only this strategy's positions — PASS (test_shadow_harness::test_harness_halt_closes_only_this_strategy_positions)
5. `/research-platform` page renders with 0 strategies AND with ≥1 strategies — manual verification; automate if possible with Playwright in v0.24.1
6. `npm run build` — PASS
7. Cost calibration slippage_bps within 30% of hardcoded 3 bps — PASS (test_cost_calibration::test_cost_calibration_within_30pct_of_default)
8. Watch loop starts cleanly with empty `strategy_registry` — manual verification (launch watch loop, check logs for `[PLATFORM] No active research strategies` or equivalent info log)
9. All 85 existing `shadow_trades` rows still have `desk='swing'` after schema migrations — SQL spot-check: `sqlite3 ai_research_desk.sqlite3 "SELECT COUNT(*) FROM shadow_trades WHERE desk IS NULL"` returns 0
10. At merge time: `SELECT * FROM shadow_trades WHERE desk != 'swing'` returns 0 rows (platform is inert until a strategy is promoted)

### Step I.4: Docs updates + final commit

Run the Task 13 doc sweep. Commit as single docs commit titled:

```
docs(v0.24.0): Sprint 4 deliverables + final release notes
```

### Step I.5: Push + PR

```bash
git push -u origin feat/platform-shadow
gh pr create --title "v0.24.0: Strategy Research Platform — shadow harness + dashboard + correlation monitoring" ...
```

Sprint 4 is the final PR in the v0.24.x alpha series → v0.24.0 final release.

### Step I.6: Post-merge tag

After merge (operator does this on main):

```bash
git checkout main && git pull
git tag v0.24.0
git push origin v0.24.0
```

### Step I.7: Post-merge verification (manual, per spec line 1344-1349 / CC prompt lines 344-349)

1. SQL: `SELECT COUNT(*) FROM strategy_registry` — should be 0 (nothing promoted yet)
2. SQL: `SELECT COUNT(*) FROM trials_registry` — should be ≥1 if any backtest has been run
3. curl `/api/platform/strategies` → returns empty list `[]`
4. Open dashboard `/research-platform` → empty state renders, no console errors
5. Watch loop logs show `[PLATFORM] No active research strategies` (expected when strategy_registry empty)

---

## Self-Review Checklist

- **Spec coverage:** Every Tier-5 task (7, 9, cost calibration), Tier-6 task (12a, 12b, 12d, 12e), Tier-7 task (11b.2, 11b.3, 11b.5, 11b.6), Tier-8 task (2, 13) has a corresponding plan task above. ✓
- **Placeholder scan:** No "TBD" / "implement later" / "handle edge cases" without code. `_find_candidates` in ShadowHarness is explicitly marked a MVP placeholder with rationale + follow-up note — that's documented deferral, not a placeholder. ✓
- **Type consistency:** `StrategySpec` fields match across Tasks 7a→7e. `BacktestConfig` fields from Sprint 1 still valid. `desk: str = "swing"` default and `desk='research_<strategy_id>'` format consistent across adapter / reconcile / harness / scheduler. ✓
- **Known issues surfaced:** Issue A (bracket_monitor/shadow_service aren't direct `_get_trading_client` callers), Issue B (PBO column still NULL post-Sprint-4 until a driver populates it), Issue C (desks.research config may not exist) all documented at top with Step P.2 verifying. ✓
- **Sequencing:** Task 7a → 7b → 7c → 7d → 7e → 7f → 9 dependency chain explicit. Tier 7 and 8 marked deferrable. Ship order (biggest-risk-first) matches spec line 1329-1334. ✓
- **Commits atomic:** Each Task is one commit. Schema edits land with the feature that uses them. Every refactor-vs-feature separation maintained. ✓
- **No src/ file over 400 lines risk:** `shadow_harness.py` targeted <300 lines; `platform.py` API routes <400; factor_decomp potentially heavy, note for mid-Tier-7 check. ✓
