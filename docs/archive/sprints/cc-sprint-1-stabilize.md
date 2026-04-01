# Sprint 1: Stabilize — Saturday Morning

You are working on the halcyon-lab repo (github.com/millerrc18/halcyon-lab).
This is a cleanup and stabilization sprint. NO new features. Fix what's broken, verify what exists.

## CRITICAL CONTEXT

Council v2 has been deployed to main. The files `src/council/agents.py`, `src/council/protocol.py`, and `src/council/engine.py` have been REPLACED with v2 implementations. v1 backups exist as `*_v1_backup.py`. A new file `src/council/value_tracker.py` was added.

The v2 council uses:
- 5 agents: tactical_operator, strategic_architect, red_team, innovation_engine, macro_navigator
- Direction: bullish/neutral/bearish (NOT position: defensive/neutral/offensive)
- Confidence: 0.0-1.0 float (NOT 1-10 integer)
- 1-2 rounds (NOT always 3). Round 2 only if <3/5 consensus.
- Data gather functions return STRINGS (NOT dicts)
- Function names: gather_tactical_data, gather_strategic_data, gather_risk_data, gather_innovation_data, gather_macro_data

## Pre-read (mandatory, read ALL of these IN FULL before starting):
```
cat AGENTS.md
cat src/council/agents.py
cat src/council/protocol.py
cat src/council/engine.py
cat src/council/value_tracker.py
cat tests/test_council.py
cat tests/test_council_agents.py
cat src/sync/render_sync.py
cat scripts/render_migrate.py
cat src/shadow_trading/executor.py
cat src/api/routes/system.py
cat src/api/websocket.py
cat src/api/cloud_app.py
cat src/data_collection/edgar_collector.py
cat frontend/src/pages/Council.jsx
```

Run before starting: `python -m pytest tests/ -x -q`
Council tests WILL fail. That's expected — they're written for v1.

---

## Task 1: Merge CC cleanup (compatible changes only)

The cleanup branch added RotatingFileHandler, Council.jsx fix, docs, config, and test fixes.
Apply these changes manually (the branch may have diverged):

**1a. File logging in watch.py:**
Add at the top of the WatchDog.__init__ or module-level setup in `src/scheduler/watch.py`:
```python
from logging.handlers import RotatingFileHandler
from pathlib import Path

log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)
fh = RotatingFileHandler(log_dir / "halcyon.log", maxBytes=10_000_000, backupCount=7)
fh.setLevel(logging.INFO)
fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
logging.getLogger().addHandler(fh)
logging.getLogger().setLevel(logging.INFO)
```
Add `logs/` to `.gitignore` if not already there.

**1b. settings.example.yaml:**
Add execution config section if not present:
```yaml
execution:
  order_type: "market"
  limit_timeout_seconds: 300
```

## Task 2: Rewrite council tests for v2

Delete the existing `tests/test_council.py` and `tests/test_council_agents.py`.
Create a single new file `tests/test_council.py` with 30+ tests.

**Read src/council/agents.py, protocol.py, engine.py, and value_tracker.py IN FULL first.**

Required test structure:

```python
"""Council v2 tests — vote-first protocol with 5 analytical-lens agents."""
import json
import os
import sqlite3
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

# ── Fixtures ──────────────────────────────────────────────────

@pytest.fixture
def council_db(tmp_path):
    """Create a temporary database with all required tables populated."""
    db_path = str(tmp_path / "test.sqlite3")
    conn = sqlite3.connect(db_path)
    
    # Create ALL tables that gather functions query
    conn.executescript("""
        CREATE TABLE vix_term_structure (date TEXT, vix_close REAL, vix9d REAL, vix3m REAL);
        CREATE TABLE traffic_light_state (id INTEGER PRIMARY KEY, current_regime TEXT, last_total_score REAL);
        CREATE TABLE scan_metrics (created_at TEXT, scan_time TEXT, packet_worthy INTEGER, 
            llm_success INTEGER, llm_total INTEGER, avg_conviction REAL);
        CREATE TABLE shadow_trades (trade_id TEXT, ticker TEXT, status TEXT, pnl_pct REAL, 
            pnl_dollars REAL, sector TEXT, actual_entry_time TEXT, actual_exit_time TEXT,
            exit_reason TEXT, planned_allocation REAL, signal_price REAL,
            implementation_shortfall_bps REAL, max_adverse_excursion REAL,
            strategy_type TEXT DEFAULT 'pullback');
        CREATE TABLE training_examples (example_id TEXT, created_at TEXT, quality_score REAL,
            quality_score_auto REAL, source TEXT, difficulty TEXT, curriculum_stage TEXT);
        CREATE TABLE model_versions (version_id TEXT, created_at TEXT);
        CREATE TABLE macro_snapshots (series_id TEXT, date TEXT, value REAL);
        
        -- Populate with realistic test data
        INSERT INTO vix_term_structure VALUES ('2026-03-28', 18.5, 17.2, 20.1);
        INSERT INTO traffic_light_state VALUES (1, 'GREEN', 5.0);
        INSERT INTO scan_metrics VALUES (datetime('now'), '2026-03-28 10:00', 3, 8, 10, 6.5);
        INSERT INTO shadow_trades VALUES ('t1', 'AAPL', 'open', 1.5, 150, 'Technology',
            datetime('now', '-3 days'), NULL, NULL, 5000, 175.0, NULL, NULL, 'pullback');
        INSERT INTO shadow_trades VALUES ('t2', 'XOM', 'closed', -0.8, -80, 'Energy',
            datetime('now', '-10 days'), datetime('now', '-5 days'), 'stop_loss', 
            5000, 110.0, 5.2, -2.1, 'pullback');
        INSERT INTO training_examples VALUES ('ex1', datetime('now'), 22.0, 20.0, 'live', 'medium', 'evidence');
        INSERT INTO macro_snapshots VALUES ('DFF', '2026-03-28', 4.50);
        INSERT INTO macro_snapshots VALUES ('T10Y2Y', '2026-03-28', 0.35);
        INSERT INTO macro_snapshots VALUES ('BAMLH0A0HYM2', '2026-03-28', 3.80);
    """)
    conn.commit()
    conn.close()
    return db_path


# ── agents.py tests ───────────────────────────────────────────

class TestAgents:
    def test_agent_names_has_5_entries(self):
        from src.council.agents import AGENT_NAMES
        assert len(AGENT_NAMES) == 5
    
    def test_agent_data_functions_match_names(self):
        from src.council.agents import AGENT_NAMES, AGENT_DATA_FUNCTIONS
        assert set(AGENT_DATA_FUNCTIONS.keys()) == set(AGENT_NAMES)
    
    def test_agent_prompts_match_names(self):
        from src.council.agents import AGENT_NAMES, AGENT_PROMPTS
        assert set(AGENT_PROMPTS.keys()) == set(AGENT_NAMES)
    
    def test_tactical_returns_string(self, council_db):
        from src.council.agents import gather_tactical_data
        result = gather_tactical_data(db_path=council_db)
        assert isinstance(result, str)
        assert len(result) > 10
    
    def test_strategic_returns_string(self, council_db):
        from src.council.agents import gather_strategic_data
        result = gather_strategic_data(db_path=council_db)
        assert isinstance(result, str)
        assert len(result) > 10
    
    def test_risk_returns_string(self, council_db):
        from src.council.agents import gather_risk_data
        result = gather_risk_data(db_path=council_db)
        assert isinstance(result, str)
        assert len(result) > 10
    
    def test_innovation_returns_string(self, council_db):
        from src.council.agents import gather_innovation_data
        result = gather_innovation_data(db_path=council_db)
        assert isinstance(result, str)
        assert len(result) > 10
    
    def test_macro_returns_string(self, council_db):
        from src.council.agents import gather_macro_data
        result = gather_macro_data(db_path=council_db)
        assert isinstance(result, str)
        assert len(result) > 10
    
    def test_all_gather_functions_handle_empty_db(self, tmp_path):
        from src.council.agents import AGENT_DATA_FUNCTIONS
        empty_db = str(tmp_path / "empty.sqlite3")
        sqlite3.connect(empty_db).close()
        for name, fn in AGENT_DATA_FUNCTIONS.items():
            result = fn(db_path=empty_db)
            assert isinstance(result, str), f"{name} didn't return string on empty DB"
    
    def test_all_gather_functions_never_raise(self, tmp_path):
        from src.council.agents import AGENT_DATA_FUNCTIONS
        bad_db = str(tmp_path / "nonexistent" / "bad.sqlite3")
        for name, fn in AGENT_DATA_FUNCTIONS.items():
            result = fn(db_path=bad_db)
            assert isinstance(result, str), f"{name} raised or didn't return string"
    
    def test_query_db_helper(self, council_db):
        from src.council.agents import _query_db
        rows = _query_db("SELECT COUNT(*) as n FROM shadow_trades", db_path=council_db)
        assert rows[0]["n"] == 2


# ── protocol.py tests ─────────────────────────────────────────

class TestProtocol:
    def test_parse_valid_json(self):
        from src.council.protocol import _parse_agent_response
        raw = json.dumps({
            "agent": "tactical_operator",
            "direction": "bullish",
            "confidence": 0.8,
            "parameters": {"position_sizing_multiplier": 1.0, "cash_reserve_target_pct": 15, "scan_aggressiveness": "normal"},
            "key_reasoning": "Market looks strong",
            "key_risk": "VIX spike",
            "falsifiable_prediction": {"claim": "SPY above 550 by April 10", "confidence": 0.7, "verification_date": "2026-04-10"}
        })
        result = _parse_agent_response(raw, "tactical_operator")
        assert result["direction"] == "bullish"
        assert result["confidence"] == 0.8
        assert result.get("_parse_failed") is not True
    
    def test_parse_code_fenced_json(self):
        from src.council.protocol import _parse_agent_response
        raw = '```json\n{"agent": "red_team", "direction": "bearish", "confidence": 0.6, "key_reasoning": "Risk", "key_risk": "Gap down"}\n```'
        result = _parse_agent_response(raw, "red_team")
        assert result["direction"] == "bearish"
    
    def test_parse_json_in_prose(self):
        from src.council.protocol import _parse_agent_response
        raw = 'Here is my assessment: {"agent": "macro_navigator", "direction": "neutral", "confidence": 0.5, "key_reasoning": "Mixed signals", "key_risk": "Unclear"} That is all.'
        result = _parse_agent_response(raw, "macro_navigator")
        assert result["direction"] == "neutral"
    
    def test_parse_old_schema_autoconvert(self):
        from src.council.protocol import _parse_agent_response
        raw = json.dumps({"agent": "tactical_operator", "position": "offensive", "confidence": 8, "recommendation": "Buy", "key_data_points": [], "risk_flags": []})
        result = _parse_agent_response(raw, "tactical_operator")
        # Old confidence 8 (1-10) should convert to 0.8 (0.0-1.0)
        assert 0.7 <= result["confidence"] <= 0.9
    
    def test_parse_garbage_returns_default(self):
        from src.council.protocol import _parse_agent_response
        result = _parse_agent_response("This is not JSON at all", "red_team")
        assert result.get("_parse_failed") is True
        assert result["agent"] == "red_team"
        assert result["direction"] == "neutral"
    
    def test_aggregate_5_bullish_consensus(self):
        from src.council.protocol import aggregate_votes
        votes = [{"agent": f"agent_{i}", "direction": "bullish", "confidence": 0.8,
                  "parameters": {"position_sizing_multiplier": 1.1, "cash_reserve_target_pct": 15, "scan_aggressiveness": "normal"}}
                 for i in range(5)]
        result = aggregate_votes(votes, "daily")
        assert result["consensus_reached"] is True
        assert result["round2_needed"] is False
        assert result["direction"] == "bullish"
    
    def test_aggregate_split_needs_round2(self):
        from src.council.protocol import aggregate_votes
        votes = [
            {"agent": "a1", "direction": "bullish", "confidence": 0.8, "parameters": {"position_sizing_multiplier": 1.0, "cash_reserve_target_pct": 15, "scan_aggressiveness": "normal"}},
            {"agent": "a2", "direction": "bullish", "confidence": 0.7, "parameters": {"position_sizing_multiplier": 1.0, "cash_reserve_target_pct": 15, "scan_aggressiveness": "normal"}},
            {"agent": "a3", "direction": "bearish", "confidence": 0.8, "parameters": {"position_sizing_multiplier": 0.5, "cash_reserve_target_pct": 30, "scan_aggressiveness": "conservative"}},
            {"agent": "a4", "direction": "bearish", "confidence": 0.7, "parameters": {"position_sizing_multiplier": 0.5, "cash_reserve_target_pct": 30, "scan_aggressiveness": "conservative"}},
            {"agent": "a5", "direction": "neutral", "confidence": 0.5, "parameters": {"position_sizing_multiplier": 1.0, "cash_reserve_target_pct": 20, "scan_aggressiveness": "normal"}},
        ]
        result = aggregate_votes(votes, "daily")
        assert result["round2_needed"] is True
    
    def test_aggregate_3_2_is_consensus(self):
        from src.council.protocol import aggregate_votes
        votes = [
            {"agent": f"a{i}", "direction": "bullish", "confidence": 0.8, "parameters": {"position_sizing_multiplier": 1.0, "cash_reserve_target_pct": 15, "scan_aggressiveness": "normal"}}
            for i in range(3)
        ] + [
            {"agent": f"b{i}", "direction": "bearish", "confidence": 0.6, "parameters": {"position_sizing_multiplier": 0.5, "cash_reserve_target_pct": 25, "scan_aggressiveness": "conservative"}}
            for i in range(2)
        ]
        result = aggregate_votes(votes, "daily")
        assert result["consensus_reached"] is True
        assert result["direction"] == "bullish"
    
    def test_rate_limiter_clips_large_change(self):
        from src.council.protocol import apply_rate_limiters
        recommended = {"position_sizing_multiplier": 0.3, "cash_reserve_target_pct": 40}
        current = {"position_sizing_multiplier": 1.0, "cash_reserve_target_pct": 15}
        # This is a 70% reduction — should be clipped to 25% daily max
        result = apply_rate_limiters(recommended, current)
        assert result["position_sizing_multiplier"] >= 0.75  # Can't drop more than 25%
    
    def test_tally_votes_backward_compat(self):
        from src.council.protocol import tally_votes
        votes = [{"agent": "a1", "direction": "bullish", "confidence": 0.8}]
        result = tally_votes(votes)
        # Should return old-format keys for backward compat
        assert "consensus" in result or "_v2" in result


# ── engine.py tests ───────────────────────────────────────────

class TestEngine:
    def test_init_creates_tables(self, council_db):
        from src.council.engine import init_council_tables
        init_council_tables(council_db)
        conn = sqlite3.connect(council_db)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'council%'"
        ).fetchall()]
        assert "council_sessions" in tables
        assert "council_votes" in tables
        assert "council_calibrations" in tables
        assert "council_debug_log" in tables
    
    def test_init_adds_v2_columns(self, council_db):
        from src.council.engine import init_council_tables
        init_council_tables(council_db)
        conn = sqlite3.connect(council_db)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(council_votes)").fetchall()]
        assert "direction" in cols
        assert "confidence_float" in cols
        assert "assessment_json" in cols
        cols2 = [r[1] for r in conn.execute("PRAGMA table_info(council_sessions)").fetchall()]
        assert "result_json" in cols2
    
    def test_cost_estimation(self):
        from src.council.engine import _estimate_session_cost
        cost_1 = _estimate_session_cost(1)
        cost_2 = _estimate_session_cost(2)
        assert cost_2 > cost_1
        assert cost_1 > 0


# ── value_tracker.py tests ────────────────────────────────────

class TestValueTracker:
    def test_get_current_parameters_defaults_on_empty(self, council_db):
        from src.council.value_tracker import get_current_parameters, init_value_tables
        init_value_tables(council_db)
        params = get_current_parameters(council_db)
        assert "position_sizing_multiplier" in params
        assert params["position_sizing_multiplier"] == 1.0
    
    def test_log_parameter_change(self, council_db):
        from src.council.value_tracker import log_parameter_change, init_value_tables
        init_value_tables(council_db)
        log_id = log_parameter_change(
            session_id="test-session",
            parameter_name="position_sizing_multiplier",
            default_value=1.0,
            council_value=0.8,
            applied_value=0.85,
            rate_limited=True,
            db_path=council_db,
        )
        assert log_id  # non-empty string
        
        conn = sqlite3.connect(council_db)
        row = conn.execute("SELECT * FROM council_parameter_log WHERE log_id = ?", (log_id,)).fetchone()
        assert row is not None
    
    def test_rolling_summary_empty_db(self, council_db):
        from src.council.value_tracker import get_rolling_value_summary, init_value_tables
        init_value_tables(council_db)
        summary = get_rolling_value_summary(db_path=council_db)
        assert summary["authority_status"] == "full"
        assert summary["total_value_added"] == 0.0
```

Adapt this template — add more tests if gaps are found while reading the source.
Target: ALL council tests pass. Zero failures.

## Task 3: Render sync for new tables

Read `src/sync/render_sync.py` IN FULL. Add these tables to the sync list:
- `traffic_light_state`
- `council_calibrations`
- `council_debug_log`
- `council_parameter_log`
- `council_parameter_state`
- `validation_results`

Add new columns to existing synced tables:
- `shadow_trades.signal_price`, `shadow_trades.implementation_shortfall_bps`
- `council_sessions.result_json`
- `council_votes.direction`, `council_votes.confidence_float`, `council_votes.assessment_json`

Update `scripts/render_migrate.py` with CREATE TABLE and ALTER TABLE for Postgres.

## Task 4: Audit quick-fixes (GitHub Issues #30, #31, #32, #33, #37)

- **#30** `src/api/routes/system.py` line ~291: bare `except:` → `except Exception as e: logger.warning(f"data_collection_stats error: {e}")`
- **#31** `src/api/websocket.py` line ~46: `broadcast_sync()` bare except → add `logger.warning`
- **#32** `src/api/cloud_app.py` line ~609: fix incorrect type annotation on `activity_feed` parameter
- **#33** Delete `src/council/agents_v1_backup.py`, `src/council/engine_v1_backup.py`, `src/council/protocol_v1_backup.py`
- **#37** `src/data_collection/edgar_collector.py` line ~96: delete dead code `_fetch_recent_filings()`

## Task 5: Strategy-specific holding period timeouts

**Research finding:** Pullback alpha concentrates in days 1-5 (80-85% of edge).

1. In `config/settings.example.yaml`, change:
```yaml
shadow_trading:
  timeout_days:
    pullback: 7
    mean_reversion: 5
    pead: 10
    default: 10
```

2. Add column if not present:
```sql
ALTER TABLE shadow_trades ADD COLUMN strategy_type TEXT DEFAULT 'pullback';
```

3. In `src/shadow_trading/executor.py`:
   - When opening trades, store `strategy_type='pullback'`
   - When checking timeouts, look up per-strategy timeout from config
   - Fallback to `timeout_days.default` if strategy not in config

## Task 6: Create `scripts/verify_counts.py`

Script that compares AGENTS.md line 1 counts against actual code:
```python
"""Verify AGENTS.md counts match code reality."""
import subprocess, re, sys

# Count actual
py_files = int(subprocess.check_output("find src -name '*.py' ! -path '*__pycache__*' ! -name '*backup*' | wc -l", shell=True))
test_files = int(subprocess.check_output("find tests -name '*.py' | wc -l", shell=True))
# ... etc for CLI commands, DB tables, research docs

# Parse AGENTS.md line 1
with open("AGENTS.md") as f:
    line1 = f.readline()

# Compare and report
# Exit 0 if all match, exit 1 if any mismatch
```

## Task 7: Create `scripts/schema_report.py`

Script that introspects SQLite and generates `docs/schema.md`:
```python
"""Generate canonical database schema documentation."""
import sqlite3

conn = sqlite3.connect("ai_research_desk.sqlite3")
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()

with open("docs/schema.md", "w") as f:
    f.write("# Database Schema Report\n\n")
    for (table,) in tables:
        cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        f.write(f"## {table} ({count} rows)\n")
        for col in cols:
            f.write(f"- {col[1]} ({col[2]})\n")
        f.write("\n")
```

## Task 8: All tests pass + frontend builds
```bash
python -m pytest tests/ -v --tb=short   # ALL pass, ZERO failures
cd frontend && npm run build && cd ..   # builds clean
python scripts/verify_counts.py         # counts match (update AGENTS.md if needed)
```

## Task 9: Update AGENTS.md counts
Run verify_counts.py. If any mismatches, update AGENTS.md line 1 to match reality.

## Task 10: Commit and push
```bash
git add -A
git commit -m "sprint 1: stabilize — council tests, render sync, logger, audit fixes, timeouts

- Council v2 tests rewritten (30+ tests for agents, protocol, engine, value_tracker)
- Render sync updated for 6 new tables + 6 new columns
- RotatingFileHandler added (logs/halcyon.log, 10MB × 7)
- Audit quick-fixes: #30, #31, #32, #33, #37
- Strategy-specific timeouts: pullback 7d (was 15)
- scripts/verify_counts.py + schema_report.py
- AGENTS.md counts verified and corrected
- All tests pass, frontend builds"

git push origin main
```

---

## Sprint Documentation Checklist
- [ ] AGENTS.md counts match (verified by script)
- [ ] CHANGELOG.md — sprint 1 entry
- [ ] docs/schema.md generated
- [ ] All tests pass
- [ ] Frontend builds
- [ ] No orphaned imports
