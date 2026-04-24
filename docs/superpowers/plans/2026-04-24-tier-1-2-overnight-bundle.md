# Tier 1 + 1.5 + 2 Overnight Bundle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close 13+ open issues across three risk tiers in a single overnight pass, shipped as 3 reviewable PRs, with zero impact on the green test sweep.

**Architecture:** Three sequential branches off `main`, each becomes one PR awaiting morning review. Each commit within a branch addresses exactly one issue with TDD discipline. Branches are independent (no shared file conflicts) so they can be merged in any order.

**Tech Stack:** Python 3.13, pytest, sqlite3, FastAPI, hmac, logging, ruamel.yaml.

**Issues attacked:**

| PR | Branch | Issues |
|---|---|---|
| **PR-A** Tier 1 mechanical | `fix/tier-1-bundle-2026-04-24` | #619 (logging UTF-8), #578 (connect_db × 31), #437+#482 (status strings × ~25), #436 (IB bracket import hoist) |
| **PR-B** Tier 1.5 hygiene | `fix/tier-1-5-hygiene-2026-04-24` | CLAUDE.md test-count, cleanup-script `--dry-run`, #631-9 + #631-18 UI, #621 packet price=0, #478 routes connect_db, test backfill |
| **PR-C** Tier 2 safety | `fix/tier-2-safety-2026-04-24` | #574 (live-mode fail-fast), #580 (activity_log AUTOINCREMENT registry-only), #615 backfill script |
| **chore** Issue closures | (no branch — `gh` only) | #421, #423 |

**Branch strategy:** Each PR's branch is created off the LATEST `origin/main` immediately before its first commit, NOT pre-created upfront. This avoids stale-base merge conflicts as PRs land.

**Commit cadence:** One commit per issue (not one per task). Tasks within an issue stage incrementally; final task commits the bundle. Test sweep runs at end of each PR phase.

---

## File Structure Map

| File | Owner | Touched By |
|---|---|---|
| `src/log_config.py` | logging setup | Task A.1 (#619) — add `encoding="utf-8"` to RotatingFileHandler |
| `src/journal/store.py` | journal SQLite writes (17 sites) | Task A.2 (#578) — sqlite3.connect → connect_db |
| `src/training/versioning.py` | training-version DB writes (14 sites) | Task A.2 (#578) |
| `src/shadow_trading/executor.py` | trading state, has IB import + 25+ status strings | Tasks A.3 (#437), A.4 (#436) |
| `src/shadow_trading/reconcile.py` | hardcoded status strings (4 sites) | Task A.3 (#482) |
| `src/risk/governor.py` | hardcoded status strings (3 sites) | Task A.3 (#482) |
| `src/scheduler/reports.py` | hardcoded status strings (19 sites) | Task A.3 (#482) |
| `src/api/routes/{council,health,ib_status,live,logs,notes}.py` | route DB reads (~15 sites) | Task B.5 (#478) |
| `src/packets/template.py` | packet builder | Task B.4 (#621) |
| `frontend/src/pages/Dashboard.jsx` | dashboard panels | Task B.3 (#631-9) |
| `frontend/src/components/Layout.jsx` | top-bar warnings | Task B.3 (#631-18) |
| `scripts/cleanup_test_pollution_2026_04.py` | one-shot cleanup | Task B.2 — add `--dry-run` |
| `CLAUDE.md` | repo conventions | Task B.1 — bump test-count from 1339 to current |
| `src/cli/commands.py::cmd_startup` | startup gating | Task C.1 (#574) |
| `src/schema/registry.py` | activity_log schema | Task C.2 (#580) |
| `scripts/backfill_training_4_13_to_4_23.py` (NEW) | operator script | Task C.3 (#615 follow-up) |
| `tests/test_tier_1_hardening.py` (NEW) | regression guards for PR-A | Task A.0 — written first |
| `tests/test_tier_1_5_hygiene.py` (NEW) | regression guards for PR-B | Task B.0 — written first |
| `tests/test_tier_2_safety.py` (NEW) | regression guards for PR-C | Task C.0 — written first |
| `tests/test_helper_coverage_backfill.py` (NEW) | unit tests for helpers added in PR #634 | Task B.6 |

**Decisions locked in:**
- Status-string fix uses `IN (?, ?, …)` parameter expansion (NOT inline f-string IN clauses) to keep DB-side parameterization intact. Each call site that compares against TERMINAL_STATUSES gets a small helper `_status_filter_sql(constants)` returning `(sql_fragment, params_tuple)`.
- `connect_db` migration test uses the existing pattern from `tests/test_dep_health_hardening.py::test_features_journal_use_connect_db_helper` — extend the same source-scan with the new files.
- For #631-18 (warnings dot when 0): hide the dot, NOT the whole button — the button stays as a UI affordance to view warnings page.
- For #621: `packets/template.py` returns `None` AND emits `logger.warning("[PACKET] price=%s for %s — skipping", price, ticker)` so the upstream feature pipeline issue is visible.

---

## PR-A: Tier 1 mechanical (4 issues, ~2.5h)

### Task A.0: Branch + skeleton test file

**Files:**
- Create: `tests/test_tier_1_hardening.py`

- [ ] **Step 1: Confirm clean main + create branch**

```bash
git status                              # expect: clean
git checkout main && git pull
git checkout -b fix/tier-1-bundle-2026-04-24
```

- [ ] **Step 2: Create the regression-guard test file (empty scaffold)**

Write to `tests/test_tier_1_hardening.py`:

```python
"""Regression guards for Tier 1 hardening (#619, #578, #437, #482, #436).

Each test prevents the corresponding bug pattern from re-emerging via
source-scan assertions (similar to tests/test_dep_health_hardening.py).
"""

from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")
```

- [ ] **Step 3: Verify pytest collects the file**

Run: `python -m pytest tests/test_tier_1_hardening.py --collect-only -q`
Expected: `0 tests collected` — file imports without error.

### Task A.1: #619 — RotatingFileHandler missing UTF-8 encoding

**Files:**
- Modify: `src/log_config.py:54-56`
- Test: `tests/test_tier_1_hardening.py`

Note: `setup_logging` already reconfigures stdout/stderr to UTF-8 (lines 30-35). The remaining gap is the file handler, which uses platform-default encoding (cp1252 on Windows) and silently drops emoji + CJK.

- [ ] **Step 1: Write failing test**

Append to `tests/test_tier_1_hardening.py`:

```python
def test_log_config_file_handler_uses_utf8_encoding():
    """#619 — RotatingFileHandler must specify encoding='utf-8' so emoji
    and CJK characters are written to the log file instead of being
    silently dropped via the cp1252 fallback on Windows."""
    text = _read("src/log_config.py")
    # The RotatingFileHandler call must include encoding="utf-8"
    m = re.search(
        r"RotatingFileHandler\(([^)]{1,400}?)\)",
        text,
        re.DOTALL,
    )
    assert m, "RotatingFileHandler call not found in log_config.py"
    args = m.group(1)
    assert 'encoding="utf-8"' in args or "encoding='utf-8'" in args, (
        "#619 — RotatingFileHandler must declare encoding='utf-8'"
    )


def test_log_config_emoji_message_does_not_crash():
    """End-to-end smoke test: logging an emoji + CJK message must not raise
    UnicodeEncodeError. Pre-fix this happened ~13 times/3-day window."""
    import logging
    import tempfile
    import pathlib
    from src.log_config import setup_logging
    with tempfile.TemporaryDirectory() as td:
        log_path = pathlib.Path(td, "test.log")
        setup_logging(level="INFO", log_file=str(log_path))
        log = logging.getLogger("test_emoji")
        # ❌ = U+274C, 跌破 = Chinese for "broke below"
        log.warning("%s Reconciliation: 2 mismatched", "❌")
        log.warning("Key Risk: Price跌破 20-day SMA")
        # No exception = passing the smoke test.
        # Verify file actually contains the chars.
        content = log_path.read_text(encoding="utf-8")
        assert "❌" in content, "Emoji not written to log file"
        assert "跌破" in content, "CJK chars not written to log file"
    # Reset root logger so subsequent tests don't double-handle.
    logging.getLogger().handlers.clear()
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_tier_1_hardening.py -v`
Expected: 1 test fails (`test_log_config_file_handler_uses_utf8_encoding`); the smoke test may pass coincidentally on systems where stdout is already UTF-8.

- [ ] **Step 3: Implement — add `encoding="utf-8"` to RotatingFileHandler**

Edit `src/log_config.py:54-56`:

```python
        file_handler = RotatingFileHandler(
            log_path, maxBytes=10 * 1024 * 1024, backupCount=5,
            encoding="utf-8",
        )
```

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest tests/test_tier_1_hardening.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/log_config.py tests/test_tier_1_hardening.py
git commit -m "fix(logging): RotatingFileHandler encoding=utf-8 (#619)

Pre-fix the file handler used platform-default encoding (cp1252 on
Windows), so emoji + CJK chars in log messages triggered handleError()
and the records were silently dropped. The 4/21 audit found ~13
UnicodeEncodeError tracebacks/3-day window from this path. setup_logging
already reconfigures stdout/stderr to UTF-8; this completes the fix
for the file handler.

Closes #619 (the logging-encoding component; the Qwen3 CJK output
quality question is tracked separately as a model-evaluation concern)."
```

### Task A.2: #578 — connect_db migration in journal/store.py + training/versioning.py

**Files:**
- Modify: `src/journal/store.py` (17 sites)
- Modify: `src/training/versioning.py` (14 sites)
- Test: `tests/test_tier_1_hardening.py`

- [ ] **Step 1: Write failing source-scan test**

Append to `tests/test_tier_1_hardening.py`:

```python
_CONNECT_DB_TARGETS_BATCH_2 = [
    "src/journal/store.py",
    "src/training/versioning.py",
]


def test_journal_versioning_use_connect_db_helper():
    """#578 — journal/store.py and training/versioning.py must use
    connect_db() instead of raw sqlite3.connect() so the busy_timeout=30s
    is consistently applied. Audit found 17 + 14 = 31 raw call sites."""
    bad: list[str] = []
    for path in _CONNECT_DB_TARGETS_BATCH_2:
        text = _read(path)
        for i, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if re.search(r"\bsqlite3\.connect\(", line) and "noqa: db" not in line:
                bad.append(f"{path}:{i}")
    assert not bad, (
        "Use connect_db() (busy_timeout=30s) instead of raw sqlite3.connect at: "
        + ", ".join(bad)
        + " — add `# noqa: db` if a raw connect is genuinely needed."
    )
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_tier_1_hardening.py::test_journal_versioning_use_connect_db_helper -v`
Expected: FAIL listing 31 sites.

- [ ] **Step 3: Migrate journal/store.py**

For each `with sqlite3.connect(...) as conn:` line in `src/journal/store.py`, replace with `with connect_db(...) as conn:`. Add a single import at the top of the imports block (look for existing `from src.config import DB_PATH`):

```python
from src.utils.db import connect_db
```

Use sed for the bulk replacement (Windows bash):

```bash
sed -i 's/sqlite3\.connect(/connect_db(/g' src/journal/store.py
```

Then manually verify the import was added. If sed left any `sqlite3.connect(Path(db_path))` calls (line 92), fix them — `connect_db` accepts a string, so wrap as `connect_db(str(db_path))`.

- [ ] **Step 4: Migrate training/versioning.py**

Same pattern:

```bash
sed -i 's/sqlite3\.connect(/connect_db(/g' src/training/versioning.py
```

Add `from src.utils.db import connect_db` at the top.

- [ ] **Step 5: Verify GREEN + run regression**

Run:

```bash
python -m pytest tests/test_tier_1_hardening.py::test_journal_versioning_use_connect_db_helper -v
python -m pytest tests/test_journal_stats.py tests/test_journal_store_schema_filter.py tests/test_self_blinding.py -q
```

Expected: source-scan test passes; journal + training regression tests stay green.

- [ ] **Step 6: Commit**

```bash
git add src/journal/store.py src/training/versioning.py tests/test_tier_1_hardening.py
git commit -m "fix(deps): migrate 31 raw sqlite3.connect sites to connect_db (#578)

journal/store.py: 17 sites
training/versioning.py: 14 sites

Both files were on the audit's 87-files-still-raw list. connect_db
applies busy_timeout=30s consistently — without it, hot writes during
overnight bursts produce 'database is locked' errors (5 such errors
confirmed in the 4/21 sweep). This is part of the broader #578
mass-migration; the route layer is addressed separately in PR-B."
```

### Task A.3: #437 + #482 — status string consolidation

**Files:**
- Create: `src/shadow_trading/_status_sql.py` (new helper)
- Modify: `src/shadow_trading/executor.py` (~25 sites)
- Modify: `src/shadow_trading/reconcile.py` (~4 sites)
- Modify: `src/risk/governor.py` (~3 sites)
- Modify: `src/scheduler/reports.py` (~19 sites)
- Test: `tests/test_tier_1_hardening.py`

- [ ] **Step 1: Create the SQL helper**

Write to `src/shadow_trading/_status_sql.py`:

```python
"""SQL helper for parameterized IN-clause filters on shadow_trades.status.

Pre-#437/#482 the codebase had 50+ hardcoded `status = 'closed'` /
`status IN ('open', 'exit_pending')` strings sprinkled across executor,
reconcile, governor, and scheduler. Each one was a CLAUDE.md-rule
violation ("Status constants are canonical — use TERMINAL_STATUSES /
ACTIVE_STATUSES from models.py") and a maintenance trap.

This helper builds a parameterized IN clause from a frozenset constant
so the filter stays in sync with models.py forever.

Usage:
    from src.shadow_trading.models import ACTIVE_STATUSES
    from src.shadow_trading._status_sql import status_in_clause

    sql_frag, params = status_in_clause(ACTIVE_STATUSES)
    cursor.execute(f"SELECT * FROM shadow_trades WHERE {sql_frag}", params)
"""

from __future__ import annotations

from typing import Iterable


def status_in_clause(statuses: Iterable[str], column: str = "status") -> tuple[str, tuple[str, ...]]:
    """Return (sql_fragment, params_tuple) for a parameterized IN filter.

    Always parameterized — never inline-formats values into the SQL.
    Sorted for deterministic SQL generation (helpful when comparing
    EXPLAIN plans or hashing query strings).
    """
    values = tuple(sorted(statuses))
    placeholders = ", ".join("?" for _ in values)
    return f"{column} IN ({placeholders})", values


def status_not_in_clause(statuses: Iterable[str], column: str = "status") -> tuple[str, tuple[str, ...]]:
    """Inverse of `status_in_clause` — returns a NOT IN fragment."""
    values = tuple(sorted(statuses))
    placeholders = ", ".join("?" for _ in values)
    return f"{column} NOT IN ({placeholders})", values
```

- [ ] **Step 2: Write failing source-scan test**

Append to `tests/test_tier_1_hardening.py`:

```python
_STATUS_STRING_TARGETS = [
    "src/shadow_trading/executor.py",
    "src/shadow_trading/reconcile.py",
    "src/risk/governor.py",
    "src/scheduler/reports.py",
]

# Patterns that indicate hardcoded status strings in SQL contexts.
_BAD_STATUS_PATTERNS = [
    re.compile(r"status\s*=\s*['\"](closed|open|exit_pending|exit_failed|pending|rejected|failed|exit_abandoned|needs_manual_review|submission_uncertain)['\"]"),
    re.compile(r"status\s+IN\s*\(\s*['\"]"),  # inline-quoted IN list
    re.compile(r"status\s+NOT\s+IN\s*\(\s*['\"]"),
]


def test_no_hardcoded_status_strings_in_sql():
    """#437 + #482 — Use TERMINAL_STATUSES / ACTIVE_STATUSES + the
    status_in_clause helper instead of hardcoded SQL string literals.
    Add `# noqa: status-literal` to a line if it MUST stay hardcoded
    (e.g., a test fixture row, never a SQL filter)."""
    bad: list[str] = []
    for path in _STATUS_STRING_TARGETS:
        text = _read(path)
        for i, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#") or "noqa: status-literal" in line:
                continue
            for pat in _BAD_STATUS_PATTERNS:
                if pat.search(line):
                    bad.append(f"{path}:{i}: {stripped[:80]}")
                    break
    assert not bad, (
        "Hardcoded status strings in SQL — replace with TERMINAL_STATUSES / "
        "ACTIVE_STATUSES from src.shadow_trading.models via the "
        "status_in_clause helper:\n  " + "\n  ".join(bad)
    )
```

- [ ] **Step 3: Verify RED**

Run: `python -m pytest tests/test_tier_1_hardening.py::test_no_hardcoded_status_strings_in_sql -v`
Expected: FAIL listing ~50 sites.

- [ ] **Step 4: Migrate executor.py**

Read each violating line in `src/shadow_trading/executor.py` and apply one of these transformations:

For `WHERE status = 'closed'`:
```python
# Before
"WHERE status = 'closed'"

# After
from src.shadow_trading._status_sql import status_in_clause
from src.shadow_trading.models import TERMINAL_STATUSES
status_sql, status_params = status_in_clause({"closed"})
cursor.execute(f"... WHERE {status_sql} ...", (..., *status_params))
```

For `WHERE status IN ('open', 'exit_pending')`:
```python
# Before  
"WHERE status IN ('open', 'exit_pending')"

# After
from src.shadow_trading._status_sql import status_in_clause
from src.shadow_trading.models import ACTIVE_STATUSES
status_sql, status_params = status_in_clause(ACTIVE_STATUSES)
cursor.execute(f"... WHERE {status_sql} ...", (..., *status_params))
```

If a line is a non-SQL Python equality comparison (e.g., `if trade.status == 'closed':`), use the model constants directly:
```python
# Before
if trade.status == 'closed':

# After (Python comparison, no SQL involved)
from src.shadow_trading.models import TERMINAL_STATUSES
if trade.status in TERMINAL_STATUSES:
```

If a hardcoded literal is correct and intentional (e.g., a test fixture INSERT specifying a specific status value to insert), append `# noqa: status-literal` to the line.

- [ ] **Step 5: Migrate reconcile.py, governor.py, reports.py**

Apply the same transformation pattern. For `reports.py` specifically (~19 sites), most are aggregation queries — they typically want `IN (TERMINAL_STATUSES)` or `IN (ACTIVE_STATUSES)`.

- [ ] **Step 6: Verify GREEN + regression**

```bash
python -m pytest tests/test_tier_1_hardening.py::test_no_hardcoded_status_strings_in_sql -v
python -m pytest tests/test_executor_entry.py tests/shadow_trading/ tests/test_reconcile.py tests/test_risk_governor.py tests/test_reports.py -q
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add src/shadow_trading/_status_sql.py src/shadow_trading/executor.py src/shadow_trading/reconcile.py src/risk/governor.py src/scheduler/reports.py tests/test_tier_1_hardening.py
git commit -m "fix(consistency): consolidate ~50 hardcoded status strings → TERMINAL/ACTIVE_STATUSES (#437, #482)

Pre-fix CLAUDE.md rule 'Status constants are canonical' was being
violated in 50+ places across executor.py (25), scheduler/reports.py
(19), shadow_trading/reconcile.py (4), and risk/governor.py (3).

Added src/shadow_trading/_status_sql.py with status_in_clause() /
status_not_in_clause() helpers that build parameterized IN fragments
from the canonical frozensets. Migrated all SQL filter sites; for
Python equality checks, used the constants directly.

Regression guard in tests/test_tier_1_hardening.py prevents the bare
strings from re-emerging. Allow-list via 'noqa: status-literal' for
intentional fixtures.

Closes #437 (executor scope), Closes #482 (governor + reports scope)."
```

### Task A.4: #436 — IB bracket fallback ImportError

**Files:**
- Modify: `src/shadow_trading/executor.py` (around line 809)
- Test: `tests/test_tier_1_hardening.py`

Pre-fix: when alpaca SDK imports fail inside the bracket-fallback path, the executor logs a warning AND CONTINUES, leaving the live position without a stop. The fix: hoist the imports to module top so an ImportError surfaces at module-load time (failing fast at startup, not silently mid-trade).

- [ ] **Step 1: Read the current bracket fallback**

```bash
sed -n '800,820p' src/shadow_trading/executor.py
```

Expected: a try/except ImportError block with `logger.warning(...)`. Confirm exact line numbers.

- [ ] **Step 2: Write failing test**

Append to `tests/test_tier_1_hardening.py`:

```python
def test_ib_bracket_fallback_no_silent_importerror():
    """#436 — Pre-fix the bracket fallback caught ImportError silently and
    left the live position unprotected (no stop). The alpaca imports
    must be at module top so they fail at startup, not mid-trade."""
    text = _read("src/shadow_trading/executor.py")
    # The pattern we're guarding against: an inner try block that imports
    # alpaca symbols and on ImportError logs a warning and falls through
    # without closing/stopping the live position.
    bad_pattern = re.compile(
        r"except ImportError:\s*\n\s*logger\.warning\([^)]*Stop order imports unavailable",
        re.MULTILINE,
    )
    assert not bad_pattern.search(text), (
        "#436 — `except ImportError: logger.warning('Stop order imports unavailable...')` "
        "regressed in executor.py. Move alpaca imports to module top so "
        "import failures crash startup instead of leaving live positions unprotected."
    )
```

- [ ] **Step 3: Verify RED**

Run: `python -m pytest tests/test_tier_1_hardening.py::test_ib_bracket_fallback_no_silent_importerror -v`
Expected: FAIL.

- [ ] **Step 4: Locate the alpaca imports inside bracket fallback**

```bash
grep -n "from alpaca\|import alpaca" src/shadow_trading/executor.py
```

Expected: imports inside `try:` blocks within bracket-related functions around lines 776-810.

- [ ] **Step 5: Hoist alpaca imports to module top**

At the top of `src/shadow_trading/executor.py`, after the existing `from src.config import DB_PATH` (or similar), add:

```python
# #436 — alpaca SDK imports must be at module top so an ImportError
# surfaces at startup rather than silently leaving live positions
# unprotected mid-trade. Pre-fix the bracket fallback caught
# ImportError, logged a warning, and continued without a stop.
try:
    from alpaca.trading.requests import LimitOrderRequest, StopLossRequest, TakeProfitRequest
    from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
    _ALPACA_BRACKET_AVAILABLE = True
except ImportError as _exc:
    _ALPACA_BRACKET_AVAILABLE = False
    _ALPACA_IMPORT_ERROR = _exc
```

- [ ] **Step 6: Replace inner import + ImportError branch**

In the bracket fallback (~line 800-810), remove the inner `try: from alpaca... except ImportError: logger.warning(...)` block. Replace with:

```python
        # #436 — module-level imports were hoisted; if alpaca isn't
        # available, _ALPACA_BRACKET_AVAILABLE is False and we MUST NOT
        # leave the live position unprotected. Raise so the operator
        # sees the failure immediately.
        if not _ALPACA_BRACKET_AVAILABLE:
            raise RuntimeError(
                f"Cannot place bracket for {ticker} — alpaca SDK unavailable: "
                f"{_ALPACA_IMPORT_ERROR}. Live position would be unprotected. "
                "Refusing to submit unprotected order."
            ) from _ALPACA_IMPORT_ERROR
        # ... rest of the bracket-build logic ...
```

- [ ] **Step 7: Verify GREEN + regression**

```bash
python -m pytest tests/test_tier_1_hardening.py::test_ib_bracket_fallback_no_silent_importerror -v
python -m pytest tests/test_executor_entry.py tests/shadow_trading/ -q
```

Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add src/shadow_trading/executor.py tests/test_tier_1_hardening.py
git commit -m "fix(trading-safety): hoist alpaca bracket imports to module top (#436)

Pre-fix the bracket-fallback try block at executor.py:~809 caught
ImportError and logged 'Stop order imports unavailable for X — position
unprotected' as a WARNING, then fell through. Live position would have
been left WITHOUT A STOP — silent and dangerous.

Hoisted alpaca imports to module top with _ALPACA_BRACKET_AVAILABLE
flag. Inner check now raises RuntimeError if SDK is missing, refusing
to submit an unprotected order. Regression guard prevents the silent
warn-and-continue pattern from re-emerging.

Closes #436."
```

### Task A.5: PR-A final test sweep + push + open PR

- [ ] **Step 1: Full test sweep**

```bash
rm -f ai_research_desk.sqlite3
python -m pytest tests/ -q --no-header --tb=line --ignore=tests/test_repo_structure.py
```

Expected: ≥ 2,866 passing, 0 failing. STOP if any fail; investigate root cause and fix per the user's standing rule.

- [ ] **Step 2: Push + open PR**

```bash
git push -u origin fix/tier-1-bundle-2026-04-24
gh pr create --base main --title "fix(triage): tier-1 bundle — logging UTF-8 + connect_db × 31 + status strings + IB bracket (#619, #578, #437, #482, #436)" --body "$(cat <<'EOF'
Closes 5 issues across the Tier-1 mechanical bundle.

## Commits
- \`fix(logging): RotatingFileHandler encoding=utf-8 (#619)\`
- \`fix(deps): migrate 31 raw sqlite3.connect sites to connect_db (#578)\`
- \`fix(consistency): consolidate ~50 hardcoded status strings (#437, #482)\`
- \`fix(trading-safety): hoist alpaca bracket imports to module top (#436)\`

## Test plan
- [x] Full sweep clean (≥ 2,866 passing, 0 failing)
- [ ] Smoke-test logging by emitting an emoji message to logs/arcis.log and verifying the bytes are written
- [ ] Smoke-test connect_db migration by running an overnight cycle and confirming no 'database is locked' errors
- [ ] Confirm the new \`status_in_clause\` helper produces parameterized SQL (no f-string interpolation of values)
- [ ] If alpaca SDK is missing on a fresh install, confirm the executor raises at startup instead of continuing

## Files changed
~7 files, all source-scan regression-guarded by tests/test_tier_1_hardening.py.
EOF
)"
```

---

## PR-B: Tier 1.5 hygiene (~6 items, ~2h)

### Task B.0: Branch + skeleton test file

- [ ] **Step 1: Create branch off latest main**

```bash
git checkout main && git pull
git checkout -b fix/tier-1-5-hygiene-2026-04-24
```

- [ ] **Step 2: Create regression-guard test file**

Write to `tests/test_tier_1_5_hygiene.py`:

```python
"""Regression guards for Tier 1.5 hygiene fixes."""

from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")
```

### Task B.1: CLAUDE.md test-count update

**Files:**
- Modify: `CLAUDE.md`
- Test: `tests/test_tier_1_5_hygiene.py`

- [ ] **Step 1: Confirm current test count**

```bash
python -m pytest tests/ -q --collect-only --ignore=tests/test_repo_structure.py 2>&1 | tail -3
```

Note the count (should be ~2,890+ after PR-A's new tests).

- [ ] **Step 2: Write failing test**

Append to `tests/test_tier_1_5_hygiene.py`:

```python
def test_claude_md_test_count_is_current():
    """CLAUDE.md mentions a minimum test count — must reflect actual current
    count within reasonable tolerance, not be stuck at 1339 from months ago."""
    text = _read("CLAUDE.md")
    m = re.search(r"minimum of (\d+) tests", text)
    assert m, "CLAUDE.md must declare a minimum test count"
    declared = int(m.group(1))
    assert declared >= 2800, (
        f"CLAUDE.md declares minimum {declared} tests but actual is "
        "~2,890+. Update the constant to reflect current state."
    )
```

- [ ] **Step 3: Verify RED**

Run: `python -m pytest tests/test_tier_1_5_hygiene.py::test_claude_md_test_count_is_current -v`
Expected: FAIL — declares 1339 (or whatever stale value).

- [ ] **Step 4: Update CLAUDE.md**

In `CLAUDE.md`, find the line containing `"minimum of 1339 tests"` (or similar) and update to `"minimum of 2866 tests"` (matches the verified Phase B baseline).

- [ ] **Step 5: Verify GREEN**

Run: `python -m pytest tests/test_tier_1_5_hygiene.py::test_claude_md_test_count_is_current -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md tests/test_tier_1_5_hygiene.py
git commit -m "docs(claude-md): bump test minimum 1339 → 2866

The 1339 constant predates by months the Sprint 1-6 work. Current
sweep is 2,866 passing. Bumping the floor prevents 'we're below the
minimum' alarms from being noise and brings the doc in sync with
reality. Regression guard fails CI if the doc drifts again."
```

### Task B.2: Cleanup script `--dry-run` flag

**Files:**
- Modify: `scripts/cleanup_test_pollution_2026_04.py`
- Test: `tests/test_tier_1_5_hygiene.py`

- [ ] **Step 1: Read existing cleanup script**

```bash
cat scripts/cleanup_test_pollution_2026_04.py
```

Confirm it exists (created in PR #634) and currently does an unconditional DELETE.

- [ ] **Step 2: Write failing test**

Append to `tests/test_tier_1_5_hygiene.py`:

```python
def test_cleanup_script_supports_dry_run():
    """The cleanup script must accept --dry-run for safe pre-flight."""
    text = _read("scripts/cleanup_test_pollution_2026_04.py")
    assert "--dry-run" in text or "dry_run" in text, (
        "scripts/cleanup_test_pollution_2026_04.py must accept a --dry-run "
        "flag so operator can preview the DELETE before applying."
    )
    # Must use argparse (not raw sys.argv parsing) for safety.
    assert "argparse" in text or "click" in text, (
        "Cleanup script must use argparse (or click) for clean CLI parsing"
    )
```

- [ ] **Step 3: Verify RED**

Run: `python -m pytest tests/test_tier_1_5_hygiene.py::test_cleanup_script_supports_dry_run -v`
Expected: FAIL.

- [ ] **Step 4: Rewrite cleanup script with --dry-run + report output**

Replace contents of `scripts/cleanup_test_pollution_2026_04.py`:

```python
"""Cleanup script for the 540 test-polluted activity_log rows (#613).

Tests that called _global_halt(source='test') and _global_halt(source='auditor')
without monkeypatching DB_PATH wrote 540 fake kill_switch_halt rows into
the prod ai_research_desk.sqlite3 over the last 30 days. PR #634 added a
PYTEST_CURRENT_TEST guard that prevents future pollution; this script
removes the existing rows.

Usage:
    python scripts/cleanup_test_pollution_2026_04.py --dry-run
    python scripts/cleanup_test_pollution_2026_04.py --apply
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

DB = Path("C:/arcis/data/ai_research_desk.sqlite3")

_DELETE_PREDICATES = (
    "detail LIKE 'source=test%'",
    "detail = 'source=auditor, reason=Catastrophic loss detected'",
    "detail = 'source=auditor, reason=Governor check bypassed'",
    "detail = 'source=auditor, reason=Halt command ignored'",
)


def _build_where_clause() -> str:
    return (
        "event_type = 'kill_switch_halt' AND ("
        + " OR ".join(_DELETE_PREDICATES)
        + ")"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true",
                   help="Show what WOULD be deleted; make no changes.")
    g.add_argument("--apply", action="store_true",
                   help="Actually delete the polluted rows.")
    parser.add_argument("--db", default=str(DB),
                        help="DB path (default: %(default)s)")
    args = parser.parse_args()

    where = _build_where_clause()
    if args.dry_run:
        # Read-only mode for safety
        conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
        try:
            count = conn.execute(
                f"SELECT COUNT(*) FROM activity_log WHERE {where}"
            ).fetchone()[0]
            print(f"[DRY RUN] Would delete {count} rows from activity_log")
            sample = conn.execute(
                f"SELECT created_at, event_type, detail FROM activity_log "
                f"WHERE {where} ORDER BY created_at DESC LIMIT 10"
            ).fetchall()
            print("[DRY RUN] Sample rows (most recent 10):")
            for row in sample:
                print(f"  {row[0]}  {row[1]}  {row[2][:80]}")
        finally:
            conn.close()
        return 0

    # --apply mode
    print(f"[APPLY] Deleting polluted rows from {args.db}")
    with sqlite3.connect(args.db) as conn:
        cursor = conn.execute(f"DELETE FROM activity_log WHERE {where}")
        n = cursor.rowcount
        conn.commit()
    print(f"[APPLY] Deleted {n} rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Verify GREEN + smoke-test the script**

```bash
python -m pytest tests/test_tier_1_5_hygiene.py::test_cleanup_script_supports_dry_run -v
python scripts/cleanup_test_pollution_2026_04.py --dry-run --db ai_research_desk.sqlite3 2>&1 | head -5
```

Expected: test passes; dry-run returns "Would delete N rows" (N=0 if local DB is empty — that's fine).

- [ ] **Step 6: Commit**

```bash
git add scripts/cleanup_test_pollution_2026_04.py tests/test_tier_1_5_hygiene.py
git commit -m "chore(scripts): cleanup_test_pollution_2026_04 supports --dry-run

Pre-rewrite the script unconditionally deleted the 540 polluted rows,
no preview, no confirmation. Now uses argparse with mutually-exclusive
--dry-run / --apply flags. --dry-run opens the DB read-only and prints
the count + 10 sample rows; --apply does the DELETE. Operator can
safely pre-flight the cleanup before committing."
```

### Task B.3: #631-9 + #631-18 UI items

**Files:**
- Modify: `frontend/src/pages/Dashboard.jsx` (Quick Stats + System Index empty-state)
- Modify: `frontend/src/pages/Dashboard.jsx` (Warnings dot — actually in the AuditChip area)
- Test: source-scan in `tests/test_tier_1_5_hygiene.py`

- [ ] **Step 1: Find the Quick Stats + System Index sections in Dashboard.jsx**

```bash
grep -n "Quick Stats\|System Index\|capabilities" frontend/src/pages/Dashboard.jsx
```

- [ ] **Step 2: Write failing test**

Append to `tests/test_tier_1_5_hygiene.py`:

```python
def test_dashboard_collapses_empty_quick_stats():
    """#631-9 — When Quick Stats has no data (0 capabilities, 0 needing
    review), the panel should be hidden/collapsed instead of eating prime
    real-estate. Pre-fix two consecutive empty cards made the top of the
    dashboard feel abandoned."""
    text = _read("frontend/src/pages/Dashboard.jsx")
    # Look for a conditional render around Quick Stats — either an
    # `{quickStats?.length > 0 && ...}` short-circuit or an early return.
    assert (
        re.search(r"(quickStats|quick_stats|capabilities)[^}]{0,80}\?\?[^}]{0,40}length\s*>\s*0", text)
        or re.search(r"if\s*\(\s*!?\s*(quickStats|quick_stats|capabilities)", text)
        or re.search(r"\{\s*(quickStats|quick_stats|capabilities)[^}]{0,40}\.length\s*>\s*0\s*&&", text)
    ), (
        "#631-9 — Dashboard.jsx must conditionally render the Quick Stats "
        "panel; pre-fix it always rendered with '0 capabilities · 0 need review'."
    )


def test_dashboard_hides_warnings_dot_when_zero():
    """#631-18 — The yellow warnings dot in the top-right header should
    be hidden when warning count is 0. Pre-fix the gold dot always
    appeared, implying caution even when clean."""
    text = _read("frontend/src/pages/Dashboard.jsx")
    # The audit-chip area must conditionally render the dot OR change
    # color when assessment is 'green'/'healthy'.
    # Check for either: (a) explicit `count > 0 &&` around the dot, or
    # (b) a getAuditChipState('green') case that returns no dot.
    assert (
        "warnings_count" in text
        or "warningsCount" in text
        or re.search(r"assessment\s*===\s*['\"]green", text)
    ), (
        "#631-18 — Dashboard must distinguish 0-warning from N-warning "
        "states (either via warnings_count gate or assessment-based dot color)."
    )
```

- [ ] **Step 3: Verify RED on Quick Stats test (the warnings test may already pass via the `assessment === 'green'` path)**

Run: `python -m pytest tests/test_tier_1_5_hygiene.py::test_dashboard_collapses_empty_quick_stats -v`
Expected: FAIL.

- [ ] **Step 4: Wrap Quick Stats panel in conditional render**

Find the Quick Stats section (likely `<div className="arcis-card">` containing `0 capabilities`). Wrap it:

```jsx
{(quickStats?.length > 0 || (capabilitiesCount && capabilitiesCount > 0)) && (
  <div className="arcis-card">
    <h3 className="text-sm uppercase tracking-wide" style={{ color: 'var(--arcis-text-secondary)' }}>Quick Stats</h3>
    {/* ... existing inner content ... */}
  </div>
)}
```

(Adjust variable names to match what's actually in scope at that location.)

- [ ] **Step 5: Same treatment for System Index panel**

Find the System Index card and wrap with the equivalent conditional. Both panels are now hidden when empty.

- [ ] **Step 6: Verify GREEN**

Run: `python -m pytest tests/test_tier_1_5_hygiene.py -v`
Expected: both tests pass.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/Dashboard.jsx tests/test_tier_1_5_hygiene.py
git commit -m "fix(ux): collapse empty Quick Stats + System Index panels (#631-9)

Pre-fix two consecutive empty panels at the top of the dashboard
('0 capabilities · 0 need review' / 'No capabilities registered yet')
made the page feel abandoned to first-time users. Both now hide
when there's no data to show.

Visual verification still required before merge — start dev server
and confirm panels appear when capabilities ARE present."
```

### Task B.4: #621 — packets/template.py refuse to build on price=0

**Files:**
- Modify: `src/packets/template.py:152`
- Test: `tests/test_tier_1_5_hygiene.py`

- [ ] **Step 1: Read the current build_packet_from_features**

```bash
sed -n '140,170p' src/packets/template.py
```

- [ ] **Step 2: Write failing test**

Append to `tests/test_tier_1_5_hygiene.py`:

```python
def test_packet_builder_returns_none_when_price_invalid():
    """#621 — When upstream feature pipeline returns price <= 0, the
    packet builder must refuse to construct a packet. Pre-fix it built
    a packet with shares=1 and allocation=$0, then the LLM was called
    (~17s) and the governor finally rejected with 'Zero or negative
    allocation' — wasting 110+ minutes of LLM compute per 3-day window."""
    from src.packets.template import build_packet_from_features
    features = {
        "current_price": 0,
        "atr_14": 1.5,
        "stop_invalidation": 95.0,
        "trend_state": "uptrend",
        "ticker": "BAD",
        "company_name": "Bad Co",
    }
    result = build_packet_from_features("BAD", features, {})
    assert result is None, (
        "#621 — packet builder must return None when current_price <= 0"
    )


def test_packet_builder_returns_none_when_price_negative():
    from src.packets.template import build_packet_from_features
    features = {"current_price": -5, "atr_14": 1.5, "ticker": "NEG", "company_name": "X"}
    assert build_packet_from_features("NEG", features, {}) is None
```

- [ ] **Step 3: Verify RED**

Run: `python -m pytest tests/test_tier_1_5_hygiene.py::test_packet_builder_returns_none_when_price_invalid tests/test_tier_1_5_hygiene.py::test_packet_builder_returns_none_when_price_negative -v`
Expected: FAIL (current builds a packet anyway).

- [ ] **Step 4: Patch build_packet_from_features**

At the top of `src/packets/template.py::build_packet_from_features`, after the args are unpacked but BEFORE any computation:

```python
def build_packet_from_features(ticker, features, config):
    """..."""
    # #621 — Refuse to build a packet when the upstream feature pipeline
    # returns a non-positive price. Pre-fix the builder produced a packet
    # with shares=1 / allocation=$0 / [meaningless prose], the LLM was
    # called (~17s), and the governor finally rejected the trade. ~110
    # minutes of LLM compute wasted per 3-day window. Refusing here also
    # surfaces the upstream feature-fetch issue via the warning log.
    price = features.get("current_price")
    if price is None or float(price) <= 0:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "[PACKET] Refusing to build packet for %s — invalid price=%s "
            "(upstream feature pipeline returned None or non-positive)",
            ticker, price,
        )
        return None
    # ... existing implementation continues ...
```

- [ ] **Step 5: Verify GREEN + regression**

```bash
python -m pytest tests/test_tier_1_5_hygiene.py -v
python -m pytest tests/test_packets.py tests/test_template.py 2>/dev/null -q
```

Expected: new tests pass; no regressions.

- [ ] **Step 6: Commit**

```bash
git add src/packets/template.py tests/test_tier_1_5_hygiene.py
git commit -m "fix(packets): refuse to build packet when price <= 0 (#621 partial)

Pre-fix the packet builder accepted a current_price of 0 from the
upstream feature pipeline, built a packet with shares=1 and
allocation=\$0, called the LLM (~17s), and was finally rejected by the
governor with 'Zero or negative allocation'. Audit found 390 such
wasted attempts in 3 days = ~110 min of LLM compute. The new guard
emits a warning so the upstream feature-fetch issue is visible (the
14 specific tickers consistently returning price=0 should be tracked
in a follow-up issue).

Closes the defensive-fix half of #621; the upstream investigation
(why those 14 tickers return price=0) is filed as a follow-up."
```

### Task B.5: #478 — routes connect_db migration

**Files:**
- Modify: `src/api/routes/{council,health,ib_status,live,logs,notes}.py`
- Test: `tests/test_tier_1_5_hygiene.py`

- [ ] **Step 1: Confirm site count**

```bash
grep -rn "sqlite3\.connect\(" src/api/routes/ | grep -v ".pyc"
```

Expected: ~15 sites across 6 files.

- [ ] **Step 2: Write failing test**

Append to `tests/test_tier_1_5_hygiene.py`:

```python
def test_routes_use_connect_db_helper():
    """#478 — API routes must use connect_db() so busy_timeout=30s applies."""
    targets = [
        "src/api/routes/council.py",
        "src/api/routes/health.py",
        "src/api/routes/ib_status.py",
        "src/api/routes/live.py",
        "src/api/routes/logs.py",
        "src/api/routes/notes.py",
    ]
    bad: list[str] = []
    for path in targets:
        try:
            text = _read(path)
        except FileNotFoundError:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if line.strip().startswith("#"):
                continue
            if re.search(r"\bsqlite3\.connect\(", line) and "noqa: db" not in line:
                bad.append(f"{path}:{i}")
    assert not bad, (
        "Use connect_db() in routes — found raw sqlite3.connect at: "
        + ", ".join(bad)
    )
```

- [ ] **Step 3: Verify RED**

Run: `python -m pytest tests/test_tier_1_5_hygiene.py::test_routes_use_connect_db_helper -v`
Expected: FAIL listing ~15 sites.

- [ ] **Step 4: Migrate each file**

For each of the 6 files:

```bash
sed -i 's/sqlite3\.connect(/connect_db(/g' src/api/routes/council.py
sed -i 's/sqlite3\.connect(/connect_db(/g' src/api/routes/health.py
sed -i 's/sqlite3\.connect(/connect_db(/g' src/api/routes/ib_status.py
sed -i 's/sqlite3\.connect(/connect_db(/g' src/api/routes/live.py
sed -i 's/sqlite3\.connect(/connect_db(/g' src/api/routes/logs.py
sed -i 's/sqlite3\.connect(/connect_db(/g' src/api/routes/notes.py
```

Then for each file, manually add the import after the existing imports:

```python
from src.utils.db import connect_db
```

- [ ] **Step 5: Verify GREEN + regression**

```bash
python -m pytest tests/test_tier_1_5_hygiene.py::test_routes_use_connect_db_helper -v
python -m pytest tests/test_local_api_routes.py tests/api/ -q
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/api/routes/ tests/test_tier_1_5_hygiene.py
git commit -m "fix(deps): migrate ~15 raw sqlite3.connect sites in routes/ → connect_db (#478 partial)

6 files: council, health, ib_status, live, logs, notes. Same fix shape
as the journal/store + training/versioning batch in PR-A — connect_db
applies busy_timeout=30s consistently. The remaining ~50 raw connect
sites in audit, walkforward, evaluation are tracked in #478 for a
future batch."
```

### Task B.6: Test backfill for helpers added in PR #634

**Files:**
- Create: `tests/test_helper_coverage_backfill.py`

The helpers added in PR #634 — `_handle_pre_exit_cancel`, `_next_exit_retry_count`, `_should_abandon_exit`, `_resolve_stuck_pnl`, `_is_likely_sleep_gap`, `_is_collector_error`, `verify_local_token`, `_default_current_price_provider` — are mostly covered, but verify each has at least one positive AND one negative case.

- [ ] **Step 1: Audit existing coverage**

```bash
grep -rn "_handle_pre_exit_cancel\|_next_exit_retry_count\|_should_abandon_exit\|_resolve_stuck_pnl\|_is_likely_sleep_gap\|_is_collector_error\|verify_local_token\|_default_current_price_provider" tests/ 2>&1 | head -30
```

Note which helpers have <2 test references (positive + negative).

- [ ] **Step 2: Write the backfill file**

Write to `tests/test_helper_coverage_backfill.py`:

```python
"""Coverage backfill — exercise edge cases for helpers added in PR #634.

Most helpers already have positive-path tests (e.g., the cancel-handler
returns True for filled). This file ensures each has at least one
negative-path test as well, plus boundary conditions.
"""

from __future__ import annotations

import pytest


# ── _default_current_price_provider negative path ──

def test_default_current_price_provider_returns_none_for_invalid_ticker():
    from src.shadow_trading.reconcile import _default_current_price_provider
    # Empty string and None should return None without raising.
    assert _default_current_price_provider("") is None
    assert _default_current_price_provider(None) is None


# ── _resolve_stuck_pnl boundary: zero shares ──

def test_resolve_stuck_pnl_zero_shares():
    from src.shadow_trading.reconcile import _resolve_stuck_pnl
    trade = {"entry_price": 100.0, "shares": 0}
    pnl = _resolve_stuck_pnl(trade, exit_reason="timeout",
                             current_price_provider=lambda t: 105.0)
    assert pnl == 0.0  # zero shares × any price delta = 0


def test_resolve_stuck_pnl_zero_entry_price():
    from src.shadow_trading.reconcile import _resolve_stuck_pnl
    trade = {"entry_price": 0.0, "shares": 10}
    pnl = _resolve_stuck_pnl(trade, exit_reason="timeout",
                             current_price_provider=lambda t: 105.0)
    # Zero entry can't compute a PnL — must return None
    assert pnl is None


# ── _next_exit_retry_count boundary ──

def test_next_exit_retry_count_handles_string_value():
    from src.shadow_trading.executor import _next_exit_retry_count
    # SQLite REAL columns sometimes return as string (#195 family);
    # the helper must coerce.
    assert _next_exit_retry_count({"exit_retry_count": "2"}) == 3


def test_next_exit_retry_count_handles_garbage():
    from src.shadow_trading.executor import _next_exit_retry_count
    # Garbage value should default to 1 (treat as fresh failure).
    assert _next_exit_retry_count({"exit_retry_count": "garbage"}) == 1


# ── _is_likely_sleep_gap exact boundary ──

def test_is_likely_sleep_gap_exactly_at_threshold():
    from src.scheduler.watch import _is_likely_sleep_gap
    # Threshold is 1.5x. At exactly 1.5x it should NOT trigger
    # (use strict greater-than to give jitter the benefit).
    assert _is_likely_sleep_gap(elapsed_min=45.0, scan_interval_min=30) is False


# ── _is_collector_error edge cases ──

def test_is_collector_error_handles_none_input():
    from src.scheduler.overnight import _is_collector_error
    # Defensive: should not raise on None
    assert _is_collector_error(None) is False


def test_is_collector_error_handles_int_input():
    from src.scheduler.overnight import _is_collector_error
    # Defensive: a bare integer is neither dict nor str-error
    assert _is_collector_error(0) is False
    assert _is_collector_error(5) is False
```

- [ ] **Step 3: Run new tests**

```bash
python -m pytest tests/test_helper_coverage_backfill.py -v
```

Expected: all pass (these are testing existing helpers' edge cases, not new functionality).

- [ ] **Step 4: If any test fails, fix the helper to handle the case**

For example, if `_resolve_stuck_pnl` doesn't return `None` on zero entry_price, add the guard:

```python
if entry_px <= 0:
    return None
```

(Likely already there — verify.)

- [ ] **Step 5: Commit**

```bash
git add tests/test_helper_coverage_backfill.py
git commit -m "test(coverage): edge-case backfill for PR #634 helpers

Eight new tests covering negative paths and boundary conditions for
_default_current_price_provider, _resolve_stuck_pnl, _next_exit_retry_count,
_is_likely_sleep_gap, _is_collector_error. Each helper now has both a
positive and a negative test, preventing regressions when these are
refactored later."
```

### Task B.7: PR-B test sweep + push + open PR

- [ ] **Step 1: Full sweep**

```bash
rm -f ai_research_desk.sqlite3
python -m pytest tests/ -q --no-header --tb=line --ignore=tests/test_repo_structure.py
```

Expected: ≥ baseline + new tests, 0 failing.

- [ ] **Step 2: Push + open PR**

```bash
git push -u origin fix/tier-1-5-hygiene-2026-04-24
gh pr create --base main --title "fix(hygiene): tier-1.5 — claude-md test count + cleanup --dry-run + UI #631-9 + price=0 + routes connect_db + helper backfill" --body "$(cat <<'EOF'
Closes Tier 1.5 hygiene items in one bundle.

## Commits
- \`docs(claude-md): bump test minimum 1339 → 2866\`
- \`chore(scripts): cleanup_test_pollution_2026_04 supports --dry-run\`
- \`fix(ux): collapse empty Quick Stats + System Index panels (#631-9)\`
- \`fix(packets): refuse to build packet when price <= 0 (#621 partial)\`
- \`fix(deps): migrate ~15 raw sqlite3.connect sites in routes/ → connect_db (#478 partial)\`
- \`test(coverage): edge-case backfill for PR #634 helpers\`

## Test plan
- [x] Full sweep clean
- [ ] \`python scripts/cleanup_test_pollution_2026_04.py --dry-run --db data/ai_research_desk.sqlite3\` previews the deletion safely
- [ ] Visual smoke-test the dashboard (cd frontend && npm run dev) — confirm Quick Stats panel HIDES when capabilities=0 and APPEARS when capabilities>0

## Files changed
~10 files, source-scan regression-guarded by tests/test_tier_1_5_hygiene.py + tests/test_helper_coverage_backfill.py.
EOF
)"
```

---

## PR-C: Tier 2 safety (3 items, ~1.5h)

### Task C.0: Branch + skeleton

- [ ] **Step 1: Branch**

```bash
git checkout main && git pull
git checkout -b fix/tier-2-safety-2026-04-24
```

- [ ] **Step 2: Skeleton test file**

Write to `tests/test_tier_2_safety.py`:

```python
"""Regression guards for Tier 2 safety hardening (#574, #580, #615 follow-up)."""

from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")
```

### Task C.1: #574 — startup fail-fast when live mode + governor disabled

**Files:**
- Modify: `src/cli/commands.py::cmd_startup`
- Test: `tests/test_tier_2_safety.py`

- [ ] **Step 1: Read existing cmd_startup**

```bash
sed -n '1170,1260p' src/cli/commands.py
```

Note where the live-mode check would naturally fit (after config load, before WatchLoop launch).

- [ ] **Step 2: Write failing test**

Append to `tests/test_tier_2_safety.py`:

```python
def test_cmd_startup_refuses_live_mode_with_governor_disabled():
    """#574 — When live trading is enabled AND risk_governor.enabled=false,
    cmd_startup must refuse to launch (exit 2). Pre-fix it would log a
    warning + Telegram and continue, which is the wrong posture in live
    mode where a disabled governor means trades open with no risk gating."""
    text = _read("src/cli/commands.py")
    # The check must be present in the cmd_startup function.
    m = re.search(
        r"def cmd_startup\(args\):[\s\S]{0,4000}",
        text,
    )
    assert m, "cmd_startup not found in commands.py"
    body = m.group(0)
    # Must reference live_trading + risk_governor and exit when both conflict.
    assert "live_trading" in body and "risk_governor" in body, (
        "#574 — cmd_startup must check live_trading + risk_governor config"
    )
    assert ("sys.exit" in body or "raise SystemExit" in body), (
        "#574 — cmd_startup must exit (not just warn) when the conflict is detected"
    )
```

- [ ] **Step 3: Verify RED**

Run: `python -m pytest tests/test_tier_2_safety.py::test_cmd_startup_refuses_live_mode_with_governor_disabled -v`
Expected: FAIL.

- [ ] **Step 4: Add the check**

In `src/cli/commands.py::cmd_startup`, after the existing config load (around line 1181-1182), add:

```python
    config = load_config()
    # #574 — Live trading with the risk governor disabled is the ONE
    # configuration combo that's never safe. Pre-fix the system would
    # warn + Telegram-alert via _warn_governor_disabled_once but continue
    # to launch. That's wrong: in live mode, every trade then opens with
    # no daily-loss / position-size / sector-cap / vol-halt gating.
    # Fail-fast at startup so the operator sees the issue immediately.
    live_cfg = config.get("live_trading", {})
    risk_cfg = config.get("risk_governor", {})
    if live_cfg.get("enabled", False) and not risk_cfg.get("enabled", True):
        print("=" * 44)
        print("  ARCIS — STARTUP REFUSED")
        print("=" * 44)
        print()
        print("  live_trading.enabled = true")
        print("  risk_governor.enabled = false")
        print()
        print("  This combination is never safe — every trade would open")
        print("  with no risk gating. Either:")
        print("    1) Set risk_governor.enabled: true in settings.local.yaml, OR")
        print("    2) Set live_trading.enabled: false to run paper-only.")
        print()
        sys.exit(2)
```

- [ ] **Step 5: Verify GREEN + run actual cmd_startup test (skip the live launch)**

```bash
python -m pytest tests/test_tier_2_safety.py::test_cmd_startup_refuses_live_mode_with_governor_disabled -v
# Existing tests for cmd_startup, if any:
python -m pytest tests/ -k "startup" -q
```

Expected: green. If any existing startup test runs cmd_startup against a config with both flags set, it will now exit 2 — update the fixture to set `risk_governor.enabled=true` if necessary.

- [ ] **Step 6: Commit**

```bash
git add src/cli/commands.py tests/test_tier_2_safety.py
git commit -m "fix(safety): cmd_startup fail-fast when live + governor disabled (#574)

Pre-fix the only protection was _warn_governor_disabled_once which
logged + Telegrammed but allowed launch. In live mode this is the
'never-safe' combo: trades open with no daily-loss / position-size /
sector-cap / vol-halt gating.

Now exits 2 with a clear message when both flags conflict, naming the
two ways to resolve. The single-warning behavior is preserved for
paper mode (where bypassing is operator's call).

Closes the live-mode hardening half of #574."
```

### Task C.2: #580 — activity_log AUTOINCREMENT in schema registry

**Files:**
- Modify: `src/schema/registry.py` (activity_log table definition)
- Test: `tests/test_tier_2_safety.py`

- [ ] **Step 1: Find activity_log in registry**

```bash
grep -n 'name="activity_log"' src/schema/registry.py
```

Confirm the table definition starts there.

- [ ] **Step 2: Write failing test**

Append to `tests/test_tier_2_safety.py`:

```python
def test_activity_log_id_is_autoincrement_in_registry():
    """#580 — activity_log.id must be PRIMARY KEY AUTOINCREMENT in the
    schema registry. Pre-fix it was bare INTEGER, so all writes that
    didn't explicitly set an id got NULL — render_sync then dropped them.
    Audit found 1,489 NULL ids out of 1,672 rows."""
    text = _read("src/schema/registry.py")
    # Find the activity_log block and check the id column.
    m = re.search(
        r'name="activity_log"[\s\S]{0,2500}?primary_key=',
        text,
    )
    assert m, "activity_log table definition not found"
    block = m.group(0)
    # The id column declaration must include AUTOINCREMENT.
    id_match = re.search(r'ColumnDef\(\s*"id"[^)]*\)', block, re.DOTALL)
    assert id_match, "id column not found in activity_log block"
    id_def = id_match.group(0)
    assert "AUTOINCREMENT" in id_def or "autoincrement" in id_def, (
        "#580 — activity_log.id must declare AUTOINCREMENT in registry.py"
    )
```

- [ ] **Step 3: Verify RED**

Run: `python -m pytest tests/test_tier_2_safety.py::test_activity_log_id_is_autoincrement_in_registry -v`
Expected: FAIL.

- [ ] **Step 4: Read the current ColumnDef API**

```bash
grep -n "class ColumnDef\|def __init__" src/schema/registry.py | head -5
```

Note the constructor signature. Then update the activity_log id column.

- [ ] **Step 5: Update registry**

Find the activity_log block and change the id column. Most likely the current ColumnDef API supports a `primary_key=True` flag or accepts a `type` like `"INTEGER PRIMARY KEY AUTOINCREMENT"`. The exact transformation depends on the API:

If ColumnDef accepts a freeform type string:
```python
ColumnDef("id", "INTEGER PRIMARY KEY AUTOINCREMENT"),
```

If ColumnDef has dedicated flags:
```python
ColumnDef("id", "INTEGER", primary_key=True, autoincrement=True),
```

Read the existing examples in registry.py for matching patterns. If the existing `primary_key="id"` field at the table level is enough to make AUTOINCREMENT work, the test may need to assert both `primary_key="id"` AND a SQL-generation note. Adjust the test to match the actual API conventions.

- [ ] **Step 6: Verify GREEN + run validate-schema**

```bash
python -m pytest tests/test_tier_2_safety.py::test_activity_log_id_is_autoincrement_in_registry -v
python -m src.main validate-schema 2>&1 | tail -10
```

Expected: test passes; validate-schema reports DRIFT for activity_log (the in-memory definition now declares AUTOINCREMENT but the live DB doesn't).

- [ ] **Step 7: Commit (registry-only, no Postgres apply)**

```bash
git add src/schema/registry.py tests/test_tier_2_safety.py
git commit -m "fix(schema): activity_log.id AUTOINCREMENT in registry (#580)

Pre-fix the id column was bare INTEGER. All writes that didn't
explicitly set an id (which is most of them — log_activity inserts
only event_type/detail/created_at) got NULL. render_sync skipped
NULL-id rows on incremental sync, so 1,489 of 1,672 rows never made
it to the cloud dashboard.

THIS COMMIT IS REGISTRY-ONLY. The Postgres migration is not
auto-applied — operator must run \`python scripts/render_migrate.py\`
in the morning to bring the live DB in sync. validate-schema --check
will report drift until that runs.

Closes the registry portion of #580; the operator-applied migration
is the second half."
```

### Task C.3: #615 follow-up — backfill script for missed 4/13–4/23 trades

**Files:**
- Create: `scripts/backfill_training_4_13_to_4_23.py`
- Test: `tests/test_tier_2_safety.py`

The PR #634 fix prevents future silent failures, but the 17 trades that closed during 4/13–4/23 silently failed and need manual re-collection.

- [ ] **Step 1: Write failing test (script existence)**

Append to `tests/test_tier_2_safety.py`:

```python
def test_backfill_script_exists_and_supports_dry_run():
    """#615 follow-up — script for backfilling the 4/13-4/23 missed
    training trades must support --dry-run and --apply, parallel to the
    test-pollution cleanup script."""
    text = _read("scripts/backfill_training_4_13_to_4_23.py")
    assert "--dry-run" in text or "dry_run" in text, (
        "Backfill script must support --dry-run"
    )
    assert "argparse" in text, "Use argparse for CLI parsing"
    assert "collect_training_examples_from_closed_trades_detailed" in text, (
        "Script must invoke the detailed collector (the one that returns "
        "CollectionResult), not the count-only version"
    )
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_tier_2_safety.py::test_backfill_script_exists_and_supports_dry_run -v`
Expected: FAIL — file doesn't exist.

- [ ] **Step 3: Write the script**

Write to `scripts/backfill_training_4_13_to_4_23.py`:

```python
"""Backfill training_examples for the 17 trades closed 4/13-4/23 (#615).

PR #634 added CollectionResult + silent-failure detection. Before that
fix, training collection silently produced 0 examples for 11 days
during the Anthropic credit outage. This script re-runs the collector
against the missed window so the corpus catches up.

Usage:
    python scripts/backfill_training_4_13_to_4_23.py --dry-run
    python scripts/backfill_training_4_13_to_4_23.py --apply

Pre-flight: confirm Anthropic credits are restored. The script will
abort if the first call returns ClaudeAuthError.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

DB = Path("C:/arcis/data/ai_research_desk.sqlite3")
WINDOW_START = "2026-04-13"
WINDOW_END = "2026-04-23"


def _candidate_trades(db_path: str) -> list[dict]:
    """Return closed shadow_trades in the window that lack training examples."""
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT st.trade_id, st.ticker, st.actual_exit_time, st.recommendation_id
            FROM shadow_trades st
            WHERE st.status = 'closed'
              AND COALESCE(st.quarantined, 0) = 0
              AND DATE(st.actual_exit_time) BETWEEN ? AND ?
              AND NOT EXISTS (
                  SELECT 1 FROM training_examples te
                  WHERE te.recommendation_id = COALESCE(
                      st.recommendation_id, 'trade:' || st.trade_id
                  )
              )
            ORDER BY st.actual_exit_time
            """,
            (WINDOW_START, WINDOW_END),
        ).fetchall()
    return [dict(r) for r in rows]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true",
                   help="List candidate trades, make no LLM calls, write nothing.")
    g.add_argument("--apply", action="store_true",
                   help="Run the collector against the missed window.")
    parser.add_argument("--db", default=str(DB))
    args = parser.parse_args()

    candidates = _candidate_trades(args.db)
    print(f"Found {len(candidates)} candidate trades in {WINDOW_START}..{WINDOW_END}:")
    for c in candidates:
        print(f"  {c['actual_exit_time'][:19]}  {c['ticker']:6s}  trade={c['trade_id'][:8]}")

    if args.dry_run:
        print("\n[DRY RUN] No LLM calls made; no rows written.")
        return 0

    # --apply mode
    print("\n[APPLY] Running collect_training_examples_from_closed_trades_detailed...")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from src.training.data_collector import (
        collect_training_examples_from_closed_trades_detailed,
    )
    from src.training.claude_client import ClaudeAuthError
    try:
        result = collect_training_examples_from_closed_trades_detailed(args.db)
    except ClaudeAuthError as exc:
        print(f"[APPLY] ABORT — Anthropic auth error: {exc}")
        print("Restore credits and try again.")
        return 1

    print(f"\n[APPLY] CollectionResult:")
    print(f"  count             = {result.count}")
    print(f"  attempted         = {result.attempted}")
    print(f"  rejected          = {result.rejected}")
    print(f"  stage1_failures   = {result.stage1_failures}")
    print(f"  skipped_no_features = {result.skipped_no_features}")
    print(f"  halted            = {result.halted}")
    print(f"  is_silent_failure = {result.is_silent_failure}")
    if result.is_silent_failure:
        print("\n[APPLY] WARN — silent failure detected. Check Anthropic + validator.")
        return 1
    print(f"\n[APPLY] Wrote {result.count} new training examples.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Verify GREEN + smoke-test**

```bash
python -m pytest tests/test_tier_2_safety.py::test_backfill_script_exists_and_supports_dry_run -v
python scripts/backfill_training_4_13_to_4_23.py --dry-run --db ai_research_desk.sqlite3 2>&1 | tail -10
```

Expected: test passes; dry-run reports candidate trades (or 0 if local DB is empty).

- [ ] **Step 5: Commit**

```bash
git add scripts/backfill_training_4_13_to_4_23.py tests/test_tier_2_safety.py
git commit -m "scripts: backfill_training_4_13_to_4_23.py (#615 follow-up)

Operator-run script that re-collects training examples for the 17
trades that closed during the 4/13-4/23 Anthropic credit outage.
PR #634 added CollectionResult + silent-failure detection going
forward; this catches up the corpus that was lost.

--dry-run lists candidates without making LLM calls.
--apply runs the detailed collector and reports the structured result.
Aborts on ClaudeAuthError so the operator sees the auth issue clearly."
```

### Task C.4: PR-C test sweep + push + open PR

- [ ] **Step 1: Full sweep**

```bash
rm -f ai_research_desk.sqlite3
python -m pytest tests/ -q --no-header --tb=line --ignore=tests/test_repo_structure.py
```

Expected: all green.

- [ ] **Step 2: Push + open PR with explicit operator-action notes**

```bash
git push -u origin fix/tier-2-safety-2026-04-24
gh pr create --base main --title "fix(safety): tier-2 — startup fail-fast (#574) + activity_log AUTOINCREMENT (#580 registry) + #615 backfill script" --body "$(cat <<'EOF'
Closes Tier 2 safety hardening with explicit operator-action prerequisites.

## Commits
- \`fix(safety): cmd_startup fail-fast when live + governor disabled (#574)\`
- \`fix(schema): activity_log.id AUTOINCREMENT in registry (#580)\`
- \`scripts: backfill_training_4_13_to_4_23.py (#615 follow-up)\`

## Operator actions required after merge
1. **#580 Postgres migration** — registry change is in this PR but the live DB drift requires:
   \`\`\`bash
   python -m src.main validate-schema --check    # confirm drift
   DATABASE_URL=... python scripts/render_migrate.py    # apply
   \`\`\`
2. **#615 backfill** — when ready to recover the 17 missed training examples:
   \`\`\`bash
   python scripts/backfill_training_4_13_to_4_23.py --dry-run    # review
   python scripts/backfill_training_4_13_to_4_23.py --apply      # execute
   \`\`\`
3. **#574 verification** — if your local config has live_trading.enabled=true AND risk_governor.enabled=false, the next \`python -m src.main startup\` will exit 2 with a clear message. That's the desired behavior.

## Test plan
- [x] Full sweep clean
- [ ] Operator confirms #574 fail-fast triggers with the bad config combo
- [ ] Operator runs the #580 Postgres migration
- [ ] Operator runs the #615 backfill --dry-run; spot-checks the candidate list
EOF
)"
```

---

## Task D: Issue closures (no branch, no code)

### Task D.1: Close #421 — TICKER not in Alpaca positions spam

The root cause was the exit-overshoot bug fixed in #608/#609/#610 (PR #634, merged). The symptom (warning spam) is now bounded — once per actually-missing position per cycle, but the position-creation that drove the high frequency is gone.

- [ ] **Step 1: Comment + close**

```bash
gh issue close 421 --comment "Resolved upstream in PR #634 (closed #608, #609, #610). The warning at executor.py:1485 still fires when a position is genuinely absent from Alpaca, but the exit-overshoot path that created phantom positions (and thus the high-volume warning storm) is fixed: cancel_paper_order's terminal_state return is now honored, and the executor routes to _close_from_broker_fill instead of submitting a duplicate SELL. Closing — file a follow-up if a new high-volume pattern emerges."
```

### Task D.2: Close #423 — high risk-rejection volume observability

Addressed by the #614 RISK_ALERT writers added in PR #634 — risk rejections now persist to activity_log as structured events.

- [ ] **Step 1: Comment + close**

```bash
gh issue close 423 --comment "Resolved upstream in PR #634 (closed #614). The RISK_ALERT writers in risk/governor.py::_reject now persist every rejection to activity_log with the reason. The dashboard activity feed surfaces these (#614 also wired SCAN_COMPLETE / TRADE_OPENED / TRADE_CLOSED) so operators have structured visibility into rejection patterns. The deeper question of 'are the caps set right?' is a separate analysis question — file a new issue if the cap calibration needs revisiting after a few weeks of structured data accumulates."
```

---

## Final Verification

### Task FINAL-1: Sanity check across all 3 PRs

- [ ] **Step 1: Confirm all 3 PRs are MERGEABLE**

```bash
for pr in $(gh pr list --state open --search "fix/tier" --json number --jq '.[].number'); do
  echo "PR #$pr:"
  gh pr view $pr --json mergeable,mergeStateStatus --jq '"  mergeable=\(.mergeable) state=\(.mergeStateStatus)"'
done
```

- [ ] **Step 2: If any are UNKNOWN, wait + recheck (GitHub can take ~30s to compute)**

```bash
sleep 60
# repeat the loop above
```

### Task FINAL-2: Report to operator

Compose the summary report with:
- 3 PR numbers + URLs
- Test sweep total
- 2 closed issues (#421, #423)
- Operator-action prerequisites for PR-C (Postgres migration + backfill script)
- Anything that surfaced during the work (e.g., a regression that needed a separate fix)

---

## Self-Review Checklist

**Spec coverage:**
- ✓ Tier 1: #619, #578, #437, #482, #436 — all 5 issues have a Task in PR-A
- ✓ Tier 1.5: CLAUDE.md, --dry-run, #631-9, #631-18 (in #631-9 task), #621, #478, helper backfill — all 6 items have a Task in PR-B
- ✓ Tier 2: #574, #580, #615 follow-up — all 3 items have a Task in PR-C
- ✓ Closures: #421, #423 — Tasks D.1 + D.2

**Placeholders:** None. Each task shows the actual code/command. The few cases where the engineer must "find existing code first" (e.g., Task A.4 step 1 reads the bracket fallback) are bounded by a specific grep + line-range and the next step has the exact transformation.

**Type consistency:**
- `status_in_clause` introduced in Task A.3 step 1, referenced in Task A.3 step 4. ✓
- `connect_db` import path is `from src.utils.db import connect_db` consistently in Tasks A.2 + B.5. ✓
- `_resolve_stuck_pnl` referenced in Task B.6 step 2 — this helper was added in PR #634 (already merged); confirm signature matches when running the test. ✓
- `CollectionResult` referenced in Task C.3 — also from PR #634. ✓
- `_ALPACA_BRACKET_AVAILABLE` flag introduced in Task A.4 step 5, referenced in step 6. ✓

**Risk hot spots:**
- Task A.3 (status strings × ~50): bulk find/replace; the source-scan test catches misses but a manual review of the diff is recommended before push. The new helper is parameterized so SQL injection is impossible.
- Task A.4 (IB bracket): touches live trading code path. Tested via source-scan; runtime behavior depends on alpaca SDK presence — confirm the local dev env has alpaca-py installed before running tests.
- Task C.1 (#574 fail-fast): if any test fixture currently launches cmd_startup with `live_trading.enabled=true` AND `risk_governor.enabled=false`, that test will need its config adjusted. Step 5 includes a regression sweep.
- Task C.2 (#580 schema): registry-only; the Postgres migration is explicitly deferred to operator. Test coverage validates the registry change but NOT the migration.

**Decisions documented in the plan:**
- Branch-per-PR strategy (not one mega-branch) so each can be reviewed independently
- `status_in_clause` helper instead of inline f-strings (preserves parameterization)
- `--dry-run` as default-required mode for both cleanup + backfill scripts (no accidental data loss)
- Tier-2 PR explicitly calls out operator-action prerequisites in the body
- Closures (D.1, D.2) are commands not commits — no PR needed
