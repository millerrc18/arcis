# Sprint 8: Comprehensive Cleanup — All Remaining Issues (Claude Code)

> **Executor:** Claude Code
> **Scope:** 10 tasks (~65 GitHub issues)
> **Prerequisite:** Sprint 7 MERGED
> **Read first:** AGENTS.md, docs/conventions.md
> **Implementation details:** `docs/sprints/sprint-8-details.md` — exact line numbers, code patterns, gotchas for every fix. READ THIS BEFORE STARTING EACH TASK.
> **Context:** Sprint 7 fixed critical reliability issues (crash handler, GTC brackets, heartbeat, TL stub). This sprint addresses EVERYTHING remaining — training pipeline, council, LLM, data pipeline, frontend, trading logic, config, and documentation. Goal: close every open issue.
> **Test baseline:** Check at start. Must not decrease.
> **Note:** This is a large sprint. Work through tasks sequentially. If any task exceeds 60 lines in a single function or 400 lines in a single file, extract into helper functions/modules.

---

## Pre-Sprint Checks (MANDATORY)

```bash
# Read existing issues first
curl -s -H "Authorization: token $GITHUB_TOKEN" \
  "https://api.github.com/repos/millerrc18/halcyon-lab/issues?state=open&per_page=100" | \
  python3 -c "import json,sys; [print(f'#{i[\"number\"]}: {i[\"title\"]}') for i in json.load(sys.stdin)]"

find src -name "*.py" ! -path "*__pycache__*" -exec sh -c 'lines=$(wc -l < "$1"); if [ "$lines" -gt 400 ]; then echo "VIOLATION: $1 ($lines lines)"; fi' _ {} \;
find tests -name "test_*.py" -exec grep -c "def test_" {} + | awk -F: '{s+=$2}END{print "Tests:", s}'
```

---

## Task 1: Training Pipeline Safety (#110, #111, #113, #114, #115, #116)

These issues affect model quality — must be fixed before the first retrain.

**#110 — Self-blinding leakage: pullback_depth and confidence in feature snapshot**
File: `src/training/data_collector.py`
The feature snapshot stored with training examples includes `pullback_depth_pct` and `confidence` which leak outcome information. When the model sees a training example with pullback_depth=-2% that became a WIN, it learns "small pullbacks win" — but that's hindsight.
Fix: Sanitize the feature snapshot before storing. Remove or mask fields that correlate with outcome: `pullback_depth_pct`, `confidence`, `pnl_dollars`, `pnl_pct`, `exit_reason`, `max_favorable_excursion`, `max_adverse_excursion`. Keep only pre-trade observable features.

**#111 — Canary set never enforced — not excluded from training data**
File: `src/training/canary.py`, `src/training/trainer.py`
The canary examples (25 fixed examples for degradation monitoring) should NEVER appear in training data. But there's no enforcement — they could be included.
Fix: In the trainer, before building the training dataset, filter out any example whose `example_id` is in the canary set. Add a check: if any canary example is found in the training batch, log a WARNING and remove it.

**#113 — Leakage detector returns false CLEAN when vocabulary is too small**
File: `src/training/leakage_detector.py`
With very few training examples, the TF-IDF vocabulary is too small to detect leakage, so the detector says CLEAN even if leakage exists.
Fix: Add a minimum sample size check — if fewer than 30 examples per class, return `{"status": "INSUFFICIENT_DATA", "reason": "Need ≥30 examples per class"}` instead of CLEAN.

**#114 — Holdout temporal split applied after quality filter — future leakage risk**
File: `src/training/trainer.py`
If quality filtering removes recent examples, the temporal split (oldest 80% train, newest 20% holdout) may include future data in training.
Fix: Apply temporal split FIRST, then quality filter within each split independently.

**#115 — Small training sets crash due to gradient accumulation vs example count**
File: `src/training/trainer.py`
If training examples < gradient_accumulation_steps × batch_size, training crashes.
Fix: Dynamically adjust gradient_accumulation_steps: `min(configured_steps, len(dataset) // batch_size)`. If dataset is too small (< batch_size), skip training with a clear warning.

**#116 — Partial trade closes mislabeled as win/loss in training data**
File: `src/training/data_collector.py`
If a trade partially closes (e.g., half position at target, half at stop), the training label doesn't reflect the mixed outcome.
Fix: Add logic to detect partial closes (check if both target and stop were hit). Label as `PARTIAL` outcome type. For now, exclude PARTIAL from training data with a log note.

**Tests:** ≥6 tests — one per issue: sanitized features, canary exclusion, insufficient data detection, temporal split order, small dataset handling, partial close detection.

**Closes:** #110, #111, #113, #114, #115, #116

---

## Task 2: Council Fixes (#117, #118, #119, #120, #121, #122)

**#117 — Anthropic API rate limits not caught — no retry or backoff**
File: `src/council/protocol.py`
Fix: Catch `anthropic.RateLimitError` (or HTTP 429). Retry with exponential backoff: 5s, 15s, 30s, then fail. Max 3 retries.

**#118 — Failed parse assessments still counted in consensus vote tally**
File: `src/council/aggregation.py`
Fix: Before aggregation, filter out votes where `assessment_json` failed to parse (is None or empty). Log the count of filtered votes.

**#119 — Consensus threshold hardcoded for exactly 5 agents**
File: `src/council/aggregation.py`
Fix: Make the majority threshold dynamic: `threshold = len(valid_votes) // 2 + 1` instead of hardcoded 3.

**#120 — No cost cap before running Round 2 — runaway API costs possible**
File: `src/council/engine.py`
Fix: Add a `max_session_cost` config key (default $2.00). Before starting Round 2, check cumulative cost. If exceeding cap, skip Round 2 with a log warning.

**#121 — Confidence value not type-validated — non-numeric string crashes parsing**
File: `src/council/parsing.py`
Fix: Wrap confidence parsing in try/except. If not a valid float, default to 0.5 and log a warning.

**#122 — Value tracker parameter table not auto-created on first access**
File: `src/council/value_tracker.py`
Fix: Add `CREATE TABLE IF NOT EXISTS` at the start of any function that accesses the table. Same pattern as other modules.

**Tests:** ≥4 tests: rate limit retry, filtered votes excluded, dynamic threshold, cost cap enforcement.

**Closes:** #117, #118, #119, #120, #121, #122

---

## Task 3: LLM Pipeline Hardening (#153, #154, #156, #162, #163, #164, #166, #167, #168, #169)

**#154 — No context window overflow protection**
File: `src/llm/packet_writer.py`
Fix: Before sending prompt to Ollama, estimate token count (chars / 4 rough heuristic). If >7000 tokens (leaving headroom for 8192 context), truncate the enrichment data section. Log a warning.

**#167 — Empty string LLM response treated as success**
File: `src/llm/client.py`
Fix: After receiving response, check `if not response or not response.strip()`. Treat as failure, return None.

**#168 — Conviction score allows None to pass — downstream sizing fails**
File: `src/llm/packet_writer.py`
Fix: If conviction is None after parsing, set to default (5) for paper trades. Log warning.

**#169 — Conviction score clamped instead of flagging hallucination**
File: `src/llm/packet_writer.py`
Fix: If raw conviction is outside 1-10, log a WARNING with the raw value before clamping. Track count in scan_metrics.

**#162 — Hallucinated ticker validation silently skipped when universe lookup fails**
File: `src/llm/validator.py`
Fix: If universe lookup fails (exception), REJECT the trade (fail closed, not open). Log error.

**#163 — Grammar client global state causes VRAM leak across model versions**
File: `src/llm/grammar_client.py`
Fix: When model version changes, explicitly release previous grammar/model state before loading new one.

**#164 — _daily_packets list grows unbounded in email digest mode**
File: `src/scheduler/watch.py`
Fix: Cap `_daily_packets` at 100 entries. If exceeded, drop oldest. Or clear at EOD after sending digest.

**#166 — VRAM manager threshold too generous — 500MB allows partially unloaded models**
File: `src/llm/grammar_client.py` or VRAM manager
Fix: Increase minimum free VRAM threshold to 1500MB before loading a model.

**#153 — LLM timeout of 180s may be too short**
File: `src/llm/client.py`
Fix: Make timeout configurable via `llm.inference_timeout_seconds` in settings.yaml. Default 300s.

**#156 — Prompt injection risk from news headlines**
File: `src/llm/packet_writer.py`
Fix: Sanitize enrichment text before including in prompt. Strip any XML-like tags, instruction-like patterns (`you are`, `ignore previous`, `system:`), and cap each enrichment section to 500 chars.

**Tests:** ≥5 tests: context overflow truncation, empty response handling, conviction None default, universe lookup failure rejection, daily_packets cap.

**Closes:** #153, #154, #156, #162, #163, #164, #166, #167, #168, #169

---

## Task 4: Data Pipeline Robustness (#123, #125, #126, #127, #128, #129, #131, #133)

**#123 — Unbounded table growth — no retention policy**
File: `src/scheduler/watch.py` or new `src/data_collection/retention.py`
Fix: Add a nightly retention job that runs during overnight mode. Delete rows older than:
- `scan_metrics`: 90 days
- `log_entries`: 30 days
- `activity_log`: 30 days
- `command_results`: 30 days
- `council_debug_log`: 60 days
Keep all data in `shadow_trades`, `training_examples`, `recommendations` (these are valuable forever).
Log count of pruned rows.

**#125 — Options collector NaN underlying_price not validated**
File: `src/data_collection/options_collector.py`
Fix: After fetching data, validate `underlying_price` is not NaN/None/0. If invalid, skip that ticker with a warning.

**#126 — EDGAR accession number format inconsistency**
File: `src/data_collection/edgar_collector.py`
Fix: Normalize accession numbers to consistent format (with dashes: `0001193125-21-123456`) before storage.

**#127 — EDGAR NLP UPDATE references columns not in table schema**
File: `src/data_collection/edgar_collector.py`
Fix: Verify columns exist before running NLP UPDATE. Use `PRAGMA table_info` check or try/except with ALTER TABLE fallback.

**#128 — CBOE ratio collector uses fragile regex**
File: `src/data_collection/cboe_collector.py`
Fix: Add fallback parsing. If regex fails, log WARNING and return None instead of all-None dict that looks like valid data.

**#129 — Short interest collector misuses conn.total_changes**
File: `src/data_collection/short_interest_collector.py`
Fix: Use `cursor.rowcount` or explicit SELECT COUNT after INSERT to get accurate record counts.

**#131 — Sync timezone handling uses naive datetime strings**
File: `src/sync/render_sync.py`
Fix: Ensure all datetime comparisons in sync use timezone-aware strings. Add `+00:00` suffix or use `datetime.now(UTC).isoformat()`.

**#133 — Enricher has no rate limit handling for Finnhub/SEC**
File: `src/data_enrichment/enricher.py`
Fix: Add simple rate limiting: track last request time per API, enforce minimum interval (Finnhub: 1s between calls, SEC: 0.1s). Use `time.sleep()` if needed.

**Tests:** ≥4 tests: retention prunes old rows, NaN price rejected, accession number normalized, rate limiter enforces interval.

**Closes:** #123, #125, #126, #127, #128, #129, #131, #133

---

## Task 5: Trading Logic Fixes (#99, #102, #104, #107, #108, #109, #144, #145)

**#99 — Race condition: duplicate position check is not atomic**
File: `src/shadow_trading/executor.py`
Fix: Use a SQLite transaction with `BEGIN IMMEDIATE` for the check-then-insert pattern. This prevents two concurrent scans from both passing the duplicate check.

**#102 — Alpaca API failure silently skips all price checks**
File: `src/shadow_trading/executor.py`
Fix: If `_get_current_price_safe()` returns None for a trade, increment a failure counter. If >50% of price checks fail in one cycle, send Telegram alert: "Alpaca API degraded — {count} price checks failed."

**#104 — Partial fills on bracket legs reported as fully protected**
File: `src/shadow_trading/bracket_monitor.py`
Fix: When checking bracket health, verify `filled_qty` matches expected qty on both stop and target legs. If partially filled, alert.

**#107 — Reconciliation backfills orphaned positions with wrong timestamps and zero protection**
File: `src/shadow_trading/reconcile.py`
Fix: When backfilling, set `stop_price=0` and `target_1=0` explicitly and log WARNING: "Backfilled {ticker} has no stop/target — manual intervention needed."

**#108 — Stale record closure during reconciliation missing P&L data**
File: `src/shadow_trading/reconcile.py`
Fix: When marking stale records as closed, try to fetch last known price from yfinance for P&L calculation. If unavailable, set `pnl_dollars=None` and `exit_reason='reconciled_stale'`.

**#109 — Daily loss limit uses unrealized P&L instead of realized losses**
File: `src/risk/governor.py`
Fix: Change daily loss check to only count realized (closed) trades from today, not unrealized positions.

**#144 — Traffic light persistence filter not idempotent**
File: `src/features/traffic_light.py`
Fix: Add a timestamp to regime transitions. Ignore persistence check if the last transition was <5 minutes ago (debounce).

**#145 — Sector exposure calculation uses stale entry prices**
File: `src/risk/governor.py`
Fix: Use current_price (from features) instead of entry_price for sector exposure calculation.

**Tests:** ≥4 tests: atomic duplicate check, Alpaca failure alert, realized-only daily loss, sector exposure uses current price.

**Closes:** #99, #102, #104, #107, #108, #109, #144, #145

---

## Task 6: Frontend Bug Fixes (#81, #134, #135, #138, #139, #140, #142)

**#81 — Frontend calls nonexistent cloud endpoints**
File: `frontend/src/api.js`
Fix: Verify every `fetchApi()` call has a matching route in `src/api/cloud_routes/`. Add missing route aliases or update api.js paths. Key gaps: `/scan`, `/training/history`, `/system/validation`.

**#134 — Missing api.getBuildScore() and api.getTrainingHistory()**
File: `frontend/src/api.js`
Fix: Add any missing API methods. Verify they match cloud backend endpoints.

**#135 — No per-page error boundaries**
File: `frontend/src/pages/*.jsx`
Fix: Create an `ErrorBoundary` component. Wrap each page's main content in it. On error, show "Something went wrong — try refreshing" instead of blank screen.

**#138 — ShadowLedger equity curve hardcodes $100K starting capital**
File: `frontend/src/pages/ShadowLedger.jsx`
Fix: Read starting capital from `/api/system/status` or `/api/config`. Fallback to $100K if unavailable.

**#139 — CTOReport crashes on partial API response**
File: `frontend/src/pages/CTOReport.jsx`
Fix: Add null checks on all data fields. Use optional chaining (`data?.field ?? defaultValue`). Show "No data available" for missing sections.

**#140 — No refetch after Council askStrategic mutation**
File: `frontend/src/pages/Council.jsx`
Fix: After the mutation succeeds, call `queryClient.invalidateQueries(['council'])` to trigger a refetch.

**#142 — Training page hardcodes outcome types**
File: `frontend/src/pages/Training.jsx`
Fix: Dynamically derive outcome types from the data instead of hardcoding. Use `[...new Set(data.map(d => d.outcome_type))]`.

**Tests:** Frontend builds clean: `cd frontend && npm run build`

**Closes:** #81, #134, #135, #138, #139, #140, #142

---

## Task 7: Frontend Security & UX (#136, #137, #141, #143, #148)

**#137 — AuthGate stores plaintext password as token with no expiry**
File: `frontend/src/components/AuthGate.jsx`
Fix: Hash the password before storing in sessionStorage. Add a 24-hour expiry timestamp. On each request, check expiry and force re-auth if expired.

**#136 — XSS risk in Docs page via dangerouslySetInnerHTML**
File: `frontend/src/pages/Docs.jsx`
Fix: Replace `dangerouslySetInnerHTML` with a sanitizer (DOMPurify if available, or switch to rendering markdown with `react-markdown`). If neither is practical, escape HTML entities before rendering.

**#148 — API_SECRET potentially exposed in client-side JavaScript bundle**
File: `frontend/src/config.js` or wherever the secret is referenced
Fix: Verify the API secret is NOT in the frontend bundle. If it is, move auth to a server-side proxy or use a session token pattern. The secret should only exist in `.env` on the server.

**#141 — No timezone conversion for displayed timestamps**
File: `frontend/src/` (multiple pages)
Fix: Create a `formatTimestamp(isoString)` utility that converts to user's local timezone. Apply to all displayed timestamps. Use `Intl.DateTimeFormat` for locale-aware formatting.

**#143 — Color-only status indicators without text/icon alternatives**
File: `frontend/src/pages/*.jsx`
Fix: Add text labels or icons alongside color-coded indicators. Examples: green dot + "Active" text, red dot + "Error" text. This improves accessibility.

**Tests:** Frontend builds clean: `cd frontend && npm run build`

**Closes:** #136, #137, #141, #143, #148

---

## Task 8: Sprint 6 Tasks 1-6 (Frontend Visibility)

These were designed but never executed. The full spec is in `docs/sprints/sprint-6-cc-pipeline-visibility.md` Tasks 1-6. Read that file and implement:

1. Wire api.js methods (3 new endpoints)
2. Data collectors grid on Training page (12 cards, freshness dots)
3. Training pipeline status (model, scoring progress, class balance)
4. Model history on Health page
5. Scan metrics sparkline on Dashboard
6. Card contrast fix (`.arcis-card` CSS class)

Follow the spec exactly. It has line numbers, component names, and CSS definitions.

**Closes:** Sprint 6 Tasks 1-6 (no issue numbers — these are from the sprint doc)

---

## Task 9: Config, Performance & Tech Debt (#83, #84, #85, #86, #92, #93, #95, #97, #98, #146, #149, #152, #165)

**#83 — Hardcoded ai_research_desk.sqlite3 in ~30 files**
Fix: Create a constant `DB_PATH` in `src/config.py`:
```python
import os
DB_PATH = os.environ.get("ARCIS_DB_PATH", "ai_research_desk.sqlite3")
```
Find/replace all hardcoded `"ai_research_desk.sqlite3"` default arguments with `from src.config import DB_PATH`. Do NOT change any function signatures — just default values.

**#84 — .env.example missing DATABASE_URL, ALPACA_BASE_URL, ALPACA_PAPER_TRADE**
Fix: Add all three to `.env.example` with comments.

**#85 — 73 modules without matching test files**
Fix: For the top 10 highest-risk modules, add minimal test files with at least 1 test each: executor, scan_service, watch, enricher, reconcile, bracket_monitor, traffic_light, governor, packet_writer, cloud analytics. Even a simple "module imports without error" test adds value.

**#86 — AGENTS.md API route count stale (55 vs 76)**
Fix: Run a count and update.

**#92 — No index on shadow_trades.status**
Fix: Add to `scripts/create_missing_tables.py`:
```sql
CREATE INDEX IF NOT EXISTS idx_shadow_trades_status ON shadow_trades(status);
CREATE INDEX IF NOT EXISTS idx_shadow_trades_status_time ON shadow_trades(status, actual_entry_time);
```
Also add to `scripts/render_migrate.py`.

**#93 — ~40 var(--slate-*) references in Dashboard.jsx and Council.jsx**
Fix: Replace all `var(--slate-*)` with equivalent `var(--arcis-*)` tokens across Dashboard.jsx and Council.jsx.

**#95 — config_overrides.py in wrong location**
Fix: Move `src/config_overrides.py` to `src/config/overrides.py`. Update all imports.

**#97 — No index on recommendations.created_at**
Fix: Add index to both migration scripts.

**#98 — Missing YAML config reference**
Fix: Add comprehensive inline comments to `config/settings.example.yaml` explaining each section and key.

**#146 — Research collector silently falls back to keyword scoring**
Fix: Log INFO when LLM is unavailable and falling back. Not a bug — just needs visibility.

**#149 — No market holiday awareness**
Fix: Add a simple holiday list for 2026 (NYSE calendar). In the scan scheduler, skip scans on holidays. Use a static list — no external dependency needed:
```python
NYSE_HOLIDAYS_2026 = {
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03",
    "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07",
    "2026-11-26", "2026-12-25",
}
```

**#152 — Computer sleep recovery**
Fix: Track `last_successful_scan_time`. If the gap between now and last scan is >30 minutes during market hours, log WARNING: "Possible sleep/crash recovery — {gap} minutes since last scan." Send Telegram alert.

**#165 — Config loaded once and cached forever**
Fix: Add a `reload_config()` function that clears the cache. Call it when a config override is applied from the command queue.

**Tests:** ≥5 tests: DB_PATH constant used, index creation, holiday detection, sleep gap detection, config reload.

**Closes:** #83, #84, #85, #86, #92, #93, #95, #97, #98, #146, #149, #152, #165

---

## Task 10: Documentation Update (MANDATORY)

1. Update AGENTS.md: all counts (files, tests, routes, tables, etc.)
2. CHANGELOG.md: Sprint 8 entry listing ALL closed issues
3. Regenerate `config/known_violations.json`
4. Update SYSTEM_STATE.md: set all referenced issues to closed, update sprint status
5. Verify:
```bash
python -m pytest tests/ -x -q
cd frontend && npm run build && cd ..
find tests -name "test_*.py" -exec grep -c "def test_" {} + | awk -F: '{s+=$2}END{print "Tests:", s}'
```

List all closed issues in the commit message.

---

## Summary: Issues Closed by Task

| Task | Issues | Count |
|---|---|---|
| 1 Training | #110, #111, #113, #114, #115, #116 | 6 |
| 2 Council | #117, #118, #119, #120, #121, #122 | 6 |
| 3 LLM | #153, #154, #156, #162, #163, #164, #166, #167, #168, #169 | 10 |
| 4 Data | #123, #125, #126, #127, #128, #129, #131, #133 | 8 |
| 5 Trading | #99, #102, #104, #107, #108, #109, #144, #145 | 8 |
| 6 Frontend bugs | #81, #134, #135, #138, #139, #140, #142 | 7 |
| 7 Frontend security/UX | #136, #137, #141, #143, #148 | 5 |
| 8 Sprint 6 Tasks 1-6 | (sprint doc) | 6 tasks |
| 9 Config/perf/debt | #83, #84, #85, #86, #92, #93, #95, #97, #98, #146, #149, #152, #165 | 13 |
| 10 Documentation | — | — |

**Total: ~63 issues + 6 Sprint 6 tasks = entire backlog cleared.**
