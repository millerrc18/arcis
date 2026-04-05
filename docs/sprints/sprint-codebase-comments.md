# Sprint: Codebase Documentation + Issue Resolution — Comments, Cross-References, and Bug Fixes

> **Priority:** HIGH — resolves all open issues + builds context for future CC sessions
> **Estimated time:** 8-12 hours CC time
> **Why this matters:** AI agents (CC, Codex) are the sole developers. They lose context between sessions. Comments in the code ARE the context. Additionally, 11 open GitHub issues need resolution — this sprint combines both to produce a clean, well-documented, zero-issue codebase.

> ⚠️ **Rules:**
> - For **commenting tasks** (Phases 1-5): Do NOT change any logic, behavior, or formatting. Comments ONLY.
> - For **issue resolution** (Phase 0): Fix the bugs. Verify each fix with tests.
> - Run `python -m pytest tests/ -x -q` before AND after. Pass count must not decrease.
> - If a file is over 400 lines, do NOT add so many comments that it exceeds the guardrail.
> - Close each GitHub issue after fixing with a comment referencing the commit.

---

## Phase 0: Resolve All 11 Open GitHub Issues

**Fix these FIRST, before commenting. Each fix gets a comment explaining what was wrong and why.**

### #248 — Bracket monitor false alarms (TRADING BUG)
**File:** `src/shadow_trading/alpaca_adapter.py` — `_serialize_order()`
**Problem:** `str(order.status)` returns `"orderstatus.held"` instead of `"held"`. The bracket monitor compares against `"held"` and never matches → false alerts.
**Fix:** Strip the enum prefix: `status = str(order.status).split(".")[-1]` or use `.value` if the Alpaca enum supports it. Add comment explaining the fix referencing #248.

### #249 — System validator reads YAML for secrets instead of env vars (BUG)
**File:** `src/evaluation/system_validator.py`
**Problem:** Validator checks `config.get("telegram", {}).get("bot_token")` which reads YAML. But secrets are in `.env` / `os.environ`, not YAML. Shows false CRITICAL.
**Fix:** Check `os.environ.get("TELEGRAM_BOT_TOKEN")` instead of config YAML for credential checks. Same for `ALPACA_LIVE_API_KEY`. Add comment explaining #249.

### #250 — Charts invisible in dark mode (FRONTEND BUG)
**File:** Multiple frontend pages — Dashboard, Health, Council, ShadowLedger
**Problem:** CSS variables undefined or chart fill opacity too low against dark backgrounds.
**Fix:** Define missing CSS variables in the root theme. Increase chart fill opacity from ~0.1 to ~0.3 for dark mode. Check every Recharts `<Area>` and `<Line>` component for hardcoded colors that don't respect theme.

### #251 — Packet commentary wildly inconsistent (LLM BUG)
**File:** `src/llm/packet_writer.py`
**Problem:** Some packets show raw template headers (`=== TECHNICAL RECOMMENDATION ===`) instead of prose. The LLM is regurgitating the prompt structure.
**Fix:** Add post-processing to strip template headers from LLM output. If output contains `===` section markers, clean them before storing. Add comment explaining this is a known model behavior and the cleaning is intentional, referencing #251.

### #253 — Open positions show no P&L (FRONTEND/BACKEND BUG)
**File:** `src/api/cloud_routes/trades.py`
**Problem:** `total_unrealized_pnl` is hardcoded to 0 (line 40, 52). Open trades have no current price to compute P&L against.
**Fix:** For each open trade, fetch current price (from the last scan's feature snapshot, NOT a live API call — too expensive). Compute `(current_price - entry_price) * shares`. Also add columns to the ledger tables: entry price, current price, shares, P&L %, days held.

### #254 — Max consecutive losses hardcoded to 0 (BUG)
**File:** `src/api/cloud_routes/analytics.py` line 175
**Problem:** `"max_consecutive_losses": 0` is hardcoded. The real calculation exists in `cto_report.py` (lines 218-223) but isn't wired in.
**Fix:** Import the real calculation and use it. Wire `_compute_max_consecutive("loss")` from cto_report into the analytics endpoint. Also fix "System Health grid all Off" — likely missing data source connections.

### #247 — Metric cards not centered (FRONTEND)
**File:** Multiple dashboard pages — Dashboard.jsx, Training.jsx
**Fix:** Add `text-center` class consistently to all metric card containers. Audit every `arcis-card` usage for alignment.

### #252 — Stress Test needs Run button (ENHANCEMENT)
**File:** `frontend/src/pages/StressTest.jsx`, `src/commands/executor.py`
**Fix:** Add a `stress-test` command to COMMAND_HANDLERS. Add a "Run Stress Test" button on the StressTest page that calls `api.submitCommand("stress-test")`. Show progress via polling or SSE.

### #255 — DB Schema and Architecture diagrams need polish (FRONTEND)
**File:** `frontend/src/pages/Architecture.jsx`, `frontend/src/pages/DBSchema.jsx`
**Fix:** Improve React Flow node styling: larger padding, readable font size, group header nodes, better dark mode colors. This is visual polish, not functional.

### #239 — Daily repo audit regression (CI)
**File:** Check `scripts/daily_repo_audit.py` and the baseline
**Fix:** Investigate what "unexpected regression" means — likely a baseline that needs updating after v0.11.0 changes. Update `config/daily_repo_audit_baseline.json` if the regression is expected (new files, changed test counts).

### #222 — Telegram Claude Code pairing (MANUAL)
**Problem:** Telegram pairing command not working from CC.
**Fix:** This may be a configuration issue. Check if the bot token is correct in `.env`, verify the chat_id is right. If it's a CC plugin issue, document the workaround. If it can't be fixed programmatically, close with a note explaining the manual workaround.

**After fixing all 11 issues:**
```bash
# Verify all issues are resolved
python -m pytest tests/ -x -q
cd frontend && npm run build
# Close each issue on GitHub with a commit reference
```

---

## What Good Comments Look Like

**BAD (what the code does — reader can see that):**
```python
# Get the account info
account = get_account_info()

# Check if VIX is above 35
if vix > 35:
```

**GOOD (why the code does it — reader can't see that):**
```python
# Alpaca paper account — used for Phase 1 bootcamp tracking (not live capital)
account = get_account_info()

# VIX > 35 = extreme fear. Strategy Decision #6: halt all new entries.
# Historically, VIX > 60 is a 100% reliable buy signal, but 35-60 is
# a regime where pullback setups have negative expectancy.
if vix > 35:
```

**Comment priorities (in order):**
1. **WHY** decisions were made — link to strategy decisions, research docs, or incidents
2. **GOTCHAS** that would bite a future agent — "don't use time.sleep() here because..."
3. **BUSINESS LOGIC** explanations — "bootcamp phase uses 50 max positions because..."
4. **MAGIC NUMBERS** — "2.0 ATR multiplier per Strategy Decision #18, optimal through 200 trades"
5. **DATA FLOW** — "this value comes from X, feeds into Y, consumed by Z"

---

## GitHub Issue Rectification — MANDATORY

**Every bug fix, workaround, type cast, or defensive pattern in the codebase must reference the GitHub issue that caused it.** This is critical because AI agents are the sole developers — without issue references, the context for WHY a `float()` cast or a `try/except` exists is lost forever.

**Step 1: Get the full closed issue list.** Run:
```bash
# Get all closed issues with titles
gh issue list --state closed --limit 200 --json number,title | python3 -c "
import json, sys
for i in json.load(sys.stdin):
    print(f'#{i[\"number\"]}: {i[\"title\"]}')
"
```

Or if `gh` CLI isn't available, read this reference list of key issues and their fixes:

| Issue | Root Cause | Where the fix lives |
|---|---|---|
| #181 | SQLite database corruption from OneDrive sync | Schema registry (`src/schema/registry.py`), recovery script |
| #182 | Reconciliation crash: `name 'now' not defined` | `watch.py` — restructured in PR #203 |
| #183 | Conviction parsing 99% broken (143/145 None) | `llm/packet_writer.py` — 5 extraction patterns added |
| #184 | Recovery DB missing 11 time columns | Schema registry auto-creates on startup |
| #185 | Postgres duplicate key violations | `render_sync.py` — `ON CONFLICT DO NOTHING` |
| #186 | Postgres missing `last_transition_at` | Added to schema registry |
| #187 | 44 failed shadow trades — buying power | Paper buying power check in executor |
| #188 | PFE -14 shares — short in long-only | Negative shares guard in reconcile backfill |
| #191 | reconcile.py exceeds 400-line guardrail | Extracted helper functions |
| #195 | TypeError: pnl_dollars returned as string | `float()` cast in data_collector |
| #196 | Duplicate exit orders without cancel | `cancel_paper_order()` before retry |
| #197 | Finnhub API key in URL query params | `X-Finnhub-Token` header |
| #198 | VRAM handoff lacks aggressive cleanup | Escalation in `vram_manager.py` |
| #199 | Render sync single connection, no recovery | Per-table reconnection |
| #106 | Kill switch not atomic, no staleness | Atomic write + staleness check |
| #112 | VRAM not freed after training | `torch.cuda.empty_cache()` |
| #132 | Fallback to placeholder API keys | Config validation on load |
| #147 | No exponential backoff on network failures | Retry utility applied everywhere |

**Step 2: For every fix in the codebase, add the issue reference.**

Examples of what to add:

```python
# Fix for #195: SQLite returns TEXT for numeric columns after DB recovery.
# pnl_dollars was "5.25" (string), not 5.25 (float). abs("5.25") throws TypeError.
pnl = float(trade.get("pnl_dollars", 0) or 0)

# Fix for #185: Postgres duplicate key violations during sync after DB recovery.
# Use ON CONFLICT DO NOTHING instead of failing the entire sync batch.
sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"

# Fix for #197: Finnhub API key was exposed in URL query params and logged in plaintext.
# Moved to X-Finnhub-Token header per Finnhub API docs.
headers = {"X-Finnhub-Token": api_key}

# Fix for #183: LLM conviction parsing was 99% broken. The model outputs conviction
# in 5+ different formats. These fallback patterns cover all observed formats:
# 1. <metadata>Conviction: 7</metadata> (XML, original format)
# 2. <conviction>7</conviction> (model-preferred tag)
# 3. Conviction: 7/10 (plain text with denominator)
# 4. **Conviction:** 7 (markdown bold)
# 5. CONVICTION: 7 (uppercase plain text)

# Fix for #196: Shadow trading exit retry submitted duplicate orders without
# canceling pending ones. Now cancel first, then resubmit.
cancel_paper_order(existing_order_id)

# Guard for #188: PFE was backfilled with -14 shares (short position in long-only system).
# Negative shares should never exist — reject at backfill time.
if shares < 0:
    logger.warning("[RECONCILE] Rejecting negative shares for %s: %d", ticker, shares)
    continue
```

**Step 3: For strategy decisions, reference the decision number.**

```python
# Strategy Decision #18: Mechanical bracket exits are optimal through 200 trades.
# Don't over-engineer exit management until we have statistical significance.
stop_price = entry_price - (atr * 2.0)  # 2.0 ATR per Decision #18

# Strategy Decision #22: 4-tier multi-cadence scanning.
# 15min positions / 30min universe / 60min sentiment / daily fundamentals
POSITION_MONITOR_INTERVAL = 900  # 15 min — Tier 1 (Decision #22)

# Strategy Decision #6: Equal weight (1/N) beats all optimization methods until 200+ trades.
# Don't try Kelly criterion, risk parity, or HRP until we have enough data.
weight = 1.0 / max_positions
```

**Step 4: For research-backed decisions, cite the paper.**

```python
# McLean & Pontiff (2015): 58% post-publication anomaly decay for academic factors.
# This is why we DON'T use published factors like momentum/value at face value —
# the edge has been arbitraged away for S&P 100 stocks.

# Martineau (2022), Subrahmanyam (2025): PEAD is dead for large-cap stocks.
# Eliminated as Strategy #2 candidate in favor of mean reversion.

# Golden ratio: He et al. (2025) — 62/38 curated-to-synthetic data ratio
# prevents model collapse while maximizing training data volume.
GOLDEN_RATIO = 0.62
```

**DO NOT SKIP THIS SECTION.** Every `float()` cast, every `try/except`, every `ON CONFLICT`, every magic number, every `if` guard that looks defensive — find the issue or decision that caused it and add the reference. If you can't find the issue, add `# Defensive guard — issue number unknown` so a future agent knows to investigate.

---

## Phase 1: Critical Path Files (do these first)

These are the files CC modifies most often and where context loss causes the most bugs.

### 1.1 `src/scheduler/watch.py` (~3,080 lines)
The main loop. Every scan, trade, and overnight task flows through here.
- Comment each numbered section (0, 0.5, 1, 1.5, 2, 2.5, 3...) explaining WHAT triggers it and WHY at that time
- Comment the timing constants (why 15 min for position monitor, why 30 min for scans, why 60 min for sentiment)
- Comment the daily reset block — what state gets cleared and why
- Comment the overnight collector list — what each one does and which API it calls
- Comment the sleep recovery detection — why it matters (computer sleep during market hours killed scans)
- Comment the backoff/retry mechanism — what triggers escalation
- Comment `_get_live_stats()` — where each stat comes from and what "N/A" means

### 1.2 `src/shadow_trading/executor.py` (~1,436 lines)
The trade execution engine. Wrong behavior here = lost money.
- Comment `open_shadow_trade()` — the full decision chain (qualify → governor → bracket → log)
- Comment paper vs live dispatch — when each fires and why they have different risk params
- Comment the ATR-based stop/target calculation — reference Strategy Decision #18
- Comment `check_and_manage_open_trades()` — each exit path (stop, target, timeout, MR RSI exit)
- Comment the MR exit dispatcher — why it runs BEFORE bracket logic (strategy-aware exits)
- Comment the dual execution block — paper always fires, live only if enabled + governor passes
- Comment why `_parse_price()` exists (LLM outputs prices in various formats)
- Comment the attribution logging points — Phase 1 (before LLM) and Phase 2 (after)

### 1.3 `src/shadow_trading/alpaca_adapter.py` (~549 lines)
The broker interface. Alpaca API quirks live here.
- Comment each function's retry behavior and failure mode
- Comment `place_bracket_order()` — GTC semantics, what happens if partial fill
- Comment paper vs live client initialization — different base URLs, different keys
- Comment notional ordering (fractional shares) vs share ordering — when each is used
- Comment `_serialize_order()` — why it exists (Alpaca Order objects aren't JSON serializable)

### 1.4 `src/schema/registry.py` (~1,386 lines)
49 tables. Every column should say WHY it exists.
- Add a one-line comment above each `TableDef` explaining what it tracks and who writes to it
- For columns with non-obvious purposes (like `drawdown_from_mfe`), add inline comments
- Comment the sync configuration (sync_to_postgres, sync_mode, sync_time_column) — when and why

### 1.5 `src/features/regime.py` + `src/features/engine.py` + `src/features/setup_classifier.py`
The feature pipeline determines what the model sees.
- Comment the traffic light logic — what each regime label means for trading
- Comment the scoring weights — why pullback_depth is weighted higher than volume
- Comment each technical indicator — what it measures and what good/bad values look like
- Comment the 7 signal dimensions — reference Alternative Data research doc

---

## Phase 2: AI/Training Pipeline

### 2.1 `src/training/data_collector.py`
- Comment the self-blinding architecture — why outcome data is NEVER in the prompt
- Comment the outcome-conditioned template block — why output_text is empty (batch later)
- Comment the quality gate (halt_batch) — when and why training halts

### 2.2 `src/training/trainer.py` (~794 lines)
- Comment the curriculum stages (structure → evidence → decision)
- Comment the learning rate schedule (3e-4 → 2e-4 → 1e-4)
- Comment the champion-challenger evaluation — what triggers a rollback
- Comment the VRAM handoff — why training and inference can't run simultaneously on 12GB

### 2.3 `src/training/outcome_prompts.py`
- Comment WHY each prompt template is worded the way it is (reference Prompt Engineering research)
- Comment the self-blinding guarantee — the template shapes analysis FOCUS, not CONCLUSION
- Comment the contrastive pair generation — these become DPO training pairs

### 2.4 `src/llm/packet_writer.py`
- Comment the LLM prompt construction — what XML tags the model expects
- Comment `_parse_llm_response()` — each fallback pattern and when it activates
- Comment the conviction extraction — the 5 patterns and their priority order
- Comment the prose fallback — when no XML tags are found at all

---

## Phase 3: Risk & Evaluation

### 3.1 `src/risk/governor.py`
- Comment each of the 8 checks with its threshold and WHY that threshold
- Comment the kill switch mechanism — file-based persistence across restarts
- Comment the graduated drawdown — Ed Thorp's protocol, linear 100%→0% from 0%→20% DD

### 3.2 `src/council/engine.py` (~554 lines)
- Comment the Modified Delphi protocol — why 3 rounds, what changes between rounds
- Comment each agent role and what perspective it brings
- Comment the consensus calculation — how votes translate to traffic light
- Comment the anti-sycophancy interventions — what prevents agents from just agreeing

### 3.3 `src/evaluation/build_score.py` + `src/evaluation/hshs_live.py`
- Comment the 6 build score components and their geometric mean
- Comment HSHS (Health Score) — 5 dimensions, phase weighting
- Comment the float() casts — WHY they're there (SQLite TEXT column incident #181)

---

## Phase 4: API Routes & Infrastructure

### 4.1 All files in `src/api/routes/` (14 files, mostly 0% comments)
- Add a comment block at the top of each route file listing the endpoints it serves
- Comment any route that does something non-obvious (e.g., `/actions/cto-report` submits `cto-report` command, not `scan`)
- Comment auth handling — when Bearer token is required vs optional

### 4.2 `src/sync/render_sync.py` (~737 lines)
- Comment the sync architecture — pull-based, local SQLite → Render Postgres
- Comment `ON CONFLICT DO NOTHING` — why it's there (incident #185)
- Comment per-table reconnection — why each table retries independently
- Comment the sync_interval and batch size choices

### 4.3 `src/notifications/telegram.py` (~1,494 lines)
- Comment which notifications are gated behind `trade_id` and why
- Comment the 32 notification functions — group by category
- Comment rate limiting and message formatting

---

## Phase 5: Scripts

### 5.1 All files in `scripts/` (35 files)
- Each script should have a module docstring explaining:
  - When to run it (daily? weekly? one-time?)
  - What it reads and writes
  - Any prerequisites (env vars, running services)
- Comment any non-obvious shell commands or SQL queries

---

## Verification

After ALL commenting and issue resolution is complete:
- `python -m pytest tests/ -x -q` — pass count ≥ baseline
- `cd frontend && npm run build` — succeeds
- `python -m src.main watch --help` — still works
- `wc -l src/scheduler/watch.py` — should not exceed ~3,300 (was 3,080, comments add ~7%)
- Spot check: open 5 random files and verify comments explain WHY, not WHAT

**Issue resolution check:**
```bash
# All 11 issues should be closed
gh issue list --state open --limit 20
# Expected: 0 open issues
```

**Issue rectification check:**
```bash
# Every closed issue should be referenced at least once in the codebase
for issue in 82 106 112 132 147 181 182 183 184 185 186 187 188 191 195 196 197 198 199 222 239 247 248 249 250 251 252 253 254 255; do
  count=$(grep -rn "#$issue" src/ scripts/ frontend/src/ --include="*.py" --include="*.jsx" --include="*.js" | grep -v __pycache__ | wc -l)
  echo "#$issue: $count references"
done
```
Target: every issue has ≥1 reference in the file where its fix lives. Issues with 0 references need a comment added.

---

## Commit

Split into 2 commits for clean history:

```bash
# Commit 1: Issue resolution
git add -A
git commit -m "fix: resolve all 11 open GitHub issues

Bugs fixed:
- #248: Bracket monitor false alarms — strip Alpaca enum prefix from order status
- #249: System validator reads YAML for secrets — check os.environ instead
- #250: Charts invisible in dark mode — define missing CSS vars, increase fill opacity
- #251: Packet commentary inconsistent — strip raw template headers from LLM output
- #253: Open positions show no P&L — compute unrealized P&L from last scan prices
- #254: Max consecutive losses hardcoded to 0 — wire real calculation from cto_report

Enhancements:
- #247: Metric cards centered consistently across all pages
- #252: Stress test Run button via command queue
- #255: DB Schema + Architecture diagram styling polish
- #239: Daily repo audit baseline updated for v0.11.0
- #222: Telegram pairing documented/resolved

Closes #222, #239, #247, #248, #249, #250, #251, #252, #253, #254, #255"

# Commit 2: Codebase documentation
git add -A
git commit -m "docs: comprehensive inline comments + GitHub issue rectification

Added WHY-focused comments to every Python module in src/ and scripts/.
Every bug fix, workaround, and defensive pattern now references its
GitHub issue number for full traceability.

Comment categories:
- Business logic rationale with strategy decision references (#1-#24)
- Bug fix provenance with GitHub issue cross-references (#82-#255)
- Research citations with paper references (McLean & Pontiff, etc.)
- Gotchas and failure modes for future AI agents
- Magic number explanations with decision traceability

30 closed issues cross-referenced across the codebase.
Zero additional logic changes in commit 2. Test count unchanged."
```

After both commits, tag and push:
```bash
git tag -a v0.12.0 -m "v0.12.0 — 11 issues resolved, comprehensive codebase documentation

0 open issues. 30 closed issues cross-referenced in code.
Inline comments on all 200+ Python files."
git push origin main && git push origin v0.12.0
```

Update MASTER.md Section 2 (GitHub issues: 0 open) and RELEASES.md with v0.12.0 entry.
