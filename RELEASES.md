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
