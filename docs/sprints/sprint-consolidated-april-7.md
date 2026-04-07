# Consolidated Sprint Package — April 7, 2026

> **5 sprints in execution order.** Each sprint is self-contained with its own
> branch, pre-flight, tasks, and documentation update.
>
> Sprint 1 and 2 can run in parallel (zero file overlap).
> Sprint 3 and 4 can run in parallel after 1+2 merge.
> Sprint 5 runs last — it's the full codebase refactor baseline.

---

## Sprint 1: Production Hotfixes (#318–321)

> **Priority:** CRITICAL — live-money bugs
> **Branch:** `fix/production-hotfixes-april`
> **Estimated time:** 1–2 hours
> **Tag:** v0.14.3
> **Closes:** #318, #319, #320, #321

### Pre-Flight

```bash
git checkout main && git pull origin main
git checkout -b fix/production-hotfixes-april
python -m pytest tests/ -x -q   # Record baseline pass count
cd frontend && npm run build && cd ..
```

### Task 1: Fix LLM conviction parsing regression (#318)

**Problem:** `conviction` parses as `None`, causing trades to hit the allocation
cap instead of being sized by conviction. The 5-strategy parse cascade in
`src/llm/packet_writer.py` (line ~253–350) is failing for the current model output format.

**Files:** `src/llm/packet_writer.py`

**Steps:**
1. Read `_parse_llm_response()` (line ~253). Understand the 5 parse strategies.
2. Check the current halcyon-v1.0.0 model's actual output format — pull 5 recent
   raw LLM responses from the `recommendations` table:
   ```sql
   SELECT raw_llm_response FROM recommendations
   ORDER BY created_at DESC LIMIT 5;
   ```
3. Identify which format the model is actually producing vs which formats the
   parser expects. The regression likely means v1 outputs a format none of the
   5 strategies match.
4. Add a 6th parse strategy that handles the actual output format.
5. Add a test with a real v1 response as fixture data.
6. Ensure `conviction=None` NEVER passes through to the executor — add a
   hard guard in `open_shadow_trade()` that rejects trades with `None` conviction
   and sends a Telegram alert.

**Test:** `pytest tests/test_llm_pipeline_hardening.py -v`

### Task 2: Fix paper positions flipped to short (#319)

**Problem:** Paper account shows short positions in a long-only system.

**Files:** `src/shadow_trading/executor.py`, `src/shadow_trading/alpaca_adapter.py`

**Steps:**
1. Query current paper positions via Alpaca API and check for any with `side=short`
   or negative `qty`.
2. Trace the order submission path in `open_shadow_trade()` (line ~135). Check
   that `side` is always `"buy"` and never derived from a variable that could
   flip sign.
3. Check `alpaca_adapter.py` — does `submit_bracket_order()` explicitly set
   `side="buy"`? Or does it inherit from a parameter?
4. Check if reconciliation (`reconcile_paper_trades`) could be marking positions
   as short during the sync process.
5. Add a hard assertion: `assert side == "buy"` before any order submission.
   A long-only system should fail loudly if it ever tries to go short.
6. Add a test that verifies `open_shadow_trade` always submits `side="buy"`.

### Task 3: Fix executor cross-broker mismatch (#320)

**Problem:** Live vs paper positions diverge — executor may be checking paper
positions when managing live trades or vice versa.

**Files:** `src/shadow_trading/executor.py`

**Steps:**
1. Read `check_and_manage_open_trades()` (line ~641). It accepts `source_filter`.
2. Verify that the `source_filter` is actually used to query only the correct
   trades from the DB. Check the SQL query on line ~660.
3. Check position_monitor.py — it calls `check_and_manage_open_trades` twice
   (once for paper, once for live). Verify the source_filter is passed correctly.
4. Check whether `_submit_exit_order()` (line ~115) uses the correct broker
   for the trade's source. A paper trade must exit via Alpaca paper API; a live
   trade must exit via the configured live broker.
5. Add a guard: if `trade["source"] == "live"` but the configured broker doesn't
   match, log an error and skip instead of silently using the wrong broker.
6. Add test coverage for the source_filter path.

### Task 4: Fix UnicodeEncodeError in reconcile-live CLI (#321)

**Problem:** `cp1252` codec can't encode emoji characters in CLI output.

**Files:** `src/cli/commands.py` (line ~403, `cmd_reconcile_live`)

**Steps:**
1. The safe_print wrapper at line ~78 should already handle this via
   `errors="replace"`. Check if `cmd_reconcile_live` bypasses `safe_print`
   and uses raw `print()` instead.
2. Find all `print()` calls in `cmd_reconcile_live` and replace with `safe_print`.
3. Also check for emoji usage in the reconcile output — the council emoji
   mapping at line ~1028 uses 🟢⚪🔴. Either strip emoji before printing or
   use ASCII equivalents in CLI output.
4. Add a test that calls `cmd_reconcile_live` with mocked data containing
   emoji characters on a non-UTF-8 stdout.

### Post-Flight

```bash
python -m pytest tests/ -x -q   # Pass count must not decrease
cd frontend && npm run build && cd ..
git add -A && git commit -m "fix: 4 production hotfixes (#318-321)

#318: conviction parsing — add 6th parse strategy for v1 format + None guard
#319: short positions — hard assert side=buy in long-only system
#320: cross-broker — verify source_filter in exit path + broker matching
#321: UnicodeEncodeError — route all CLI output through safe_print"

git tag -a v0.14.3 -m "v0.14.3 — 4 production hotfixes"
git push origin fix/production-hotfixes-april
git push origin v0.14.3
```

### Documentation

- Update MASTER.md Section 2: close #318-321, update issue count
- Update RELEASES.md with v0.14.3 entry
- Update CHANGELOG.md

---

## Sprint 2: Attribution Pipeline Wiring

> **Priority:** HIGH — existential validation question has zero data flowing
> **Branch:** `feat/attribution-wiring`
> **Estimated time:** 2–3 hours
> **Tag:** v0.15.0 (with Sprint 1 merged first)

### Context

The attribution module (`src/attribution/logger.py`) is fully implemented:
- `log_attribution_before_llm()` — Phase 1 logging
- `log_attribution_after_llm()` — Phase 2 logging
- `resolve_pending_outcomes()` — daily resolution at 4:30 PM
- `get_attribution_stats()` — dashboard API
- `simulate_mechanical_outcome()` — bracket simulation
- Schema table `attribution_trades` — 16 columns
- Dashboard page `Attribution.jsx` — 157 lines
- Tests in `test_attribution.py`

**The problem:** `log_attribution_before_llm` and `log_attribution_after_llm`
are NEVER called from anywhere in the pipeline. The scan service generates
packets and opens trades without logging attribution data. The attribution
table has zero rows. The existential question — does the LLM add alpha? — has
been accumulating zero evidence since system launch.

### Pre-Flight

```bash
git checkout main && git pull origin main
git checkout -b feat/attribution-wiring
python -m pytest tests/ -x -q
# Verify attribution_trades is empty:
python3 -c "
import sqlite3
from src.config import DB_PATH
with sqlite3.connect(DB_PATH) as conn:
    count = conn.execute('SELECT COUNT(*) FROM attribution_trades').fetchone()[0]
    print(f'attribution_trades rows: {count}')
"
```

### Task 1: Wire attribution into scan_service.py

**File:** `src/services/scan_service.py`

The scan pipeline currently flows:
```
rank_universe → get_top_candidates → [for each candidate]:
    build_packet_from_features → enhance_packet_with_llm → open_shadow_trade
```

Attribution must be injected BETWEEN ranking and LLM enhancement:

```
rank_universe → get_top_candidates → [for each candidate]:
    log_attribution_before_llm(ticker, score, entry, stop, target)  ← NEW
    enhance_packet_with_llm
    log_attribution_after_llm(attribution_id, llm_action, conviction) ← NEW
    open_shadow_trade
```

**Steps:**
1. After `get_top_candidates()` returns the candidate list, before the LLM
   enhancement loop, import `log_attribution_before_llm` and
   `log_attribution_after_llm` from `src.attribution.logger`.
2. For each candidate that passes ranking:
   a. Call `log_attribution_before_llm()` with the ranker score and mechanical
      bracket levels (entry_zone, stop_loss, take_profit from the packet).
   b. Run the LLM enhancement as normal.
   c. Determine `llm_action`:
      - `"taken"` if the trade was opened (conviction above threshold)
      - `"rejected"` if LLM conviction was below threshold
      - `"parse_failed"` if LLM response couldn't be parsed
      - `"conviction_none"` if conviction came back None
   d. Call `log_attribution_after_llm()` with the attribution_id from step (a),
      the llm_action, and the parsed conviction score.
3. Wrap attribution calls in try/except — attribution must NEVER block trade
   execution. Log warnings on failure, continue with the trade.

### Task 2: Wire outcome resolution into watch loop

**File:** `src/scheduler/watch.py`

The watch loop already calls `resolve_pending_outcomes` at 4:30 PM (line ~1388).
Verify this is working correctly:

1. Check that the import path matches the actual function location.
2. Check that `resolve_pending_outcomes` correctly fetches forward OHLCV data
   for pending rows and simulates mechanical bracket outcomes.
3. Add a second resolution path: when a shadow trade closes (via the position
   monitor), update the corresponding `attribution_trades` row with the
   `llm_portfolio_outcome` and `llm_portfolio_pnl_pct`. This creates the
   paired comparison: ranker-only outcome vs LLM-qualified outcome.

**New function in `src/attribution/logger.py`:**
```python
def link_trade_outcome(recommendation_id: str, outcome: str,
                       pnl_pct: float, db_path: str = DB_PATH) -> None:
    """Update attribution row with LLM portfolio outcome when trade closes."""
```

**Call site:** `src/shadow_trading/executor.py`, in the trade closure logic
(around line ~700 where `close_shadow_trade` is called). After closing a trade,
call `link_trade_outcome` with the recommendation_id, outcome, and P&L.

### Task 3: Add attribution stats to dashboard API

**Files:** `src/api/routes/system.py` or `src/api/cloud_routes/analytics.py`

1. Add a `/attribution/stats` endpoint that calls `get_attribution_stats()`.
2. Add a `/attribution/pairs` endpoint that returns recent paired comparisons
   (both ranker outcome and LLM outcome resolved).
3. Verify the Attribution.jsx dashboard page is reading from the correct
   endpoints and rendering the data.

### Task 4: Tests

**File:** `tests/test_attribution.py` (extend existing)

1. Test the full pipeline flow: scan_service calls attribution before/after LLM.
2. Test that attribution failure doesn't block trade execution.
3. Test outcome resolution with mock OHLCV data.
4. Test `link_trade_outcome` updates the correct row.

### Post-Flight

```bash
python -m pytest tests/ -x -q
cd frontend && npm run build && cd ..
git add -A && git commit -m "feat: wire attribution pipeline into scan service

Attribution logging now fires on every scan candidate:
- Phase 1 (before LLM): logs ranker score + mechanical brackets
- Phase 2 (after LLM): logs conviction + action taken/rejected
- Trade closure: links LLM portfolio outcome to attribution row
- Outcome resolution: simulates mechanical brackets at 4:30 PM daily

Every qualifying trade now generates a paired comparison:
ranker-only mechanical outcome vs LLM-qualified actual outcome."

git push origin feat/attribution-wiring
```

### Documentation

- Update MASTER.md: attribution now LIVE, not just DEPLOYED
- Add note that attribution data collection started [date]
- Statistical power note: need 50+ pairs for preliminary signal, 200+ for adequate

---

## Sprint 3: Simulation Engine Promotion

> **Priority:** MEDIUM — architectural hygiene
> **Branch:** `refactor/simulation-promotion`
> **Estimated time:** 2–3 hours

### Context

The simulation engine currently lives primarily in `scripts/simulation_engine.py`
(706 lines) with a thin 153-line wrapper in `src/simulation/`. The script has
all the regime definitions, Monte Carlo logic, traffic light validation, and
report generation. The `src/simulation/` module has only cache and monte_carlo
helpers.

### Pre-Flight

```bash
git checkout main && git pull origin main
git checkout -b refactor/simulation-promotion
python -m pytest tests/ -x -q
# Verify simulation works before refactor:
python scripts/simulation_engine.py --dry-run
```

### Task 1: Extract core engine into src/simulation/engine.py

**From:** `scripts/simulation_engine.py`
**To:** `src/simulation/engine.py`

Move the following into the module:
- Regime definitions (REGIMES dict with all 13 scenarios)
- `SimulationEngine` class (if one exists) or create one wrapping:
  - `run_single_regime()` — run one regime simulation
  - `run_all_regimes()` — run all 13 with optional Monte Carlo
  - `validate_traffic_light()` — compare TL predictions to simulation outcomes
  - `compute_deflated_sharpe()` — DSR calculation
  - `generate_report()` — structured result dict (not formatted output)
- YAML config loading

**Keep in script:** CLI argument parsing, formatted stdout output, PDF export.
The script becomes a thin wrapper:
```python
from src.simulation.engine import SimulationEngine
engine = SimulationEngine(config_path=args.config)
results = engine.run_all_regimes(monte_carlo=args.monte_carlo)
```

### Task 2: Wire into schema registry

**File:** `src/schema/registry.py`

Verify `simulation_results` table is properly registered. If the script was
writing directly via raw SQL, move the table definition to the registry and
use registry-based writes.

### Task 3: Wire API endpoints

**Files:** `src/api/routes/system.py`

Ensure endpoints exist:
- `GET /simulation/results` — latest simulation results
- `GET /simulation/regimes` — regime definitions and parameters
- `POST /simulation/run` (via command queue) — trigger a simulation run

Verify the Simulation.jsx dashboard page (350 lines) renders correctly from
these endpoints.

### Task 4: Update watch loop scheduling

**File:** `src/scheduler/watch.py`

The existing `_run_simulation_engine()` stub (line ~3251) likely shells out
to the script. Update it to import and call the engine directly:
```python
from src.simulation.engine import SimulationEngine
```

### Task 5: Tests

**File:** `tests/test_simulation_engine.py` (extend existing)

1. Test single regime simulation with mock data.
2. Test Monte Carlo produces correct number of samples.
3. Test traffic light validation logic.
4. Test that the script CLI still works as a thin wrapper.

### Post-Flight

```bash
python -m pytest tests/ -x -q
python scripts/simulation_engine.py --dry-run  # Script still works
cd frontend && npm run build && cd ..
```

### File size check

`src/simulation/engine.py` should be under 400 lines. If the extraction
produces a file over 400, split regime definitions into
`src/simulation/regimes.py` and report generation into
`src/simulation/report.py`.

---

## Sprint 4: Mean Reversion End-to-End Integration

> **Priority:** MEDIUM — MR trades can't open, only close
> **Branch:** `feat/mr-integration`
> **Estimated time:** 2–3 hours

### Context

Mean reversion (Strategy #2) has:
- ✅ Feature engine: `src/features/mean_reversion.py` (194 lines) — `scan_for_mr_candidates()`, `compute_mr_exit_signal()`
- ✅ Exit logic in executor: `check_and_manage_open_trades()` handles `strategy_type == "mean_reversion"` with RSI exit + timeout
- ✅ Config: `strategies.mean_reversion` with all parameters
- ✅ Setup classifier: identifies `mean_reversion` setup type
- ❌ **NO entry path**: `scan_for_mr_candidates()` is never called from the watch loop or scan_service
- ❌ **NO MR trade opening**: no code path actually opens an MR position
- ❌ **NO MR-specific LLM prompts**: packet_writer may use pullback prompts for MR candidates

### Pre-Flight

```bash
git checkout main && git pull origin main
git checkout -b feat/mr-integration
python -m pytest tests/ -x -q
# Count existing MR trades (should be 0 or very few):
python3 -c "
import sqlite3
from src.config import DB_PATH
with sqlite3.connect(DB_PATH) as conn:
    count = conn.execute(
        \"SELECT COUNT(*) FROM shadow_trades WHERE strategy_type='mean_reversion'\"
    ).fetchone()[0]
    print(f'MR trades: {count}')
"
```

### Task 1: Add MR scanning to the watch loop

**File:** `src/scheduler/watch.py`

Add an MR scan step AFTER the main pullback scan. MR runs at the same 30-min
cadence (Tier 2) but as a separate pass:

```python
# After the main pullback scan completes:
if config.get("strategies", {}).get("mean_reversion", {}).get("enabled", False):
    from src.features.mean_reversion import scan_for_mr_candidates
    from src.data_ingestion.market_data import fetch_ohlcv
    from src.universe.sp100 import get_sp100_universe

    universe = get_sp100_universe()
    ohlcv = fetch_ohlcv(universe)
    mr_candidates = scan_for_mr_candidates(ohlcv, config)
    # Process each candidate...
```

### Task 2: Add MR trade opening to executor

**File:** `src/shadow_trading/executor.py`

Create `open_mr_shadow_trade()` or extend `open_shadow_trade()` to accept a
`strategy_type` parameter:

1. MR trades use RSI-based exits, NOT bracket orders. The entry is a market
   order with no bracket attached.
2. The stop is tracked internally via `compute_mr_exit_signal()` — it's an
   ATR-based stop, not a broker stop-loss order.
3. Set `strategy_type = "mean_reversion"` in the shadow_trades row so the
   exit logic in `check_and_manage_open_trades()` routes correctly.
4. Respect `paper_only: true` — MR trades NEVER go to the live account.
5. Respect `max_positions: 5` — check current open MR positions before opening.

### Task 3: Add MR-specific LLM prompts

**File:** `src/llm/prompts.py`

The LLM should generate different commentary for MR setups than pullback setups.
An MR packet should explain:
- Why this stock is extremely oversold (RSI(2) value, cumulative 3-day return)
- Why the stock is still structurally sound (above 200 EMA)
- Expected mean reversion timeframe (1–5 days)
- Volume confirmation or divergence

Add a `get_mr_prompt()` function that builds the MR-specific system prompt.
Wire it into `packet_writer.py` based on `setup_type == "mean_reversion"`.

### Task 4: MR training data tagging

**File:** `src/training/data_collector.py`

When closed MR trades become training examples, they must be tagged with
`strategy_type = "mean_reversion"` so the training pipeline can:
- Apply MR-specific quality scoring criteria
- Balance MR vs pullback examples in the training mix
- Generate MR-specific contrastive pairs

### Task 5: Tests

1. Test `scan_for_mr_candidates()` returns candidates when RSI(2) < 10 and
   price above 200 EMA.
2. Test MR trade opening respects `paper_only` and `max_positions`.
3. Test MR exit signal fires when RSI(2) > 70.
4. Test that the watch loop's MR scan doesn't interfere with pullback scanning.
5. Test that MR candidates generate MR-specific (not pullback) LLM prompts.

### Post-Flight

```bash
python -m pytest tests/ -x -q
cd frontend && npm run build && cd ..
```

---

## Sprint 5: Codebase Refactor Baseline

> **Priority:** MEDIUM — establish tech debt baseline and begin decomposition
> **Branch:** `refactor/codebase-baseline`
> **Estimated time:** 4–6 hours
> **Tag:** v0.15.1 (or appropriate)

### Context

This is the first-ever dedicated refactoring sprint. The goal is NOT to
refactor the entire codebase. The goal is:

1. **Establish a measurable baseline** — how many violations, how much tech debt
2. **Fix the most dangerous violations** — watch.py decomposition Sprint 1
3. **Set up automated tracking** so future sprints can measure improvement

### Pre-Flight

```bash
git checkout main && git pull origin main
git checkout -b refactor/codebase-baseline
python -m pytest tests/ -x -q

# Capture baseline metrics
echo "=== BASELINE METRICS ==="
echo "Python files: $(find src/ -name '*.py' | wc -l)"
echo "Test files: $(find tests/ -name '*.py' | wc -l)"
echo "Total LOC: $(find src/ -name '*.py' -exec cat {} + | wc -l)"
echo "Files over 400 lines: $(find src/ -name '*.py' -not -name '__init__.py' -exec wc -l {} + | awk '$1 > 400' | wc -l)"
echo "Functions over 60 lines: TODO (run test_repo_structure.py and count warnings)"
echo "Known violations: $(python3 -c "import json; d=json.load(open('config/known_violations.json')); print(len(d.get('oversized_files',[])))")"

python -m pytest tests/test_repo_structure.py -v 2>&1 | grep "GRANDFATHERED" | wc -l
```

### Task 1: Create refactor tracking document

**File:** `docs/audits/refactor-baseline-2026-04.md`

Record the baseline state:
- Total files, LOC, test count
- Count of files over 400 lines (with line counts)
- Count of functions over 60 lines (with line counts)
- Count of known_violations.json entries
- List of the 10 most critical tech debt items ranked by risk

This becomes the benchmark. Every future refactor sprint measures against it.

### Task 2: Update known_violations.json

**File:** `config/known_violations.json`

The current file may have stale entries (line counts that no longer match).
Regenerate it from the actual codebase:

```python
# For each oversized file, record the ACTUAL current line count
# For each oversized function, record the ACTUAL current line count
# Remove entries for files/functions that no longer exist
# Add entries for NEW violations that appeared since last update
```

### Task 3: Extract overnight schedule from watch.py

**New file:** `src/scheduler/overnight.py`

Extract these methods from `watch.py`:
- `_run_post_close_capture()` (line ~2062)
- `_run_overnight_training_collection()` (line ~2131)
- `_run_news_ingestion()` (line ~2167)
- `_run_enrichment_precache()` (line ~2200)
- `_run_pre_market_refresh()` (line ~2232)
- `_run_data_collection()` (line ~2260)
- `_run_evening_handoff()` (line ~2479)
- `_run_morning_handoff()` (line ~2512)
- `_run_premarket_rolling_features()` (line ~3203)
- `_run_premarket_training()` (line ~3210)
- `_run_premarket_news_scoring()` (line ~3221)
- `_run_premarket_candidates()` (line ~3228)

**Rules:**
- Each extracted function must have the same signature and return type.
- watch.py imports and calls the extracted functions — zero behavior change.
- The extracted functions may need access to `self.config` — pass it as a
  parameter instead of relying on `self`.
- Run the full test suite after extraction. Every test must still pass.

**Expected result:** watch.py drops by ~800–1,000 lines.

### Task 4: Extract reporting from watch.py

**New file:** `src/scheduler/reports.py`

Extract these methods:
- `_send_premarket_brief()` (line ~2641)
- `_send_eod_report()` (line ~2766)
- `_send_data_asset_report()` (line ~2880)
- `_send_weekly_digest()` (line ~2990)
- `_run_saturday_reports()` (line ~1942)

**Same rules as Task 3.** Expected: another ~600–800 lines removed from watch.py.

### Task 5: Extract telegram.py into domain modules

**Current:** `src/notifications/telegram.py` (1,563 lines, 55+ functions)

Split into:
- `src/notifications/telegram_core.py` — `send_message()`, `send_photo()`,
  `is_telegram_enabled()`, rate limiting, command polling
- `src/notifications/telegram_trades.py` — `notify_trade_opened()`,
  `notify_trade_closed()`, `notify_trade_milestone()`, etc.
- `src/notifications/telegram_system.py` — `notify_startup()`,
  `notify_validation_summary()`, `notify_daily_summary()`, etc.
- `src/notifications/telegram_reports.py` — `notify_scoring_summary()`,
  `notify_council_result()`, `notify_data_asset_report()`, etc.

Each file should be under 400 lines. Update all import sites.

### Task 6: Measure improvement

After all extractions, re-run the baseline metrics from Pre-Flight:
- How many files over 400 lines now? (Target: reduce by 2–3)
- How many lines is watch.py now? (Target: under 2,000, ideally under 1,500)
- How many lines is telegram.py now? (Target: split into 4 files, each under 400)
- Did any tests break? (Must be zero)

Record the post-refactor metrics in the same tracking document from Task 1.

### Task 7: Update known_violations.json

Remove entries for:
- watch.py (if under the new threshold — likely still over 400 but smaller)
- telegram.py (should be deleted, replaced by 4 smaller files)

Add entries for any new files that ended up over 400 despite best efforts.

### Post-Flight

```bash
python -m pytest tests/ -x -q   # ALL tests must pass
cd frontend && npm run build && cd ..

# Record final metrics
echo "=== POST-REFACTOR METRICS ==="
echo "watch.py: $(wc -l < src/scheduler/watch.py) lines"
echo "Files over 400: $(find src/ -name '*.py' -not -name '__init__.py' -exec wc -l {} + | awk '$1 > 400' | wc -l)"
```

### Documentation

- Update MASTER.md with new file counts and module structure
- Update DIRECTORY.md if file locations changed
- Add `docs/audits/refactor-baseline-2026-04.md` with before/after metrics
- CHANGELOG entry for the refactor

---

## Execution Order

```
Phase 1 (parallel):
  Terminal 1: Sprint 1 — fix/production-hotfixes-april
  Terminal 2: Sprint 2 — feat/attribution-wiring

Phase 2 (after Phase 1 merges):
  git checkout main && git merge fix/production-hotfixes-april
  git tag -a v0.14.3 -m "v0.14.3 — production hotfixes"
  git merge feat/attribution-wiring

Phase 3 (parallel):
  Terminal 1: Sprint 3 — refactor/simulation-promotion
  Terminal 2: Sprint 4 — feat/mr-integration

Phase 4 (after Phase 3 merges):
  git merge refactor/simulation-promotion
  git merge feat/mr-integration
  git tag -a v0.15.0 -m "v0.15.0 — attribution + simulation + MR integration"

Phase 5 (sequential):
  Sprint 5 — refactor/codebase-baseline
  git tag -a v0.15.1 -m "v0.15.1 — codebase refactor baseline"
```

---

## Ralph Loop Verification

### Iteration 1 gaps found and fixed:
- Attribution sprint initially didn't include `link_trade_outcome` for closing
  trades — added Task 2 step 3 for closing the LLM side of the paired comparison
- MR sprint didn't address LLM prompts — MR candidates would get pullback-style
  commentary. Added Task 3 for MR-specific prompts
- Refactor sprint initially tried to extract ALL of watch.py in one go — scoped
  down to overnight + reports only (Tasks 3+4), which is ~1,400 lines and the
  safest extraction targets

### Iteration 2 gaps found and fixed:
- Hotfix sprint Task 1 didn't specify HOW to get real model output format —
  added SQL query to pull 5 recent raw responses from recommendations table
- Attribution sprint didn't specify error isolation — added try/except
  requirement so attribution never blocks trade execution
- MR sprint didn't check existing MR trade count in pre-flight — added
- Simulation sprint didn't include a script backward-compat check — added
  `python scripts/simulation_engine.py --dry-run` to post-flight
- Refactor sprint Task 5 (telegram split) — specified the 4 target files and
  their responsibilities to prevent CC from making arbitrary splits

### Iteration 3 gaps found and fixed:
- Hotfix sprint Task 2: checked `reconcile_paper_trades` as potential source
  of short positions — added step 4
- Attribution sprint: verified watch.py already has resolve_pending_outcomes
  at 4:30 PM (line ~1388) — no duplicate needed, just verify it works
- MR sprint Task 2: specified that MR trades do NOT use bracket orders (RSI
  exit is internal, not broker-level) — this is the key architectural difference
- Refactor sprint: added Task 2 to refresh known_violations.json BEFORE
  starting extractions, so the baseline is accurate
- All sprints: verified zero file overlap between Sprint 1 and 2 (hotfix
  touches executor/packet_writer/commands, attribution touches scan_service
  /attribution/watch — no conflicts)
