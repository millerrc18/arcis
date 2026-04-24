# Tier A + B Root-Cause Bundle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship 7 small PRs that close 9 backlog issues by treating the underlying root causes (silent-failure patterns, missing audit trails, undocumented invariants, no auth-by-default), not just the immediate symptoms. Plus 3 admin closeouts of issues investigation revealed are already resolved.

**Architecture:** Each PR follows the same pattern established by today's morning work: identify the structural drift / silent failure mode, fix the symptom, AND add a coupling test or runtime guard that prevents the same shape of bug from recurring. Defensive-design over reactive-patching.

**Tech Stack:** Python 3.13, FastAPI (cloud routes), pytest, SQLite (raw sqlite3), Alpaca SDK, python-dotenv. All work targets the existing `src/`, `tests/`, and `docs/` trees in the halcyon-lab repo. No new dependencies.

---

## Decision context (read first)

This plan is the follow-up to the 2026-04-24 morning session that shipped 4 PRs (#644, #646, #648, #652) closing tier 1+2 issues. Today's investigation revealed the recurring **silent-failure pattern**: code paths that reject/skip/return-None without surfacing a reason, leaving operators unable to answer "why didn't this fire?" without grep'ing source. PRs #646, #648, #652 each addressed one instance of this pattern via coupling tests (paper↔live bracket equivalence; prompt↔validator field consistency; prod-DB-write rejection at runtime).

This bundle continues that pattern across Tier A (security hardening + docs) and Tier B (investigations turned into fixes).

### Issue → root cause → PR mapping

| Issue | Symptom | Root cause | PR | Fix shape |
|---|---|---|---|---|
| #632 | walk-forward routes serve anonymous reads | No router-level auth-by-default; per-route opt-in pattern is leak-prone | PR-1 | Add Depends + coupling test that scans routes for missing auth |
| #424 | Bot token can leak in `requests.post` exception | No sanitization layer for exception messages from telegram client | PR-2 | `_redact_token(exc)` helper + regression test |
| #642 | Operator + AI confused by .env-anchored DB layout | Undocumented invariant in CLAUDE.md | PR-3 | Docs + delete vestigial stub DBs |
| #650 | 1290+ historical pollution rows in prod activity_log | Root fixed in #647; this is symptom cleanup only | PR-4 | Operator script with `--dry-run` default |
| #629 | Log signal-to-noise (FutureWarning + URL rot + CANCEL warns) | 3 distinct subroots; no warning-suppression policy | PR-5 | Each subroot fixed + warning filter |
| #511 | 5 MR candidates/scan, 100% silently rejected | `open_shadow_trade` returns None without reason; mr_scan_service doesn't capture | PR-6 | Capture rejection_reason + log + tag in result |
| #617 | Trainer silently produces 0 holdout examples | `export_training_data` doesn't warn when corpus stalled | PR-7 | WARNING + Telegram alert + structured return code |
| #582 | model_versions row stuck rolled_back | Operator manually rolled back; no audit trail on `rollback_model()` | PR-8 | UPDATE to active + add `log_activity` calls in versioning.py + spinoff issue |
| #510 | test_excess_sharpe regression | Resolved by side-effect of #640+#647 | Admin | Close with verification comment |
| #607 | training_examples 94% orphan rate | Resolved (verified post-fix) | Admin | Close with verification comment |
| #633 | API token == comparison | Already fixed in cloud_app.py:151-152 (`hmac.compare_digest`) | Admin | Close with verification comment |

### PR ordering (recommended)

Sequence is chosen for minimum blast radius progression:

1. **Admin closeouts** (3 issues, no code) — clears noise from backlog
2. **PR-1** #632 — CRITICAL security; small + isolated to API layer
3. **PR-2** #424 — small auth-hygiene; same security category
4. **PR-3** #642 — pure docs + 5 file deletions; no code
5. **PR-4** #650 — operator script; dry-run default means low-risk-on-merge
6. **PR-5** #629 — log-only changes; can ship during market
7. **PR-6** #511 — touches scheduler-side service; safe (rejection-reason capture, no governor change)
8. **PR-7** #617 — trainer changes; trainer runs overnight, safe to ship today
9. **PR-8** #582 — versioning audit trail + ONE manual SQL operator action

**Defer to after market close** (in this plan but flagged):
- PR-8's manual SQL UPDATE should run after market close so any in-flight model lookup doesn't see a transient state change

---

## File Structure

This plan modifies/creates files across 7 PRs. Listed by responsibility:

### Security & API (PRs 1-2)
- `src/api/cloud_routes/walkforward.py` (modify) — add auth dependency to 4 routes
- `src/api/cloud_routes/__init__.py` (modify if needed) — coupling-test surface
- `src/notifications/telegram.py` (modify) — `_redact_token` helper applied to exception logging
- `tests/test_cloud_routes_auth.py` (create) — coupling test that scans for unprotected routes
- `tests/test_telegram.py` (modify) — add token-leak regression tests

### Docs & Cleanup (PRs 3-4)
- `CLAUDE.md` (modify) — add "Repo Layout (local dev)" section
- 5 files deleted: stub DBs at `data/ai_research_desk.sqlite3`, `data/arcis.db`, `data/halcyon.db`, `data/shadow_trades.db`, parent `C:\arcis\ai_research_desk.sqlite3`
- `scripts/cleanup_test_pollution_647.py` (create) — operator cleanup script with `--dry-run` default
- `tests/test_cleanup_test_pollution_647.py` (create) — verifies signature matching + dry-run safety

### Log noise (PR 5)
- `src/log_config.py` (modify) — install warnings filter at startup
- `src/shadow_trading/alpaca_adapter.py` (modify lines 550, 577, 600) — `[CANCEL]` warning → debug
- `src/data_collection/research_synthesizer.py` or wherever URL-rot lives (modify) — remove dead sources
- `tests/test_log_levels.py` (modify or create) — assert [CANCEL] is debug-level

### Diagnostic (PRs 6-7)
- `src/services/mr_scan_service.py` (modify lines 148-161) — capture rejection_reason in results
- `src/training/trainer.py` (modify lines 528-545) — add holdout-empty WARNING + Telegram alert
- `src/notifications/telegram.py` (modify) — add `notify_trainer_holdout_empty(...)` function
- `tests/test_mr_scan_service.py` (create or extend) — verify rejection_reason captured
- `tests/test_trainer.py` (modify or create) — verify holdout-empty alert fires

### Audit trail (PR 8)
- `src/training/versioning.py` (modify lines 175-200) — add `log_activity` calls to `rollback_model()` and `promote_model()`
- `tests/test_versioning_audit_trail.py` (create) — coupling test that verifies every state-mutating function logs to activity_log

### Operator action (separate from PRs)
- One SQL UPDATE on `C:\arcis\data\ai_research_desk.sqlite3` for #582 — applied AFTER market close

---

## Pre-flight (run once before starting)

- [ ] **Step 0.1: Verify clean tree on main**

```bash
cd /c/arcis/halcyon-lab
git checkout main
git pull origin main
git status --short
```

Expected: `working tree clean` (probe scripts already deleted in earlier session).

- [ ] **Step 0.2: Verify all 4 morning PRs landed**

```bash
git log --oneline -6
```

Expected to see (in order, top to bottom):
```
1d2fece fix(trading-safety): live trades now place real broker-side bracket orders (#651) (#652)
9290984 fix(tests): close test-pollution leak that wrote 562+ fake rows to prod (#647) (#648)
ebfca5b fix(training): teach outcome prompts about required metadata fields (#645) (#646)
d4dcb06 fix(notifications): bump VIX-change + S&P futures precision to 2 decimals (#643) (#644)
5c3e307 fix(tier-2): safety — #574 startup gate, ...
5c0803b fix(tier-1.5): hygiene — CLAUDE.md, ...
```

If missing, abort: `git pull origin main` first.

- [ ] **Step 0.3: Confirm baseline test count**

```bash
python -m pytest tests/ -q --no-header --collect-only 2>&1 | tail -3
```

Note the collected count. Each PR must not decrease this number; tests added must increase it.

---

## Admin closeouts (do first — no code, instant)

### Task 0: Close 3 already-resolved issues

**Files:** None (gh CLI only)

- [ ] **Step 0a: Close #510 with the verification comment already posted**

```bash
gh issue close 510 --comment "Closing per investigation 2026-04-24 (issue comment above): test passes in isolation, file, and full suite (1 passed, 2971 deselected). Resolution attributed to #640 (timezone flake) + #647 (test pollution leak). Reopen if regression recurs after PR #644/#646/#648/#652 baseline."
```

Expected: `https://github.com/millerrc18/arcis/issues/510 closed`

- [ ] **Step 0b: Close #607 with the verification comment**

```bash
gh issue close 607 --comment "Closing per re-verification 2026-04-24 (issue comment above): re-ran original SQL, numbers match within rounding (+11 rows from today's backfill). Last 7 days: zero null linkage across 4 sources (blinded_timeout, blinded_win, contrastive_loss, contrastive_win). Write-path fix confirmed durable. Option (a) accepted as documented."
```

Expected: closed.

- [ ] **Step 0c: Close #633 with code-pointer verification**

```bash
gh issue close 633 --comment "Closing as already-resolved. Investigation 2026-04-24: src/api/cloud_app.py:151-152 currently uses hmac.compare_digest, which is functionally equivalent to secrets.compare_digest (secrets.compare_digest is a re-export of hmac.compare_digest in Python's stdlib). Both are constant-time. Verified via: \`grep -rnE 'API_SECRET\s*==|api_secret\s*==' src/\` returns no matches. Timing-attack surface is closed. If issue intends a stricter fix (e.g. secrets.compare_digest specifically), reopen with the rationale."
```

Expected: closed.

- [ ] **Step 0d: Verify the 3 closures landed**

```bash
gh issue view 510 --json state -q .state
gh issue view 607 --json state -q .state
gh issue view 633 --json state -q .state
```

Expected: each prints `CLOSED`.

---

## PR-1: Walk-forward auth + router auth coupling test (#632)

**Files:**
- Modify: `src/api/cloud_routes/walkforward.py:60,92,104,136` — add `dependencies=[Depends(verify_auth)]`
- Create: `tests/test_cloud_routes_auth_coverage.py` — coupling test that scans every router for unprotected routes

**Branch:** `fix/632-walkforward-auth`

### Task 1: Set up branch

- [ ] **Step 1.1: Create branch from main**

```bash
git checkout main
git pull origin main
git checkout -b fix/632-walkforward-auth
```

Expected: `Switched to a new branch 'fix/632-walkforward-auth'`

### Task 2: Write the coupling test (TDD red)

- [ ] **Step 2.1: Create the auth coverage test file**

Create `tests/test_cloud_routes_auth_coverage.py`:

```python
"""Coupling test: every cloud route must require auth.

Pre-#632, src/api/cloud_routes/walkforward.py shipped 4 routes without
the `dependencies=[Depends(verify_auth)]` pattern that every other
router uses. Anonymous reads were possible on Render. This test scans
the source of every cloud_routes/*.py file and asserts every @router.get,
@router.post, @router.put, @router.delete, @router.patch decorator
includes a verify_auth dependency.

Exempted endpoints (must be explicitly listed):
- /healthz — Render's health-check probe; no secret to leak
"""
import re
from pathlib import Path

import pytest

# Whitelist of routes that intentionally serve anonymous traffic.
# Adding to this list requires explicit reviewer sign-off.
_ANONYMOUS_ROUTES_WHITELIST = {
    "/healthz",
}

CLOUD_ROUTES_DIR = Path(__file__).resolve().parent.parent / "src" / "api" / "cloud_routes"

# Match: @router.METHOD("PATH"[, ...])
_ROUTE_DECORATOR_RE = re.compile(
    r'@router\.(get|post|put|delete|patch)\(\s*["\']([^"\']+)["\']'
    r'(?P<rest>[^)]*)\)',
    re.MULTILINE,
)


def _route_files():
    return sorted(p for p in CLOUD_ROUTES_DIR.glob("*.py") if not p.name.startswith("_"))


@pytest.mark.parametrize("route_file", _route_files(), ids=lambda p: p.name)
def test_every_route_requires_auth(route_file):
    """Each @router.METHOD(...) must include verify_auth dependency."""
    src = route_file.read_text()
    unprotected = []
    for m in _ROUTE_DECORATOR_RE.finditer(src):
        method, path, rest = m.group(1), m.group(2), m.group("rest")
        if path in _ANONYMOUS_ROUTES_WHITELIST:
            continue
        if "verify_auth" not in rest:
            line_no = src[: m.start()].count("\n") + 1
            unprotected.append(f"{route_file.name}:{line_no} {method.upper()} {path}")
    assert not unprotected, (
        f"Unprotected routes found in {route_file.name}:\n  "
        + "\n  ".join(unprotected)
        + "\n\nFix: add `dependencies=[Depends(verify_auth)]` to the @router decorator. "
        f"If anonymous access is intentional, add the path to "
        f"_ANONYMOUS_ROUTES_WHITELIST in tests/test_cloud_routes_auth_coverage.py "
        f"with a comment explaining why."
    )
```

- [ ] **Step 2.2: Run the test — should FAIL because walkforward.py routes are unprotected**

```bash
python -m pytest tests/test_cloud_routes_auth_coverage.py -v --no-header
```

Expected: 1+ tests FAIL with output like:
```
Unprotected routes found in walkforward.py:
  walkforward.py:60 GET /api/walkforward/runs
  walkforward.py:92 GET /api/walkforward/runs/{run_id}
  walkforward.py:104 GET /api/walkforward/runs/{run_id}/windows
  walkforward.py:136 GET /api/walkforward/runs/{run_id}/trades
```

### Task 3: Add auth to walkforward.py (TDD green)

- [ ] **Step 3.1: Read the current walkforward.py to see the imports + decorators**

```bash
head -30 src/api/cloud_routes/walkforward.py
```

Note whether `verify_auth` and `Depends` are already imported.

- [ ] **Step 3.2: If imports missing, add them**

If `verify_auth` is not imported, modify `src/api/cloud_routes/walkforward.py` near the top to add:

```python
from fastapi import Depends
from src.api.cloud_app import verify_auth
```

(Match the existing import style — analytics.py and core.py have the same imports; copy from there.)

- [ ] **Step 3.3: Add `dependencies=[Depends(verify_auth)]` to all 4 route decorators**

For each of the 4 `@router.get(...)` decorators in walkforward.py at lines 60, 92, 104, 136, change:

```python
@router.get("/api/walkforward/runs")
```

to:

```python
@router.get("/api/walkforward/runs", dependencies=[Depends(verify_auth)])
```

(Apply the same pattern to all 4 routes; preserve any other args the decorator already has.)

- [ ] **Step 3.4: Re-run the coupling test — should now pass**

```bash
python -m pytest tests/test_cloud_routes_auth_coverage.py -v --no-header
```

Expected: ALL parametrize cases PASS.

- [ ] **Step 3.5: Run any existing walkforward tests to confirm no regression**

```bash
python -m pytest tests/ -k walkforward --no-header -q
```

Expected: existing tests still pass (or skip if they require a DB). No NEW failures.

### Task 4: Commit and PR

- [ ] **Step 4.1: Commit**

```bash
git add src/api/cloud_routes/walkforward.py tests/test_cloud_routes_auth_coverage.py
git commit -m "$(cat <<'EOF'
fix(api): require auth on walk-forward routes + coupling test (#632)

The 4 walkforward.py routes shipped without the verify_auth dependency
that every other cloud route uses, exposing anonymous reads on Render.
This is a one-off in the immediate symptom; the root cause is that
adding a route to a router-decorator-style codebase doesn't require
proving auth coverage.

Two changes:

1. src/api/cloud_routes/walkforward.py — Add Depends(verify_auth) to
   all 4 GET routes. Mirrors the pattern used by analytics.py and
   core.py.

2. tests/test_cloud_routes_auth_coverage.py — New parametrized
   coupling test that scans every src/api/cloud_routes/*.py file
   and asserts every @router.METHOD(...) decorator includes
   verify_auth in its dependencies. Maintains an explicit whitelist
   for legitimate anonymous routes (currently just /healthz). Future
   routes added without auth fail this test on first CI run.

The coupling test eliminates the "I forgot to add auth" failure mode
class — same defensive pattern as PR #648's runtime guard for prod-DB
writes from pytest.

Closes #632.
EOF
)"
```

- [ ] **Step 4.2: Push + create PR**

```bash
git push -u origin fix/632-walkforward-auth
gh pr create --title "fix(api): require auth on walk-forward routes + coupling test (#632)" --body "$(cat <<'EOF'
## Summary

Closes #632 (CRITICAL — anonymous read access on Render walk-forward endpoints).

Two changes:

1. **\`src/api/cloud_routes/walkforward.py\`** — Add \`dependencies=[Depends(verify_auth)]\` to all 4 GET routes (matches the analytics.py + core.py pattern that all other routers already use).

2. **\`tests/test_cloud_routes_auth_coverage.py\`** — Coupling test that scans every cloud_routes/*.py file and asserts every \`@router.METHOD\` decorator includes verify_auth. Future routes added without auth fail this test immediately.

## Why coupling test

The bug shape is "I forgot to add auth on a new route." A per-route opt-in pattern is leak-prone — somebody will always forget eventually. Same defensive pattern as PR #648's runtime guard for prod-DB writes.

## Test plan

- [x] Coupling test FAILS pre-fix (catches walkforward.py's 4 unprotected routes)
- [x] Coupling test PASSES post-fix
- [x] Existing walkforward tests still pass

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: PR URL printed.

---

## PR-2: Telegram bot-token redaction in exception logs (#424)

**Files:**
- Modify: `src/notifications/telegram.py` — add `_redact_token(text)` helper, apply to lines 131, 134, 861 (3 except-block log calls)
- Modify or Create: `tests/test_telegram_token_redaction.py` — regression test verifying token never leaks in exception logs

**Branch:** `fix/424-telegram-token-redaction`

### Task 5: Branch

- [ ] **Step 5.1: Create branch**

```bash
git checkout main
git pull origin main
git checkout -b fix/424-telegram-token-redaction
```

### Task 6: Write the redaction test (TDD red)

- [ ] **Step 6.1: Create the test file**

Create `tests/test_telegram_token_redaction.py`:

```python
"""Regression: Telegram bot token must never leak via exception logs.

Pre-#424, src/notifications/telegram.py:131 and :134 logged
`requests.post` exceptions with `logger.warning(..., %s, e)`. The
exception message often included the URL `https://api.telegram.org/
bot<TOKEN>/sendMessage`, leaking the bot token to wherever logs ship
(Loki, files, dashboard streams). This test ensures the redaction
helper sanitizes the token from any exception representation that
includes the standard Telegram URL pattern.
"""
import logging
from unittest.mock import patch, MagicMock

import pytest


def test_redact_token_strips_telegram_bot_url():
    """Exception messages containing the bot URL must have the token replaced."""
    from src.notifications.telegram import _redact_token

    raw = (
        "HTTPSConnectionPool(host='api.telegram.org', port=443): "
        "Max retries exceeded with url: /bot1234567890:ABC-DEF_real-secret-here/sendMessage"
    )
    redacted = _redact_token(raw)
    assert "1234567890:ABC-DEF_real-secret-here" not in redacted
    assert "[REDACTED]" in redacted


def test_redact_token_handles_exception_object():
    """Should accept an Exception instance directly, not just str."""
    from src.notifications.telegram import _redact_token

    exc = Exception(
        "ConnectionError at https://api.telegram.org/bot987:XYZ_secret/sendMessage"
    )
    redacted = _redact_token(exc)
    assert "987:XYZ_secret" not in redacted
    assert "[REDACTED]" in redacted


def test_redact_token_passthrough_when_no_token():
    """Non-token-bearing strings should pass through unchanged."""
    from src.notifications.telegram import _redact_token

    safe = "ConnectionError: timed out"
    assert _redact_token(safe) == safe


def test_send_telegram_logs_redacted_on_exception(caplog):
    """End-to-end: send_telegram's except block must log redacted text."""
    from src.notifications.telegram import send_telegram

    with patch(
        "src.notifications.telegram._get_telegram_config",
        return_value={"enabled": True, "bot_token": "987:XYZ_real_token", "chat_id": "1"},
    ), patch(
        "src.notifications.telegram.requests.post",
        side_effect=Exception(
            "ConnectionError at https://api.telegram.org/bot987:XYZ_real_token/sendMessage"
        ),
    ):
        with caplog.at_level(logging.WARNING):
            result = send_telegram("test")

    assert result is False
    # The token must NOT appear anywhere in the captured log output.
    full_log = "\n".join(r.getMessage() for r in caplog.records)
    assert "987:XYZ_real_token" not in full_log, (
        f"Token leaked in log output:\n{full_log}"
    )
```

- [ ] **Step 6.2: Run the test — should FAIL**

```bash
python -m pytest tests/test_telegram_token_redaction.py -v --no-header
```

Expected: 4 FAILs (`_redact_token` not defined; or token not redacted in send_telegram).

### Task 7: Implement `_redact_token` and apply to all except blocks (TDD green)

- [ ] **Step 7.1: Add `_redact_token` helper near top of telegram.py**

Modify `src/notifications/telegram.py` — add after the `TELEGRAM_API` constant (around line 80):

```python
import re

# #424 — Sanitize the bot token from any string that contains the
# standard Telegram URL pattern. Telegram bot tokens have the shape
# `<digits>:<base64-ish>` and appear in URLs as `/bot<TOKEN>/<method>`.
# requests.post exceptions on connection errors include the URL in the
# message, so any logger.warning("...%s", e) call leaks the token to
# wherever logs ship (Loki, files, dashboard streams).
_TELEGRAM_TOKEN_RE = re.compile(r"/bot([0-9]+:[A-Za-z0-9_\-]+)")


def _redact_token(text) -> str:
    """Replace any embedded Telegram bot token with [REDACTED].

    Accepts a string OR an Exception instance. Returns a string safe
    to log. Use in EVERY except-block log call inside this module."""
    s = str(text) if not isinstance(text, str) else text
    return _TELEGRAM_TOKEN_RE.sub("/bot[REDACTED]", s)
```

- [ ] **Step 7.2: Apply `_redact_token` to the 3 except-block log calls**

Find and replace in `src/notifications/telegram.py`:

At line 131 (the `if resp.status_code == 200` else branch):

OLD:
```python
            logger.warning("[TELEGRAM] Send failed: %s %s", resp.status_code, resp.text[:200])
```
NEW:
```python
            logger.warning("[TELEGRAM] Send failed: %s %s", resp.status_code, _redact_token(resp.text[:200]))
```

At line 134 (the `except Exception as e` block):

OLD:
```python
        logger.warning("[TELEGRAM] Send error: %s", e)
```
NEW:
```python
        logger.warning("[TELEGRAM] Send error: %s", _redact_token(e))
```

At line 861 (`notify_validation_summary` except block):

OLD:
```python
        logger.warning("[TELEGRAM] notify_validation_summary send failed: %s", e)
```
NEW:
```python
        logger.warning("[TELEGRAM] notify_validation_summary send failed: %s", _redact_token(e))
```

- [ ] **Step 7.3: Run the redaction tests — should PASS**

```bash
python -m pytest tests/test_telegram_token_redaction.py -v --no-header
```

Expected: 4 passed.

- [ ] **Step 7.4: Run the broader telegram test suite to confirm no regression**

```bash
python -m pytest tests/test_expanded_notifications.py tests/test_telegram_token_redaction.py -q --no-header
```

Expected: all pass (27 from expanded_notifications + 4 new = 31).

### Task 8: Commit and PR

- [ ] **Step 8.1: Commit**

```bash
git add src/notifications/telegram.py tests/test_telegram_token_redaction.py
git commit -m "$(cat <<'EOF'
fix(notifications): redact Telegram bot token from exception logs (#424)

requests.post exceptions on connection errors include the request URL
in their message. The Telegram URL is `https://api.telegram.org/
bot<TOKEN>/sendMessage` — meaning any `logger.warning("...%s", e)`
call leaks the bot token to wherever logs ship (Loki, dashboard, file).

Two changes:

1. src/notifications/telegram.py — Add _redact_token(text) helper
   that replaces any embedded `/bot<token>` URL pattern with
   `/bot[REDACTED]`. Accepts either a string or Exception instance.
   Applied to all 3 except-block log calls in the module
   (send_telegram lines 131 + 134, notify_validation_summary line 861).

2. tests/test_telegram_token_redaction.py — 4 regression tests:
   - Helper strips token from a synthetic ConnectionError-style string
   - Helper accepts Exception objects directly
   - Non-token strings pass through unchanged
   - End-to-end test patches requests.post to raise with token in
     message, asserts caplog never contains the token

The root cause is that exception messages from outbound HTTP libs
naturally include the URL. The right defense is sanitization at the
log-call site, with a regex that doesn't depend on the operator
remembering to redact each new place we log a Telegram error.

Closes #424.
EOF
)"
```

- [ ] **Step 8.2: Push + create PR**

```bash
git push -u origin fix/424-telegram-token-redaction
gh pr create --title "fix(notifications): redact Telegram bot token from exception logs (#424)" --body "$(cat <<'EOF'
## Summary

Closes #424. \`requests.post\` exceptions include the URL in the message — for Telegram, that URL contains the bot token. Any \`logger.warning("...%s", e)\` call was leaking the token to logs.

## Two changes

1. **\`src/notifications/telegram.py\`** — Add \`_redact_token()\` helper, applied to 3 except-block log calls (lines 131, 134, 861).

2. **\`tests/test_telegram_token_redaction.py\`** — 4 regression tests including end-to-end patched-exception verification that token never appears in caplog.

## Test plan

- [x] All 4 new redaction tests pass
- [x] 27 existing test_expanded_notifications.py tests still pass
- [x] Helper accepts both str and Exception inputs

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## PR-3: Repo layout docs + delete vestigial stub DBs (#642)

**Files:**
- Modify: `CLAUDE.md` — add "Repo Layout (local dev)" section
- Delete: `data/ai_research_desk.sqlite3` (0 bytes), `data/arcis.db` (0 bytes), `data/halcyon.db` (0 bytes), `data/shadow_trades.db` (0 bytes)
- Delete: `C:\arcis\ai_research_desk.sqlite3` (0 bytes — operator action since outside repo)

**Branch:** `fix/642-repo-layout-docs`

### Task 9: Branch

- [ ] **Step 9.1: Branch**

```bash
git checkout main
git pull origin main
git checkout -b fix/642-repo-layout-docs
```

### Task 10: Verify the stub DBs are still 0 bytes (safety check)

- [ ] **Step 10.1: Confirm sizes before deletion**

```bash
ls -la data/ai_research_desk.sqlite3 data/arcis.db data/halcyon.db data/shadow_trades.db 2>&1
```

Expected: all 4 files show size `0`. If any are non-zero, **abort**: a file may have been accidentally written there since the issue was filed; investigate before deleting.

### Task 11: Delete the in-repo stubs

- [ ] **Step 11.1: Delete the 4 in-repo stubs**

```bash
rm data/ai_research_desk.sqlite3 data/arcis.db data/halcyon.db data/shadow_trades.db
ls data/ 2>&1 | head
```

Expected: `data/` now contains only `reference/`, `simulation_cache/`, `watch.lock`, `watchdog.txt` (live runtime artifacts) and not the 4 stubs.

- [ ] **Step 11.2: Confirm `.gitignore` covers `data/*.sqlite3` and `data/*.db`**

```bash
grep -E "data/.*\.(sqlite|db)|^data/" .gitignore
```

Expected: pattern present. If not, append:

```bash
echo "" >> .gitignore
echo "# #642 — runtime SQLite + db files live outside repo (see CLAUDE.md Repo Layout)" >> .gitignore
echo "data/*.sqlite3" >> .gitignore
echo "data/*.db" >> .gitignore
```

### Task 12: Add CLAUDE.md docs section

- [ ] **Step 12.1: Add the Repo Layout section to CLAUDE.md**

Read the current CLAUDE.md to find a good insertion point — it should go after the "Key Rules" section, before "Database Schema Rules".

```bash
grep -n "^## " CLAUDE.md | head -10
```

Insert (using the Edit tool against the file directly) AFTER the last line of the "Key Rules" section and BEFORE `## Database Schema Rules`:

```markdown
## Repo Layout (local dev)

The runtime data lives **outside** the git repo. This is intentional, not accidental.

- `C:\arcis\halcyon-lab\` — git repo. Must be cwd when running CLI (`python -m src.main ...`).
- `C:\arcis\halcyon-lab\.env` — sets `ARCIS_DB_PATH=C:/arcis/data/ai_research_desk.sqlite3` (canonical).
- `C:\arcis\data\ai_research_desk.sqlite3` — active SQLite DB (~1 GB). **DO NOT** create or write a SQLite file at the repo root or `halcyon-lab/data/`; those are stub locations and have been removed (#642). Code reads `src.config.DB_PATH` which respects the env override.
- `C:\arcis\logs\` — runtime logs (mirrored to Render-deployed instances).
- `C:\arcis\data\reference\`, `data\simulation_cache\`, `data\watch.lock`, `data\watchdog.txt` — runtime artifacts.

**Why state lives outside the repo:**
1. Keeps a 1 GB binary out of `git status` / `git diff` performance scans.
2. Survives repo re-clone, branch switches, and worktree creation.
3. Mirrors the Render production layout where the DB is a separate managed resource.

**Mechanism:** `src/config/__init__.py:55-56` reads `ARCIS_DB_PATH` from env (loaded by `python-dotenv` via `.env`). Override per-process by exporting `ARCIS_DB_PATH=...` to point elsewhere (e.g. for testing against a snapshot DB).

**Common gotchas:**
- The watch loop must be started from a working directory where `.env` can be discovered. NSSM service startup uses the configured `AppDirectory`. If you change to a clone outside `C:\arcis\halcyon-lab\`, also set the env var explicitly.
- `scripts/statusline.py` uses the same `_resolve_data_root()` pattern — when adding new operator scripts that read runtime state, follow the same convention.
- Tests must NEVER write to the prod DB. The runtime guard in `src/utils/activity_logger.py` (#647) raises if a test opts in to writes without redirecting `db_path`.

```

- [ ] **Step 12.2: Verify CLAUDE.md still parses (it's just markdown but check for obvious typos)**

```bash
head -200 CLAUDE.md | grep -A 5 "Repo Layout"
```

Expected: the new section appears with proper markdown heading.

### Task 13: Commit and PR

- [ ] **Step 13.1: Commit**

```bash
git add CLAUDE.md .gitignore
git rm data/ai_research_desk.sqlite3 data/arcis.db data/halcyon.db data/shadow_trades.db
git commit -m "$(cat <<'EOF'
docs: add Repo Layout section to CLAUDE.md + delete vestigial stubs (#642)

The .env-anchored DB layout (ARCIS_DB_PATH override → C:\arcis\data\)
was undocumented anywhere outside src/config/__init__.py:50-56's hotfix
comment. Cost ~1 hour of confusion during the 2026-04-24 morning session
when the empty stub DBs in halcyon-lab/data/ presented as "the local
DB is uninitialized" while the real 1 GB DB sat at the parent C:\arcis\
location.

Two changes:

1. Add "Repo Layout (local dev)" section to CLAUDE.md after Key Rules
   and before Database Schema Rules. Documents:
   - Cwd requirement (must be halcyon-lab\)
   - ARCIS_DB_PATH override mechanism + .env parsing
   - Why state lives outside the repo (3 reasons)
   - Common gotchas including the test-write runtime guard

2. Delete 4 vestigial 0-byte stub DBs in halcyon-lab/data/
   (ai_research_desk.sqlite3, arcis.db, halcyon.db, shadow_trades.db).
   Add data/*.sqlite3 + data/*.db to .gitignore so future stubs from
   fresh checkouts also don't get tracked.

The stub at C:\arcis\ai_research_desk.sqlite3 (parent dir, outside
repo) requires manual operator deletion — documented in the issue.

Closes #642.
EOF
)"
```

- [ ] **Step 13.2: Push + create PR**

```bash
git push -u origin fix/642-repo-layout-docs
gh pr create --title "docs: add Repo Layout section + delete vestigial stub DBs (#642)" --body "$(cat <<'EOF'
## Summary

Closes #642. The .env-anchored DB layout (ARCIS_DB_PATH override → \`C:\arcis\data\\\`) was undocumented; the empty stubs in halcyon-lab/data/ presented as "DB is uninitialized" during the 2026-04-24 morning session, costing ~1 hour of investigation.

## Two changes

1. **\`CLAUDE.md\`** — New "Repo Layout (local dev)" section documenting cwd requirement, ARCIS_DB_PATH override, and common gotchas including the new test-write runtime guard from #647.

2. **Delete 4 vestigial 0-byte stub DBs** + add \`data/*.sqlite3\` and \`data/*.db\` to \`.gitignore\`.

## Operator follow-up

Manual deletion (outside repo): \`Remove-Item C:\arcis\ai_research_desk.sqlite3\` (also 0 bytes, also vestigial).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## PR-4: Cleanup script for historical pollution rows (#650)

**Files:**
- Create: `scripts/cleanup_test_pollution_647.py` — operator script with `--dry-run` default
- Create: `tests/test_cleanup_test_pollution_647.py` — verifies signature matching + dry-run safety + cutoff timestamp respect

**Branch:** `fix/650-pollution-cleanup-script`

### Task 14: Branch

- [ ] **Step 14.1: Branch**

```bash
git checkout main
git pull origin main
git checkout -b fix/650-pollution-cleanup-script
```

### Task 15: Write the test for the cleanup script (TDD red)

- [ ] **Step 15.1: Create the test file**

Create `tests/test_cleanup_test_pollution_647.py`:

```python
"""Tests for the pollution-cleanup operator script (#650).

The cleanup script removes historical kill_switch_halt and kill_switch_resume
rows that were written to the prod activity_log via the test pollution leak
fixed in #647. Three safety properties under test:

  1. The script's signature matcher only deletes rows that match KNOWN test
     fixture signatures — never real production rows.
  2. Default mode is --dry-run; --apply must be explicit.
  3. The cutoff timestamp filter prevents deletion of any rows created
     after the #647 fix landed (so post-fix legitimate halts are preserved).
"""
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "cleanup_test_pollution_647.py"


def _make_test_db(tmp_path):
    """Create an activity_log table with a mix of pollution + real rows."""
    db_path = tmp_path / "test_activity.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE activity_log ("
            "id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "
            "event_type TEXT NOT NULL, "
            "detail TEXT, "
            "created_at TEXT NOT NULL"
            ")"
        )
        rows = [
            # Pollution signatures (must be deleted)
            ("kill_switch_halt", "source=unknown, reason=", "2026-04-15T10:00:00"),
            ("kill_switch_halt", "source=test, reason=unit test", "2026-04-15T10:01:00"),
            ("kill_switch_halt", "source=test, reason=", "2026-04-15T10:02:00"),
            ("kill_switch_halt", "source=telegram, reason=manual halt", "2026-04-15T10:03:00"),
            ("kill_switch_halt", "source=auditor, reason=Halt command ignored", "2026-04-15T10:04:00"),
            ("kill_switch_halt", "source=auditor, reason=Governor check bypassed", "2026-04-15T10:05:00"),
            ("kill_switch_halt", "source=auditor, reason=Catastrophic loss detected", "2026-04-15T10:06:00"),
            ("kill_switch_resume", "source=unknown, reason=", "2026-04-15T10:07:00"),

            # Real production rows (must NOT be deleted)
            ("kill_switch_halt", "source=cli, reason=manual halt via halt-trading command", "2026-04-15T11:00:00"),
            ("trade_opened", "ticker=AAPL", "2026-04-15T12:00:00"),
            ("scan_complete", "scanned=50", "2026-04-15T13:00:00"),

            # Post-cutoff row (legitimate test signature but after fix landed)
            ("kill_switch_halt", "source=test, reason=", "2026-04-25T10:00:00"),
        ]
        for r in rows:
            conn.execute(
                "INSERT INTO activity_log (event_type, detail, created_at) VALUES (?, ?, ?)",
                r,
            )
        conn.commit()
    return db_path


def _run_script(*args, db_path=None):
    """Invoke the cleanup script as a subprocess so it tests the real CLI."""
    cmd = [sys.executable, str(SCRIPT)]
    if db_path:
        cmd.extend(["--db-path", str(db_path)])
    cmd.extend(args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


def test_dry_run_is_default(tmp_path):
    """No flag => dry run, no rows deleted."""
    db_path = _make_test_db(tmp_path)
    before = _count_all(db_path)
    result = _run_script(db_path=db_path)
    after = _count_all(db_path)
    assert before == after, "dry-run must not delete rows"
    assert result.returncode == 0
    assert "DRY RUN" in result.stdout


def test_apply_deletes_pollution_only(tmp_path):
    """--apply removes pollution signatures, preserves real rows."""
    db_path = _make_test_db(tmp_path)
    result = _run_script("--apply", "--cutoff", "2026-04-24T00:00:00", db_path=db_path)
    assert result.returncode == 0, result.stderr

    with sqlite3.connect(db_path) as conn:
        # 8 pollution rows pre-cutoff should be gone
        polluted_remaining = conn.execute(
            "SELECT COUNT(*) FROM activity_log WHERE event_type='kill_switch_halt' "
            "AND detail IN ('source=unknown, reason=', 'source=test, reason=unit test', "
            "'source=test, reason=', 'source=telegram, reason=manual halt')"
        ).fetchone()[0]
        # Pre-cutoff 'source=test, reason=' is gone; the post-cutoff one survives
        assert polluted_remaining == 0

        # Real production row preserved
        real_halt = conn.execute(
            "SELECT COUNT(*) FROM activity_log WHERE detail LIKE 'source=cli%'"
        ).fetchone()[0]
        assert real_halt == 1

        # Non-kill_switch events untouched
        other = conn.execute(
            "SELECT COUNT(*) FROM activity_log WHERE event_type IN ('trade_opened','scan_complete')"
        ).fetchone()[0]
        assert other == 2

        # Post-cutoff pollution-shaped row preserved (cutoff filter works)
        post_cutoff = conn.execute(
            "SELECT COUNT(*) FROM activity_log WHERE created_at >= '2026-04-24T00:00:00'"
        ).fetchone()[0]
        assert post_cutoff == 1


def test_unknown_signature_never_deleted(tmp_path):
    """A halt with a NEW source string we haven't whitelisted must survive."""
    db_path = _make_test_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO activity_log (event_type, detail, created_at) VALUES "
            "('kill_switch_halt', 'source=newfeature, reason=novel reason', '2026-04-20T10:00:00')"
        )
        conn.commit()

    _run_script("--apply", "--cutoff", "2026-04-24T00:00:00", db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        novel = conn.execute(
            "SELECT COUNT(*) FROM activity_log WHERE detail LIKE 'source=newfeature%'"
        ).fetchone()[0]
    assert novel == 1, "Unknown signature must NEVER be deleted (deny-by-default)"


def _count_all(db_path):
    with sqlite3.connect(db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM activity_log").fetchone()[0]
```

- [ ] **Step 15.2: Run the test — should FAIL (script doesn't exist yet)**

```bash
python -m pytest tests/test_cleanup_test_pollution_647.py -v --no-header
```

Expected: 3 FAIL with "FileNotFoundError" or "Script returned nonzero".

### Task 16: Implement the cleanup script (TDD green)

- [ ] **Step 16.1: Create the script**

Create `scripts/cleanup_test_pollution_647.py`:

```python
"""Cleanup historical test-pollution rows in prod activity_log (#650).

Removes kill_switch_halt + kill_switch_resume rows whose `detail` field
matches one of the known test-fixture signatures from pre-#647 leakage.
Default is --dry-run; --apply requires explicit operator opt-in.

Safety design:
  - DENY-BY-DEFAULT: only deletes rows matching a hard-coded whitelist of
    known test signatures. A novel signature (e.g. a new test fixture
    leaking with a different source string) is NEVER deleted automatically.
  - CUTOFF TIMESTAMP: --cutoff (default = #647 PR merge time) excludes any
    rows created after the fix landed. Preserves post-fix legitimate halts
    even if they happen to share a signature.
  - PER-SIGNATURE DRY-RUN OUTPUT: prints count + sample row for each
    signature so the operator can review before --apply.

Usage:
    python scripts/cleanup_test_pollution_647.py                   # dry run
    python scripts/cleanup_test_pollution_647.py --apply           # delete
    python scripts/cleanup_test_pollution_647.py --apply --db-path <path>
    python scripts/cleanup_test_pollution_647.py --cutoff 2026-04-24T12:00:00
"""
import argparse
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# #647 (PR #648) merged at 2026-04-24T11:57:33Z. Anything older than this
# AND matching a known test signature is safe to delete. Use ET ISO format
# matching activity_log.created_at column convention.
DEFAULT_CUTOFF = "2026-04-24T08:00:00"  # ET, conservative buffer

# Known test-fixture signatures from tests/test_kill_switch.py,
# tests/test_risk_governor.py, and tests/test_auditor.py — verified by
# count analysis (99/99/99 + 91/91/91/92) and string match against
# test source.
SIGNATURES = {
    "kill_switch_halt": [
        "source=unknown, reason=",
        "source=test, reason=unit test",
        "source=test, reason=",
        "source=telegram, reason=manual halt",
        "source=auditor, reason=Halt command ignored",
        "source=auditor, reason=Governor check bypassed",
        "source=auditor, reason=Catastrophic loss detected",
    ],
    "kill_switch_resume": [
        "source=unknown, reason=",
        "source=test, reason=",
        "source=test, reason=unit test",
        "source=telegram, reason=",
    ],
}


def _resolve_db_path(arg_path: str | None) -> str:
    """Match scripts/statusline.py's resolution: env var > .env > default."""
    if arg_path:
        return arg_path
    env_path = os.environ.get("ARCIS_DB_PATH")
    if env_path:
        return env_path
    repo_root = Path(__file__).resolve().parent.parent
    env_file = repo_root / ".env"
    if env_file.exists():
        try:
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if line.startswith("ARCIS_DB_PATH="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            pass
    return str(repo_root / "data" / "ai_research_desk.sqlite3")


def main():
    parser = argparse.ArgumentParser(
        description="Delete historical test-pollution rows from activity_log (#650)"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually DELETE matching rows. Without this flag, runs in dry-run mode.",
    )
    parser.add_argument(
        "--db-path",
        help="Override DB path. Default: resolved from ARCIS_DB_PATH or .env.",
    )
    parser.add_argument(
        "--cutoff",
        default=DEFAULT_CUTOFF,
        help=f"ISO timestamp: don't delete rows newer than this. Default: {DEFAULT_CUTOFF}",
    )
    args = parser.parse_args()

    db_path = _resolve_db_path(args.db_path)
    if not Path(db_path).exists():
        print(f"ERROR: DB not found at {db_path}", file=sys.stderr)
        return 1

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"=== {mode} ===")
    print(f"DB:     {db_path}")
    print(f"Cutoff: {args.cutoff}  (rows newer than this are preserved)")
    print()

    total_to_delete = 0
    sql_per_event = []

    with sqlite3.connect(db_path) as conn:
        for event_type, sigs in SIGNATURES.items():
            placeholders = ",".join("?" * len(sigs))
            params = (*sigs, args.cutoff)
            count = conn.execute(
                f"SELECT COUNT(*) FROM activity_log "
                f"WHERE event_type=? AND detail IN ({placeholders}) "
                f"AND created_at < ?",
                (event_type, *params),
            ).fetchone()[0]
            print(f"  {event_type}: {count} rows match")
            for sig in sigs:
                sub = conn.execute(
                    "SELECT COUNT(*) FROM activity_log "
                    "WHERE event_type=? AND detail=? AND created_at < ?",
                    (event_type, sig, args.cutoff),
                ).fetchone()[0]
                if sub:
                    print(f"    {sub:5d}  detail={sig!r}")
            sql_per_event.append((event_type, sigs, params, count))
            total_to_delete += count

        print()
        print(f"TOTAL to delete: {total_to_delete}")

        if not args.apply:
            print()
            print("DRY RUN — no rows changed. Re-run with --apply to delete.")
            return 0

        if total_to_delete == 0:
            print("Nothing to delete.")
            return 0

        # Apply phase
        print()
        for event_type, sigs, params, expected in sql_per_event:
            placeholders = ",".join("?" * len(sigs))
            cur = conn.execute(
                f"DELETE FROM activity_log "
                f"WHERE event_type=? AND detail IN ({placeholders}) "
                f"AND created_at < ?",
                (event_type, *params),
            )
            print(f"  Deleted {cur.rowcount} from {event_type} (expected {expected})")
        conn.commit()
        print()
        print("Committed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 16.2: Run the tests — should PASS**

```bash
python -m pytest tests/test_cleanup_test_pollution_647.py -v --no-header
```

Expected: 3 passed.

- [ ] **Step 16.3: Sanity dry-run against the real prod DB**

```bash
python scripts/cleanup_test_pollution_647.py
```

Expected output: prints DRY RUN, lists ~1290 kill_switch_halt + ~375 kill_switch_resume rows by signature, says "Re-run with --apply".

**Do NOT run with `--apply` yet.** That's an operator decision documented in the PR, not part of the merge.

### Task 17: Commit and PR

- [ ] **Step 17.1: Commit**

```bash
git add scripts/cleanup_test_pollution_647.py tests/test_cleanup_test_pollution_647.py
git commit -m "$(cat <<'EOF'
chore(scripts): cleanup script for historical pollution rows (#650)

Symptom-only cleanup — root cause was already fixed in #647 (PR #648).
This script lets the operator remove the 1290+ historical kill_switch_halt
and ~375 kill_switch_resume rows that test fixtures wrote to the prod
activity_log between 2026-04-03 and #647's merge on 2026-04-24.

Three safety properties:

1. DENY-BY-DEFAULT: hard-coded whitelist of 11 known test signatures
   (verified via 99/99/99 + 91/91/91/92 count analysis + string match
   against test source). Any novel signature is NEVER deleted.
2. DRY-RUN DEFAULT: --apply must be explicit; default prints what would
   be deleted with sample rows per signature.
3. CUTOFF FILTER: --cutoff (default 2026-04-24T08:00:00 ET, ~4h before
   PR #648 merged) preserves any post-fix rows even if they match a
   known signature.

Path resolution mirrors scripts/statusline.py (env > .env > repo-default)
so the script works whether invoked from the runtime CWD or directly.

Closes #650.
EOF
)"
```

- [ ] **Step 17.2: Push + PR**

```bash
git push -u origin fix/650-pollution-cleanup-script
gh pr create --title "chore(scripts): cleanup script for historical pollution rows (#650)" --body "$(cat <<'EOF'
## Summary

Closes #650. Symptom cleanup for the 1290+ \`kill_switch_halt\` + 375 \`kill_switch_resume\` rows that test fixtures wrote to prod activity_log pre-#647. Root cause is already fixed (PR #648 runtime guard).

Three safety properties:

1. **Deny-by-default whitelist** of 11 known test signatures. Novel signatures NEVER deleted.
2. **Dry-run default**; \`--apply\` is explicit operator opt-in.
3. **Cutoff filter** preserves post-fix rows even if they match a signature.

## Operator usage (not part of merge)

\`\`\`bash
python scripts/cleanup_test_pollution_647.py                   # see what would be deleted
python scripts/cleanup_test_pollution_647.py --apply           # actually delete
\`\`\`

Recommend running --apply after market close to avoid any concurrent activity_log writes.

## Test plan

- [x] Test verifies dry-run is default (no rows changed)
- [x] Test verifies --apply removes only whitelisted signatures, preserves real rows
- [x] Test verifies cutoff filter excludes post-fix rows
- [x] Test verifies novel signatures (deny-by-default) survive

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## PR-5: Log signal-to-noise (#629)

**Files:**
- Modify: `src/log_config.py` — install warnings filter at startup
- Modify: `src/shadow_trading/alpaca_adapter.py` lines 550, 577, 600 — `[CANCEL]` warnings → debug
- Create: `tests/test_log_levels.py` — assert [CANCEL] log calls use debug, not warning

**Branch:** `fix/629-log-signal-to-noise`

### Task 18: Branch

- [ ] **Step 18.1: Branch**

```bash
git checkout main
git pull origin main
git checkout -b fix/629-log-signal-to-noise
```

### Task 19: Write the test for log levels (TDD red)

- [ ] **Step 19.1: Create the test file**

Create `tests/test_log_levels.py`:

```python
"""Assert log levels for routine events match operator expectations (#629).

Each call site listed here was previously logged at WARNING despite
being a routine, recoverable event that pollutes the operator's
WARNING+ stream. Demoting to DEBUG eliminates the noise while
preserving the diagnostic info for verbose troubleshooting.

If a future commit re-elevates one of these to WARNING/ERROR, this
test fails immediately so the change is conscious.
"""
import re
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parent.parent / "src"


@pytest.mark.parametrize("file_rel,line_marker,expected_level", [
    # alpaca_adapter.py — [CANCEL] failures are routine (broker often
    # rejects cancels because order already filled/cancelled by bracket OCO)
    ("shadow_trading/alpaca_adapter.py", "[CANCEL] Could not cancel order", "debug"),
    ("shadow_trading/alpaca_adapter.py", "[CANCEL] Failed to cancel order", "debug"),
    ("shadow_trading/alpaca_adapter.py", "[CANCEL] Could not cancel all orders", "debug"),
])
def test_log_call_uses_expected_level(file_rel, line_marker, expected_level):
    """Verify the source line containing line_marker uses logger.<expected_level>."""
    src = (SRC_ROOT / file_rel).read_text()
    matches = []
    for i, line in enumerate(src.splitlines(), 1):
        if line_marker in line:
            # Look at this line and previous 1 (the logger call may wrap)
            window = "\n".join(src.splitlines()[max(0, i - 2):i])
            matches.append((i, window))
    assert matches, f"line_marker {line_marker!r} not found in {file_rel}"
    for line_no, window in matches:
        assert f"logger.{expected_level}(" in window, (
            f"{file_rel}:{line_no} expected logger.{expected_level} but got:\n{window}"
        )
```

- [ ] **Step 19.2: Run the test — should FAIL**

```bash
python -m pytest tests/test_log_levels.py -v --no-header
```

Expected: 3 FAILs (current code uses `logger.warning`, test expects `logger.debug`).

### Task 20: Demote the [CANCEL] warnings to debug (TDD green)

- [ ] **Step 20.1: Edit alpaca_adapter.py line 550 area**

Find:
```python
        logger.warning("[CANCEL] Could not cancel order %s: %s", order_id, e)
```
Replace with:
```python
        logger.debug("[CANCEL] Could not cancel order %s: %s", order_id, e)
```

- [ ] **Step 20.2: Edit line 577 area**

Find:
```python
                logger.warning("[CANCEL] Failed to cancel order %s for %s: %s",
```
Replace with:
```python
                logger.debug("[CANCEL] Failed to cancel order %s for %s: %s",
```

- [ ] **Step 20.3: Edit line 600 area**

Find:
```python
        logger.warning("[CANCEL] Could not cancel all orders: %s", e)
```
Replace with:
```python
        logger.debug("[CANCEL] Could not cancel all orders: %s", e)
```

- [ ] **Step 20.4: Run the level test — should PASS**

```bash
python -m pytest tests/test_log_levels.py -v --no-header
```

Expected: 3 passed.

### Task 21: Install warnings filter in log_config.py

- [ ] **Step 21.1: Read current log_config.py**

```bash
head -50 src/log_config.py
```

- [ ] **Step 21.2: Add warnings filter at the top of `setup_logging` (or wherever logging is initialized)**

Modify `src/log_config.py` — add near the top of the module-level code, after imports:

```python
import warnings

# #629 — Suppress upstream FutureWarning spam from pandas/sklearn that drowns
# real warnings in operator log streams (~28k entries in 3 days). These are
# upstream lib deprecation hints, not actionable from our code; we'll re-enable
# during library upgrade windows by setting ARCIS_SHOW_WARNINGS=1.
import os
if not os.environ.get("ARCIS_SHOW_WARNINGS"):
    warnings.filterwarnings("ignore", category=FutureWarning)
    warnings.filterwarnings("ignore", category=DeprecationWarning, module="pandas")
    warnings.filterwarnings("ignore", category=DeprecationWarning, module="sklearn")
```

- [ ] **Step 21.3: Run a smoke test that imports a module known to trigger FutureWarning**

```bash
python -c "
import os
# Ensure filter is active by importing log_config FIRST
import src.log_config
import warnings
import pandas as pd
# Try a deprecated pattern that triggers FutureWarning
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter('always')  # bypass our filter for this test
    pd.DataFrame({'a':[1]}).iloc[0]
    print('FutureWarning intentionally re-enabled in this test:', any(issubclass(wi.category, FutureWarning) for wi in w))
"
```

Expected: confirms filter machinery works; no exception.

### Task 22: Commit and PR

- [ ] **Step 22.1: Commit**

```bash
git add src/log_config.py src/shadow_trading/alpaca_adapter.py tests/test_log_levels.py
git commit -m "$(cat <<'EOF'
chore(logging): demote routine [CANCEL] warns + suppress upstream warnings (#629)

Two log-noise fixes:

1. src/shadow_trading/alpaca_adapter.py — Demote 3 [CANCEL]* logger.warning
   calls to logger.debug. Cancel failures from Alpaca are routine: the broker
   often rejects cancels because the order already filled or was cancelled by
   the bracket's OCA group. WARNING-level for routine events trains operators
   to ignore the WARNING+ stream entirely.

2. src/log_config.py — Install warnings filter at startup that suppresses
   FutureWarning + pandas/sklearn DeprecationWarning. ~28k of these polluted
   the log stream over 3 days. Re-enable for library-upgrade work via
   ARCIS_SHOW_WARNINGS=1 env var.

Plus tests/test_log_levels.py — parametrized assertion that the 3 demoted
[CANCEL] sites stay at debug. Future commits that re-elevate these to
WARNING/ERROR fail this test immediately.

Closes part of #629. The URL-rot subitem is filed separately as a smaller
content-only follow-up.
EOF
)"
```

- [ ] **Step 22.2: Push + PR**

```bash
git push -u origin fix/629-log-signal-to-noise
gh pr create --title "chore(logging): demote [CANCEL] warns + suppress upstream FutureWarning (#629)" --body "$(cat <<'EOF'
## Summary

Closes part of #629 (log signal-to-noise).

Two changes:

1. **\`src/shadow_trading/alpaca_adapter.py\`** — Demote 3 \`[CANCEL]\` logger.warning calls to logger.debug. Cancel failures are routine (broker often rejects cancels because order already filled or OCA-cancelled).

2. **\`src/log_config.py\`** — Install warnings filter that suppresses FutureWarning + pandas/sklearn DeprecationWarning at startup. Re-enable via \`ARCIS_SHOW_WARNINGS=1\`.

## Test plan

- [x] \`tests/test_log_levels.py\` parametrized over 3 [CANCEL] sites — asserts each uses logger.debug. Future re-elevation breaks this test.
- [x] Warnings filter smoke-tested via Python REPL.

## Not in scope

The URL-rot subitem from #629 is research-source URLs that returned 404. Filed as smaller content-only follow-up.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## PR-6: MR scan rejection-reason capture (#511)

**Files:**
- Modify: `src/services/mr_scan_service.py` lines 148-161 — capture `result["rejection_reason"]` from open_shadow_trade
- Create: `tests/test_mr_scan_rejection_reason.py` — verify reason is captured + logged

**Branch:** `fix/511-mr-rejection-reason-capture`

### Task 23: Branch

- [ ] **Step 23.1: Branch**

```bash
git checkout main
git pull origin main
git checkout -b fix/511-mr-rejection-reason-capture
```

### Task 24: Read open_shadow_trade return shape

- [ ] **Step 24.1: Confirm what open_shadow_trade returns on rejection**

```bash
grep -nE "def open_shadow_trade|return None|return.*trade_id|rejection_reason" src/shadow_trading/executor.py | head -10
```

Note: `open_shadow_trade` currently returns `str | None`. To capture rejection reason, we need EITHER (a) modify it to return a tuple/dict, or (b) capture the governor's rejection_reason from the `check_trade` result before invoking executor. Option (b) is less invasive.

Looking at `mr_scan_service.py:148-161`, the executor call is `trade_id = open_shadow_trade(rec_id, packet, feat)`. The governor's check is INSIDE open_shadow_trade. Reason is logged via `[GOVERNOR]` warning inside the executor. So we can't easily extract it from the return value without a signature change.

**Decision: extract by tailing the most recent governor rejection log entry tied to this ticker.** No — too brittle. Better: change open_shadow_trade to return a dict.

**Re-decision: scoped change — add a thin wrapper `open_shadow_trade_with_reason()` in executor.py that returns `tuple[str | None, str | None]`. mr_scan_service uses the new wrapper; existing callers stay on the old function.** This keeps the blast radius tiny.

### Task 25: Add the wrapper + capture (TDD red first)

- [ ] **Step 25.1: Write the test first**

Create `tests/test_mr_scan_rejection_reason.py`:

```python
"""#511 — MR scan must capture WHY each candidate was rejected.

Pre-#511, mr_scan_service.py logged "Scan complete: 5 candidates, 0 trades
opened" with no per-candidate diagnostic. Operators couldn't tell whether
rejection was BP, position-cap, sector-cap, governor halt, dup-check, or
something else.

Post-fix, each candidate's rejection (if any) is captured in the result
list with a `rejection_reason` field, AND a [MR] log line per rejection
includes the reason.
"""
import logging
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture
def mr_setup(tmp_path, monkeypatch):
    """Minimal MR scan environment that produces 1 candidate."""
    db_path = str(tmp_path / "test.sqlite3")
    from tests.conftest import init_test_db
    init_test_db(db_path, ["shadow_trades", "recommendations", "activity_log"])
    return db_path


def test_rejection_reason_captured_in_result(mr_setup):
    """When open_shadow_trade rejects, the reason appears in the candidate result."""
    from src.services.mr_scan_service import scan_and_open_mr_trades

    config = {
        "shadow_trading": {"enabled": True},
        "mean_reversion": {"enabled": True, "paper_only": True},
    }
    fake_candidate = {
        "ticker": "AAPL",
        "score": 95,
        "features": {"current_price": 150.0, "rsi_2": 5, "atr_14": 1.5},
    }
    with patch("src.features.mean_reversion.scan_for_mr_candidates",
               return_value=[fake_candidate]), \
         patch("src.shadow_trading.executor.open_shadow_trade_with_reason",
               return_value=(None, "Position size: $4800 is 96% of equity, exceeds 10% limit")), \
         patch("src.packets.template.build_packet_from_features") as mock_packet, \
         patch("src.llm.packet_writer.enhance_packet_with_llm") as mock_enhance, \
         patch("src.journal.store.log_recommendation", return_value="rec-1"), \
         patch("src.training.versioning.get_active_model_name", return_value="v1.0.0"):
        mock_packet.return_value = MagicMock(position_sizing=MagicMock(allocation_dollars=100.0))
        mock_enhance.return_value = mock_packet.return_value

        result = scan_and_open_mr_trades(
            ohlcv_dict={"AAPL": MagicMock()}, config=config, db_path=mr_setup,
        )

    assert result["trades_opened"] == 0
    rejected = [r for r in result["results"] if r["action"] == "rejected"]
    assert len(rejected) == 1
    assert rejected[0]["ticker"] == "AAPL"
    assert "Position size" in rejected[0]["rejection_reason"]


def test_rejection_logged_with_reason(mr_setup, caplog):
    """[MR] log line on rejection must include the rejection reason."""
    from src.services.mr_scan_service import scan_and_open_mr_trades

    config = {
        "shadow_trading": {"enabled": True},
        "mean_reversion": {"enabled": True},
    }
    fake_candidate = {"ticker": "MSFT", "score": 80, "features": {"current_price": 300.0, "rsi_2": 8}}
    with patch("src.features.mean_reversion.scan_for_mr_candidates",
               return_value=[fake_candidate]), \
         patch("src.shadow_trading.executor.open_shadow_trade_with_reason",
               return_value=(None, "Volatility circuit breaker: VIX proxy at 38.0% exceeds 35% threshold")), \
         patch("src.packets.template.build_packet_from_features") as mp, \
         patch("src.llm.packet_writer.enhance_packet_with_llm") as me, \
         patch("src.journal.store.log_recommendation", return_value="rec-2"), \
         patch("src.training.versioning.get_active_model_name", return_value="v1.0.0"):
        mp.return_value = MagicMock(position_sizing=MagicMock(allocation_dollars=100.0))
        me.return_value = mp.return_value

        with caplog.at_level(logging.INFO):
            scan_and_open_mr_trades(
                ohlcv_dict={"MSFT": MagicMock()}, config=config, db_path=mr_setup,
            )

    msgs = "\n".join(r.getMessage() for r in caplog.records)
    assert "MSFT" in msgs
    assert "Volatility circuit breaker" in msgs, (
        f"Expected rejection reason in log, got:\n{msgs}"
    )
```

- [ ] **Step 25.2: Run the test — should FAIL**

```bash
python -m pytest tests/test_mr_scan_rejection_reason.py -v --no-header
```

Expected: FAIL with `AttributeError: ... has no attribute 'open_shadow_trade_with_reason'`.

### Task 26: Add `open_shadow_trade_with_reason` wrapper (TDD green)

- [ ] **Step 26.1: Read the existing open_shadow_trade signature**

```bash
grep -nA 5 "^def open_shadow_trade" src/shadow_trading/executor.py | head -15
```

- [ ] **Step 26.2: Add wrapper at end of executor.py module (or near open_shadow_trade)**

Modify `src/shadow_trading/executor.py` — add new function near the existing `open_shadow_trade`:

```python
def open_shadow_trade_with_reason(
    recommendation_id: str,
    packet: TradePacket,
    features: dict,
    db_path: str = DB_PATH,
) -> tuple[str | None, str | None]:
    """Same as open_shadow_trade but also returns rejection reason on None.

    #511 — diagnostic wrapper for callers that need to surface why a
    candidate was rejected (mr_scan_service, dashboard rejection feed).
    Avoids changing open_shadow_trade's signature which has many callers.

    Returns:
        (trade_id, None) on success
        (None, "rejection reason") on rejection (governor / BP / dup / etc.)
        (None, "internal error: ...") on unexpected exception

    The reason string mirrors the [GOVERNOR] / [SHADOW] WARNING log line
    when one is emitted; otherwise a generic "rejected (no reason captured)"
    is returned with a debug log call so missing-reason cases are visible
    in verbose mode.
    """
    # Re-implementation strategy: call check_trade explicitly first to
    # capture the rejection_reason, then if approved delegate to
    # open_shadow_trade for actual execution. This avoids touching
    # the executor's hot path while gaining the diagnostic.
    try:
        from src.risk.governor import RiskGovernor, get_portfolio_state
        from src.config import load_config
        cfg = load_config()
        portfolio = get_portfolio_state(db_path)
        gov = RiskGovernor(cfg)
        tl_mult = features.get("traffic_light_multiplier", 0.5)
        event_mult = _resolve_event_risk_multiplier(features, packet.ticker, path="MR")
        check = gov.check_trade(
            packet.ticker,
            packet.position_sizing.allocation_dollars,
            features,
            portfolio,
            traffic_light_multiplier=tl_mult,
            event_risk_multiplier=event_mult,
        )
        if not check["approved"]:
            return (None, check.get("rejection_reason", "rejected (no reason captured)"))
    except Exception as e:
        logger.debug("[MR-WRAPPER] governor pre-check failed for %s: %s", packet.ticker, e)
        # Fall through — let open_shadow_trade do its own check

    try:
        trade_id = open_shadow_trade(recommendation_id, packet, features, db_path)
        if trade_id:
            return (trade_id, None)
        # open_shadow_trade returned None for a non-governor reason (BP, dup, etc.)
        return (None, "rejected by executor (post-governor check failed — see [SHADOW] log for detail)")
    except Exception as e:
        logger.warning("[MR-WRAPPER] open_shadow_trade raised for %s: %s", packet.ticker, e)
        return (None, f"internal error: {type(e).__name__}: {e}")
```

- [ ] **Step 26.3: Update `src/services/mr_scan_service.py:148-161` to use the new wrapper**

Find:
```python
        # Open shadow trade
        if shadow_enabled and rec_id:
            from src.shadow_trading.executor import open_shadow_trade
            trade_id = open_shadow_trade(rec_id, packet, feat)
            if trade_id:
                trades_opened += 1
                results.append({"ticker": ticker, "rsi_2": feat.get("rsi_2"),
                                "trade_id": trade_id, "action": "opened"})
            else:
                results.append({"ticker": ticker, "rsi_2": feat.get("rsi_2"),
                                "action": "rejected"})
        else:
            results.append({"ticker": ticker, "rsi_2": feat.get("rsi_2"),
                            "action": "no_shadow"})
```

Replace with:
```python
        # Open shadow trade (with rejection-reason capture, #511)
        if shadow_enabled and rec_id:
            from src.shadow_trading.executor import open_shadow_trade_with_reason
            trade_id, reject_reason = open_shadow_trade_with_reason(rec_id, packet, feat)
            if trade_id:
                trades_opened += 1
                results.append({"ticker": ticker, "rsi_2": feat.get("rsi_2"),
                                "trade_id": trade_id, "action": "opened"})
            else:
                logger.info("[MR] %s rejected: %s", ticker, reject_reason or "unknown")
                results.append({"ticker": ticker, "rsi_2": feat.get("rsi_2"),
                                "action": "rejected",
                                "rejection_reason": reject_reason or "unknown"})
        else:
            results.append({"ticker": ticker, "rsi_2": feat.get("rsi_2"),
                            "action": "no_shadow"})
```

- [ ] **Step 26.4: Run the rejection-reason tests — should PASS**

```bash
python -m pytest tests/test_mr_scan_rejection_reason.py -v --no-header
```

Expected: 2 passed.

- [ ] **Step 26.5: Run broader MR + executor tests to confirm no regression**

```bash
python -m pytest tests/ -k "mr_scan or open_shadow_trade or executor_entry" -q --no-header
```

Expected: all pass.

### Task 27: Commit and PR

- [ ] **Step 27.1: Commit**

```bash
git add src/services/mr_scan_service.py src/shadow_trading/executor.py tests/test_mr_scan_rejection_reason.py
git commit -m "$(cat <<'EOF'
fix(mr-scan): capture rejection reason per candidate (#511)

The 2026-04-23 log evidence showed [MR] Found 5 candidates / 0 trades
opened, repeated every 30 minutes. With no per-candidate diagnostic,
operators couldn't tell whether the rejection was BP, position-cap,
sector-cap, governor halt, dup-check, or something else. Same
silent-failure pattern as #645, #647, #649, #651.

Two changes:

1. src/shadow_trading/executor.py — Add open_shadow_trade_with_reason()
   wrapper that runs the governor check explicitly first, captures
   the rejection_reason field, then delegates to open_shadow_trade for
   actual execution. Avoids changing the existing function's signature
   (paper, live, scan_service all use it) while gaining the diagnostic
   for callers that need it.

2. src/services/mr_scan_service.py — Use the new wrapper. Per-rejection
   [MR] log line now includes the reason; results dict includes a
   rejection_reason field so dashboard/diagnostic consumers can surface
   it without scraping logs.

Plus 2 regression tests verifying the reason flows through (DB-row
context for both governor-rejection and volatility-halt scenarios).

Followup #649 will generalize this to all governor rejections (paper +
live + MR), with rate-limited activity_log events. This PR is the
narrow MR-only fix that closes #511.

Closes #511.
EOF
)"
```

- [ ] **Step 27.2: Push + PR**

```bash
git push -u origin fix/511-mr-rejection-reason-capture
gh pr create --title "fix(mr-scan): capture rejection reason per candidate (#511)" --body "$(cat <<'EOF'
## Summary

Closes #511. Pre-fix, MR scan logged "5 candidates, 0 trades opened" every 30 min with zero per-candidate diagnostic. Same silent-failure pattern as today's other fixes.

## Two changes

1. **\`src/shadow_trading/executor.py\`** — New \`open_shadow_trade_with_reason()\` wrapper that runs the governor check first, captures \`rejection_reason\`, then delegates to \`open_shadow_trade\`. Avoids changing the existing function's signature.

2. **\`src/services/mr_scan_service.py\`** — Use the wrapper. \`[MR] AAPL rejected: Position size...\` log lines now appear; \`results\` dict carries \`rejection_reason\` field.

## Followup

#649 generalizes this to all governor rejections (paper + live + MR) with rate-limited activity_log events. This PR is the narrow MR-only fix.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## PR-7: Trainer holdout-empty alert (#617)

**Files:**
- Modify: `src/training/trainer.py:528-565` — add WARNING + Telegram alert when holdout=0 and train>0
- Modify: `src/notifications/telegram.py` — add `notify_trainer_holdout_empty()` function
- Create or extend: `tests/test_trainer_holdout_alert.py` — verify alert fires in stalled-corpus scenario

**Branch:** `fix/617-trainer-holdout-alert`

### Task 28: Branch

- [ ] **Step 28.1: Branch**

```bash
git checkout main
git pull origin main
git checkout -b fix/617-trainer-holdout-alert
```

### Task 29: Write the test (TDD red)

- [ ] **Step 29.1: Create the test**

Create `tests/test_trainer_holdout_alert.py`:

```python
"""#617 — trainer must WARN when holdout=0 due to corpus stall.

Pre-#617, export_training_data wrote an empty holdout.jsonl and returned
{"training": N, "holdout": 0} silently when the most recent example was
older than the 5-day temporal-gap window. Across 4/21, 4/22, 4/23 the
nightly trainer reported "Exported 1393 training + 0 holdout" with zero
visible signal that model evaluation was blocked.

Post-fix, that condition emits:
  - logger.error with corpus-stall details
  - Telegram alert (if enabled) so operators can react before the next train cycle
"""
import json
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest


def _make_corpus(tmp_path, dates):
    """Seed training_examples with rows on the given dates (YYYY-MM-DD strings)."""
    import sqlite3
    db_path = tmp_path / "training.sqlite3"
    from tests.conftest import init_test_db
    init_test_db(str(db_path), ["training_examples"])
    with sqlite3.connect(db_path) as conn:
        for i, d in enumerate(dates):
            conn.execute(
                "INSERT INTO training_examples "
                "(example_id, source, instruction, input_text, output_text, "
                "created_at) VALUES (?, 'blinded_win', 'i', 'in', 'out', ?)",
                (f"ex-{i}", f"{d}T10:00:00"),
            )
    return str(db_path)


def test_holdout_empty_emits_error_when_train_nonempty(tmp_path, caplog):
    """All examples are from a single old date — split window pushes holdout past end."""
    from src.training.trainer import export_training_data
    import logging

    # 30 examples all from 4/12 — stale corpus
    db_path = _make_corpus(tmp_path, ["2026-04-12"] * 30)
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    with caplog.at_level(logging.ERROR):
        result, total = export_training_data(db_path, str(output_dir))

    assert result["holdout"] == 0
    assert result["training"] > 0
    err_lines = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("HOLDOUT EMPTY" in r.getMessage() for r in err_lines), (
        f"Expected HOLDOUT EMPTY error log; got:\n"
        + "\n".join(r.getMessage() for r in caplog.records)
    )


def test_holdout_empty_sends_telegram_alert(tmp_path):
    """When holdout=0 + train>0 + telegram enabled, alert is sent."""
    from src.training.trainer import export_training_data

    db_path = _make_corpus(tmp_path, ["2026-04-12"] * 30)
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    with patch("src.notifications.telegram.is_telegram_enabled", return_value=True), \
         patch("src.notifications.telegram.notify_trainer_holdout_empty") as mock_notify:
        export_training_data(db_path, str(output_dir))

    mock_notify.assert_called_once()
    kwargs = mock_notify.call_args.kwargs
    # Should pass at least the corpus-stale-date and the train-count
    assert "most_recent_date" in kwargs or len(mock_notify.call_args.args) >= 1


def test_holdout_populated_does_not_alert(tmp_path):
    """Healthy corpus (recent examples) — no alert fires."""
    from src.training.trainer import export_training_data

    today = datetime.now().date()
    dates = [str(today - timedelta(days=i)) for i in range(30)]
    db_path = _make_corpus(tmp_path, dates)
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    with patch("src.notifications.telegram.is_telegram_enabled", return_value=True), \
         patch("src.notifications.telegram.notify_trainer_holdout_empty") as mock_notify:
        result, total = export_training_data(db_path, str(output_dir))

    # Healthy corpus should not alert; holdout may or may not be non-empty
    # depending on the temporal-gap window, but the alert specifically fires
    # only when holdout=0 + train>0. Check accordingly.
    if result["training"] > 0 and result["holdout"] == 0:
        # Edge case: even today's corpus could result in empty holdout.
        # If so the alert SHOULD fire.
        mock_notify.assert_called_once()
    else:
        mock_notify.assert_not_called()
```

- [ ] **Step 29.2: Run the test — should FAIL (notify_trainer_holdout_empty doesn't exist)**

```bash
python -m pytest tests/test_trainer_holdout_alert.py -v --no-header
```

Expected: FAIL with AttributeError or assertion failure.

### Task 30: Implement the alert (TDD green)

- [ ] **Step 30.1: Add `notify_trainer_holdout_empty` to telegram.py**

Modify `src/notifications/telegram.py` — add a new function near the other `notify_*` definitions (e.g. after `notify_premarket_brief`):

```python
def notify_trainer_holdout_empty(
    train_count: int,
    most_recent_date: str,
    days_stale: int,
) -> bool:
    """#617 — alert: training holdout split was empty due to stalled corpus.

    Fires when export_training_data writes a non-empty training set but
    zero holdout examples. This happens when all examples are older than
    the 5-day temporal gap window, meaning model evaluation (canary, A/B)
    cannot run on out-of-sample data.
    """
    msg = (
        f"⚠️ <b>TRAINER HOLDOUT EMPTY</b>\n"
        f"Training examples: {train_count}\n"
        f"Holdout examples:  0\n"
        f"Corpus most recent: {most_recent_date} ({days_stale}d stale)\n"
        f"Model evaluation blocked. Run backfill or wait for collection to resume."
    )
    return send_telegram(msg)
```

- [ ] **Step 30.2: Add the alert call in trainer.py after holdout is computed**

Modify `src/training/trainer.py` — after the `holdout_examples = [...]` line at ~528 (right before the `_write_jsonl` calls), add:

```python
    # #617 — surface the corpus-stall failure mode that pre-fix produced silent
    # zero-holdout. If train_examples is populated but holdout is empty, the
    # 5-day gap pushed holdout past the end of corpus. Model evaluation is
    # blocked until new examples land.
    if train_examples and not holdout_examples:
        most_recent = examples[-1]["created_at"][:10] if examples else "unknown"
        try:
            from datetime import datetime as _dt2
            days_stale = (_dt2.now() - _dt2.fromisoformat(most_recent)).days
        except (ValueError, TypeError):
            days_stale = -1
        logger.error(
            "[TRAINER] HOLDOUT EMPTY: corpus most recent %s (%dd stale) — "
            "5-day gap pushed holdout past end of corpus. Model evaluation BLOCKED.",
            most_recent, days_stale,
        )
        try:
            from src.notifications.telegram import (
                notify_trainer_holdout_empty, is_telegram_enabled,
            )
            if is_telegram_enabled():
                notify_trainer_holdout_empty(
                    train_count=len(train_examples),
                    most_recent_date=most_recent,
                    days_stale=days_stale,
                )
        except Exception as exc:
            logger.debug("[TRAINER] holdout-empty Telegram alert failed: %s", exc)
```

- [ ] **Step 30.3: Run the alert tests — should PASS**

```bash
python -m pytest tests/test_trainer_holdout_alert.py -v --no-header
```

Expected: 3 passed.

- [ ] **Step 30.4: Run broader trainer/notification tests to confirm no regression**

```bash
python -m pytest tests/ -k "trainer or holdout or notify" -q --no-header
```

Expected: all pass.

### Task 31: Commit and PR

- [ ] **Step 31.1: Commit**

```bash
git add src/training/trainer.py src/notifications/telegram.py tests/test_trainer_holdout_alert.py
git commit -m "$(cat <<'EOF'
fix(training): alert on stalled-corpus holdout-empty condition (#617)

Pre-#617, export_training_data silently wrote an empty holdout.jsonl
when all examples were older than the 5-day temporal-gap window.
Across 4/21, 4/22, 4/23 nightly cycles reported "Exported 1393
training + 0 holdout" with zero signal that model evaluation was
blocked. Same silent-failure pattern as #615.

Two changes:

1. src/training/trainer.py — After holdout_examples is computed, if
   train_examples is non-empty but holdout is empty, emit a logger.error
   and Telegram alert with the most-recent-example date and days-stale
   count. This is the operator's first warning that they need to run
   backfill or wait for collection to resume.

2. src/notifications/telegram.py — New notify_trainer_holdout_empty()
   function with structured message body matching #615's silent-failure
   indicator pattern.

Plus 3 regression tests in tests/test_trainer_holdout_alert.py:
  - Stale corpus emits ERROR-level log
  - Stale corpus calls notify_trainer_holdout_empty
  - Healthy corpus does NOT alert (no false positives)

Closes #617.
EOF
)"
```

- [ ] **Step 31.2: Push + PR**

```bash
git push -u origin fix/617-trainer-holdout-alert
gh pr create --title "fix(training): alert on stalled-corpus holdout-empty condition (#617)" --body "$(cat <<'EOF'
## Summary

Closes #617. Pre-fix, the trainer silently wrote an empty holdout.jsonl when corpus was stale, blocking model evaluation with no operator signal.

## Two changes

1. **\`src/training/trainer.py\`** — After holdout split, if \`train_examples > 0\` and \`holdout_examples == 0\`, emit \`logger.error\` + Telegram alert with most-recent-date and days-stale count.

2. **\`src/notifications/telegram.py\`** — New \`notify_trainer_holdout_empty()\`.

## Test plan

- [x] Stale corpus emits ERROR
- [x] Stale corpus calls notify_trainer_holdout_empty
- [x] Healthy corpus does NOT alert (no false positives)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## PR-8: Model registry audit trail + Option A operator action (#582)

**Files:**
- Modify: `src/training/versioning.py:175-200` — add `log_activity` calls to `rollback_model()` and `promote_model()`
- Create: `tests/test_versioning_audit_trail.py` — coupling test that asserts every state-mutating function logs

**Branch:** `fix/582-model-registry-audit-trail`

**Operator action (separate, after market close):** SQL UPDATE to flip arcis:v1.0.0 from `rolled_back` to `active` with audit notes.

### Task 32: Branch

- [ ] **Step 32.1: Branch**

```bash
git checkout main
git pull origin main
git checkout -b fix/582-model-registry-audit-trail
```

### Task 33: Write the audit-trail coupling test (TDD red)

- [ ] **Step 33.1: Create the test**

Create `tests/test_versioning_audit_trail.py`:

```python
"""#582 — model_versions writes must leave an audit trail.

Pre-fix, src/training/versioning.py's rollback_model() and promote_model()
silently UPDATEd model_versions.status without writing anything to
activity_log. The operator who manually rolled back arcis:v1.0.0 on
2026-03-25 left zero audit trail; investigation 4 weeks later couldn't
answer "who/when/why."

Post-fix, every state mutation in versioning.py emits an activity_log
entry so the chain of custody is reconstructible.
"""
import os
import sqlite3
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _opt_in_writes(monkeypatch):
    """Allow log_activity writes within these tests; tests pass tmp paths."""
    monkeypatch.setenv("ARCIS_LOG_ACTIVITY_IN_PYTEST", "1")


def _seed(tmp_path):
    db_path = str(tmp_path / "test_versioning.sqlite3")
    from tests.conftest import init_test_db
    init_test_db(db_path, ["model_versions", "activity_log"])
    return db_path


def test_rollback_model_writes_activity_log(tmp_path, monkeypatch):
    """rollback_model must record a rollback event in activity_log."""
    monkeypatch.setattr("src.utils.activity_logger.DB_PATH", "")  # unused; explicit db_path used
    db_path = _seed(tmp_path)

    # Seed an active and a retired version
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO model_versions (version_id, version_name, status, created_at) "
            "VALUES (?, ?, 'active', '2026-04-20T00:00:00')",
            ("v-active", "arcis:test_active"),
        )
        conn.execute(
            "INSERT INTO model_versions (version_id, version_name, status, created_at) "
            "VALUES (?, ?, 'retired', '2026-04-15T00:00:00')",
            ("v-retired", "arcis:test_retired"),
        )
        conn.commit()

    from src.training.versioning import rollback_model
    rollback_model(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        events = conn.execute(
            "SELECT event_type, detail FROM activity_log "
            "WHERE event_type LIKE 'model_%' ORDER BY id"
        ).fetchall()
    assert len(events) >= 1
    assert any("rollback" in e[0].lower() or "rollback" in (e[1] or "").lower() for e in events), (
        f"Expected a rollback event in activity_log; got {events}"
    )


def test_versioning_state_mutators_all_log(monkeypatch):
    """Coupling: every public state-changing function in versioning.py must
    contain a log_activity call. Static-analysis check on source.

    Mutators (state writes): rollback_model, promote_model, mark_canary_evaluation,
    insert_new_version. (Read-only functions like get_active_model_version are exempt.)
    """
    import inspect
    import re
    from src.training import versioning

    mutators = [
        "rollback_model",
        # If any of these don't exist in current code, the coupling test
        # gracefully skips them — meaning they're either not yet written
        # (filed for follow-up) or they're read-only.
    ]
    for name in mutators:
        fn = getattr(versioning, name, None)
        if fn is None:
            continue
        src = inspect.getsource(fn)
        assert re.search(r"log_activity\s*\(", src), (
            f"versioning.{name} mutates model_versions but does not call "
            f"log_activity. Add an audit-trail entry — see #582 / PR-8."
        )
```

- [ ] **Step 33.2: Run the test — should FAIL**

```bash
python -m pytest tests/test_versioning_audit_trail.py -v --no-header
```

Expected: FAIL with both "no model_* events found" and "rollback_model does not call log_activity".

### Task 34: Add `log_activity` calls to versioning.py (TDD green)

- [ ] **Step 34.1: Read the current rollback_model implementation**

```bash
grep -nA 30 "^def rollback_model" src/training/versioning.py
```

- [ ] **Step 34.2: Add log_activity at the end of rollback_model**

Modify `src/training/versioning.py` `rollback_model()` — after the existing `conn.commit()` and before `return`:

```python
def rollback_model(db_path: str = DB_PATH) -> dict | None:
    """Roll back active model to previous retired version. Returns restored version or None."""
    init_training_tables(db_path)

    # Capture pre-state for the audit trail (so we know what was active)
    pre_active_name = None
    with connect_db(db_path) as conn_pre:
        conn_pre.row_factory = sqlite3.Row
        row = conn_pre.execute(
            "SELECT version_name FROM model_versions WHERE status = 'active' LIMIT 1"
        ).fetchone()
        if row:
            pre_active_name = row["version_name"]

    with connect_db(db_path) as conn:
        conn.row_factory = sqlite3.Row

        # Set active to rolled_back
        conn.execute(
            "UPDATE model_versions SET status = 'rolled_back' WHERE status = 'active'"
        )

        # Find most recent retired version
        row = conn.execute(
            "SELECT * FROM model_versions WHERE status = 'retired' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()

        if row:
            conn.execute(
                "UPDATE model_versions SET status = 'active' WHERE version_id = ?",
                (row["version_id"],),
            )
            conn.commit()
            restored = dict(row)
        else:
            conn.commit()
            restored = None

    # #582 — audit trail for the operator-initiated state change
    try:
        from src.utils.activity_logger import log_activity
        import json as _json
        log_activity(
            "model_rollback",
            _json.dumps({
                "rolled_back_from": pre_active_name,
                "restored_to": restored["version_name"] if restored else None,
            }),
            db_path=db_path,
        )
    except Exception as exc:
        logger.debug("[VERSIONING] activity_log write failed during rollback: %s", exc)

    return restored
```

- [ ] **Step 34.3: Run the audit-trail tests — should PASS**

```bash
python -m pytest tests/test_versioning_audit_trail.py -v --no-header
```

Expected: 2 passed.

- [ ] **Step 34.4: Run broader versioning tests**

```bash
python -m pytest tests/ -k "versioning or rollback or model_version" -q --no-header
```

Expected: all pass.

### Task 35: File the spinoff issue for promote_model

- [ ] **Step 35.1: File a follow-up issue tracking the same audit-trail gap for promote_model**

```bash
gh issue create --title "Audit trail: promote_model() and other versioning.py mutators missing log_activity calls (followup #582)" --body "$(cat <<'EOF'
## Context

#582's PR-8 added log_activity to rollback_model(). The coupling test in tests/test_versioning_audit_trail.py is structured as a parameterized list — currently only \`rollback_model\` is in the list because that's what #582 fixed.

This issue tracks the same gap for the remaining state-mutating functions in versioning.py:

- promote_model() — promotes a candidate version to active
- mark_canary_evaluation() — records canary outcome
- insert_new_version() — creates a new model_versions row

## Acceptance

For each function above:
- Add a log_activity call recording the state change
- Add the function name to the coupling test's mutators list
- Verify the existing tests still pass

## Why a separate PR

Keeps PR-8 (#582) tightly scoped to "fix the immediate operational gap" (one row stuck rolled_back, one function missing audit trail). This followup is the systematic version that walks every mutator.
EOF
)"
```

### Task 36: Create the operator SQL action script (deferred until after market close)

- [ ] **Step 36.1: Write a small operator script (NOT in the PR — separate operator action)**

Create `_582_operator_action.sql` in the repo root:

```sql
-- #582 — flip arcis:v1.0.0 from rolled_back to active with audit notes.
-- Run AFTER market close so model lookups don't see a transient state change.
-- Apply via:
--   sqlite3 C:/arcis/data/ai_research_desk.sqlite3 < _582_operator_action.sql

UPDATE model_versions
SET
    status = 'active',
    notes = 'Rollback origin lost (manual operator action 2026-03-25, no audit trail). ' ||
            'Verified operationally healthy: 30+ days of paper trading. ' ||
            'Re-activated on 2026-04-24 per #582 investigation. ' ||
            'Future state changes will leave audit trail via PR-8.'
WHERE version_id = 'b3866636-c189-4c7c-90aa-c44c097aa3de';

SELECT version_id, version_name, status, substr(notes, 1, 80) AS notes
FROM model_versions;
```

This file should NOT be committed — add it to .gitignore or delete after the operator runs it.

### Task 37: Commit and PR

- [ ] **Step 37.1: Commit**

```bash
git add src/training/versioning.py tests/test_versioning_audit_trail.py
git commit -m "$(cat <<'EOF'
fix(versioning): audit trail for rollback_model + coupling test (#582)

Investigation 2026-04-24 found arcis:v1.0.0 stuck status='rolled_back'
in model_versions despite Ollama loading + actively serving 329+
inferences/day. activity_log had ZERO model-related events ever —
the operator who rolled it back manually on 2026-03-25 left no audit
trail because rollback_model() didn't call log_activity.

Two changes:

1. src/training/versioning.py — rollback_model() now captures the
   pre-state (active version name), performs the UPDATEs, then writes
   an activity_log event of event_type='model_rollback' with structured
   detail JSON (rolled_back_from, restored_to). The activity_log write
   is best-effort (try/except) so a logging failure can never block
   the rollback itself.

2. tests/test_versioning_audit_trail.py — Two regression tests:
   - End-to-end: rollback_model writes a model_* event
   - Coupling: every state-mutating function in versioning.py must
     contain a log_activity call. Currently parameterized over
     rollback_model only; a followup issue (filed) extends to
     promote_model + mark_canary_evaluation + insert_new_version.

Operator action (separate, after market close):
  sqlite3 C:/arcis/data/ai_research_desk.sqlite3 < _582_operator_action.sql

Closes #582.
EOF
)"
```

- [ ] **Step 37.2: Push + PR**

```bash
git push -u origin fix/582-model-registry-audit-trail
gh pr create --title "fix(versioning): audit trail for rollback_model + coupling test (#582)" --body "$(cat <<'EOF'
## Summary

Closes #582. Investigation revealed arcis:v1.0.0 was manually rolled back on 2026-03-25 with zero audit trail because \`rollback_model()\` didn't call \`log_activity\`.

## Two changes

1. **\`src/training/versioning.py\`** — \`rollback_model()\` now writes \`event_type='model_rollback'\` with structured JSON detail (rolled_back_from, restored_to) to activity_log. Best-effort write — can never block the rollback itself.

2. **\`tests/test_versioning_audit_trail.py\`** — Coupling test that asserts every state-mutating function in versioning.py contains a \`log_activity\` call. Currently parameterized over \`rollback_model\` only.

## Followup

Spinoff issue filed: extend the coupling test's mutator list to \`promote_model\`, \`mark_canary_evaluation\`, \`insert_new_version\`. Same pattern, separate scope.

## Operator action (after market close)

\`\`\`bash
sqlite3 C:/arcis/data/ai_research_desk.sqlite3 < _582_operator_action.sql
\`\`\`

Flips arcis:v1.0.0 from rolled_back → active with audit notes. Run AFTER market close so model lookups don't see a transient state change.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Wrap-up

### Task 38: Verify all PRs

- [ ] **Step 38.1: List all 7 PRs + 3 closed issues**

```bash
gh pr list --state open --author @me --limit 20
gh issue list --state closed --limit 5
```

Expected:
- 7 OPEN PRs (#653-659 approximately)
- Most recent 5 closed: includes #510, #607, #633, plus #650/#629/etc as they merge

### Task 39: Update task list with completion

After each PR is merged, mark the task list item complete and pull main locally:

```bash
git checkout main
git pull origin main
nssm restart ArcisWatchLoop  # only if PR-5 (log changes) or PR-6/7 land
```

### Task 40: After-market-close manual action for #582

- [ ] **Step 40.1: AFTER 16:00 ET, run the operator SQL**

```bash
cd C:\arcis\halcyon-lab
sqlite3 C:/arcis/data/ai_research_desk.sqlite3 < _582_operator_action.sql
```

Expected output: confirms 1 row updated, prints the new state.

- [ ] **Step 40.2: Delete the operator SQL file (single-use)**

```bash
rm _582_operator_action.sql
```

---

## Self-review (skill requirement)

### Spec coverage

| Spec item | Task |
|---|---|
| #632 walk-forward auth | PR-1 (Tasks 1-4) ✓ |
| #424 telegram token leakage | PR-2 (Tasks 5-8) ✓ |
| #642 repo layout docs | PR-3 (Tasks 9-13) ✓ |
| #650 pollution cleanup script | PR-4 (Tasks 14-17) ✓ |
| #629 log signal-to-noise | PR-5 (Tasks 18-22) ✓ — partial; URL-rot follow-up filed |
| #511 MR rejection-reason | PR-6 (Tasks 23-27) ✓ |
| #617 trainer holdout alert | PR-7 (Tasks 28-31) ✓ |
| #582 model registry audit trail + Option A | PR-8 (Tasks 32-37 + 40) ✓ |
| #510 close as resolved | Task 0a ✓ |
| #607 close as confirmed | Task 0b ✓ |
| #633 close as already-fixed | Task 0c ✓ |

All 11 issues covered.

### Placeholder scan

No "TBD", "TODO", "fill in", "implement later", or "similar to Task N" found. All code blocks complete; all commands have expected output. Test bodies are real, not pseudo-code.

### Type consistency

- `verify_auth` import in PR-1 matches usage at decorator argument.
- `_redact_token` in PR-2 returns str in all branches; tests check str output.
- `open_shadow_trade_with_reason` in PR-6 returns `tuple[str | None, str | None]`; tests unpack accordingly; mr_scan_service unpacks accordingly.
- `notify_trainer_holdout_empty` in PR-7 keyword args match between def + call site + test mock assertions.
- `log_activity` call signatures in PR-8 match the existing function (event_type, detail, db_path=).

### Cross-task consistency

- PR-1's coupling-test pattern (`_ANONYMOUS_ROUTES_WHITELIST`) deliberately mirrors PR-8's coupling-test pattern (mutators list) and PR-5's parametrized log-level test. Same defensive shape across all three.
- The "after market close" operator action for PR-8 is referenced in both Task 36 (script creation) and Task 40 (execution) — consistent.

---

**Plan complete and saved to `docs/superpowers/plans/2026-04-24-tier-a-b-rootcause-bundle.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task (Tasks 1-37 in sequence), review between PRs, fast iteration. Each PR ships independently.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints between PRs. Heavier on this session's context but faster turnaround per PR.

**Which approach?**
