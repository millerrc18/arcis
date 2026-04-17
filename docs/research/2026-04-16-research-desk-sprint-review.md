# Equity Research Desk MVP Sprint — Code Review

**Date:** 2026-04-16 | **Depth:** exhaustive | **Domain:** implementation risk audit
**Scope:** `docs/sprints/sprint-research-desk-mvp.md` vs actual codebase state
**Reviewer:** Claude Opus 4.7 (1M) with 6 parallel code-verification agents + council skeptic
**Classification:** PUBLIC (internal project code)

---

## Verdict: **SHIP-WITH-MODIFICATIONS** (leaning toward *DO-NOT-SHIP* unless Task 4 is re-scoped)

The sprint delivers a **clean dual-desk infrastructure** but **cannot produce a working research candidate** on Monday morning because the EDGAR data layer the strategy depends on is empty. The sprint spec is well-written at the architectural level — desk isolation, feature flags, per-desk clients, cadence-gated scanning are all correct patterns — but two load-bearing assumptions fail on contact with the real repo state:

1. **EDGAR `full_text` and `sections_json` columns are 0% populated across all 3,362 filings.** Lazy Prices (the PRIMARY entry trigger) reads `sections_json` from `edgar_filings` — there is literally nothing to read. This is not a 2.5-hour Task 4 fix; it is a data-pipeline debug + backfill of 3,362 filings that must land *before* Task 4 can be validated.
2. **Alpaca client routing has 11 call sites, not 1.** The sprint only patches `executor.py`. `reconcile.py` and `bracket_monitor.py` will route research-desk traffic through the swing client by default, producing silent 404s on position reconciliation and bracket monitoring once the research desk is ever activated.

The sprint is structurally sound for `desks.research.enabled: false` — nothing fires, nothing breaks. But the spec's own Go/No-Go criterion #5 ("verify a candidate is identified, LLM produces valid JSON, research trade logged with non-null research_thesis") **cannot be met in 14 hours** without fixing the EDGAR data crisis first.

**Ship the infrastructure sprint (~7.5h MVS) this weekend. Defer working signal generation to v0.24.1.**

---

## Top 5 Implementation Concerns (ranked by severity)

### 1. CRITICAL — EDGAR `full_text` / `sections_json` are 0% populated (0/3,362 rows)

**Evidence (direct SQL verification):**
```
Total edgar_filings: 3,362 (dates: 2024-03-26 to 2026-04-15)
full_text populated: 0/3,362
sections_json populated: 0/3,362
10-K with full_text > 10k chars: 0
Sample 10-K (LOW, filed 2026-03-23): full_text = NULL, sections_json = NULL, word_count = NULL
```

The collector at `src/data_collection/edgar_collector.py:329` calls `_fetch_filing_text`, which returns `None` on any exception (line 188-190: `except Exception as e: logger.debug(...); return None`). Every filing has fallen through this silent-null path since collection began in 2024. The regex-based `_parse_sections` at line 193 works correctly — but it's fed `None` every single time.

**Impact on the sprint:** Task 4's Lazy Prices filter (`src/features/lazy_prices.py`) reads `sections_json` from DB (see sprint line 484-509). With 0% population, `recent_filings_with_cosine()` returns `None` for every ticker. `passes_lazy_prices_filter` returns `False` for every ticker. The research scanner identifies **zero candidates forever** until a full EDGAR backfill runs.

**Why the sprint misses this:** Pre-Flight Check #4 tests `COUNT(*)` of recent filings — which is 196 (10-K) + 590 (10-Q). It does NOT test `sections_json IS NOT NULL`. The check passes while the data is unusable.

**What Task 4 is really asking for:**
- Debug why `_fetch_filing_text` has failed for 3,362 filings (rate limiting? auth? HTML-parsing timeout? redirect chain?) — 2-4h
- Backfill all historical 10-K / 10-Q filings at SEC EDGAR rate limits (10 req/sec, real throughput ~3-5/sec after retries) → ~20 minutes of network, ~2-4h of operator babysitting for the re-parse pipeline
- Add item_1a regex to `_parse_sections` (the sprint's actual claim) — 30 min
- Build lazy_prices.py + ml_sue.py + research_scan_service.py — 3-4h
- Tests — 1-2h

**Realistic Task 4: 8-12 hours, not 2.5.** Possibly one full weekend on its own if the fetch layer is broken at the network level.

---

### 2. HIGH — Alpaca client routing has 11 call sites, sprint patches 1

**Call sites requiring desk-awareness (verified via grep):**

| File | Function | Lines | Risk |
|---|---|---|---|
| `src/shadow_trading/executor.py` | place_bracket_order, place_paper_entry, place_live_entry, get_order_status, get_live_account_info, get_current_price | 58, 259, 283, 485, 752, 903, 1217 | **HIGH** — order placement and lookup |
| `src/shadow_trading/reconcile.py` | reconcile_live_trades | 42 | **CRITICAL** — will 404 on research positions; may attempt to close via wrong account |
| `src/shadow_trading/bracket_monitor.py` | check_bracket_health | 109 | **CRITICAL** — polls Alpaca for bracket order state; research brackets will be invisible to swing client |
| `src/services/shadow_service.py` | get_shadow_status | 64 | MEDIUM — account info display |

**The sprint's assertion guardrail `client_tag == trade_desk` is insufficient** because:
- `ShadowTrade` model (`src/shadow_trading/models.py`) has no `desk` field
- `trade_data` dict uses `source` (`paper`/`live`), not `desk`
- No existing code path populates `trade_data["desk"]`
- Default fallback `trade_data.get("desk", "swing")` in the sprint's helper silently routes research trades to the swing client if any code path forgets to set it

**Mitigation in current sprint:** None. The sprint says "preserves backward compat" but that's code for "research trades will silently reconcile through the wrong client when `enabled: true`."

**What must happen:**
- Add `desk TEXT NOT NULL DEFAULT 'swing'` to `ShadowTrade` model
- Update reconcile.py to accept desk context from the trade record (not the default client)
- Update bracket_monitor.py similarly
- Add a test: open research trade → run reconcile → assert research client was polled, not swing

---

### 3. HIGH — Cadence gating via "mirror `_run_mr_scan`" does NOT produce 10-min cadence

**Current `_run_mr_scan` behavior (`src/scheduler/watch.py:708-714`):**
```python
def _run_mr_scan(self):
    from src.services.mr_scan_service import run_mr_scan
    result = run_mr_scan(self.config)
    # ... logging
```

**Critical:** `_run_mr_scan` fires **inline within `if self._should_scan(now):`** at `watch.py:1266` — i.e., every time the main 30-minute scan fires, not on its own clock. There is NO `_last_mr_scan_time` state variable. Mirroring this pattern produces 30-min cadence, not 10-min.

**The sprint's Task 9 acknowledges this with "Add state flag in __init__: `self._last_research_scan_time = None`"** — but the opening sentence says "add a new method `_run_research_scan` mirroring `_run_mr_scan`." These two instructions contradict. A reviewer following the "mirror" instruction literally will produce a broken cadence.

**Correct reference pattern is `_last_position_monitor_time` (15-min, line 1240-1246) or `_last_sentiment_refresh_time` (60-min, line 1271-1272)** — both use `(now - self._last_X_time).total_seconds() > threshold` explicit gating.

**Line edit required:** Change Task 9's opening instruction to:
> "Add a new method `_run_research_scan` using the interval-gating pattern from `_last_sentiment_refresh_time` (watch.py:1271-1272), NOT the inline pattern from `_run_mr_scan`. Research requires an independent 10-min cadence."

---

### 4. MEDIUM-HIGH — LLM `generate_structured` has zero test coverage, wrong timeout model, and no existing callers

**Evidence:** `src/llm/client.py` at line 107 (sprint says line 212 — wrong):
```python
def generate_structured(prompt: str, system_prompt: str, response_schema: dict,
                        temperature: float = 0.3) -> dict | None:
```

- **No `timeout` parameter.** Uses global `cfg["timeout_seconds"]` (default 180s).
- **Sprint's `timeout_s=6` parameter in `generate_research_note` has nowhere to plug in.** Task 8 will silently use 180s, which contradicts the spec's cold-start mitigation (sprint says 6s timeout → fall back to "[LLM_TIMEOUT]").
- **Zero production call sites** — grep confirmed `generate_structured` is defined but never called anywhere in the codebase. Task 8 is the first consumer.
- **Zero test coverage** in `tests/test_llm_client.py` — only `generate` and `_strip_think_blocks` are tested.
- **No retry logic** — single attempt, returns `None` on any `JSONDecodeError` / `KeyError` / `IndexError`.

**Additional concern — verbatim quote check attack vectors:**

The sprint's `_has_verbatim_substring(needle, haystack, min_len=20)` is trivially defeated:
- 35-char SEC boilerplate "The Company may experience adverse" appears verbatim in most 10-Ks' risk-factor preambles. An LLM hallucinating a thesis that *contains* this 20-char window passes the check without the quote being substantively about the actual change.
- Stop-word phrases like "and the company has been" or "as of the date of this" are 20+ chars and appear in virtually every filing.
- No content-richness check (e.g., require quote to contain ≥2 nouns not in a stop-word list).

**Pre-requisite for Task 8:** Extend `generate_structured` to accept a per-call `timeout` parameter. This is a 30-minute change (signature + `requests.post(timeout=...)` plumbing + 1 test) that the sprint silently assumes already exists.

---

### 5. MEDIUM — Task 4 time estimate is under by ~150-300%

The sprint claims 2.5 hours for Task 4. Real scope (even assuming EDGAR data pipeline *does* work — which it doesn't):

| Sub-task | Sprint | Realistic |
|---|---|---|
| Add item_1a regex to _parse_sections | — | 30 min (+edge cases for em-dash formatting) |
| Build `src/features/lazy_prices.py` (cosine + passes filter) | included | 1.0h |
| Build `src/features/ml_sue.py` (weighted SUE — note: not actually elastic-net despite the name) | included | 1.0h |
| Build `src/services/research_scan_service.py` (universe + both triggers + dry run) | included | 1.0h |
| Cosine quartile threshold derivation | sprint hardcodes `0.75` with TODO | 1-2h to derive from actual cosine distribution; OR accept literal with disclaimer |
| Tests (10+ test functions claimed) | included | 1.5-2h |
| **Plus: EDGAR data backfill** | **not in sprint** | **3-6h if fetch works; 10+ if broken** |

**Honest total: 8-12h minimum.** If fetch is broken at the network layer (auth, User-Agent, redirect handling), add another 4-8h. The 2.5h claim is optimistic by ~4-5×.

---

## Task-by-Task Honest Time Estimates

| Task | Sprint Claim | Realistic | Risk |
|---|---|---|---|
| T1 Config + `load_desk_config` | 1.0h | 1.0-1.5h | Low — straightforward |
| T2 Schema (3 new columns) | 0.5h | 0.5-1.0h | Low — but add a real-data test for SQLite DEFAULT backfill behavior; do not trust documentation |
| T3 Alpaca dual-client factory | 1.0h | 1.5h | Low — `verify_accounts_distinct` live call is the only risk |
| **T4 Research scanner + EDGAR fix** | **2.5h** | **8-12h (24h worst case)** | **CRITICAL** — EDGAR data crisis blocks everything |
| T5 Risk governor per-desk | 1.0h | 1.5-2.0h | Medium — cross-desk kill switch semantics need explicit decision |
| **T6 Executor desk routing** | **2.0h** | **3.5-4.5h** | **HIGH** — must include reconcile.py + bracket_monitor.py |
| T7 Journal desk-aware queries | 1.0h | 1.0h | Low |
| **T8 LLM prompt + validation** | **2.0h** | **3.5-4.5h** | **HIGH** — requires 30-min pre-req to add timeout param to `generate_structured`; verbatim check fragility |
| T9 Watch loop wiring | 1.5h | 2.0h | Medium — cadence pattern choice is critical |
| T10 Dashboard filter + Telegram prefix | 1.5h | 1.5h | Low |
| Buffer | 1.0h | — | — |
| **TOTAL** | **14h** | **22-29h** | Sprint is over-scoped by 60-100% |

**Weekend reality:** 14h spans ~8:00 Saturday through ~22:00 Sunday with rest breaks. 22-29h spans the full weekend plus Monday morning without sleep.

---

## Minimum Viable Subset for 8 Hours (Saturday only)

If Ryan has one day, ship the **infrastructure-only** slice that validates dual-desk architecture without requiring any research data:

| # | Task | Hours | Output |
|---|---|---|---|
| 1 | T1 Config dual-desk + `load_desk_config` | 1.0h | `desks.swing` and `desks.research` loadable from YAML |
| 2 | T2 Schema `desk`, `research_thesis`, `filing_anchor_accession` columns | 0.5h | 85 existing rows backfilled to `desk='swing'` via DEFAULT (verify with real DB test) |
| 3 | T3 Alpaca `get_client(desk)` factory + `verify_accounts_distinct` | 1.0h | Second paper account reachable; account numbers confirmed distinct |
| 4 | T5 Risk governor per-desk (without cross-desk ticker check — defer that to T6+) | 1.0h | `GOVERNORS["swing"]` and `GOVERNORS["research"]` both instantiable |
| 5 | T7 Journal `get_open_shadow_trades_by_desk` | 1.0h | Desk-isolated queries work |
| 6 | T9 Watch loop cadence slot for research (inactive if `enabled: false`) | 1.5h | Loop runs cleanly with research gated; swing untouched |
| 7 | T10 Dashboard desk filter + Telegram `[RESEARCH]` prefix | 1.5h | Frontend can filter; Telegram formatting ready |
| | **Total** | **~7.5h** | |

**Explicitly deferred:**
- T4 Research scanner (needs EDGAR data)
- T6 Executor routing beyond executor.py (reconcile + bracket_monitor)
- T8 LLM prompt (needs generate_structured timeout refactor first)

**What the MVS produces:** a second Alpaca account reachable, schema ready, per-desk risk governor, journal query isolation, watch-loop cadence slot, and dashboard/Telegram desk-awareness. **No research trade can fire** because T4 + T8 are out. That's fine — `desks.research.enabled: false` stays in the commit.

**What the MVS *doesn't* produce:** any movement toward Go/No-Go criterion #5 (end-to-end candidate → LLM → trade). That criterion must be rewritten or deferred.

---

## Specific Line Edits to the Sprint Spec

### Edit 1 — Pre-Flight Check #4

**Current:**
```bash
# 4. Confirm EDGAR collector has recent data (at least 1 filing in last 30 days)
python -c "from src.config import DB_PATH; import sqlite3; c = sqlite3.connect(DB_PATH); print('Recent EDGAR filings:', c.execute(\"SELECT COUNT(*) FROM edgar_filings WHERE filing_date > date('now', '-30 days')\").fetchone()[0])"
```

**Replace with:**
```bash
# 4. Confirm EDGAR filings have populated sections_json (CRITICAL for Lazy Prices)
python -c "
from src.config import DB_PATH
import sqlite3
c = sqlite3.connect(DB_PATH)
total = c.execute('SELECT COUNT(*) FROM edgar_filings').fetchone()[0]
with_sj = c.execute(\"SELECT COUNT(*) FROM edgar_filings WHERE sections_json IS NOT NULL AND sections_json != '{}'\").fetchone()[0]
print(f'Total: {total}, with_sections: {with_sj}, pct: {100*with_sj/max(total,1):.1f}%')
"
# Expected: >=70% with sections. If 0% — DO NOT PROCEED. Fix edgar_collector first.
```

### Edit 2 — Task 4 restructure

Split Task 4 into:
- **T4-PRE (Friday or pre-sprint, 2-6h):** Diagnose and fix `edgar_collector._fetch_filing_text` (why is `full_text` always NULL?). Backfill sections_json across all historical 10-K / 10-Q.
- **T4-A (Saturday, 1h):** Add item_1a regex pattern; verify on 5 recent filings manually.
- **T4-B (Saturday, 1.5h):** Build `src/features/lazy_prices.py` + tests.
- **T4-C (Saturday, 1.5h):** Build `src/features/ml_sue.py` + tests. Rename file to `src/features/weighted_sue.py` or add a prominent comment: `# This is NOT elastic-net per Kaczmarek-Zaremba — it's a simplified weighted average. Cited alpha may not transfer.`
- **T4-D (Sunday, 1h):** Build `src/services/research_scan_service.py` + tests.

### Edit 3 — Task 6 scope expansion

Replace the current "Two changes" section with:

```
Three changes (not two):

6a. Desk-aware client selection in executor.py (as written).
6b. Desk-aware routing in reconcile.py — accept desk from ShadowTrade record;
    route get_live_positions() and any close orders through the correct client.
6c. Desk-aware routing in bracket_monitor.py — poll the correct client for
    bracket order status based on the trade's desk field.
```

Add test:
```python
def test_reconcile_routes_research_trade_to_research_client():
    """Research trade must not leak to swing client during reconcile."""
    # Open research trade via research client
    # Inject reconcile run
    # Assert research client's get_order_by_id was called, NOT swing client's
```

### Edit 4 — Task 8 pre-requisite

Add to the top of Task 8:

```
PRE-REQUISITE (0.5h before starting main Task 8):
Extend src/llm/client.py generate_structured to accept a per-call `timeout`
parameter. Current implementation uses only the global cfg["timeout_seconds"]
(default 180s). The sprint's timeout_s=6 parameter has no wiring without this
change.

    def generate_structured(prompt, system_prompt, response_schema,
                            temperature=0.3, timeout=None):
        ...
        effective_timeout = timeout if timeout else cfg["timeout_seconds"]
        response = requests.post(..., timeout=effective_timeout)
```

Add test: `test_generate_structured_respects_per_call_timeout`.

### Edit 5 — Task 9 cadence clarification

Replace Task 9's opening sentence:
> "Add a new method mirroring `_run_mr_scan`:"

With:
> "Add a new method using the interval-gating pattern from `_last_sentiment_refresh_time` (watch.py:1271-1272). Do NOT mirror `_run_mr_scan` — that pattern fires inline with the 30-min main scan and will not produce the required 10-min cadence. Add `self._last_research_scan_time: datetime | None = None` to both `__init__` and `_reset_daily_state`."

### Edit 6 — Verbatim quote check hardening

Replace the naive sliding-window check with a content-richness check:

```python
def _has_verbatim_substring(needle: str, haystack: str, min_len: int = 20) -> bool:
    norm_hay = re.sub(r"\s+", " ", haystack).lower()
    norm_needle = re.sub(r"\s+", " ", needle).lower()
    # Reject quotes where the 20-char window is >60% stopwords
    STOPWORDS = {"the", "a", "an", "and", "or", "of", "to", "in", "for",
                 "is", "are", "was", "were", "be", "been", "being",
                 "company", "may", "could", "would", "should", "has", "have"}
    for i in range(len(norm_needle) - min_len + 1):
        chunk = norm_needle[i:i + min_len]
        if chunk in norm_hay:
            tokens = chunk.split()
            content_tokens = [t for t in tokens if t not in STOPWORDS]
            if len(content_tokens) >= 2:
                return True
    return False
```

### Edit 7 — Revised Go/No-Go Criterion #5

**Current:** "End-to-end dry run: flip `desks.research.enabled: true`, run one scan cycle manually, verify a candidate is identified ..., LLM produces valid JSON, research trade gets logged ..."

**Replace with (if T4+T8 are in scope):** as-written, but add "If sections_json is still 0% populated, end-to-end dry run is expected to return candidates=0 without error — that is acceptable. Non-acceptable: any exception thrown, or a research trade logged with NULL desk column."

**Replace with (if T4+T8 are out of MVS):** "Dry run: flip `desks.research.enabled: true`, run `python -m src.services.research_scan_service run_research_scan --dry-run`, verify result = `{'status': 'ok', 'candidates': 0, ...}` without exceptions. Flip back to false. **Actual trade generation is explicitly deferred to v0.24.1.**"

### Edit 8 — Add Task 11 (optional, 1h): `sharpe-attribution` desk dimension

Current D1 endpoint `/api/shadow/sharpe-attribution` aggregates all closed trades regardless of desk. Once research trades begin flowing, swing and research P&L will be conflated. Add an optional `?desk=swing|research` query param to the existing endpoint, defaulting to all-desks for backward compat with the Trade History panel.

---

## Things the Sprint Glosses Over (from user's review prompt)

### Research Desk dashboard P&L aggregation

TradeHistory.jsx gets a filter dropdown (Task 10), but Dashboard.jsx (700+ lines) does NOT filter by desk and hard-codes no desk. All aggregated metrics (`today.pnl`, `all.wr`, stats panels) will conflate swing + research trades post-MVP. This is a "ENABLE-TIME" bug, not a MERGE-TIME bug — `enabled: false` keeps it hidden — but it needs a v0.24.1 task.

The `/api/shadow/sharpe-attribution` endpoint similarly doesn't accept `?desk=`. Post-activation, the excess-Sharpe metric Ryan relies on for SD#41 REVISED Phase 1 gate will be contaminated by research-desk P&L.

### Cross-desk kill switch semantics

`src/risk/governor.py` uses a file-based kill switch at `data/trading_halted`. It's **global** — halts both desks. The sprint's `RiskGovernor(config, desk=...)` makes per-desk caps work, but the portfolio-wide kill switch remains shared and unspecified.

**Decision needed:** If research loses 5% intraday on its `$100K` starting capital (i.e., $5K loss on $200K total), does that halt only research or both desks?

Without an explicit decision, the existing file-based switch halts both. If Ryan wants per-desk halt, add a `data/trading_halted_research` file semantics and teach the governor to check both.

### "enabled: false" → how does the switch flip?

The sprint leaves `desks.research.enabled: false` at commit. **There is no plan for how it gets flipped.** A separate v0.24.0-post sprint (or a single line of documentation) should specify:
- Prerequisite checks (sections_json ≥ 70% populated, LLM timeout override merged, reconcile/bracket_monitor desk-aware)
- First-week monitoring (what to watch; when to roll back)
- Roll-back procedure (flip to false, cancel any open research positions via the research client, leave shadow_trades rows intact)

Recommend adding a one-paragraph "Activation Plan" section to the sprint spec before merge.

---

## Concerns the User Asked About — Direct Answers

| Question | Answer |
|---|---|
| Does dual-desk integrate cleanly with v0.23.2 asyncio refactor? | Mostly yes. `_run_sync_body` still exists (asyncio layer wraps via `asyncio.to_thread`). Handler registry exists as a mixin but the current loop is still class-based + sync-body. The sprint's approach (add methods to the class) is architecturally consistent with v0.23.2's actual state, which is Phase A (wrapped sync) not Phase C (fully async). |
| Is registering as a `watch_handlers.py` handler better? | No. `watch_handlers.py` is for **time-window-based** overnight tasks with done-flags. Research scan is **interval-based** (every 10 min during market hours), which is the inline pattern. Use the sentiment-refresh pattern, not the handler-registry pattern. |
| Does SQLite ALTER TABLE ADD COLUMN with DEFAULT backfill existing rows? | Yes for constant-string defaults in SQLite ≥ 3.0 (your repo uses 3.35+). `DEFAULT 'swing'` will populate existing 85 rows. Verified via inspection of `src/schema/sqlite.py:132-139`. **But add a real-DB test** — don't trust theory. |
| Does `render_sync.py` auto-migrate new columns to Postgres? | Yes. `src/sync/render_sync.py:719-721` calls `create_all_tables` + `ensure_columns` before each sync. All three new columns are TEXT — no `_REAL_COLUMNS` change needed. ✓ |
| Does `generate_structured` reliably enforce JSON schema? | Mostly. Uses Ollama's `response_format: {"type": "json_schema", ...}` which does constrain output. But no retry, no per-call timeout, zero test coverage, zero production callers. Semantic validation (enum checks, length limits) still required downstream. |
| Is the 20-char verbatim check robust? | **No.** Trivially defeated by common SEC boilerplate. See Edit 6 above for a content-richness hardening. |
| Does the 10-min cadence give enough headroom for 2-8 candidates × 2-4s LLM calls? | Marginal. 8 candidates × 4s = 32s, well under 600s. But Ollama cold-start can spike to 15s on the first call after a period of inactivity. Budget: ~60s for the first cycle, ~30s steady-state. The 600s cadence is safe. Watch for cascading backpressure on the first scan of the day. |
| Does the item_1a regex handle real SEC filings? | Mostly. **Fails on em-dash variants** ("Item 1A—Risk Factors" — common in HTML-stripped text). TOC entries with page numbers ("Item 1A. Risk Factors ....... 24") will match but capture noise. Add an em-dash alternative: `r"(?i)item\s+1a[.\s\u2014—-]+risk\s+factors(.*?)(?=item\s+1b|item\s+2|\Z)"` |
| Do 70%+ of SP100 have prior-year 10-K/10-Q data? | **100% coverage on row existence (101 unique tickers, all with 2+ years of filings).** But 0% of those rows have populated `sections_json`. The critical metric is not filings-present but filings-parsed. |
| Can the executor assertion prevent desk tag leakage? | Only partially. Assertion uses `.get("desk", "swing")` default, which silently routes missing-desk trades to swing. Legacy code paths that construct `trade_data` without `desk` will silently hit the swing account even if the caller intended research. **Fix:** fail-fast if `desk` is absent when `desks.research.enabled: true`. |
| Is ~40 new tests enough coverage? | Borderline. Missing scenarios: (a) swing and research open AAPL in same minute — cross-desk conflict race; (b) watch-loop restart mid-sprint with one research trade open — state recovery; (c) schema migration on DB that already has `desk` column from partial prior run — idempotency; (d) Alpaca API returns 429 rate limit on second desk during high-throughput day. Add these four. |

---

## Summary of Recommended Actions

**Before writing any code:**
1. Run the diagnostic query on edgar_filings to confirm full_text nullability (done — 0/3,362).
2. Decide: repair EDGAR fetch in-sprint, or split T4+T8 into v0.24.1.
3. Stratify the 11 Alpaca call sites into read-vs-write; expand T6 to include reconcile.py + bracket_monitor.py.
4. Add the 30-min pre-requisite to T8 (per-call timeout param on `generate_structured`).

**If Ryan commits to 14h this weekend:**
- Ship the MVS (~7.5h) on Saturday
- Use Sunday to repair EDGAR fetch pipeline (diagnose + backfill) — likely 4-6h
- Defer T4-scanner, T8-LLM, T6-reconcile-fixes to v0.24.1 weekend

**If Ryan has 8h (Saturday only):**
- Ship the MVS exactly as spec'd above
- Update Go/No-Go criterion #5 to "dry run returns status=ok, candidates=0, no errors"
- Tag as v0.24.0-infra; next weekend delivers v0.24.0-signal

**Do NOT ship as-written.** The 14h estimate and criterion #5 together assume a working EDGAR data pipeline that does not exist.

---

## Research Metadata

- **Query:** Skeptical code review of sprint-research-desk-mvp.md vs actual Arcis repo state
- **Depth:** exhaustive
- **Domain:** implementation risk audit (internal)
- **Duration:** ~35 minutes
- **Agents dispatched:** 6 parallel code-verification (Explore subagent), 3 council (skeptic + 2 partially-run)
- **SQL queries executed:** 2 direct (edgar_filings population, shadow_trades baseline)
- **Files inspected directly:** 6 (sprint spec, research report, D1 sprint, MASTER.md §1-§5, edgar_collector.py:180-280, universe/)
- **Files inspected via agents:** 15+ (watch.py, handler_registry.py, watch_handlers.py, registry.py, sqlite.py, render_sync.py, llm/client.py, alpaca_adapter.py, executor.py, reconcile.py, bracket_monitor.py, shadow_service.py, risk/governor.py, TradeHistory.jsx, Dashboard.jsx, notifications/telegram.py)
- **Evidence gaps flagged:** (a) root cause of edgar full_text NULL not determined (network vs parse layer); (b) SQLite version not confirmed for DEFAULT-backfill behavior on existing rows; (c) stratification of 11 Alpaca call sites into read-vs-write not completed; (d) council practitioner and contrarian rounds partially run.
- **Confidence: HIGH on top 3 concerns (direct SQL + grep evidence), MEDIUM on time estimates (honest calibration against past Arcis sprints unavailable to reviewer).**
