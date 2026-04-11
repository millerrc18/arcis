# SPRINT IB-7: Integration Validation — End-to-End IB Verification

> **Branch:** `test/ib-integration-validation`
> **Priority:** HIGH — nothing goes live until this passes
> **Depends on:** IB-1 through IB-6 ALL merged
> **Estimated CC time:** 4-6 hours
>
> **Pre-flight:**
> ```bash
> git checkout main && git pull origin main
> git checkout -b test/ib-integration-validation
> python -m pytest tests/ -x -q --ignore=tests/test_ingestion.py
> ```
>
> **Purpose:** Verify that all 6 IB sprints work together. Unit tests prove
> each piece works in isolation. This sprint proves they work as a system.

---

## What This Sprint Tests

| Layer | What Could Break | How We Verify |
|-------|-----------------|---------------|
| **Data flow** | Child order IDs from IB-2 don't reach bracket monitor from IB-1 | End-to-end trade lifecycle test |
| **Multi-broker** | Governor counts IB positions but reconciler doesn't, or vice versa | Cross-component position counting |
| **Config progression** | shadow_mode → paper_routing → live doesn't transition cleanly | Config-driven behavior matrix |
| **Fallback cascade** | IB down → Alpaca fallback → IB recovers → state inconsistency | Failure/recovery simulation |
| **Schema integrity** | New columns (broker, ib_child_order_ids, broker_order_id) not populated in all code paths | Data completeness check |
| **Alpaca regression** | Paper trading broken by IB changes | Full paper trade lifecycle unchanged |
| **Dashboard accuracy** | Pages show wrong data when trades span both brokers | API response validation |

---

## Task 1: End-to-end trade lifecycle test (IB path)

**File:** Create `tests/test_ib_integration.py` (~250 lines)

Test the complete lifecycle of an IB paper trade through all components:

```python
class TestIBTradeLifecycle:
    """End-to-end: entry → monitor → bracket fill → exit → close → P&L."""

    def test_full_ib_paper_trade_lifecycle(self, tmp_db):
        """
        1. open_shadow_trade() routes to IB (score >= threshold)
        2. shadow_trades row has broker="ib", ib_child_order_ids populated
        3. check_and_manage_open_trades() detects IB bracket fill via broker factory
        4. close_shadow_trade() computes P&L correctly
        5. Reconciler sees the IB position
        6. Risk governor counts the IB position
        7. Postmortem generated
        """

    def test_full_alpaca_paper_trade_lifecycle_unchanged(self, tmp_db):
        """
        Same lifecycle as above but for Alpaca paper trade (score < threshold).
        Verifies zero regression from IB changes.
        1. open_shadow_trade() routes to Alpaca
        2. shadow_trades row has broker="alpaca"
        3. check_and_manage detects Alpaca bracket fill via alpaca_adapter
        4. Everything else identical to pre-IB behavior
        """
```

**Commit:** `test(ib): end-to-end trade lifecycle — IB path + Alpaca regression`

---

## Task 2: Cross-component position counting

**File:** Add to `tests/test_ib_integration.py`

```python
class TestCrossBrokerPositionCounting:
    """Verify governor, reconciler, and executor all agree on position counts."""

    def test_governor_counts_both_brokers(self, tmp_db):
        """3 IB + 4 Alpaca = 7 positions against max_open_positions."""
        # Insert mixed-broker trades into tmp_db
        # Verify governor.check_max_positions() counts 7

    def test_reconciler_checks_correct_broker_per_trade(self, tmp_db):
        """IB trades reconcile against IB positions, Alpaca against Alpaca."""
        # Insert IB trade + Alpaca trade
        # Mock both brokers with different positions
        # Verify IB trade checks IB, Alpaca trade checks Alpaca

    def test_executor_position_check_spans_brokers(self, tmp_db):
        """Duplicate detection checks both brokers before entry."""
        # AAPL open on IB → new AAPL signal → should be blocked
        # MSFT open on Alpaca → new MSFT signal → should be blocked

    def test_buying_power_checked_on_correct_broker(self, tmp_db):
        """IB trade checks IB buying power, Alpaca checks Alpaca."""
```

**Commit:** `test(ib): cross-broker position counting — governor, reconciler, executor agree`

---

## Task 3: Config progression matrix

**File:** Add to `tests/test_ib_integration.py`

```python
class TestConfigProgression:
    """Verify behavior changes correctly as config progresses through IB phases."""

    def test_no_ib_config_is_pure_alpaca(self):
        """Default config (no IB section) → all trades to Alpaca, no IB imports."""
        # Verify zero IB code paths touched

    def test_shadow_mode_logs_without_executing(self):
        """ib.shadow_mode=true → shadow log populated, no IB orders placed."""
        # Verify ib_shadow_log has rows, placeOrder never called

    def test_paper_routing_splits_by_score(self):
        """ib.paper_routing=true → high scores to IB, low to Alpaca."""
        # Score 85 → broker="ib", Score 72 → broker="alpaca"

    def test_shadow_and_routing_mutually_exclusive(self):
        """Can't have both shadow_mode and paper_routing enabled."""
        # If both true, paper_routing takes precedence (shadow is graduated)

    def test_live_ib_uses_broker_factory(self):
        """live_trading.broker=ib → live trades route through IBBroker."""
```

**Commit:** `test(ib): config progression matrix — shadow → routing → live`

---

## Task 4: Failure and recovery simulation

**File:** Add to `tests/test_ib_integration.py`

```python
class TestIBFailureRecovery:
    """Verify clean state after IB failures and recovery."""

    def test_ib_down_mid_session_falls_back(self):
        """
        1. First trade → IB succeeds (broker="ib")
        2. IB disconnects
        3. Second trade → falls back to Alpaca (broker="alpaca")
        4. Both trades tracked correctly
        """

    def test_ib_recovery_resumes_routing(self):
        """
        1. IB down → trades go to Alpaca
        2. IB reconnects
        3. Next trade goes to IB again
        """

    def test_mixed_broker_trades_in_same_session(self):
        """
        After fallback and recovery, session has IB + Alpaca trades.
        Verify: reconciler handles both, governor counts both, dashboard shows both.
        """

    def test_ib_failure_during_exit_retries_on_correct_broker(self):
        """
        IB trade needs exit, IB is down.
        _retry_exit should attempt IB (not Alpaca) and handle the failure.
        """
```

**Commit:** `test(ib): failure/recovery simulation — fallback, resume, mixed state`

---

## Task 5: Schema and data completeness validation script

**File:** Create `scripts/validate_ib_integration.py` (~150 lines)

A runtime validation script Ryan can run against his live database:

```python
"""Validate IB integration data completeness across all tables.

Run: python scripts/validate_ib_integration.py

Checks:
1. All shadow_trades have broker column populated (not NULL)
2. All IB bracket trades have ib_child_order_ids populated
3. All ib_shadow_log entries have required fields
4. No orphaned IB orders (shadow_trades references orders that don't exist)
5. Risk governor equity matches IB account equity (when IB connected)
6. Position counts match across governor, reconciler, and dashboard API
7. No Alpaca-only function calls in IB trade code paths
"""
```

This script queries the database and prints a validation report:

```
=== IB INTEGRATION VALIDATION ===
✓ shadow_trades.broker: 100% populated (18 alpaca, 0 ib)
✓ ib_shadow_log: 0 entries (shadow mode not yet active)
✓ Schema: broker column exists, ib_child_order_ids exists, broker_order_id exists
⚠ No IB trades yet — routing validation deferred
✓ Alpaca paper trades: no regression detected
```

**Commit:** `feat(scripts): IB integration validation — data completeness checker`

---

## Task 6: API response validation for multi-broker

**File:** Add to `tests/test_ib_integration.py`

```python
class TestMultiBrokerAPIResponses:
    """Verify dashboard API routes handle mixed-broker data correctly."""

    def test_shadow_open_includes_broker_field(self):
        """/api/shadow/open response includes broker field per trade."""

    def test_shadow_metrics_aggregates_across_brokers(self):
        """/api/shadow/metrics P&L includes both IB and Alpaca trades."""

    def test_cto_report_counts_both_brokers(self):
        """/api/analytics/cto-report trade counts span both brokers."""

    def test_ib_shadow_summary_accurate(self):
        """/api/ib-shadow/summary matches actual ib_shadow_log data."""
```

**Commit:** `test(ib): API response validation — multi-broker data correctness`

---

## Task 7: Smoke test checklist (human-executable)

**File:** Create `docs/operations/ib-smoke-test.md`

A step-by-step manual checklist for Ryan to run on his local machine after all sprints are merged:

```markdown
# IB Integration Smoke Test

## Prerequisites
- [ ] All 6 IB sprints merged to main
- [ ] `git pull origin main` on local machine
- [ ] IB Gateway running on port 4002 (paper)
- [ ] `python -m src.main validate-schema --fix`

## Phase 1: Shadow Mode (5 min)
- [ ] Set `ib.shadow_mode: true` in settings.local.yaml
- [ ] Start watch loop: `python -m src.main watch --email-mode silent`
- [ ] Wait for one scan cycle to complete
- [ ] Check: `python scripts/validate_ib_integration.py`
- [ ] Check: ib_shadow_log has entries? (Yes → shadow mode works)
- [ ] Check: Alpaca paper trades still executing? (Yes → no regression)
- [ ] Stop watch loop

## Phase 2: Dual Routing (10 min)
- [ ] Set `ib.shadow_mode: false`, `ib.paper_routing: true`, threshold 80
- [ ] Start watch loop
- [ ] Wait for trades to generate
- [ ] Check: high-score trades have broker="ib"?
- [ ] Check: low-score trades have broker="alpaca"?
- [ ] Check: IB bracket trades have ib_child_order_ids?
- [ ] Check: dashboard shows both broker types?
- [ ] Stop watch loop

## Phase 3: IB Bracket Monitoring (15 min)
- [ ] With IB paper trades open, wait for bracket fills
- [ ] Check: exit detected via IB (not Alpaca)?
- [ ] Check: P&L calculated correctly?
- [ ] Check: reconciler handles IB positions?

## Phase 4: Failure Recovery (5 min)
- [ ] Stop IB Gateway while trades are open
- [ ] Check: Telegram alert received?
- [ ] Check: next trade falls back to Alpaca?
- [ ] Restart IB Gateway
- [ ] Check: reconnection alert received?
- [ ] Check: next high-score trade routes back to IB?

## Phase 5: Dashboard (5 min)
- [ ] Open halcyonlab.app
- [ ] Shadow Ledger: shows broker column?
- [ ] IB Shadow page: shows shadow data?
- [ ] Health page: shows IB status?
- [ ] CTO Report: trade counts correct?

## Result
- [ ] All checks passed → IB integration validated
- [ ] Failures documented below:
  -
```

**Commit:** `docs: IB smoke test checklist — manual validation after all sprints merge`

---

## Task 8: Documentation

- `CHANGELOG.md` — integration validation entry
- `MASTER.md` — update IB status to "validated" or note remaining items

**Commit:** `docs: IB integration validation complete`

**Push:**
```bash
git push origin test/ib-integration-validation
```

---

## Verification Checklist

```bash
# All tests pass (including new integration tests)
python -m pytest tests/ -x -q --ignore=tests/test_ingestion.py

# Integration tests specifically
python -m pytest tests/test_ib_integration.py -v

# Validation script runs clean
python scripts/validate_ib_integration.py

# Frontend builds
cd frontend && npm run build && cd ..

# Count total IB test coverage
python -m pytest tests/test_ib_broker.py tests/test_ib_shadow.py tests/test_ib_integration.py -v --tb=short | tail -5
```

---

## Ralph Loop Findings

**Pass 1:** The lifecycle test (Task 1) needs to mock BOTH Alpaca AND IB in the same test, with the router selecting between them based on score. Most existing tests mock only one broker. The fixture setup is more complex than typical unit tests.

**Pass 2:** The config progression test (Task 3) caught a gap: what happens if BOTH `shadow_mode` and `paper_routing` are true? The spec didn't address this. Added explicit precedence rule: `paper_routing` wins (shadow mode is the precursor stage, routing is the graduation).

**Pass 3:** The smoke test checklist (Task 7) is the most important deliverable — it's what Ryan actually runs. Automated tests prove the code works in isolation. The smoke test proves it works on Ryan's machine with real IB Gateway. If the automated tests pass but the smoke test fails, we have an environment issue to fix before going live.
