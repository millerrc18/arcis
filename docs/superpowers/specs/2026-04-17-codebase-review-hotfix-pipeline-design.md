# Codebase Review + Hotfix Pipeline — Design Spec

**Date:** 2026-04-17
**Author:** Claude (Opus 4.7) under user `millerrc18` direction
**Scope:** Exhaustive code review + 24h log review → file issues for new findings → hotfix branch + PR per critical/high issue (new and existing) → await human merge.
**Disposition:** Non-merging. PRs opened non-draft, local `pytest` green, merge decision stays with operator.

---

## Context

Arcis is a live autonomous equity trading system (v0.21.0, paper $100K + $100 live via Alpaca, 24/7 watch loop under NSSM). 225 Python source files, 1852 tests, 53 schema tables. An automated audit (`scripts/daily_repo_audit.py`, run #28) already files `[Audit]` issues on a rotating file index. This review supplements — not duplicates — that pipeline with a human-directed pass over critical/high severity items, plus a pattern-matching sweep of 24h of logs.

At spec time, 32 issues are open. ~16 of these match scope (labeled `severity:critical`/`severity:high`, plus 6 uplifted items: 5 security and 1 trading-safety that are implicitly in tier but unlabeled).

---

## Scope

### In scope
- Existing open issues labeled `severity:critical` or `severity:high`.
- Existing open issues uplifted to critical/high by operator decision on 2026-04-17:
  - Security (5): #413, #424, #439, #440, #459
  - Trading-safety (1): #431
- New findings at critical/high severity surfaced by this review from:
  - Targeted code review of production hot paths (executor, governor, broker adapter, schema, scheduler, cloud API, data collectors).
  - 24h log sweep of `logs/arcis.log` and `logs/arcis_err.log` since `2026-04-16T07:00 America/New_York`.

### Out of scope
- Issues labeled `future`, `enhancement`, `shadow-ledger` without severity labels.
- Issues labeled `technical-debt` only (e.g. #367 WatchLoop god object — sprint-sized).
- Medium/low-severity audit findings (`severity:medium` in body or unlabeled non-security findings) — respect the audit bot's cadence.
- Merging any PR. Disposition is review-by-operator.
- Config/secret file changes (`.env`, `config/settings.local.yaml`, `.mcp.json`).
- Postgres migrations (`scripts/render_migrate.py`) — operator-initiated.

### Existing issues in scope (16)

| # | Severity | Category | Tier |
|---|---|---|---|
| #455 | critical | deps (beautifulsoup4) | 1 Deploy-blocker |
| #460 | critical | deps (scipy/numpy) | 1 Deploy-blocker |
| #462 | critical | deps (pyarrow) | 1 Deploy-blocker |
| #436 | critical | trading-safety (bracket fallback) | 2 Silent trading-safety |
| #438 | high | trading-safety (governor equity=0) | 2 Silent trading-safety |
| #431 | (uplifted) | trading-safety (reconciler backfill) | 2 Silent trading-safety |
| #439 | (uplifted) | security (auth bypass) | 3 Auth/cred security |
| #440 | (uplifted) | security (timing attack) | 3 Auth/cred security |
| #424 | (uplifted) | security (token leak in logs) | 3 Auth/cred security |
| #413 | (uplifted) | security (unsafe-deser cache load) | 4 Deserialization RCE |
| #459 | (uplifted) | security (unsafe-deser cache load) | 4 Deserialization RCE |
| #434 | critical | architecture (circular import) | 5 Startup crash |
| #435 | critical | tests (coerce_to_schema) | 6 Failing-test canary |
| #456 | high | technical-debt (file length) | 7 CI file-size |
| #457 | high | technical-debt (file length) | 7 CI file-size |
| #461 | high | architecture (3 cycles) | 8 Import-graph debt |

---

## Test baseline

To be captured at Phase 0 execution:
- Run `python -m pytest tests/ -q` on clean `main` before any branch is created.
- Record passing count, failing count, error count, skipped count.
- CLAUDE.md rule: pass count must not decrease and failure count must not increase on any PR. Minimum floor is 1339.

---

## Pipeline phases

### Phase 0 — Baseline
- `git fetch --all`
- Verify working tree clean on `main`
- `python -m pytest tests/ -q` → record baseline counts
- Load remediation context: top of `CHANGELOG.md` + last 10 entries of `RELEASES.md` + `git log --since="2026-04-10"` file-commit map

### Phase 1 — Investigation (parallel + self)

**Self-investigated (6 trivial existing issues):** direct reads, no agent dispatch.

| # | Verification |
|---|---|
| #455 | Grep `from bs4`/`import bs4` in src/; add `beautifulsoup4` to `requirements.txt`. |
| #460 | Grep `import scipy`/`import numpy` in src/; add both to `requirements.txt` (pin majors that match installed). |
| #462 | Grep `import pyarrow`/`pa\.`/parquet usage; add `pyarrow` to `requirements.txt`. |
| #435 | Run `pytest tests/test_coerce_to_schema.py` to confirm failure; update test fixture to match `planned_shares REAL`. |
| #456 | Read `src/api/cloud_routes/trades.py`, extract cohesive helper(s) below 400-line CI limit. |
| #457 | Read `startup_checks.py:_check_render_postgres`, extract inner block below 60-line limit. |

**Agent-investigated (10 complex existing issues):** three parallel Explore subagents, each with a self-contained prompt (no session context). Each returns a short structured report (<400 words per issue).

- **Agent A — Security cluster:** #413 (data_enrichment cache unsafe-deser), #459 (training/historical_data cache unsafe-deser), #439 (verify_auth empty secret), #440 (bearer token timing attack), #424 (bot-token exception leak)
  - Deliverable per issue: root-cause confirmation, attack surface, proposed fix (safe-serializer migration / `hmac.compare_digest` / redaction / allowlist), test strategy, file list
- **Agent B — Import graph:** #434 (startup↔startup_checks), #461 (three cycles)
  - Deliverable: cycle graph, root cause per cycle, decoupling strategy, import-order regression test plan
- **Agent C — Trading-safety:** #436 (bracket fallback ImportError), #438 (governor equity=0), #431 (reconciler backfill bypass)
  - Deliverable per issue: code path, reproduction conditions, fail-safe vs fail-closed decision, regression test strategy

**Log sweep (self, serial):**
- Scope: `logs/arcis.log` + `logs/arcis_err.log`. Verified at spec time that `data/logs/` (NSSM service stdout/stderr) does not exist on this machine — the service isn't currently installed — so there are no additional NSSM logs to sweep. If `data/logs/service.*.log` exists at Phase 0, it will be added to the sweep.
- `grep -n -E '^\S*\s+\[(ERROR|CRITICAL|WARNING)\]|^Traceback' logs/arcis.log logs/arcis_err.log` filtered to the 24h window.
- Cluster by `(logger_name, first_non_stdlib_stackframe_or_message_shape)`.
- Apply thresholds: CRITICAL/Traceback ≥2×, ERROR ≥5×, WARNING ≥20×.

### Phase 2 — Triage

For every candidate new finding (code-review or log-derived):

1. **Remediation cross-check** — match against CHANGELOG `## [Unreleased]` + last 10 versions + `git log --since="2026-04-10"`. If a fix commit is newer than the last log occurrence, drop from queue and note in Phase 4 summary under "already remediated."
2. **Open-issue dedup** — match by `(file, symbol)` or stack fingerprint against the 32 open issues. If match exists, add evidence comment rather than file duplicate.
3. **File remaining candidates** using the canonical `[Audit]` body format:
   ```
   **Focus Area:** <domain>
   **Severity:** <critical|high>
   **File:** <path>
   **Line(s):** <N or N-M>

   **Finding:**
   <description>

   **Suggested Fix:**
   <code block if applicable>

   ---
   *Opened by Claude Code review — 2026-04-17*
   ```
4. Apply appropriate labels from the existing taxonomy (`audit`, `bug`, `severity:critical`/`high`, `trading-safety`, `security`, `architecture`, `tests`).

### Phase 3 — Hotfix execution (serial, risk-descending)

For each issue in the final queue:

1. `git checkout main && git pull`
2. `git checkout -b fix/<issue-number>-<kebab-desc>`
3. Apply fix; update/add regression test(s).
4. `python -m pytest tests/<touched-area> -xvs` — fast local feedback.
5. `python -m pytest tests/ -q` — full suite; capture pass/fail deltas.
6. If schema touched: `python -m src.main validate-schema --fix`, paste output into PR body. Do NOT run `scripts/render_migrate.py`.
7. Update `CHANGELOG.md` `## [Unreleased]` section with a one-line entry in the appropriate category (`### Fixed`, `### Security`, `### Changed`).
8. `git commit -m "fix(<area>): <summary>"` with body referencing the issue.
9. `git push -u origin fix/<issue-number>-<kebab-desc>`
10. `gh pr create --base main --title "fix(<area>): <summary>" --body "<from template>"` — NON-draft.
11. Do NOT merge. Move to next issue.

**Stacked PRs:** if fix N touches files modified by in-flight fix M, branch N from `fix/M-…` (not `main`) and `gh pr create --base fix/M-…`. Explicit note in the PR body.

**Risk-descending queue:**

| Tier | Issue(s) |
|---|---|
| 1 Deploy-blocker | #455, #460, #462 |
| 2 Silent trading-safety | #436, #438, #431 |
| 3 Auth/cred security | #439, #440, #424 |
| 4 Deserialization RCE | #413, #459 |
| 5 Startup crash | #434 |
| 6 Failing-test canary | #435 |
| 7 CI file-size | #456, #457 |
| 8 Import-graph debt | #461 |

New findings are inserted at the appropriate tier.

### Phase 4 — Summary report

Post-run operator deliverable containing:
1. **New issues filed** — number, title, severity, category
2. **PRs opened** — branch, base, issue ref, key files, test delta, stacked relationship
3. **Issues investigated but not fixed** — deferred items with reason (e.g., "needs schema change + Postgres migration — operator-initiated")
4. **Log findings already remediated** — with fix-commit SHAs, per dedup rule
5. **Top-10 log noise report** (informational)
6. **Protocol deviations** — any departures from this spec with rationale

---

## Commit and PR conventions

**Branch:** `fix/<issue-number>-<kebab-short-desc>` — e.g., `fix/462-pyarrow-in-requirements`, `fix/438-governor-equity-zero`

**Commit template:**
```
fix(<area>): <imperative summary under 72 chars>

<body: what changed, why, root cause>

Fixes #<N>
```
Areas (seen in git log): `attribution`, `telegram`, `scheduler`, `journal`, `deps`, `security`, `schema`, `startup`, `risk`, `executor`, `reconcile`, `tests`, `ci`.

**PR body template:**
```markdown
## Fixes
Closes #<N>

## Root cause
<1–3 paragraphs — reproduction, what's broken, why it matters>

## Fix
<what the diff does; why this approach vs alternatives>

## Tests
- Added: `tests/<path>::<name>` — <guard>
- Modified: <if any>
- Baseline pass count on main (Phase 0): `<N>`
- After this branch: `<N'>` passing, `<F'>` failing
- Delta: `<explain or "none">`

## Risk assessment
- **Blast radius:** <files/modules/runtime effects>
- **Deploy impact:** <restart required? schema change? none?>
- **Rollback:** `git revert <sha>` — safe because <reason>
- **Monitoring:** watch `<Grafana label / logger name>` for <pattern> post-deploy

## CLAUDE.md compliance
- [ ] Pass count ≥ Phase 0 baseline AND total tests ≥ 1339 CI floor
- [ ] Failure count not increased vs Phase 0 baseline
- [ ] No DDL outside `src/schema/registry.py` (or schema change documented)
- [ ] External APIs mocked in any new test
- [ ] No secrets in diff
- [ ] No bypass of risk governor checks

## Verification transcript
<tail ~20 lines of `pytest tests/ -q`>
<if schema touched: `python -m src.main validate-schema` output>
```

**CHANGELOG.md:** every hotfix PR updates `## [Unreleased]` with a one-line entry in the correct category. `RELEASES.md` is not touched — that's a release-cut action.

---

## Safety rails (will NOT do autonomously)

1. Merge any PR. Disposition C is operator-gated.
2. Delete stale branches (e.g. `fix/watch-loop-signal-crash` — already merged as `5a78839`).
3. Modify `.env`, `config/settings.local.yaml`, `.mcp.json`, or any gitignored secret file.
4. Write `CREATE TABLE` / `ALTER TABLE` outside `src/schema/registry.py`.
5. Run `scripts/render_migrate.py` (Postgres sync is operator-initiated).
6. Use `--no-verify` on any git command. If a pre-commit hook fails, fix root cause.
7. Kill the running watch loop PID, remove `data/watch.lock`, or touch the NSSM service.
8. Close existing open issues (PR merges close via `Closes #N`).
9. Force-push any branch.
10. Bump version in `MASTER.md` or anywhere else.
11. Commit before local `pytest` has run clean vs baseline. Failed runs stay uncommitted; I report and ask.
12. Echo secrets from `config/settings.local.yaml` (live Alpaca paper keys, Gmail app password) into any issue/PR/commit/log message.

---

## Done criteria

- Every in-scope issue has one of: an open PR against `main` (or stacked on another fix branch), a documented deferral with rationale, or a documented "already remediated" finding with commit SHA.
- No working-tree changes left on `main`.
- No stale branches authored by this pipeline (all pushed to `origin` as `fix/*`).
- `python -m pytest tests/ -q` on `main` post-run still at or above baseline pass count.
- Phase 4 summary posted to operator.

---

## Appendix A — Noise-floor exclusions for log sweep

Silent non-actionable skips (will NOT file, will list in Phase 4 top-10 noise report if frequent):
- Single-occurrence Tracebacks where stack top is in library code (e.g., transient `urllib3.exceptions`)
- Windows-specific `signal.signal` warnings from worker threads (fixed by `5a78839`)
- Alpaca rate-limit 429s (infrastructure, not a bug)
- Ollama temporary-unavailable with circuit breaker already in place (fixed in v0.16.7–v0.16.8)

## Appendix B — Agent prompt checklist

Every dispatched Explore agent receives:
- Exact issue number(s) and full body text
- Repo path: `/c/arcis/halcyon-lab/`
- Pointers: `MASTER.md` (conventions), `CLAUDE.md` (rules), `src/schema/registry.py` (schema SSoT)
- Read-only constraint: no writes, no Edit, no Write
- Required return shape: RCA, fix plan, affected files, test strategy
- Word cap: under 400 per issue

## Appendix C — Known edge cases flagged for operator attention

- **#456 file-length fix:** if extracting a helper from `cloud_routes/trades.py` changes the public route surface, CI's route-contract tests (if any) need re-verification.
- **#434 circular import fix:** import-order is load-bearing; any lazy-import change needs a smoke test invoking `python -m src.main startup --check-only`.
- **#413 / #459 unsafe-deserialization replacement:** if cache format changes, existing on-disk caches will be invalidated — first post-deploy run will take longer. Flag in PR body.
- **#438 governor equity=0:** need to decide fail-closed (block all trades) vs fail-safe (skip check, log loud). Deferred to agent C's analysis; operator signs off via PR review.
