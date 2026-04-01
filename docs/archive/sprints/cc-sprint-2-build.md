# Sprint 2: Build — Saturday Afternoon (CC Solo)

You are working on the halcyon-lab repo (github.com/millerrc18/halcyon-lab).
This sprint adds research-validated features. Max 10 tasks.

## Pre-read (mandatory, read ALL IN FULL):
```
cat docs/research/Event_Calendar_Integration_for_SP100_Pullback_Trading.md
cat docs/research/Alpaca_Bracket_Order_Failure_Modes_and_Mitigations.md
cat docs/research/XML_Compliance_via_GBNF_Grammar_Enforcement.md
cat docs/research/Bulletproof_Data_Quality_for_Small-Scale_Financial_ML.md
cat docs/research/Claude_API_Cost_Optimization__Prompt_Caching_Batch_API_Haiku.md
cat src/services/scan_service.py
cat src/risk/governor.py
cat src/shadow_trading/executor.py
cat src/training/claude_client.py
cat src/council/protocol.py
cat src/scheduler/watch.py
cat frontend/src/pages/Council.jsx
cat frontend/src/pages/Health.jsx
cat frontend/src/App.jsx
cat frontend/src/api.js
```

Run `python -m pytest tests/ -x -q` first. ALL tests should pass (Sprint 1 fixed them).

---

## Task 1: Event calendar 0-10 continuous risk scoring

**Research source:** `docs/research/Event_Calendar_Integration_for_SP100_Pullback_Trading.md`
**Decision:** Full 0-10 continuous scoring, linear size reduction, 25% floor, hard block ≥8.

Create `src/features/event_risk_score.py`:
```python
"""Event calendar risk scoring — 0-10 continuous scale.

Additive scoring:
  Earnings proximity (0-4): within 5 days of earnings = max component
  FOMC (0-2): within 2 days of FOMC meeting
  NFP (0-1): non-farm payrolls release day
  CPI (0-1): CPI release day
  OpEx (0-1): options expiration (3rd Friday)
  Month-end (0-1): last 2 trading days of month

Position sizing:
  Score 0-3: full sizing (1.0×)
  Score 4-7: linear reduction → 0.25 floor
  Score 8+: hard block (no new entries)
"""
```

Implementation requirements:
- Query `earnings_calendar` table for earnings dates within 5 days of each ticker
- Query `economic_calendar` table for FOMC, NFP, CPI dates
- Compute OpEx as 3rd Friday of current month
- Month-end detection
- Returns: `{"total_score": float, "components": dict, "sizing_multiplier": float, "blocked": bool}`
- Pure function — no side effects, no DB writes

Wire into the scan pipeline:
- In `src/services/scan_service.py`: compute event risk score ONCE per scan (not per ticker for market-wide events, per-ticker for earnings)
- Pass to governor as additional sizing multiplier
- In `src/risk/governor.py`: apply event_risk_multiplier alongside traffic_light_multiplier
- Telegram notification when score ≥ 6

Write tests in `tests/test_event_risk.py` (at least 8 tests).

## Task 2: Bracket order health monitor

**Research source:** `docs/research/Alpaca_Bracket_Order_Failure_Modes_and_Mitigations.md`
**Finding:** 9 failure modes, positions unprotected 17+ hours/day.

Create `src/shadow_trading/bracket_monitor.py`:
```python
"""Bracket order health monitor.

Runs every 5 minutes during market hours.
Verifies stop and target legs are active for every open position.
Alerts via Telegram if any bracket is broken.
"""
```

Implementation:
- For each open shadow_trade with an Alpaca order:
  - Query Alpaca API for order status
  - Verify both stop and target child legs are active
  - If any leg missing/canceled → log to `bracket_health` table + Telegram alert
- Pre-market check at 9:00 AM ET: verify all brackets active before open
- Post-close check at 4:30 PM ET: log which positions are unprotected overnight

Create `bracket_health` table:
```sql
CREATE TABLE IF NOT EXISTS bracket_health (
    check_id TEXT PRIMARY KEY,
    trade_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    stop_leg_status TEXT,
    target_leg_status TEXT,
    bracket_intact INTEGER DEFAULT 1,
    action_taken TEXT,
    checked_at TEXT NOT NULL
);
```

Wire into `watch.py` scheduler (every 5 minutes during market hours).
Write tests (mocked Alpaca API, at least 5 tests).

## Task 3: GBNF grammar enforcement for XML

**Research source:** `docs/research/XML_Compliance_via_GBNF_Grammar_Enforcement.md`
**Finding:** Ollama cannot enforce XML. GBNF structural envelope = 100% compliance.

Create `config/trade_commentary.gbnf`:
- Constrains tag structure only (why_now → analysis → metadata)
- Prose inside tags is unconstrained (`[^<]+`)
- Metadata fields have enum values for conviction, direction

Create `src/llm/grammar_client.py`:
- Uses `llama_cpp.Llama` and `LlamaGrammar` for constrained generation
- Falls back to Ollama client if `llama-cpp-python` not installed
- Same interface as existing Ollama client (takes prompt, returns text)

Add config flag (OFF by default):
```yaml
llm:
  use_grammar_enforcement: false
  grammar_file: "config/trade_commentary.gbnf"
```

Wire into `src/llm/packet_writer.py` as alternative generation path.
Write tests (at least 3 tests — grammar loads, fallback works, config toggle).

## Task 4: Data quality ingestion gates

**Research source:** `docs/research/Bulletproof_Data_Quality_for_Small-Scale_Financial_ML.md`

Create `src/training/ingestion_gate.py` (~80 lines):
```python
"""Training data ingestion quality gates.

Validates every training example before it enters the database.
Returns (is_valid: bool, rejection_reason: str | None).
"""

def validate_training_example(xml_text: str, existing_examples: list[str] = None) -> tuple[bool, str | None]:
    """Validate a training example.
    
    Checks:
    1. XML structure: <why_now>, <analysis>, <metadata> tags present and ordered
    2. Content length: why_now ≥ 50 chars, analysis ≥ 100 chars
    3. Metadata: conviction 1-10 integer, direction valid
    4. No markdown contamination (no **, no ```, no #)
    5. Duplicate detection: TF-IDF cosine similarity > 0.9 vs existing
    """
```

Wire into training example creation (wherever `INSERT INTO training_examples` happens).
Pipeline halt: if <90% of a batch passes validation → Telegram alert + stop pipeline.
Write tests (at least 6 tests — valid example, missing tags, short content, bad metadata, markdown contamination, duplicate detection).

## Task 5: Notes page (cloud dashboard)

Create the Notes page for the Render dashboard:

**Database:**
```sql
CREATE TABLE IF NOT EXISTS user_notes (
    note_id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT 'Untitled',
    content TEXT DEFAULT '',
    tags TEXT DEFAULT '[]',
    pinned INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

**API (in cloud_app.py):**
- `GET /api/notes` — list all notes (sorted by pinned desc, updated_at desc)
- `POST /api/notes` — create note
- `PUT /api/notes/{note_id}` — update note
- `DELETE /api/notes/{note_id}` — delete note

**Frontend:**
- `frontend/src/pages/Notes.jsx` — list view with create/edit/delete
- Auto-save on typing (debounced 1 second)
- Monospace textarea for content
- Tag chips, pin toggle
- Search by title/content
- Add route in App.jsx, navigation in Layout.jsx
- Add API calls in api.js

## Task 6: Council.jsx v2 visual update

Update `frontend/src/pages/Council.jsx` for v2 schema:

1. Agent cards with new names and emojis:
```jsx
const agentConfig = {
  tactical_operator: { label: 'Tactical', emoji: '⚡', color: '#f59e0b' },
  strategic_architect: { label: 'Strategic', emoji: '🏗️', color: '#3b82f6' },
  red_team: { label: 'Red Team', emoji: '🔴', color: '#ef4444' },
  innovation_engine: { label: 'Innovation', emoji: '💡', color: '#8b5cf6' },
  macro_navigator: { label: 'Macro', emoji: '🌍', color: '#10b981' },
};
```

2. Direction display (bullish=green, neutral=gray, bearish=red) — NOT position
3. Confidence as percentage (0-100%) — NOT integer 1-10
4. Consensus badge: "5-0 Bullish", "3-2 Bearish", "No Consensus"
5. Remove ALL `round3` references
6. Remove ALL `devils_advocate`, `risk_officer`, `alpha_strategist`, `data_scientist`, `regime_analyst` references
7. Parameter adjustments table (before → after, rate-limited badge)
8. If `result_json` exists on session, use it for rich display

## Task 7: HSHS radar chart on Health page

Add to `frontend/src/pages/Health.jsx`:
- Fetch from `GET /api/health/hshs`
- Recharts `RadarChart` with 5 dimensions (Performance, Model Quality, Data Asset, Flywheel Velocity, Defensibility)
- Composite HSHS score prominently displayed (large number)
- Phase indicator (Phase 1 weights: Data=35%, Model=25%, etc.)

## Task 8: Prompt caching on council sessions

**Research source:** `docs/research/Claude_API_Cost_Optimization__Prompt_Caching_Batch_API_Haiku.md`
**Finding:** 5 agents share 10K+ system prompt. Agents 2-5 get 90% off input with caching.

In `src/council/protocol.py` `run_round_1()`:
- Sequence agent calls: first agent includes `cache_control: {"type": "ephemeral"}` on system message
- Wait for first response before launching agents 2-5
- Log cache hit/miss in debug output
- Requires modifying the Claude API call to include cache_control parameter

If the Claude client wrapper doesn't support cache_control, add it.

## Task 9: Module ownership docstrings

For every `.py` file in `src/` that doesn't already have a "Called by" / "Calls" header,
add a 3-line docstring at the top:

```python
"""Short description of what this module does.

Called by: list of modules that import from this one
Calls: list of modules this one imports from src/
"""
```

Use grep to find actual import relationships:
```bash
for f in $(find src -name "*.py" ! -path "*__pycache__*" ! -name "*backup*"); do
    echo "=== $f ==="
    grep "from src\." "$f" | head -5
done
```

## Task 10: All tests pass + frontend builds + verify_counts

```bash
python -m pytest tests/ -v --tb=short   # ALL pass
cd frontend && npm run build && cd ..   # builds clean
python scripts/verify_counts.py         # counts match
```

Update AGENTS.md if counts changed.

Commit:
```bash
git add -A
git commit -m "sprint 2: build — event scoring, bracket monitor, GBNF, data gates, UI updates

- Event calendar 0-10 risk scoring (earnings 5-day, FOMC 2-day, NFP, CPI, OpEx)
- Bracket order health monitor (every 5 min, Telegram alerts)
- GBNF grammar enforcement for XML (off by default, config flag)
- Data quality ingestion gates (5 validation checks, pipeline halt)
- Notes page (CRUD, auto-save, tags, search)
- Council.jsx v2 (new agents, direction display, consensus badge)
- HSHS radar chart on Health page
- Prompt caching on council sessions
- Module ownership docstrings across src/
- All tests pass, frontend builds"

git push origin main
```

---

## Sprint Documentation Checklist
- [ ] AGENTS.md counts match (verify_counts.py)
- [ ] CHANGELOG.md — sprint 2 entry
- [ ] All new modules have ownership docstrings
- [ ] All tests pass (including new tests for event risk, bracket monitor, data gates)
- [ ] Frontend builds with Notes page + Council v2 + HSHS radar
