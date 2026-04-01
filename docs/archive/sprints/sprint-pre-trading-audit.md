# Sprint: Pre-Trading-Week Comprehensive Audit
# ZERO TOLERANCE — Every component verified end-to-end

> **Context:** Two major sprints just landed (reliability + features). The system has
> ~25 open positions and is about to enter its first full week of monitored trading.
> This audit verifies EVERYTHING works before Monday's market open.
>
> **Approach:** This is NOT a build sprint. Do NOT write new features. Do NOT refactor.
> The ONLY acceptable code changes are:
> 1. Fixing bugs found during verification
> 2. Adding missing tests for untested paths
> 3. Fixing documentation that doesn't match code
>
> **Pre-read (mandatory):**
> ```
> cat AGENTS.md
> cat CHANGELOG.md
> cat docs/audit_comprehensive_2026-03-28.md
> cat src/services/scan_service.py
> cat src/risk/governor.py
> cat src/shadow_trading/executor.py
> cat src/scheduler/watch.py
> cat src/features/traffic_light.py
> cat src/data_enrichment/earnings_signals.py
> cat src/evaluation/hshs_live.py
> cat src/evaluation/system_validator.py
> cat src/journal/store.py
> cat src/training/trainer.py
> cat src/council/engine.py
> cat src/notifications/telegram.py
> cat config/settings.example.yaml
> ```
>
> **For each section:** Run the verification, record PASS/FAIL, fix any FAIL immediately.
> At the end, produce a complete audit report.

---

# ══════════════════════════════════════════════════════════════
# SECTION 1: DATABASE INTEGRITY
# ══════════════════════════════════════════════════════════════

## 1.1 Verify all tables exist

Run `initialize_database()` from `src/journal/store.py` and verify every expected table:

```python
import sqlite3
from src.journal.store import initialize_database

initialize_database()
conn = sqlite3.connect("ai_research_desk.sqlite3")
tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
print(f"Tables ({len(tables)}):")
for t in tables:
    count = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"  {t}: {count} rows")
```

**Expected tables (minimum 38):** recommendations, shadow_trades, training_examples, model_versions, scan_metrics, council_sessions, council_votes, council_calibrations, macro_snapshots, insider_transactions, analyst_estimates, edgar_filings, short_interest, options_chains, vix_term_structure, earnings_calendar, google_trends, economic_calendar, sector_rotation, data_asset_metrics, activity_log, daily_metrics, validation_results, api_costs, halt_state, market_events, research_papers, training_scores, quality_audits, weekly_audits, traffic_light_state, user_notes

**Verify new columns exist:**
```python
# Implementation Shortfall columns
cols = [r[1] for r in conn.execute("PRAGMA table_info(shadow_trades)").fetchall()]
assert "signal_price" in cols, "MISSING: shadow_trades.signal_price"
assert "implementation_shortfall_bps" in cols, "MISSING: shadow_trades.implementation_shortfall_bps"

# Council result_json column
cols = [r[1] for r in conn.execute("PRAGMA table_info(council_sessions)").fetchall()]
assert "result_json" in cols, "MISSING: council_sessions.result_json"

print("All new columns verified ✓")
```

## 1.2 Verify database indexes

```python
indexes = conn.execute("SELECT name, tbl_name FROM sqlite_master WHERE type='index'").fetchall()
print(f"Indexes ({len(indexes)}):")
for idx, tbl in indexes:
    print(f"  {idx} on {tbl}")
```

Verify at minimum: idx_shadow_trades_status, idx_recommendations_ticker, idx_council_votes_session, idx_council_sessions_created, idx_scan_metrics_created.

## 1.3 Verify WAL mode

```python
mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
assert mode == "wal", f"Expected WAL mode, got {mode}"
print(f"Journal mode: {mode} ✓")
```

## 1.4 Verify no orphaned data

```python
# Shadow trades with no recommendation
orphaned = conn.execute(
    "SELECT COUNT(*) FROM shadow_trades WHERE recommendation_id IS NOT NULL "
    "AND recommendation_id NOT IN (SELECT rec_id FROM recommendations WHERE rec_id IS NOT NULL)"
).fetchone()[0]
print(f"Orphaned shadow trades: {orphaned} {'✓' if orphaned == 0 else '⚠️ INVESTIGATE'}")

# Council votes with no session
orphaned_votes = conn.execute(
    "SELECT COUNT(*) FROM council_votes WHERE session_id NOT IN (SELECT session_id FROM council_sessions)"
).fetchone()[0]
print(f"Orphaned council votes: {orphaned_votes} {'✓' if orphaned_votes == 0 else '⚠️ INVESTIGATE'}")
```

---

# ══════════════════════════════════════════════════════════════
# SECTION 2: SAFETY SYSTEMS (most critical — verify first)
# ══════════════════════════════════════════════════════════════

## 2.1 Risk governor rejects on exception

```python
from src.risk.governor import RiskGovernor, compute_current_drawdown

# Test 1: Governor rejects when check_trade() throws
config = {"risk_governor": {"enabled": True}}
governor = RiskGovernor(config)

# Simulate exception by passing invalid portfolio
try:
    result = governor.check_trade("TEST", 1000.0, {}, None)  # None portfolio → exception in equity check
except Exception:
    pass  # If it raises, that's acceptable

# Verify: the code path in executor.py catches and returns None
# Read executor.py lines 65-82 to verify the except block returns None, not continues
```

**MANUAL VERIFICATION:** Open `src/shadow_trading/executor.py` and confirm:
- Line ~68-82: Risk governor `except Exception` block has `return None` (NOT `logger.warning ... continue`)
- Line ~58-63: LLM validator `except Exception` block has `return None` (NOT `pass`)

## 2.2 Drawdown returns conservative on error

```python
# Force an error by using a non-existent DB path
dd = compute_current_drawdown(db_path="/nonexistent/path.sqlite3")
assert dd == 15.0, f"Expected 15.0 conservative estimate, got {dd}"
print(f"Drawdown on error: {dd}% (conservative estimate) ✓")
```

## 2.3 Kill switch works

```python
from src.risk.governor import _is_halted

# Verify kill switch table exists and is queryable
import sqlite3
with sqlite3.connect("ai_research_desk.sqlite3") as conn:
    halted = _is_halted()
    print(f"Kill switch active: {halted} (should be False for normal operation) ✓")
```

## 2.4 No bare except:pass remaining in safety code

```bash
echo "=== Bare except:pass in SAFETY-CRITICAL files ==="
for f in src/risk/governor.py src/shadow_trading/executor.py src/llm/validator.py; do
    count=$(grep -c "except.*:" "$f" 2>/dev/null | head -1)
    passes=$(grep -A1 "except.*:" "$f" 2>/dev/null | grep -c "pass" | head -1)
    echo "$f: $count except blocks, $passes with bare pass"
done
echo ""
echo "=== All files with bare except:pass ==="
grep -rn "except.*:$" src/ --include="*.py" -A1 | grep "pass$" | grep -v "__pycache__"
```

**ZERO bare except:pass allowed in risk, executor, validator, governor files.**

## 2.5 Traffic Light multiplier applied correctly

```python
from src.risk.governor import RiskGovernor

config = {"risk_governor": {"enabled": True, "max_position_pct": 0.10, "max_open_positions": 50}}
governor = RiskGovernor(config)

# Simulate with Traffic Light multiplier = 0.5
portfolio = {"equity": 100000, "daily_pnl_pct": 0, "open_count": 5, "sector_exposure": {}, "open_positions": []}
result = governor.check_trade("AAPL", 5000.0, {"sector": "Technology"}, portfolio, traffic_light_multiplier=0.5)

# The allocation should be halved: $5000 * 0.5 = $2500
# Check that the traffic_light check appears in the checks list
tl_check = [c for c in result["checks"] if c["name"] == "traffic_light"]
assert len(tl_check) == 1, "Traffic Light check not found in governor checks"
assert "2500" in tl_check[0]["detail"] or "$2,500" in tl_check[0]["detail"], f"Expected halved allocation in detail: {tl_check[0]['detail']}"
print(f"Traffic Light multiplier applied: {tl_check[0]['detail']} ✓")
```

---

# ══════════════════════════════════════════════════════════════
# SECTION 3: TRADE LIFECYCLE (end-to-end)
# ══════════════════════════════════════════════════════════════

## 3.1 Scan pipeline dry run

```bash
python -m src.main scan --verbose --dry-run 2>&1 | tee /tmp/scan_audit.log
```

**Verify in output:**
- [ ] Universe loaded (should be ~100 stocks)
- [ ] Features computed for 90+ tickers
- [ ] Enrichment ran (fundamental, insider, news, macro, earnings signals)
- [ ] Traffic Light computed (score, multiplier, regime)
- [ ] Ranking produced candidates
- [ ] Packet-worthy tickers identified with scores
- [ ] LLM generated commentary (NOT "template fallback" for every ticker)
- [ ] Signal price captured for each candidate

```bash
# Check for Traffic Light in scan output
grep -i "traffic light\|traffic_light" /tmp/scan_audit.log
# Check for PEAD earnings context
grep -i "earnings context\|earnings_signals\|include_in_prompt" /tmp/scan_audit.log
# Check for IS signal price
grep -i "signal_price\|implementation shortfall" /tmp/scan_audit.log
```

## 3.2 Verify open positions have bracket protection

```python
import sqlite3
conn = sqlite3.connect("ai_research_desk.sqlite3")

open_trades = conn.execute(
    "SELECT trade_id, ticker, status, stop_price, target_1, alpaca_order_id "
    "FROM shadow_trades WHERE status = 'open'"
).fetchall()

print(f"Open positions: {len(open_trades)}")
for t in open_trades:
    trade_id, ticker, status, stop, target, alpaca_id = t
    issues = []
    if not stop: issues.append("NO STOP")
    if not target: issues.append("NO TARGET")
    if not alpaca_id: issues.append("NO ALPACA ORDER")
    status_str = " ⚠️ " + ", ".join(issues) if issues else " ✓"
    print(f"  {ticker}: stop=${stop} target=${target} alpaca={alpaca_id[:8] if alpaca_id else 'NONE'}{status_str}")
```

**EVERY open position must have stop_price, target_1, AND alpaca_order_id.**

## 3.3 Verify trade exit monitoring

```python
# Check that check_and_manage_open_trades runs without error
from src.shadow_trading.executor import check_and_manage_open_trades

# Paper trades
actions = check_and_manage_open_trades(source_filter=None)
print(f"Trade management actions: {len(actions)}")
for a in actions[:5]:
    print(f"  {a}")

# Independent live trade check
live_actions = check_and_manage_open_trades(source_filter="live")
print(f"Live trade actions: {len(live_actions)}")
```

## 3.4 Verify Implementation Shortfall tracking

```python
import sqlite3
conn = sqlite3.connect("ai_research_desk.sqlite3")

# Check if any trades have IS data
is_trades = conn.execute(
    "SELECT ticker, signal_price, actual_entry_price, implementation_shortfall_bps "
    "FROM shadow_trades WHERE signal_price IS NOT NULL LIMIT 5"
).fetchall()

if is_trades:
    print(f"Trades with IS data: {len(is_trades)}")
    for t in is_trades:
        print(f"  {t[0]}: signal=${t[1]:.2f} fill=${t[2]:.2f} IS={t[3]:.1f}bps")
else:
    print("No IS data yet (expected — only captures on new trades) ✓")
```

---

# ══════════════════════════════════════════════════════════════
# SECTION 4: TRAINING PIPELINE
# ══════════════════════════════════════════════════════════════

## 4.1 Train pipeline CLI verification

```bash
python -m src.main train-pipeline --help
```

**Verify:** Command exists and shows 5-step description (not empty stub).

## 4.2 Training data integrity

```python
import sqlite3
conn = sqlite3.connect("ai_research_desk.sqlite3")

# Count and distribution
total = conn.execute("SELECT COUNT(*) FROM training_examples").fetchone()[0]
by_stage = conn.execute(
    "SELECT curriculum_stage, COUNT(*) FROM training_examples GROUP BY curriculum_stage"
).fetchall()
by_source = conn.execute(
    "SELECT source, COUNT(*) FROM training_examples GROUP BY source"
).fetchall()
scored = conn.execute(
    "SELECT COUNT(*) FROM training_examples WHERE quality_score IS NOT NULL AND quality_score > 0"
).fetchone()[0]

print(f"Total training examples: {total}")
print(f"By stage: {dict(by_stage)}")
print(f"By source: {dict(by_source)}")
print(f"Quality scored: {scored}/{total} ({scored/total*100:.0f}%)")

# Check for format issues (the root cause of the 62% fallback disaster)
# Sample 10 random examples and verify XML format
samples = conn.execute(
    "SELECT output_text FROM training_examples ORDER BY RANDOM() LIMIT 10"
).fetchall()
xml_ok = 0
for s in samples:
    text = s[0] or ""
    has_why = "<why_now>" in text and "</why_now>" in text
    has_analysis = "<analysis>" in text and "</analysis>" in text
    has_metadata = "<metadata>" in text and "</metadata>" in text
    if has_why and has_analysis and has_metadata:
        xml_ok += 1
    else:
        print(f"  ⚠️ NON-XML example found: {text[:100]}...")

print(f"XML format: {xml_ok}/10 sampled {'✓' if xml_ok >= 8 else '⚠️ FORMAT ISSUE'}")
```

## 4.3 Canary evaluation wired

```bash
grep -n "from src.training.canary import" src/training/trainer.py
```

**Verify:** canary is imported and called AFTER model training, BEFORE model promotion.

## 4.4 Leakage detector functional

```python
# Verify the leakage detector module exists and is importable
from src.training.leakage_detector import check_outcome_leakage
print("Leakage detector importable ✓")
```

---

# ══════════════════════════════════════════════════════════════
# SECTION 5: TRAFFIC LIGHT SYSTEM
# ══════════════════════════════════════════════════════════════

## 5.1 Verify thresholds match research

```python
from src.features.traffic_light import _classify_vix, _classify_trend, _classify_credit

# VIX: research says <20 green, 20-30 yellow, >30 red
assert _classify_vix(19.0) == 0, "VIX 19 should be green"
assert _classify_vix(20.0) == 1, "VIX 20 should be yellow"
assert _classify_vix(30.0) == 1, "VIX 30 should be yellow"
assert _classify_vix(31.0) == 2, "VIX 31 should be red"
print("VIX thresholds: 20/30 ✓")

# Verify RED multiplier is 0.1 (not 0.0)
from src.features.traffic_light import _regime_to_multiplier
assert _regime_to_multiplier("RED") == 0.1, f"RED should be 0.1, got {_regime_to_multiplier('RED')}"
print("RED multiplier: 0.1 (not 0.0) ✓")
```

## 5.2 Verify persistence filter

```python
# Verify persistence threshold is 5 (not 2)
import inspect
from src.features import traffic_light
source = inspect.getsource(traffic_light)
assert ">= 5" in source or ">=5" in source, "Persistence should require 5 consecutive readings"
assert ">= 2" not in source.replace(">= 20", ""), "Old persistence threshold (2) should not be present"
print("Persistence threshold: 5 ✓")
```

## 5.3 Live Traffic Light computation

```python
from src.features.traffic_light import compute_traffic_light
from src.data_ingestion.market_data import fetch_spy_benchmark

spy = fetch_spy_benchmark()
result = compute_traffic_light(spy=spy)
print(f"Live Traffic Light:")
print(f"  VIX score: {result.get('vix_score')} ({result.get('vix_value', '?')})")
print(f"  Trend score: {result.get('trend_score')}")
print(f"  Credit score: {result.get('credit_score')}")
print(f"  Total: {result.get('total_score')}/6 → {result.get('regime_label')} (×{result.get('sizing_multiplier')})")
```

## 5.4 Verify Traffic Light wired into scan

```bash
grep -n "traffic_light" src/services/scan_service.py
grep -n "traffic_light_multiplier" src/shadow_trading/executor.py
grep -n "traffic_light_multiplier" src/risk/governor.py
```

**All three files must reference Traffic Light.**

---

# ══════════════════════════════════════════════════════════════
# SECTION 6: PEAD ENRICHMENT
# ══════════════════════════════════════════════════════════════

## 6.1 Earnings signals module functional

```python
from src.data_enrichment.earnings_signals import compute_earnings_signals

# Test with a real S&P 100 ticker
result = compute_earnings_signals("AAPL")
print(f"AAPL earnings signals:")
for k, v in result.items():
    print(f"  {k}: {v}")
```

## 6.2 Wired into enrichment pipeline

```bash
grep -n "earnings_signals" src/data_enrichment/enricher.py
```

**Verify:** `compute_earnings_signals` called for each ticker in the enrichment loop.

## 6.3 Conditional prompt inclusion

```bash
grep -n "include_in_prompt\|EARNINGS CONTEXT" src/llm/packet_writer.py
```

**Verify:** Earnings context section is conditional on `include_in_prompt == True`.

---

# ══════════════════════════════════════════════════════════════
# SECTION 7: HSHS LIVE HEALTH SCORE
# ══════════════════════════════════════════════════════════════

## 7.1 HSHS computation

```python
from src.evaluation.hshs_live import compute_hshs

result = compute_hshs()
print(f"HSHS: {result.get('hshs', 0):.1f}/100 (phase: {result.get('phase')})")
for dim, val in result.get("dimensions", {}).items():
    weight = result.get("weights", {}).get(dim, 0)
    print(f"  {dim}: {val:.1f}/100 (weight: {weight:.0%})")
```

## 7.2 Wired into CTO report

```bash
grep -n "hshs\|HSHS" src/evaluation/cto_report.py
```

## 7.3 Wired into council

```bash
grep -n "hshs\|HSHS" src/council/protocol.py
```

## 7.4 API endpoint exists

```bash
grep -n "hshs" src/api/cloud_app.py
```

---

# ══════════════════════════════════════════════════════════════
# SECTION 8: DATA COLLECTION PIPELINE
# ══════════════════════════════════════════════════════════════

## 8.1 Verify all 12 collectors

For each collector, verify the module exists, is importable, and the target table has recent data:

```python
import sqlite3
from datetime import datetime, timedelta

conn = sqlite3.connect("ai_research_desk.sqlite3")
cutoff = (datetime.utcnow() - timedelta(days=3)).isoformat()

collectors = [
    ("macro_collector", "macro_snapshots", "date"),
    ("insider_collector", "insider_transactions", "created_at"),
    ("edgar_collector", "edgar_filings", "created_at"),
    ("short_interest_collector", "short_interest", "created_at"),
    ("options_collector", "options_chains", "created_at"),
    ("vix_collector", "vix_term_structure", "date"),
    ("earnings_collector", "earnings_calendar", "created_at"),
    ("google_trends_collector", "google_trends", "created_at"),
    ("sector_rotation_collector", "sector_rotation", "created_at"),
    ("economic_calendar_collector", "economic_calendar", "created_at"),
    ("news_collector", "market_events", "created_at"),
    ("analyst_collector", "analyst_estimates", "created_at"),
]

for name, table, time_col in collectors:
    try:
        total = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        recent = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {time_col} > ?", (cutoff,)).fetchone()[0]
        status = "✓" if recent > 0 else "⚠️ NO RECENT DATA"
        print(f"  {name}: {total} total, {recent} in last 3 days {status}")
    except Exception as e:
        print(f"  {name}: ❌ ERROR: {e}")
```

---

# ══════════════════════════════════════════════════════════════
# SECTION 9: TELEGRAM NOTIFICATIONS
# ══════════════════════════════════════════════════════════════

## 9.1 Count notification functions

```bash
echo "Notification functions defined:"
grep -c "^def notify_" src/notifications/telegram.py

echo ""
echo "Notification functions CALLED in watch.py:"
grep -o "notify_[a-z_]*" src/scheduler/watch.py | sort -u | wc -l

echo ""
echo "Functions defined but NOT called:"
comm -23 \
    <(grep "^def notify_" src/notifications/telegram.py | sed 's/def //;s/(.*//' | sort) \
    <(grep -o "notify_[a-z_]*" src/scheduler/watch.py | sort -u)
```

**ZERO uncalled notification functions.**

## 9.2 Test Telegram connectivity

```bash
python -m src.main send-test-telegram 2>&1
```

---

# ══════════════════════════════════════════════════════════════
# SECTION 10: DASHBOARD & FRONTEND
# ══════════════════════════════════════════════════════════════

## 10.1 Frontend builds

```bash
cd frontend && npm run build 2>&1 | tail -5
```

**Must succeed with zero errors.**

## 10.2 All pages registered

```bash
grep "Route.*path=" frontend/src/App.jsx
```

**Expected routes:** /, /packets, /shadow, /training, /live, /cto-report, /settings, /roadmap, /docs, /council, /health, /validation, /notes

## 10.3 All API endpoints accessible

```bash
grep "@app.get\|@app.post\|@app.put\|@app.delete" src/api/cloud_app.py | wc -l
```

**Verify count matches AGENTS.md.**

---

# ══════════════════════════════════════════════════════════════
# SECTION 11: SYSTEM VALIDATOR
# ══════════════════════════════════════════════════════════════

## 11.1 Run full validation

```bash
python -m src.main validate-system 2>&1 | tee /tmp/validation_audit.log
```

**Review every FAIL and WARNING.** Document each one.

---

# ══════════════════════════════════════════════════════════════
# SECTION 12: TESTS
# ══════════════════════════════════════════════════════════════

## 12.1 All tests pass

```bash
python -m pytest tests/ -v --tb=short 2>&1 | tee /tmp/test_audit.log
echo ""
echo "=== SUMMARY ==="
tail -20 /tmp/test_audit.log
```

**ZERO failures. ZERO errors. All tests pass.**

## 12.2 Test coverage for new modules

```bash
echo "=== New module test coverage ==="
echo "Traffic Light:"
grep -c "def test_" tests/test_traffic_light.py 2>/dev/null || echo "NO TESTS"
echo "Earnings Signals:"
grep -c "def test_" tests/test_earnings_signals.py 2>/dev/null || echo "NO TESTS"
echo "HSHS Live:"
grep -c "def test_" tests/test_hshs_live.py 2>/dev/null || echo "NO TESTS"
echo "System Validator:"
grep -c "def test_" tests/test_system_validator.py 2>/dev/null || echo "NO TESTS"
```

---

# ══════════════════════════════════════════════════════════════
# SECTION 13: DOCUMENTATION ACCURACY
# ══════════════════════════════════════════════════════════════

## 13.1 AGENTS.md counts match code

Run these commands and compare to AGENTS.md line 1:

```bash
echo "Python files:" && find src -name "*.py" ! -path "*__pycache__*" | wc -l
echo "Test files:" && find tests -name "*.py" | wc -l
echo "Tests:" && find tests -name "*.py" -exec grep -c "def test_" {} + 2>/dev/null | awk -F: '{s+=$2}END{print s}'
echo "CLI commands:" && grep -c "add_parser" src/main.py
echo "API routes:" && grep -c "@app\.\|@router\." src/api/cloud_app.py src/api/routes/*.py 2>/dev/null
echo "DB tables:" && python3 -c "
import sqlite3; conn = sqlite3.connect('ai_research_desk.sqlite3')
tables = conn.execute(\"SELECT COUNT(*) FROM sqlite_master WHERE type='table'\").fetchone()[0]
print(f'{tables}')
"
echo "Notifications:" && grep -c "^def notify_" src/notifications/telegram.py
echo "Research docs:" && ls docs/research/*.md | wc -l
```

**Every count must match AGENTS.md. Fix any that don't.**

## 13.2 Deleted files are actually gone

```bash
test -f src/scheduler/overnight.py && echo "⚠️ overnight.py STILL EXISTS" || echo "overnight.py deleted ✓"
test -f src/shadow_trading/broker.py && echo "⚠️ broker.py STILL EXISTS" || echo "broker.py deleted ✓"
test -f tests/test_overnight.py && echo "⚠️ test_overnight.py STILL EXISTS" || echo "test_overnight.py deleted ✓"
test -f tests/test_broker.py && echo "⚠️ test_broker.py STILL EXISTS" || echo "test_broker.py deleted ✓"
```

## 13.3 No imports of deleted modules

```bash
grep -rn "from src.scheduler.overnight\|from src.shadow_trading.broker" src/ tests/ --include="*.py" | grep -v __pycache__
```

**Must return zero results.**

---

# ══════════════════════════════════════════════════════════════
# SECTION 14: CONFIG VERIFICATION
# ══════════════════════════════════════════════════════════════

## 14.1 Settings load without error

```python
from src.config import load_config
config = load_config()
print(f"Config loaded: {len(config)} top-level keys")
for key in sorted(config.keys()):
    print(f"  {key}")
```

## 14.2 Critical config values

```python
risk = config.get("risk", {})
shadow = config.get("shadow_trading", {})
print(f"starting_capital: {risk.get('starting_capital')} (should be 100000)")
print(f"max_open_positions: {risk.get('max_open_positions')} (should be ≥10)")
print(f"shadow_enabled: {shadow.get('enabled')} (should be True for paper trading)")
print(f"timeout_days: {shadow.get('timeout_days')} (should be 15)")
```

---

# ══════════════════════════════════════════════════════════════
# SECTION 15: AUDIT REPORT
# ══════════════════════════════════════════════════════════════

After completing all sections, produce a summary report:

```
## Pre-Trading-Week Audit Report — [DATE]

### Safety Systems
- [ ] Risk governor rejects on exception: PASS/FAIL
- [ ] Drawdown conservative estimate: PASS/FAIL
- [ ] Kill switch functional: PASS/FAIL
- [ ] Zero bare except:pass in safety code: PASS/FAIL
- [ ] Traffic Light multiplier applied: PASS/FAIL

### Trade Lifecycle
- [ ] Scan pipeline dry run completes: PASS/FAIL
- [ ] All open positions have brackets: PASS/FAIL
- [ ] Trade exit monitoring runs: PASS/FAIL
- [ ] IS tracking captures signal price: PASS/FAIL

### Training Pipeline
- [ ] train-pipeline CLI runs 5 steps: PASS/FAIL
- [ ] Training data XML format: PASS/FAIL
- [ ] Canary wired into trainer: PASS/FAIL
- [ ] Leakage detector importable: PASS/FAIL

### Traffic Light
- [ ] VIX thresholds 20/30: PASS/FAIL
- [ ] RED multiplier 0.1: PASS/FAIL
- [ ] Persistence 5 consecutive: PASS/FAIL
- [ ] Wired into scan+governor+executor: PASS/FAIL

### PEAD Enrichment
- [ ] Earnings signals compute for AAPL: PASS/FAIL
- [ ] Wired into enricher: PASS/FAIL
- [ ] Conditional prompt inclusion: PASS/FAIL

### HSHS
- [ ] Computes from database: PASS/FAIL
- [ ] Wired into CTO report: PASS/FAIL
- [ ] Wired into council: PASS/FAIL
- [ ] API endpoint exists: PASS/FAIL

### Data Collection
- [ ] All 12 collectors have recent data: PASS/FAIL (list any without)

### Telegram
- [ ] All notifications wired: PASS/FAIL
- [ ] Connectivity test: PASS/FAIL

### Dashboard
- [ ] Frontend builds: PASS/FAIL
- [ ] All routes registered: PASS/FAIL

### Tests
- [ ] All tests pass: PASS/FAIL (count: X)
- [ ] New module tests exist: PASS/FAIL

### Documentation
- [ ] AGENTS.md counts match: PASS/FAIL
- [ ] Deleted files gone: PASS/FAIL
- [ ] No orphaned imports: PASS/FAIL

### Config
- [ ] Settings load: PASS/FAIL
- [ ] Critical values correct: PASS/FAIL

### Overall Verdict: READY / NOT READY for trading week
```

Save this report to `docs/audits/pre-trading-week-audit-2026-03-29.md`.

---

## Sprint Documentation Checklist

### Tier 1 (MANDATORY):
- [ ] AGENTS.md — counts corrected if any mismatch found
- [ ] Audit report saved to docs/audits/
- [ ] Any bugs fixed are committed with descriptive messages

### Verification (run at very end):
```bash
python -m pytest tests/ -x -q
cd frontend && npm run build && cd ..
```

**Both must pass. This is the final gate before Monday's market open.**
