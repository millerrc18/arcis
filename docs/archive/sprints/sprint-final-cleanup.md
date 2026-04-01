# Sprint: Final Cleanup — Everything Verified Before Bed
# Every broken thing fixed, every older feature verified, every gap closed.

> **CRITICAL ITEMS (will break if not fixed):**
> 1. test_council.py — 15 tests reference DELETED functions, WILL FAIL
> 2. Render sync — cloud dashboard BLIND to all new tables/columns
> 3. Logger — no file rotation, crash evidence LOST
> 4. Council.jsx — old agent names in dissent detection
>
> **Pre-read (mandatory, IN FULL):**
> ```
> cat AGENTS.md
> cat src/council/agents.py
> cat src/council/protocol.py
> cat src/council/engine.py
> cat src/council/value_tracker.py
> cat src/scheduler/watch.py
> cat src/sync/render_sync.py
> cat src/notifications/telegram.py
> cat src/main.py
> cat src/features/traffic_light.py
> cat src/data_enrichment/earnings_signals.py
> cat src/evaluation/hshs_live.py
> cat src/evaluation/system_validator.py
> cat src/shadow_trading/executor.py
> cat src/risk/governor.py
> cat src/services/scan_service.py
> cat src/features/engine.py
> cat src/ranking/ranker.py
> cat src/packets/template.py
> cat src/training/trainer.py
> cat src/email/notifier.py
> cat config/settings.example.yaml
> cat docs/architecture.md
> cat docs/roadmap.md
> cat tests/test_council.py
> cat frontend/src/pages/Council.jsx
> cat frontend/src/App.jsx
> cat frontend/src/api.js
> ```
>
> **Run `python -m pytest tests/ -x -q` first. Council tests WILL fail. That's expected.**

---

# ══════════════════════════════════════════════════════════════
# PART 0: CRITICAL FIXES (do these first)
# ══════════════════════════════════════════════════════════════

## 0A. Rewrite tests/test_council.py for v2

The existing test file references deleted functions and old schema. Read the NEW
agents.py, protocol.py, engine.py, and value_tracker.py IN FULL before rewriting.

**Deleted functions that tests reference:**
- `gather_risk_officer_data` → now `gather_risk_data`
- `gather_alpha_strategist_data` → now `gather_tactical_data`
- `gather_data_scientist_data` → now `gather_innovation_data`
- `gather_regime_analyst_data` → now `gather_macro_data`
- `gather_devils_advocate_data` → DELETED (all agents run independently)
- `run_round_3` → DELETED (max 2 rounds)

**Schema changes tests must reflect:**
- `position` (defensive/neutral/offensive) → `direction` (bullish/neutral/bearish)
- `confidence` (1-10 int) → `confidence` (0.0-1.0 float)
- `vote` (reduce/hold/increase/selective) → mapped via backward compat
- Data functions return STRING not dict

**Required test coverage:**
```python
# agents.py
- All 5 gather functions return non-empty strings on populated DB
- All 5 gather functions return fallback string on empty/broken DB
- All 5 gather functions never raise exceptions
- AGENT_NAMES has exactly 5 entries
- AGENT_DATA_FUNCTIONS has exactly 5 entries
- _query_db helper works

# protocol.py
- _parse_agent_response: valid JSON → correct fields
- _parse_agent_response: code-fenced JSON → strips fences
- _parse_agent_response: JSON buried in prose → extracted
- _parse_agent_response: old schema (position, confidence 1-10) → auto-converted
- _parse_agent_response: garbage → _default_response with _parse_failed
- aggregate_votes: 5 bullish → consensus_reached=True, round2_needed=False
- aggregate_votes: 2-2-1 → consensus_reached=False, round2_needed=True
- aggregate_votes: 3-2 → consensus_reached=True
- apply_rate_limiters: >25% daily change → clipped
- apply_rate_limiters: within bounds → not clipped
- tally_votes backward compat: returns old format with _v2 key

# engine.py
- init_council_tables creates all tables (council_sessions, votes, calibrations, debug_log)
- New columns exist (result_json, direction, confidence_float, assessment_json)

# value_tracker.py
- log_parameter_change stores entry and closes previous window
- compute_attribution: sizing multiplier counterfactual correct
- get_rolling_value_summary: counts consecutive negative weeks
- get_current_parameters: returns defaults on empty DB
```

## 0B. Render sync for new tables

Read `src/sync/render_sync.py` in full. Add ALL new tables to the sync list:
- `traffic_light_state`
- `council_calibrations`
- `council_debug_log`
- `council_parameter_log`
- `council_parameter_state`
- `validation_results`

Also ensure new COLUMNS on existing tables are synced:
- `shadow_trades.signal_price`, `shadow_trades.implementation_shortfall_bps`
- `council_sessions.result_json`
- `council_votes.direction`, `council_votes.confidence_float`, `council_votes.assessment_json`

Update `scripts/render_migrate.py` with CREATE TABLE + ALTER TABLE for Postgres.

## 0C. File logging with rotation

In `src/scheduler/watch.py`, add RotatingFileHandler:
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

Add `logs/` to `.gitignore`.

## 0D. Fix Council.jsx

1. Replace `devils_advocate` dissent detection:
```jsx
// OLD: agent.role === 'devils_advocate' || agent.is_dissenter || agent.is_devils_advocate
// NEW: agent.is_dissenter || agent.direction !== consensusDirection
```

2. Add new agent label/emoji mappings (tactical_operator→⚡, strategic_architect→🏗️,
   red_team→🔴, innovation_engine→💡, macro_navigator→🌍)

3. Replace `position` display with `direction` (bullish/neutral/bearish)

4. Remove any `round3` references

5. `npm run build` must succeed

---

# ══════════════════════════════════════════════════════════════
# PART 1: VERIFY OLDER UNTOUCHED FEATURES
# ══════════════════════════════════════════════════════════════

These components were NOT touched by either sprint. Verify they still work.

## 1A. Feature engine

```python
from src.features.engine import compute_all_features
print("Feature engine imports OK ✓")
# Verify it references regime.py, earnings.py correctly
```

```bash
grep "from src" src/features/engine.py | head -10
# Verify no imports of deleted modules
```

## 1B. Ranking pipeline

```python
from src.ranking.ranker import rank_universe, get_top_candidates
print("Ranking imports OK ✓")
```

## 1C. Position sizing / packets

```python
from src.packets.template import build_packet_from_features, render_packet
print("Packet builder imports OK ✓")
```

## 1D. Email notifications

```python
from src.email.notifier import send_email
print("Email notifier imports OK ✓")
```

## 1E. AuthGate (cloud authentication)

```bash
grep "AuthGate" frontend/src/App.jsx
# Verify it's still wrapping the routes
```

## 1F. Alpaca adapter

```python
from src.shadow_trading.alpaca_adapter import get_current_price, submit_bracket_order
print("Alpaca adapter imports OK ✓")
```

## 1G. Saturday retrain pipeline

```python
from src.training.trainer import run_training_pipeline
print("Training pipeline imports OK ✓")
```

```bash
python -m src.main train-pipeline --help
# Must show help text, not crash
```

## 1H. CTO report

```python
from src.evaluation.cto_report import generate_cto_report
print("CTO report imports OK ✓")
```

## 1I. Setup classifier

```python
from src.features.setup_classifier import classify_setup
print("Setup classifier imports OK ✓")
```

## 1J. Data integrity

```python
from src.data_integrity import validate_features
print("Data integrity imports OK ✓")
```

## 1K. Full dry-run scan

```bash
python -m src.main scan --verbose --dry-run 2>&1 | tee /tmp/scan_verify.log
```

**Verify in output:**
- Universe loads (90+ tickers)
- Features computed
- Enrichment runs (fundamentals, insiders, news, macro, PEAD earnings)
- Traffic Light computed (score, multiplier, regime)
- Ranking produces candidates
- LLM commentary generated (NOT 100% fallback)
- Signal prices captured
- No crashes, no unhandled exceptions

---

# ══════════════════════════════════════════════════════════════
# PART 2: DOCUMENTATION
# ══════════════════════════════════════════════════════════════

## 2A. docs/architecture.md — full rewrite

Add all new modules, deleted modules, new tables, new columns, new API endpoints,
data flow changes. See section 1.2 of previous sprint draft for complete list.

## 2B. docs/roadmap.md — confirmed strategy decisions

Add: Strategy #2 = Mean Reversion (Phase 2), Strategy #3 = Evolved PEAD (Phase 3),
RL = Dr. GRPO, Traffic Light built ✓, Council v2 deployed ✓.

## 2C. AGENTS.md — exact counts

Run count commands and update line 1 to match reality.

## 2D. config/settings.example.yaml

Add execution config section (order_type, limit_timeout_seconds).

---

# ══════════════════════════════════════════════════════════════
# PART 3: FINAL GATE
# ══════════════════════════════════════════════════════════════

```bash
echo "=== FINAL GATE ===" 
python -m pytest tests/ -v --tb=short 2>&1 | tail -15
cd frontend && npm run build 2>&1 | tail -3 && cd ..
echo ""
echo "Orphaned imports:"
grep -rn "from src.scheduler.overnight\|from src.shadow_trading.broker\|protocol_v2\|agents_v2" src/ tests/ --include="*.py" | grep -v backup | grep -v __pycache__
echo "(must be empty)"
echo ""
echo "Old agent names in active code:"  
grep -rn "risk_officer\|alpha_strategist\|data_scientist\|regime_analyst\|devils_advocate" src/ frontend/src/ tests/ --include="*.py" --include="*.jsx" | grep -v backup | grep -v __pycache__ | grep -v node_modules | grep -v "is_devils_advocate\|# " 
echo "(must be empty or only schema column references)"
```

ALL tests pass. Frontend builds. No orphaned imports. No old agent names.

---

# Sprint Documentation Checklist (docs/sprint-checklist.md)

### Tier 1 (MANDATORY):
- [ ] AGENTS.md counts match
- [ ] CHANGELOG.md — cleanup sprint entry
- [ ] docs/architecture.md — full update
- [ ] All tests pass
- [ ] Frontend builds
- [ ] File logging configured
- [ ] Render sync updated
- [ ] Council.jsx updated
- [ ] Council tests rewritten and passing
