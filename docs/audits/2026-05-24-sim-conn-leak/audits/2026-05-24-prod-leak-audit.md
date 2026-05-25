# PROD Connection-Lifecycle Audit — #100 sim conn-leak fix

**Sprint:** `2026-05-24-sim-conn-leak`
**Date:** 2026-05-24
**Auditor:** Task 7 (document-only — no PROD code changes in this PR)
**Scope:** SQLite/PG connection lifecycle across PROD call sites. Identifies leak risks,
partial patterns, and clean patterns for reference. Each finding that requires code
change is filed as a separate future task per operator requirements.

---

## 1. Methodology

Files were read and grepped for `connect_db` call sites. Each site was classified by
whether the connection is guaranteed to be closed on all code paths (including exception
paths). Classification:

| Class | Meaning |
|---|---|
| **LEAK** | Connection is NOT closed on at least one exception path |
| **AMBIGUOUS** | Pattern is technically safe but lacks explicit close discipline; a future reader could misread it as a leak |
| **PARTIAL** | Connection is closed on success path but NOT on at least one exception branch |
| **CLEAN** | Connection is closed on all paths via `with` pattern or explicit try/finally with close in finally |

The `PostgresConnectionWrapper.__exit__` contract at `utils/db.py:549–555` (see §5)
underpins the CLEAN classification for all `with connect_db(...)` sites.

---

## 2. PRIMARY Findings (real leak risk)

Per requirements: **no PROD code changes in this PR.** Each PRIMARY finding becomes a
separate future task.

| File:Line | Pattern | Risk class | Future-task action |
|---|---|---|---|
| `src/shadow_trading/bracket_attach.py:126` | `conn = connect_db(db_path)` at L126; `try:` at L128 with `finally: pass` (no close); `conn.close()` at L244 OUTSIDE the try/finally. If any code between L128 and L244 raises an unhandled exception the `conn.close()` at L244 is never reached. | **LEAK on exception path** | File as **#100-followup-A**: convert to `with closing(connect_db(db_path)) as conn:` |
| `src/shadow_trading/broker_exception_logger.py:51` | `conn = connect_db(**kwargs)` at L51; `with conn:` at L52 (context-manager body executes INSERT). The `with conn:` delegates to `PostgresConnectionWrapper.__exit__` which calls `commit()` or `rollback()` AND `close()` on exit. Technically safe, but the pattern is AMBIGUOUS: the conn object is not named in a `with connect_db(...) as conn:` assignment; a future reader could mistake the outer variable reference for a bare connection that outlives the `with` block. | **AMBIGUOUS / readable as leak** | File as **#100-followup-B**: make close discipline explicit (e.g. `with connect_db(**kwargs) as conn:` — single expression) |

### 2.1 Line-number verification

Spec stated `bracket_attach.py:126` and `broker_exception_logger.py:51`. Verification
via grep confirms:

```
src/shadow_trading/bracket_attach.py:126:    conn = connect_db(db_path)
src/shadow_trading/broker_exception_logger.py:51:        conn = connect_db(**kwargs)
```

**No line drift.** Spec line numbers match current file state.

### 2.2 bracket_attach.py structure detail (L126–L244)

```python
# L125-128
client = _get_trading_client(desk=desk)
conn = connect_db(db_path)           # L126  ← bare open

try:                                 # L128
    rows = conn.execute(...)
    .fetchall()
finally:
    pass                             # L140-142 — intentional no-op comment

# ... loop over rows (L149–L242) — multiple try/except blocks
#     including conn.execute() + conn.commit() calls
#     exceptions caught per-ticker but any uncaught exception
#     would bypass the close below

conn.close()                         # L244  ← OUTSIDE try/finally
```

The `finally: pass` block exists but is explicitly inert (comment says "per-action
commits below; close at the very end"). Any exception escaping the outer try (e.g.
from the loop body, from a missing DB table, or from a future refactor) will bypass
`conn.close()` at L244.

### 2.3 broker_exception_logger.py structure detail (L51–L66)

```python
# L49-71
try:
    kwargs = {} if db_path is None else {"db_path": db_path}
    conn = connect_db(**kwargs)      # L51 ← bare open
    with conn:                       # L52 ← delegates to __exit__
        conn.execute(INSERT ...)     # L53
except Exception as insert_err:
    logger.critical(...)
```

The `with conn:` block at L52 invokes `PostgresConnectionWrapper.__exit__`, which
calls `rollback()` (on exception) or `commit()` (on success) and then `close()`.
This is technically safe. The AMBIGUOUS classification reflects that the variable
`conn` is assigned separately from the `with` statement, making the close discipline
implicit rather than stated. The preferred form is `with connect_db(**kwargs) as conn:`.

---

## 3. SECONDARY Findings (partial coverage)

| File:Line | Pattern | Status |
|---|---|---|
| `src/scheduler/watch.py:1495` (`_check_row_counts`) | Bare conn + manual `close()` on success path only. See detail below. | **PARTIAL** — Add to **#100-followup-C** (P3, batch with watch.py audit) |

### 3.1 watch.py:1495 structure detail

```python
# L1491-1507
@staticmethod
def _check_row_counts():
    try:
        conn = connect_db(DB_PATH)          # L1495 ← bare open
        row = conn.execute("SELECT ...").fetchone()
        count = _scalar(row)
        conn.close()                        # L1498 ← close on SUCCESS path only
        if count == 0:
            ...
    except Exception as exc:
        logger.warning("[DB] Row count check failed: %s", exc)
        # ← NO conn.close() in except branch; conn silently leaks
```

If `conn.execute()` raises (e.g. table missing, DB locked), control goes to the
`except` branch with no `conn.close()` call. The connection leaks silently. The
outer `except` swallows the error so no stack trace surfaces — this is a
particularly stealthy leak pattern.

**Severity note:** `_check_row_counts` is a periodic PROD diagnostic, not a
high-frequency trading path, so the leak is low-frequency. Filed P3.

---

## 4. CLEAN Findings

### 4.1 With-pattern bucket (sampled)

The following files were sampled and found clean. All sites use the `with connect_db(...):`
or `with connect_db(...) as conn:` idiom, relying on `PostgresConnectionWrapper.__exit__`
(see §5) to guarantee commit/rollback + close on all paths.

| File | Sites | Status |
|---|---|---|
| `src/shadow_trading/reconcile.py` | 14 sites | CLEAN — all `with connect_db(...)` |
| `src/shadow_trading/executor.py` | 10 sites | CLEAN — all `with connect_db(...)` |
| `src/journal/store.py` | 17 sites | CLEAN — all `with connect_db(...)` |
| `src/council/*` | all sites | CLEAN — all `with` pattern |
| `src/scheduler/watch.py` `_run_scan` sites | multiple | CLEAN — all `with` pattern |

**Sampling caveat:** this bucket was sampled, not exhaustively traced. See §6.

### 4.2 Bare-conn-with-try/finally bucket (enumerated)

The following sites use a bare `conn = connect_db(...)` assignment but are CLEAN
because `conn.close()` (or equivalent) appears in the `finally` block, guaranteeing
execution on all paths:

| File:Line | Pattern | Status |
|---|---|---|
| `src/capability_registration.py:40` | bare open + try/finally with close | CLEAN |
| `src/state.py:46` | bare open + try/finally with close | CLEAN |
| `src/reconcile_state.py:34` | bare open + try/finally with close | CLEAN |
| `src/exit_reconciliation.py:307` | bare open + try/finally with close | CLEAN |
| `src/scheduler/watch.py:2663` (walkforward helper) | bare open + try/finally with close | CLEAN |
| `src/scheduler/watch.py:2701` (walkforward helper) | bare open + try/finally with close | CLEAN |
| `src/scheduler/watch.py:2743` (walkforward helper) | bare open + try/finally with close | CLEAN |

---

## 5. Coverage Gap (disclosed)

The with-pattern bucket in §4.1 is **sampled, not exhaustively traced**. The CLEAN
classification for those sites relies entirely on `PostgresConnectionWrapper.__exit__`
at `utils/db.py:549–555`.

```python
# utils/db.py L546-L555  (verified current; spec stated L549-L555 — minor offset)
def __enter__(self):
    return self

def __exit__(self, exc_type, exc_val, exc_tb):
    if exc_type is None:
        self.commit()
    else:
        self.rollback()
    self.close()
    return False
```

Contract: `__exit__` unconditionally calls `self.close()` on both success and exception
paths. `return False` propagates exceptions to the caller (does not suppress).

**If a future change weakens this contract** (e.g. swallows the close on certain
exception types, or adds an early-return before `self.close()`), the sampling
assumption in §4.1 no longer holds and all sampled sites would need re-verification.

The coverage gap is **acceptable for this PR** because the with-pattern is the
preferred, blessed idiom in this codebase and `__exit__` is a stable, well-tested
contract. This disclosure exists to prevent a future refactor from silently
invalidating the §4.1 CLEAN classifications.

---

## 6. Summary

| Class | Count | Files |
|---|---|---|
| LEAK | 1 | `bracket_attach.py:126` |
| AMBIGUOUS | 1 | `broker_exception_logger.py:51` |
| PARTIAL | 1 | `watch.py:1495` |
| CLEAN (with-pattern, sampled) | 5 files | reconcile.py, executor.py, store.py, council/*, watch.py _run_scan |
| CLEAN (bare-conn + try/finally, enumerated) | 7 sites | capability_registration.py, state.py, reconcile_state.py, exit_reconciliation.py, watch.py ×3 |

### Follow-up tasks

| Task | File:Line | Priority | Action |
|---|---|---|---|
| #100-followup-A | `bracket_attach.py:126` | P2 | Convert to `with closing(connect_db(db_path)) as conn:` |
| #100-followup-B | `broker_exception_logger.py:51` | P2 | Make close discipline explicit (`with connect_db(**kwargs) as conn:`) |
| #100-followup-C | `watch.py:1495` | P3 | Add `conn.close()` in except branch (or convert to with-pattern); batch with watch.py audit |

---

## 7. Audit scope exclusions

- `src/simulation/lifecycle/` — sim harness. Covered by the #100 fix itself (7 cursor
  sites + Oracle.assert_all() rollback). Not PROD.
- `src/tools/` — tools layer. Uses its own `_db.py` adapter, not `utils/db.connect_db`
  directly. Audited separately in #106.
- Test files — not PROD; excluded.
