# PR-E2 T40 — Suite Green-Gate Audit (#102b)

**Date:** 2026-05-28
**Authoritative baseline:** PR-E `pg-tests` CI run `26587967887` (Linux, clean env,
both schemas bootstrapped, signal-timeout survives hangs, 9m18s). Local Windows
runs are NOT authoritative (prod `.env`, empty 5434, `thread`-timeout aborts on
first hang — see Methodology pitfalls).

## Baseline

| Outcome | Count |
|---------|-------|
| passed | 6,666 |
| **failed** | **204** |
| **errors** | **91** |
| skipped | 42 |
| xfailed | 3 |
| **non-passing (gate gap)** | **~295** |

CI's floor check passes only because it gates on `passed ≥ 5,267` and
**deliberately tolerates this chronic-failure class** (CLAUDE.md L15: worktree
env-drift, hardcoded fixtures, env-pollution). The green-gate (DD-42: zero
failures, zero xpass, justified skips only) requires resolving all ~295.

## Categorization by root cause + effort

| # | Bucket | Count | Effort | Notes |
|---|--------|-------|--------|-------|
| 1 | **engine-aware PG-on-5434 (CONFIG)** | **~130** | **LOW** | All `psycopg2.OperationalError: connection to 127.0.0.1:**5434**` (274 hits). The `[postgres]` parametrized + engine-aware tests target 5434, but the standard `pg-tests` CI job provisions PG on **5432** only (5434 is the dispatch-only lifecycle job). **VERIFIED config, not logic:** `test_db_engine_aware_upsert.py` → 23 passed/2 skipped against a bootstrapped local 5434 (was 10 CI errors). Fix = ONE CI change: add a 5434 PG service + `bootstrap_pg_test_schema.py` to `pg-tests.yml` (or retarget tests to `TEST_DATABASE_URL`). Clears ~44% of the gap. |
| 2 | **api / local_routes / projections route-shape** | **~25** | **HIGH** | `test_route_parity.py` (15), `test_projections.py` (5), `test_local_routes.py` (5+, 29 total in the broader file). cloud_app→`src.api.app` migration debt + stale route-shape mocks (e.g. `result` lost its `value` key). Per-file rewrites. Folds kins #10/#11/#20/#26. |
| 3 | **capability_registry_coverage** | 22 | MEDIUM | Registry-coverage assertions. Need to determine: registry genuinely missing entries vs test reads DB (may partly fold into #1). |
| 4 | **"other" (RuntimeError 24, pytest.fail 18, FileNotFound 6, IntegrityError 4, SymbolFindError 4, OSError 3)** | ~62 | MIXED | Heterogeneous; IntegrityError/OSError likely DB (fold into #1); SymbolFindError = rg-tool tests; FileNotFound = fixture/path; pytest.fail = guardrail/source-scan checks. Per-cluster triage. |
| 5 | **remaining assertion/misc** | ~56 | MIXED | Smaller clusters: auditor, shadow_trading, eslint/queryfn guardrail, audit_email_throttle, log_levels, no_sqlite_isms, phantom_close, self_blinding, trainer, etc. Some real (e.g. `test_no_conflict_markers_in_repo`, source-scan guardrails), some env. |
| 6 | **skips (42) + xfails (3)** | 45 | LOW | Justify per DD-42 allowlist {platform, optional-dep, engine-aware, tracked-upstream-bug(#N)}. Observed skip reasons: "deferred" (7), "requires live PG fixture" (7), "T0.4 #10" (2), live-PG-policy (2). |

## Separate finding — Windows-only hangs (not in CI)
Two hang classes block local full-suite runs but NOT CI (Linux signal-timeout):
- PG-lock hang: destructive tests vs prod 5433 block on the live watch-loop's locks → kin #27 (24-file fallback hardening, in PR-E2 scope).
- `test_run_full_gate_is_authoritative` (simulation/lifecycle): real `enricher._rate_limit` `time.sleep` unmocked → needs a sleep/rate-limiter mock (T41).

## Safety finding (handled)
The campaign ran the suite via `ARCIS_ALLOW_PROD_PG_IN_TESTS=1` (P0-guard escape
hatch) with `.env` `DATABASE_URL`=prod. Prod survived (verified intact: 79
tables) only because every full-suite run HUNG before the destructive files.
Corrected convention: memory `feedback_test_pg_use_test_database_url`; hardening
= kin #27.

## Recommended approach (phased)
1. **T41a (LOW, high-leverage):** the 5434 CI-config fix — clears ~130 (~44%). Then RE-BASELINE via a fresh CI run to get the true remaining gap.
2. **T41b:** route-rewrites (#2 cluster, folds kins #10/#11/#20/#26) + the lifecycle sleep-mock + capability_registry triage.
3. **T41c:** "other"/remaining triage (#4/#5) — fix or justified-skip.
4. **T42:** justify the 45 skips/xfails per the allowlist.
5. **T43:** CI sentinel `test_suite_integrity.py` + `xfail_strict` — gate at the post-fix green state (meaningful only after the gap is closed or ratcheted).

The decision to make: full-green (resolve all ~295) vs ratchet (config-fix + sentinel at the post-fix pass-count, remaining as kin backlog).
