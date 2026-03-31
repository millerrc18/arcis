# Sprint 8: Implementation Details

> **Read this alongside:** `docs/sprints/sprint-8-cc-comprehensive.md`
> **Purpose:** Exact line numbers, code patterns, gotchas, and acceptance criteria for every fix.

---

## GUARDRAIL WARNING

These files already exceed 400 lines. Do NOT add significant code to them. Extract helpers instead.
- `src/training/trainer.py` — 761 lines
- `src/training/curriculum.py` — 461 lines
- `src/council/engine.py` — 596 lines
- `src/shadow_trading/executor.py` — 1185 lines

---

## Task 1 Details: Training Pipeline Safety

### #110 — Self-blinding leakage in feature snapshot

**Where:** `src/training/data_collector.py` ~line 158
```python
feature_snapshot, trade_outcome, instruction, input_text, output_text
```
The `feature_snapshot` is stored as JSON alongside training examples. If it includes outcome-correlated fields, the model can learn shortcuts.

**Fields that MUST be removed from feature_snapshot before storage:**
- `pnl_dollars`, `pnl_pct` (direct outcome)
- `exit_reason` (direct outcome)
- `max_favorable_excursion`, `max_adverse_excursion` (post-trade info)
- `actual_exit_price`, `actual_exit_time` (post-trade info)
- `duration_days` (post-trade info)

**Fields to KEEP** (pre-trade observables):
- `pullback_depth_pct` — this is actually fine, it's computed before the trade
- `trend_state`, `relative_strength_state`, `current_price`, `sma_50`, `sma_200`
- `vix_proxy`, `regime_label`, `traffic_light`, `sector`
- All enrichment data (news, insider, macro)

**Implementation:**
```python
OUTCOME_FIELDS = {
    "pnl_dollars", "pnl_pct", "exit_reason", "max_favorable_excursion",
    "max_adverse_excursion", "actual_exit_price", "actual_exit_time",
    "duration_days", "status", "outcome_type",
}

def _sanitize_feature_snapshot(snapshot: dict) -> dict:
    """Remove outcome-correlated fields from feature snapshot."""
    return {k: v for k, v in snapshot.items() if k not in OUTCOME_FIELDS}
```
Call this before storing: `feature_snapshot = _sanitize_feature_snapshot(feature_snapshot)`

**Acceptance:** No key in OUTCOME_FIELDS appears in any stored feature_snapshot.

### #111 — Canary set not excluded from training

**Where:** `src/training/canary.py` line 37 defines `DEFAULT_CANARY_PATH = data/reference/canary_set.jsonl`
**Where trainer uses data:** `src/training/trainer.py` ~line 269 `export_training_data()`

**The canary set is loaded from a JSONL file.** Each entry has an `example_id`. The trainer needs to check:
```python
from src.training.canary import CanaryEvaluator
evaluator = CanaryEvaluator()
canary_ids = {e["example_id"] for e in evaluator._load_canary_examples()}
# Filter training data
training_data = [ex for ex in all_examples if ex["example_id"] not in canary_ids]
```

**Edge case:** If `canary_set.jsonl` doesn't exist yet, `canary_ids` should be empty set (not crash).

**Acceptance:** Test that creates a fake canary set, runs export, and verifies canary IDs are NOT in the exported training JSONL.

### #113 — Leakage detector false CLEAN on small vocab

**Where:** `src/training/leakage_detector.py` ~line 80-100 (the TF-IDF classification)

**Current behavior:** With <30 examples per class, TF-IDF produces a tiny vocabulary, random accuracy is near 0.5, and the detector says CLEAN regardless.

**Fix:** Before running TF-IDF, check class sizes:
```python
win_count = sum(1 for ex in examples if ex["label"] == "win")
loss_count = sum(1 for ex in examples if ex["label"] == "loss")
if min(win_count, loss_count) < 30:
    return {
        "status": "INSUFFICIENT_DATA",
        "balanced_accuracy": None,
        "reason": f"Need ≥30 per class (have {win_count} win, {loss_count} loss)",
    }
```

**Acceptance:** Test with 10 win + 5 loss examples returns INSUFFICIENT_DATA.

### #114 — Holdout temporal split order

**Where:** `src/training/trainer.py` ~line 269 `export_training_data()`

**Current order:**
1. Load all examples
2. Filter by quality
3. Split into train/holdout chronologically

**Correct order:**
1. Load all examples
2. Split into train/holdout chronologically FIRST
3. Filter by quality within each split independently

**Why:** If quality filter removes recent examples, the "newest 15%" holdout may actually include examples that were in the middle of the timeline.

**Implementation:** Move the quality filter AFTER the temporal split. Apply it to `train_set` and `holdout_set` separately.

**Acceptance:** After export, verify that ALL holdout examples have `created_at` AFTER all training examples.

### #115 — Small training set crashes

**Where:** `src/training/trainer.py` lines 68, 149, 215 — `gradient_accumulation_steps` hardcoded to 8 or 16

**Fix:**
```python
effective_gas = min(gradient_accumulation_steps, max(1, len(dataset)))
```
Also add a minimum dataset size check:
```python
if len(dataset) < 5:
    logger.error("[TRAINER] Dataset too small (%d examples) — skipping training", len(dataset))
    return {"status": "skipped", "reason": "insufficient_data"}
```

**Acceptance:** Test with 3-example dataset doesn't crash, returns skipped status.

### #116 — Partial close mislabeling

**Where:** `src/training/data_collector.py` — wherever `trade_outcome` is assigned

**Check:** Does the collector look at `exit_reason`? If `exit_reason` contains both "target" and "stop" references, it's a partial close.

**Fix:** Add outcome type detection:
```python
if exit_reason and "partial" in exit_reason.lower():
    outcome = "PARTIAL"
elif pnl_dollars and pnl_dollars > 0:
    outcome = "WIN"
elif pnl_dollars and pnl_dollars < 0:
    outcome = "LOSS"
else:
    outcome = "TIMEOUT"
```
For now, PARTIAL examples are stored but excluded from training (logged for manual review).

---

## Task 2 Details: Council Fixes

### #117 — Anthropic rate limit retry

**Where:** `src/council/protocol.py` line 38-48

**Current:**
```python
try:
    raw = generate_training_example(...)
except Exception as exc:
    ...
```

**Fix:** Import and catch the specific rate limit error:
```python
import anthropic

MAX_RETRIES = 3
for attempt in range(MAX_RETRIES):
    try:
        raw = generate_training_example(...)
        break
    except anthropic.RateLimitError as exc:
        wait = (attempt + 1) * 10  # 10s, 20s, 30s
        logger.warning("[COUNCIL] Rate limited, retrying in %ds (attempt %d/%d)", wait, attempt+1, MAX_RETRIES)
        time.sleep(wait)
    except Exception as exc:
        logger.error("[COUNCIL] API call failed: %s", exc)
        break
```

### #118 — Failed parse still counted in vote tally

**Where:** `src/council/aggregation.py`

**Look for:** Where votes are counted for consensus. If `assessment_json` is None or empty after parsing, that vote should be excluded from the tally.

**Fix:** Filter before aggregation:
```python
valid_votes = [v for v in votes if v.get("assessment_json") and v.get("direction")]
```
Log: `"[COUNCIL] Filtered {len(votes) - len(valid_votes)} unparseable votes"`

### #119 — Hardcoded 5-agent threshold

**Where:** `src/council/aggregation.py` — look for `3` or `>= 3` or any hardcoded majority check

**Fix:** `threshold = len(valid_votes) // 2 + 1`

### #120 — No cost cap

**Where:** `src/council/engine.py` ~line 169 `_estimate_session_cost()`

Before starting Round 2, check:
```python
max_cost = config.get("council", {}).get("max_session_cost", 2.0)
estimated_round2_cost = _estimate_session_cost(1)  # 1 additional round
if current_cost + estimated_round2_cost > max_cost:
    logger.warning("[COUNCIL] Cost cap reached ($%.2f > $%.2f) — skipping Round 2", 
                   current_cost + estimated_round2_cost, max_cost)
    # Skip round 2, finalize with round 1 results
```

### #121 — Confidence not type-validated

**Where:** `src/council/parsing.py` ~line 50-80

**Fix:**
```python
try:
    confidence = float(raw_confidence)
    confidence = max(0.0, min(1.0, confidence))
except (TypeError, ValueError):
    logger.warning("[COUNCIL] Invalid confidence value: %s — defaulting to 0.5", raw_confidence)
    confidence = 0.5
```

### #122 — Value tracker table not auto-created

**Where:** `src/council/value_tracker.py` — find functions that query the parameter table

**Fix:** Add `CREATE TABLE IF NOT EXISTS` at the entry point:
```python
def _ensure_tables(db_path):
    with sqlite3.connect(db_path) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS council_value_tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ...
        )""")
```

---

## Task 3 Details: LLM Pipeline

### #154 — Context window overflow

**Where:** `src/llm/packet_writer.py` — the function that builds the full prompt

**Rough token estimate:** `len(prompt_text) // 4`

**Qwen3 8B context window:** 8192 tokens (some report 32K for Qwen3, verify with `ollama show halcyonlatest`)

**Fix:**
```python
estimated_tokens = len(full_prompt) // 4
MAX_CONTEXT = 7000  # Leave headroom
if estimated_tokens > MAX_CONTEXT:
    # Truncate enrichment section (news, insider, macro) first
    logger.warning("[LLM] Prompt too long (%d est. tokens) — truncating enrichment", estimated_tokens)
    # Cut enrichment to fit
    excess = estimated_tokens - MAX_CONTEXT
    chars_to_cut = excess * 4
    enrichment_section = enrichment_section[:-chars_to_cut]
```

### #167 — Empty string treated as success

**Where:** `src/llm/client.py` — the `generate()` function return path

**Fix:** After getting response from Ollama:
```python
if not response or not response.strip():
    logger.warning("[LLM] Empty response from Ollama")
    return None
```

### #168 — Conviction None passes through

**Where:** `src/llm/packet_writer.py` ~line 299-309

**Current:**
```python
conviction, why_now, deeper_analysis = _parse_llm_response(response)
if conviction is not None:
    packet.llm_conviction = conviction
```

**Fix:** If conviction is None, set default for paper trades:
```python
if conviction is None:
    logger.warning("[LLM] No conviction parsed for %s — defaulting to 5", packet.ticker)
    conviction = 5
packet.llm_conviction = conviction
```

### #156 — Prompt injection from news/filings

**Where:** `src/llm/packet_writer.py` or `src/data_enrichment/enricher.py`

**Create sanitizer:**
```python
import re

def _sanitize_enrichment_text(text: str, max_chars: int = 500) -> str:
    """Strip potential prompt injection patterns from enrichment data."""
    # Remove XML-like tags
    text = re.sub(r'<[^>]+>', '', text)
    # Remove instruction-like patterns
    text = re.sub(r'(?i)(you are|ignore previous|system:|assistant:|human:)', '[FILTERED]', text)
    return text[:max_chars]
```
Apply to all news headlines, filing text, and insider transaction descriptions before including in the prompt.

### #163 — Grammar client VRAM leak

**Where:** `src/llm/grammar_client.py`

**Look for:** Global variables holding model references. When model version changes, the old model may not be released.

**Fix:** Add explicit cleanup:
```python
def _release_model():
    global _loaded_model
    if _loaded_model is not None:
        del _loaded_model
        _loaded_model = None
        import gc; gc.collect()
        try:
            import torch; torch.cuda.empty_cache()
        except ImportError:
            pass
```
Call `_release_model()` before loading a new version.

### #164 — _daily_packets unbounded

**Where:** `src/scheduler/watch.py` — find `_daily_packets` list

**Fix:** After sending EOD digest email, clear the list:
```python
self._daily_packets = []
```
Also add a cap: `if len(self._daily_packets) > 200: self._daily_packets = self._daily_packets[-100:]`

### #166 — VRAM handoff fails: threshold too low, no torch cleanup, short timeout

**Where:** `src/scheduler/vram_manager.py` — `_wait_for_vram_clear()` and `handoff_to_training()`

**Current behavior (broken):**
- Threshold is 500MB — a partially unloaded Qwen3 8B Q8_0 (8.7GB) can leave 2GB+ in VRAM
- After killing Ollama, no `torch.cuda.empty_cache()` call — GPU memory fragments persist
- Final wait after kill is only 15s — Windows process cleanup is slow
- Result: handoff fails every night, overnight training never runs

**Fix — 4 changes in `vram_manager.py`:**

1. **Raise threshold** from 500MB to 1500MB in ALL `_wait_for_vram_clear()` calls:
```python
def _wait_for_vram_clear(self, threshold_mb: int = 1500,
                         timeout_seconds: int = 30) -> bool:
```
Also update the three call sites in `handoff_to_training()` and `handoff_to_inference()` that pass `threshold_mb=500` explicitly.

2. **Add torch.cuda.empty_cache() after killing Ollama:**
```python
# After killing Ollama process:
try:
    import torch
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        logger.info("[VRAM] torch.cuda.empty_cache() called")
except ImportError:
    pass
```
Insert this after the `taskkill`/`pkill` call and the `time.sleep(5)`.

3. **Increase final timeout** from 15s to 45s after killing Ollama:
```python
if not self._wait_for_vram_clear(threshold_mb=1500, timeout_seconds=45):
    logger.error("[VRAM] Handoff to training FAILED — VRAM not clear even after killing Ollama")
    return False
```

4. **Add a force-kill retry** — if the first `taskkill` doesn't work, try killing `ollama_llama_server.exe` (the actual inference subprocess on Windows):
```python
if platform.system() == "Windows":
    subprocess.run(["taskkill", "/f", "/im", "ollama.exe"],
                   capture_output=True, timeout=10)
    # Also kill the inference subprocess directly
    subprocess.run(["taskkill", "/f", "/im", "ollama_llama_server.exe"],
                   capture_output=True, timeout=10)
```

**Also update `handoff_to_inference()`** — same threshold and torch cleanup changes.

**Acceptance:** After fix, `handoff_to_training()` succeeds when Ollama is running with Qwen3 8B loaded. VRAM drops below 1500MB within 45s. Log shows `[VRAM] Handoff to training: Ollama unloaded, VRAM at XMB`.

### #153 — LLM timeout configurable

**Where:** `src/llm/client.py` — find the `timeout` parameter in the Ollama API call

**Fix:**
```python
timeout = config.get("llm", {}).get("inference_timeout_seconds", 300)
```

### #169 — Conviction clamped without flagging

**Where:** `src/llm/packet_writer.py` ~line 203-204

**Current:** `conviction = max(1, min(10, conviction))`

**Fix:** Add warning before clamping:
```python
if raw_conviction < 1 or raw_conviction > 10:
    logger.warning("[LLM] Hallucinated conviction %d (outside 1-10) for %s — clamping", raw_conviction, ticker)
conviction = max(1, min(10, raw_conviction))
```

### #162 — Hallucinated ticker validation fails open

**Where:** `src/llm/validator.py` ~line 30-50

**Fix:** If the universe lookup throws an exception, REJECT (fail closed):
```python
try:
    valid_tickers = get_sp100_tickers()
except Exception as e:
    logger.error("[VALIDATE] Universe lookup failed: %s — REJECTING trade", e)
    return False, "Universe lookup failed"
```

---

## Task 4 Details: Data Pipeline

### #123 — Retention policy

**Create:** `src/data_collection/retention.py`

```python
RETENTION_RULES = {
    "scan_metrics": 90,       # days
    "log_entries": 30,
    "activity_log": 30,
    "command_results": 30,
    "council_debug_log": 60,
    "setup_signals": 180,
    "options_metrics": 90,
}
# NEVER prune: shadow_trades, training_examples, recommendations, council_sessions

def run_retention(db_path: str = "ai_research_desk.sqlite3") -> dict:
    """Delete rows older than retention period. Returns count per table."""
    ...
```

**Hook in watch.py:** Call during overnight mode, once per night.

### #125, #128, #129 — Collector data validation

For each collector, add a validation step after fetching data:
- Options: `if pd.isna(underlying_price) or underlying_price <= 0: skip`
- CBOE: If regex returns all None, return None (not a dict of Nones)
- Short interest: Use `cursor.rowcount` instead of `conn.total_changes`

### #126, #127 — EDGAR fixes

- Normalize accession numbers: `accession.replace("-", "")` then reformat with dashes
- Before NLP UPDATE, check columns exist with PRAGMA

### #131 — Sync timezone

**Where:** `src/sync/render_sync.py`

Ensure all `datetime.now()` calls use `datetime.now(UTC)` or `datetime.now(ZoneInfo("UTC"))`.

### #133 — Enricher rate limiting

**Where:** `src/data_enrichment/enricher.py`

Add per-API rate tracking:
```python
_last_request_time = {}
def _rate_limit(api_name: str, min_interval: float = 1.0):
    now = time.time()
    last = _last_request_time.get(api_name, 0)
    if now - last < min_interval:
        time.sleep(min_interval - (now - last))
    _last_request_time[api_name] = time.time()
```
Call `_rate_limit("finnhub")` before each Finnhub request.

---

## Task 5 Details: Trading Logic

### #99 — Atomic duplicate check

**Where:** `src/shadow_trading/executor.py` line 147-149

**Fix:** Use `BEGIN IMMEDIATE` transaction:
```python
with sqlite3.connect(db_path) as conn:
    conn.execute("BEGIN IMMEDIATE")
    existing = conn.execute(
        "SELECT trade_id FROM shadow_trades WHERE ticker = ? AND status = 'open'",
        (ticker,)
    ).fetchone()
    if existing:
        conn.execute("ROLLBACK")
        return None
    # ... insert new trade ...
    conn.execute("COMMIT")
```

### #109 — Daily loss uses unrealized

**Where:** `src/risk/governor.py` line 180

**Current:** `daily_pnl_pct = portfolio.get("daily_pnl_pct", 0)` — this includes unrealized

**Fix:** Calculate realized-only daily P&L:
```python
today = datetime.now(ET).strftime("%Y-%m-%d")
realized_today = conn.execute(
    "SELECT COALESCE(SUM(pnl_dollars), 0) FROM shadow_trades "
    "WHERE status='closed' AND actual_exit_time LIKE ?",
    (f"{today}%",)
).fetchone()[0]
daily_loss_pct = realized_today / equity if equity > 0 else 0
```

### #145 — Sector exposure uses stale prices

**Where:** `src/risk/governor.py` — sector concentration check

**Fix:** When calculating sector exposure, use `features.get("current_price", entry_price)` instead of `entry_price` for dollar-weighted exposure.

### #104, #107, #108, #144 — See sprint doc for these (already detailed enough)

---

## Task 6-7 Details: Frontend

### #137 — AuthGate plaintext password

**Where:** `frontend/src/components/AuthGate.jsx` line 4

**Current:** Token is the plaintext password stored in localStorage.

**Fix:** Hash before storing:
```javascript
async function hashToken(password) {
  const encoder = new TextEncoder();
  const data = encoder.encode(password);
  const hash = await crypto.subtle.digest('SHA-256', data);
  return Array.from(new Uint8Array(hash)).map(b => b.toString(16).padStart(2, '0')).join('');
}
```
Store hash in localStorage, send hash in Authorization header. Backend must also compare against hash.

**IMPORTANT:** This changes the auth contract. Backend `verify_auth` must also hash the expected secret before comparing. Check `src/api/cloud_app.py` for the auth verification function.

### #136 — XSS via dangerouslySetInnerHTML

**Where:** `frontend/src/pages/Docs.jsx` line 257

**Fix:** Replace with `react-markdown` if available, or sanitize:
```javascript
function sanitizeHtml(html) {
  const div = document.createElement('div');
  div.textContent = html;
  return div.innerHTML;
}
```
Or better: render markdown source directly instead of pre-rendered HTML.

### #148 — API_SECRET in bundle

**Where:** `frontend/src/config.js` line 5, `frontend/src/api.js` line 1 and 11

The `VITE_API_SECRET` env var is baked into the JS bundle at build time. Anyone can see it in browser dev tools.

**Fix:** The auth should use a session token pattern:
1. User enters password → hashed → sent to `/api/auth/login`
2. Server validates, returns a session token (JWT or random string)
3. Frontend stores session token, uses it for all requests
4. Secret never leaves the server

**However:** This is a significant architectural change. Minimum viable fix: ensure `VITE_API_SECRET` is different from any real API keys and is only used for dashboard access control. Add a comment in `.env.example` explaining this.

### #135 — Error boundaries

**Create:** `frontend/src/components/ErrorBoundary.jsx`

```javascript
import { Component } from 'react';

export default class ErrorBoundary extends Component {
  state = { hasError: false, error: null };
  
  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }
  
  render() {
    if (this.state.hasError) {
      return (
        <div className="arcis-card" style={{ padding: '2rem', textAlign: 'center' }}>
          <h3>Something went wrong</h3>
          <p style={{ color: 'var(--arcis-text-muted)' }}>
            {this.state.error?.message || 'Unknown error'}
          </p>
          <button onClick={() => window.location.reload()}>Refresh page</button>
        </div>
      );
    }
    return this.props.children;
  }
}
```

Wrap each page in `App.jsx` routes:
```jsx
<Route path="/dashboard" element={<ErrorBoundary><Dashboard /></ErrorBoundary>} />
```

---

## Task 8 Details: Sprint 6 Tasks 1-6

**Read the full spec:** `docs/sprints/sprint-6-cc-pipeline-visibility.md` Tasks 1-6.

CC already wrote an implementation plan for this (see the Sprint 6 session). Key notes:
- 2 of 5 API methods already exist (`getTrainingStatus`, `getCosts`)
- Only need to ADD: `getDataCollectionStats`, `getTrainingHistory`, `getScanMetrics`
- Training.jsx is already 307 lines — keep new sections concise
- Verify actual API response shapes before building UI

---

## Task 9 Details: Config, Performance & Tech Debt

### #83 — Hardcoded DB path (87 files!)

This is the biggest change by volume. **Be surgical:**

1. Create the constant:
```python
# src/config.py (add near top)
import os
DB_PATH = os.environ.get("ARCIS_DB_PATH", "ai_research_desk.sqlite3")
```

2. For every file, change:
```python
def some_function(db_path: str = "ai_research_desk.sqlite3"):
```
to:
```python
from src.config import DB_PATH
def some_function(db_path: str = DB_PATH):
```

3. **Do NOT change any function signatures** — only default values.
4. **Do NOT change test files** — they may intentionally use temp DB paths.
5. **Do NOT change scripts/** — they run standalone and need explicit paths.

This is 87 files. Use a systematic find-and-replace with verification.

### #92, #97 — Missing indexes

Add to BOTH `scripts/create_missing_tables.py` AND `scripts/render_migrate.py`:
```sql
CREATE INDEX IF NOT EXISTS idx_shadow_trades_status ON shadow_trades(status);
CREATE INDEX IF NOT EXISTS idx_shadow_trades_status_time ON shadow_trades(status, actual_entry_time);
CREATE INDEX IF NOT EXISTS idx_recommendations_created ON recommendations(created_at);
```

### #149 — Market holiday awareness

```python
# src/scheduler/holidays.py
NYSE_HOLIDAYS_2026 = {
    "2026-01-01",  # New Year's Day
    "2026-01-19",  # MLK Jr. Day
    "2026-02-16",  # Presidents' Day
    "2026-04-03",  # Good Friday
    "2026-05-25",  # Memorial Day
    "2026-06-19",  # Juneteenth
    "2026-07-03",  # Independence Day (observed)
    "2026-09-07",  # Labor Day
    "2026-11-26",  # Thanksgiving
    "2026-12-25",  # Christmas
}

def is_market_holiday(date_str: str) -> bool:
    return date_str in NYSE_HOLIDAYS_2026
```

In watch.py, before running scans:
```python
if is_market_holiday(now.strftime("%Y-%m-%d")):
    logger.info("[WATCH] Market holiday — skipping scans")
    return
```

### #152 — Sleep detection

In watch.py, after each scan:
```python
if self._last_scan_time:
    gap = (now - self._last_scan_time).total_seconds() / 60
    if gap > 30 and self._is_market_open(now):
        logger.warning("[WATCH] %.0f minute gap since last scan — possible sleep/crash", gap)
        send_telegram(f"⚠️ {gap:.0f} minute gap detected — possible computer sleep")
self._last_scan_time = now
```

---

## Verification Checklist (Task 10)

After ALL tasks, CC must verify:
```bash
# Tests pass
python -m pytest tests/ -x -q

# Frontend builds
cd frontend && npm run build && cd ..

# Test count increased (new tests added)
find tests -name "test_*.py" -exec grep -c "def test_" {} + | awk -F: '{s+=$2}END{print "Tests:", s}'

# No new guardrail violations introduced
find src -name "*.py" ! -path "*__pycache__*" -exec sh -c 'lines=$(wc -l < "$1"); if [ "$lines" -gt 400 ]; then echo "VIOLATION: $1 ($lines lines)"; fi' _ {} \;

# All referenced issues exist and are still open
# Use: gh issue list --state open --limit 100

# AGENTS.md counts match reality
grep -c "def test_" tests/test_*.py | tail -1
find src -name "*.py" ! -path "*__pycache__*" | wc -l
grep -rn "@router\." src/api/cloud_routes/*.py | wc -l
```

All closed issues should be listed in the PR description with `Closes #NNN` syntax so GitHub auto-closes them on merge.
