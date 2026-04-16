# Sprint: Cold-Store IB Integration

**Authority:** SD#41 `docs/research/SD-41-defer-ib-integration.md`
**Effort:** 2-3 hours
**Branch:** `feat/ib-cold-storage`
**Tag on merge:** `v0.18.0`
**Preserves:** All IB integration code (dormant, not deleted)
**Ralph-loop status:** Spec written, awaiting 3x evaluate→research→refine review before CC execution

---

## Goal

Disable active IB trading while preserving the ability to reactivate in 2-4 weeks when any of SD#41's three reactivation triggers occur. Every line of IB integration code remains in the repo. No tables are dropped. The `ib_async` dependency stays in `requirements.txt`. This is a **config flag flip plus observability cleanup**, not a deletion.

At the end of this sprint, the system runs cleanly on Alpaca alone, no IB Gateway connection is attempted, no IB shadow log rows are written, the dashboard clearly communicates IB is dormant, and reactivation is a single config change plus a watch-loop restart.

---

## Pre-Flight Checks (run before any file changes)

1. **Verify current branch and clean state**
   ```bash
   git status
   git branch --show-current
   ```
   Expected: clean working tree, on `main`.

2. **Check current IB position state**
   ```bash
   python -c "from src.storage.database import get_db; db=get_db(); rows=db.execute('SELECT ticker, status, broker FROM shadow_trades WHERE broker=\"ib\" AND status IN (\"open\",\"pending\")').fetchall(); print(f'Open IB positions: {len(rows)}'); [print(r) for r in rows]"
   ```
   Expected: TGT and COP listed as open. If any **pending** IB orders exist, halt sprint and resolve manually first.

3. **Verify Alpaca is the default broker**
   ```bash
   grep -n "broker:" settings.local.yaml settings.yaml 2>/dev/null
   ```
   Expected: either missing (defaults to alpaca) or `broker: alpaca`. If `broker: ib`, flag as blocker.

4. **Confirm tests pass on main**
   ```bash
   pytest -x --no-cov -q tests/trading/test_broker_factory.py tests/shadow_trading/test_executor_stubs.py 2>&1 | tail -5
   ```
   Expected: all pass.

5. **Create feature branch**
   ```bash
   git checkout -b feat/ib-cold-storage
   ```

---

## Task List (max 10 tasks, file-size limits enforced)

### Task 1 — Add `trading.ib_enabled` config flag

**File:** `src/config/defaults.py` (or wherever default config lives — CC should verify)

Add to the default config dict:
```python
"trading": {
    "ib_enabled": False,  # SD#41 — IB dormant through Phase 1. See docs/research/SD-41-defer-ib-integration.md
    # ...existing trading config...
},
```

If `src/config/defaults.py` does not exist, the flag goes at the top of `settings.yaml`:
```yaml
trading:
  ib_enabled: false  # SD#41 — IB dormant through Phase 1
```

**Validation:** `python -c "from src.config import load_config; c = load_config(); print(c.get('trading', {}).get('ib_enabled'))"` → prints `False`.

### Task 2 — Gate broker_factory.py behind ib_enabled flag

**File:** `src/trading/broker_factory.py` (currently ~70 lines)

Modify `get_live_broker()`:
- After reading `broker_name = live_cfg.get("broker", "alpaca")`, check the new flag
- If `broker_name == "ib"` AND `config.get("trading", {}).get("ib_enabled", False) is False`, log a warning and fall back to Alpaca

```python
if broker_name == "ib":
    if not config.get("trading", {}).get("ib_enabled", False):
        logger.warning(
            "[BROKER] IB requested but trading.ib_enabled=false (SD#41 dormant). "
            "Falling back to Alpaca. To reactivate, set trading.ib_enabled=true."
        )
        broker_name = "alpaca"
    else:
        from src.trading.ib_broker import IBBroker
        # ... existing IB init code unchanged ...
```

**Constraint:** Do not delete the IB branch. The flag controls entry into it, that's all.

### Task 3 — Gate executor.py shadow-log writes behind ib_enabled flag

**File:** `src/shadow_trading/executor.py`

Two call sites at lines ~877 and ~2014 (CC should verify line numbers):
```python
ib_shadow_cfg = config.get("live_trading", {}).get("ib", {})
if ib_shadow_cfg.get("shadow_mode") and trade_data.get("status") == "open":
    from src.trading.ib_shadow import IBShadowLogger
    _ib_shadow = IBShadowLogger(config)
    _ib_shadow.log_shadow_trade(...)
```

Add a check before the import:
```python
ib_enabled = config.get("trading", {}).get("ib_enabled", False)
ib_shadow_cfg = config.get("live_trading", {}).get("ib", {})
if ib_enabled and ib_shadow_cfg.get("shadow_mode") and trade_data.get("status") == "open":
    # ... existing logic ...
```

**Why two call sites:** One is for entry, one is for exit/reconcile. Both need the gate.

**Constraint:** Keep the inner logic identical. Just the outer condition changes.

### Task 4 — Gate reconcile.py IB position check behind ib_enabled flag

**File:** `src/shadow_trading/reconcile.py`

At line ~348 there's an IB broker instantiation for position reconciliation:
```python
if ib_trade_count > 0:
    from src.trading.ib_broker import IBBroker
    _ib_broker = IBBroker(...)
```

Wrap the entire block:
```python
ib_enabled = config.get("trading", {}).get("ib_enabled", False)
if ib_enabled and ib_trade_count > 0:
    from src.trading.ib_broker import IBBroker
    # ... existing logic ...
elif not ib_enabled and ib_trade_count > 0:
    runtime.logger.info(
        "[RECONCILE] %d IB positions exist but trading.ib_enabled=false. "
        "Letting brackets resolve naturally. See SD#41.", ib_trade_count
    )
```

**Why this matters:** TGT and COP need to resolve via their existing brackets. We do NOT want to actively close them via IB API, but we also don't want the reconciler trying to connect to IB every cycle.

### Task 5 — Skip IB shadow log sync when ib_enabled=false

**File:** `src/scheduler/watch.py`

Find the IB shadow sync task (if present — CC should grep for `ib_shadow` in scheduler paths). Wrap the task in:
```python
if config.get("trading", {}).get("ib_enabled", False):
    # existing IB shadow sync logic
else:
    # skip silently — logged once at startup, not every cycle
    pass
```

At watch loop startup, log once:
```python
if not config.get("trading", {}).get("ib_enabled", False):
    logger.info("[WATCH] IB integration dormant per SD#41. Alpaca-only mode.")
```

### Task 6 — Dashboard status indicator

**File:** `frontend/src/pages/Settings.jsx` (or create new section if needed)

Add a panel:
```jsx
<div className="arcis-card">
  <h3 className="text-sm uppercase tracking-wide mb-3" style={{ color: 'var(--arcis-text-secondary)' }}>
    Broker Status
  </h3>
  <div className="grid grid-cols-2 gap-3">
    <div>
      <div className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>Primary</div>
      <div className="text-sm font-medium" style={{ color: 'var(--arcis-success)' }}>
        Alpaca · Active
      </div>
    </div>
    <div>
      <div className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>Secondary</div>
      <div className="text-sm font-medium" style={{ color: 'var(--arcis-text-muted)' }}>
        IB · Dormant (SD#41)
      </div>
    </div>
  </div>
  <p className="text-xs mt-3" style={{ color: 'var(--arcis-text-muted)' }}>
    IB integration is preserved but inactive. Reactivation triggers documented in SD#41.
  </p>
</div>
```

**Constraint:** Do not delete the Settings page — just add this section. If Settings.jsx does not exist, skip Task 6 and note it as a follow-up TODO.

### Task 7 — Grafana dashboard panel update

**File:** `observability/arcis-grafana-dashboard.json`

Find any panel with `broker="ib"` filter or IB-specific queries. Either:
- Remove from dashboard if the panel is IB-only
- Change filter to `broker=~"alpaca|ib"` if panel shows both

**Acceptable to skip** if the dashboard only queries Alpaca or aggregate data. CC should verify by grepping for `ib` in the JSON.

### Task 8 — NSSM service dependency cleanup

**File:** `scripts/install_service.ps1`

If the NSSM install command references IB Gateway as a dependency or adds a startup wait for port 4002, remove it. The ArcisWatchLoop service should start immediately without waiting for IB Gateway.

Search for:
```powershell
nssm set ArcisWatchLoop DependOnService
# or
nssm set ArcisWatchLoop AppStartupDelay
```

**Acceptable to skip** if no such dependency exists.

### Task 9 — Add 3 regression tests

**File:** `tests/trading/test_ib_cold_storage.py` (new file)

```python
"""Tests for SD#41 IB cold storage behavior.

Verifies that with trading.ib_enabled=false:
1. broker_factory falls back to Alpaca even when broker=ib is configured
2. executor does not instantiate IBShadowLogger
3. reconcile does not attempt IB connection

Ralph-loop note: these are behavior-preservation tests, not feature tests.
They prevent regression when we reactivate IB later.
"""

import pytest
from unittest.mock import MagicMock, patch


def test_broker_factory_falls_back_to_alpaca_when_ib_disabled():
    from src.trading.broker_factory import get_live_broker
    # Clear singleton cache
    import src.trading.broker_factory as bf
    bf._brokers.clear()

    config = {
        "trading": {"ib_enabled": False},
        "live_trading": {"broker": "ib", "ib": {"host": "127.0.0.1", "port": 4002}},
    }
    with patch("src.trading.alpaca_broker.AlpacaLiveBroker") as mock_alpaca:
        mock_alpaca.return_value = MagicMock()
        broker = get_live_broker(config)
    # If IB were instantiated, we'd import ib_broker — fallback uses Alpaca
    assert "alpaca" in bf._brokers
    assert "ib" not in bf._brokers


def test_broker_factory_uses_ib_when_explicitly_enabled():
    from src.trading.broker_factory import get_live_broker
    import src.trading.broker_factory as bf
    bf._brokers.clear()

    config = {
        "trading": {"ib_enabled": True},
        "live_trading": {"broker": "ib", "ib": {"host": "127.0.0.1", "port": 4002}},
    }
    with patch("src.trading.ib_broker.IBBroker") as mock_ib:
        mock_ib.return_value = MagicMock()
        broker = get_live_broker(config)
    assert "ib" in bf._brokers


def test_default_config_has_ib_disabled():
    """SD#41: new installs default to IB dormant."""
    from src.config import load_config
    config = load_config()
    # After Task 1, this should be False by default
    assert config.get("trading", {}).get("ib_enabled", None) is False, (
        "SD#41 requires trading.ib_enabled=false by default. "
        "If this test fails, check defaults.py or settings.yaml"
    )
```

**Constraint:** These tests must pass. If the third test requires adjusting how `load_config` surfaces the flag, fix Task 1 not the test.

### Task 10 — Documentation updates

**Files:**
- `CHANGELOG.md` — add entry under v0.18.0
- `RELEASES.md` — add release notes
- `MASTER.md` Section 2 (System State) — update broker status from "Alpaca + IB" to "Alpaca (IB dormant per SD#41)"
- `README.md` — if it mentions IB as a primary broker, update to reflect dormant status

**CHANGELOG entry:**
```markdown
## v0.18.0 (2026-04-16)

### Changed
- **SD#41: IB integration cold-stored.** Alpaca is now the sole active broker
  through Phase 1. IB integration preserved (all code intact) but disabled
  via `trading.ib_enabled=false` default. Reactivation triggers documented
  in `docs/research/SD-41-defer-ib-integration.md`.
- Settings page shows "IB · Dormant" status indicator.

### Removed
- NSSM service no longer depends on IB Gateway (if applicable).
- Grafana panels filtered to Alpaca-only metrics where relevant.

### Preserved (not deleted)
- `src/trading/ib_broker.py`, `src/trading/ib_shadow.py`
- `src/api/cloud_routes/ib_shadow.py`, `src/api/routes/ib_status.py`
- `ib_shadow_log` database table
- `ib_async` dependency in `requirements.txt`
```

---

## Backward Compatibility Notes

**No schema changes.** `ib_shadow_log` table remains. `broker` column on `shadow_trades` remains. Existing IB rows are queryable.

**No API changes.** `/api/ib-shadow/*` endpoints still exist and respond correctly — they just return empty or dormant data when `ib_enabled=false`.

**Reactivation path** (documented in SD#41):
1. Update `settings.local.yaml`: `trading.ib_enabled: true`
2. Verify IB Gateway is running
3. `nssm restart ArcisWatchLoop`
4. Watch loop picks up flag within 60s, IB broker instantiation resumes

**No code needs to change** to reactivate. That's the whole point of cold storage vs deletion.

---

## Commit Messages (CC should use these formats)

```
feat(config): add trading.ib_enabled flag defaulting to false (SD#41)
feat(broker): gate IBBroker instantiation behind ib_enabled flag
feat(executor): skip IB shadow logging when ib_enabled=false
feat(reconcile): defer IB connection when ib_enabled=false, let brackets resolve
feat(watch): log dormant IB status once at startup
feat(frontend): add dormant IB indicator to Settings page
chore(infra): remove IB Gateway dependency from NSSM service
test: add regression tests for IB cold storage behavior
docs: update CHANGELOG/RELEASES/MASTER for v0.18.0 SD#41
```

Squash-merge to `main` or keep individual commits — CC's choice based on task atomicity. Tag after merge.

---

## File-Size Discipline

- `src/trading/broker_factory.py` is currently ~70 lines. After changes, should be ~85 lines. **Hard cap: 120 lines.**
- `src/shadow_trading/executor.py` is ~2000+ lines. This sprint adds ~6 lines of guards. **Do NOT refactor the rest of the file.** File-size refactor is a separate sprint.
- `tests/trading/test_ib_cold_storage.py` new file, should be ~80 lines.

---

## docs/sprint-checklist.md (final section)

Before the PR is opened, confirm:

- [ ] All 10 tasks completed (or explicitly marked N/A with reason)
- [ ] `pytest tests/trading/test_ib_cold_storage.py -v` passes (all 3 tests)
- [ ] `pytest tests/ --no-cov -q` passes fully (no regressions elsewhere)
- [ ] `scripts/verify_docs.py` passes
- [ ] `python -m src.cli.commands audit` shows no new stale warnings
- [ ] Grep confirms no IB code was **deleted** (only gated):
  ```bash
  git diff main --stat | grep -E "ib_(broker|shadow)" 
  # Should show additions but NOT file deletions
  ```
- [ ] MASTER.md Section 2 updated
- [ ] CHANGELOG.md has v0.18.0 entry
- [ ] RELEASES.md has v0.18.0 entry
- [ ] README.md badges updated if version-referenced
- [ ] Tag `v0.18.0` created after merge to main
- [ ] Architecture diagram (`halcyon-architecture.html`) updated if IB is shown as active

---

## Out-of-Scope (explicitly deferred)

These are NOT part of this sprint — resist scope creep:

1. **Deleting IB code.** Preservation is the whole point.
2. **Refactoring executor.py size.** Different sprint.
3. **Removing the Broker Comparison page frontend file.** Already done in Trade History sprint.
4. **Closing TGT/COP positions manually.** Let brackets resolve naturally.
5. **Changing Alpaca-side logic.** Alpaca path is untouched.
6. **Updating IBShadow.jsx.** The component file stays; it's just not routed.
7. **Removing `ib_async` from `requirements.txt`.** Stays for reactivation.

---

## Ralph-Loop Review Questions (before CC executes)

1. **Is every IB import guarded by `ib_enabled` check?** Yes — verified across broker_factory, executor (×2), reconcile, watch.

2. **Can the system still query historical IB data?** Yes — `ib_shadow_log` table remains queryable via `/api/ib-shadow/*` endpoints. Those endpoints just return empty data going forward.

3. **What happens to TGT/COP?** Their brackets are Alpaca-side (check — need to verify), so they resolve normally. If brackets are IB-side, the reconciler will flag them as IB-pending and log a warning but not actively close them.

4. **Is reactivation truly one-flag?** Yes — set `trading.ib_enabled: true`, restart watch loop. No code changes needed.

5. **Does the sprint preserve the IB account opening date?** The sprint doesn't touch the account itself — that's Ryan's manual task (monthly login, minimum balance).

6. **Are the regression tests the right tests?** They verify the fallback behavior. Alternative: also test executor's shadow log skip, but that requires heavier mocking. Keep it to the 3 focused tests.

---

## Post-Merge Verification (after pull on local)

```bash
# On Windows local:
cd C:\arcis\halcyon-lab
git pull origin main
git checkout v0.18.0
nssm restart ArcisWatchLoop
# Wait 60s
type C:\arcis\logs\halcyon.log | findstr /C:"dormant"
# Should see: [WATCH] IB integration dormant per SD#41. Alpaca-only mode.
```

If the log line appears and no IB-related errors follow, cold storage is working correctly.

---

## Success Criteria

1. Watch loop runs 24 hours with zero IB-related errors or connection attempts
2. No new `ib_shadow_log` rows written after deployment
3. Existing Alpaca trading continues without change
4. TGT and COP resolve naturally via their existing brackets
5. Dashboard clearly shows "IB · Dormant"
6. All tests pass
7. Reactivation is a single config flag change (verifiable via inspection)

---

*Sprint ready for CC execution. Estimated CC time: 2-3 hours including self-verification.*
