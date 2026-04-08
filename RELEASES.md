# Arcis Release History

> **Versioning:** [Semantic Versioning](https://semver.org/) — `MAJOR.MINOR.PATCH`
> **v1.0.0 criteria:** Phase 1 gate passed, all critical bugs resolved, 7-day uptime, ≥90% conviction parse rate

---

## Release Process

### For each sprint release:
1. CC works on feature branch (`feat/sprint-X`)
2. PR opened → reviewed (check every changed file for stubs/TODOs)
3. Fix cycle until clean (typically 2-3 rounds)
4. Merge to `main` with `--no-ff`
5. Tag: `git tag -a vX.Y.Z -m "description"`
6. Push: `git push origin main && git push origin vX.Y.Z`
7. Restart system (`git pull && python -m src.main startup`)
8. Monitor logs 30 minutes
9. If broken: `git checkout vX.Y.Z-1 && restart` (instant rollback)

### Version increment rules:
- **Patch** (0.x.**Y**): Bug fixes, doc updates, config changes — no behavior change
- **Minor** (0.**X**.0): New features, new dashboard pages, new scanners, schema changes
- **Major** (**X**.0.0): Breaking changes to data schema format, config format, or trading behavior

### Hotfix process:
- Branch from `main`: `hotfix/issue-NNN`
- Fix + test + PR (expedited review)
- Merge + tag as patch increment
- Deploy immediately

---

## Path to v1.0.0 (Stable Release)

| Criterion | Target | Current |
|---|---|---|
| Phase 1 gate passed | 50 trades, WR≥45%, Sharpe≥0.15, PF≥1.3, DD≤12% | 18 trades (36%) — accumulating |
| Critical bugs resolved | Zero CRITICAL issues open | ✅ Done (0 open issues) |
| MASTER.md complete | All 13 sections populated | ✅ Done (v0.10.0) |
| Conviction parsing | ≥90% parse rate | ✅ Fixed (v0.11.0) — verify in logs |
| Watch loop uptime | 7 consecutive days without crash | Clock started Apr 4 |
| Alpha attribution running | ≥50 paired trades | Accumulating (deployed v0.10.0) |
| Stress test completed | 2008/2020/2022 scenarios | Deployed, runs Sunday 9 PM |
| Schema registry | All tables, zero DDL outside | ✅ Done (49 tables) |
| CI guardrails | 9 tests, Dependabot | ✅ Done (v0.11.0) |

---

## Releases

### v0.15.3 — Production Sweep (2026-04-08)
**14 issues closed in 3 phases. Branch: `fix/production-sweep`.**

**v0.15.1 — CRITICAL (5 issues):**
- #326: Stop-price > 0 guard before all bracket order placements
- #325: Fractional share tolerance in reconciliation (float qty, 0.001 threshold)
- #329: Additional conviction extraction patterns (stages 7-8) + parse rate logging
- #330: safe_numeric() for quality_score_auto, int() cast on config thresholds
- #335: Overnight training script import path verified

**v0.15.2 — HIGH (4 issues):**
- #331: Postgres schema validation (create_all_tables + ensure_columns) at sync startup
- #332: macro_snapshots sync_conflict_col to prevent duplicate key errors
- #327: DDL guardrail verified — no inline CREATE TABLE outside schema/
- #328: Data collection stats COALESCE(collected_at, collected_date) for column compat

**v0.15.3 — MEDIUM (5 issues):**
- #302: NULL PK root cause verified — inline PRIMARY KEY prevents NULL ids
- #303: Research source graceful degradation with caching + 30s timeout + retry
- #304/#333: VRAM handoff 3-retry logic (15s backoff, Telegram alert on failure)
- #334: Ingestion gate narrowed — inline bold emphasis no longer triggers rejection

---

### v0.15.0 — (pending: 3 more feature branches to merge)
**4 feature sprints: gap assessment + simulation engine + model performance + Bloomberg UI**

*Merged to main so far:*

**Gap assessment (merged 2026-04-07):**
- #295: Embedding-based semantic leakage detection (Ollama + LogisticRegression, 55% threshold)
- #296: Dynamic Bayesian agent weighting for AI Council (Beta posterior, feature flag, 12-week window)
- #297: Two-tier relative strength (60% vs SPY + 40% vs sector ETF, 11 sector ETFs mapped)
- 26 new tests (leakage: 12, council: 6, ranker: 7, ranking: 7 shared)
- Backward compatible: falls back to static weights and market-only RS when data unavailable
- Closes #295, #296, #297

*Pending merge:*
- feat/simulation-engine: 13-scenario engine, Monte Carlo, TL validation, dashboard page
- feat/model-performance: per-model metrics, regression alerts, dashboard page
- feat/ui-bloomberg: Bloomberg Terminal aesthetic on all 18 pages

Tag v0.15.0 after all 4 features are merged and tested.

---

### v0.14.2 — 2026-04-06
**Hotfix merge sprint — 6 critical production bugs + codex fixes + dependency updates**

17 files changed, +387 -22 (hotfix). 11 PRs merged. 9 issues closed (#299-301, #307-312).
5 stale remote branches deleted. 29 new tests added (1,410 → 1,439).

**Critical fixes (PR #313):**
- #310: Shadow trade exit cascade — `exit_failed` on broker exception + circuit breaker + `cancel-all-pending` CLI
- #311: Type-safety gaps — `safe_numeric` utility, fixes in traffic_light, watch.py (VIX/EOD/brief)
- #309/#312: LLM conviction parsing — Stage 6 catch-all regex + debug file logging
- #308: Risk governor TypeError — `safe_numeric` coercion at `check_trade` entry
- #307: Postgres schema drift — startup drift check + CLAUDE.md rule #8

**Codex fixes (PR #305):**
- #299: Ingestion gate markdown detection narrowed to line-leading headings
- #300: Type-safety in notifications/digests
- #301: Fundamentals refresh import drift fixed

**Dependencies (9 Dependabot PRs):**
- CI: actions/checkout 4→6, setup-node 4→6, setup-python 5→6
- Frontend: react-router-dom 7.14, react-query 5.96, vite 8.0.5, lucide-react 1.7, eslint 10.2
- Backend: yfinance version range widened to <2.0

**Cleanup:**
- 5 stale branches deleted (audit-run-1, codex/*, master)
- PR #298 closed (superseded by #305), PR #218 closed (superseded by #306)

---

### v0.14.1 — 2026-04-05
**Log audit hotfix — 14 production issues from 15K-line log analysis**

16 files changed, +1,182 -48. 8 issues closed (#279-#286).

**Critical fixes:**
- #279: Bracket monitor — Alpaca enum prefix stripped from leg statuses + `accepted` added to ACTIVE_LEG_STATUSES (was showing 0/N protected)
- #280: Earnings signals — column names corrected to schema (actual/estimate/metric, not eps_actual/revenue_actual)

**High fixes:**
- #281: Overnight training script — imports actual trainer functions (was broken)
- #282: Position monitor — int() cast on SQLite TEXT timeout_days
- #283: Regime refresh — sentiment_scanner passes ohlcv_data argument
- #284: HSHS performance sub-score — float() cast on SQLite TEXT value
- #285: Training collection format string — float() before %.2f

**Medium fixes:**
- #286: Postgres sync — null ID guard, duplicate PK handling improved
- Stress test VIX symbol handling fixed
- EOD recap format string type safety

**Audit report:** `docs/audits/log-audit-2026-04-04.md` (15K lines analyzed)

---

### v0.14.0 — 2026-04-05
**Interactive Brokers integration — broker abstraction layer**

5 new files, 19 new tests. Multi-broker architecture deployed.

**New files:**
- `src/trading/broker_interface.py` — Abstract BrokerAdapter (10 methods) + normalized dataclasses
- `src/trading/broker_factory.py` — Singleton factory, config-driven routing
- `src/trading/ib_broker.py` — IB adapter via ib_async, lazy connection, GTC bracket orders
- `src/trading/alpaca_broker.py` — Thin wrapper over existing alpaca_adapter.py
- `tests/test_broker_interface.py` — 19 tests (interface compliance, factory routing, dataclasses)

**Architecture:**
- Paper trading unchanged (Alpaca direct, no abstraction needed)
- Live trading routes through broker factory: `config.live_trading.broker = "ib" | "alpaca"`
- Executor wired: `open_live_trade()` calls `get_live_broker(config)` instead of direct Alpaca
- Schema: `broker` column added to `shadow_trades` (default "alpaca")
- Config: `settings.example.yaml` updated with IB settings (host, port, client_id)

**NOT included (requires IB Gateway on Windows):**
- IB Gateway installation and connection verification
- Startup validation for IB connectivity
- Live trading on IB (start with paper port 4002)

---

### v0.13.0 — 2026-04-04
**Gap analysis rectification — 23 issues resolved in 3 tiers**

19 files changed, +414 -157. 0 open issues.

**Tier 1 — CRITICAL (6 issues, money at risk + training data):**
- #272: Live trading now enforces RiskGovernor + LLM validator (was bypassed entirely)
- #274: Bracket fallback places standalone stop-loss (was naked market entry)
- #275: Daily loss guard uses today's realized P&L (was all-time unrealized)
- #277: Feature sanitization BEFORE LLM generation (self-blinding leak fixed)
- #273: Empty-output templates excluded from training dataset
- #278: Partial fills tracked correctly (was recording as full close)

**Tier 2 — HIGH (7 issues, reliability):**
- #271: MR exit passes all required args to close_shadow_trade
- #276: Duplicate position check + insert in same transaction (race fixed)
- #267: Traffic light defaults to 0.5 (conservative) when missing
- #257: _safe_run only sets done-flag on success (failed tasks retry)
- #259: pull_commands only claims successfully inserted commands
- #269: _notify_exit_trade call sites pass all required params
- #264: open_shadow_trade returns None consistently on failure

**Tier 3 — MEDIUM (9 issues, polish):**
- #256: Options metrics query column names fixed
- #260: options_chains retention rule added (30 days)
- #261: Documented as future enhancement
- #262: earnings_signals logs errors instead of swallowing
- #263: Duplicate bracket order log removed
- #265: Stub endpoints return not_implemented status
- #266: shadow_account queries unified
- #268: Dead canary_score import removed
- #270: NYSE 2026 holiday calendar added

---

### v0.12.0 — 2026-04-04
**Codebase documentation + issue resolution + gap analysis**

116 files changed, +3,757 lines. 0 pre-existing issues remaining.

**Issue resolution (11 closed):**
- #248: Bracket monitor false alarms — Alpaca enum prefix stripped
- #249: System validator reads env vars, not YAML
- #250: Dark mode chart visibility — CSS variables defined
- #251: Packet commentary — raw template headers stripped
- #253: Open positions unrealized P&L computed
- #254: Max consecutive losses wired from cto_report
- #247: Metric cards centered
- #252: Stress test Run button via command queue
- #255: React Flow diagram polish
- #239: Daily audit baseline updated
- #222: Telegram pairing documented

**Codebase documentation:**
- WHY-focused inline comments on all 200+ Python files
- 30 closed issues cross-referenced in code at fix locations
- Strategy decisions (#1-#24) cited at implementation points
- Research paper citations at relevant code sections

**Gap analysis (15 new issues filed):**
- #256: Options metrics query wrong columns (pipeline dead)
- #257: _safe_run done-flags set on failure (tasks never retry)
- #258: 220+ sqlite3.connect() bypass connect_db (no busy_timeout)
- #259: pull_commands marks all claimed even on insert failure
- #260: Options chains unbounded growth (no retention)
- #261: Options flow collected but unused in training
- #262: earnings_signals swallows all errors
- #263: Duplicate log in place_bracket_order
- #264: open_shadow_trade returns dict on buying power fail
- #265: review_scorecard/postmortems are stubs
- #266: shadow_account queries wrong columns
- #267: Traffic light defaults to 1.0 (no regime protection)
- #268: compute_canary_score import broken
- #269: _notify_exit_trade missing parameters
- #270: No market holiday calendar

---

### v0.11.0 — 2026-04-04
**Bug bash complete — all issues closed, CI hardened**

PRs #205-#212. 0 open issues (was 17). 1,344 tests (was 1,105). 13 architecture diagrams.

**Critical fixes:**
- #183: Conviction parsing — 5 extraction patterns (was 2), target ≥90% parse rate
- #197: Finnhub API key moved to `X-Finnhub-Token` header (7 files)
- #187: Paper buying power check before trade entry
- #188: Negative shares guard in reconcile backfill (long-only enforcement)
- #106: Atomic kill switch with staleness check + audit trail
- #132: Config validation rejects placeholder API keys on load
- #147: Exponential backoff retry utility applied to all enrichment/collection
- #82: Silent exception swallowing replaced with logger.debug() in council

**CI hardening (9 guardrail tests):**
- API parity (frontend ⊆ backend routes)
- No DDL outside schema registry
- Import smoke test (catches wrong module paths)
- Stub function detection (no pass-only functions)
- Test coverage enforcement (every module referenced by a test)
- TODO must reference GitHub issue number
- Dashboard route validation
- Schema column drift detection
- Config key validation against settings.example.yaml

**Infrastructure:**
- Dependabot configured (Python + npm weekly Saturday, Actions monthly)
- 13 architecture SVG diagrams with light/dark mode
- Test count floor updated in CI (1,344)

---

### v0.10.0 — 2026-04-03
**Sprints A-7: Dashboard, Docs, Attribution, MR, Multi-Cadence, Training, Stress Testing**

53 files changed, +6,210 -2,798. PR #203. 3 review cycles, 8 issues found and fixed.

**New capabilities:**
- MASTER.md: consolidated reference (823 lines, replaces 5 docs / 34K tokens)
- Alpha attribution experiment: simulation ledger (LLM vs ranker-only)
- Mean reversion paper trading: RSI(2) Strategy #2, strategy-aware exit dispatcher
- Multi-cadence scanning: 4-tier (15min/30min/60min/daily)
- Outcome-conditioned training: 3-5x data yield per closed trade
- Historical stress testing: 2008/2020/2022 crisis replay
- Dashboard: audit chip, build score empty state, CTO report handler, Attribution + StressTest pages
- Watch loop: enriched banner, 60-min heartbeat, scan summary line

**Schema:** +3 tables (attribution_trades, data_freshness, stress_test_results), +8 columns on shadow_trades
**Strategy decisions:** 16 → 24
**Phase gates expanded:** +alpha attribution, +stress test, +100 MR paper trades

---

### v0.10.1 — 2026-04-03
**Sprint gap closures, RCCA bug fixes, audit plugin**

34 files changed, +3,699 -364. PR #204.

**Bug fixes (8 RCCA issues from 4/3 log audit):**
- P0: Position monitor broken — SQLite TEXT in numeric comparisons (float/int casts)
- P0: VIX refresh — `.iloc[-1]` returns Series, not scalar (`.item()` fix)
- P0: Regime refresh — missing required `ohlcv_data` argument
- P1: Pre-market brief, digest emails, Telegram heartbeat, HSHS scoring — TEXT→numeric casts
- P2: Postgres duplicate keys — exclude SERIAL id from INSERT

**Sprint gaps closed (6):**
- Pending outcomes wired into post-close (S3), attribution tests (S3), strategy_type filter (S4)
- Universe scanner extracted (S5), VIX-regime brackets (S7), stress test scheduling (S7)

**New: halcyon-audit plugin** — 8 domain agents, /audit skill, scheduling, quality gate

---

### v0.9.0 — 2026-04-03 (baseline tag)
**Pre-Sprint-A baseline — last stable before v0.10.0**

Tagged retroactively as rollback point.
- 13 closed trades (12W/1L, 92% WR, $860 P&L)
- 175 Python files, 16 dashboard pages, 46 schema tables
- PRs #176-#178, #189-#190, #200-#202 merged
- Schema registry complete
- PR #200: Cast pnl_dollars to float before comparison (#195)
- PR #201: Exit cancel race fix, VRAM handoff hardening, sync reconnection (#196, #198, #199)
- PR #202: 22 missing local API routes for dashboard parity

---

### Pre-v0.9.0 (untagged)
All work from project inception through April 2, 2026.
Sprints 4A-8, reconciliation, analytics migration, dashboard redesign, log audit, data integrity, mega sprint.
See CHANGELOG.md for full history.
