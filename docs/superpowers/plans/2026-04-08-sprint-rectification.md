# Sprint Rectification — 7 Unfinished Sprints

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement all remaining unfinished and partially-implemented sprint work across 7 phases: risk scaling tiers, XML prompt expansion, outcome-conditioned training integration, system monitoring, strategy dashboard, React Flow shared components + dashboard polish, and iOS Capacitor.

**Architecture:** Each phase ships on its own branch, is independently testable, and merges to main before the next phase begins. Phases are ordered by priority and dependency: risk hardening first (production safety), then LLM/training pipeline (data quality), then infrastructure (monitoring), then frontend (dashboard + iOS).

**Tech Stack:** Python 3.13, SQLite, FastAPI, React 19, Tailwind 4, TanStack Query, Recharts, @xyflow/react 12, Capacitor 6

**Test baseline:** 1,543 tests. Every phase must maintain or increase this count.

---

## Phase Map

| Phase | Branch | Scope | Depends On | Est. Hours |
|-------|--------|-------|------------|------------|
| 1 | `feat/risk-scaling-tiers` | Risk governor tier-based scaling | — | 2-3 |
| 2 | `feat/xml-expansion` | LLM prompt 7→11 sections | — | 3-4 |
| 3 | `feat/outcome-conditioned-training` | Wire outcome prompts into data collector | Phase 2 | 2-3 |
| 4 | `feat/system-monitoring` | New monitoring module + dashboard page | — | 5-7 |
| 5 | `feat/strategy-dashboard` | Strategy comparison page (new) + backend API | — | 4-6 |
| 6 | `feat/dashboard-polish` | React Flow shared components + mega dashboard fixes | — | 3-4 |
| 7 | `feat/ios-capacitor` | Capacitor wrapper for iOS sideloading | — (macOS blocked) | 4-6 |

---

## Phase 1: Risk Scaling Tiers

**Goal:** Replace the static `planned_risk_pct_max` with account-size-based tiers so risk per trade decreases as equity grows.

**Branch:** `feat/risk-scaling-tiers`

**Spec:** `docs/decisions/risk-scaling-tiers-spec.md`

### File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/risk/governor.py` | Modify | Add `get_current_equity()`, `get_effective_risk_pct()`, `check_tier_transition()` |
| `src/packets/template.py` | Modify line 32 | Use tiered risk instead of static config |
| `src/shadow_trading/executor.py` | Modify line 294 | Use tiered base risk for Thorp adjustment |
| `src/startup.py` | Modify | Add tier config validation |
| `src/api/routes/system.py` | Modify | Expose tier info in status API |
| `config/settings.example.yaml` | Modify | Add `risk_scaling` config block |
| `tests/test_risk_governor.py` | Modify | Add 8 tier tests |

---

### Task 1: Add `get_current_equity()` and `get_effective_risk_pct()`

**Files:**
- Modify: `src/risk/governor.py:186` (after `compute_current_drawdown`)
- Modify: `tests/test_risk_governor.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_risk_governor.py`:

```python
class TestRiskScalingTiers:
    """Risk scaling tiers — Strategy Decision #26."""

    def _mock_config(self, enabled=True, tiers=None):
        return {
            "risk": {
                "starting_capital": 100000,
                "planned_risk_pct_max": 0.02,
                "risk_scaling": {
                    "enabled": enabled,
                    "tiers": tiers or [
                        {"equity_below": 100000, "risk_pct_max": 0.02},
                        {"equity_below": 500000, "risk_pct_max": 0.015},
                        {"equity_below": 1000000, "risk_pct_max": 0.0125},
                        {"equity_below": 999999999, "risk_pct_max": 0.01},
                    ],
                },
            },
            "risk_governor": {},
        }

    def test_scaling_disabled_returns_static(self, tmp_path):
        from src.risk.governor import get_effective_risk_pct
        db = str(tmp_path / "test.db")
        _init_db(db)
        cfg = self._mock_config(enabled=False)
        pct, label = get_effective_risk_pct(cfg, db)
        assert pct == 0.02
        assert label == "static"

    def test_equity_50k_returns_2pct(self, tmp_path):
        from src.risk.governor import get_effective_risk_pct, get_current_equity
        db = str(tmp_path / "test.db")
        _init_db(db)
        # No closed trades → equity = starting_capital = 100K
        # But starting_capital is 100K and no P&L means equity = 100K
        # That falls in the <100K tier? No — 100K is NOT below 100K.
        # It falls in the <500K tier → 1.5%
        cfg = self._mock_config()
        pct, label = get_effective_risk_pct(cfg, db)
        assert pct == 0.015

    def test_equity_below_starting_returns_2pct(self, tmp_path):
        from src.risk.governor import get_effective_risk_pct
        db = str(tmp_path / "test.db")
        _init_db(db)
        # Simulate -$20K in closed trade P&L → equity = $80K
        _add_closed_trade(db, pnl=-20000)
        cfg = self._mock_config()
        pct, label = get_effective_risk_pct(cfg, db)
        assert pct == 0.02  # $80K < $100K → 2%

    def test_equity_200k_returns_1_5pct(self, tmp_path):
        from src.risk.governor import get_effective_risk_pct
        db = str(tmp_path / "test.db")
        _init_db(db)
        _add_closed_trade(db, pnl=100000)  # equity = $200K
        cfg = self._mock_config()
        pct, label = get_effective_risk_pct(cfg, db)
        assert pct == 0.015  # $200K < $500K → 1.5%

    def test_equity_800k_returns_1_25pct(self, tmp_path):
        from src.risk.governor import get_effective_risk_pct
        db = str(tmp_path / "test.db")
        _init_db(db)
        _add_closed_trade(db, pnl=700000)  # equity = $800K
        cfg = self._mock_config()
        pct, label = get_effective_risk_pct(cfg, db)
        assert pct == 0.0125  # $800K < $1M → 1.25%

    def test_equity_2m_returns_1pct(self, tmp_path):
        from src.risk.governor import get_effective_risk_pct
        db = str(tmp_path / "test.db")
        _init_db(db)
        _add_closed_trade(db, pnl=1900000)  # equity = $2M
        cfg = self._mock_config()
        pct, label = get_effective_risk_pct(cfg, db)
        assert pct == 0.01  # $2M < $999M → 1.0%

    def test_empty_tiers_returns_static(self, tmp_path):
        from src.risk.governor import get_effective_risk_pct
        db = str(tmp_path / "test.db")
        _init_db(db)
        cfg = self._mock_config(tiers=[])
        pct, label = get_effective_risk_pct(cfg, db)
        assert pct == 0.02
        assert label == "static"

    def test_get_current_equity_no_trades(self, tmp_path):
        from src.risk.governor import get_current_equity
        db = str(tmp_path / "test.db")
        _init_db(db)
        cfg = {"risk": {"starting_capital": 100000}}
        equity = get_current_equity(cfg, db)
        assert equity == 100000

    def test_get_current_equity_with_pnl(self, tmp_path):
        from src.risk.governor import get_current_equity
        db = str(tmp_path / "test.db")
        _init_db(db)
        _add_closed_trade(db, pnl=5000)
        _add_closed_trade(db, pnl=-2000)
        cfg = {"risk": {"starting_capital": 100000}}
        equity = get_current_equity(cfg, db)
        assert equity == 103000


def _init_db(db_path):
    """Create minimal shadow_trades table for tier tests."""
    import sqlite3
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS shadow_trades (
                trade_id TEXT PRIMARY KEY,
                status TEXT,
                pnl_dollars REAL,
                actual_exit_time TEXT
            )
        """)


def _add_closed_trade(db_path, pnl):
    """Insert a closed trade with given P&L for equity computation."""
    import sqlite3
    import uuid
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO shadow_trades (trade_id, status, pnl_dollars, actual_exit_time) "
            "VALUES (?, 'closed', ?, '2026-04-01T10:00:00')",
            (str(uuid.uuid4()), pnl),
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_risk_governor.py::TestRiskScalingTiers -v`
Expected: FAIL — `ImportError: cannot import name 'get_effective_risk_pct'`

- [ ] **Step 3: Write the implementation**

In `src/risk/governor.py`, add after `compute_current_drawdown` (after line 220):

```python
def get_current_equity(config: dict | None = None,
                       db_path: str = DB_PATH) -> float:
    """Compute current equity from starting capital + realized P&L.

    Uses only closed-trade P&L (not unrealized) to prevent equity
    oscillation during market hours from affecting position sizing.
    """
    if config is None:
        config = load_config()
    starting_capital = config.get("risk", {}).get("starting_capital", 100000)
    try:
        import sqlite3
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(pnl_dollars), 0) "
                "FROM shadow_trades WHERE status = 'closed'"
            ).fetchone()
            total_pnl = float(row[0]) if row else 0
        return starting_capital + total_pnl
    except Exception as e:
        logger.warning("[RISK] Equity computation failed: %s — using starting_capital", e)
        return starting_capital


def get_effective_risk_pct(config: dict | None = None,
                           db_path: str = DB_PATH) -> tuple[float, str]:
    """Get the risk percentage for the current equity tier.

    Returns (effective_risk_pct, tier_label).
    If scaling is disabled or tiers are empty, returns (planned_risk_pct_max, "static").
    """
    if config is None:
        config = load_config()
    risk_cfg = config.get("risk", {})
    base = risk_cfg.get("planned_risk_pct_max", 0.02)

    scaling = risk_cfg.get("risk_scaling", {})
    if not scaling.get("enabled", False):
        return base, "static"

    tiers = scaling.get("tiers", [])
    if not tiers:
        return base, "static"

    equity = get_current_equity(config, db_path)

    for tier in sorted(tiers, key=lambda t: t["equity_below"]):
        if equity < tier["equity_below"]:
            label = f"<${tier['equity_below']:,.0f} ({tier['risk_pct_max']:.1%})"
            return tier["risk_pct_max"], label

    last = tiers[-1]
    label = f">=${last['equity_below']:,.0f} ({last['risk_pct_max']:.1%})"
    return last["risk_pct_max"], label
```

Add `from src.config import load_config` at the top of `governor.py` if not already present.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_risk_governor.py::TestRiskScalingTiers -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add src/risk/governor.py tests/test_risk_governor.py
git commit -m "feat: add get_current_equity and get_effective_risk_pct for tier scaling (#SD26)"
```

---

### Task 2: Wire tiered risk into packet template and executor

**Files:**
- Modify: `src/packets/template.py:32`
- Modify: `src/shadow_trading/executor.py:294`

- [ ] **Step 1: Update template.py**

In `src/packets/template.py`, change line 32:

```python
# Before:
    risk_pct = risk_cfg.get("planned_risk_pct_max", 0.01)
# After:
    from src.risk.governor import get_effective_risk_pct
    risk_pct, _tier = get_effective_risk_pct(config)
```

- [ ] **Step 2: Update executor.py Thorp base risk**

In `src/shadow_trading/executor.py`, find the line where `base_risk` is read from config (around line 294):

```python
# Before:
    base_risk = config.get("risk", {}).get("planned_risk_pct_max", 0.02)
# After:
    from src.risk.governor import get_effective_risk_pct
    base_risk, _tier = get_effective_risk_pct(config, db_path)
```

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest tests/ -q --tb=line 2>&1 | tail -5`
Expected: All pass, count >= 1543

- [ ] **Step 4: Commit**

```bash
git add src/packets/template.py src/shadow_trading/executor.py
git commit -m "feat: wire tiered risk into packet sizing and Thorp adjustment (#SD26)"
```

---

### Task 3: Add tier transition notification

**Files:**
- Modify: `src/risk/governor.py`
- Modify: `src/scheduler/watch.py` (EOD block)

- [ ] **Step 1: Add check_tier_transition to governor.py**

```python
def check_tier_transition(config: dict, db_path: str = DB_PATH) -> dict | None:
    """Detect if equity has crossed a tier boundary since last EOD check.

    Stores last known tier in activity_log. Returns transition dict if changed.
    """
    import sqlite3
    current_pct, current_label = get_effective_risk_pct(config, db_path)
    equity = get_current_equity(config, db_path)

    try:
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT details_json FROM activity_log "
                "WHERE event_type = 'tier_check' ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()

        prev_label = None
        if row and row[0]:
            import json
            prev = json.loads(row[0])
            prev_label = prev.get("tier_label")

        # Store current tier
        with sqlite3.connect(db_path) as conn:
            import json
            conn.execute(
                "INSERT INTO activity_log (event_type, details_json, timestamp) "
                "VALUES ('tier_check', ?, datetime('now'))",
                (json.dumps({"tier_label": current_label, "equity": equity, "risk_pct": current_pct}),),
            )

        if prev_label and prev_label != current_label:
            return {
                "equity": equity,
                "prev_tier": prev_label,
                "new_tier": current_label,
                "new_risk_pct": current_pct,
            }
    except Exception as e:
        logger.debug("[RISK] Tier transition check failed: %s", e)

    return None
```

- [ ] **Step 2: Wire into EOD block in watch.py**

In `src/scheduler/watch.py`, inside the EOD recap section, add:

```python
        # Check for risk tier transition (Strategy Decision #26)
        try:
            from src.risk.governor import check_tier_transition
            transition = check_tier_transition(self.config, db_path)
            if transition:
                msg = (
                    f"📊 RISK TIER CHANGE\n"
                    f"Equity: ${transition['equity']:,.2f}\n"
                    f"Previous: {transition['prev_tier']}\n"
                    f"New: {transition['new_tier']}\n"
                    f"Max risk/trade: {transition['new_risk_pct']:.1%}"
                )
                logger.info("[RISK] %s", msg)
                from src.notifications.telegram import send_telegram
                send_telegram(msg)
        except Exception as e:
            logger.debug("[RISK] Tier transition check skipped: %s", e)
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/ -q --tb=line 2>&1 | tail -5`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add src/risk/governor.py src/scheduler/watch.py
git commit -m "feat: add risk tier transition detection with Telegram alert (#SD26)"
```

---

### Task 4: Config example and startup validation

**Files:**
- Modify: `config/settings.example.yaml`
- Modify: `src/startup.py`

- [ ] **Step 1: Add risk_scaling to settings.example.yaml**

Under the `risk:` section, add:

```yaml
  # Account-size risk scaling (Strategy Decision #26)
  risk_scaling:
    enabled: true
    tiers:
      - equity_below: 100000
        risk_pct_max: 0.02
      - equity_below: 500000
        risk_pct_max: 0.015
      - equity_below: 1000000
        risk_pct_max: 0.0125
      - equity_below: 999999999
        risk_pct_max: 0.01
    notify_on_transition: true
```

- [ ] **Step 2: Add startup validation**

In `src/startup.py`, in the config validation section, add:

```python
    # Validate risk scaling tiers
    scaling = config.get("risk", {}).get("risk_scaling", {})
    if scaling.get("enabled"):
        tiers = scaling.get("tiers", [])
        if not tiers:
            results.append(CheckResult("warn", "risk_scaling enabled but tiers is empty", "Add tiers or disable scaling"))
        for i, tier in enumerate(tiers):
            if "equity_below" not in tier or "risk_pct_max" not in tier:
                results.append(CheckResult("fail", f"Tier {i} missing equity_below or risk_pct_max", "Fix risk_scaling.tiers config"))
            elif tier["risk_pct_max"] > 0.05:
                results.append(CheckResult("warn", f"Tier {i} risk_pct_max={tier['risk_pct_max']:.1%} exceeds 5%", "Verify this is intentional"))
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/ -q --tb=line 2>&1 | tail -5`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add config/settings.example.yaml src/startup.py
git commit -m "feat: add risk scaling tier config and startup validation (#SD26)"
```

---

## Phase 2: XML Prompt Expansion (7→11 Sections)

**Goal:** Restructure `_build_feature_prompt()` from 7+3 sub-sections into clean 11 numbered sections, adding cross-asset correlation data and enhancing options/event/earnings sections.

**Branch:** `feat/xml-expansion`

**Spec:** `docs/sprints/sprint-xml-expansion.md`

**Execution note:** The existing sprint doc at `docs/sprints/sprint-xml-expansion.md` contains complete, accurate code for all tasks. Execute it as-written with these updates:

### File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/llm/packet_writer.py` | Modify lines 84-220 | Restructure `_build_feature_prompt()` to 11 sections |
| `src/llm/prompts.py` | Modify | Update system prompt section references |
| `tests/test_xml_format.py` | Modify | Add tests for new sections |

---

### Task 5: Restructure `_build_feature_prompt()` to 11 sections

**Files:**
- Modify: `src/llm/packet_writer.py:84-220`
- Modify: `tests/test_xml_format.py`

- [ ] **Step 1: Write tests for the new section structure**

Append to `tests/test_xml_format.py`:

```python
class TestElevenSections:
    """Verify the 11-section prompt structure."""

    def test_all_section_headers_present(self):
        from src.llm.packet_writer import _build_feature_prompt
        features = _minimal_features()
        prompt = _build_feature_prompt(features, "AAPL")
        expected_sections = [
            "=== TECHNICAL DATA ===",
            "=== MARKET REGIME ===",
            "=== SECTOR RELATIVE ===",
            "=== FUNDAMENTAL SNAPSHOT ===",
            "=== INSIDER ACTIVITY ===",
            "=== RECENT NEWS ===",
            "=== MACRO CONTEXT ===",
            "=== OPTIONS FLOW ===",
            "=== EVENT CALENDAR ===",
            "=== EARNINGS SIGNALS ===",
            "=== CROSS-ASSET CORRELATION ===",
        ]
        for header in expected_sections:
            assert header in prompt, f"Missing section: {header}"

    def test_no_subsection_numbering(self):
        """Old 7.5/7.6/7.7 sub-sections should be gone."""
        from src.llm.packet_writer import _build_feature_prompt
        features = _minimal_features()
        prompt = _build_feature_prompt(features, "AAPL")
        assert "7.5" not in prompt
        assert "7.6" not in prompt
        assert "7.7" not in prompt

    def test_missing_data_graceful(self):
        """Sections with no data should show 'n/a', not crash."""
        from src.llm.packet_writer import _build_feature_prompt
        prompt = _build_feature_prompt({}, "TEST")
        assert "=== CROSS-ASSET CORRELATION ===" in prompt
        assert "n/a" in prompt


def _minimal_features():
    return {
        "price": 150.0, "atr": 3.5, "trend": "up",
        "spy_trend": "up", "vix": 18.0,
        "sector": "Technology", "sector_etf": "XLK",
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_xml_format.py::TestElevenSections -v`
Expected: FAIL — `CROSS-ASSET CORRELATION` not in prompt

- [ ] **Step 3: Implement the 11-section restructure**

Follow the code in `docs/sprints/sprint-xml-expansion.md` Task 1 exactly. The sprint doc contains the complete `_build_feature_prompt()` rewrite with all 11 sections, `_interpret_skew()` helper, and cross-asset correlation section.

Key changes:
- Rename "Options Context" (7.5) → "OPTIONS FLOW" (Section 8) with skew interpretation
- Rename "Event Context" (7.6) → "EVENT CALENDAR" (Section 9) with compound risk flag
- Rename "Earnings Context" (7.7) → "EARNINGS SIGNALS" (Section 10) with revision momentum
- Add new "CROSS-ASSET CORRELATION" (Section 11) with bond yields, dollar, oil, VIX term structure
- Add `_interpret_skew()` and `_compound_event_risk()` helpers

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_xml_format.py -v`
Expected: All pass

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -q --tb=line 2>&1 | tail -5`
Expected: All pass, count >= 1543

- [ ] **Step 6: Commit**

```bash
git add src/llm/packet_writer.py tests/test_xml_format.py
git commit -m "feat: restructure LLM prompt to 11 clean sections with cross-asset data"
```

---

### Task 6: Add random source subsetting

**Files:**
- Modify: `src/llm/packet_writer.py`
- Modify: `tests/test_xml_format.py`

- [ ] **Step 1: Write the test**

```python
class TestRandomSourceSubsetting:
    def test_subsetting_drops_some_sections(self):
        """With subsetting enabled, some non-core sections should be omitted."""
        from src.llm.packet_writer import _build_feature_prompt
        features = _minimal_features()
        # Run 20 times — at least one should drop a section
        prompts = [_build_feature_prompt(features, "TEST", subsetting=True) for _ in range(20)]
        full = _build_feature_prompt(features, "TEST", subsetting=False)
        assert any(len(p) < len(full) for p in prompts), "Subsetting should sometimes drop sections"

    def test_core_sections_never_dropped(self):
        """Technical Data and Market Regime must always be present."""
        from src.llm.packet_writer import _build_feature_prompt
        features = _minimal_features()
        for _ in range(50):
            prompt = _build_feature_prompt(features, "TEST", subsetting=True)
            assert "=== TECHNICAL DATA ===" in prompt
            assert "=== MARKET REGIME ===" in prompt
```

- [ ] **Step 2: Implement subsetting**

Follow `docs/sprints/sprint-xml-expansion.md` Task 2. Core sections (1, 2) are always included. Sections 3-11 are each included with 70% probability when `subsetting=True`. This prevents the model from learning to rely on any single auxiliary source.

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_xml_format.py -v`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add src/llm/packet_writer.py tests/test_xml_format.py
git commit -m "feat: add random source subsetting for training robustness"
```

---

## Phase 3: Outcome-Conditioned Training Integration

**Goal:** Wire the existing `outcome_prompts.py` templates into `data_collector.py` so each closed trade generates 3-5 training examples instead of 1.

**Branch:** `feat/outcome-conditioned-training`

**Spec:** `docs/sprints/implementation-plan-sprints-3-7.md` (Sprint 6, lines 303-393)

**Current state:** `src/training/outcome_prompts.py` (251 lines, 4 templates) and schema columns (regime_at_entry, vix_at_entry, etc.) already exist. What's missing is the integration in `data_collector.py` — it still generates only 1 example per trade.

### File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/training/data_collector.py` | Modify line 116+ | Add outcome classification and multi-example generation |
| `tests/test_data_collectors.py` | Modify | Add tests for outcome-conditioned generation |

---

### Task 7: Add outcome classifier and multi-example generation

**Files:**
- Modify: `src/training/data_collector.py:116`
- Modify: `tests/test_data_collectors.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_data_collectors.py`:

```python
class TestOutcomeClassification:
    def test_classify_win(self):
        from src.training.data_collector import _classify_outcome
        trade = {"status": "closed", "pnl_dollars": 100, "exit_reason": "target_1_hit"}
        assert _classify_outcome(trade) == "WIN"

    def test_classify_loss(self):
        from src.training.data_collector import _classify_outcome
        trade = {"status": "closed", "pnl_dollars": -50, "exit_reason": "stop_hit"}
        assert _classify_outcome(trade) == "LOSS"

    def test_classify_timeout(self):
        from src.training.data_collector import _classify_outcome
        trade = {"status": "closed", "pnl_dollars": 10, "exit_reason": "timeout"}
        assert _classify_outcome(trade) == "TIMEOUT"

    def test_classify_breakeven(self):
        from src.training.data_collector import _classify_outcome
        trade = {"status": "closed", "pnl_dollars": 0.5, "exit_reason": "timeout"}
        assert _classify_outcome(trade) == "TIMEOUT"


class TestOutcomePromptSelection:
    def test_win_selects_winner_prompt(self):
        from src.training.data_collector import _get_outcome_prompt
        from src.training.outcome_prompts import WINNER_SYSTEM_PROMPT
        prompt = _get_outcome_prompt("WIN")
        assert prompt == WINNER_SYSTEM_PROMPT

    def test_loss_selects_loser_prompt(self):
        from src.training.data_collector import _get_outcome_prompt
        from src.training.outcome_prompts import LOSER_SYSTEM_PROMPT
        prompt = _get_outcome_prompt("LOSS")
        assert prompt == LOSER_SYSTEM_PROMPT
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_data_collectors.py::TestOutcomeClassification -v`
Expected: FAIL — `ImportError: cannot import name '_classify_outcome'`

- [ ] **Step 3: Add outcome classification**

In `src/training/data_collector.py`, add before `collect_training_examples_from_closed_trades`:

```python
def _classify_outcome(trade: dict) -> str:
    """Classify a closed trade's outcome type for prompt selection."""
    exit_reason = trade.get("exit_reason", "")
    pnl = float(trade.get("pnl_dollars") or 0)

    if "timeout" in exit_reason:
        return "TIMEOUT"
    if pnl > 0:
        return "WIN"
    return "LOSS"


def _get_outcome_prompt(outcome_type: str) -> str:
    """Get the system prompt template for a given outcome type."""
    from src.training.outcome_prompts import (
        WINNER_SYSTEM_PROMPT, LOSER_SYSTEM_PROMPT,
        TIMEOUT_SYSTEM_PROMPT, PASS_SYSTEM_PROMPT,
    )
    return {
        "WIN": WINNER_SYSTEM_PROMPT,
        "LOSS": LOSER_SYSTEM_PROMPT,
        "TIMEOUT": TIMEOUT_SYSTEM_PROMPT,
        "PASS": PASS_SYSTEM_PROMPT,
    }.get(outcome_type, WINNER_SYSTEM_PROMPT)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_data_collectors.py::TestOutcomeClassification tests/test_data_collectors.py::TestOutcomePromptSelection -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/training/data_collector.py tests/test_data_collectors.py
git commit -m "feat: add outcome classification and prompt selection for training"
```

---

### Task 8: Integrate multi-example generation into collection loop

**Files:**
- Modify: `src/training/data_collector.py:156-170`

- [ ] **Step 1: Modify the collection loop**

In `collect_training_examples_from_closed_trades`, after line 161 (`trade = dict(row)`), modify the generation logic:

```python
    for row in rows:
        trade = dict(row)
        outcome_type = _classify_outcome(trade)

        enriched = trade.get("enriched_prompt")
        if enriched:
            feature_input = enriched
        else:
            feature_input = _rebuild_basic_prompt(trade)

        # Primary example (outcome-conditioned prompt)
        system_prompt = _get_outcome_prompt(outcome_type)
        example_1 = _generate_single_example(
            feature_input, system_prompt, trade, db_path,
            example_type="primary", outcome_type=outcome_type,
        )
        if example_1:
            count += 1

        # Contrastive example (opposite stance) — for WIN and LOSS only
        if outcome_type in ("WIN", "LOSS"):
            contrastive_type = "PASS" if outcome_type == "WIN" else "WIN"
            contrastive_prompt = _get_outcome_prompt(contrastive_type)
            example_2 = _generate_single_example(
                feature_input, contrastive_prompt, trade, db_path,
                example_type="contrastive", outcome_type=outcome_type,
            )
            if example_2:
                count += 1

        attempted += 1
        if attempted >= max_per_batch:
            break
```

Where `_generate_single_example` wraps the existing LLM call + quality scoring + storage logic that's currently inline. Extract the existing inline code into this function — same behavior, just callable multiple times per trade.

- [ ] **Step 2: Run full test suite**

Run: `python -m pytest tests/ -q --tb=line 2>&1 | tail -5`
Expected: All pass, count >= 1543

- [ ] **Step 3: Commit**

```bash
git add src/training/data_collector.py
git commit -m "feat: generate 2-3 training examples per closed trade via outcome-conditioned prompts"
```

---

## Phase 4: System Monitoring

**Goal:** Create a system metrics collector, schema, API, and dashboard page for GPU/CPU/RAM/disk/Ollama monitoring.

**Branch:** `feat/system-monitoring`

**Spec:** `docs/sprints/sprint-system-monitoring.md`

**Execution note:** The existing sprint doc contains complete, accurate code for all tasks. Execute it as-written. Key deliverables:

### File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/monitoring/__init__.py` | Create | Package init |
| `src/monitoring/system_metrics.py` | Create | Metric collector (GPU, CPU, RAM, disk, Ollama) |
| `src/schema/registry.py` | Modify | Add `system_metrics` table |
| `src/api/routes/system.py` | Modify | Add `/api/monitoring/snapshot` and `/api/monitoring/history` |
| `src/scheduler/watch.py` | Modify | Add 5-minute collection trigger |
| `frontend/src/pages/Monitoring.jsx` | Create | Dashboard page |
| `frontend/src/App.jsx` | Modify | Add route |
| `frontend/src/components/Layout.jsx` | Modify | Add sidebar entry |
| `tests/test_system_metrics.py` | Create | Unit tests |

---

### Task 9: Create system_metrics schema

**Files:**
- Modify: `src/schema/registry.py`
- Create: `src/monitoring/__init__.py`

- [ ] **Step 1: Add system_metrics table to registry**

In `src/schema/registry.py`, add:

```python
TableDef(
    name="system_metrics",
    description="System utilization snapshots (GPU, CPU, RAM, disk, Ollama)",
    columns=[
        ColumnDef("snapshot_id", "TEXT", primary_key=True),
        ColumnDef("timestamp", "TEXT", description="ISO timestamp ET"),
        ColumnDef("gpu_util_pct", "REAL"),
        ColumnDef("gpu_vram_used_mb", "REAL"),
        ColumnDef("gpu_vram_total_mb", "REAL"),
        ColumnDef("gpu_temp_c", "REAL"),
        ColumnDef("gpu_power_w", "REAL"),
        ColumnDef("cpu_pct", "REAL"),
        ColumnDef("ram_used_mb", "REAL"),
        ColumnDef("ram_total_mb", "REAL"),
        ColumnDef("disk_used_gb", "REAL"),
        ColumnDef("disk_total_gb", "REAL"),
        ColumnDef("ollama_status", "TEXT", description="'running', 'stopped', 'error'"),
        ColumnDef("ollama_model", "TEXT"),
        ColumnDef("python_rss_mb", "REAL", description="Current process RSS"),
    ],
),
```

- [ ] **Step 2: Create package init**

```python
# src/monitoring/__init__.py
"""System monitoring — GPU, CPU, RAM, disk, Ollama health tracking."""
```

- [ ] **Step 3: Run schema validation**

Run: `python -m src.main validate-schema`
Expected: system_metrics table created

- [ ] **Step 4: Commit**

```bash
git add src/schema/registry.py src/monitoring/__init__.py
git commit -m "feat: add system_metrics schema table for monitoring"
```

---

### Task 10: Create metric collector

**Files:**
- Create: `src/monitoring/system_metrics.py`
- Create: `tests/test_system_metrics.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_system_metrics.py
"""Tests for system metrics collector."""

from unittest.mock import patch, MagicMock


class TestCollectGpuMetrics:
    def test_nvidia_smi_success(self):
        from src.monitoring.system_metrics import _collect_gpu_metrics
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "45, 4096, 12288, 62, 120.5"
        with patch("subprocess.run", return_value=mock_result):
            metrics = _collect_gpu_metrics()
        assert metrics["gpu_util_pct"] == 45.0
        assert metrics["gpu_vram_used_mb"] == 4096.0
        assert metrics["gpu_temp_c"] == 62.0

    def test_nvidia_smi_not_available(self):
        from src.monitoring.system_metrics import _collect_gpu_metrics
        with patch("subprocess.run", side_effect=FileNotFoundError):
            metrics = _collect_gpu_metrics()
        assert metrics["gpu_util_pct"] is None


class TestCollectCpuRam:
    def test_psutil_metrics(self):
        from src.monitoring.system_metrics import _collect_cpu_ram_metrics
        metrics = _collect_cpu_ram_metrics()
        assert "cpu_pct" in metrics
        assert "ram_used_mb" in metrics
        assert metrics["cpu_pct"] >= 0


class TestCollectOllamaStatus:
    def test_ollama_running(self):
        from src.monitoring.system_metrics import _collect_ollama_status
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"models": [{"name": "halcyon-v1.0.0"}]}
        with patch("requests.get", return_value=mock_resp):
            metrics = _collect_ollama_status()
        assert metrics["ollama_status"] == "running"

    def test_ollama_down(self):
        from src.monitoring.system_metrics import _collect_ollama_status
        with patch("requests.get", side_effect=Exception("refused")):
            metrics = _collect_ollama_status()
        assert metrics["ollama_status"] == "error"


class TestFullSnapshot:
    def test_snapshot_stores_to_db(self, tmp_path):
        from src.monitoring.system_metrics import collect_system_snapshot
        from src.journal.store import initialize_database
        import sqlite3

        db = str(tmp_path / "test.db")
        initialize_database(db)

        with patch("src.monitoring.system_metrics._collect_gpu_metrics",
                   return_value={"gpu_util_pct": 50, "gpu_vram_used_mb": 4000,
                                 "gpu_vram_total_mb": 12000, "gpu_temp_c": 60,
                                 "gpu_power_w": 120}), \
             patch("src.monitoring.system_metrics._collect_ollama_status",
                   return_value={"ollama_status": "running", "ollama_model": "halcyon-v1.0.0"}):
            snapshot = collect_system_snapshot(db)

        assert snapshot["gpu_util_pct"] == 50
        with sqlite3.connect(db) as conn:
            row = conn.execute("SELECT COUNT(*) FROM system_metrics").fetchone()
            assert row[0] == 1
```

- [ ] **Step 2: Implement the collector**

Follow the code in `docs/sprints/sprint-system-monitoring.md` Task 1 exactly. The sprint doc has the complete `system_metrics.py` with `_collect_gpu_metrics()`, `_collect_cpu_ram_metrics()`, `_collect_disk_metrics()`, `_collect_ollama_status()`, `_collect_process_metrics()`, and `_store_snapshot()`.

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_system_metrics.py -v`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add src/monitoring/system_metrics.py tests/test_system_metrics.py
git commit -m "feat: system metrics collector — GPU, CPU, RAM, disk, Ollama"
```

---

### Task 11: API endpoints and watch loop integration

**Files:**
- Modify: `src/api/routes/system.py`
- Modify: `src/scheduler/watch.py`

- [ ] **Step 1: Add API endpoints**

In `src/api/routes/system.py`, add:

```python
@router.get("/api/monitoring/snapshot")
def monitoring_snapshot():
    """Get latest system metrics snapshot."""
    from src.monitoring.system_metrics import collect_system_snapshot
    return collect_system_snapshot()


@router.get("/api/monitoring/history")
def monitoring_history(hours: int = 24):
    """Get system metrics history for the last N hours."""
    import sqlite3
    from src.config import DB_PATH
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM system_metrics "
            "WHERE timestamp >= datetime('now', ? || ' hours') "
            "ORDER BY timestamp ASC",
            (f"-{hours}",),
        ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 2: Add 5-minute collection trigger to watch loop**

In `src/scheduler/watch.py`, in the main loop's periodic task section, add:

```python
        # System metrics collection every 5 minutes
        if self._scan_number % 5 == 0:
            try:
                from src.monitoring.system_metrics import collect_system_snapshot
                collect_system_snapshot(db_path)
            except Exception as e:
                logger.debug("[WATCH] System metrics collection failed: %s", e)
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/ -q --tb=line 2>&1 | tail -5`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add src/api/routes/system.py src/scheduler/watch.py
git commit -m "feat: monitoring API endpoints and watch loop collection trigger"
```

---

### Task 12: Monitoring dashboard page

**Files:**
- Create: `frontend/src/pages/Monitoring.jsx`
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/components/Layout.jsx`

- [ ] **Step 1: Create the page**

Follow `docs/sprints/sprint-system-monitoring.md` for the full React component. Key sections:
- GPU utilization time-series chart (Recharts AreaChart)
- CPU/RAM gauges (current values with 24h sparkline)
- Disk usage bar
- Ollama status indicator
- System metrics table (last 10 snapshots)

Use TanStack Query with `useQuery({ queryKey: ['monitoring-history'], queryFn: () => api('/api/monitoring/history'), refetchInterval: 60000 })` for auto-refresh.

- [ ] **Step 2: Add route to App.jsx**

```jsx
import Monitoring from './pages/Monitoring'

// In the Routes:
<Route path="/monitoring" element={<Monitoring />} />
```

- [ ] **Step 3: Add sidebar entry to Layout.jsx**

Add `{ path: '/monitoring', label: 'Monitoring', icon: Activity }` to the nav items array, grouped with the other infrastructure pages (Health, Settings, Logs).

- [ ] **Step 4: Verify build**

Run: `cd /c/arcis/halcyon-lab/frontend && npm run build`
Expected: Build succeeds with zero errors

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Monitoring.jsx frontend/src/App.jsx frontend/src/components/Layout.jsx
git commit -m "feat: Monitoring dashboard page — GPU, CPU, RAM, Ollama status"
```

---

## Phase 5: Strategy Dashboard

**Goal:** Create a Strategy comparison page with per-strategy equity curves, score band analysis, regime breakdown, and drawdown profiles.

**Branch:** `feat/strategy-dashboard`

**Spec:** `docs/decisions/strategy-dashboard-spec.md`

### File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/api/cloud_routes/analytics.py` | Modify | Add `/api/strategy-detail/{strategy_type}` endpoint |
| `frontend/src/pages/Strategy.jsx` | Create | Full strategy comparison page |
| `frontend/src/App.jsx` | Modify | Add route |
| `frontend/src/components/Layout.jsx` | Modify | Add sidebar entry |

---

### Task 13: Backend strategy-detail endpoint

**Files:**
- Modify: `src/api/cloud_routes/analytics.py`

- [ ] **Step 1: Add the endpoint**

In `src/api/cloud_routes/analytics.py`, add:

```python
@router.get("/api/strategy-detail/{strategy_type}")
def strategy_detail(strategy_type: str):
    """Detailed analytics for a single strategy (pullback or mean_reversion)."""
    import sqlite3
    from src.config import DB_PATH

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        trades = conn.execute("""
            SELECT ticker, actual_entry_time as entry_date,
                   actual_exit_time as exit_date,
                   pnl_pct, pnl_dollars, exit_reason,
                   duration_days, quality_score_auto as score,
                   regime_at_entry as regime
            FROM shadow_trades
            WHERE status = 'closed' AND strategy_type = ?
            ORDER BY actual_exit_time ASC
        """, (strategy_type,)).fetchall()

    if not trades:
        return {"trades": [], "by_score_band": {}, "by_regime": {},
                "hold_distribution": [], "by_sector": {},
                "rolling_metrics": [], "drawdown_series": []}

    trade_list = [dict(t) for t in trades]

    # Compute cumulative P&L
    cumulative = 0
    for t in trade_list:
        cumulative += float(t.get("pnl_dollars") or 0)
        t["cumulative_pnl"] = round(cumulative, 2)

    # Score band breakdown
    bands = {"0-39": [], "40-59": [], "60-79": [], "80-100": []}
    for t in trade_list:
        s = int(t.get("score") or 0)
        if s >= 80: bands["80-100"].append(t)
        elif s >= 60: bands["60-79"].append(t)
        elif s >= 40: bands["40-59"].append(t)
        else: bands["0-39"].append(t)

    by_score_band = {}
    for band, tlist in bands.items():
        if not tlist:
            by_score_band[band] = {"trades": 0, "wins": 0, "win_rate": 0, "avg_pnl": 0}
            continue
        wins = sum(1 for t in tlist if float(t.get("pnl_dollars") or 0) > 0)
        avg_pnl = sum(float(t.get("pnl_pct") or 0) for t in tlist) / len(tlist)
        by_score_band[band] = {
            "trades": len(tlist), "wins": wins,
            "win_rate": round(wins / len(tlist), 3),
            "avg_pnl": round(avg_pnl, 2),
        }

    # Regime breakdown
    by_regime = {}
    for t in trade_list:
        regime = t.get("regime") or "unknown"
        if regime not in by_regime:
            by_regime[regime] = []
        by_regime[regime].append(t)
    by_regime = {
        k: {
            "trades": len(v),
            "win_rate": round(sum(1 for t in v if float(t.get("pnl_dollars") or 0) > 0) / len(v), 3),
            "avg_pnl": round(sum(float(t.get("pnl_pct") or 0) for t in v) / len(v), 2),
        }
        for k, v in by_regime.items()
    }

    # Hold distribution
    hold_counts = {}
    for t in trade_list:
        days = int(t.get("duration_days") or 0)
        hold_counts[days] = hold_counts.get(days, 0) + 1
    hold_distribution = [{"days": d, "count": c} for d, c in sorted(hold_counts.items())]

    # Drawdown series
    peak = 0
    drawdown_series = []
    for i, t in enumerate(trade_list):
        cum = t["cumulative_pnl"]
        peak = max(peak, cum)
        dd_pct = round((peak - cum) / max(peak, 1) * 100, 1) if peak > 0 else 0
        drawdown_series.append({"trade_num": i + 1, "cumulative_pnl": cum, "drawdown_pct": dd_pct})

    return {
        "trades": trade_list,
        "by_score_band": by_score_band,
        "by_regime": by_regime,
        "hold_distribution": hold_distribution,
        "drawdown_series": drawdown_series,
    }
```

- [ ] **Step 2: Run tests**

Run: `python -m pytest tests/ -q --tb=line 2>&1 | tail -5`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add src/api/cloud_routes/analytics.py
git commit -m "feat: add /api/strategy-detail endpoint for per-strategy analytics"
```

---

### Task 14: Strategy.jsx frontend page

**Files:**
- Create: `frontend/src/pages/Strategy.jsx`
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/components/Layout.jsx`

- [ ] **Step 1: Create Strategy.jsx**

Build a page with these sections:
1. Strategy selector tabs (Pullback / Mean Reversion)
2. KPI cards row (total trades, win rate, profit factor, avg hold days)
3. Equity curve (Recharts LineChart from `trades[].cumulative_pnl`)
4. Score band bar chart (from `by_score_band`)
5. Regime performance table (from `by_regime`)
6. Hold period histogram (from `hold_distribution`)
7. Drawdown chart (from `drawdown_series`)

Use TanStack Query:
```jsx
const { data } = useQuery({
    queryKey: ['strategy-detail', selectedStrategy],
    queryFn: () => api(`/api/strategy-detail/${selectedStrategy}`),
})
```

Follow the existing Arcis Palette H CSS variables and component patterns from `Dashboard.jsx` and `CTOReport.jsx`.

- [ ] **Step 2: Add route and sidebar**

In `App.jsx`:
```jsx
import Strategy from './pages/Strategy'
<Route path="/strategy" element={<Strategy />} />
```

In `Layout.jsx`, add `{ path: '/strategy', label: 'Strategy', icon: Target }` to nav items near the trading section.

- [ ] **Step 3: Verify build**

Run: `cd /c/arcis/halcyon-lab/frontend && npm run build`
Expected: Build succeeds

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Strategy.jsx frontend/src/App.jsx frontend/src/components/Layout.jsx
git commit -m "feat: Strategy dashboard page — equity curves, score bands, regime breakdown"
```

---

## Phase 6: Dashboard Polish (React Flow Shared Components + Mega Dashboard Fixes)

**Goal:** Extract shared React Flow diagram components from Architecture.jsx, and complete remaining mega dashboard polish (audit banner redesign, build score empty state, CTO report command handler).

**Branch:** `feat/dashboard-polish`

**Specs:** `docs/sprints/sprint-react-flow-ui-polish.md` (Part A) + `docs/sprints/sprint-mega-dashboard-docs.md` (Part A Tasks 1-2)

### File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `frontend/src/components/diagrams/FlowDiagram.jsx` | Create | Shared React Flow wrapper |
| `frontend/src/components/diagrams/SystemNode.jsx` | Create | Custom node component |
| `frontend/src/pages/Architecture.jsx` | Modify | Refactor to use shared components |
| `frontend/src/pages/Dashboard.jsx` | Modify | Audit banner chip + build score empty state |
| `src/commands/executor.py` | Modify | Add `cto-report` command handler |

---

### Task 15: Extract shared React Flow components

**Files:**
- Create: `frontend/src/components/diagrams/FlowDiagram.jsx`
- Create: `frontend/src/components/diagrams/SystemNode.jsx`
- Modify: `frontend/src/pages/Architecture.jsx`

- [ ] **Step 1: Create FlowDiagram wrapper**

```jsx
// frontend/src/components/diagrams/FlowDiagram.jsx
import { ReactFlow, Background, Controls, MiniMap } from '@xyflow/react'
import '@xyflow/react/dist/style.css'

export default function FlowDiagram({
  nodes, edges, nodeTypes, onNodesChange, onEdgesChange,
  fitView = true, minimap = false, className = '',
}) {
  return (
    <div className={`w-full rounded-lg border ${className}`}
         style={{ height: 600, background: 'var(--arcis-bg-secondary)' }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        fitView={fitView}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={16} size={1} color="var(--arcis-border)" />
        <Controls position="bottom-right" />
        {minimap && <MiniMap />}
      </ReactFlow>
    </div>
  )
}
```

- [ ] **Step 2: Create SystemNode component**

```jsx
// frontend/src/components/diagrams/SystemNode.jsx
import { Handle, Position } from '@xyflow/react'

const CATEGORY_COLORS = {
  data: 'var(--arcis-success)',
  ai: 'var(--arcis-accent)',
  risk: 'var(--arcis-danger)',
  training: 'var(--arcis-warning)',
  infra: 'var(--arcis-text-muted)',
}

export default function SystemNode({ data }) {
  const accentColor = CATEGORY_COLORS[data.category] || CATEGORY_COLORS.infra
  return (
    <div className="rounded-lg border px-3 py-2 min-w-[140px]"
         style={{ background: 'var(--arcis-bg-card)', borderColor: 'var(--arcis-border)' }}>
      <div className="absolute left-0 top-0 bottom-0 w-1 rounded-l-lg"
           style={{ background: accentColor }} />
      <div className="text-xs font-semibold" style={{ color: 'var(--arcis-text-primary)' }}>
        {data.label}
      </div>
      {data.subtitle && (
        <div className="text-[10px] mt-0.5" style={{ color: 'var(--arcis-text-muted)' }}>
          {data.subtitle}
        </div>
      )}
      {data.badge && (
        <span className="text-[9px] px-1.5 py-0.5 rounded-full mt-1 inline-block"
              style={{ background: accentColor + '22', color: accentColor }}>
          {data.badge}
        </span>
      )}
      <Handle type="target" position={Position.Top} />
      <Handle type="source" position={Position.Bottom} />
    </div>
  )
}
```

- [ ] **Step 3: Refactor Architecture.jsx to use shared components**

Replace the inline node/edge styling in `Architecture.jsx` with imports from the shared components. The page should import `FlowDiagram` and `SystemNode` and pass them as `nodeTypes={{ system: SystemNode }}`.

- [ ] **Step 4: Verify build**

Run: `cd /c/arcis/halcyon-lab/frontend && npm run build`
Expected: Build succeeds

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/diagrams/ frontend/src/pages/Architecture.jsx
git commit -m "feat: extract shared React Flow diagram components (FlowDiagram, SystemNode)"
```

---

### Task 16: Redesign audit banner and fix build score empty state

**Files:**
- Modify: `frontend/src/pages/Dashboard.jsx`

- [ ] **Step 1: Replace audit banner with compact chip**

Follow `docs/sprints/sprint-mega-dashboard-docs.md` Task 1 exactly. Replace the full-width red banner (lines 224-232) with a single-line expandable chip:

```jsx
const [auditExpanded, setAuditExpanded] = useState(false)

// Compute staleness
const auditCreatedAt = auditData?.created_at || auditData?.audit_date
const isStale = auditCreatedAt &&
  (Date.now() - new Date(auditCreatedAt).getTime()) > 24 * 60 * 60 * 1000

// Chip color by assessment
const chipConfig = isStale
  ? { text: 'Stale (>24h)', color: 'var(--arcis-text-muted)' }
  : auditAssessment === 'green' || auditAssessment === 'healthy'
  ? { text: 'System OK', color: 'var(--arcis-success)' }
  : auditAssessment === 'yellow' || auditAssessment === 'warning'
  ? { text: 'Warnings', color: 'var(--arcis-warning)' }
  : auditAssessment === 'red' || auditAssessment === 'critical'
  ? { text: 'Issues found', color: 'var(--arcis-danger)' }
  : { text: 'No audit', color: 'var(--arcis-text-muted)' }
```

- [ ] **Step 2: Fix build score empty state**

Follow `docs/sprints/sprint-mega-dashboard-docs.md` Task 2A. When `build_score === 0` and all components are 0, show "Build Score not yet computed" instead of zero-filled gauges.

- [ ] **Step 3: Verify build**

Run: `cd /c/arcis/halcyon-lab/frontend && npm run build`
Expected: Build succeeds

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Dashboard.jsx
git commit -m "fix: compact audit chip + build score empty state on Dashboard"
```

---

### Task 17: Add cto-report command handler

**Files:**
- Modify: `src/commands/executor.py`

- [ ] **Step 1: Add the handler**

In `src/commands/executor.py`, in the `COMMAND_HANDLERS` dict, add:

```python
"cto-report": _handle_cto_report,
```

And add the handler function:

```python
def _handle_cto_report(args: dict, config: dict, db_path: str) -> dict:
    """Generate CTO report (build score + evaluation)."""
    try:
        from src.evaluation.build_score import persist_build_score
        result = persist_build_score(db_path=db_path)
        return {"status": "ok", "build_score": result}
    except Exception as e:
        logger.error("[CMD] CTO report generation failed: %s", e)
        return {"status": "error", "error": str(e)}
```

- [ ] **Step 2: Run tests**

Run: `python -m pytest tests/ -q --tb=line 2>&1 | tail -5`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add src/commands/executor.py
git commit -m "feat: add cto-report command handler for dashboard button"
```

---

## Phase 7: iOS Capacitor

**Goal:** Wrap the React dashboard in Capacitor for iOS sideloading.

**Branch:** `feat/ios-capacitor`

**Spec:** `docs/sprints/sprint-ios-capacitor.md`

**Execution note:** Execute the sprint doc as-written. It contains complete, accurate code for all 15 tasks. The frontend has grown from 14 to 20 pages since the doc was written, but the Capacitor integration is additive — no existing pages need changes beyond:
- `config.js` (API URL detection)
- `index.html` (service worker guard)
- `App.jsx` (status bar config on mount)
- `Dashboard.jsx` (haptics on halt/resume)

**macOS blocker:** Tasks 1-7 and 10-14 run on Windows. Tasks 8-9 (Xcode build + app icon generation) require macOS. Generate the `ios/` project and leave it ready for a Mac build session.

### File Map

| File | Action | Source |
|------|--------|--------|
| `frontend/capacitor.config.ts` | Create | Sprint doc Task 1 |
| `frontend/src/config.js` | Modify | Sprint doc Task 2 — add Capacitor native detection |
| `frontend/index.html` | Modify | Sprint doc Task 3 — guard service worker |
| `frontend/src/native.js` | Create | Sprint doc Task 6 — haptics, status bar, auth, lifecycle |
| `frontend/src/App.jsx` | Modify | Sprint doc Task 7 — configureStatusBar on mount |
| `frontend/src/pages/Dashboard.jsx` | Modify | Sprint doc Task 7 — haptic on halt/resume |
| `frontend/src/index.css` | Modify | Sprint doc Task 8 — safe area CSS |
| `frontend/package.json` | Modify | Sprint doc Tasks 1, 4, 5, 11 — deps + scripts |

### Task 18-24: Execute sprint-ios-capacitor.md Tasks 1-7, 10-14

- [ ] **Step 1:** Install Capacitor core + CLI + iOS (Tasks 1, 4)
- [ ] **Step 2:** Create `capacitor.config.ts` with plugin config (Task 1)
- [ ] **Step 3:** Update `config.js` with native detection (Task 2)
- [ ] **Step 4:** Guard service worker in `index.html` (Task 3)
- [ ] **Step 5:** Install native plugins (Task 5)
- [ ] **Step 6:** Create `native.js` bridge utility (Task 6)
- [ ] **Step 7:** Wire haptics + status bar into App.jsx and Dashboard.jsx (Task 7)
- [ ] **Step 8:** Add safe area CSS variables (Task 8)
- [ ] **Step 9:** Add build scripts to package.json (Task 11)
- [ ] **Step 10:** Add pull-to-refresh (Task 12)
- [ ] **Step 11:** Add foreground refetch (Task 13)
- [ ] **Step 12:** Verify `npm run build` succeeds
- [ ] **Step 13:** Run `npx cap sync ios` (creates ios/ project)
- [ ] **Step 14:** Commit

```bash
git add frontend/
git commit -m "feat: iOS Capacitor wrapper — native bridge, haptics, safe areas, pull-to-refresh"
```

**Deferred to macOS session:** Open Xcode, set signing team, build to device (30 min).

---

## Final Verification

After all 7 phases are merged to main:

- [ ] **Full test suite:** `python -m pytest tests/ -q` — must pass, count >= 1,560
- [ ] **Frontend build:** `cd frontend && npm run build` — zero errors
- [ ] **Schema validation:** `python -m src.main validate-schema` — no drift
- [ ] **Startup check:** `python -m src.main startup` — all checks pass
- [ ] **Preflight:** `python -m src.main preflight` — no warnings

---

## Appendix: What Was Already Done (No Action Needed)

| Sprint | Status | Evidence |
|--------|--------|----------|
| Sprint 7: Stress Testing | Implemented | `scripts/stress_test.py` (434 lines), `StressTest.jsx` (201 lines) |
| Sprint 6: Outcome Prompts (templates) | Implemented | `outcome_prompts.py` (251 lines), 4 templates, schema columns |
| Sprint 6: Schema columns | Implemented | `regime_at_entry`, `vix_at_entry`, etc. in registry |
| React Flow: Architecture page | Implemented | `Architecture.jsx` (195 lines, 7 React Flow refs) |
| Mega Dashboard: Part A Tasks 3-4 | Implemented | Activity feed + action buttons working |
