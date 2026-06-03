"""Single source of truth for the app version (#631 item 15).

Called by: api.cloud_routes.core, services.system_service
Calls: none
Owns tables: none
Config keys: none
Tests: tests/test_version.py

Pre-fix the version "v0.17.2" was hardcoded in three places (cloud_routes/
core.py, services/system_service.py, frontend/Layout.jsx fallback) while
the actual deployed version was v0.24.0-alpha1 — confusing operators reading
the dashboard who saw a header version that didn't match the What's New
section.

The frontend reads `status.version` from /api/system/status; that endpoint
now reads VERSION from this module. The frontend fallback constant has
also been updated to match. Bump VERSION here when cutting a release;
update CHANGELOG.md alongside.
"""

# Update when cutting a release. Latest CHANGELOG header: v0.36.83
# (Cleanup-2 — last Phase-4 items. #51: the deterministic drawdown circuit-breaker
# now evaluates a 30-day rolling window instead of the days=1 audit snapshot — the
# _DRAWDOWN_MIN_SAMPLE=50 guard was unreachable in a single day, so the CRITICAL
# drawdown flag never fired. #77: root-caused as 18 sim-placeholder rows (rec-4),
# not a rec-flow bug — documented + closed; symptom already handled by v0.36.41.)
# Versioning policy: see docs/versioning-policy.md.
# v0.36.84 (#132): sim-gate honesty pass — certified the clean-close OCO path
# (was xfailed) and in doing so fixed THREE real PG-cutover regressions in the
# trade-close path (postmortem datetime[:10] subscript crash, days_open
# fromisoformat(datetime) phantom-timeout, SPY-benchmark .replace crash) — a
# DB-closed/broker-open orphan source — plus a sim harness neutral-price drift.
# Full lifecycle gate now returns STABLE.
# v0.36.85 (#95): W21 capstone — the destructive prod clean-slate-wipe script
# (scripts/clean_slate_wipe.py + scripts/_clean_slate/*) is BUILT (not run):
# dry-run-by-default, ProdGuard-gated, backup-first (verify-restore into a fresh
# ephemeral DB), single-transaction TRUNCATE of the 53-table WIPE set (27 KEEP
# preserved), live-schema+FK reconciliation, SQLite archive-then-empty, forensic
# WIPE_COMMITTED marker, + full verify-by-mutation test suite. EXECUTION stays
# operator-gated. Found+fixed a Windows fsync(O_RDONLY)->EBADF portability bug.
VERSION = "v0.36.85"
