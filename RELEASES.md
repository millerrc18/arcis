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
7. Restart watch loop (`git pull && python -m src.main watch ...`)
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
| Phase 1 gate passed | 50 trades, WR≥45%, Sharpe≥0.15, PF≥1.3, DD≤12% | 13 trades (26%) |
| Critical bugs resolved | Zero CRITICAL issues open | 2 (#182, #183) |
| MASTER.md complete | All 13 sections populated | ✅ Done (v0.10.0) |
| Conviction parsing | ≥90% parse rate | 1% (broken) |
| Watch loop uptime | 7 consecutive days without crash | Not validated |
| Alpha attribution running | ≥50 paired trades | 0 (just deployed) |
| Stress test completed | 2008/2020/2022 scenarios | Deployed, not run |
| Schema registry | All tables, zero DDL outside | ✅ Done (49 tables) |

---

## Releases

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

### v0.9.0 — 2026-04-03 (baseline tag)
**Pre-Sprint-A baseline — last stable before v0.10.0**

Tagged retroactively as rollback point.
- 13 closed trades (12W/1L, 92% WR, $860 P&L)
- 175 Python files, 16 dashboard pages, 46 schema tables
- PRs #176-#178, #189-#190, #200-#202 merged
- Schema registry complete

---

### Pre-v0.9.0 (untagged)
All work from project inception through April 2, 2026.
Sprints 4A-8, reconciliation, analytics migration, dashboard redesign, log audit, data integrity, mega sprint.
See CHANGELOG.md for full history.
